"""Private persistent build workspace; final data still publishes atomically."""

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from ragforge.core.embedding import file_hash
from ragforge.core.source import is_link


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists() and is_link(path.lstat()):
        raise ValueError("checkpoint must not be a link")
    descriptor, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, sort_keys=True, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class BuildWorkspace:
    def __init__(
        self,
        job: Path,
        output: Path,
        recipe: dict[str, Any],
        *,
        resume: bool,
    ) -> None:
        self.job = job.resolve(strict=True)
        self.output = output
        self.state_path = job / "build.json"
        self.fingerprint = hashlib.sha256(
            json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.state_path.exists():
            if not resume or is_link(self.state_path.lstat()):
                raise ValueError("existing build requires explicit --resume")
            if self.state_path.stat().st_size > 1024**2:
                raise ValueError("oversized build state")
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if self.state["fingerprint"] != self.fingerprint:
                raise ValueError("build recipe/snapshot changed; use a new build job")
            if self.state["output"] != str(output):
                raise ValueError("resumed build must keep its original output path")
            self.stage = Path(self.state["stage"])
        else:
            if resume:
                raise ValueError("cannot resume a missing build state")
            self.stage = Path(tempfile.mkdtemp(prefix=".ragforge-stage-", dir=output.parent))
            self.state = {
                "fingerprint": self.fingerprint,
                "output": str(output),
                "stage": str(self.stage),
                "phase": "created",
            }
            self.save()
        if (
            self.stage.parent.resolve() != output.parent.resolve()
            or not self.stage.name.startswith(".ragforge-stage-")
            or (self.stage.exists() and is_link(self.stage.lstat()))
        ):
            raise ValueError("build stage must remain an owned sibling of its output")
        if self.stage.exists():
            entries = 0
            for parent, dirs, files in os.walk(self.stage, followlinks=False):
                for name in dirs + files:
                    entries += 1
                    path = Path(parent) / name
                    info = path.lstat()
                    if (
                        entries > 10000
                        or is_link(info)
                        or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                        or not path.resolve().is_relative_to(self.stage.resolve())
                    ):
                        raise ValueError("unsafe entry in resumed private build stage")
        self.published = bool(
            self.state.get("build_id") and not self.stage.exists() and output.exists()
        )
        if not self.published and not self.stage.is_dir():
            raise ValueError("resumed build stage is missing")

    def save(self) -> None:
        atomic_json(self.state_path, self.state)

    def reusable(self, component: str, path: Path) -> bool:
        expected = self.state.get(component + "_sha256")
        if expected is None:
            return False
        if is_link(path.lstat()) or file_hash(path) != expected:
            raise ValueError(f"completed {component} checkpoint checksum mismatch")
        return True

    def completed(self, component: str, path: Path) -> None:
        self.state[component + "_sha256"] = file_hash(path)
        self.state["phase"] = component + "_complete"
        self.save()

    def before_publish(self, build_id: str) -> None:
        self.state["build_id"] = build_id
        self.state["phase"] = "publishing"
        self.save()

    def after_publish(self) -> None:
        self.state["phase"] = "published"
        self.save()


def build_status(job: Path) -> dict[str, Any]:
    """Read fixed checkpoint files without following any stored stage/output paths."""
    if is_link(job.lstat()):
        raise ValueError("build job must not be a link")
    path = job / "build.json"
    if is_link(path.lstat()) or path.stat().st_size > 1024**2:
        raise ValueError("unsafe build state")
    state = json.loads(path.read_text(encoding="utf-8"))
    result = {key: state.get(key) for key in ("phase", "fingerprint", "output", "build_id")}
    result["kind"] = "build"
    path = job / "dense-progress.json"
    if path.exists():
        if is_link(path.lstat()) or path.stat().st_size > 4096:
            raise ValueError("unsafe dense checkpoint")
        progress = json.loads(path.read_text(encoding="utf-8"))
        if not 0 <= progress["next_row"] <= progress["count"]:
            raise ValueError("invalid dense checkpoint progress")
        result["completed_embedding_chunks"] = progress["next_row"]
        result["total_embedding_chunks"] = progress["count"]
    path = job / "ann-progress.json"
    if path.exists():
        if is_link(path.lstat()) or path.stat().st_size > 65536:
            raise ValueError("unsafe ANN checkpoint")
        progress = json.loads(path.read_text(encoding="utf-8"))
        result["completed_ann_chunks"] = sum(row["rows"] for row in progress["shards"])
        result["total_ann_chunks"] = progress["rows"]
    return result
