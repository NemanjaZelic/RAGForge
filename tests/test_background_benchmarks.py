"""Background plans preserve frozen inputs and never run during validation."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "background_benchmarks", ROOT / "scripts/background_benchmarks.py"
)
background = importlib.util.module_from_spec(spec)
spec.loader.exec_module(background)


@pytest.fixture
def local_project(tmp_path: Path):
    root = tmp_path / "project with spaces"
    for folder in [
        ".venv/Scripts",
        "scripts",
        "models/test",
        "data/benchmarks/scale-v1/runs/execution-v1",
        "data/benchmarks/scale-v1/runs/cases",
        "data/benchmarks/scale-v1/runs/pdf",
        "data/benchmarks/scale-v1/runs/quality-v1/full-rfc-rebuild-v1",
    ]:
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / ".venv/Scripts/python.exe").write_bytes(b"")
    run = root / "data/benchmarks/scale-v1/runs/execution-v1"
    frozen = run / "runtime.py"
    frozen.write_text("print('frozen')", encoding="utf-8")
    recipe = {
        "root": str(root / "data/benchmarks/scale-v1"),
        "model": str(root / "models/test"),
        "cases": str(run.parent / "cases"),
        "pdf_cache": str(run.parent / "pdf"),
        "budget_root": str(root / "data/benchmarks"),
        "reserve_free_bytes": 15000000000,
        "runtime_sha256": {"runtime.py": hashlib.sha256(frozen.read_bytes()).hexdigest()},
    }
    (run / "recipe.json").write_text(json.dumps(recipe), encoding="utf-8")
    quality = run.parent / "quality-v1/full-rfc-rebuild-v1"
    (quality / "runtime.py").write_bytes(frozen.read_bytes())
    (quality / "configuration.json").write_text(
        json.dumps({"frozen_sha256": recipe["runtime_sha256"], "publish_private": True}),
        encoding="utf-8",
    )
    return root, run, quality


def test_plan_reuses_owned_commands_and_resume_without_publication(local_project):
    root, run, quality = local_project
    plans = background.make_plan(root, "both", False)
    assert [p["name"] for p in plans] == ["scale", "rfc-rebuild"]
    assert "--resume" in plans[0]["command"]
    assert plans[0]["command"][0] == str(root / ".venv/Scripts/python.exe")
    assert str(run) in plans[0]["command"]
    assert plans[1]["command"][-2:] == ["--child", str(quality / "configuration.json")]
    assert all("publisher" not in p for p in plans)
    assert not (root / ".cache").exists()


def test_publication_requires_explicit_scale_option(local_project):
    root, _, _ = local_project
    plan = background.make_plan(root, "scale", True)[0]
    assert plan["publisher"][-2:] == ["--branch", "results/scale-v1"]
    assert "--watch" in plan["publisher"]


def test_tampered_frozen_runtime_stops_before_start(local_project):
    root, run, _ = local_project
    (run / "runtime.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="runtime changed"):
        background.make_plan(root, "both", False)


def test_frozen_inventory_cannot_escape_run(local_project):
    _, run, _ = local_project
    (run.parent / "outside.py").write_text("outside", encoding="utf-8")
    with pytest.raises(ValueError, match="inside its run"):
        background.verify_frozen(
            run, {"runtime_sha256": {"../outside.py": "f" * 64}}, "runtime_sha256"
        )


def test_input_paths_cannot_escape_project(local_project, tmp_path):
    root, run, _ = local_project
    recipe = json.loads((run / "recipe.json").read_text(encoding="utf-8"))
    recipe["model"] = str(tmp_path)
    (run / "recipe.json").write_text(json.dumps(recipe), encoding="utf-8")
    with pytest.raises(ValueError, match="input must stay"):
        background.make_plan(root, "scale", False)


def test_check_mode_never_launches_process(local_project, monkeypatch, capsys):
    root, _, _ = local_project
    monkeypatch.setattr(background, "ROOT", root)
    monkeypatch.setattr(background.sys, "argv", ["background_benchmarks", "--check"])
    monkeypatch.setattr(
        background.subprocess, "Popen", lambda *a, **k: pytest.fail("validation launched a process")
    )
    background.main()
    assert json.loads(capsys.readouterr().out)["starts_processes"] is False
