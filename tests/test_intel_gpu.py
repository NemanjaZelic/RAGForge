"""Optional GPU contracts: no analytics, external reads or unsafe buffer reuse."""

import importlib
import json
import sys
from queue import Queue
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from ragforge.core import intel_gpu
from ragforge.core.rerank import ONNXReranker, reranker_spec


@pytest.mark.parametrize("preloaded", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_sdk_import_forces_noop_telemetry_and_restores_process(monkeypatch, preloaded, fail):
    original = ModuleType("openvino_telemetry")
    if preloaded:
        monkeypatch.setitem(sys.modules, "openvino_telemetry", original)
    else:
        monkeypatch.delitem(sys.modules, "openvino_telemetry", raising=False)
    before = list(sys.meta_path)
    sdk = ModuleType("openvino")

    def load(name):
        assert name == "openvino"
        assert "openvino_telemetry" not in sys.modules
        with pytest.raises(ModuleNotFoundError):
            sys.meta_path[0].find_spec("openvino_telemetry", None)
        with pytest.raises(ModuleNotFoundError):
            sys.meta_path[0].find_spec("openvino_telemetry.backend", None)
        if fail:
            raise ImportError("missing optional SDK")
        return sdk

    monkeypatch.setattr(intel_gpu, "import_module", load)
    if fail:
        with pytest.raises(ValueError, match="runtime is unavailable"):
            intel_gpu.gpu_runtime()
    else:
        assert intel_gpu.gpu_runtime() is sdk
    assert sys.meta_path == before
    assert sys.modules.get("openvino_telemetry") is (original if preloaded else None)


def test_missing_gpu_is_explicit_and_enumerated_gpu_is_accepted(monkeypatch):
    devices = ["CPU"]
    monkeypatch.setattr(
        intel_gpu,
        "gpu_runtime",
        lambda: SimpleNamespace(Core=lambda: SimpleNamespace(available_devices=devices)),
    )
    with pytest.raises(ValueError, match="No supported"):
        intel_gpu.check_gpu_available()
    devices.append("GPU.0")
    intel_gpu.check_gpu_available()


@pytest.mark.parametrize("kind", ["external", "nested", "training", "invalid"])
def test_reject_untrusted_graph_before_loading_sdk(tiny_reranker, monkeypatch, kind):
    import onnx
    from onnx import TensorProto, helper

    content = (tiny_reranker / "model.onnx").read_bytes()
    graph = onnx.load_model_from_string(content)
    if kind == "external":
        tensor = TensorProto(name="external", data_type=TensorProto.FLOAT, dims=[1])
        tensor.data_location = TensorProto.EXTERNAL
        tensor.external_data.add(key="location", value="outside.bin")
        graph.graph.initializer.append(tensor)
    elif kind == "nested":
        graph.graph.node.append(
            helper.make_node(
                "If", ["condition"], ["branch"], then_branch=helper.make_graph([], "nested", [], [])
            )
        )
    elif kind == "training":
        graph.training_info.add()
    content = b"invalid" if kind == "invalid" else graph.SerializeToString()

    def forbidden():
        raise AssertionError("must validate inline graph before importing SDK")

    monkeypatch.setattr(intel_gpu, "gpu_runtime", forbidden)
    with pytest.raises(ValueError, match="GPU reranker"):
        intel_gpu.OpenVINOSession(content, max_tokens=512, batch_size=8, requests=2)


def test_request_output_is_copied_and_slot_is_returned_on_error():
    buffer = np.array([[7.0]], dtype=np.float32)
    failure = False

    def infer(values):
        if failure:
            raise RuntimeError("device failure")
        return {"out": buffer}

    request = SimpleNamespace(infer=infer)
    session = object.__new__(intel_gpu.OpenVINOSession)
    session._output = "out"
    session._requests = Queue(maxsize=1)
    session._requests.put(request)
    result = session.run(None, {})[0]
    buffer[0, 0] = -4
    assert result[0, 0] == 7
    assert session._requests.qsize() == 1
    failure = True
    with pytest.raises(RuntimeError, match="device failure"):
        session.run(None, {})
    assert session._requests.qsize() == 1


def test_cpu_spec_keeps_legacy_serialization_and_gpu_dispatch(tiny_reranker, monkeypatch):
    spec = reranker_spec(tiny_reranker)
    assert "runtime" not in spec.model_dump()
    descriptor = tiny_reranker / "reranker.json"
    descriptor.write_text(
        spec.model_copy(update={"runtime": "openvino-gpu-f16"}).model_dump_json(), encoding="utf-8"
    )
    calls = []

    class Session:
        def __init__(self, content, **kwargs):
            calls.append(kwargs)

        def get_inputs(self):
            return [SimpleNamespace(name=n) for n in ("input_ids", "attention_mask")]

        def get_outputs(self):
            return [SimpleNamespace(shape=[None, 1])]

        def run(self, outputs, values):
            return [values["input_ids"].sum(axis=1, keepdims=True).astype(np.float32)]

    monkeypatch.setattr(intel_gpu, "OpenVINOSession", Session)
    model = ONNXReranker(tiny_reranker, threads=8, workers=8, cache_batches=0)
    assert model.workers == 2
    assert calls == [{"max_tokens": 512, "batch_size": 8, "requests": 2}]
    assert model.execution_optimization == "openvino-gpu-f16"
    assert len(model.score("warmup", ["warmup source"] * 9)) == 9


def test_gpu_setup_failed_smoke_preserves_active_state(
    tmp_path, tiny_model, tiny_reranker, monkeypatch
):
    monkeypatch.syspath_prepend(str(__import__("pathlib").Path(__file__).parents[1] / "scripts"))
    setup = importlib.import_module("setup_models")
    spec = reranker_spec(tiny_reranker).model_copy(update={"runtime": "openvino-gpu-f16"})
    monkeypatch.setattr(intel_gpu, "check_gpu_available", lambda: None)
    calls = []

    def prepare(destination, **kwargs):
        calls.append((destination.name, kwargs))
        return tiny_model if destination.name == "e5-small" else tiny_reranker

    monkeypatch.setattr(setup, "prepare", prepare)
    monkeypatch.setattr(setup, "reranker_spec", lambda path: spec)
    state = tmp_path / ".cache/quickstart/models.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"existing":"keep"}')
    before = state.read_bytes()

    class FailedSmoke:
        def __init__(self, *args, **kwargs):
            pass

        def score(self, *args):
            raise ValueError("GPU smoke failed")

    monkeypatch.setattr(setup, "ONNXReranker", FailedSmoke)
    with pytest.raises(ValueError, match="smoke failed"):
        setup.setup_models(
            tmp_path,
            tmp_path / "models",
            offline=True,
            document_language="en",
            accelerator="intel-gpu",
        )
    assert state.read_bytes() == before
    assert calls[1][0] == "ms-marco-minilm-gpu-reranker"
    assert calls[1][1]["script_args"] == ["--model", "minilm-l6-gpu"]
    with pytest.raises(ValueError, match="requires"):
        setup.setup_models(tmp_path, tmp_path / "models", accelerator="intel-gpu")
    assert state.read_bytes() == before


def test_gpu_manifest_identity_matches_descriptor(tiny_model, tiny_reranker, tmp_path, monkeypatch):
    from pathlib import Path

    from ragforge.artifacts.builder import build_bundle
    from ragforge.artifacts.verification import verify_bundle

    spec = reranker_spec(tiny_reranker).model_copy(update={"runtime": "openvino-gpu-f16"})
    (tiny_reranker / "reranker.json").write_text(spec.model_dump_json(), encoding="utf-8")
    bundle = tmp_path / "bundle"
    manifest = build_bundle(
        Path(__file__).parents[1] / "examples/mini-docs",
        bundle,
        model_directory=tiny_model,
        reranker_directory=tiny_reranker,
    )
    assert manifest.retrieval_configuration.reranker.runtime == "openvino-gpu-f16"
    verify_bundle(bundle)
    path = bundle / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["retrieval_configuration"]["reranker"]["runtime"] = "onnxruntime-cpu"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_bundle(bundle)


@pytest.mark.parametrize(
    "runtime,expected",
    [
        ("onnxruntime-cpu", ["graph", "reranker"]),
        ("openvino-gpu-f16", ["reranker", "graph"]),
    ],
)
def test_gpu_graph_pages_warmed_after_shared_memory_allocations(runtime, expected, monkeypatch):
    from ragforge.core.ann import AnnStore
    from ragforge.core.engine import BundleEngine

    events = []
    engine = object.__new__(BundleEngine)
    engine.manifest = SimpleNamespace(
        default_search_method="hybrid",
        retrieval_configuration=SimpleNamespace(
            query_language="en", reranker=SimpleNamespace(runtime=runtime)
        ),
    )
    engine._parents = None
    engine._embedder = SimpleNamespace(encode=lambda *a, **k: np.zeros((1, 4), dtype=np.float32))
    engine._dense = object.__new__(AnnStore)
    monkeypatch.setattr(engine._dense, "warm_up", lambda vector: events.append("graph"))
    monkeypatch.setattr(engine, "_prepare_dense", lambda: None)
    model = SimpleNamespace(
        spec=SimpleNamespace(batch_size=8, max_tokens=512),
        workers=2,
        score=lambda *a: events.append("reranker"),
    )
    monkeypatch.setattr(engine, "_get_reranker", lambda: model)
    assert engine.warm_up() == {"query_model": True, "dense_index": True, "reranker": True}
    assert events == expected
