# Project instructions

- Canonical project directory on this computer is D:\RAGForge.
- Read docs/PLAN-REVIEW.md, docs/ARCHITECTURE.md and docs/BACKLOG.md before feature work.
- Preserve docs/RAGForge-Project-Plan.md exactly; put proposed changes in separate documents.
- Follow docs/RELEASE-SCOPE.md: v0.1 requires text-bearing PDF and dense/hybrid retrieval.
- Keep one local engine shared by CLI, MCP and HTTP. BM25 remains a runtime option and baseline.
- Default planned v0.1 profile is balanced; OCR is explicitly deferred by the user.
- Do not advertise unimplemented commands, simulated retrieval or fabricated benchmark results.
- Keep project environments, downloaded tools, caches, corpora and models on D.
  On this Windows machine use scripts/dev.ps1; do not install project tools globally.
- Run pytest, ruff check, ruff format --check, mypy and schema drift checks for code changes.
- Keep generated schemas consistent with the Pydantic models.
- No network calls, telemetry, automatic downloads or document execution in local retrieval.
- Remote/cloud features are later milestones. Build never implicitly deploys.
- The first release has not been licensed or published; do not infer a license choice from a proposal.
