"""Measured process memory; no claims about unsampled aggregate system peaks."""

import os
import sys
from typing import TypedDict


class ProcessMemory(TypedDict):
    pid: int
    rss_bytes: int | None
    peak_rss_bytes: int | None
    private_committed_bytes: int | None


def process_memory() -> ProcessMemory:
    result: ProcessMemory = {
        "pid": os.getpid(),
        "rss_bytes": None,
        "peak_rss_bytes": None,
        "private_committed_bytes": None,
    }
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "peak_rss",
                    "rss",
                    "peak_paged",
                    "paged",
                    "peak_nonpaged",
                    "nonpaged",
                    "pagefile",
                    "peak_pagefile",
                    "private",
                )
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        kernel.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if kernel.K32GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            result["rss_bytes"] = int(counters.rss)
            result["peak_rss_bytes"] = int(counters.peak_rss)
            result["private_committed_bytes"] = int(counters.private)

    elif sys.platform.startswith("linux"):
        import resource
        from pathlib import Path

        result["peak_rss_bytes"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                result["rss_bytes"] = int(line.split()[1]) * 1024
    return result
