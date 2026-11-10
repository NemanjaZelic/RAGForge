"""Exact uint8-to-int8 weight representation for AVX-512 VNNI CPUs.

No recalibration, retraining, network access or model-file mutation. Other CPUs
retain the original U8U8 graph: their U8S8 kernels can saturate intermediate sums.
"""

from __future__ import annotations

import importlib
import os
import platform
from dataclasses import dataclass


@dataclass(frozen=True)
class SignedGraph:
    content: bytes
    converted_matmuls: int


def supports_signed_weights() -> bool:
    if os.environ.get("RAGFORGE_DISABLE_VNNI") == "1":
        return False
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        return False
    try:
        # NumPy checks both CPUID and OS vector-state support. Fail closed when
        # this optional internal feature inventory is unavailable or changes.
        module = importlib.import_module("numpy._core._multiarray_umath")
        features = getattr(module, "__cpu_features__", {})
        return isinstance(features, dict) and features.get("AVX512VNNI") is True
    except (ImportError, AttributeError):
        return False


def prepare_signed_weights(content: bytes) -> SignedGraph | None:
    if not supports_signed_weights():
        return None
    try:
        import onnx
    except ImportError:
        return None
    import numpy as np
    from onnx import numpy_helper

    model = onnx.load_model_from_string(content)
    # Keep this transform deliberately narrow. Never resolve external tensor
    # paths, nested control-flow graphs, functions or sparse representations.
    if model.functions or model.graph.sparse_initializer:
        return None
    tensors = list(model.graph.initializer)
    for node in model.graph.node:
        for attribute in node.attribute:
            if attribute.type in {
                onnx.AttributeProto.GRAPH,
                onnx.AttributeProto.GRAPHS,
                onnx.AttributeProto.SPARSE_TENSOR,
                onnx.AttributeProto.SPARSE_TENSORS,
            }:
                return None
            if attribute.type == onnx.AttributeProto.TENSOR:
                tensors.append(attribute.t)
            elif attribute.type == onnx.AttributeProto.TENSORS:
                tensors.extend(attribute.tensors)
    if any(t.external_data or t.data_location == onnx.TensorProto.EXTERNAL for t in tensors):
        return None
    initial = {t.name: t for t in model.graph.initializer}
    overridable = {value.name for value in model.graph.input}
    occupied = set(initial) | {v for n in model.graph.node for v in [*n.input, *n.output]}
    converted = {}
    count = 0
    for node in model.graph.node:
        if node.domain or node.op_type != "MatMulInteger" or len(node.input) != 4:
            continue
        names = [node.input[1], node.input[3]]
        if any(name not in initial or name in overridable for name in names):
            continue
        weight, zero = (initial[name] for name in names)
        if weight.data_type != onnx.TensorProto.UINT8 or zero.data_type != onnx.TensorProto.UINT8:
            continue
        if len(weight.dims) != 2 or list(zero.dims) not in ([], [weight.dims[1]]):
            continue
        for position in (1, 3):
            name = node.input[position]
            if name not in converted:
                fresh = name + ".ragforge_signed"
                while fresh in occupied:
                    fresh += "_"
                occupied.add(fresh)
                array = numpy_helper.to_array(initial[name])
                # For every integer, (W-128) - (Z-128) == W-Z exactly.
                signed = (array.astype(np.int16) - 128).astype(np.int8)
                converted[name] = numpy_helper.from_array(signed, fresh)
            node.input[position] = converted[name].name
        count += 1
    if not count:
        return None
    used = {v for n in model.graph.node for v in n.input} | overridable
    used.update(v.name for v in model.graph.output)
    retained = [v for v in model.graph.initializer if v.name not in converted or v.name in used]
    del model.graph.initializer[:]
    model.graph.initializer.extend(retained)
    model.graph.initializer.extend(converted.values())
    return SignedGraph(model.SerializeToString(), count)
