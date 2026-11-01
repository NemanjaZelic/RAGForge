"""Visible ingestion gaps are separate from artifact checksum validity."""

import json
from typing import Any

from ragforge.core.sqlite import SQLiteEngine


def ingestion_diagnostics(engine: SQLiteEngine) -> dict[str, Any]:
    failed = empty = pages = no_text = errors = warnings = documents = indexed = 0
    with engine._connect() as connection:
        for row in connection.execute(
            "SELECT d.source_path,d.parser_version,d.pages_json,d.warnings_json,"
            "EXISTS(SELECT 1 FROM chunks c WHERE c.document_id=d.document_id) AS indexed "
            "FROM documents d ORDER BY d.source_path"
        ):
            documents += 1
            indexed += int(row["indexed"])
            is_failed = row["parser_version"] == "parse-failed-v1"
            failed += is_failed
            empty += not row["indexed"] and not is_failed
            warnings += bool(json.loads(row["warnings_json"]))
            reports = json.loads(row["pages_json"])
            if not isinstance(reports, list) or len(reports) > 10000:
                raise ValueError("invalid PDF page diagnostics")
            pages += len(reports)
            for report in reports:
                if report["status"] not in {"extracted", "no_text", "error"}:
                    raise ValueError("invalid PDF page status")
                no_text += report["status"] == "no_text"
                errors += report["status"] == "error"
    return {
        "source_documents": documents,
        "indexed_documents": indexed,
        "failed_documents_retained": failed,
        "other_zero_chunk_documents": empty,
        "reported_pdf_pages": pages,
        "pdf_no_text_pages": no_text,
        "pdf_error_pages": errors,
        "documents_with_warnings": warnings,
        "all_sources_have_searchable_text": indexed == documents and not no_text and not errors,
        "scope": "text-layer diagnostics; figures/tables and semantic completeness need evaluation",
    }
