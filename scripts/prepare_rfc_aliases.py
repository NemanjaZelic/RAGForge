"""Mine local RFC acronym definitions without reading any evaluation questions."""

import argparse
import collections
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ragforge.artifacts.verification import verify_bundle
from ragforge.core.aliases import Acronym, AliasBank, AliasProof, canonical, verify_aliases
from ragforge.core.sqlite import SQLiteEngine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.catalogue.stat().st_size > 64 * 1024**2:
        raise ValueError("catalogue too large")
    manifest = verify_bundle(args.artifact)
    collection = manifest.collections[0]
    docs = {d.source_path: d for d in collection.documents}
    engine = SQLiteEngine(args.artifact / collection.database_path)
    namespace = {"r": "https://www.rfc-editor.org/rfc-index"}
    payload = args.catalogue.read_bytes()
    counts = collections.defaultdict(lambda: collections.defaultdict(set))
    examples = {}
    with engine._connect() as connection:
        for entry in ET.fromstring(payload).findall("r:rfc-entry", namespace):
            name = entry.findtext("r:doc-id", default="", namespaces=namespace)
            if not name.upper().startswith("RFC") or not name[3:].isdigit():
                continue
            names = {name.lower(), "rfc" + str(int(name[3:]))}
            matches = [
                docs[n + s]
                for n in names
                for s in [".txt", ".html", ".htm", ".pdf"]
                if n + s in docs
            ]
            if len(matches) != 1:
                continue
            document = matches[0]
            node = entry.find("r:abstract", namespace)
            if node is None:
                continue
            abstract = " ".join(node.itertext())
            lead = None
            for match in re.finditer(r"\(([A-Za-z]{2,10})\)", abstract):
                short = match[1]
                if sum(char.isupper() for char in short) < 2:
                    continue
                words = re.findall(
                    r"[A-Za-z]+", abstract[max(0, match.start() - 150) : match.start()]
                )
                for size in range(2, min(10, len(words)) + 1):
                    expansion = " ".join(words[-size:])
                    if "".join(w[0] for w in words[-size:]).casefold() != short.casefold():
                        continue
                    if lead is None:
                        lead = canonical(
                            "\n".join(
                                row[0]
                                for row in connection.execute(
                                    "SELECT text FROM chunks WHERE document_id=? "
                                    "ORDER BY ordinal LIMIT 16",
                                    (document.document_id,),
                                )
                            )
                        )[:8192]
                    quote = expansion + " (" + short + ")"
                    if canonical(quote) not in lead:
                        continue
                    key = short.casefold(), expansion.casefold()
                    counts[key[0]][key[1]].add(document.source_path)
                    examples[key] = quote
                    break
    definitions = []
    for short, variants in sorted(counts.items()):
        ranked = sorted(variants.items(), key=lambda v: (-len(v[1]), v[0]))
        name, paths = ranked[0]
        if len(paths) < 3 or len(paths) / sum(len(p) for p in variants.values()) < 0.7:
            continue
        definitions.append(
            Acronym(
                short=short.upper(),
                long_form=name,
                proofs=[
                    AliasProof(
                        source_path=p,
                        source_sha256=docs[p].content_sha256,
                        quote=examples[(short, name)],
                    )
                    for p in sorted(paths)[:3]
                ],
            )
        )
    bank = AliasBank(catalogue_sha256=hashlib.sha256(payload).hexdigest(), definitions=definitions)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(bank.model_dump_json(indent=2) + "\n")
    verify_aliases(args.output, manifest, engine)
    print(bank.model_dump_json(exclude={"definitions"}))
    print(f"Prepared {len(definitions)} source-proven acronym expansions")


if __name__ == "__main__":
    main()
