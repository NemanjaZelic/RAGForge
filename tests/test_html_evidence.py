import hashlib
from pathlib import Path

import pytest

from ragforge.artifacts.builder import build_bundle
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.evaluation.models import EvaluationCase, Evidence, EvidenceGroup
from ragforge.evaluation.scoring import score_response
from ragforge.evaluation.sources import EvidenceSources, HTMLBodyText, canonicalize

METHOD = "html-body-text-collapse-whitespace-v1"
HTML = (
    '<!DOCTYPE html SYSTEM "https://invalid.example/never-fetch.dtd">'
    "<html><head><title>Excluded title</title></head><body>"
    "<h2>Transactions</h2><p>Use <code>COMMIT</code> to finish &amp; keep changes.</p>"
    "<script>raise RuntimeError('do not execute')</script>"
    "<style>Excluded style</style><template><p>Excluded template</p></template>"
    "<pre>SELECT 1;\nSELECT 2;</pre>"
    "<table><tr><td>Row</td><td>Value</td></tr></table></body>Excluded tail</html>"
)
TEXT = "Transactions Use COMMIT to finish & keep changes. SELECT 1; SELECT 2; Row Value"


def evidence(raw: str, quote: str) -> Evidence:
    start = (" " + TEXT + " ").index(quote)
    return Evidence(
        source_path="guide.html",
        source_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        canonicalizer=METHOD,
        char_start=start,
        char_end=start + len(quote),
        span_sha256=hashlib.sha256(quote.encode()).hexdigest(),
    )


def test_html_body_oracle_handles_inline_code_entities_and_table_boundaries():
    parser = HTMLBodyText()
    parser.feed(HTML)
    assert canonicalize("".join(parser.parts), METHOD).strip() == TEXT
    fragment = HTMLBodyText()
    fragment.feed("<p>A fragment is not an explicit body.</p>")
    assert not fragment.parts


def test_html_source_facts_score_actual_offline_returned_text(tmp_path: Path, monkeypatch):
    import socket

    def denied(*args, **kwargs):
        raise AssertionError("HTML evidence extraction must not fetch external resources")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    source = tmp_path / "source"
    source.mkdir()
    (source / "guide.html").write_bytes(HTML.encode("utf-8"))
    target = evidence(HTML, "Use COMMIT to finish & keep changes.")
    provider = EvidenceSources(source)
    assert provider.text(target).strip() == TEXT
    bundle = tmp_path / "bundle"
    build_bundle(source, bundle, collection_id="docs", profile="minimal")
    case = EvaluationCase(
        case_id="html:1",
        corpus_id="original",
        collection_id="docs",
        family_id="html",
        split="test",
        query="How can a transaction keep changes?",
        answerability="answerable",
        evidence_groups=[EvidenceGroup(any_of=[target])],
        review_status="ai_draft",
    )
    result = BundleEngine(bundle).retrieve(RetrieveRequest(query="COMMIT", top_k=50))
    scored = score_response(case, result, provider.text, evidence_cutoff=50, minimum_coverage=1.0)
    assert scored["all_required_groups_covered"]
    assert scored["unmapped_reference_chunks"] == 0


def test_html_oracle_refuses_changed_source_and_fact_span(tmp_path: Path):
    (tmp_path / "guide.html").write_bytes(HTML.encode("utf-8"))
    target = evidence(HTML, "Use COMMIT to finish & keep changes.")
    bad = target.model_copy(update={"span_sha256": "0" * 64})
    with pytest.raises(ValueError, match="span hash"):
        EvidenceSources(tmp_path).text(bad)
    (tmp_path / "guide.html").write_text(HTML + "changed", encoding="utf-8")
    with pytest.raises(ValueError, match="source bytes"):
        EvidenceSources(tmp_path).text(target)
