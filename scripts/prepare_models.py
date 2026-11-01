"""Explicit online provisioning. Never called or imported by retrieval/build."""

import argparse
import json
import urllib.request
from pathlib import Path

from ragforge.artifacts.manifest import FileRecord
from ragforge.core.embedding import ModelSpec, file_hash, model_spec

CANDIDATES = {
    "e5-small": {
        "id": "intfloat/multilingual-e5-small",
        "revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
        "graph": "onnx/model_qint8_avx512_vnni.onnx",
        "license": "MIT",
        "license_url": "https://raw.githubusercontent.com/microsoft/unilm/master/LICENSE",
        "query_prefix": "query: ",
        "document_prefix": "passage: ",
        "pad_token": "<pad>",
        "max_tokens": 512,
    },
    "minilm": {
        "id": "sentence-transformers/all-MiniLM-L6-v2",
        "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "graph": "onnx/model_quint8_avx2.onnx",
        "license": "Apache-2.0",
        "license_url": "https://www.apache.org/licenses/LICENSE-2.0.txt",
        "query_prefix": "",
        "document_prefix": "",
        "pad_token": "[PAD]",
        "max_tokens": 256,
    },
}


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "RAGForge-model-provisioning"})
    with urllib.request.urlopen(request, timeout=30) as response, destination.open("xb") as stream:
        size = 0
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > 256 * 1024 * 1024:
                raise ValueError("model asset exceeds provisioning size limit")
            stream.write(block)
    print(f"Prepared {destination.name}: {size} bytes", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicitly download a pinned public pilot model.")
    parser.add_argument("candidate", choices=sorted(CANDIDATES))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    candidate = CANDIDATES[args.candidate]
    args.output.mkdir(parents=True, exist_ok=False)
    base = f"https://huggingface.co/{candidate['id']}/resolve/{candidate['revision']}/"
    sources = {
        "model.onnx": base + candidate["graph"],
        "tokenizer.json": base + "tokenizer.json",
        "model_config.json": base + "config.json",
        "README.md": base + "README.md",
        "LICENSE": candidate["license_url"],
    }
    for name, url in sources.items():
        download(url, args.output / name)
    records = [
        FileRecord(
            path=name,
            sha256=file_hash(args.output / name),
            size_bytes=(args.output / name).stat().st_size,
        )
        for name in sorted(sources)
    ]
    spec = ModelSpec(
        model_id=candidate["id"],
        revision=candidate["revision"],
        dimensions=384,
        max_tokens=candidate["max_tokens"],
        pad_token=candidate["pad_token"],
        query_prefix=candidate["query_prefix"],
        document_prefix=candidate["document_prefix"],
        license=candidate["license"],
        source_url=base,
        license_url=candidate["license_url"],
        files=records,
    )
    (args.output / "model.json").write_text(spec.model_dump_json(indent=2) + "\n", encoding="utf-8")
    model_spec(args.output)
    print(
        json.dumps(
            {
                "model": spec.model_id,
                "revision": spec.revision,
                "bytes": sum(r.size_bytes for r in records),
            }
        )
    )


if __name__ == "__main__":
    main()
