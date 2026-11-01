import json
from pathlib import Path

import pytest

from ragforge.artifacts import builder
from ragforge.artifacts.builder import build_bundle
from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.embedding import ONNXEmbedder
from ragforge.core.engine import BundleEngine


def test_actual_dense_checkpoint_resumes_without_reembedding_committed_prefix(
    tmp_path: Path,
    tiny_model: Path,
    monkeypatch,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "manual.txt").write_text("rollback " * 16000, encoding="utf-8")
    output, job = tmp_path / "bundle", tmp_path / "build-job"
    config = ChunkConfig(chunk_size_chars=32, overlap_chars=0)

    def interrupt(event):
        if event["phase"] == "dense":
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        build_bundle(
            source,
            output,
            collection_id="docs",
            model_directory=tiny_model,
            chunk_config=config,
            work_directory=job,
            progress=interrupt,
        )
    checkpoint = json.loads((job / "dense-progress.json").read_text())
    assert checkpoint["next_row"] == 4096 < checkpoint["count"]
    assert not output.exists()
    embedded = 0
    original = ONNXEmbedder.encode

    def track(self, texts, **kwargs):
        nonlocal embedded
        embedded += len(texts)
        return original(self, texts, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(ONNXEmbedder, "encode", track)
        manifest = build_bundle(
            source,
            output,
            collection_id="docs",
            model_directory=tiny_model,
            chunk_config=config,
            work_directory=job,
            resume=True,
        )
    assert embedded == checkpoint["count"] - checkpoint["next_row"]
    assert BundleEngine(output).retrieve(RetrieveRequest(query="rollback")).results
    assert json.loads((job / "build.json").read_text())["phase"] == "published"
    assert (
        build_bundle(
            source,
            output,
            collection_id="docs",
            model_directory=tiny_model,
            chunk_config=config,
            work_directory=job,
            resume=True,
        ).build_id
        == manifest.build_id
    )


def test_crash_after_publish_recovers_without_replacing_output(tmp_path: Path, monkeypatch):
    from ragforge.jobs.build import BuildWorkspace

    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("rollback transaction")
    output, job = tmp_path / "bundle", tmp_path / "job"

    def failed_ack(self):
        raise OSError("crash after atomic publish")

    with monkeypatch.context() as patched:
        patched.setattr(BuildWorkspace, "after_publish", failed_ack)
        with pytest.raises(OSError, match="after atomic publish"):
            build_bundle(
                source, output, collection_id="docs", profile="minimal", work_directory=job
            )
    before = (output / "manifest.json").read_bytes()
    build_bundle(
        source, output, collection_id="docs", profile="minimal", work_directory=job, resume=True
    )
    assert (output / "manifest.json").read_bytes() == before
    assert json.loads((job / "build.json").read_text())["phase"] == "published"


def test_resume_rejects_recipe_changes_and_completed_file_corruption(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("rollback transaction")
    output, job = tmp_path / "bundle", tmp_path / "job"

    def fail_publish(*args):
        raise OSError("interrupted publication")

    with monkeypatch.context() as patched:
        patched.setattr(builder, "publish_new", fail_publish)
        with pytest.raises(OSError, match="publication"):
            build_bundle(
                source, output, collection_id="docs", profile="minimal", work_directory=job
            )
    state = json.loads((job / "build.json").read_text())
    with pytest.raises(ValueError, match="recipe"):
        build_bundle(
            source,
            output,
            collection_id="docs",
            profile="minimal",
            work_directory=job,
            resume=True,
            chunk_config=ChunkConfig(chunk_size_chars=500, overlap_chars=0),
        )
    database = Path(state["stage"]) / "collections/docs/index.sqlite"
    with database.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        build_bundle(
            source, output, collection_id="docs", profile="minimal", work_directory=job, resume=True
        )
    assert not output.exists()
