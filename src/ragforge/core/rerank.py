"""Pinned, local ONNX cross-encoder. Ranking scores are not probabilities."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from ragforge.artifacts.manifest import FileRecord
from ragforge.core.embedding import file_hash
from ragforge.core.source import is_link
from ragforge.types import ContractModel


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
    def __init__(self, directory: Path, *, threads: int = 4) -> None:
        self.spec = reranker_spec(directory)
        if type(threads) is not int or not 1 <= threads <= 32:
            raise ValueError("CPU threads must be between 1 and 32")
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
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.use_deterministic_compute = True
        # No model filesystem base: an external-weight graph cannot read local files.
        self.session = ort.InferenceSession(
            (directory / "model.onnx").read_bytes(),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
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

    def score(self, query: str, passages: list[str]) -> list[float]:
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
            for start in range(0, len(passages), batch_size):
                encodings = self.tokenizer.encode_batch(
                    [(query, passage) for passage in passages[start : start + batch_size]]
                )
                values = {
                    "input_ids": np.asarray([e.ids for e in encodings], dtype=np.int64),
                    "attention_mask": np.asarray(
                        [e.attention_mask for e in encodings], dtype=np.int64
                    ),
                    "token_type_ids": np.asarray([e.type_ids for e in encodings], dtype=np.int64),
                }
                logits = np.asarray(self.session.run(None, {k: values[k] for k in self.inputs})[0])
                if logits.shape != (len(encodings), 1) or not np.isfinite(logits).all():
                    raise ValueError("invalid reranker logits")
                result.extend(float(v) for v in logits[:, 0])
            return result
        finally:
            self.tokenizer.no_truncation()
