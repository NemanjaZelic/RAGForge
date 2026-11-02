"""Opt-in, process-scoped Windows idle-sleep request for a running benchmark controller."""

import argparse
import ctypes
import json
import sys
import time
from pathlib import Path


class WindowsRequest:
    def __init__(self, pid):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        self.kernel.OpenProcess.restype = ctypes.c_void_p
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.kernel.WaitForSingleObject.restype = ctypes.c_uint32
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
        self.kernel.SetThreadExecutionState.restype = ctypes.c_uint32
        self.handle = self.kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only.
        if not self.handle:
            raise OSError("cannot monitor benchmark controller process")
        self.previous = None

    def acquire(self):
        if not self.alive():
            self.restore()
            raise ValueError("benchmark controller already exited")
        self.previous = self.kernel.SetThreadExecutionState(0x80000001)
        if not self.previous:
            self.restore()
            raise OSError("cannot request Windows system activity")

    def alive(self):
        return self.kernel.WaitForSingleObject(self.handle, 0) == 258  # WAIT_TIMEOUT

    def restore(self):
        try:
            if self.previous:
                self.kernel.SetThreadExecutionState(0x80000000)
        finally:
            if self.handle:
                self.kernel.CloseHandle(self.handle)
                self.handle = None


def watch(run, controller_pid, *, request=None, wait=time.sleep):
    if request is None:
        if sys.platform != "win32":
            return "not_required_on_this_platform"
        request = WindowsRequest(controller_pid)
    request.acquire()
    print(json.dumps({"sleep_guard": "active", "controller_pid": controller_pid}), flush=True)
    try:
        while request.alive():
            path = run / "status.json"
            if path.stat().st_size > 1024**2:
                raise ValueError("unexpected benchmark status size")
            status = json.loads(path.read_text(encoding="utf-8"))
            if status.get("state") != "running":
                break
            wait(30)
    finally:
        request.restore()
        print(json.dumps({"sleep_guard": "released"}), flush=True)
    return "released"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--controller-pid", type=int, required=True)
    args = parser.parse_args()
    watch(args.run, args.controller_pid)


if __name__ == "__main__":
    main()
