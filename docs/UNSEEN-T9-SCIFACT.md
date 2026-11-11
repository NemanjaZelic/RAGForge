# T9 SciFact: one-pass test through public application commands

**First-run outcome: PASSED.** The observed 95% source-evidence target **passed**;
the all-requests-below-10-seconds target **passed**. The application code and model
profile were frozen before downloading the new dataset and were not tuned after
outputs. Every scored native claim received one `search_docs` call through the
unchanged public CLI server. This is an English scientific-evidence retrieval test,
not a generated-answer or scientific-verdict accuracy score.

| Measurement | First result |
| --- | ---: |
| Complete native rationale retrieved | **183/188 (97.34%)** |
| Every annotated document has a complete rationale | 181/188 |
| Primary results hit any native evidence document, diagnostic only | 186/188 |
| Actual successful MCP calls below 10 seconds | **188/188** |
| Actual MCP median / empirical p95 / maximum | **2.503 / 3.576 / 5.674 s** |
| MCP / grading errors | 0 / 0 |
| Complete evidence and below 10 seconds jointly | 183/188 |
| Server startup, separate | 21.605 s |
| One-time corpus build, approximate and separate | ~1345 s |

## A new collection and a frozen protocol

The [official AllenAI SciFact release](https://github.com/allenai/scifact) pairs
scientific claims with abstracts and annotated evidence sentence sets. The
[native schema](https://github.com/allenai/scifact/blob/master/doc/data.md) defines
supporting and contradicting rationale alternatives. The official public **dev**
partition was newly held out for this project; native test gold is hidden. This
is not an official SciFact leaderboard submission, nor a claim that public data
was absent from pretrained-model training.

The complete corpus contains **5,183 abstracts / 15,803 indexed chunks**.
All 300 native dev records were inspected by the data adapter using the frozen
eligibility rule. **All 188 claims with native evidence were evaluated**, without
sampling. The other **112 native no-evidence claims are outside this source-evidence
metric**, not successes. Abstention for those claims was not measured. No failure
was dropped after outputs. All 338 native rationale alternatives and their labels
were retained; invalid reference indices would stop preflight instead of silently
removing an example.

Success requires every sentence of at least one native rationale from an annotated
evidence document to occur in actual returned source text. `SUPPORT` and
`CONTRADICT` both identify relevant evidence: retrieving a refutation can be useful,
and does not mean that the claim is true. Returning the right paper alone is
insufficient. Native sentence sets remain unchanged. Additional relevant but
unannotated evidence is not given a semantic-review bonus. The secondary all-document
measurement is separate because different papers can supply independent sufficient
rationales for the same claim.

The [prospective protocol](benchmarks/t9-scifact-unseen-protocol-v1.json) was pushed
in commit `d081dd51d5bf78edf104d8becb8d20a231cbebe7` before the build and any measured
query. Application commit `1fa5c90c1106ca88db1b20420b8ffda4f2cb09d9` and all 70 product Python
files were frozen before acquisition. Runtime/model selection and retrieval/output
budgets stayed fixed for the first run. The original T8 and subsequent QASPER
validation results are unchanged.

## Only public build and serve commands inside the application

The test exported native titles and all abstract sentences into ordinary Markdown
files. No claim, evidence label, cited-document list or question/reference file
was indexed. Acquisition, format export and grading are test-adapter work; the
application itself ran its stock `ragforge.quickstart build` and `ragforge serve`
commands. There was no private build function, custom server, modified candidate
planner or patched ranking function.

The build reused the already installed explicit-English Intel-GPU setup, copied
byte-for-byte into isolated project state. Existing models and canonical active
bundle pointers remained intact. Commands, with paths substituted from the public
protocol, were:

```text
python -m ragforge.quickstart --project <isolated-project> build <exported-documents> --output <new-bundle> --threads 8
python -m ragforge serve <new-bundle> --warm-up --threads 8 --rerank-workers 2 --rerank-cache-batches 0
```

The stock English factory used balanced E5-small, the existing MS MARCO MiniLM GPU
reranker, token-aware sections (1000/100), ANN, facets-v3 and section-gaps-v3.
A persistent stdio MCP client sent each **unchanged native claim alone**. It supplied
**no paper title, document ID, cited-document hint, translation or filter**. The
whole corpus was searchable. No per-claim follow-up, retry, replacement, query
rewrite, parameter search or additional model was used.

Timing covers the actual `search_docs` round trip until sources return. A neutral
server warm-up and `list_collections` startup handshake preceded measured queries.
Build, startup, saving outputs and grading are outside query latency. Neural batch
caching was disabled by the public CLI flag; cache counters were not instrumented.

The public build succeeded once. The supervising script then looked for its
security receipt under the Windows venv launcher PID instead of the interpreter
PID. That bookkeeping error was recovered from the existing verified receipt and
completed artifact, without rebuilding or changing application code. Build time
is therefore an approximate timestamp-based measurement; query RPC timings use
the client performance clock normally.

## Evidence and execution checks

Each first structured response was saved before grading. Source hashes and every
nonempty indexed chunk were aligned to the exported native text before requests.
Returned text, offsets, document identity and physical source locations were
checked against the unchanged SQLite artifact. The same budget of 50 primary
results, at most 32 context chunks and 48,000 characters applied throughout.
Native query/reference locks and runtime hashes were checked again after the run.
A further automatic audit of the saved outputs used whitespace/Unicode/case
normalization while preserving punctuation, inequalities and numeric operators.
It independently reproduced 183/188 complete rationales and 181/188 all-document
passes, with zero disagreements or additional RAG queries. The frozen primary
metric and native labels stayed unchanged.

A security-only Python startup guard verified frozen source files, denied access
to the raw dataset/claims/archive and private labels/query/document-map files,
and blocked external Python network/DNS use. Its label-access denial was tested
before the stock command ran. Only socket/file security behavior was guarded;
retrieval and ranking functions were untouched. This was application-level checking,
not an operating-system isolation guarantee. Hardware remained the existing
Windows laptop: i7-1195G7, 12 GB RAM and integrated Iris Xe. There were no new
model downloads, paid services or full 3GPP runs.

The new small run prospectively reserved 10 GB free disk and used an 800 MB peak
allocation estimate within the existing 60 GB benchmark cap. Earlier test protocols
were not changed, and no old data/artifact was deleted. The public build command
was supervised for free space and duration; these checks are not an OS quota.

## What this establishes

The table reports the **first** unchanged-program result, even when a target is
missed. The conditions apply to this English, evidence-labelled public-dev group
and this corpus size. They do not establish all-language or 4.7-million-chunk 3GPP
performance, downstream answer truthfulness, no-evidence abstention, or a different
fresh-install model profile. The previous 3GPP development score remains 30/32
(93.75%) and was not rerun or relabeled. After this run, T9 is consumed; future
changes measured on it are development results.

[Machine-readable first-result aggregate](benchmarks/t9-scifact-first-results-v1.json)
records counts, timing, first-output/source/input locks and command-only execution
checks. Raw claims, answers, source text, native IDs and individual outputs remain
local and are not committed to Git. Production code stayed byte-identical, so the
previous software validation (578 passed, 19 skipped) was not repeated locally
for this documentation-only evaluation; exact-commit CI is checked before main.
