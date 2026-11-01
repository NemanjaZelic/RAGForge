"""Generate checked-in schemas or fail when they drift from the Python models."""

import argparse
import json
from pathlib import Path

from ragforge.cli import SchemaName, schema_document

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name in SchemaName:
        path = SCHEMAS / f"{name.value}-v1.schema.json"
        content = json.dumps(schema_document(name), indent=2, sort_keys=True) + "\n"
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                print(f"Schema drift: {path.name}")
                return 1
        else:
            SCHEMAS.mkdir(exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
