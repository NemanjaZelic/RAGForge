"""Acquire unchanged pinned native QA originals; explicit preparation only."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    metadata = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/benchmarks/scale-v1/telequad-audit.json"
    )
    audit = json.loads(metadata.read_text(encoding="utf-8"))
    for row in audit["files"]:
        dest = args.root / "external-qa/telequad/raw" / row["path"]
        if dest.exists():
            body = dest.read_bytes()
        else:
            if not args.download:
                raise ValueError("Native QA original missing; explicit --download required")
            with urllib.request.urlopen(row["url"], timeout=45) as response:
                body = response.read(row["size_bytes"] + 1)
        if len(body) != row["size_bytes"] or hashlib.sha256(body).hexdigest() != row["sha256"]:
            raise ValueError("Native upstream QA source changed")
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("xb") as output:
                output.write(body)
        dest.chmod(0o444)
    for name in (
        "telequad-audit.json",
        "telequad-exact-3gpp-sources.json",
        "tspec-markdown-inventory.json",
    ):
        source = metadata.parent / name
        target = args.root / "metadata" / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(source.read_bytes())
        elif target.read_bytes() != source.read_bytes():
            raise ValueError("Existing source metadata differs; inspect instead of replacing it")
    print("Verified unchanged native TeleQuAD sources; no product execution")


if __name__ == "__main__":
    main()
