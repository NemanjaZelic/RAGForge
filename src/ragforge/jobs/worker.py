"""Private JSON-lines parsing worker with OS process memory and parent wall deadline."""

import argparse
import ctypes
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from ragforge.core.parse import ParsedDocument, TextOptions, load_document
from ragforge.core.pdf import PdfOptions
from ragforge.core.scan import ScanLimits, ScannedDocument

_JOB_HANDLE: Any = None


def limit_memory(mebibytes: int) -> None:
    """Set an actual OS allocation/address-space limit, not an RSS estimate."""
    global _JOB_HANDLE
    limit = mebibytes * 1024**2
    if sys.platform == "win32":
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("min_ws", ctypes.c_size_t),
                ("max_ws", ctypes.c_size_t),
                ("processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Io(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "reads",
                    "writes",
                    "other",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", Io),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        handle = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY, committed bytes
        info.process_memory = limit
        if (
            not handle
            or not kernel.SetInformationJobObject(
                handle, 9, ctypes.byref(info), ctypes.sizeof(info)
            )
            or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())
        ):
            raise OSError("cannot apply Windows worker process memory limit")
        _JOB_HANDLE = handle  # Keep the job alive for this process's lifetime.
    elif sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    else:
        raise RuntimeError("bounded parsing workers support Windows and Linux")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-mib", type=int, default=512)
    args = parser.parse_args()
    if not 128 <= args.memory_mib <= 4096:
        raise ValueError("worker memory must be 128..4096 MiB")
    limit_memory(args.memory_mib)
    adapter = TypeAdapter(ParsedDocument)
    for line in sys.stdin:
        try:
            task = json.loads(line)
            record = ScannedDocument.model_validate(task["record"])
            document = load_document(
                Path(task["root"]),
                task["collection_id"],
                record,
                ScanLimits(**task["scan_limits"]),
                pdf_options=PdfOptions.model_validate(task["pdf_options"]),
                pdf_backend=task["pdf_backend"],
                text_options=TextOptions.model_validate(task.get("text_options", {})),
                allow_permitted_pdf=task.get("allow_permitted_pdf", False),
            )
            result = {"document": adapter.dump_python(document, mode="json")}
        except Exception as error:
            result = {"error": type(error).__name__ + ": " + str(error)[:2000]}
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
