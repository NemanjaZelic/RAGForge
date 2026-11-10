"""Create a verified reranked bundle version without re-embedding its index."""

import os
import shutil
import tempfile
from pathlib import Path

from ragforge.artifacts.builder import publish_new
from ragforge.artifacts.manifest import (
    BundleManifest,
    FileRecord,
    RerankerModel,
    RetrievalConfiguration,
)
from ragforge.artifacts.verification import build_identity, verify_bundle
from ragforge.core.embedding import file_hash
from ragforge.core.rerank import reranker_spec
from ragforge.core.source import is_link
from ragforge.jobs.budget import StorageBudget


def enhance_bundle(
    artifact: Path,
    output: Path,
    reranker_directory: Path,
    *,
    candidates: int = 100,
    max_chunks_per_document: int | None = None,
    storage: StorageBudget | None = None,
) -> BundleManifest:
    manifest = verify_bundle(artifact)
    if manifest.retrieval_configuration is not None:
        raise ValueError("bundle already contains a reranker; start from its original base version")
    spec = reranker_spec(reranker_directory)
    model_paths = [str(record.path) for record in spec.files] + ["reranker.json"]
    configuration = RetrievalConfiguration(
        candidates_per_method=candidates,
        max_chunks_per_document=max_chunks_per_document,
        reranker=RerankerModel(
            model_id=spec.model_id,
            runtime=spec.runtime,
            revision=spec.revision,
            license=spec.license,
            files=["models/reranker/" + p for p in sorted(model_paths)],
        ),
    )
    output = output.absolute()
    if output.resolve().is_relative_to(artifact.resolve()) or artifact.resolve().is_relative_to(
        output.resolve()
    ):
        raise ValueError("new bundle must be separate from the base bundle")
    if os.path.lexists(output):
        raise FileExistsError("enhanced bundle output must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.resolve(strict=True)
    output = parent / output.name
    if storage:
        if not output.resolve().is_relative_to(storage.root):
            raise ValueError("enhanced bundle must remain inside storage budget")
        storage.check(
            sum(r.size_bytes for r in manifest.files)
            + sum((reranker_directory / p).stat().st_size for p in model_paths)
            + 32 * 1024**2,
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
        for relative in model_paths:
            destination = stage / "models/reranker" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(reranker_directory / relative, destination)
            if storage:
                storage.account(destination.stat().st_size)
        manifest.retrieval_configuration = configuration
        for relative in configuration.reranker.files:
            path = stage / relative
            manifest.files.append(
                FileRecord(path=relative, sha256=file_hash(path), size_bytes=path.stat().st_size)
            )
        manifest.files.sort(key=lambda r: r.path)
        manifest.licenses.append(spec.license + ": reranker; see models/reranker/LICENSE")
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
