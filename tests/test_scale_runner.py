"""Actual subprocess coverage for the large-run coordinator on tiny synthetic sources."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas

from ragforge.evaluation.models import EvaluationCase, Evidence, EvidenceGroup
from ragforge.evaluation.runner import read_cases
from ragforge.jobs.build import BuildWorkspace
from ragforge.jobs.ingest import ingest_corpus


def script(name):
    location = Path(__file__).resolve().parents[1] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lock_only_build_job_can_resume_after_scan_interruption(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "writer.lock").touch()
    workspace = BuildWorkspace(job, tmp_path / "bundle", {"recipe": 1}, resume=True)
    assert workspace.stage.is_dir()
    other = tmp_path / "other"
    other.mkdir()
    (other / "unknown").touch()
    with pytest.raises(ValueError, match="missing build state"):
        BuildWorkspace(other, tmp_path / "b2", {}, resume=True)


def test_reference_cache_is_source_bound_resumable_and_matches_label_oracle(tmp_path):
    from ragforge.core.embedding import file_hash

    module = script("prepare_pdf_evidence_cache")
    root, output = tmp_path / "sources", tmp_path / "reference"
    source = root / "3gpp-etsi/input/reference.pdf"
    source.parent.mkdir(parents=True)
    canvas = Canvas(str(source))
    canvas.drawString(72, 720, "Independent alpha evidence")
    canvas.save()
    ref = {
        "path": "reference.pdf",
        "sha256": file_hash(source),
        "state": "exact_source_bytes_acquired",
    }
    metadata = root / "metadata/telequad-exact-3gpp-sources.json"
    metadata.parent.mkdir()
    metadata.write_text(json.dumps({"records": [ref]}), encoding="utf-8")
    assert module.prepare(root, output, tmp_path)["references"] == 1
    cache_file = output / (ref["sha256"] + ".json")
    pages = json.loads(cache_file.read_text(encoding="utf-8"))
    assert len(pages) == 1 and "alpha evidence" in pages[0]
    before = cache_file.stat().st_mtime_ns
    module.prepare(root, output, tmp_path, resume=True)
    assert cache_file.stat().st_mtime_ns == before
    cache_file.write_text('["tampered"]', encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        module.prepare(root, output, tmp_path, resume=True)


def test_full_coordinator_uses_frozen_offline_children_and_resumes_all_steps(tmp_path, tiny_model):
    module = script("run_scale_benchmark")
    root, cases, cache = tmp_path / "scale", tmp_path / "cases", tmp_path / "pdf-cache"
    cases.mkdir()
    cache.mkdir()
    body = "alpha evidence"
    for corpus, collection in (
        ("kernel-6.18", "kernel-6-18"),
        ("ietf-rfcs", "ietf-rfcs"),
        ("3gpp-etsi", "3gpp-etsi"),
    ):
        source = root / corpus / "input"
        source.mkdir(parents=True)
        (source / "a.txt").write_text(body, encoding="utf-8")
        ingest_corpus(source, root / "runs/ingest-v1" / corpus, collection_id=collection)
        tracks = (
            ["native_source_alignment_diagnostic", "explicit_version_draft"]
            if (corpus == "3gpp-etsi")
            else ["supplementary_evidence_draft"]
        )
        bank = []
        for track in tracks:
            for split in ("dev", "tuning", "test"):
                evidence = Evidence(
                    source_path="a.txt",
                    source_sha256=hashlib.sha256(body.encode()).hexdigest(),
                    canonicalizer="collapse-whitespace-v1",
                    char_start=0,
                    char_end=len(body),
                    span_sha256=hashlib.sha256(body.encode()).hexdigest(),
                )
                row = EvaluationCase(
                    case_id="synthetic",
                    corpus_id=corpus,
                    collection_id=collection,
                    family_id="synthetic",
                    split="dev",
                    query="alpha",
                    answerability="answerable",
                    evidence_groups=[EvidenceGroup(any_of=[evidence])],
                    review_status="ai_draft",
                )
                row = row.model_copy(
                    update={
                        "case_id": track + split,
                        "corpus_id": corpus,
                        "collection_id": collection,
                        "split": split,
                        "family_id": track + split,
                        "track": track,
                    }
                )
                bank.append(row.model_dump_json())
        (cases / (corpus + ".jsonl")).write_text("\n".join(bank) + "\n", encoding="utf-8")
        assert read_cases(cases / (corpus + ".jsonl"))
    output = root / "runs/execution"
    module.execute(root, output, tiny_model, cases, cache, tmp_path)
    state = json.loads((output / "status.json").read_text(encoding="utf-8"))
    assert state["state"] == "complete_diagnostic_draft_labels"
    assert len(state["steps"]) == 15
    summaries = list(output.rglob("measurement.json"))
    assert len(summaries) == 12
    for path in summaries:
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["strict_scoring"] is False
        for method in ("bm25", "dense", "hybrid"):
            assert report["methods"][method]["document_recall_at_5"] == 1
            assert report["methods"][method]["errors"] == 0
    before = {p: p.stat().st_mtime_ns for p in summaries}
    module.execute(root, output, tiny_model, cases, cache, tmp_path, resume=True)
    assert all(p.stat().st_mtime_ns == stamp for p, stamp in before.items())
    (output / "runtime/ragforge/__init__.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen runtime was modified"):
        module.execute(root, output, tiny_model, cases, cache, tmp_path, resume=True)
