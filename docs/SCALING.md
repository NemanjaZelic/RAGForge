# Full-source ingestion and explicit capacity

Prepared scale inputs are integrated without changing their source hashes or labels.
`ingest` processes the whole scanned inventory and checkpoints every document in a
private parsing journal. A resumed job rehashes sources and checks the recipe;
changed snapshots require a new job. Concurrent writers are rejected by an OS lock.
Failures and missing/blank PDF text are counted, with paths, pages and diagnostics.
Completion of an audit is distinct from successful, complete ingestion.

```powershell
.\scripts\dev.ps1 run ragforge ingest data/benchmarks/scale-v1/ietf-rfcs/input --collection ietf-rfcs --job data/benchmarks/scale-v1/runs/rfc-job --pdf-backend pdfium --max-file-bytes 67108864 --max-total-bytes 6442450944 --pdf-max-pages 10000 --pdf-max-text-chars 64000000 --allow-partial-pdf --continue-on-error --storage-root data/benchmarks
.\scripts\dev.ps1 run ragforge job-status data/benchmarks/scale-v1/runs/rfc-job
# Same arguments plus --resume; add --retry-failed to explicitly retry errors.
```

Workers have actual OS memory limits (Windows process committed bytes, Linux
address space) and parent-enforced wall deadlines. A timed-out private worker is
terminated, including the Windows venv interpreter child. No document code,
JavaScript, PDF actions, attachments or network calls are executed.
The default worker limit is 512 MiB and 300 seconds per document. These are
separate from page/text/scan limits. A worker failure is recorded, never hidden.

