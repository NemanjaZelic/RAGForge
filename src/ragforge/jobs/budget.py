"""Aggregate logical-byte budget checked before writes; not an OS filesystem quota."""

import os
import shutil
import time
from pathlib import Path

from ragforge.core.source import is_link


class StorageBudget:
    def __init__(
        self,
        root: Path,
        *,
        limit_bytes: int = 65_000_000_000,
        reserve_free_bytes: int = 15_000_000_000,
    ) -> None:
        if limit_bytes < 1 or reserve_free_bytes < 0:
            raise ValueError("invalid storage budget")
        if is_link(root.lstat()) or not root.is_dir():
            raise ValueError("storage root must be a real directory")
        self.root = root.resolve(strict=True)
        self.limit = limit_bytes
        self.reserve = reserve_free_bytes
        self.used = 0
        self.refreshed = float("-inf")

    def check(self, planned_bytes: int = 0, *, refresh: bool = False) -> int:
        if planned_bytes < 0:
            raise ValueError("planned allocation must be nonnegative")
        if refresh or time.monotonic() - self.refreshed >= 30:
            total = 0
            for parent, dirs, files in os.walk(self.root, followlinks=False):
                file_names = set(files)
                for name in dirs + files:
                    path = Path(parent) / name
                    info = path.lstat()
                    if is_link(info):
                        raise ValueError("links are forbidden in benchmark storage")
                    if name in file_names:
                        total += info.st_size
            self.used = total
            self.refreshed = time.monotonic()
        if self.used + planned_bytes > self.limit:
            raise ValueError("aggregate benchmark storage budget exceeded before allocation")
        if shutil.disk_usage(self.root).free - planned_bytes < self.reserve:
            raise ValueError("allocation would consume reserved free disk space")
        return self.used

    def account(self, allocated_bytes: int) -> None:
        self.used += max(0, allocated_bytes)
