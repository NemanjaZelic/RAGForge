"""Attached source context shares the original evidence budget and scope."""

import json

import pytest
from test_evaluation import case, chunk, target

from ragforge.core.contracts import FetchContextRequest, RetrievalResponse, RetrieveRequest
from ragforge.evaluation.scoring import score_response
from ragforge.shared.client import SharedClient


def section_chunk(text, *, path="guide.txt", page=None):
    result = chunk(path, text, page)
    return result.model_copy(
        update={"source": result.source.model_copy(update={"section": "Guide > Rule"})}
    )


def test_empty_context_keeps_the_legacy_json_shape():
    response = RetrievalResponse(contract_version="1", results=[section_chunk("prefix")])
    assert "context" not in response.model_dump(mode="json")
    assert "context" not in json.loads(response.model_dump_json())


def test_context_requires_same_document_section_and_page_and_unique_ids():
    first = section_chunk("prefix")
    with pytest.raises(ValueError, match="same-page or same-section"):
        RetrievalResponse(
            contract_version="1", results=[first], context=[section_chunk("fact", path="other.txt")]
        )
    with pytest.raises(ValueError, match="same-page or same-section"):
        RetrievalResponse(
            contract_version="1", results=[first], context=[section_chunk("fact", page=2)]
        )
    with pytest.raises(ValueError, match="duplicate"):
        RetrievalResponse(contract_version="1", results=[first], context=[first])
    with pytest.raises(ValueError, match="total result text"):
        RetrievalResponse(
            contract_version="1", results=[first], context=[section_chunk("x" * 100000)]
        )


def test_fact_scoring_credits_actual_returned_context_without_changing_ranked_cutoffs():
    fact = "The transport MUST NOT expose credentials in the URL."
    response = RetrievalResponse(
        contract_version="1",
        results=[section_chunk("prefix"), section_chunk("suffix")],
        context=[section_chunk(fact)],
    )
    query = case([[target("guide.txt", fact)]])
    assert not score_response(query, response, lambda target: fact, evidence_cutoff=1)[
        "all_required_groups_covered"
    ]
    whole = score_response(query, response, lambda target: fact, evidence_cutoff=50)
    assert whole["all_required_groups_covered"]
    assert whole["document_recall_at_5"] == 1
    assert response.evidence_chunks(1) == response.results[:1]


def test_shared_client_counts_context_against_request_and_refuses_it_for_neighbor_reads(
    monkeypatch,
):
    first = section_chunk("prefix")
    response = RetrievalResponse(
        contract_version="1", results=[first], context=[section_chunk("extra evidence")]
    )
    client = SharedClient("http://127.0.0.1:8765", "synthetic-bearer")
    monkeypatch.setattr(client, "_request", lambda *args: response.model_dump_json().encode())
    with pytest.raises(ValueError, match="scope or budget"):
        client.retrieve(RetrieveRequest(query="rule", max_output_chars=len(first.text)))
    with pytest.raises(ValueError, match="context escaped"):
        client.fetch_context(
            FetchContextRequest(collection_id="docs", chunk_id=first.chunk_id, neighbors=0)
        )


def test_pdf_page_context_can_work_without_an_extracted_heading():
    primary = chunk("guide.pdf", "page prefix", 3)
    extra = chunk("guide.pdf", "page continuation", 3)
    response = RetrievalResponse(contract_version="1", results=[primary], context=[extra])
    assert response.evidence_chunks() == [primary, extra]
    with pytest.raises(ValueError, match="same-page"):
        RetrievalResponse(
            contract_version="1", results=[primary], context=[chunk("guide.pdf", "wrong page", 4)]
        )
