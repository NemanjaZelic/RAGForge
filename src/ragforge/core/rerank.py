"""Pinned, local ONNX cross-encoder. Ranking scores are not probabilities."""

from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock, RLock
from typing import TYPE_CHECKING, Annotated, Literal, Protocol

from pydantic import Field

from ragforge.artifacts.manifest import FileRecord
from ragforge.core.embedding import file_hash
from ragforge.core.source import is_link
from ragforge.types import ContractModel

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


class _ScoringSession(Protocol):
    def run(
        self, outputs: None, values: dict[str, NDArray[np.int64]]
    ) -> list[NDArray[np.float32]]: ...


class RerankerSpec(ContractModel):
    model_schema_version: Literal["1"] = "1"
    model_id: Annotated[str, Field(min_length=1)]
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    max_tokens: Annotated[int, Field(ge=16, le=512)] = 512
    pad_token: str = "[PAD]"
    batch_size: Annotated[int, Field(ge=1, le=8)] = 8
    license: Annotated[str, Field(min_length=1)]
    source_url: str
    files: Annotated[list[FileRecord], Field(min_length=3)]


def reranker_spec(directory: Path) -> RerankerSpec:
    if is_link(directory.lstat()) or not directory.is_dir():
        raise ValueError("reranker directory must not be a link")
    descriptor = directory / "reranker.json"
    if is_link(descriptor.lstat()) or descriptor.stat().st_size > 1024**2:
        raise ValueError("invalid reranker descriptor")
    spec = RerankerSpec.model_validate_json(descriptor.read_text(encoding="utf-8"))
    paths = [str(record.path) for record in spec.files]
    if len({p.casefold() for p in paths}) != len(paths):
        raise ValueError("duplicate reranker asset path")
    if not {"model.onnx", "tokenizer.json", "LICENSE"} <= set(paths):
        raise ValueError("reranker lacks graph/tokenizer/license")
    if "reranker.json" in paths or any(r.size_bytes > 384 * 1024**2 for r in spec.files):
        raise ValueError("invalid reranker inventory/asset limit")
    if sum(r.size_bytes for r in spec.files) > 512 * 1024**2:
        raise ValueError("reranker package exceeds asset byte limit")
    actual = set()
    names: set[str] = set()
    for parent, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            path = Path(parent) / name
            key = path.relative_to(directory).as_posix().casefold()
            if key in names or len(names) >= 10000 or is_link(path.lstat()):
                raise ValueError("unsafe reranker entry")
            names.add(key)
            if name in files:
                if not path.is_file():
                    raise ValueError("reranker assets must be regular files")
                actual.add(path.relative_to(directory).as_posix())
    if actual != set(paths) | {"reranker.json"}:
        raise ValueError("unexpected or missing reranker asset")
    for record in spec.files:
        path = directory / record.path
        if path.stat().st_size != record.size_bytes or file_hash(path) != record.sha256:
            raise ValueError("reranker asset checksum mismatch")
    return spec


