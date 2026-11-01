# Full-source benchmark snapshots and test cases

This supersedes the tiny pilot as the product-scale benchmark.
See [the scale plan](../../../../docs/LARGE-BENCHMARK-PLAN.md).

Three acquired collections contain **18,434 documents**, about **4.244 GB**
per input copy or **8.487 GB** for separate raw/input copies:

- 4,723 published 3GPP PDFs: 4,709 cataloged versions plus 14 exact versions
  needed for native QA source references;
- all 3,857 HTML documents in the Linux kernel 6.18.0 Sphinx inventory;
- all 9,854 published entries in the frozen RFC index, including seven
  PDF-only documents.

`corpus-snapshots.json` records each acquired URL, size, SHA-256, relative
path, collection/document identity and collection snapshot hash. Original
sources are under `D:/RAGForge/data/benchmarks/scale-v1`, excluded from Git.
Ancillary website image/CSS/JS assets are not separate retrieval inputs.

`etsi-pdf-inventory.json` retains the original public catalog.
`tspec-markdown-inventory.json` records 15,420 alternative Markdown documents
(4.73 GB) at revision `2deccaebf031bb1eb063dcc87cc4392eb37a71a7`; gated content
was not downloaded. TSpec is neither an independent domain nor a test of our
PDF parser. The scoped ETSI catalog has no Release-20 PDF layer: do not claim
complete normative 6G coverage or confuse studies with normative requirements.

`policy.json` applies a **65 GB total budget** to sources, copies, extracted
text, staging, indexes, benchmark models and results together.
`storage-report.json` records preparation usage and free disk space.
`preflight.json` records actual current-limit failures: eight PDFs exceed
32 MiB and selected large PDFs have 5,790-7,123 physical pages, beyond the
current 500-page default. 3GPP/RFC collections exceed the 512 MiB scan default.
No large files were removed to hide these constraints.

## Cases and annotation status

`drafts/` contains **240 source-grounded AI draft queries** over RFC and
kernel: 100 single-document and 20 multi-document cases per corpus. Exact
frozen file and evidence-range hashes are provided. Multi-document cases
require both sources. Shared evidence stays together across splits; the
entire kernel corpus is a future cross-corpus holdout. Test labels are not
locked before independent review.

Evidence locations are offsets in a named canonical source representation,
not chunk IDs or invented public HTML line numbers. TXT canonicalization
collapses whitespace. HTML canonicalization extracts the main Sphinx body
and collapses whitespace. `validate_large_drafts.py` reconstructs these
representations from frozen bytes. Source matching alone does not establish
semantic correctness of a label.

Local TeleQuAD data supplies **4,763 native QA cases** plus **42 explicit
version draft variants**. Upstream extractive questions are manually
annotated; tabular questions retain upstream draft status. The bank includes
web/older-technology sources, not exclusively 5G/6G. Eleven invalid/empty
positive label spans are quarantined. Originals remain unchanged and local
adaptations are not redistributed.

Exact original 3GPP versions were acquired for 3,439 positive native cases.
2,726 have candidate text evidence in the correct source PDF and physical
page. These are source-alignment results, **not retrieval scores**, and need
review, including normalization effects for formulas/tables. Native paragraph
negatives are not full-corpus negatives. No draft is silently promoted to
strict gold. The 5,045 cases include correlated variants, not 5,045 independent
samples.

## Reproduction

Use the frozen snapshot rather than current latest catalogs:

```powershell
.\scripts\dev.ps1 run python scripts/restore_large_benchmark_sources.py --root D:/RAGForge/data/benchmarks/scale-v1 --download
.\scripts\dev.ps1 run python scripts/download_telequad_sources.py --root D:/RAGForge/data/benchmarks/scale-v1 --download
.\scripts\dev.ps1 run python scripts/align_telequad_sources.py --root D:/RAGForge/data/benchmarks/scale-v1
.\scripts\dev.ps1 run python scripts/prepare_large_benchmark.py --root D:/RAGForge/data/benchmarks/scale-v1
.\scripts\dev.ps1 run python scripts/validate_large_benchmark.py --root D:/RAGForge/data/benchmarks/scale-v1
.\scripts\dev.ps1 run python scripts/validate_large_drafts.py --source-root D:/RAGForge/data/benchmarks/scale-v1
```

The native downloader restores the pinned metadata needed for alignment.
These tools never import the product, build an index, download a model or
execute document code. Native originals/adaptations remain under `/data/`;
review upstream rights before distribution.

`tests/test_large_benchmark.py` has offline policy/fixture checks and an
opt-in external-data check (`RAGFORGE_TEST_EXTERNAL_DATA=1`). Missing data must
fail an explicitly requested external check. Skipping an unrequested external
check does not count as a product pass. The product and pytest were **not run**.
Full ingestion/retrieval, offline CLI, performance and release approval remain
unexecuted. Data validation is not a substitute for them.
