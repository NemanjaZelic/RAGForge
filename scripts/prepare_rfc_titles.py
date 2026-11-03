"""Prepare optional RFC titles from a local catalogue; no queries or network."""

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ragforge.artifacts.titles import DocumentTitle, indexed_title
from ragforge.artifacts.verification import verify_bundle
from ragforge.core.sqlite import SQLiteEngine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.catalogue.stat().st_size > 64 * 1024**2:
        raise ValueError("RFC catalogue byte limit exceeded")
    manifest = verify_bundle(args.artifact)
    collection = manifest.collections[0]
    documents = {d.source_path: d for d in collection.documents}
    namespace = {"r": "https://www.rfc-editor.org/rfc-index"}
    payload = args.catalogue.read_bytes()
    entries = ET.fromstring(payload).findall("r:rfc-entry", namespace)
    rows = []
    with SQLiteEngine(args.artifact / collection.database_path)._connect() as connection:
        for entry in entries:
            name = entry.findtext("r:doc-id", default="", namespaces=namespace)
            if not name.upper().startswith("RFC") or not name[3:].isdigit():
                continue
            names = {name.lower(), "rfc" + str(int(name[3:]))}
            matches = [
                documents[name + suffix]
                for name in names
                for suffix in [".txt", ".html", ".htm", ".pdf"]
                if name + suffix in documents
            ]
            if len(matches) != 1:
                continue
            record = matches[0]
            title = " ".join(entry.findtext("r:title", default="", namespaces=namespace).split())
            if not 1 <= len(title) <= 512 or not indexed_title(
                connection, record.document_id, title
            ):
                continue
            rows.append(
                DocumentTitle(
                    source_path=record.source_path, source_sha256=record.content_sha256, title=title
                )
            )
    if len({v.source_path for v in rows}) != len(rows):
        raise ValueError("duplicate RFC title assignment")
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(
            [v.model_dump(mode="json") for v in sorted(rows, key=lambda r: r.source_path)],
            stream,
            ensure_ascii=False,
            indent=2,
        )
        stream.write("\n")
    print(
        json.dumps(
            {
                "artifact_build_id": manifest.build_id,
                "catalogue_sha256": hashlib.sha256(payload).hexdigest(),
                "source_verified_titles": len(rows),
                "documents_without_title": len(documents) - len(rows),
            }
        )
    )


if __name__ == "__main__":
    main()