class ONNXReranker:
    def __init__(
        self, directory: Path, *, threads: int = 4, workers: int = 4, cache_batches: int = 512
    ) -> None:
        self.spec = reranker_spec(directory)
        if type(threads) is not int or not 1 <= threads <= 32:
            raise ValueError("CPU threads must be between 1 and 32")
        if type(workers) is not int or not 1 <= workers <= 8:
            raise ValueError("reranker workers must be between 1 and 8")
        if type(cache_batches) is not int or not 0 <= cache_batches <= 4096:
            raise ValueError("reranker cache batches must be between 0 and 4096")
        self.cache_batches = cache_batches
        self._score_lock = RLock()
        self._cache_lock = Lock()
        self._batch_cache: OrderedDict[bytes, tuple[float, ...]] = OrderedDict()
        self._inflight: dict[bytes, Future[tuple[float, ...]]] = {}
        self._cache_hits = self._cache_misses = 0
        # One shared session, a bounded total CPU budget, identical model batches.
        self.workers = min(workers, threads)
        import onnxruntime as ort  # type: ignore[import-untyped]
        from tokenizers import Tokenizer

        ort.disable_telemetry_events()
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        pad_id = self.tokenizer.token_to_id(self.spec.pad_token)
        if pad_id is None:
            raise ValueError("reranker pad token missing")
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token=self.spec.pad_token)
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, threads // self.workers)
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.use_deterministic_compute = True
        # No model filesystem base: an external-weight graph cannot read local files.
        graph = (directory / "model.onnx").read_bytes()
        self.session = ort.InferenceSession(
            graph,
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._cache_session = self.session
        self.inputs = {item.name for item in self.session.get_inputs()}
        if not {"input_ids", "attention_mask"} <= self.inputs or not self.inputs <= {
            "input_ids",
            "attention_mask",
            "token_type_ids",
        }:
            raise ValueError("unsupported reranker graph inputs")
        outputs = self.session.get_outputs()
        if len(outputs) != 1 or len(outputs[0].shape) != 2 or outputs[0].shape[-1] != 1:
            raise ValueError("reranker must expose one logit per pair")

        self.execution_optimization = "original"
        from ragforge.core.signed_weights import prepare_signed_weights

        try:
            prepared = prepare_signed_weights(graph)
            if prepared is not None:
                candidate = ort.InferenceSession(
                    prepared.content, sess_options=options, providers=["CPUExecutionProvider"]
                )
                if self._same_initial_scores(candidate):
                    self.session = candidate
                    self._cache_session = candidate
                    self.execution_optimization = "vnni-signed-weights"
        except Exception:
            # Optional execution tuning must never replace the original model
            # on unsupported kernels, parser errors or failed startup checks.
            self.execution_optimization = "original"

    def _same_initial_scores(self, candidate: _ScoringSession) -> bool:
        import numpy as np

        # Neutral startup probes, never user documents or answers. Include a
        # short and a long dynamic shape before selecting the derived session.
        for repeats in (1, self.spec.max_tokens):
            self.tokenizer.enable_truncation(
                max_length=self.spec.max_tokens, strategy="only_second"
            )
            try:
                encoded = self.tokenizer.encode_batch(
                    [
                        ("warmup", "warmup token " * repeats),
                        ("warmup", "transaction retry source " * repeats),
                    ]
                )
            finally:
                self.tokenizer.no_truncation()
            arrays = {
                "input_ids": np.asarray([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.asarray([e.attention_mask for e in encoded], dtype=np.int64),
                "token_type_ids": np.asarray([e.type_ids for e in encoded], dtype=np.int64),
            }
            values = {name: arrays[name] for name in self.inputs}
            original = self.session.run(None, values)[0]
            optimized = candidate.run(None, values)[0]
            if not np.isfinite(original).all() or not np.array_equal(original, optimized):
                return False
        return True

    def cache_info(self) -> dict[str, int]:
        with self._cache_lock:
            return {
                "capacity": self.cache_batches,
                "entries": len(self._batch_cache),
                "hits": self._cache_hits,
                "misses": self._cache_misses,
            }

    def _infer_batch(self, values: dict[str, NDArray[np.int64]]) -> list[float]:
        import numpy as np

        def compute() -> tuple[float, ...]:
            logits = np.asarray(self._cache_session.run(None, values)[0])
            if logits.shape != (len(values["input_ids"]), 1) or not np.isfinite(logits).all():
                raise ValueError("invalid reranker logits")
            return tuple(float(v) for v in logits[:, 0])

        if self.cache_batches == 0:
            with self._cache_lock:
                self._cache_misses += 1
            return list(compute())
        digest = hashlib.sha256()
        for name, value in sorted(values.items()):
            digest.update(
                (name + "\0" + value.dtype.str + "\0" + repr(value.shape) + "\0").encode()
            )
            digest.update(value.tobytes(order="C"))
        key = digest.digest()
        with self._cache_lock:
            cached = self._batch_cache.get(key)
            if cached is not None:
                self._batch_cache.move_to_end(key)
                self._cache_hits += 1
                return list(cached)
            future = self._inflight.get(key)
            owner = future is None
            if owner:
                future = Future()
                self._inflight[key] = future
                self._cache_misses += 1
            else:
                self._cache_hits += 1
        assert future is not None
        if not owner:
            return list(future.result())
        try:
            scores = compute()
        except BaseException as error:
            with self._cache_lock:
                self._inflight.pop(key)
                future.set_exception(error)
            raise
        with self._cache_lock:
            self._batch_cache[key] = scores
            self._batch_cache.move_to_end(key)
            while len(self._batch_cache) > self.cache_batches:
                self._batch_cache.popitem(last=False)
            self._inflight.pop(key)
            future.set_result(scores)
        return list(scores)

    def score(self, query: str, passages: list[str]) -> list[float]:
        # The tokenizer is mutable. Serialize separate public calls while keeping
        # independent, already-tokenized batches parallel inside each call.
        with self._score_lock:
            with self._cache_lock:
                if self._cache_session is not self.session:
                    self._batch_cache.clear()
                    self._cache_session = self.session
            return self._score(query, passages)

    def _score(self, query: str, passages: list[str]) -> list[float]:
        import numpy as np

        if (
            not query.strip()
            or len(query) > 8192
            or not 1 <= len(passages) <= 400
            or any(not passage.strip() or len(passage) > 128000 for passage in passages)
        ):
            raise ValueError("invalid reranker query/passages")
        if len(self.tokenizer.encode(query).ids) > self.spec.max_tokens - 16:
            raise ValueError("query leaves insufficient reranker passage budget")
        # Reranking only: explicitly truncate the passage, never the returned source.
        # Candidate extraction preserves the full query; document embeddings remain strict.
        self.tokenizer.enable_truncation(max_length=self.spec.max_tokens, strategy="only_second")
        try:
            result: list[float] = []
            batch_size = self.spec.batch_size

            def inputs() -> Iterator[dict[str, NDArray[np.int64]]]:
                # Tokenization stays on the caller thread. Inference workers see only
                # immutable arrays, with the exact original batch membership/padding.
                for start in range(0, len(passages), batch_size):
                    encodings = self.tokenizer.encode_batch(
                        [(query, passage) for passage in passages[start : start + batch_size]]
                    )
                    values = {
                        "input_ids": np.asarray([e.ids for e in encodings], dtype=np.int64),
                        "attention_mask": np.asarray(
                            [e.attention_mask for e in encodings], dtype=np.int64
                        ),
                        "token_type_ids": np.asarray(
                            [e.type_ids for e in encodings], dtype=np.int64
                        ),
                    }
                    yield {key: values[key] for key in self.inputs}

            if self.workers == 1 or len(passages) <= batch_size:
                for values in inputs():
                    result.extend(self._infer_batch(values))
            else:
                pool = ThreadPoolExecutor(max_workers=self.workers)
                try:
                    # map restores input order even when later batches finish first.
                    for scores in pool.map(self._infer_batch, inputs()):
                        result.extend(scores)
                finally:
                    pool.shutdown(wait=True, cancel_futures=True)
            return result
        finally:
            self.tokenizer.no_truncation()
