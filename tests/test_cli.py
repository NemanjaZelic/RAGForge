import json
import subprocess
from collections.abc import Callable
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


def test_doctor_reports_implemented_bundle_and_search_methods() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["fts5"] is True
    assert report["retrieval_implemented"] is True
    assert report["bundle_implemented"] is True
    assert report["mcp_stdio_implemented"] is True
    assert report["mcp_dependency_available"] is True
    assert report["retrieval_methods"] == ["bm25", "dense", "hybrid"]
    assert report["balanced_dependencies_available"] is True


@pytest.mark.parametrize(
    "name",
    [
        "manifest",
        "retrieve-request",
        "retrieval-response",
        "shared-policy",
        "shared-connection",
        "web-sources",
    ],
)
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
    offline_cli: Callable[[list[str]], subprocess.CompletedProcess[str]],
    command: list[str],
) -> None:
    # Python socket/DNS guard, not an OS network sandbox.
    result = offline_cli(command)
    assert result.returncode == 0, result.stderr
    assert "network forbidden" not in result.stderr
