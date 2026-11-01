"""Explicit acquisition of the frozen ETSI PDF inventory; never runs RAGForge."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path
from threading import Lock
from typing import Any


def digest_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def acquire(inventory_path: Path, root: Path, max_bytes: int) -> dict[str, Any]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if inventory["errors"] or inventory["unknown_sizes"]:
        raise ValueError("Resolve incomplete source inventory before downloading")
    # Raw and input are separate copies; reserve both, no hidden duplication overhead.
    required_bytes = 2 * sum(row["size_bytes"] for row in inventory["files"])
    if required_bytes > max_bytes:
        raise ValueError(f"Raw + input require {required_bytes} bytes, above the explicit budget")
    root.mkdir(parents=True, exist_ok=True)
    raw_root, input_root = root / "raw", root / "input"
    journal = root / "source-checksums.jsonl"
    records = {}
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            records[row["url"]] = row
    missing_bytes = 0
    for row in inventory["files"]:
        path = source_path(row)
        for base in (raw_root, input_root):
            dest = base / path
            if not dest.exists():
                missing_bytes += row["size_bytes"]
    if shutil.disk_usage(root).free < missing_bytes + 15_000_000_000:
        raise ValueError("Insufficient free space for missing sources plus 15 GB free reserve")
    downloaded = 0
    record_lock = Lock()

    def fetch_one(row: dict[str, Any]) -> None:
        nonlocal downloaded
        path = source_path(row)
        raw, target = raw_root / path, input_root / path
        if raw.exists():
            expected = records.get(row["url"])
            if expected is None:
                raise ValueError(f"Existing source has no trusted local acquisition record: {raw}")
            if raw.stat().st_size != row["size_bytes"] or digest_file(raw) != expected["sha256"]:
                raise ValueError(f"Existing raw source changed: {raw}")
        else:
            raw.parent.mkdir(parents=True, exist_ok=True)
            partial = raw.with_suffix(".pdf.partial")
            if partial.exists():
                raise ValueError(
                    f"Incomplete download needs explicit inspection/removal: {partial}"
                )
            if not row["url"].startswith("https://www.etsi.org/deliver/"):
                raise ValueError("Unexpected download host/path in frozen inventory")
            request = urllib.request.Request(
                row["url"], headers={"User-Agent": "RAGForge-benchmark-preparation/1"}
            )
            with urllib.request.urlopen(request, timeout=90) as response, partial.open("xb") as out:
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > row["size_bytes"]:
                        raise ValueError("Download exceeds frozen listed size")
                    out.write(block)
            if partial.stat().st_size != row["size_bytes"]:
                raise ValueError("Download size differs from frozen inventory")
            with partial.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError("Downloaded object is not a PDF")
            record = {
                "url": row["url"],
                "path": path.as_posix(),
                "size_bytes": row["size_bytes"],
                "sha256": digest_file(partial),
                "release": row["release"],
                "version": row["version"],
            }
            partial.rename(raw)
            with record_lock:
                with journal.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record) + "\n")
                records[row["url"]] = record
                downloaded += 1
        raw.chmod(0o444)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if digest_file(target) != records[row["url"]]["sha256"]:
                raise ValueError(f"Input differs from raw snapshot: {target}")
        else:
            # Exclusive creation avoids overwriting an independently prepared input.
            with raw.open("rb") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
        target.chmod(0o444)
        if len(records) % 100 == 0:
            print(f"Verified {len(records)} of {len(inventory['files'])} PDFs", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch_one, inventory["files"]))
    report = {
        "pdf_files": len(inventory["files"]),
        "new_downloads": downloaded,
        "raw_and_input_bytes": required_bytes,
        "state": "bytes_acquired_text_not_yet_verified",
        "product_execution": "not_run",
        "retrieval_ready": False,
    }
    (root / "acquisition-summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def source_path(row: dict[str, Any]) -> Path:
    filename = row["url"].rsplit("/", 1)[-1]
    spec_id = row["etsi_spec_id"]
    if (
        not filename.endswith(".pdf")
        or not spec_id.isdigit()
        or "/" in filename
        or "\\" in filename
        or row["kind"] not in {"ts", "tr"}
        or row["release"] not in {8, 15, 18, 19, 20}
    ):
        raise ValueError("Invalid portable source identity")
    return Path(f"rel-{int(row['release'])}") / row["kind"] / spec_id / filename


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--max-total-bytes", type=int, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if not args.download:
        parser.error("Network acquisition requires explicit --download")
    print(json.dumps(acquire(args.inventory, args.root, args.max_total_bytes), indent=2))


if __name__ == "__main__":
    main()
