"""Restore frozen benchmark source bytes; no product imports, models or indexing."""

import argparse
import concurrent.futures
import hashlib
import json
import re
import shutil
import urllib.request
from pathlib import Path, PurePosixPath


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=65_000_000_000)
    args = parser.parse_args()
    snapshot = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/benchmarks/scale-v1/corpus-snapshots.json"
    )
    manifest = json.loads(snapshot.read_text(encoding="utf-8"))
    jobs = []
    for corpus in manifest["corpora"]:
        name = corpus["corpus_id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", name):
            raise ValueError("Unsafe corpus directory")
        for row in corpus["files"]:
            path = PurePosixPath(row["path"])
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in row["path"]
                or ":" in row["path"]
            ):
                raise ValueError("Unsafe source path")
            jobs.append((name, row))
    args.root.mkdir(parents=True, exist_ok=True)
    used = sum(p.stat().st_size for p in args.root.rglob("*") if p.is_file())
    missing = sum(
        row["size_bytes"]
        for name, row in jobs
        for folder in ("raw", "input")
        if not (args.root / name / folder / row["path"]).exists()
    )
    if used + missing > args.max_bytes:
        raise ValueError("Source restoration would exceed the shared benchmark budget")
    if shutil.disk_usage(args.root).free < missing + 15_000_000_000:
        raise ValueError("Insufficient disk space with the 15 GB free-space reserve")

    def one(job: tuple[str, dict]) -> None:
        name, row = job
        raw = args.root / name / "raw" / row["path"]
        target = args.root / name / "input" / row["path"]
        if not raw.exists():
            if not args.download:
                raise ValueError("Missing frozen source; explicit --download required")
            if not row["url"].startswith(
                ("https://www.etsi.org/", "https://www.rfc-editor.org/", "https://docs.kernel.org/")
            ):
                raise ValueError("Unexpected source host")
            raw.parent.mkdir(parents=True, exist_ok=True)
            partial = raw.with_suffix(raw.suffix + ".partial")
            request = urllib.request.Request(
                row["url"], headers={"User-Agent": "RAGForge-benchmark-preparation/1"}
            )
            with (
                urllib.request.urlopen(request, timeout=90) as response,
                partial.open("xb") as stream,
            ):
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > row["size_bytes"]:
                        raise ValueError("Download exceeds frozen size")
                    stream.write(block)
            if partial.stat().st_size != row["size_bytes"] or digest(partial) != row["sha256"]:
                raise ValueError("Downloaded bytes differ from frozen snapshot")
            partial.rename(raw)
        if raw.stat().st_size != row["size_bytes"] or digest(raw) != row["sha256"]:
            raise ValueError("Frozen raw source changed")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with raw.open("rb") as source, target.open("xb") as stream:
                shutil.copyfileobj(source, stream, 1024 * 1024)
        if target.stat().st_size != row["size_bytes"] or digest(target) != row["sha256"]:
            raise ValueError("Input copy differs from frozen source")
        raw.chmod(0o444)
        target.chmod(0o444)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for count, _ in enumerate(pool.map(one, jobs), 1):
            if count % 1000 == 0:
                print(f"Verified {count}/{len(jobs)} frozen sources", flush=True)
    print("Frozen source bytes verified; no product execution or retrieval benchmark")


if __name__ == "__main__":
    main()
