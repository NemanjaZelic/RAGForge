"""Checkpoint sharing failures must not abort resumable jobs or corrupt prior state."""

import ctypes
import errno
import json
import os

import pytest

from ragforge.jobs import build


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_transient_windows_sharing_error_retries_same_complete_payload(
    tmp_path, monkeypatch, winerror
):
    path = tmp_path / "status.json"
    path.write_text('{"old": true}', encoding="utf-8")
    original = build.os.replace
    attempts = []
    sleeps = []

    def replace(source, target):
        attempts.append(source)
        assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
        assert json.loads(build.Path(source).read_text(encoding="utf-8")) == {"new": True}
        if len(attempts) < 3:
            error = PermissionError(errno.EACCES, "sharing denied")
            error.winerror = winerror
            raise error
        original(source, target)

    monkeypatch.setattr(build.os, "replace", replace)
    monkeypatch.setattr(build.time, "sleep", sleeps.append)
    build.atomic_json(path, {"new": True})
    assert len(attempts) == 3 and len(set(attempts)) == 1
    assert sleeps == [0.02, 0.04]
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    assert list(tmp_path.iterdir()) == [path]


def test_persistent_windows_denial_is_bounded_and_keeps_old_checkpoint(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    path.write_text('{"old": true}', encoding="utf-8")
    attempts = []
    sleeps = []

    def denied(source, target):
        attempts.append(source)
        error = PermissionError(errno.EACCES, "persistent denial")
        error.winerror = 5
        raise error

    monkeypatch.setattr(build.os, "replace", denied)
    monkeypatch.setattr(build.time, "sleep", sleeps.append)
    with pytest.raises(PermissionError, match="persistent denial"):
        build.atomic_json(path, {"new": True})
    assert len(attempts) == 8 and len(sleeps) == 7 and sum(sleeps) < 2
    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert list(tmp_path.iterdir()) == [path]


def test_non_windows_permission_error_is_not_retried(tmp_path, monkeypatch):
    attempts = []
    sleeps = []

    def denied(source, target):
        attempts.append(source)
        raise PermissionError(errno.EACCES, "ordinary permission failure")

    monkeypatch.setattr(build.os, "replace", denied)
    monkeypatch.setattr(build.time, "sleep", sleeps.append)
    with pytest.raises(PermissionError, match="ordinary permission failure"):
        build.atomic_json(tmp_path / "status.json", {"new": True})
    assert len(attempts) == 1 and not sleeps and not list(tmp_path.iterdir())


@pytest.mark.skipif(os.name != "nt", reason="Windows file-sharing integration")
def test_actual_windows_reader_lock_recovers_after_reader_closes(tmp_path, monkeypatch):
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    path = tmp_path / "status.json"
    path.write_text('{"old": true}', encoding="utf-8")
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    sleeps = []

    def unlock(seconds):
        nonlocal handle
        sleeps.append(seconds)
        if handle is not None:
            assert kernel.CloseHandle(handle)
            handle = None

    monkeypatch.setattr(build.time, "sleep", unlock)
    try:
        build.atomic_json(path, {"new": True})
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
    assert sleeps == [0.02]
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    assert list(tmp_path.iterdir()) == [path]
