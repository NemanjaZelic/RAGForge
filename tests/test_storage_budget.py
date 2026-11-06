"""Logical storage accounting remains exact while directory scans get cheaper."""

import contextlib
import stat
from types import SimpleNamespace

import pytest

from ragforge.jobs import budget as module
from ragforge.jobs.budget import StorageBudget


def test_nested_logical_bytes_accounting_and_allocation_limit(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.bin").write_bytes(b"abc")
    (tmp_path / "nested" / "same-content.bin").write_bytes(b"abc")
    (tmp_path / "nested" / "empty.bin").touch()
    budget = StorageBudget(tmp_path, limit_bytes=10, reserve_free_bytes=0)
    assert budget.check(4) == 6
    with pytest.raises(ValueError, match="storage budget"):
        budget.check(5)
    budget.account(2)
    assert budget.check(2) == 8
    with pytest.raises(ValueError, match="storage budget"):
        budget.check(3)


def test_fresh_enumeration_keeps_original_thirty_second_refresh(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    path = tmp_path / "data.bin"
    path.write_bytes(b"abc")
    budget = StorageBudget(tmp_path, limit_bytes=100, reserve_free_bytes=0)
    assert budget.check() == 3
    path.write_bytes(b"0123456789")
    (tmp_path / "new.bin").write_bytes(b"new")
    now[0] = 129.9
    assert budget.check() == 3
    now[0] = 130.0
    assert budget.check() == 13
    path.write_bytes(b"a")
    assert budget.check(refresh=True) == 4


def test_reserved_free_space_and_unreadable_tree_fail_closed(tmp_path, monkeypatch):
    budget = StorageBudget(tmp_path, limit_bytes=100, reserve_free_bytes=8)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=10))
    with pytest.raises(ValueError, match="reserved free"):
        budget.check(3)

    def denied(_):
        raise PermissionError("directory denied")

    monkeypatch.setattr(module.os, "scandir", denied)
    with pytest.raises(PermissionError, match="directory denied"):
        budget.check(refresh=True)


@pytest.mark.parametrize("directory", [False, True])
def test_file_and_directory_links_are_rejected(tmp_path, directory):
    root = tmp_path / "budget"
    root.mkdir()
    target = tmp_path / "outside"
    if directory:
        target.mkdir()
        (target / "data.bin").write_bytes(b"data")
    else:
        target.write_bytes(b"data")
    try:
        (root / "link").symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("creating links requires local privileges")
    with pytest.raises(ValueError, match="links are forbidden"):
        StorageBudget(root, reserve_free_bytes=0).check()


def test_concurrently_removed_entry_fails_closed(tmp_path, monkeypatch):
    (tmp_path / "keep.bin").write_bytes(b"keep")
    (tmp_path / "transient.bin").write_bytes(b"gone")
    original = module.os.scandir

    class Vanished:
        def stat(self, *, follow_symlinks):
            assert follow_symlinks is False
            (tmp_path / "transient.bin").unlink()
            raise FileNotFoundError("retired during scan")

    @contextlib.contextmanager
    def entries(path):
        with original(path) as scan:
            yield (Vanished() if entry.name == "transient.bin" else entry for entry in scan)

    monkeypatch.setattr(module.os, "scandir", entries)
    with pytest.raises(FileNotFoundError, match="retired during scan"):
        StorageBudget(tmp_path, reserve_free_bytes=0).check()


@pytest.mark.parametrize("directory", [False, True])
def test_windows_reparse_metadata_is_rejected(tmp_path, monkeypatch, directory):
    info = SimpleNamespace(
        st_mode=stat.S_IFDIR if directory else stat.S_IFREG,
        st_size=999,
        st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
    )
    entry = SimpleNamespace(stat=lambda *, follow_symlinks: info)

    @contextlib.contextmanager
    def entries(_):
        yield iter([entry])

    monkeypatch.setattr(module.os, "scandir", entries)
    with pytest.raises(ValueError, match="links are forbidden"):
        StorageBudget(tmp_path, reserve_free_bytes=0).check()
