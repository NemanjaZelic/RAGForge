"""Small real ONNX graph fixtures for runtime contracts, not quality evaluation."""

import hashlib
from pathlib import Path

import pytest


@pytest.fixture
def tiny_model(tmp_path: Path) -> Path:
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors

    from ragforge.artifacts.manifest import FileRecord
    from ragforge.core.embedding import ModelSpec

    directory = tmp_path / "local-model"
    directory.mkdir()
    words = [
        "[PAD]",
        "[UNK]",
        "[CLS]",
        "[SEP]",
        "rollback",
        "transaction",
        "token",
        "authentication",
        "savepoint",
        "offline",
        "local",
    ]
    vocabulary = {word: index for index, word in enumerate(words)}
    tokenizer = Tokenizer(models.WordLevel(vocabulary, unk_token="[UNK]"))
    tokenizer.normalizer = normalizers.Lowercase()
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]",
        special_tokens=[("[CLS]", 2), ("[SEP]", 3)],
    )
    tokenizer.save(str(directory / "tokenizer.json"))
    weights = np.random.default_rng(42).normal(size=(len(words), 4)).astype(np.float32)
    weights[0] = 0
    graph = helper.make_graph(
        [helper.make_node("Gather", ["weights", "input_ids"], ["hidden"], axis=0)],
        "fixture-local-embedding",
        [
            helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["batch", "sequence"]),
            helper.make_tensor_value_info(
                "attention_mask", TensorProto.INT64, ["batch", "sequence"]
            ),
        ],
        [helper.make_tensor_value_info("hidden", TensorProto.FLOAT, ["batch", "sequence", 4])],
        [numpy_helper.from_array(weights, name="weights")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 10
    onnx.save_model(model, directory / "model.onnx")
    (directory / "LICENSE").write_text(
        "Original synthetic runtime fixture only.\n", encoding="utf-8"
    )
    records = [
        FileRecord(
            path=p.name,
            sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
            size_bytes=p.stat().st_size,
        )
        for p in sorted(directory.iterdir())
    ]
    spec = ModelSpec(
        model_id="fixture/not-pretrained",
        revision="a" * 40,
        dimensions=4,
        max_tokens=512,
        pad_token="[PAD]",
        license="test-fixture-only",
        source_url="local:fixture",
        license_url="local:fixture",
        files=records,
    )
    (directory / "model.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    return directory
