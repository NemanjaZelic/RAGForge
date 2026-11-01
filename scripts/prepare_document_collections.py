"""Acquire full versioned kernel HTML and snapshot-indexed RFC documents only."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path, PurePosixPath
from threading import Lock
from urllib.parse import quote, urljoin


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "RAGForge-benchmark-preparation/1"}
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read(32 * 1024**2 + 1)


def inventory(root: Path, corpus: str) -> list[dict[str, object]]:
    metadata = root / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    frozen = metadata / "inventory.json"
    if frozen.exists():
        return json.loads(frozen.read_text(encoding="utf-8"))["files"]
    if corpus == "kernel-6.18":
        base = "https://docs.kernel.org/6.18/"
        raw = fetch(base + "objects.inv")
        (metadata / "objects.inv").write_bytes(raw)
        head = raw.split(b"\n", 4)
        if head[2] != b"# Version: 6.18.0":
            raise ValueError("Unexpected kernel documentation version")
        files = []
        for line in zlib.decompress(head[4]).decode().splitlines():
            match = re.match(r"^(.*?)\s+(\S+:\S+)\s+(-?\d+)\s+(\S+)\s+(.*)$", line)
            if match and match[2] == "std:doc":
                path = match[4].split("#", 1)[0]
                files.append({"path": path, "url": urljoin(base, quote(path, safe="/:%"))})
        files = list({r["path"]: r for r in files}.values())
        source = base + "objects.inv"
    else:
        source = "https://www.rfc-editor.org/rfc/rfc-index.xml"
        raw = fetch(source)
        (metadata / "rfc-index.xml").write_bytes(raw)
        xml = ET.fromstring(raw)
        namespace = {"r": "https://www.rfc-editor.org/rfc-index"}
        files = []
        for entry in xml.findall("r:rfc-entry", namespace):
            id = entry.findtext("r:doc-id", namespaces=namespace)
            formats = [f.text for f in entry.findall("r:format/r:file-format", namespace)]
            extension = (
                "txt"
                if "TXT" in formats
                else "html"
                if "HTML" in formats
                else "pdf"
                if "PDF" in formats
                else None
            )
            if extension and id:
                path = id.lower() + "." + extension
                files.append({"path": path, "url": "https://www.rfc-editor.org/rfc/" + path})
    seen = set()
    for row in files:
        path = str(row["path"])
        if (
            not path.endswith((".html", ".txt", ".pdf"))
            or PurePosixPath(path).is_absolute()
            or any(p in {"", ".", ".."} for p in path.split("/"))
            or "\\" in path
            or ":" in path
            or path.casefold() in seen
        ):
            raise ValueError("Unsafe or colliding source path")
        seen.add(path.casefold())
    frozen.write_text(
        json.dumps(
            {
                "corpus": corpus,
                "catalog_url": source,
                "catalog_sha256": digest(raw),
                "files": sorted(files, key=lambda r: r["path"]),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return files


def acquire(root: Path, corpus: str, max_bytes: int) -> dict[str, object]:
    files = inventory(root, corpus)
    raw_root, input_root = root / "raw", root / "input"
    journal = root / "source-checksums.jsonl"
    existing = {}
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            existing[row["path"]] = row
    lock = Lock()
    # Count both source copies and partial downloads against this corpus budget.
    used = sum(
        p.stat().st_size
        for base in (raw_root, input_root)
        if base.exists()
        for p in base.rglob("*")
        if p.is_file()
    )
    completed = 0

    def one(row: dict[str, object]) -> dict[str, str] | None:
        nonlocal used, completed
        path = str(row["path"])
        raw, target = raw_root / path, input_root / path
        try:
            if raw.exists():
                data = raw.read_bytes()
                record = existing.get(path)
                if record is None or digest(data) != record["sha256"]:
                    raise ValueError("Existing source lacks matching acquisition hash")
            else:
                raw.parent.mkdir(parents=True, exist_ok=True)
                data = fetch(str(row["url"]))
                if not data or len(data) > 32 * 1024**2:
                    raise ValueError("Unexpected empty/oversized document response")
                if path.endswith(".pdf") and not data.startswith(b"%PDF-"):
                    raise ValueError("PDF source does not have a PDF header")
                with lock:
                    if used + 2 * len(data) > max_bytes:
                        raise ValueError("Corpus source/copy storage budget reached")
                    if shutil.disk_usage(root).free < 15_000_000_000 + 2 * len(data):
                        raise ValueError("15 GB free-space reserve reached")
                    used += 2 * len(data)
                with raw.open("xb") as stream:
                    stream.write(data)
                record = {
                    "path": path,
                    "url": row["url"],
                    "size_bytes": len(data),
                    "sha256": digest(data),
                }
                with lock, journal.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record) + "\n")
            if target.exists():
                if digest(target.read_bytes()) != record["sha256"]:
                    raise ValueError("Input changed from frozen raw source")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(data)
            raw.chmod(0o444)
            target.chmod(0o444)
            with lock:
                completed += 1
                if completed % 500 == 0:
                    print(f"{corpus}: verified {completed}/{len(files)} documents", flush=True)
            return None
        except Exception as error:
            return {"path": path, "error": type(error).__name__ + ": " + str(error)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        failures = [r for r in pool.map(one, files) if r is not None]
    report = {
        "corpus": corpus,
        "cataloged_files": len(files),
        "verified_files": completed,
        "errors": failures,
        "raw_and_input_bytes": sum(
            p.stat().st_size
            for base in (raw_root, input_root)
            for p in base.rglob("*")
            if p.is_file()
        ),
        "status": "complete_bytes_acquired" if not failures else "incomplete_source_acquisition",
        "product_execution": "not_run",
        "text_provenance_verified": False,
    }
    (root / "acquisition-summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--corpus", choices=["kernel-6.18", "ietf-rfcs"], required=True)
    parser.add_argument("--max-total-bytes", type=int, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if not args.download:
        parser.error("Explicit --download required")
    report = acquire(args.root, args.corpus, args.max_total_bytes)
    print(json.dumps({k: v for k, v in report.items() if k != "errors"}, indent=2))
    if report["errors"]:
        raise SystemExit("Source acquisition incomplete; see acquisition-summary.json")


if __name__ == "__main__":
    main()
