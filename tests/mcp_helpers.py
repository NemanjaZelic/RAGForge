"""Actual stdio subprocesses with network denied, allowing event-loop socketpair IPC."""

import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

GUARD = r"""
import builtins, os, socket
RAGFORGE_MCP_GUARD = True
_original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if os.getenv('RAGFORGE_FORBID_ML_IMPORTS') and name.split('.')[0] in {
        'numpy', 'onnxruntime', 'onnx', 'tokenizers', 'huggingface_hub'
    }:
        raise AssertionError('ML import forbidden: ' + name)
    return _original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
def blocked(*args, **kwargs):
    raise RuntimeError('network forbidden by MCP test')
_pair_depth = 0
_original_pair = socket.socketpair
class GuardedSocket(socket.socket):
    def connect(self, *args, **kwargs):
        if not _pair_depth:
            blocked()
        return super().connect(*args, **kwargs)
    def connect_ex(self, *args, **kwargs):
        if not _pair_depth:
            blocked()
        return super().connect_ex(*args, **kwargs)
    def bind(self, *args, **kwargs):
        if not _pair_depth:
            blocked()
        return super().bind(*args, **kwargs)
    def listen(self, *args, **kwargs):
        if not _pair_depth:
            blocked()
        return super().listen(*args, **kwargs)
    sendto = blocked
    if hasattr(socket.socket, "sendmsg"):
        sendmsg = blocked
def socketpair(*args, **kwargs):
    global _pair_depth
    _pair_depth += 1
    try:
        return _original_pair(*args, **kwargs)
    finally:
        _pair_depth -= 1
socket.socket = GuardedSocket
socket.socketpair = socketpair
socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.gethostbyname = blocked
socket.gethostbyname_ex = blocked
"""


def offline_client(
    artifact: Path,
    directory: Path,
    *,
    forbid_ml: bool = False,
    mode: str = "auto",
    warm_up: bool = False,
) -> Client:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sitecustomize.py").write_text(GUARD, encoding="utf-8")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-c",
            "import sitecustomize,socket; assert sitecustomize.RAGFORGE_MCP_GUARD; "
            "assert socket.getaddrinfo is sitecustomize.blocked; "
            "assert socket.socket is sitecustomize.GuardedSocket; "
            "from ragforge.cli import app; app()",
            "serve",
            str(artifact),
            *(["--warm-up"] if warm_up else []),
        ],
        env={
            "PYTHONPATH": str(directory),
            "PYTHONIOENCODING": "utf-8",
            "RAGFORGE_FORBID_ML_IMPORTS": "1" if forbid_ml else "",
            "OTEL_SDK_DISABLED": "true",
        },
        cwd=str(directory),
    )
    return Client(parameters, read_timeout_seconds=20, mode=mode)
