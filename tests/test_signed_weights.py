"""Signed weight representation is exact; unsafe CPU paths keep the original graph."""

import hashlib
from types import SimpleNamespace

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper, numpy_helper

from ragforge.core import signed_weights
from ragforge.core.signed_weights import prepare_signed_weights


def graph(*, external=False, zero=128):
    w = numpy_helper.from_array(np.array([[0, 127, 255], [128, 254, 1]], dtype=np.uint8), "weight")
    z = numpy_helper.from_array(np.array([zero] * 3, dtype=np.uint8), "zero")
    if external:
        w.ClearField("raw_data")
        w.data_location = TensorProto.EXTERNAL
        w.external_data.add(key="location", value="private-sentinel.bin")
    g = helper.make_graph(
        [helper.make_node("MatMulInteger", ["x", "weight", "az", "zero"], ["out"])],
        "integer_projection",
        [
            helper.make_tensor_value_info("x", TensorProto.UINT8, [2, 2]),
            helper.make_tensor_value_info("az", TensorProto.UINT8, []),
        ],
        [helper.make_tensor_value_info("out", TensorProto.INT32, [2, 3])],
        [w, z],
    )
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 14)])
    m.ir_version = 9
    return m.SerializeToString()


def test_processor_gate_fails_closed_and_disable_wins(monkeypatch):
    monkeypatch.setattr(signed_weights.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(
        signed_weights.importlib,
        "import_module",
        lambda name: SimpleNamespace(__cpu_features__={"AVX512VNNI": True}),
    )
    assert signed_weights.supports_signed_weights()
    monkeypatch.setenv("RAGFORGE_DISABLE_VNNI", "1")
    assert not signed_weights.supports_signed_weights()
    monkeypatch.delenv("RAGFORGE_DISABLE_VNNI")
    monkeypatch.setattr(
        signed_weights.importlib,
        "import_module",
        lambda name: SimpleNamespace(__cpu_features__={"AVX2": True}),
    )
    assert not signed_weights.supports_signed_weights()
    monkeypatch.setattr(signed_weights.platform, "machine", lambda: "aarch64")
    assert not signed_weights.supports_signed_weights()


@pytest.mark.parametrize("zero", [0, 1, 127, 128, 255])
def test_representation_preserves_every_integer_product(monkeypatch, zero):
    monkeypatch.setattr(signed_weights, "supports_signed_weights", lambda: True)
    original = graph(zero=zero)
    digest = hashlib.sha256(original).hexdigest()
    new = prepare_signed_weights(original)
    assert new is not None and new.converted_matmuls == 1
    model = onnx.load_model_from_string(new.content)
    onnx.checker.check_model(model)
    init = {t.name: numpy_helper.to_array(t).astype(np.int32) for t in model.graph.initializer}
    node = model.graph.node[0]
    weight = init[node.input[1]]
    zp = init[node.input[3]]
    assert model.graph.initializer[0].data_type == TensorProto.INT8
    for activation_zero in [0, 128, 255]:
        values = np.arange(256, dtype=np.int32).reshape(128, 2) - activation_zero
        expected = values @ (np.array([[0, 127, 255], [128, 254, 1]], dtype=np.int32) - zero)
        assert np.array_equal(values @ (weight - zp), expected)
    assert hashlib.sha256(original).hexdigest() == digest


def test_external_tensor_never_resolves_or_reads_a_file(monkeypatch):
    monkeypatch.setattr(signed_weights, "supports_signed_weights", lambda: True)

    def deny(*args, **kwargs):
        pytest.fail("external tensor data must not be loaded")

    monkeypatch.setattr(numpy_helper, "to_array", deny)
    assert prepare_signed_weights(graph(external=True)) is None


def test_overridable_weights_and_unsupported_cpu_remain_original(monkeypatch):
    monkeypatch.setattr(signed_weights, "supports_signed_weights", lambda: False)
    assert prepare_signed_weights(b"not even parsed") is None
    monkeypatch.setattr(signed_weights, "supports_signed_weights", lambda: True)
    model = onnx.load_model_from_string(graph())
    model.graph.input.append(helper.make_tensor_value_info("weight", TensorProto.UINT8, [2, 3]))
    assert prepare_signed_weights(model.SerializeToString()) is None


def test_real_integer_kernels_match_when_vnni_is_available():
    if not signed_weights.supports_signed_weights():
        pytest.skip("exact U8S8 path needs AVX512 VNNI")
    import onnxruntime as ort

    original = graph()
    new = prepare_signed_weights(original)
    assert new is not None
    before = ort.InferenceSession(original, providers=["CPUExecutionProvider"])
    after = ort.InferenceSession(new.content, providers=["CPUExecutionProvider"])
    for values in [
        np.array([[255, 255], [0, 255]], dtype=np.uint8),
        np.array([[127, 128], [1, 254]], dtype=np.uint8),
    ]:
        data = {"x": values, "az": np.array(128, dtype=np.uint8)}
        assert np.array_equal(before.run(None, data)[0], after.run(None, data)[0])


@pytest.mark.parametrize("change_logits", [False, True])
def test_startup_equivalence_check_selects_or_rejects_without_changing_files(
    monkeypatch, tiny_reranker, change_logits
):
    from ragforge.core.rerank import ONNXReranker
    from ragforge.core.signed_weights import SignedGraph

    monkeypatch.setenv("RAGFORGE_DISABLE_VNNI", "1")
    source = (tiny_reranker / "model.onnx").read_bytes()
    baseline = ONNXReranker(tiny_reranker, threads=1, cache_batches=0)
    expected = baseline.score("token", ["rollback token", "transaction"])
    model = onnx.load_model_from_string(source)
    if change_logits:
        output = model.graph.output[0].name
        for node in model.graph.node:
            for index, name in enumerate(node.output):
                if name == output:
                    node.output[index] = "original_logits"
        model.graph.initializer.append(
            numpy_helper.from_array(np.array(1, dtype=np.float32), "logit_shift")
        )
        model.graph.node.append(
            helper.make_node("Add", ["original_logits", "logit_shift"], [output])
        )
    prepared = SignedGraph(model.SerializeToString(), 1)
    monkeypatch.setattr(signed_weights, "prepare_signed_weights", lambda value: prepared)
    actual = ONNXReranker(tiny_reranker, threads=1, cache_batches=0)
    assert actual.execution_optimization == ("original" if change_logits else "vnni-signed-weights")
    assert actual.score("token", ["rollback token", "transaction"]) == expected
    assert (tiny_reranker / "model.onnx").read_bytes() == source


def test_optional_optimizer_error_keeps_valid_original_model(monkeypatch, tiny_reranker):
    from ragforge.core.rerank import ONNXReranker

    def unavailable(value):
        raise RuntimeError("optional kernel unavailable")

    monkeypatch.setattr(signed_weights, "prepare_signed_weights", unavailable)
    model = ONNXReranker(tiny_reranker, threads=1, cache_batches=0)
    assert model.execution_optimization == "original"
    assert len(model.score("token", ["rollback token"])) == 1
