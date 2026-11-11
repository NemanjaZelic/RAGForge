# Explicit title scope: first quality and latency results

The shared engine now resolves an explicitly supplied document title before
ranking the question. On the existing laptop, the implemented product achieved
**120/120 full native-evidence support on the consumed T8 development replay**
and **120/120 on a frozen validation partition of different questions and papers**.
All 240 product MCP requests completed below 10 seconds. These are English,
explicitly paper-scoped source-retrieval results on the QASPER corpus; they do not
establish universal quality, all-language quality or 3GPP-scale latency.

| Partition / method | Complete native evidence | Median MCP | p95 MCP | Maximum MCP |
| --- | ---: | ---: | ---: | ---: |
| Original untouched T8 first test, global title + question | 97/120 (80.83%) | 2.634 s | 3.151 s | 4.270 s |
| Same T8, product explicit-title development replay | 120/120 (100%) | 0.497 s | 0.850 s | 1.972 s |
| First paper-disjoint validation, frozen product | 120/120 (100%) | 0.536 s | 1.043 s | 2.059 s |

The quality metric and original native labels are unchanged: returned source text
must cover **every evidence paragraph for at least one eligible native annotation**.
No semantic-review bonus, rewritten question, excluded failure, label repair or
retry increases either new score. Returned text, offsets, physical source
locations and the same output limits (50 primary chunks, at most 32 context
chunks, 48,000 characters) were verified for every response. Correct document
identity alone is insufficient. These measurements establish source support,
not truthfulness of a downstream generated answer or official QASPER answer F1.
The Wilson 95% interval for each 120/120 sample is 96.90-100%; it does not account
for reference-label errors or distribution shift.

## Why the original result was lower

The previous development sets and this first new test differ in question style,
size, labeling and prior exposure during development. Their percentages are not
interchangeable. Many QASPER questions are short and refer to a particular paper,
whose title was supplied with the question. The old engine treated that title
as more ranking text across the collection. Miss inspection found repeated
introductions and broad descriptions of the right study without its requested
evaluation datasets, full method lists or numeric sizes. A stricter whole-paragraph
native evidence metric also differs from earlier minimal-fact judgments.

The implemented change separates two jobs: identify the document the user names,
then rank the actual question within it. The existing FTS index finds literal
title candidates, and the engine checks the first indexed source heading. A unique
exact match inside the caller's existing document grant narrows retrieval; unknown,
duplicate or overly broad title matches retain the old request. No benchmark
document IDs or answer map are supplied to the resolver. The original caller
question plus native title is unchanged; the internal title-derived filter is
an explicit feature of the **new** protocol. This is an intentional switch from
global retrieval to source-confirmed document retrieval, not a claim that the two
search protocols are identical.

The gain includes dedicating the bounded context budget to the requested paper,
which often fits substantially within that budget. It does not prove the same
result for huge single documents or queries that supply no source scope.
Maximum reranker pairs fell from 322 in the original test to
125 in the product development replay and
139 in validation. There was no new model, additional inference service,
index rebuild or larger answer budget. See [usage and fallback rules](DOCUMENT-SCOPE.md).
The generated provider-neutral agent skill now teaches this workflow.

## Validation locked before requests

Product and [prospective validation protocol](benchmarks/title-scope-validation-protocol-v1.json)
were published in commit `9c62cfc09281144cea59bdebea1f236c1b2b1ecf` before the
first validation request. The code was frozen for both product evaluations and
was not tuned after validation outputs. A private earlier wrapper prototype also
scored 120/120 on the development questions; the table uses the subsequent actual
product run, not that prototype's times.

The validation sample uses the same official QASPER v0.3 test corpus: **all 416
papers / 15,490 chunks** remain indexed. It excludes every original T8 paper,
then selects one eligible question per remaining paper and 120 papers by fixed
seeded SHA-256 ordering. There were 283 eligible remaining papers and 870 eligible
remaining questions; first annotation types were 82 extractive, 25 free-form and
13 yes/no. Native answers and references were retained unchanged. Eligibility
uses the same prospectively defined answerable, locatable textual-evidence rule;
figure/table-only questions are outside this measurement. Thus validation has
**120 different papers and questions**, within the same dataset family and source
index. It is not a second independent corpus or proof of unseen model pretraining.

The actual stdio MCP server used frozen copies of all 70 product Python files.
Its Python audit guard denied private benchmark questions, references and document
maps; Python network/DNS use was blocked during retrieval. These were application
checks, not an operating-system isolation guarantee. Each first response was
saved before grading. Both runs had zero MCP/grading errors, zero neural cache hits
and zero network attempts. A neutral warm-up preceded timing. Separate startup:
8.897 s for development and 8.009 s for validation. The original
905-second corpus build was reused; startup and build are outside query latency.
Hardware: i7-1195G7, 12 GB RAM, integrated Iris Xe, existing E5-small and MS MARCO
MiniLM GPU reranker, eight threads and two reranker workers.

## Regression checks and remaining limits

The final product code passed **578 tests, 19 skips**, Ruff checks and formatting,
Mypy and schema-drift checks. The new scope tests cover literal/Unicode titles,
source versus body/nested-heading matches, ambiguity, limits, existing document
grants and consistent original/translated question scopes. Existing bundles do
not need rebuilding and public request/response schemas remain unchanged.

All 60 previous sampled unscoped requests passed an identity/no-extra-SQL regression
check: the new resolver returns their original request object. This is not a new
60-question neural accuracy measurement. The original consumed 3GPP subset remains
**30/32 (93.75%)**; it was not rerun or relabeled. No full 3GPP evaluation ran.
Queries without an explicit title keep their existing retrieval behavior.

The original [T8 first result](UNSEEN-T8-QASPER.md), including 97 native passes and
its separate 104/120 AI-assisted estimate, remains intact. The new 100% figures
use native evidence alone. They meet the observed 95% and sub-10-second goals for
these two English paper-scoped samples. They do **not** establish 95% for every
corpus/language, unscoped questions or 4.7-million-chunk 3GPP performance. Native
references can be imperfect, and public-benchmark overlap with pretrained models
is unknown. After observing this validation result, its questions are consumed;
any future tuning on them must be described as development.

[Machine-readable aggregate](benchmarks/title-scope-first-results-v1.json) records
sample locks, source/build identity, runtime recipes, response-set hashes and metrics.
Raw questions, answers, source quotes and individual review/output records remain
local and are not redistributed in Git.
