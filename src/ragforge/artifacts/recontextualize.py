"""Build a new context-mapped version from two verified source-identical bundles."""

import os
import shutil
import tempfile
from pathlib import Path

from ragforge import __version__
from ragforge.artifacts.builder import publish_new
from ragforge.artifacts.manifest import BundleManifest, DenseSource, QueryPlanning, SectionContext
from ragforge.artifacts.verification import build_identity, verify_bundle
from ragforge.jobs.budget import StorageBudget


def recontextualize_bundle(
    dense_base: Path,
    context_base: Path,
    output: Path,
    *,
    storage: StorageBudget | None = None,
    document_titles: Path | None = None,
    query_aliases: Path | None = None,
    query_planning: QueryPlanning | None = None,
    section_context: SectionContext | None = None,
) -> BundleManifest:
    child = verify_bundle(dense_base)
    parent = verify_bundle(context_base)
    if document_titles is not None:
        from ragforge.artifacts.titles import apply_document_titles
        from ragforge.core.sqlite import SQLiteEngine

        parent = apply_document_titles(
            parent,
            SQLiteEngine(context_base / parent.collections[0].database_path),
            document_titles,
        )
    cc, pc = child.collections[0], parent.collections[0]
    dense = cc.dense_index
    if child.profile != "balanced" or dense is None or dense.source_chunks is not None:
        raise ValueError("dense base must be an unmapped balanced bundle")
    if cc.collection_id != pc.collection_id or sorted(
        (d.document_id, d.source_path, d.content_sha256) for d in cc.documents
    ) != sorted((d.document_id, d.source_path, d.content_sha256) for d in pc.documents):
        raise ValueError("context and dense source inventories must be identical")
    if parent.build_configuration.chunk_size_chars <= child.build_configuration.chunk_size_chars:
        raise ValueError("context base must use larger context chunks")
    output = output.absolute()
    for base in [dense_base, context_base]:
        if output.resolve().is_relative_to(base.resolve()) or base.resolve().is_relative_to(
            output.resolve()
        ):
            raise ValueError("new context bundle must be separate from both bases")
    if os.path.lexists(output):
        raise FileExistsError("context bundle output must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    output = output.parent.resolve(strict=True) / output.name
    assert child.query_model is not None
    source_path = f"collections/{cc.collection_id}/dense-chunks.sqlite"
    child_files = {record.path: record for record in child.files}
    parent_files = {record.path: record for record in parent.files}
    copies = {pc.database_path: (context_base / pc.database_path, parent_files[pc.database_path])}
    for name in [dense.path, *child.query_model.files]:
        copies[name] = (dense_base / name, child_files[name])
    copies[source_path] = (
        dense_base / cc.database_path,
        child_files[cc.database_path].model_copy(update={"path": source_path}),
    )
    configuration = parent.retrieval_configuration or child.retrieval_configuration
    if query_planning is not None:
        if configuration is None:
            raise ValueError("query planning requires a configured reranker")
        configuration = configuration.model_copy(update={"query_planning": query_planning})
    if section_context is not None:
        if configuration is None:
            raise ValueError("section completion requires a configured reranker")
        configuration = configuration.model_copy(update={"section_context": section_context})
    if query_aliases is not None:
        from ragforge.artifacts.manifest import FileRecord
        from ragforge.core.aliases import verify_aliases
        from ragforge.core.embedding import file_hash
        from ragforge.core.sqlite import SQLiteEngine

        if configuration is None:
            raise ValueError("query aliases require a configured reranker")
        verify_aliases(query_aliases, parent, SQLiteEngine(context_base / pc.database_path))
        alias_path = f"collections/{cc.collection_id}/query-aliases.json"
        configuration = configuration.model_copy(update={"query_aliases": alias_path})
        copies[alias_path] = (
            query_aliases,
            FileRecord(
                path=alias_path,
                sha256=file_hash(query_aliases),
                size_bytes=query_aliases.stat().st_size,
            ),
        )
    elif configuration is not None and configuration.query_aliases is not None:
        origin = context_base if parent.retrieval_configuration is not None else dense_base
        records = parent_files if parent.retrieval_configuration is not None else child_files
        copies[configuration.query_aliases] = (
            origin / configuration.query_aliases,
            records[configuration.query_aliases],
        )
    if configuration is not None:
        origin = context_base if parent.retrieval_configuration is not None else dense_base
        records = parent_files if parent.retrieval_configuration is not None else child_files
        for name in configuration.reranker.files:
            copies[name] = (origin / name, records[name])
    if storage:
        if not output.resolve().is_relative_to(storage.root):
            raise ValueError("context bundle must remain inside storage budget")
        storage.check(
            sum(record.size_bytes for _, record in copies.values()) + 32 * 1024**2, refresh=True
        )
    mapped = dense.model_copy(
        update={
            "source_chunks": DenseSource(
                database_path=source_path,
                build_id=child.build_id,
            )
        }
    )
    candidate = parent.model_copy(
        update={
            "profile": "balanced",
            "capabilities": ["bm25", "dense", "hybrid"],
            "default_search_method": "hybrid",
            "query_model": child.query_model,
            "retrieval_configuration": configuration,
            "collections": [pc.model_copy(update={"dense_index": mapped})],
            "files": [record for _, (_, record) in sorted(copies.items())],
            "producer_version": __version__,
            "licenses": list(dict.fromkeys(parent.licenses + child.licenses)),
        }
    )
    candidate = BundleManifest.model_validate(candidate.model_dump())
    candidate.build_id = build_identity(candidate)
    stage = Path(tempfile.mkdtemp(prefix=".ragforge-stage-", dir=output.parent)).resolve()
    try:
        for name, (source, record) in copies.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if storage:
                storage.account(record.size_bytes)
        (stage / "manifest.json").write_text(
            candidate.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        verified = verify_bundle(stage)
        if storage:
            storage.check(refresh=True)
        publish_new(stage, output)
        return verified
    finally:
        if stage.exists():
            if stage.resolve() == output.parent or not stage.resolve().is_relative_to(
                output.parent
            ):
                raise ValueError("staging cleanup escaped the owned output parent")
            shutil.rmtree(stage)
