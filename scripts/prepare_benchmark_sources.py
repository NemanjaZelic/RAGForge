"""Explicit source preparation. Downloads require --download; never runs RAGForge."""

import argparse
import json
import urllib.request
from pathlib import Path

from validate_benchmark_set import digest, relative_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests/fixtures/benchmarks/pilot-v1",
    )
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--download", action="store_true", help="Explicitly allow HTTPS source downloads"
    )
    args = parser.parse_args()
    manifest = json.loads((args.dataset / "dataset.json").read_text(encoding="utf-8"))
    for corpus in manifest["corpora"]:
        corpus_id = relative_path(corpus["corpus_id"])
        for row in corpus["files"]:
            path = relative_path(row["path"])
            raw = args.destination / corpus_id / "raw" / path
            target = args.destination / corpus_id / "input" / path
            if raw.exists():
                body = raw.read_bytes()
            else:
                if not args.download:
                    raise ValueError(
                        f"Source missing: {raw}; use --download only during explicit preparation"
                    )
                if not row["url"].startswith("https://"):
                    raise ValueError("Only HTTPS sources are allowed")
                request = urllib.request.Request(
                    row["url"], headers={"User-Agent": "RAGForge-benchmark-preparation/1"}
                )
                with urllib.request.urlopen(request, timeout=45) as response:
                    body = response.read(row["size_bytes"] + 1)
            if len(body) != row["size_bytes"] or digest(body) != row["sha256"]:
                raise ValueError(
                    f"Pinned source differs: {corpus_id}/{path}; "
                    "do not silently update the snapshot"
                )
            if target.exists() and target.read_bytes() != body:
                raise ValueError(f"Refusing to replace changed input: {target}")
            for dest in (raw, target):
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with dest.open("xb") as stream:
                        stream.write(body)
            raw.chmod(0o444)
            print(f"Verified {corpus_id}/{path}")


if __name__ == "__main__":
    main()
