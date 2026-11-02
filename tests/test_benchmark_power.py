import importlib.util
import json
from pathlib import Path

import pytest


def test_idle_sleep_request_is_released_after_completion_and_status_failure(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/keep_benchmark_awake.py"
    spec = importlib.util.spec_from_file_location("keep_benchmark_awake", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Request:
        def __init__(self):
            self.acquired = self.restored = False

        def acquire(self):
            self.acquired = True

        def restore(self):
            self.restored = True

        def alive(self):
            return True

    status = tmp_path / "status.json"
    status.write_text('{"state":"running"}', encoding="utf-8")
    request = Request()

    def complete(_):
        status.write_text('{"state":"complete_diagnostic_draft_labels"}', encoding="utf-8")

    assert module.watch(tmp_path, 1, request=request, wait=complete) == "released"
    assert request.acquired and request.restored
    request = Request()
    status.write_text("invalid JSON", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        module.watch(tmp_path, 1, request=request)
    assert request.restored
