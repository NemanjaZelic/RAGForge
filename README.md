# RAGForge

Portable document retrieval for agents. Local execution is the default.

**Development stage: local balanced retrieval, stdio MCP and authenticated shared HTTP.**
Portable minimal/balanced bundles, local BM25/dense/hybrid search and source
citations now work, with an MCP adapter and passive agent skill/config generator.
Broader retrieval and autonomous-agent evaluation remain in the plan.
See [local bundle behavior and limits](docs/LOCAL-BUNDLES.md) and
[MCP setup, tools and limits](docs/MCP.md).

Start with the [current working plan](docs/PROJECT-PLAN.md).
The original proposal is preserved in [docs/RAGForge-Project-Plan.md](docs/RAGForge-Project-Plan.md).
The [optional optimization plan](docs/OPTIMIZATION-PLAN.md) defines four effort levels:
first try, light, high and max. Runtime is estimated from hardware measurements and
the corpus; max receives an automatic budget of at least 8 h, with justified early
convergence allowed. Optimization is not implemented.
See the [explicit change list](docs/PLAN-CHANGES.md) for proposals and status.
The [real-documentation testing plan](docs/TESTING-PLAN.md) starts with three
corpora and 30 reviewed questions each, then expands toward five diverse corpora.
Three complete frozen corpora (18,434 files) and draft evidence questions are local.
Full-source ingestion and scheduled large retrieval measurements are complete.
Retrospective 3GPP source review is complete; quality targets and independent validation remain open. See [scale execution](docs/SCALING.md).
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
.\scripts\dev.ps1 run ragforge chunk examples/mini-docs --collection mini
.\scripts\dev.ps1 run ragforge index examples/mini-docs .cache/demo.sqlite --collection mini
.\scripts\dev.ps1 run ragforge search .cache/demo.sqlite rollback
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

- Read-only stdio MCP: search_docs/fetch_context/list_collections over the same engine;
  passive Agent Skills and separate MCP config generator (`integrate`).
- Authenticated REST/stateless MCP HTTP over the same engine, offline RS256 JWT verification,
  source permissions, TLS and explicit shared CLI client. Passive deploy/connection
  profiles support verified version activation/rollback with an explicit restart.
  See [shared setup](docs/SHARED.md).
- Typer CLI: build/use/verify/context/serve/integrate, resumable ingest/build jobs, evidence evaluation,
  standalone index/search, corpus scan, chunk preview and SQLite/FTS5 diagnostics.
- Deterministic MD/TXT/HTML/PDF discovery and bounded SHA-256 hashing, link and collision rejection.
  Scan inventories bytes; it does not parse PDF text or build a searchable index.
- Text-bearing PDF parsing, physical page citations, page status and explicit partial mode;
  bounded streams/work, original PDF fixtures and a 194-page real PDF parser pilot.
  OCR is disabled. See [PDF behavior and limits](docs/PDF.md).
- Strict UTF-8 MD/TXT/HTML parsing, Markdown headings/fenced code, deterministic bounded chunks,
  verified source bytes and source citations. HTML script/style/head/template data is excluded;
  HTML source line numbers remain unknown. See [parser limits](docs/PARSING.md).
- Real SQLite FTS5/BM25 engine: literal queries, filters, read-only results and scoped context.
  See [retrieval behavior and measured baseline](docs/RETRIEVAL.md).
- Local ONNX CPU embeddings, exact cosine or explicit optional sharded ANN, and RRF
  over the same SQLite sources; resumable vector/shard construction for large corpora.
- Balanced defaults to hybrid; raw BM25 never imports/loads embedding libraries.
- Optional verified local cross-encoder reranking, section-aware chunks, and answer-fact
  evaluation with accepted alternative citations. See [quality work and limits](docs/QUALITY.md).
- Optional bounded question planning and short-section context completion in the same engine,
  enabled with `recontextualize --query-planning facets-v2 --section-context section-start-v2`.
  Generated agent instructions for planned section bundles specify the wider measured
  request limits (`top_k=50`, `max_output_chars=48000`).
- Optional source-bound definition and adjacent-context completion in the shared engine;
  corpus-only preparation, explicit local use or portable attachment.
  See [source context and measured limits](docs/SOURCE-CONTEXT.md).
- Verified bundle inventories, copied query model/licenses and atomic publication to a new directory.
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

`mixed documents Ã¢â€ â€™ parse/chunk Ã¢â€ â€™ BM25 + dense Ã¢â€ â€™ bundle Ã¢â€ â€™ hybrid query Ã¢â€ â€™ cited source`

The local `build`, `use`, `verify` and `context` commands work on the same engine.
Model preparation is explicit and separate; build/query never download anything.
The initial multilingual model candidate is a pinned quantized E5-small.
Representative quality evaluation is a separate workstream and still gates v0.1.
Read-only stdio MCP and passive skill/config generation are implemented.
Shared REST/MCP HTTP is implemented with explicit JWT policy and TLS controls.
Independent agent evaluation, operational rollout and remote compute remain later milestones.

The bundle data format and the executable runtime are separate. A bundle is not
a universal executable for every operating system.

Project license is still a proposal in the source plan; no license choice or
public release has been made.

Private GitHub setup and progress: [docs/PROGRESS.md](docs/PROGRESS.md).
Long Windows benchmark runs: [background launcher](docs/BACKGROUND-BENCHMARKS.md).

## Local balanced quickstart

Development setup installs the optional balanced dependencies. Once, while online,
prepare the pinned public model (skip this if the directory is already prepared):

```powershell
.\scripts\dev.ps1 run python scripts/prepare_models.py e5-small models/e5-small
.\scripts\dev.ps1 run ragforge build examples/mini-docs --output kb/mini-v1 --model models/e5-small --collection mini --offline
.\scripts\dev.ps1 run ragforge use kb/mini-v1 --mode local --query "How are access tokens sent?"
.\scripts\dev.ps1 run ragforge use kb/mini-v1 --query rollback --search-method bm25
```

Use a new output directory for each build. Minimal build uses `--profile minimal`
and needs no model/ML dependencies. Bundles contain data and a local query model;
a compatible runtime installation is still required on the receiving machine.
