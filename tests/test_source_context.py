"""Source-only context must improve evidence without losing unique or scoped information."""

import asyncio
import hashlib
import json
import shutil
import sqlite3
import textwrap
from pathlib import Path

import pytest
from mcp_helpers import offline_client
from reportlab.pdfgen.canvas import Canvas
from typer.testing import CliRunner

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.source_context import attach_source_context, build_source_context
from ragforge.artifacts.verification import build_identity, verify_bundle
from ragforge.cli import app
from ragforge.core.contracts import RetrievalFilters, RetrievalResponse, RetrieveRequest
from ragforge.core.definitions import extract_definitions, verify_catalogue
from ragforge.core.engine import BundleEngine
from ragforge.core.source_context import SourceContext, definition_short, information_key


def pdf(path: Path, text: str) -> None:
    canvas = Canvas(str(path))
    for i, line in enumerate(textwrap.wrap(text, 85)):
        canvas.drawString(40, 800 - i * 15, line)
    canvas.save()


@pytest.fixture
def context_bundle(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    duplicate = "DNS resolver operations. " + "The resolver processes incoming messages. " * 8
    for version in [100, 101, 102]:
        pdf(source / f"ts01v{version}p.pdf", duplicate)
    pdf(source / "ts02v100p.pdf", "Domain Name System (DNS) resolves host names.")
    pdf(source / "ts03v100p.pdf", "Data Network Service (DNS) is a separate meaning.")
    base = tmp_path / "base"
    manifest = build_bundle(source, base, collection_id="docs", profile="minimal")
    catalogue = tmp_path / "definitions.sqlite"
    stats = build_source_context(base, catalogue)
    assert stats["neural_inference_calls"] == stats["benchmark_inputs_read"] == 0
    engine = BundleEngine(base)
    original = engine.retrieve(RetrieveRequest(query="resolver operations", top_k=3))
    assert len(original.results) == 3
    assert len({information_key(c, False) for c in original.results}) == 1
    checksum = manifest.files[0].sha256
    return base, catalogue, engine, original, checksum


def test_live_retrieval_and_portable_relocation_preserve_index_and_old_identity(
    context_bundle, tmp_path
):
    base, catalogue, old_engine, original, _ = context_bundle
    old_manifest = (base / "manifest.json").read_bytes()
    request = RetrieveRequest(query="What is DNS?", top_k=5)
    before = old_engine.retrieve(request)
    enhanced = BundleEngine(base, source_context=catalogue).retrieve(request)
    assert {information_key(c, False) for c in before.results} <= {
        information_key(c, False) for c in enhanced.results
    }
    assert len(enhanced.results) <= 5
    response = BundleEngine(base, source_context=catalogue)._source_context.supplement(
        request, original
    )
    assert any("Domain Name System" in c.text for c in response.results)
    assert any("Data Network Service" in c.text for c in response.results)
    attached = tmp_path / "attached"
    manifest = attach_source_context(base, catalogue, attached)
    assert manifest.build_id != old_engine.manifest.build_id
    assert manifest.files[0].sha256 == old_engine.manifest.files[0].sha256
    moved = tmp_path / "moved bundle"
    shutil.move(str(attached), moved)
    assert verify_bundle(moved) == manifest
    assert BundleEngine(moved).retrieve(request) == enhanced
    assert (base / "manifest.json").read_bytes() == old_manifest
    legacy = json.loads(old_manifest)
    legacy.pop("source_context", None)
    (base / "manifest.json").write_text(json.dumps(legacy))
    assert verify_bundle(base).build_id == build_identity(old_engine.manifest)
    with pytest.raises(ValueError, match="not both"):
        BundleEngine(moved, source_context=catalogue)


def test_only_duplicates_replace_and_version_and_character_budgets_protect_original(context_bundle):
    _, catalogue, engine, original, checksum = context_bundle
    context = SourceContext(catalogue, engine.sqlite, checksum, "docs")
    request = RetrieveRequest(query="What is DNS?", top_k=3)
    unique = RetrievalResponse(contract_version="1", results=original.results[:1])
    assert context.supplement(request, unique) is unique
    versioned = request.model_copy(update={"query": "What is DNS in release 17?"})
    assert context.supplement(versioned, original) is original
    translated = request.model_copy(
        update={"query": "DNS version 17", "query_translation": "What is DNS?"}
    )
    assert context.supplement(translated, original) is original
    bound = request.model_copy(
        update={"max_output_chars": sum(len(c.text) for c in original.results)}
    )
    actual = context.supplement(bound, original, max_chunks_per_document=1)
    assert sum(len(c.text) for c in actual.results) <= bound.max_output_chars
    assert (
        max(sum(c.document_id == d.document_id for c in actual.results) for d in actual.results)
        == 1
    )
    with pytest.raises(ValueError, match="budget"):
        context.supplement(request.model_copy(update={"max_output_chars": 1}), original)
    with pytest.raises(ValueError, match="scope"):
        context.supplement(request.model_copy(update={"collection_id": "other"}), original)


def test_scoped_catalogue_and_source_queries_do_not_read_or_expand_other_documents(context_bundle):
    _, catalogue, engine, original, checksum = context_bundle
    context = SourceContext(catalogue, engine.sqlite, checksum, "docs")
    allowed = [c.document_id for c in original.results]
    request = RetrieveRequest(
        query="What is DNS?", top_k=3, filters=RetrievalFilters(document_ids=allowed)
    )
    actual = context.supplement(request, original)
    assert actual is original
    with pytest.raises(ValueError, match="scope"):
        context.supplement(
            request.model_copy(update={"filters": RetrievalFilters(document_ids=["f" * 64])}),
            original,
        )
    # If forbidden proofs were inspected before SQL scope filtering, this would fail.
    with sqlite3.connect(catalogue) as db:
        db.execute("UPDATE definitions SET source_json='not-json',quote='not-in-source'")
    assert context.supplement(request, original) is original
    assert not engine.retrieve(
        RetrieveRequest(query="DNS", filters=RetrievalFilters(document_ids=["f" * 64]))
    ).results


@pytest.mark.parametrize("fault", ["quote", "index", "schema", "trigger", "checksum"])
def test_untrusted_catalogue_fails_before_runtime(context_bundle, tmp_path, fault):
    base, catalogue, engine, _, checksum = context_bundle
    if fault == "checksum":
        attached = tmp_path / "attached"
        manifest = attach_source_context(base, catalogue, attached)
        with (attached / manifest.source_context).open("ab") as stream:
            stream.write(b"changed")
        with pytest.raises(ValueError, match="checksum"):
            BundleEngine(attached)
        return
    with sqlite3.connect(catalogue) as db:
        if fault == "quote":
            db.execute("UPDATE definitions SET quote='fabricated answer'")
        elif fault == "index":
            db.execute("UPDATE metadata SET value=? WHERE key='index_sha256'", ("f" * 64,))
        elif fault == "schema":
            db.execute("ALTER TABLE definitions ADD COLUMN injected TEXT")
        else:
            db.execute("CREATE TRIGGER unexpected AFTER INSERT ON meanings BEGIN SELECT 1; END")
    with pytest.raises(ValueError):
        verify_catalogue(catalogue, engine.sqlite, checksum, "docs")
    with pytest.raises(ValueError):
        attach_source_context(base, catalogue, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_catalogue_build_no_overwrite_and_reject_other_index(context_bundle, tmp_path):
    base, catalogue, _, _, _ = context_bundle
    before = hashlib.sha256(catalogue.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        build_source_context(base, catalogue)
    assert hashlib.sha256(catalogue.read_bytes()).hexdigest() == before
    with pytest.raises(ValueError, match="immutable"):
        build_source_context(base, base / "extra.sqlite")
    assert not (base / "extra.sqlite").exists()
    source = tmp_path / "other-source"
    source.mkdir()
    (source / "other.txt").write_text("Different indexed source.")
    other = tmp_path / "other"
    build_bundle(source, other, collection_id="docs", profile="minimal")
    with pytest.raises(ValueError, match="another index"):
        BundleEngine(other, source_context=catalogue)


def test_cli_build_attach_and_use_offline_without_ml(
    context_bundle, tmp_path, offline_cli, monkeypatch
):
    base, _, _, _, _ = context_bundle
    monkeypatch.setenv("RAGFORGE_FORBID_ML_IMPORTS", "1")
    catalogue = tmp_path / "cli.sqlite"
    built = offline_cli(["source-context", str(base), "--output", str(catalogue)])
    assert built.returncode == 0, built.stderr
    assert json.loads(built.stdout)["neural_inference_calls"] == 0
    attached = tmp_path / "cli-bundle"
    bound = offline_cli(["attach-context", str(base), str(catalogue), "--output", str(attached)])
    assert bound.returncode == 0, bound.stderr
    args = ["--query", "What is DNS?", "--top-k", "5"]
    external = offline_cli(["use", str(base), "--source-context", str(catalogue), *args])
    portable = offline_cli(["use", str(attached), *args])
    assert external.returncode == portable.returncode == 0, (external.stderr, portable.stderr)
    assert json.loads(external.stdout) == json.loads(portable.stdout)
    for command in [
        ["use", "--mode", "shared", "--query", "DNS", "--source-context", str(catalogue)],
        ["serve", str(base), "--transport", "http", "--source-context", str(catalogue)],
    ]:
        rejected = CliRunner().invoke(app, command)
        assert rejected.exit_code == 2
        assert "source context" in rejected.stderr


def test_portable_catalogue_retrieval_via_real_mcp(context_bundle, tmp_path):
    base, catalogue, _, _, _ = context_bundle
    portable = tmp_path / "portable"
    attach_source_context(base, catalogue, portable)
    expected = BundleEngine(portable).retrieve(RetrieveRequest(query="What is DNS?", top_k=5))

    async def exercise():
        async with offline_client(portable, tmp_path / "guard", forbid_ml=True) as client:
            result = await client.call_tool("search_docs", {"query": "What is DNS?", "top_k": 5})
            assert not result.is_error
            assert result.structured_content == expected.model_dump(mode="json")

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "query", ["What is DNS?", "What does DNS stand for?", 'What is "DNS" short for?']
)
def test_definition_candidates_are_literal_source_data(query):
    assert definition_short(query) == "dns"
    assert ("DNS", "Domain Name System", "Domain Name System (DNS)") in list(
        extract_definitions("Domain Name System (DNS) resolves names.")
    )
    assert definition_short("what is the best resolver?") is None
    assert not list(extract_definitions("Nothing (NOTE) shall be treated as a meaning."))


def test_inventoried_context_honors_authenticated_http_document_grants(context_bundle, tmp_path):
    import httpx2
    from test_shared_http import listener, token_for

    from ragforge.shared.policy import Principal

    base, catalogue, _, original, _ = context_bundle
    portable = tmp_path / "shared"
    attach_source_context(base, catalogue, portable)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    identity = (
        private,
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    )
    allowed = [c.document_id for c in original.results]
    principals = [
        Principal(subject="limited", collection_id="docs", document_ids=allowed).model_dump(),
        Principal(subject="all", collection_id="docs").model_dump(),
    ]
    with listener(portable, identity, principals) as (url, policy):
        with httpx2.Client(base_url=url, trust_env=False) as client:
            headers = {"Authorization": "Bearer " + token_for(identity, policy, subject="limited")}
            response = client.post(
                "/retrieve", headers=headers, json={"query": "What is DNS?", "top_k": 5}
            )
            assert response.status_code == 200, response.text
            chunks = response.json()["results"]
            assert chunks and all(c["document_id"] in allowed for c in chunks)
            assert not any("Domain Name System" in c["text"] for c in chunks)


def test_corrupt_sqlite_catalogue_returns_controlled_cli_error(
    context_bundle, tmp_path, offline_cli
):
    base, _, _, _, _ = context_bundle
    invalid = tmp_path / "invalid.sqlite"
    invalid.write_bytes(b"Not a SQLite database" * 20)
    used = offline_cli(["use", str(base), "--query", "DNS", "--source-context", str(invalid)])
    assert used.returncode == 2
    assert json.loads(used.stderr)["error"] == "cannot use source-definition catalogue"
    assert "Traceback" not in used.stderr


@pytest.mark.parametrize(
    "query",
    [
        "What is ZQP used for?",
        "What is the ZQP for?",
        "What does ZQP do?",
        "What is the purpose of ZQP?",
        "What is the role of ZQP?",
        "What is the function of the ZQP?",
        "What are the uses of ZQP?",
    ],
)
def test_purpose_questions_recognize_only_explicit_technical_short_forms(query):
    assert definition_short(query) == "zqp"
    assert definition_short(query.replace("ZQP", "work")) is None
    assert definition_short(query[:-1] + " and what else?") is None


def test_purpose_context_keeps_multiple_meanings_and_needs_no_neural_call(
    context_bundle, monkeypatch
):
    _, catalogue, engine, original, checksum = context_bundle
    context = SourceContext(catalogue, engine.sqlite, checksum, "docs")

    def forbidden(*args, **kwargs):
        raise AssertionError("No capacity remains after filling the two duplicate slots")

    monkeypatch.setattr(context, "_focused", forbidden)
    request = RetrieveRequest(query="What is DNS used for?", top_k=3)
    result = context.supplement(request, original)
    assert len(result.results) == 3
    assert any("Domain Name System" in c.text for c in result.results)
    assert any("Data Network Service" in c.text for c in result.results)
    assert {information_key(c, False) for c in original.results} <= {
        information_key(c, False) for c in result.results
    }
    assert sum(len(c.text) for c in result.results) <= request.max_output_chars


def test_exact_definition_lookup_skips_global_enumeration_and_scopes_before_read(
    context_bundle, monkeypatch
):
    _, catalogue, engine, original, checksum = context_bundle
    context = SourceContext(catalogue, engine.sqlite, checksum, "docs")
    from ragforge.core.definitions import catalogue_connection

    statements = []
    with catalogue_connection(catalogue, checksum, "docs") as bank, engine.sqlite._connect() as db:
        bank.set_trace_callback(statements.append)
        all_meanings = context._definitions("What is DNS?", db, bank, "hybrid", None)
    assert len(all_meanings) == 2
    assert not any("SELECT DISTINCT short" in statement for statement in statements)

    def forbidden(*args, **kwargs):
        raise AssertionError("Must not read foreign definition bodies")

    monkeypatch.setattr(context, "_actual", forbidden)
    allowed = [c.document_id for c in original.results]
    scoped = RetrieveRequest(
        query="What does DNS do?", top_k=3, filters=RetrievalFilters(document_ids=allowed)
    )
    assert context.supplement(scoped, original) == original


@pytest.mark.parametrize(
    "query,expected",
    [
        ("What is DNSS?", "Domain Name System"),
        ("What is DNT?", "Domain Name System"),
    ],
)
def test_exact_lookup_retains_previous_plural_and_typo_fallback(context_bundle, query, expected):
    _, catalogue, engine, original, checksum = context_bundle
    context = SourceContext(catalogue, engine.sqlite, checksum, "docs")
    result = context.supplement(RetrieveRequest(query=query, top_k=3), original)
    assert any(expected in c.text for c in result.results)


def test_purpose_sources_keep_subject_and_actor_without_requiring_question_verb(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    duplicate = "ZQP delivery procedure. " + "The receiver processes incoming messages. " * 8
    for version in [100, 101, 102]:
        pdf(source / f"ts01v{version}p.pdf", duplicate)
    (source / "name.txt").write_text(
        "Queue Processing (ZQP) identifies the receiver.", encoding="utf-8"
    )
    (source / "mapping.txt").write_text(
        "Status flags of messages sent to the ZQP list values zero and one. " * 4,
        encoding="utf-8",
    )
    proof = "Status flags in messages allow the ZQP to choose a recovery action."
    (source / "purpose.txt").write_text(proof, encoding="utf-8")
    base = tmp_path / "base"
    manifest = build_bundle(source, base, collection_id="docs", profile="minimal")
    catalogue = tmp_path / "definitions.sqlite"
    build_source_context(base, catalogue)
    engine = BundleEngine(base)
    context = SourceContext(catalogue, engine.sqlite, manifest.files[0].sha256, "docs")
    original = engine.retrieve(RetrieveRequest(query="delivery procedure", top_k=3))
    assert len({information_key(c, False) for c in original.results}) == 1
    request = RetrieveRequest(
        query="What is the purpose of the status flags of messages sent to the ZQP?",
        top_k=3,
    )
    response = context.supplement(request, original)
    assert any(proof in c.text for c in response.results)
    assert {information_key(c, False) for c in original.results} <= {
        information_key(c, False) for c in response.results
    }
    allowed = [c.document_id for c in original.results]
    restricted = request.model_copy(update={"filters": RetrievalFilters(document_ids=allowed)})
    assert context.supplement(restricted, original) == original
    small = request.model_copy(
        update={"max_output_chars": sum(len(c.text) for c in original.results)}
    )
    bounded = context.supplement(small, original)
    assert sum(len(c.text) for c in bounded.results) <= small.max_output_chars
