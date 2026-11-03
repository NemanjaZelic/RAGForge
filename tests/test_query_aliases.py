"""Expansion is optional source data, never question/answer lookup."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.recontextualize import recontextualize_bundle
from ragforge.artifacts.verification import build_identity, verify_bundle
from ragforge.core.aliases import Acronym, AliasBank, AliasProof, expand_query
from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine


def test_expansion_retains_original_terms_and_respects_budgets():
    aliases = {
        "dns": "domain name system",
        "tls": "transport layer security",
        "jwt": "json web token",
        "tcp": "transmission control protocol",
    }
    query = "DNS TLS JWT TCP"
    assert (
        expand_query(query, aliases)
        == query + " domain name system transport layer security json web token"
    )
    assert expand_query("DNS DNS", aliases) == "DNS DNS domain name system"
    assert expand_query("DNS domain name system", aliases) == "DNS domain name system"
    long = "DNS " + " ".join(f"term{i}" for i in range(63))
    assert expand_query(long, aliases) == long
    assert expand_query("unknown", aliases) == "unknown"


def test_natural_words_do_not_trigger_technical_acronym_expansion():
    aliases = {
        "dns": "domain name system",
        "in": "intelligent network",
        "as": "autonomous system",
    }
    query = "How does DNS work in this case as a resolver?"
    assert expand_query(query, aliases) == query + " domain name system"
    assert expand_query("In this case, act as a resolver", aliases) == (
        "In this case, act as a resolver"
    )
    assert expand_query("dns in as", aliases) == "dns in as"
    assert expand_query("AS IN", aliases) == "AS IN autonomous system intelligent network"


def test_alias_bundle_is_portable_scoped_and_raw_bm25_remains_original(
    tmp_path: Path, tiny_model, tiny_reranker, monkeypatch
):
    source = tmp_path / "sources"
    source.mkdir()
    for i in range(3):
        (source / f"{i}.txt").write_text(
            f"Domain Name System (DNS) resolves names. Independent source {i}.\n"
            + "The server processes protocol messages. " * 8
        )
    (source / "public.txt").write_text("DNS server public information without an expansion.")
    child, parent, output = tmp_path / "child", tmp_path / "parent", tmp_path / "mapped"
    build_bundle(
        source,
        child,
        collection_id="docs",
        model_directory=tiny_model,
        chunk_config=ChunkConfig(chunk_size_chars=140, overlap_chars=20),
    )
    m = build_bundle(
        source, parent, collection_id="docs", profile="minimal", reranker_directory=tiny_reranker
    )
    definition = Acronym(
        short="DNS",
        long_form="domain name system",
        proofs=[
            AliasProof(
                source_path=d.source_path,
                source_sha256=d.content_sha256,
                quote="Domain Name System (DNS)",
            )
            for d in m.collections[0].documents
            if d.source_path != "public.txt"
        ],
    )
    bank = tmp_path / "aliases.json"
    bank.write_text(
        AliasBank(catalogue_sha256="a" * 64, definitions=[definition]).model_dump_json()
    )
    manifest = recontextualize_bundle(child, parent, output, query_aliases=bank)
    assert manifest.retrieval_configuration.query_aliases == "collections/docs/query-aliases.json"
    engine = BundleEngine(output, threads=1)
    raw = engine.retrieve(RetrieveRequest(query="DNS server", search_method="bm25"))
    assert raw.results and engine._reranker is None and engine._embedder is None
    seen = []
    original = engine.sqlite.rank_bm25

    def rank(request, limit):
        seen.append(request.query)
        return original(request, limit)

    monkeypatch.setattr(engine.sqlite, "rank_bm25", rank)
    engine.retrieve(RetrieveRequest(query="DNS server", search_method="hybrid"))
    assert seen == ["DNS server domain name system"]
    from ragforge.core.contracts import RetrievalFilters

    public = next(
        d.document_id for d in m.collections[0].documents if d.source_path == "public.txt"
    )
    seen.clear()
    scoped = engine.retrieve(
        RetrieveRequest(
            query="DNS server",
            search_method="hybrid",
            filters=RetrievalFilters(document_ids=[public]),
        )
    )
    assert seen == ["DNS server"]
    assert all(c.document_id == public for c in scoped.results)

    # An apparently valid manifest cannot approve absent source evidence.
    path = output / manifest.retrieval_configuration.query_aliases
    payload = json.loads(path.read_text())
    payload["definitions"][0]["proofs"][0]["source_sha256"] = "f" * 64
    path.write_text(json.dumps(payload))
    from ragforge.core.embedding import file_hash

    for f in manifest.files:
        if f.path == manifest.retrieval_configuration.query_aliases:
            f.sha256 = file_hash(path)
            f.size_bytes = path.stat().st_size
    manifest.build_id = build_identity(manifest)
    (output / "manifest.json").write_text(manifest.model_dump_json())
    with pytest.raises(ValueError, match="acronym source"):
        verify_bundle(output)
    with pytest.raises(ValidationError, match="initials"):
        definition.model_validate(
            {**definition.model_dump(), "long_form": "incorrect invented name"}
        )
