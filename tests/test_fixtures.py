import json
from pathlib import Path

from ragforge.core.contracts import RetrieveRequest
from ragforge.core.identity import document_id

ROOT = Path(__file__).resolve().parents[1]


def test_development_queries_have_resolvable_labels() -> None:
    corpus = ROOT / "examples" / "mini-docs"
    documents = {
        document_id("mini", path.relative_to(corpus).as_posix()) for path in corpus.rglob("*.md")
    }
    queries = [
        json.loads(line)
        for line in (ROOT / "examples" / "eval.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(queries) == 20
    assert len({row["query_id"] for row in queries}) == 20
    assert sum(row["kind"] == "unanswerable" for row in queries) == 4
    for row in queries:
        RetrieveRequest(query=row["query"], collection_id=row["collection_id"])
        expected = [
            document_id(row["collection_id"], path) for path in row["relevant_source_paths"]
        ]
        assert row["relevant_document_ids"] == expected
        assert set(expected) <= documents
        assert bool(expected) == (row["kind"] == "relevant")
