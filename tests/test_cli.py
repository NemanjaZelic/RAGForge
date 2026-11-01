import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ragforge import __version__
from ragforge.cli import app

runner = CliRunner()


def test_help_and_version_are_real_commands() -> None:
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "doctor" in help_result.output
    assert "schema" in help_result.output
    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0
    assert version.output.strip() == __version__


def test_doctor_checks_fts5_without_claiming_retrieval() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["fts5"] is True
    assert report["retrieval_implemented"] is False


@pytest.mark.parametrize("name", ["manifest", "retrieve-request", "retrieval-response"])
def test_schema_is_machine_readable(name: str) -> None:
    result = runner.invoke(app, ["schema", name])
    assert result.exit_code == 0
    schema = json.loads(result.output)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "command",
    [
        ["--help"],
        ["doctor"],
        ["schema", "manifest"],
        ["scan", str(Path(__file__).resolve().parents[1] / "examples/mini-docs")],
        ["chunk", str(Path(__file__).resolve().parents[1] / "examples/mini-docs")],
        ["chunk", str(Path(__file__).resolve().parent / "fixtures/pdf")],
    ],
)
def test_cli_subprocess_with_network_calls_blocked(
    tmp_path: Path,
    command: list[str],
) -> None:
    # This is a Python network-call guard, not an OS-level network namespace.
    guard = tmp_path / "sitecustomize.py"
    guard.write_text(
        "import socket\n"
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
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sitecustomize; assert sitecustomize.RAGFORGE_OFFLINE_GUARD; "
            "from ragforge.cli import app; app()",
            *command,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "network forbidden" not in result.stderr
