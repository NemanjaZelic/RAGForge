# RAGForge

Portable document retrieval for agents. Local execution is the default.

**Development stage: Phase 1 started (RF-000 and RF-001 complete).**
Document indexing and search are the next milestone; they are not implemented yet.

Start with the [current working plan](docs/PROJECT-PLAN.md).
The original proposal is preserved in [docs/RAGForge-Project-Plan.md](docs/RAGForge-Project-Plan.md).
The [optional optimization plan](docs/OPTIMIZATION-PLAN.md) defines four effort levels:
first try, light, high and max. Runtime is estimated from hardware measurements and
the corpus; max receives an automatic budget of at least 8 h, with justified early
convergence allowed. Optimization is not implemented.
See the [explicit change list](docs/PLAN-CHANGES.md) for proposals and status.
The [real-documentation testing plan](docs/TESTING-PLAN.md) starts with three
corpora and 30 reviewed questions each, then expands toward five diverse corpora.
External corpora and golden sets are planned, not downloaded or evaluated yet.
Read the [plan review](docs/PLAN-REVIEW.md), [architecture decisions](docs/ARCHITECTURE.md)
and [implementation backlog](docs/BACKLOG.md) before starting feature work.

## Development on this computer

Project location: `D:\RAGForge`. Python 3.13 is available.
Project tools, virtual environments, caches and temporary build files stay on D.

```powershell
cd D:\RAGForge
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 check
.\scripts\dev.ps1 run ragforge --help
.\scripts\dev.ps1 run ragforge doctor
.\scripts\dev.ps1 run ragforge scan examples/mini-docs --collection mini
.\scripts\dev.ps1 run ragforge schema manifest
```

The setup step downloads development packages. Installed CLI commands work locally.
The repository-local uv executable is `.tools\Scripts\uv.exe`.

On another machine with uv installed:

```bash
uv sync --locked
uv run ragforge --help
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python scripts/export_schemas.py --check
```

## Implemented

- Typer CLI: corpus scan, help, version, SQLite/FTS5 doctor and JSON Schema export.
- Deterministic MD/TXT/HTML/PDF discovery and bounded SHA-256 hashing, link and collision rejection.
  Scan inventories bytes; it does not parse PDF text or build a searchable index.
- Validated minimal/balanced draft manifests and BM25/dense/hybrid query contracts; engine protocol.
- Synthetic manifest examples in `examples/manifests/`; these are not built bundles.
- Small original document corpus and 20 development queries with authored relevance labels.
- Tests, formatting, linting, type checking and GitHub Actions configuration.

## Next release: v0.1

[Approved scope](docs/RELEASE-SCOPE.md): mixed MD/TXT/HTML/text-bearing PDF input,
local embeddings, BM25 + dense retrieval with RRF, a portable balanced bundle,
and cited local query results. Text-bearing PDF and hybrid are release requirements.
OCR is deferred. Balanced/hybrid is the planned default; BM25 is an explicit
lightweight query option on the same bundle and the benchmark baseline.

`mixed documents → parse/chunk → BM25 + dense → bundle → hybrid query → cited source`

Planned commands such as `build`, `use`, `integrate` and `deploy` are not advertised
as working commands. Phase 0 currently has no dense model or PDF implementation.
The planned v0.1 balanced path requires a locally available embedding model;
HTTP hosting, GPU, cloud accounts and Docker are not required.

The bundle data format and the executable runtime are separate. A bundle is not
a universal executable for every operating system.

Project license is still a proposal in the source plan; no license choice or
public release has been made.

Private GitHub setup and progress: [docs/PROGRESS.md](docs/PROGRESS.md).
