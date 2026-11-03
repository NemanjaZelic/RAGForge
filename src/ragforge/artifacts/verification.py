"""Bundle path, inventory and content verification before opening runtime data."""

import ast
import json
import os
import struct
from pathlib import Path

from pydantic import TypeAdapter

from ragforge.artifacts.manifest import BundleManifest
from ragforge.core.embedding import file_hash, model_spec
from ragforge.core.limits import (
    MAX_BUNDLE_FILE_BYTES,
    MAX_BUNDLE_TOTAL_BYTES,
    MAX_DENSE_ROWS,
)
from ragforge.core.source import is_link
from ragforge.core.sqlite import SQLiteEngine
from ragforge.types import RelativePath

_PATH = TypeAdapter(RelativePath)


def build_identity(manifest: BundleManifest) -> str:
    import hashlib

    data = manifest.model_dump(mode="json", exclude={"build_id"})
    if data.get("retrieval_configuration") is None:
        data.pop("retrieval_configuration", None)  # Preserve identities of earlier v1 bundles.
    for collection_data in data["collections"]:
        dense_data = collection_data.get("dense_index")
        if dense_data is not None and dense_data.get("source_chunks") is None:
            dense_data.pop("source_chunks", None)
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def bundle_files(root: Path) -> dict[str, Path]:
    if is_link(root.lstat()) or not root.is_dir():
        raise ValueError("bundle root must be a real directory")
    files: dict[str, Path] = {}
    names: set[str] = set()
    directories: set[str] = set()
    entries = 0
    for parent, dirs, leaves in os.walk(root, followlinks=False):
        for name in dirs + leaves:
            entries += 1
            if entries > 10000:
                raise ValueError("bundle inventory exceeds 10000 entries")
            path = Path(parent) / name
            relative = _PATH.validate_python(path.relative_to(root).as_posix())
            if is_link(path.lstat()) or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("bundle links/escapes are forbidden")
            key = relative.casefold()
            if key in names:
                raise ValueError("case collision in bundle")
            names.add(key)
        directories.update((Path(parent) / name).relative_to(root).as_posix() for name in dirs)
        for name in leaves:
            path = Path(parent) / name
            if not path.is_file():
                raise ValueError("bundle entry must be a regular file")
            files[path.relative_to(root).as_posix()] = path
    prefixes = {
        "/".join(path.split("/")[:index])
        for path in files
        for index in range(1, len(path.split("/")))
    }
    if directories != prefixes:
        raise ValueError("unexpected empty bundle directory")
    return files


