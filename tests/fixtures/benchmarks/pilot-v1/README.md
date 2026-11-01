# RF-006B: pilot test set, v1

Prepared 2026-11-01 from [TESTING-PLAN](../../../../docs/TESTING-PLAN.md) and the
adopted [release scope](../../../../docs/RELEASE-SCOPE.md). The product was not run.
This is an **AI-authored draft awaiting independent review**, not measured
retrieval quality or an independently verified golden benchmark.

| Corpus | Frozen input | Questions | Positive / unsupported |
| --- | --- | ---: | ---: |
| `uv-guides` | uv 0.9.5: projects, scripts, tools, README | 30 | 24 / 6 |
| `python-tutorial` | Python 3.13.0 rendered tutorial chapters 4, 5, 7, 8 | 30 | 24 / 6 |
| `http-semantics` | Original RFC 9110 PDF, 194 physical pages | 30 | 24 / 6 |

There are 9 source files, 41 evidence spans and 90 questions. MD, TXT, HTML
and text-bearing PDF are present. The TXT input is the uv README with only
the extension changed; its bytes are identical to upstream Markdown. It
tests TXT ingestion and is not a fourth independent corpus. Some questions
use Serbian Latin/Cyrillic; this is a supplement, not a Serbian real corpus.

## Files and source preparation

- `dataset.json`: URLs, revisions, source hashes/sizes, snapshot identities,
  relative roots, rights/attribution references and preparation status.
- `evidence.jsonl`: document identities and exact source sections/ranges,
  independent of any chunking configuration.
- `gold/{dev,tuning,test}.jsonl`: 30 questions per split, including 10 per
  corpus (8 answerable, 2 unsupported).
- `selection.json`: selection rationale, seed, exclusions and pilot limitations.
- `controls/`: small authored fault/adversarial inputs and their expectations;
  these do not count as additional real corpora or part of the 90 questions.
- `scenarios.json`: future product checks and required evidence. All are
  explicitly `not_run`; a checklist entry is not an executed product test.

Original files are local only under `D:/RAGForge/data/benchmarks/pilot-v1`.
Each corpus has separate `raw/` and `input/` directories; raw files are read-only.
The existing repository `/data/` ignore rule keeps source corpora out of Git.
No upstream document text or model is redistributed in this test set.
No code snippets or commands from documents were executed.

To acquire the exact sources on another machine, run **only as explicit
network preparation**, from the repository root:

```powershell
.\scripts\dev.ps1 run python scripts/prepare_benchmark_sources.py --destination D:/RAGForge/data/benchmarks/pilot-v1 --download
```

Without `--download`, this command accepts existing verified raw files only.
Changed downloads fail the pinned SHA-256 check; do not update hashes to make
a failing comparison pass. Keep build outputs and reports outside `input/`.
Review source-specific license/notice requirements before redistributing
documents. No license for RAGForge itself is selected here.

The validator does not import the product, build an index or issue queries:

```powershell
.\scripts\dev.ps1 run python scripts/validate_benchmark_set.py
.\scripts\dev.ps1 run python scripts/validate_benchmark_set.py --source-root D:/RAGForge/data/benchmarks/pilot-v1
```

The first command validates metadata without downloads. The second additionally
checks raw/input bytes and evidence hashes, using pinned pypdf 6.21.4 only for
PDF source extraction. These are data checks, not retrieval benchmarks.
`tests/test_benchmark_pilot.py` protects the dataset against duplicate IDs,
snapshot drift, unresolved evidence, cross-split leakage and premature gold
promotion. It is prepared for normal pytest discovery; pytest was not run as
part of preparing this set.

## Label contract and review

Each query has a stable ID, corpus/snapshot/collection, language, task type,
topic group, split, expected facts, an answer rubric and review metadata.
`required_evidence_groups` is an AND across groups and an OR within `any_of`:
all groups are needed, but any reviewed alternative within a group is valid.
The document relevance list is derived from the evidence, not a separate ID
system. Grade 2 means direct supporting source; future grade 1 can identify
reviewed contextual support. No unreviewed document is presumed irrelevant.

Line locations are 1-based and inclusive over the frozen file. HTML byte
ranges are zero-based, end-exclusive UTF-8 source ranges with an element ID;
they are review anchors, **not invented public HTML line numbers**. PDF pages
are 1-based physical file pages. PDF character ranges are zero-based and
end-exclusive within that page's pypdf plain text. `span_sha256` covers the
exact selected bytes or the UTF-8 PDF text range without normalization.
PDF headings and all 14 referenced physical pages were also visually checked.
Source verification is not independent annotation review.

Evidence ranges locate supporting sections. Merely overlapping a large
section does not prove that a returned fragment supports the expected fact.
During independent review, tighten ranges where useful, verify every fact,
add legitimate alternative sections, and record disagreements. An answer
must cite text supporting its actual claims, not just the right file/page.

All 90 rows have `review.status=ai_draft`, no independent reviewer,
`relevance_complete=false` and `strict_scoring_eligible=false`. There is no
automatic promotion command. Reviewers must read the frozen sources, verify
labels/absence checks and approve a separately versioned reviewed release.
The validator intentionally accepts only this draft contract; promotion
requires a reviewed schema/validator update as well.

Unsupported questions are scoped to the exact input subset. They do not claim
that no external document can answer them. Absence rationale, search terms
and full input scope are recorded; independent confirmation remains pending.
Return of loosely related fragments is not itself a retrieval failure or
proof of answerability. Agents must explicitly acknowledge insufficient
evidence rather than fabricate an answer.

## Splits and future scoring

The seed and SHA-256 ordering are fixed before product runs. Connected topics
and shared evidence remain together. Each topic has two correlated question
variants; do not treat 90 rows as 90 independent samples when estimating
uncertainty. Do not expose test labels to the optimizer.

`test` is **reserved**, not yet locked: annotations still require review.
After review and evaluator rules are frozen, lock a version and record which
candidate/configuration is evaluated. If test results inform development,
reclassify that set as development data and prepare a fresh final test.
This three-corpus pilot does not establish cross-corpus generalization.
At the planned five-corpus expansion reserve at least one whole corpus.

Future runs must compare BM25, dense and default hybrid on identical source
hashes, queries, `top_k=10` and `max_output_chars=16000` (report actual output
sizes). Report Recall@5/10, MRR@10 and nDCG@10 for positives, document and
evidence coverage separately, and unsupported cases separately. Deduplicate
document IDs before document-level ranking; one PDF document makes its
document-level recall trivial, so page/span/fact evidence is essential there.
An evidence group is covered only by supporting content, not a filename hit.
No global quality threshold is invented before the reviewed pilot.

Report per corpus/type, then equal-weight corpus macro averages, question
counts, incomplete judgments and uncertainty. Measure real build time, peak
RAM, bundle size, cold/warm median/p95 latency, hardware and versions only
after product execution is possible. Never fill missing measurements with
zeros or label unimplemented paths as passed.

BM25 mode over a balanced bundle must block embedding inference; hybrid
requires real local weights. Future product E2E must build, copy a bundle to
a different path, query/fetch context and verify citations offline. Keep
query/label data outside ingestion roots. The mixed-format scenario combines
these existing files and counts as a pipeline check, not new independent data.
MCP/agent, shared, remote, serverless and optimizer checks remain later gates.
