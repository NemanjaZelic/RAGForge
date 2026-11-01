"""Acquire exact legacy spec versions named by native QA, source preparation only."""

import argparse
import concurrent.futures
import hashlib
import json
import urllib.request
from pathlib import Path

from pypdf import PdfReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    ROOT = args.root
    audit = json.loads((ROOT / "metadata/telequad-audit.json").read_text(encoding="utf-8"))
    jobs = sorted(
        {
            (r["spec_code"], r["version"]): r for r in audit["source_records"] if "spec_code" in r
        }.values(),
        key=lambda r: r["spec_code"],
    )

    def one(row):
        code = row["spec_code"]
        kind = "tr" if code in {"21915", "25996"} else "ts"
        etsi = "1" + code
        start = int(etsi) // 100 * 100
        v = tuple(map(int, row["version"].split(".")))
        dirname = ".".join(f"{x:02}" for x in v) + "_60"
        filename = f"{kind}_{etsi}v" + "".join(f"{x:02}" for x in v) + "p.pdf"
        url = (
            f"https://www.etsi.org/deliver/etsi_{kind}/{start:06}_{start + 99:06}/"
            f"{etsi}/{dirname}/{filename}"
        )
        path = f"qa-reference/{filename}"
        raw = ROOT / "3gpp-etsi/raw" / path
        target = ROOT / "3gpp-etsi/input" / path
        try:
            if not raw.exists():
                if not args.download:
                    raise ValueError("Explicit --download required for missing exact sources")
                request = urllib.request.Request(
                    url, headers={"User-Agent": "RAGForge-benchmark-preparation/1"}
                )
                with urllib.request.urlopen(request, timeout=45) as response:
                    body = response.read(64 * 1024**2)
                if not body.startswith(b"%PDF-"):
                    raise ValueError("Not a PDF")
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(body)
            body = raw.read_bytes()
            cover = " ".join(p.extract_text() for p in list(PdfReader(raw).pages)[:3])
            import re

            canonical = re.sub(r"\s+", " ", cover)
            if row["version"] not in canonical:
                raise ValueError("Expected version not found on PDF cover")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
            elif target.read_bytes() != body:
                raise ValueError("Existing input differs")
            raw.chmod(0o444)
            target.chmod(0o444)
            return {
                "spec_code": code,
                "version": row["version"],
                "source": row["source"],
                "url": url,
                "path": path,
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "cover_version_verified": True,
                "state": "exact_source_bytes_acquired",
                "answer_span_mapping": "pending",
            }
        except Exception as e:
            return {
                "spec_code": code,
                "version": row["version"],
                "url": url,
                "state": "unavailable",
                "error": type(e).__name__ + ": " + str(e),
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(one, jobs))
    report = {
        "records": records,
        "exact_versions_requested": len(jobs),
        "exact_versions_acquired": sum(
            r["state"] == "exact_source_bytes_acquired" for r in records
        ),
        "product_execution": "not_run",
    }
    (ROOT / "metadata/telequad-exact-3gpp-sources.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "records"}), flush=True)
    for r in records:
        if "error" in r:
            print(r["spec_code"], r["version"], r["error"])


if __name__ == "__main__":
    main()
