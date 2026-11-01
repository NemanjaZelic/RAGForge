"""Versioned identity algorithm; document contents are hashed separately."""

import hashlib
import json

from pydantic import TypeAdapter

from ragforge.types import Identifier, RelativePath

_collection_adapter: TypeAdapter[str] = TypeAdapter(Identifier)
_path_adapter: TypeAdapter[str] = TypeAdapter(RelativePath)


def document_id(collection_id: str, relative_path: str) -> str:
    collection = _collection_adapter.validate_python(collection_id)
    path = _path_adapter.validate_python(relative_path)
    payload = json.dumps(
        ["ragforge-document-v1", collection, path],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
