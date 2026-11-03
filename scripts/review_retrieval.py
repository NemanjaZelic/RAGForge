"""Export blinded local review packets and validate source-quoted semantic judgments."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from ragforge.core.engine import BundleEngine
from ragforge.evaluation.models import AnswerEvidence
from ragforge.evaluation.review import ReviewObservation, SemanticReview, summarize_reviews
from ragforge.evaluation.runner import read_cases
from ragforge.evaluation.sources import EvidenceSources


def sha(data):
    return hashlib.sha256(data).hexdigest()


def export(args):
    recipe = json.loads((args.run / "run.json").read_text(encoding="utf-8"))
    engine = BundleEngine(args.artifact)
    if engine.manifest.build_id != recipe["artifact_build_id"]:
        raise ValueError("wrong review artifact")
    cases = {c.case_id: c for c in read_cases(args.cases) if c.split == recipe["split"]}
    if sha(args.cases.read_bytes()) != recipe["cases_sha256"]:
        raise ValueError("review case bank changed")
    answers = {
        a.case_id: a
        for a in [
            AnswerEvidence.model_validate_json(line)
            for line in args.answers.read_text(encoding="utf-8").splitlines()
        ]
    }
    if sha(args.answers.read_bytes()) != recipe["answer_evidence_sha256"]:
        raise ValueError("review fact bank changed")
    source = EvidenceSources(args.source_root)
    output = args.output
    db = sqlite3.connect((args.run / "evaluation.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    returned_cases = [
        r[0] for r in db.execute("SELECT case_id FROM results WHERE method=?", (args.method,))
    ]
    if len(returned_cases) != len(cases) or set(returned_cases) != set(cases):
        raise ValueError("review requires every case in the selected evaluation split")
    observations = []
    packets = []
    with engine.sqlite._connect() as index:
        for case_id, raw in db.execute(
            "SELECT case_id,json FROM results WHERE method=? ORDER BY rowid", (args.method,)
        ):
            row = json.loads(raw)
            if "error" in row:
                raise ValueError("cannot review a failed retrieval as successful")
            case = cases[case_id]
            annotation = answers[case_id]
            if annotation.collection_id != case.collection_id or annotation.query_sha256 != sha(
                case.query.encode()
            ):
                raise ValueError("review question mismatch")
            chunks = []
            for item in row["ranked_sources"]:
                chunk = index.execute(
                    "SELECT * FROM chunks WHERE chunk_id=?", (item["chunk_id"],)
                ).fetchone()
                if chunk is None:
                    raise ValueError("returned review chunk missing")
                value = engine.sqlite._chunk(chunk, 0, args.method)
                if value.source.model_dump(mode="json") != item["source"]:
                    raise ValueError("review citation changed")
                chunks.append(value)
            if len(chunks) != row.get("returned", len(chunks)) or len(chunks) > recipe["top_k"]:
                raise ValueError("review result count differs from the actual retrieval")
            if sum(len(c.text) for c in chunks) > recipe["max_output_chars"]:
                raise ValueError("review result exceeds retrieval output budget")
            facts = []
            for group in annotation.facts:
                target = group.any_of[0]
                text = source.text(target)
                facts.append(text[target.char_start : target.char_end])
            # Score/method/run names are omitted from the reviewer packet.
            observation = ReviewObservation(
                case_id=case_id,
                query_sha256=sha(case.query.encode()),
                artifact_build_id=engine.manifest.build_id,
                run_recipe_sha256=sha((args.run / "run.json").read_bytes()),
                facts=facts,
                chunks=chunks,
            )
            observations.append(observation)
            packet = {
                "case_id": case_id,
                "observation_sha256": observation.fingerprint(),
                "question": case.query,
                "required_facts": facts,
                "scope_note": annotation.scope_note,
                "passages": [
                    {
                        "chunk_id": c.chunk_id,
                        "source": c.source.model_dump(mode="json"),
                        "text": c.text,
                    }
                    for c in sorted(chunks, key=lambda c: c.chunk_id)
                ],
            }
            packets.append(packet)
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in [
        ("observations.jsonl", [r.model_dump(mode="json") for r in observations]),
        ("packets.jsonl", packets),
    ]:
        (output / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
            newline="\n",
        )
    (output / "receipt.json").write_text(
        json.dumps(
            {
                "observations_sha256": sha((output / "observations.jsonl").read_bytes()),
                "packets_sha256": sha((output / "packets.jsonl").read_bytes()),
                "cases": len(packets),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"exported_cases": len(packets), "questions_and_passages_stay_local": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    e = sub.add_parser("export")
    for name in ["artifact", "run", "cases", "answers", "source-root", "output"]:
        e.add_argument("--" + name, type=Path, required=True)
    e.add_argument("--method", choices=["bm25", "dense", "hybrid"], required=True)
    s = sub.add_parser("summarize")
    s.add_argument("--packets", type=Path, required=True)
    s.add_argument("--reviews", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "export":
        export(args)
        return
    receipt = json.loads((args.packets / "receipt.json").read_text())
    if sha((args.packets / "packets.jsonl").read_bytes()) != receipt["packets_sha256"]:
        raise ValueError("reviewer packets changed")
    data = (args.packets / "observations.jsonl").read_bytes()
    if sha(data) != receipt["observations_sha256"]:
        raise ValueError("review observations changed")
    observations = [
        ReviewObservation.model_validate_json(line) for line in data.decode("utf-8").splitlines()
    ]
    reviews = [
        SemanticReview.model_validate_json(line)
        for line in args.reviews.read_text(encoding="utf-8").splitlines()
    ]
    result = summarize_reviews(observations, reviews)
    print(json.dumps(result, indent=2))
    (args.reviews.parent / "semantic-summary.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
