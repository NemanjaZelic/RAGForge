"""Explicit online maintenance: provision one pinned public, CPU-only reranker.

Never imported by build or inference. No document data is sent to the model hub.
"""

import argparse
from pathlib import Path

from prepare_models import download

from ragforge.artifacts.manifest import FileRecord
from ragforge.core.embedding import file_hash
from ragforge.core.rerank import RerankerSpec, reranker_spec

MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
MMARCO_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
MMARCO_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--model", choices=["minilm-l6", "bge-base", "mmarco-minilm"], default="minilm-l6"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    model, revision, license_name, pad_token, batch_size = MODEL, REVISION, "Apache-2.0", "[PAD]", 8
    graph = "onnx/model_quint8_avx2.onnx"
    if args.model == "bge-base":
        model = "onnx-community/bge-reranker-base-ONNX"
        revision = "f131ae72114cb18333648a2ee6b0942849e8ab95"
        license_name, pad_token, batch_size = "MIT", "<pad>", 1
        graph = "onnx/model_quantized.onnx"
    if args.model == "mmarco-minilm":
        model = MMARCO_MODEL
        revision = MMARCO_REVISION
        pad_token, batch_size = "<pad>", 2
    base = f"https://huggingface.co/{model}/resolve/{revision}/"
    sources = {
        "model.onnx": base + graph,
        "tokenizer.json": base + "tokenizer.json",
        "model_config.json": base + "config.json",
        "README.md": base + "README.md",
        "LICENSE": "https://www.apache.org/licenses/LICENSE-2.0.txt",
    }
    if args.model == "bge-base":
        sources["LICENSE"] = (
            "https://raw.githubusercontent.com/FlagOpen/FlagEmbedding/"
            "897baa67c0ffddbfccf4e6776ff55310d67809d4/LICENSE"
        )
        sources["upstream-model-card.md"] = (
            "https://huggingface.co/BAAI/bge-reranker-base/resolve/"
            "2cfc18c9415c912f9d8155881c133215df768a70/README.md"
        )
    for name, url in sources.items():
        download(
            url,
            args.output / name,
            max_bytes=384 * 1024**2 if name == "model.onnx" else 256 * 1024**2,
        )
    if args.model == "bge-base" and file_hash(args.output / "model.onnx") != (
        "46a1bb4cf46ff1e300d27589d620141fbf04fc0eaf8e7bb6dea5e044475ff387"
    ):
        raise ValueError("pinned BGE quantized graph checksum mismatch")
    if args.model == "mmarco-minilm" and file_hash(args.output / "model.onnx") != (
        "6c2513767fb63d008a4377bef7a7a3555433d9436342bb53e35a3a72ffc52d4b"
    ):
        raise ValueError("pinned multilingual mMARCO graph checksum mismatch")
    spec = RerankerSpec(
        model_id=model,
        revision=revision,
        license=license_name,
        pad_token=pad_token,
        batch_size=batch_size,
        source_url=base,
        files=[
            FileRecord(
                path=name,
                sha256=file_hash(args.output / name),
                size_bytes=(args.output / name).stat().st_size,
            )
            for name in sorted(sources)
        ],
    )
    (args.output / "reranker.json").write_text(
        spec.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    reranker_spec(args.output)
    print(spec.model_dump_json(exclude={"files"}))


if __name__ == "__main__":
    main()
