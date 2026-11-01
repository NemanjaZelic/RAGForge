import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from model_fixtures import tiny_model as tiny_model


@pytest.fixture
def offline_cli(tmp_path: Path) -> Callable[[list[str]], subprocess.CompletedProcess[str]]:
    guard = tmp_path / "sitecustomize.py"
    guard.write_text(
        "import socket,os,builtins\n"
        "original_import = builtins.__import__\n"
        "def guarded_import(name, *args, **kwargs):\n"
        "    denied = {'numpy','onnxruntime','onnx','tokenizers','huggingface_hub'}\n"
        "    if os.getenv('RAGFORGE_FORBID_ML_IMPORTS') and name.split('.')[0] in denied:\n"
        "        raise AssertionError('ML import forbidden: ' + name)\n"
        "    return original_import(name, *args, **kwargs)\n"
        "builtins.__import__ = guarded_import\n"
        "RAGFORGE_OFFLINE_GUARD = True\n"
        "def blocked(*args, **kwargs):\n"
        "    raise RuntimeError('network forbidden by test')\n"
        "class BlockedSocket(socket.socket):\n"
        "    def __init__(self, *args, **kwargs):\n"
        "        blocked()\n"
        "socket.socket = BlockedSocket\n"
        "socket.create_connection = blocked\n"
        "socket.getaddrinfo = blocked\n"
        "socket.gethostbyname = blocked\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}

    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import sitecustomize,socket; assert sitecustomize.RAGFORGE_OFFLINE_GUARD; "
                "assert socket.getaddrinfo is sitecustomize.blocked; "
                "assert socket.socket is sitecustomize.BlockedSocket; "
                "from ragforge.cli import app; app()",
                *command,
            ],
            env={
                **env,
                **{k: v for k, v in os.environ.items() if k == "RAGFORGE_FORBID_ML_IMPORTS"},
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    return run
