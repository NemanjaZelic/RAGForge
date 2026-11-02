"""Reconstruct the frozen pypdf evidence representation without rewriting labels."""

import argparse
import importlib.metadata
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ragforge.core.embedding import file_hash
from ragforge.core.source import checked_stat, is_link
from ragforge.jobs.budget import StorageBudget
from ragforge.jobs.build import atomic_json
from ragforge.jobs.ingest import job_lock


def reference_path(root, ref):
    path = root / "3gpp-etsi/input"
    base = path.resolve(strict=True)
    for part in ref["path"].split("/"):
        if part in {"", ".", ".."} or "\\" in part or ":" in part:
            raise ValueError("invalid reference source path")
        path /= part
        checked_stat(path, base)
    if path.stat().st_size > 64 * 1024**2 or file_hash(path) != ref["sha256"]:
        raise ValueError("reference source hash/size differs from frozen metadata")
    return path


def one(root, output, ref, budget_root):
    from pypdf import PdfReader

    from ragforge.jobs.worker import limit_memory

    limit_memory(1024)
    path = reference_path(root, ref)
    reader = PdfReader(io.BytesIO(path.read_bytes()))
    if len(reader.pages) > 10000:
        raise ValueError("reference exceeds 10000 pages")
    pages, chars = [], 0
    for page in reader.pages:
        text = page.extract_text(extraction_mode="plain")
        chars += len(text)
        if chars > 64_000_000:
            raise ValueError("reference text exceeds 64 million characters")
        pages.append(text)
    data = (json.dumps(pages, ensure_ascii=True) + "\n").encode()
    StorageBudget(budget_root, limit_bytes=60_000_000_000).check(len(data))
    target = output / (ref["sha256"] + ".json")
    # The parent owns this new output; never replace a previous extraction.
    descriptor, temporary = tempfile.mkstemp(prefix=".reference-", dir=output)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)  # Atomic publication that refuses an existing target.
    finally:
        os.unlink(temporary)
    print(json.dumps({"pages": len(pages), "text_chars": chars}), flush=True)


def prepare(root, output, budget_root, *, resume=False):
    if importlib.metadata.version("pypdf") != "6.21.4":
        raise ValueError("frozen evidence representation requires pypdf 6.21.4")
    refs_file = root / "metadata/telequad-exact-3gpp-sources.json"
    refs = json.loads(refs_file.read_text(encoding="utf-8"))["records"]
    if output.exists() and (not resume or is_link(output.lstat())):
        raise ValueError("existing reference cache requires explicit resume and no links")
    if resume and not output.exists():
        raise ValueError("cannot resume a missing reference cache")
    output.mkdir(parents=True, exist_ok=True)
    with job_lock(output):
        manifest = output / "reference-cache.json"
        identity = {"pypdf": "6.21.4", "reference_metadata_sha256": file_hash(refs_file)}
        report = (
            json.loads(manifest.read_text(encoding="utf-8"))
            if manifest.exists()
            else {**identity, "records": []}
        )
        if any(report.get(k) != v for k, v in identity.items()):
            raise ValueError("reference cache recipe changed")
        existing = {r["source_sha256"]: r for r in report["records"]}
        for ref in refs:
            if ref["state"] != "exact_source_bytes_acquired":
                raise ValueError("exact reference source is not acquired")
            reference_path(root, ref)
            target = output / (ref["sha256"] + ".json")
            if ref["sha256"] in existing:
                if (
                    is_link(target.lstat())
                    or file_hash(target) != existing[ref["sha256"]]["cache_sha256"]
                ):
                    raise ValueError("committed evidence cache checksum mismatch")
                continue
            if target.exists():
                raise ValueError("uncommitted extraction exists; inspect it before resuming")
            command = [
                sys.executable,
                str(Path(__file__).absolute()),
                "--root",
                str(root),
                "--output",
                str(output),
                "--budget-root",
                str(budget_root),
                "--one",
                ref["sha256"],
            ]
            process = subprocess.Popen(
                command,
                stdout=sys.stdout,
                stderr=sys.stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                code = process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                        timeout=15,
                    )
                else:
                    process.kill()
                process.wait(timeout=15)
                raise RuntimeError("bounded reference extraction exceeded 300 seconds") from None
            if code:
                raise RuntimeError(f"bounded reference extraction failed (exit {code})")
            record = {
                "source_sha256": ref["sha256"],
                "cache_sha256": file_hash(target),
                "cache_bytes": target.stat().st_size,
            }
            report["records"].append(record)
            atomic_json(manifest, report)
        report["state"] = "complete_reference_representation_not_label_review"
        atomic_json(manifest, report)
        return {"references": len(report["records"]), "state": report["state"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-root", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--one", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.one:
        refs = json.loads(
            (args.root / "metadata/telequad-exact-3gpp-sources.json").read_text(encoding="utf-8")
        )["records"]
        ref = next(r for r in refs if r["sha256"] == args.one)
        one(args.root, args.output, ref, args.budget_root)
    else:
        print(json.dumps(prepare(args.root, args.output, args.budget_root, resume=args.resume)))


if __name__ == "__main__":
    main()
