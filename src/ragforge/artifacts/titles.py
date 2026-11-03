"""Optional document titles must match verified indexed source text."""

import json
import sqlite3
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from ragforge.artifacts.manifest import BundleManifest
from ragforge.core.contracts import SourceLocation
from ragforge.core.source import is_link
from ragforge.core.sqlite import SQLiteEngine
from ragforge.types import ContractModel, RelativePath, Sha256


class DocumentTitle(ContractModel):
    source_path: RelativePath
    source_sha256: Sha256
    title: Annotated[str, Field(min_length=1, max_length=512)]


def canonical_title(text: str) -> str:
    return " ".join(text.split()).casefold()


def indexed_title(connection: sqlite3.Connection, document_id: str, title: str) -> bool:
    rows = connection.execute(
        "SELECT text,source_json FROM chunks WHERE document_id=? ORDER BY ordinal LIMIT 16",
        (document_id,),
    ).fetchall()
    lead = "\n".join(row[0] for row in rows)[:8192]
    candidate = canonical_title(title)
    headings = [SourceLocation.model_validate_json(row[1]).section for row in rows]
    return bool(candidate) and (
        candidate in canonical_title(lead)
        or any(candidate == canonical_title(heading) for heading in headings if heading is not None)
    )


def apply_document_titles(
    manifest: BundleManifest, engine: SQLiteEngine, path: Path
) -> BundleManifest:
    if is_link(path.lstat()) or not path.is_file() or path.stat().st_size > 16 * 1024**2:
        raise ValueError("unsafe or oversized document title metadata")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) > 100000:
        raise ValueError("invalid document title inventory size")
    rows = TypeAdapter(list[DocumentTitle]).validate_python(data)
    if len({r.source_path for r in rows}) != len(rows):
        raise ValueError("duplicate document title metadata")
    collection = manifest.collections[0]
    documents = {d.source_path: d for d in collection.documents}
    with engine._connect() as connection:
        for row in rows:
            source = documents.get(row.source_path)
            if source is None or source.content_sha256 != row.source_sha256:
                raise ValueError("document title source does not match the verified inventory")
            if not indexed_title(connection, source.document_id, row.title):
                raise ValueError("document title is absent from indexed source lead text")
            documents[row.source_path] = source.model_copy(update={"title": row.title})
    return manifest.model_copy(
        update={
            "collections": [
                collection.model_copy(
                    update={"documents": [documents[d.source_path] for d in collection.documents]}
                )
            ]
        }
    )
