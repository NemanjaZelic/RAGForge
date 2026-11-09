"""Parallel inference preserves original batch tensors, logits and caller ordering."""

import hashlib
import threading
import time

import numpy as np
import pytest

from ragforge.core.rerank import ONNXReranker


def fingerprint(values):
    return tuple(
        (key, array.shape, hashlib.sha256(array.tobytes()).hexdigest())
        for key, array in sorted(values.items())
    )


def test_parallel_batches_preserve_all_inputs_logits_and_order(tiny_reranker):
    passages = ["transaction " * (i + 1) + "token" for i in range(24)]
    serial = ONNXReranker(tiny_reranker, threads=4, workers=1)
    parallel = ONNXReranker(tiny_reranker, threads=4, workers=4)
    serial.spec = serial.spec.model_copy(update={"batch_size": 2})
    parallel.spec = parallel.spec.model_copy(update={"batch_size": 2})
    batches = {"serial": [], "parallel": []}
    lock = threading.Lock()
    active = peak = 0
    ready = threading.Barrier(4, timeout=10)

    class Capture:
        def __init__(self, session, name):
            self.session, self.name = session, name

        def run(self, output_names, values):
            nonlocal active, peak
            with lock:
                batches[self.name].append(fingerprint(values))
                number = len(batches[self.name])
                active += 1
                peak = max(active, peak)
            try:
                if self.name == "parallel" and number <= 4:
                    ready.wait()
                    time.sleep((4 - number) * 0.01)
                return self.session.run(output_names, values)
            finally:
                with lock:
                    active -= 1

    serial.session = Capture(serial.session, "serial")
    parallel.session = Capture(parallel.session, "parallel")
    expected = serial.score("rollback token", passages)
    actual = parallel.score("rollback token", passages)
    assert actual == expected
    assert len(actual) == len(passages)
    assert len(set(actual)) > 4  # Restoring the original slots is observable.
    assert sorted(batches["serial"]) == sorted(batches["parallel"])
    assert 1 < peak <= 4
    assert parallel.tokenizer.truncation is None


@pytest.mark.parametrize("workers", [0, 9, True, 1.5])
def test_invalid_worker_configuration_is_rejected(tiny_reranker, workers):
    with pytest.raises(ValueError, match="workers"):
        ONNXReranker(tiny_reranker, workers=workers)


def test_worker_budget_and_error_recovery(tiny_reranker):
    model = ONNXReranker(tiny_reranker, threads=2, workers=8)
    assert model.workers == 2
    assert model.session.get_session_options().intra_op_num_threads == 1
    model.spec = model.spec.model_copy(update={"batch_size": 2})
    actual_session = model.session

    class Invalid:
        def run(self, outputs, values):
            return [np.zeros((len(values["input_ids"]), 2))]

    model.session = Invalid()
    with pytest.raises(ValueError, match="logits"):
        model.score("rollback", ["transaction token"] * 12)
    assert model.tokenizer.truncation is None
    model.session = actual_session
    assert len(model.score("rollback", ["transaction token"] * 12)) == 12


def test_cli_serial_parallel_options_keep_exact_offline_response(
    tmp_path, tiny_reranker, offline_cli
):
    import json
    from pathlib import Path

    from ragforge.artifacts.builder import build_bundle

    corpus = Path(__file__).resolve().parents[1] / "examples/mini-docs"
    bundle = tmp_path / "bundle"
    build_bundle(corpus, bundle, profile="minimal", reranker_directory=tiny_reranker)
    base = ["use", str(bundle), "--query", "rollback token", "--rerank", "--threads", "4"]
    serial = offline_cli([*base, "--rerank-workers", "1"])
    parallel = offline_cli([*base, "--rerank-workers", "4"])
    assert serial.returncode == parallel.returncode == 0, (serial.stderr, parallel.stderr)
    assert json.loads(serial.stdout) == json.loads(parallel.stdout)