`pdfium` is optional (`ragforge[pdf-fast]`, pinned pypdfium2 5.14.0). Its explicit
page/text bounds and worker budgets replace pypdf decoded-stream/work counters;
it does not claim to enforce those counters. The pypdf backend and strict UTF-8
remain defaults. PDFium text is versioned separately, with physical page citations
and unknown line numbers. Blank/scanned pages remain visible; no OCR fallback.
See [PDFium's API and process/thread requirements](https://pypdfium2.readthedocs.io/en/stable/python_api.html).

Historical text can use explicit `--text-fallback latin-1 --escape-controls`.
Valid UTF-8 is still preferred; invalid bytes are not silently replaced. Control
characters become visible escape sequences, and actual decoding/escaping enters
parser identity and warnings. Original bytes/hashes remain untouched. A strict
journal can upgrade these policies and retry only previously rejected documents;
successful clean parses are identical. Other semantic recipe changes require a
new job. HTML extraction prefers an authored main landmark, with a generic
fallback for pages without one; navigation outside that landmark is excluded.

A source-bound journal can feed the existing builder:

```powershell
.\scripts\dev.ps1 run ragforge build data/benchmarks/scale-v1/ietf-rfcs/input --collection ietf-rfcs --ingest-job data/benchmarks/scale-v1/runs/rfc-job --output data/benchmarks/scale-v1/runs/rfc-bundle --model models/e5-small --chunk-size-chars 350 --overlap-chars 50 --max-index-chunks 8000000 --max-index-text-chars 4000000000 --allow-incomplete
```

Scan/PDF options come from the journal. By default the builder refuses pending/failed source
records, verifies cached payload checksums and source identities, and retains the
full document inventory. `--allow-incomplete` explicitly permits recorded PDF page
losses; it does not omit failed documents. No sampled corpus is substituted.

Indexing streams chunks; dense lookup streams ordered IDs from SQLite instead of
materializing millions of Python strings. Finite capacities are 8 million dense
rows, 16 GiB per bundle file, 32 GiB per bundle. These are supported limits, not
claims of measured performance. Dense float32 blocks stay within 16 MiB for
validation/scoring. Character chunk limits never silently truncate model tokens.

The shared benchmark budget is 65,000,000,000 logical bytes, with a default
15,000,000,000 bytes of free disk reserved. Storage checks cover the chosen root,
refresh external growth periodically and check reservations before document
writes. This is an application guard, not an OS filesystem quota against unrelated
writers. Keep benchmark caches, staging, models and results under the budgeted
root, and account for any reused external model assets in the final storage report.
Prepared raw/input copies are retained. Detailed run data remains under ignored
`data/`; public-source manifests and aggregate reports can be versioned separately.

Labels remain drafts and final test sets remain unlocked. Ingestion coverage and
exploratory retrieval measurements are not strict release-quality approval.


## Resumable balanced builds and explicit ANN

Use `build --job NEW_JOB --dense-backend ann` for the large benchmark; repeat the
same command with `--resume` after interruption. `job-status JOB` reports committed
embedding rows and completed ANN shards. The job binds source bytes, parser cache,
model, chunking, thread count and embedding pipeline. Completed components are
hashed, committed vector prefixes validated, and publication remains atomic and
no-replace. Private unfinished staging is retained for a resumable job.

ANN is an optional extra (`ragforge[scale]`, USearch 2.26.6), never an automatic
replacement for exact cosine. Bounded shards contain 25,000 rows, f16 vectors,
HNSW connectivity 16, construction expansion 128 and query expansion 64. Search
merges candidates from every shard and reranks their stored f16 vectors. This is
approximate retrieval; document-filtered scoring uses exact stored-vector cosine.
A framed `dense.index` inventories shard hashes, byte offsets and SQLite row IDs.
The normal exact backend and BM25 remain available. BM25 imports neither model nor
ANN runtime. These capacities are engineering limits, not measured quality claims.

Explicit `--allow-permitted-pdf` ingestion can extract an encrypted PDF only when
it opens without a supplied password and grants text extraction. The default
still rejects encryption. Disallowed sources stay failures. A diagnostic build
can retain such records with zero chunks using **both** `--allow-incomplete` and
`--allow-failed-documents`; verification reports them separately. It never drops
source inventory or manufactures searchable content for failed inputs.

## Evidence evaluation

`evaluate ARTIFACT --cases CASES.jsonl --source-root ORIGINALS --output NEW_DIR`
executes the real bundle engine. Use `--split`, optional `--track`, and repeated
`--method` flags; default methods are the bundle capabilities. Frozen evidence is
bound to original source hashes, independent canonical offsets and span hashes.
PDF evidence requires `--pdf-reference-cache` from the original label extractor,
not product chunks. `scripts/prepare_pdf_evidence_cache.py` reconstructs this cache
without rewriting labels, using isolated, bounded pypdf workers.

Results include document Recall@5, document MRR@10, mean evidence group coverage,
and the fraction covering every required group by at least 80%. The coverage
threshold defines a diagnostic metric, not a release quality target. Repeated
ambiguous text is uncredited; document hits cannot substitute for evidence from
all required documents. Context-only negatives are excluded from global-negative
scoring. Draft labels require `--allow-draft` and cannot approve a release.

A SQLite result journal checkpoints each actual query. Explicit `--resume` binds
the same artifact, case file, limits, split, track and scorer. Reports separate
first-query timing, p50/p95 wall latency, setup time, source coverage and actual
process memory. OS caches are not cleared; process peaks are not whole-machine
or aggregate-worker peaks. Detailed native QA adaptations remain local and ignored
by Git. Only aggregate diagnostic reports may be saved to the private repository.


## Complete scale run on this workstation

The source/evidence preflight verified 3,005 cases and 4,347 source spans without
changing labels. This validates source alignment, not retrieval or label quality.
The prepared kernel corpus is a whole-corpus holdout: parameters below are fixed
before observing its retrieval scores and will not be tuned on those scores.

```powershell
.\scripts\dev.ps1 run python scripts/prepare_pdf_evidence_cache.py --root data/benchmarks/scale-v1 --output data/benchmarks/scale-v1/runs/pdf-reference-v1 --budget-root data/benchmarks --resume
.\scripts\dev.ps1 run python scripts/run_scale_benchmark.py --root data/benchmarks/scale-v1 --output data/benchmarks/scale-v1/runs/execution-v1 --model models/e5-small --cases data/benchmarks/scale-v1/runs/cases-v2 --pdf-cache data/benchmarks/scale-v1/runs/pdf-reference-v1 --budget-root data/benchmarks
```

Use `--resume` on the second command after interruption. For a fresh reference
cache omit `--resume` on the first command. The controller freezes product source,
its own driver, dependency versions, case hashes and retrieval parameters in the
run directory. Offline child processes use the frozen code even during further
development. Mutable job and runtime files stay on D, outside source inventories.
The controller exits on failure with resumable checkpoints and logs.

The order is kernel, RFC, then 3GPP. Each complete balanced artifact is measured
with BM25/dense/hybrid over dev/tuning/test separately. Native alignment,
version-scoped and supplementary tracks remain separate; the controller never
changes configuration using scores. `aggregate-summary.json` is updated after
each stage and uses equal corpus weight within each track/split, with explicit
incomplete status until every stage finishes. Detailed query journals stay local.

This runner caps the benchmark data root at **60 GB**, leaving **5 GB** of the
65 GB total for the prepared source model and isolated GPU feasibility environment
outside that root. An additional **15 GB free disk reserve** is enforced. Final
budget reports must also account for those external assets. The reserve does not
expand corpus support or remove any files automatically. CPU-heavy embedding may
take many hours; prepared tests and passing CI do not mean that workload completed.


## Private progress backup

`scripts/save_benchmark_report.py RUN --watch` is an explicitly online maintenance
tool, separate from the offline controller. It saves only whitelisted numerical
measurements, known corpus/track names and hashes to `results/scale-v1`. Original
questions, document text, answers and per-case records are excluded. Before every
push it verifies the expected remote and private repository visibility; pushes
are never forced. An isolated Git index leaves the working branch and user index
untouched. Upload failure is logged and retried at most three times.

The results branch contains `docs/benchmarks/scale-runtime-v1.json`. CI ignores
results-only branch pushes; software checks continue on development branches and
pull requests. These automated report commits neither promote drafts to release
ground truth nor change the active application version.
