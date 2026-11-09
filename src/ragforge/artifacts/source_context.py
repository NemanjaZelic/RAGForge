"""Build a corpus-only catalogue or attach it to a new portable bundle."""

import os
import shutil
import tempfile
from pathlib import Path

from ragforge.artifacts.builder import publish_new
from ragforge.artifacts.manifest import BundleManifest, FileRecord
from ragforge.artifacts.verification import build_identity, verify_bundle
from ragforge.core.definitions import build_catalogue, verify_catalogue
from ragforge.core.embedding import file_hash
from ragforge.core.source import is_link
from ragforge.core.sqlite import SQLiteEngine
from ragforge.jobs.budget import StorageBudget


def build_source_context(
    artifact: Path, output: Path, *, storage: StorageBudget | None = None
) -> dict[str, int | bool | str]:
    if output.resolve().is_relative_to(artifact.resolve()):
        raise ValueError("catalogue output must be outside the immutable base bundle")
    manifest = verify_bundle(artifact)
    collection = manifest.collections[0]
    checksum = next(r.sha256 for r in manifest.files if r.path == collection.database_path)
    index = SQLiteEngine(artifact / collection.database_path)
    counts = build_catalogue(index, output, checksum, collection.collection_id, storage=storage)
    verify_catalogue(output, index, checksum, collection.collection_id)
    return {**counts, "sha256": file_hash(output), "source_index_sha256": checksum}


def attach_source_context(
    artifact: Path,
    catalogue: Path,
    output: Path,
    *,
    storage: StorageBudget | None = None,
) -> BundleManifest:
    """Publish a new immutable version; never alter or re-embed the base bundle."""
    manifest = verify_bundle(artifact)
    if manifest.source_context is not None:
        raise ValueError("bundle already contains source context")
    collection = manifest.collections[0]
    checksum = next(r.sha256 for r in manifest.files if r.path == collection.database_path)
    verify_catalogue(
        catalogue,
        SQLiteEngine(artifact / collection.database_path),
        checksum,
        collection.collection_id,
    )
    output = output.absolute()
    if output.resolve().is_relative_to(artifact.resolve()) or artifact.resolve().is_relative_to(
        output.resolve()
    ):
        raise ValueError("new bundle must be separate from the base bundle")
    if os.path.lexists(output):
        raise FileExistsError("source-context bundle output must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.resolve(strict=True)
    output = parent / output.name
    if storage:
        if not output.resolve().is_relative_to(storage.root):
            raise ValueError("source-context bundle must remain inside storage budget")
        storage.check(
            sum(r.size_bytes for r in manifest.files) + catalogue.stat().st_size + 32 * 1024**2,
            refresh=True,
        )
    stage = Path(tempfile.mkdtemp(prefix=".ragforge-stage-", dir=parent)).resolve()
    try:
        for record in manifest.files:
            destination = stage / record.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(artifact / record.path, destination)
            if storage:
                storage.account(record.size_bytes)
        relative = f"collections/{collection.collection_id}/source-context.sqlite"
        destination = stage / relative
        shutil.copyfile(catalogue, destination)
        if storage:
            storage.account(destination.stat().st_size)
        manifest.source_context = relative
        manifest.files.append(
            FileRecord(
                path=relative, sha256=file_hash(destination), size_bytes=destination.stat().st_size
            )
        )
        manifest.files.sort(key=lambda r: r.path)
        manifest.build_id = build_identity(manifest)
        (stage / "manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        verified = verify_bundle(stage)
        if storage:
            storage.check(refresh=True)
        publish_new(stage, output)
        return verified
    finally:
        if stage.exists():
            if (
                stage.resolve().parent != parent
                or is_link(stage.lstat())
                or not stage.name.startswith(".ragforge-stage-")
            ):
                raise ValueError("unsafe staging cleanup target")
            shutil.rmtree(stage)
