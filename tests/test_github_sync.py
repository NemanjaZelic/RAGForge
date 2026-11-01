import runpy
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.mark.parametrize("fault", ["public", "wrong_account", "wrong_repo", "dirty", "origin"])
def test_sync_never_pushes_when_preconditions_fail(
    fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/github_sync.py"))
    main = scope["main"]
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        if args[0] == "branch":
            return "main"
        if args[0] == "status":
            return " M README.md" if fault == "dirty" else ""
        if args == ("remote",):
            return "origin" if fault == "origin" else ""
        if args[0] == "remote":
            return "https://github.com/someone/unrelated.git"
        raise AssertionError("unexpected git write")

    def fake_api(token: str, path: str, data: object = None) -> dict[str, Any]:
        assert token == "fixture-only"
        assert data is None
        if path == "/user":
            return {"login": "other" if fault == "wrong_account" else "NemanjaZelic"}
        return {
            "private": fault != "public",
            "visibility": "public" if fault == "public" else "private",
            "full_name": "other/project" if fault == "wrong_repo" else "NemanjaZelic/RAGForge",
            "size": 0,
        }

    monkeypatch.setitem(main.__globals__, "git", fake_git)
    monkeypatch.setitem(main.__globals__, "credential", lambda: "fixture-only")
    monkeypatch.setitem(main.__globals__, "api", fake_api)
    monkeypatch.setattr(sys, "argv", ["github_sync.py", "--push"])
    assert main() == 2
    assert not any(call[0] == "push" or call[:2] == ("remote", "add") for call in calls)


def test_sync_verifies_private_push_and_remote_head(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/github_sync.py"))
    main = scope["main"]
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        if args[0] == "branch":
            return "main"
        if args[0] == "rev-parse":
            return "a" * 40
        if args[0] == "ls-remote":
            return "a" * 40 + "\trefs/heads/main"
        return ""

    def fake_api(token: str, path: str, data: object = None) -> dict[str, Any]:
        if path == "/user":
            return {"login": "NemanjaZelic"}
        return {"private": True, "visibility": "private", "full_name": "NemanjaZelic/RAGForge"}

    monkeypatch.setitem(main.__globals__, "git", fake_git)
    monkeypatch.setitem(main.__globals__, "credential", lambda: "fixture-only")
    monkeypatch.setitem(main.__globals__, "api", fake_api)
    monkeypatch.setattr(sys, "argv", ["github_sync.py", "--push"])
    assert main() == 0
    assert ("push", "--set-upstream", "origin", "main") in calls
    assert ("ls-remote", "origin", "refs/heads/main") in calls
