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
    assert calls == [{"max_tokens": 512, "batch_size": 4, "requests": 2}]
    assert model.spec.batch_size == 8
    assert model.execution_batch_size == 4
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
        execution_batch_size=4 if runtime == "openvino-gpu-f16" else 8,
        workers=2,
        score=lambda *a: events.append("reranker"),
    )
    monkeypatch.setattr(engine, "_get_reranker", lambda: model)
    assert engine.warm_up() == {"query_model": True, "dense_index": True, "reranker": True}
    assert events == expected


@pytest.mark.parametrize("declared", [1, 2, 4, 8])
def test_gpu_execution_batch_respects_package_limit_and_keeps_every_passage(
    tiny_reranker, monkeypatch, declared
):
    descriptor = tiny_reranker / "reranker.json"
    spec = reranker_spec(tiny_reranker)
    descriptor.write_text(
        spec.model_copy(
            update={"runtime": "openvino-gpu-f16", "batch_size": declared}
        ).model_dump_json(),
        encoding="utf-8",
    )
    batches = []

    class Session:
        def __init__(self, graph, **kwargs):
            assert kwargs["batch_size"] == min(declared, 4)

        def get_inputs(self):
            return [SimpleNamespace(name="input_ids"), SimpleNamespace(name="attention_mask")]

        def get_outputs(self):
            return [SimpleNamespace(shape=[None, 1])]

        def run(self, outputs, values):
            batches.append(len(values["input_ids"]))
            return [values["input_ids"].sum(axis=1, keepdims=True).astype(np.float32)]

    monkeypatch.setattr(intel_gpu, "OpenVINOSession", Session)
    model = ONNXReranker(tiny_reranker, threads=2, workers=2, cache_batches=0)
    passages = ["warmup source " * (i + 1) for i in range(9)]
    expected = [float(sum(model.tokenizer.encode("warmup", p).ids)) for p in passages]
    assert model.score("warmup", passages) == expected
    assert sum(batches) == 9 and max(batches) <= min(declared, 4)
    assert model.spec.batch_size == declared
    assert model.cache_info()["hits"] == 0
    assert model.tokenizer.truncation is None


@pytest.mark.parametrize("workers", [1, 2])
def test_gpu_length_groups_keep_pair_tokens_masks_and_original_score_slots(
    tiny_reranker, monkeypatch, workers
):
    from collections import Counter
    from threading import Lock

    spec = reranker_spec(tiny_reranker).model_copy(
        update={"runtime": "openvino-gpu-f16", "pad_token": "[UNK]"}
    )
    (tiny_reranker / "reranker.json").write_text(spec.model_dump_json(), encoding="utf-8")
    captured = []
    shapes = []
    lock = Lock()
    fail = False

    class Session:
        def __init__(self, content, **kwargs):
            pass

        def get_inputs(self):
            return [
                SimpleNamespace(name=name)
                for name in ("input_ids", "attention_mask", "token_type_ids")
            ]

        def get_outputs(self):
            return [SimpleNamespace(shape=[None, 1])]

        def run(self, outputs, values):
            if fail:
                raise RuntimeError("GPU failure")
            scores = []
            for ids, mask, types in zip(
                values["input_ids"],
                values["attention_mask"],
                values["token_type_ids"],
                strict=True,
            ):
                active = mask.astype(bool)
                assert not types[~active].any()
                assert (ids[~active] == model.tokenizer.token_to_id("[UNK]")).all()
                tokens = tuple(
                    zip(
                        ids[active].tolist(),
                        mask[active].tolist(),
                        types[active].tolist(),
                        strict=True,
                    )
                )
                with lock:
                    captured.append(tokens)
                scores.append(sum((i + 1) * int(v) for i, v in enumerate(ids[active])))
            with lock:
                shapes.append(values["input_ids"].shape)
            return [np.asarray(scores, dtype=np.float32).reshape(-1, 1)]

    monkeypatch.setattr(intel_gpu, "OpenVINOSession", Session)
    model = ONNXReranker(tiny_reranker, threads=2, workers=workers, cache_batches=0)
    query = "transaction rollback"
    passages = ["source " * n + "token" for n in [80, 1, 50, 3, 900, 5, 4, 100, 2]]
    model.tokenizer.no_padding()
    model.tokenizer.enable_truncation(max_length=512, strategy="only_second")
    encodings = model.tokenizer.encode_batch([(query, p) for p in passages])
    expected = [float(sum((i + 1) * v for i, v in enumerate(e.ids))) for e in encodings]
    expected_tokens = [
        tuple(zip(e.ids, e.attention_mask, e.type_ids, strict=True)) for e in encodings
    ]
    original_padding_work = sum(
        max(len(e.ids) for e in encodings[i : i + 4]) * len(encodings[i : i + 4])
        for i in range(0, len(encodings), 4)
    )
    model.tokenizer.no_truncation()
    model.tokenizer.enable_padding(pad_id=model.tokenizer.token_to_id("[UNK]"), pad_token="[UNK]")
    assert model.score(query, passages) == expected
    assert Counter(captured) == Counter(expected_tokens)
    assert sum(batch * length for batch, length in shapes) < original_padding_work
    assert max(batch for batch, _ in shapes) <= 4
    assert all(length % 16 == 0 for _, length in shapes)
    assert model.tokenizer.truncation is None
    assert model.tokenizer.padding["direction"] == "right"
    assert model.cache_info()["hits"] == 0
    fail = True
    with pytest.raises(RuntimeError, match="GPU failure"):
        model.score(query, passages)
    assert model.tokenizer.truncation is None
    assert model.tokenizer.padding["pad_token"] == "[UNK]"
    fail = False
    assert model.score(query, passages) == expected


@pytest.mark.parametrize("max_tokens", [47, 48, 63, 512])
def test_gpu_sequence_padding_is_bounded_by_the_packaged_token_limit(
    tiny_reranker, monkeypatch, max_tokens
):
    spec = reranker_spec(tiny_reranker).model_copy(
        update={"runtime": "openvino-gpu-f16", "max_tokens": max_tokens}
    )
    (tiny_reranker / "reranker.json").write_text(spec.model_dump_json(), encoding="utf-8")
    seen = []

    class Session:
        def __init__(self, content, **kwargs):
            assert kwargs["max_tokens"] == max_tokens

        def get_inputs(self):
            return [SimpleNamespace(name=n) for n in ("input_ids", "attention_mask")]

        def get_outputs(self):
            return [SimpleNamespace(shape=[None, 1])]

        def run(self, outputs, values):
            length = values["input_ids"].shape[1]
            active = values["attention_mask"].sum(axis=1)
            assert (active <= length).all()
            assert length <= max_tokens
            seen.append(length)
            return [active.astype(np.float32).reshape(-1, 1)]

    monkeypatch.setattr(intel_gpu, "OpenVINOSession", Session)
    model = ONNXReranker(tiny_reranker, threads=1, workers=1, cache_batches=0)
    short = model.score("token", ["source", "source source"])
    assert len(short) == 2 and seen[-1] == 16
    long = model.score("token", ["source " * 900])
    assert long == [float(max_tokens)] and seen[-1] == max_tokens
    assert model.tokenizer.truncation is None
