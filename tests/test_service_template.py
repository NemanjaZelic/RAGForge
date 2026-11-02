import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    shutil.which("systemd-analyze") is None, reason="systemd syntax tool unavailable"
)
def test_linux_service_example_passes_native_syntax_verification(tmp_path):
    source = Path(__file__).resolve().parents[1] / "deploy/systemd/ragforge.service"
    content = source.read_text(encoding="utf-8-sig")
    executable = str(Path(sys.executable).absolute()).replace("%", "%%").replace('"', '\\"')
    content = content.replace("/opt/ragforge/.venv/bin/python", '"' + executable + '"')
    content = content.replace("User=ragforge", "User=" + str(os.getuid()))
    content = content.replace("Group=ragforge", "Group=" + str(os.getgid()))
    target = tmp_path / "ragforge.service"
    target.write_text(content, encoding="utf-8")
    result = subprocess.run(
        ["systemd-analyze", "verify", "--man=no", str(target)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
