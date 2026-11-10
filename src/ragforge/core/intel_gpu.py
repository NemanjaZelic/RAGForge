"""Optional local Intel GPU execution of a verified, inline ONNX reranker.

Only the runtime Core API is used. Block the SDK's optional analytics import so
its conversion package selects its own no-op telemetry stub; no preferences or
files outside the project are changed.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from queue import Queue
from threading import RLock
from types import ModuleType
from typing import TYPE_CHECKING, Any

from ragforge.core.signed_weights import inline_model

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

_IMPORT_LOCK = RLock()


class _WithoutTelemetry(MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if fullname == "openvino_telemetry" or fullname.startswith("openvino_telemetry."):
            raise ModuleNotFoundError("OpenVINO optional telemetry is disabled")
        return None


def gpu_runtime() -> ModuleType:
    with _IMPORT_LOCK:
        previous = sys.modules.get("openvino_telemetry")
        if previous is not None:
            del sys.modules["openvino_telemetry"]
        guard = _WithoutTelemetry()
        sys.meta_path.insert(0, guard)
        try:
            return import_module("openvino")
        except (ImportError, OSError):
            raise ValueError(
                "Intel GPU runtime is unavailable; install the intel-gpu extra through setup."
            ) from None
        finally:
            sys.meta_path.remove(guard)
            if previous is not None:
                sys.modules["openvino_telemetry"] = previous


def check_gpu_available() -> None:
    ov = gpu_runtime()
    if not any(d == "GPU" or d.startswith("GPU.") for d in ov.Core().available_devices):
        raise ValueError(
            "No supported local Intel GPU was found; use CPU setup or install its graphics driver."
        )


@dataclass(frozen=True)
class _ValueInfo:
    name: str
    shape: list[int | None]


class OpenVINOSession:
    def __init__(self, graph: bytes, *, max_tokens: int, batch_size: int, requests: int) -> None:
        if not 1 <= batch_size <= 8 or not 1 <= requests <= 2 or not 16 <= max_tokens <= 512:
            raise ValueError("invalid GPU session limits")
        try:
            parsed = inline_model(graph)
        except Exception:
            raise ValueError("GPU reranker must be a valid inline ONNX graph") from None
        if parsed is None:
            raise ValueError("GPU reranker does not support external, sparse or nested graph data")
        del parsed
        ov = gpu_runtime()
        core = ov.Core()
        if not any(d == "GPU" or d.startswith("GPU.") for d in core.available_devices):
            raise ValueError("No supported local Intel GPU was found; use the CPU profile.")
        # A byte buffer has no model directory from which to load extra files.
        network = core.read_model(graph)
        inputs = []
        for port in network.inputs:
            if len(port.get_partial_shape()) != 2:
                raise ValueError("GPU reranker requires two-dimensional integer inputs")
            if port.get_element_type() != ov.Type.i64:
                raise ValueError("GPU reranker requires int64 inputs")
            inputs.append(_ValueInfo(port.get_any_name(), [None, None]))
        if len(network.outputs) != 1:
            raise ValueError("GPU reranker must expose one output")
        output = network.output(0)
        shape = output.get_partial_shape()
        if (
            len(shape) != 2
            or shape[-1].get_length() != 1
            or output.get_element_type() != ov.Type.f32
        ):
            raise ValueError("GPU reranker must expose one float32 logit per pair")
        network.reshape(
            {
                item.name: ov.PartialShape(
                    [ov.Dimension(1, batch_size), ov.Dimension(1, max_tokens)]
                )
                for item in inputs
            }
        )
        self._compiled = core.compile_model(network, "GPU", {"INFERENCE_PRECISION_HINT": "f16"})
        self.execution_devices = tuple(self._compiled.get_property("EXECUTION_DEVICES"))
        if not self.execution_devices or any(
            not device.startswith("GPU") for device in self.execution_devices
        ):
            raise ValueError("The requested GPU reranker did not compile for a GPU device")
        self._inputs = inputs
        self._output = self._compiled.output(0)
        self._requests: Queue[Any] = Queue(maxsize=requests)
        for _ in range(requests):
            self._requests.put(self._compiled.create_infer_request())

    def get_inputs(self) -> list[_ValueInfo]:
        return self._inputs

    def get_outputs(self) -> list[_ValueInfo]:
        return [_ValueInfo("logits", [None, 1])]

    def run(self, outputs: None, values: dict[str, NDArray[np.int64]]) -> list[NDArray[np.float32]]:
        import numpy as np

        request = self._requests.get()
        try:
            # Request buffers are reused. Copy before releasing the slot, so a
            # concurrent batch cannot overwrite logits that another caller reads.
            result = request.infer(values)[self._output]
            return [np.array(result, dtype=np.float32, copy=True)]
        finally:
            self._requests.put(request)
