"""Verify candidate answer evidence against exact source versions, not retrieval."""

import argparse
import hashlib
import json
import unicodedata
from pathlib import Path

from pypdf import PdfReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    ROOT = args.root
    refs = json.loads((ROOT / "metadata/telequad-exact-3gpp-sources.json").read_text())
    native = json.loads(
        (ROOT / "external-qa/telequad/raw/extractive/v4/TeleQuAD-v4-full.json").read_text(
            encoding="utf-8"
        )
    )
    cache = ROOT / "source-review/telequad-source-pages"
    cache.mkdir(parents=True, exist_ok=True)

    def canon(text):
        return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())

    out = []
    for ref in refs["records"]:
        if ref["state"] != "exact_source_bytes_acquired":
            continue
        path = ROOT / "3gpp-etsi/input" / ref["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
            raise ValueError("Source hash changed")
        version = "".join(
            "0123456789abcdefghijklmnopqrstuvwxyz"[int(x)] for x in ref["version"].split(".")
        )
        source = f"3GPP-Specs#{ref['spec_code']}-{version}"
        documents = [
            d
            for d in native["data"]
            if d["source"] == source or d["source"].startswith(source + "#")
        ]
        cachefile = cache / (ref["sha256"] + ".json")
        if cachefile.exists():
            pages = json.loads(cachefile.read_text(encoding="utf-8"))
        else:
            pages = [page.extract_text(extraction_mode="plain") for page in PdfReader(path).pages]
            cachefile.write_text(json.dumps(pages) + "\n", encoding="utf-8")
        canonical_pages = [canon(t) for t in pages]
        found = 0
        total = 0
        for doc in documents:
            for paragraph in doc["paragraphs"]:
                context = paragraph["context"]
                for query in paragraph["qas"]:
                    if query["is_impossible"]:
                        continue
                    total += 1
                    hits = []
                    for answer in query["answers"]:
                        a, b = answer["answer_start"], answer["answer_end"]
                        if not (0 <= a < b <= len(context)) or context[a:b] != answer["text"]:
                            continue
                        window = canon(context[max(0, a - 80) : min(len(context), b + 80)])
                        if len(window) < 40:
                            continue
                        for number, text in enumerate(canonical_pages, 1):
                            pos = text.find(window)
                            if pos >= 0:
                                hits.append(
                                    {
                                        "page": number,
                                        "canonical_char_start": pos,
                                        "canonical_char_end": pos + len(window),
                                        "canonicalizer": "NFKC-casefold-alnum-v1",
                                        "span_sha256": hashlib.sha256(window.encode()).hexdigest(),
                                    }
                                )
                    if hits:
                        found += 1
                    out.append(
                        {
                            "case_id": "telequad-extractive:" + query["id"],
                            "spec_code": ref["spec_code"],
                            "version": ref["version"],
                            "source_path": ref["path"],
                            "source_sha256": ref["sha256"],
                            "candidate_evidence": hits,
                            "status": "exact_text_alignment_candidate"
                            if hits
                            else "needs_manual_source_alignment",
                            "independent_review": "pending",
                            "strict_scoring_eligible": False,
                        }
                    )
        print(
            ref["spec_code"],
            ref["version"],
            "pages",
            len(pages),
            "positive cases",
            total,
            "with source-alignment candidates",
            found,
            flush=True,
        )
    dest = ROOT / "metadata/telequad-source-alignment.json"
    report = {
        "purpose": "source_annotation_alignment_not_a_retrieval_benchmark",
        "product_execution": "not_run",
        "positive_3gpp_cases": len(out),
        "cases_with_source_candidates": sum(bool(r["candidate_evidence"]) for r in out),
        "strict_scoring_eligible": 0,
        "records": out,
    }
    dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "records"}), flush=True)


if __name__ == "__main__":
    main()
