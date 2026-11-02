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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    base = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/"
    sources = {
        "model.onnx": base + "onnx/model_quint8_avx2.onnx",
        "tokenizer.json": base + "tokenizer.json",
        "model_config.json": base + "config.json",
        "README.md": base + "README.md",
        "LICENSE": "https://www.apache.org/licenses/LICENSE-2.0.txt",
    }
    for name, url in sources.items():
        download(url, args.output / name)
    spec = RerankerSpec(
        model_id=MODEL,
        revision=REVISION,
        license="Apache-2.0",
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
