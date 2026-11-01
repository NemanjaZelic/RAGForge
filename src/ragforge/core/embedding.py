"""Pinned local ONNX embedding packages. No hub client or downloader in inference."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from ragforge.artifacts.manifest import FileRecord
from ragforge.core.source import is_link
from ragforge.types import ContractModel

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    FloatMatrix = NDArray[np.float32]


class ModelSpec(ContractModel):
    model_schema_version: Literal["1"] = "1"
    model_id: Annotated[str, Field(min_length=1)]
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    dimensions: Annotated[int, Field(ge=1, le=4096)]
    max_tokens: Annotated[int, Field(ge=4, le=512)]
    pooling: Literal["mean"] = "mean"
    normalized: Literal[True] = True
    query_prefix: str = ""
    document_prefix: str = ""
    pad_token: Annotated[str, Field(min_length=1)]
    license: Annotated[str, Field(min_length=1)]
    source_url: str
    license_url: str
    files: Annotated[list[FileRecord], Field(min_length=3)]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def model_spec(directory: Path, *, verify: bool = True) -> ModelSpec:
    if is_link(directory.lstat()) or not directory.is_dir():
        raise ValueError("model directory must not be a link")
    descriptor = directory / "model.json"
    if is_link(descriptor.lstat()) or descriptor.stat().st_size > 1024 * 1024:
        raise ValueError("invalid or oversized model descriptor")
    spec = ModelSpec.model_validate_json(descriptor.read_text(encoding="utf-8"))
    if (
        any(record.size_bytes > 256 * 1024 * 1024 for record in spec.files)
        or sum(record.size_bytes for record in spec.files) > 512 * 1024 * 1024
    ):
        raise ValueError("model package exceeds supported asset byte limits")
    paths = [str(record.path) for record in spec.files]
    if len({path.casefold() for path in paths}) != len(paths):
        raise ValueError("duplicate model file path")
    if not {"model.onnx", "tokenizer.json", "LICENSE"} <= set(paths):
        raise ValueError("model package lacks graph/tokenizer/license")
    if "model.json" in paths:
        raise ValueError("model descriptor cannot inventory itself")
    actual: set[str] = set()
    all_names: set[str] = set()
    entry_count = 0
    for parent, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            entry_count += 1
            if entry_count > 10000:
                raise ValueError("model package exceeds 10000 entries")
            path = Path(parent) / name
            key = path.relative_to(directory).as_posix().casefold()
            if key in all_names:
                raise ValueError("case collision in model package")
            all_names.add(key)
            if is_link(path.lstat()):
                raise ValueError("links are forbidden in model package")
            if name in files and not path.is_file():
                raise ValueError("model assets must be regular files")
        for name in files:
            actual.add((Path(parent) / name).relative_to(directory).as_posix())
    if actual != set(paths) | {"model.json"}:
        raise ValueError("unexpected or missing model package file")
    if verify:
        for record in spec.files:
            path = directory / record.path
            if path.stat().st_size != record.size_bytes or file_hash(path) != record.sha256:
                raise ValueError(f"model file checksum mismatch: {record.path}")
    return spec


class ONNXEmbedder:
    """CPU-only, mean pooling and L2 normalization; lazy optional dependencies."""

    def __init__(self, directory: Path, *, threads: int = 4) -> None:
        self.spec = model_spec(directory)
        if type(threads) is not int or not 1 <= threads <= 32:
            raise ValueError("CPU threads must be between 1 and 32")
        try:
            import onnxruntime as ort  # type: ignore[import-untyped]
            from tokenizers import Tokenizer
        except ImportError as error:
            raise ValueError("balanced inference requires ragforge[balanced]") from error
        ort.disable_telemetry_events()
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        pad_id = self.tokenizer.token_to_id(self.spec.pad_token)
        if pad_id is None:
            raise ValueError("model pad token is not in the local tokenizer")
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token=self.spec.pad_token)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.use_deterministic_compute = True
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        graph = directory / "model.onnx"
        if graph.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("ONNX graph exceeds the supported 256 MiB limit")
        # Byte loading supplies no model filesystem base for external weight files.
        try:
            self.session = ort.InferenceSession(
                graph.read_bytes(),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        except Exception as error:
            raise ValueError(f"cannot load local ONNX graph: {error}") from error
        inputs = {item.name for item in self.session.get_inputs()}
        if not {"input_ids", "attention_mask"} <= inputs or not inputs <= {
            "input_ids",
            "attention_mask",
            "token_type_ids",
        }:
            raise ValueError("unsupported ONNX embedding graph inputs")
        self.inputs = inputs
        output = self.session.get_outputs()[0]
        if len(output.shape) != 3 or output.shape[-1] != self.spec.dimensions:
            raise ValueError("graph must expose per-token embeddings with expected dimensions")

    def encode(self, texts: list[str], *, query: bool = False) -> FloatMatrix:
        import numpy as np

        if not texts or len(texts) > 32 or any(not text.strip() for text in texts):
            raise ValueError("embedding batch must contain 1-32 nonblank texts")
        prefix = self.spec.query_prefix if query else self.spec.document_prefix
        encodings = self.tokenizer.encode_batch([prefix + text for text in texts])
        if any(len(item.ids) > self.spec.max_tokens for item in encodings):
            raise ValueError(
                "model token limit exceeded; reduce chunk size/query; no silent truncation"
            )
        inputs = {
            "input_ids": np.asarray([item.ids for item in encodings], dtype=np.int64),
            "attention_mask": np.asarray(
                [item.attention_mask for item in encodings], dtype=np.int64
            ),
            "token_type_ids": np.asarray([item.type_ids for item in encodings], dtype=np.int64),
        }
        hidden = np.asarray(
            self.session.run(None, {key: inputs[key] for key in self.inputs})[0], dtype=np.float32
        )
        if hidden.shape != (len(texts), len(encodings[0].ids), self.spec.dimensions):
            raise ValueError("unexpected ONNX output shape")
        mask = inputs["attention_mask"].astype(np.float32)[..., None]
        vectors = (hidden * mask).sum(axis=1) / mask.sum(axis=1)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.isfinite(vectors).all() or not (norms > 0).all():
            raise ValueError("invalid model embeddings")
        return np.asarray(vectors / norms, dtype=np.float32)