def verify_bundle(root: Path) -> BundleManifest:
    files = bundle_files(root)
    descriptor = files.get("manifest.json")
    if descriptor is None or descriptor.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("missing or oversized bundle manifest")
    manifest = BundleManifest.model_validate_json(descriptor.read_text(encoding="utf-8"))
    if manifest.build_id != build_identity(manifest):
        raise ValueError("bundle build identity mismatch")
    inventory = {record.path: record for record in manifest.files}
    if set(files) != set(inventory) | {"manifest.json"}:
        raise ValueError("unexpected or missing bundle file")
    collection = manifest.collections[0]
    required = {collection.database_path}
    if manifest.profile == "balanced":
        assert collection.dense_index is not None and manifest.query_model is not None
        required.add(collection.dense_index.path)
        if collection.dense_index.source_chunks is not None:
            required.add(collection.dense_index.source_chunks.database_path)
        required.update(manifest.query_model.files)
    if manifest.retrieval_configuration is not None:
        required.update(manifest.retrieval_configuration.reranker.files)
    if set(inventory) != required:
        raise ValueError("inventory contains files outside declared runtime components")
    total = 0
    for record in manifest.files:
        path = files[record.path]
        size = path.stat().st_size
        total += size
        if size > MAX_BUNDLE_FILE_BYTES or total > MAX_BUNDLE_TOTAL_BYTES:
            raise ValueError("bundle exceeds supported verification byte limits")
        if size != record.size_bytes or file_hash(path) != record.sha256:
            raise ValueError(f"bundle checksum mismatch: {record.path}")
    engine = SQLiteEngine(root / collection.database_path)
    with engine._connect() as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("SQLite quick_check failed")
        actual = [
            dict(row)
            for row in connection.execute(
                "SELECT document_id,source_path,content_sha256 FROM documents ORDER BY source_path"
            )
        ]
        expected = [
            doc.model_dump() for doc in sorted(collection.documents, key=lambda d: d.source_path)
        ]
        if actual != expected:
            raise ValueError("SQLite document inventory does not match manifest")
        if engine.list_collections()[0].collection_id != collection.collection_id:
            raise ValueError("SQLite collection does not match manifest")
    if manifest.profile == "balanced":
        from ragforge.core.dense import BACKEND, BACKEND_VERSION

        dense = collection.dense_index
        assert dense is not None
        from ragforge.core.ann import BACKEND as ANN_BACKEND
        from ragforge.core.ann import BACKEND_VERSION as ANN_VERSION
        from ragforge.core.ann import read_header

        dense_engine = engine
        if dense.source_chunks is not None:
            from ragforge.core.parents import ParentMapper

            dense_engine = SQLiteEngine(root / dense.source_chunks.database_path)
            with dense_engine._connect() as connection:
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("dense source SQLite quick_check failed")
            ParentMapper(dense_engine, engine)  # Includes exact source inventory equality.
        with dense_engine._connect() as connection:
            rows = int(connection.execute("SELECT count(*) FROM chunks").fetchone()[0])
        if dense.metric != "cosine":
            raise ValueError("unsupported dense metric")
        if (dense.backend, dense.backend_version) == (ANN_BACKEND, ANN_VERSION):
            read_header(root / dense.path, rows=rows, dimensions=dense.dimensions)
        elif (dense.backend, dense.backend_version) == (BACKEND, BACKEND_VERSION):
            with (root / dense.path).open("rb") as stream:
                if stream.read(8) != b"\x93NUMPY\x01\x00":
                    raise ValueError("unsupported dense file version")
                length_bytes = stream.read(2)
                if len(length_bytes) != 2:
                    raise ValueError("truncated dense header")
                length = struct.unpack("<H", length_bytes)[0]
                if length > 4096:
                    raise ValueError("oversized dense header")
                try:
                    header = ast.literal_eval(stream.read(length).decode("ascii").strip())
                except (SyntaxError, UnicodeError, ValueError) as error:
                    raise ValueError("invalid dense header") from error
                expected_header = {
                    "descr": "<f4",
                    "fortran_order": False,
                    "shape": (rows, dense.dimensions),
                }
                if header != expected_header or not 1 <= rows <= MAX_DENSE_ROWS:
                    raise ValueError("dense header does not match SQLite/model")
                if (root / dense.path).stat().st_size != 10 + length + rows * dense.dimensions * 4:
                    raise ValueError("dense byte size does not match header")
        else:
            raise ValueError("unsupported dense backend/version/metric")
        assert manifest.query_model is not None
        spec = model_spec(root / "models/query", verify=False)
        model = manifest.query_model
        paths = {"models/query/" + record.path for record in spec.files} | {
            "models/query/model.json"
        }
        if paths != set(model.files):
            raise ValueError("query model inventory does not match descriptor")
        if (model.model_id, model.revision, model.dimensions, model.license) != (
            spec.model_id,
            spec.revision,
            spec.dimensions,
            spec.license,
        ):
            raise ValueError("query model identity/dimensions/license do not match")
    if manifest.retrieval_configuration is not None:
        from ragforge.core.rerank import reranker_spec

        reranker = manifest.retrieval_configuration.reranker
        spec_r = reranker_spec(root / "models/reranker")
        expected_r = {"models/reranker/" + str(r.path) for r in spec_r.files} | {
            "models/reranker/reranker.json"
        }
        if expected_r != set(reranker.files) or (
            reranker.model_id,
            reranker.revision,
            reranker.license,
        ) != (spec_r.model_id, spec_r.revision, spec_r.license):
            raise ValueError("reranker identity/inventory does not match descriptor")
    return manifest
