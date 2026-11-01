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
.\scripts\dev.ps1 run ragforge build data/benchmarks/scale-v1/ietf-rfcs/input --collection ietf-rfcs --ingest-job data/benchmarks/scale-v1/runs/rfc-job --output data/benchmarks/scale-v1/runs/rfc-bundle --model models/e5-small --chunk-size-chars 350 --overlap-chars 50 --max-index-chunks 5000000 --max-index-text-chars 4000000000 --allow-incomplete
```

Scan/PDF options come from the journal. The builder refuses pending/failed source
records, verifies cached payload checksums and source identities, and retains the
full document inventory. `--allow-incomplete` explicitly permits recorded PDF page
losses; it does not omit failed documents. No sampled corpus is substituted.

Indexing streams chunks; dense lookup streams ordered IDs from SQLite instead of
materializing millions of Python strings. Finite capacities are 5 million dense
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
