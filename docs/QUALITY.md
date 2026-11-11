# Retrieval quality and answer-bearing evidence

The user target is at least **95%**, with **99%** considered excellent. Neither
threshold has been demonstrated across all corpora and languages. The
[explicit-title QASPER validation](DOCUMENT-SCOPE-RESULTS.md) reached 120/120
complete native-evidence support below 10 seconds on a frozen English
paper-disjoint sample. That bounded result does not establish a global quality
guarantee. Document Recall@5 is a component diagnostic;
it is not answer accuracy. RAGForge returns sources, not generated answers.

## Original independent T8 first test

The [first QASPER test](UNSEEN-T8-QASPER.md) used 120 unchanged English questions
on 416 papers. Complete native evidence was 97/120 (80.83%); adding seven
source-quoted AI sufficiency judgments gives 104/120 (86.67%), with independent
human review pending. All 120 actual MCP calls were below 10 seconds (maximum
4.270 s). Speed passed on this corpus; the 95% quality target failed. The runtime
was frozen before the first T8 requests. Subsequent title-scope development and
validation are described in the separate report. This is source support, not generated-answer
accuracy or proof for all languages or 3GPP-scale latency.

## What counts as success

Relevant, correct information with a verifiable citation counts even when it
comes from another document. Accepted alternatives for one fact use `any_of`.
All distinct facts needed for a multi-part question must be present. A source
from an incompatible version is not automatically acceptable. Merely matching
a keyword, finding the right filename, or returning a partial negated statement
is insufficient.

`evaluate --answer-evidence FILE` optionally loads a separate JSONL annotation
bank with `AnswerEvidence` records. Each record binds the exact question SHA-256,
collection, scoped facts, accepted source locations/hashes, and review status.
Each fact has one or more accepted source quotes. The metric
`answer_evidence_support_at_k` requires **100% coverage of every fact** in the
returned top-k chunks; `answer_fact_coverage` reports partial coverage separately.
The original document/MRR/context-window diagnostics remain unchanged.

These are verified support measurements. An unlisted paraphrase is **unjudged**,
not proof of a wrong answer. Equally, automatic verbatim expansion cannot prove
that a quote is semantically appropriate or current. Semantic alternatives and
version restrictions require independent review. Even reviewed retrieval support
does not measure a downstream agent's generated-answer truthfulness.

## Current annotation repair

The frozen original 3,005-case bank is unchanged. During RFC development, source
inspection found that several broad 1,300-character context labels miss the
answer-bearing passage (including ICMP type numbers and IPsec SA direction).
This invalidates interpreting their span-coverage percentage as answer accuracy.
It does not explain away genuine retrieval misses.

A separate local RFC **development-only** bank covers all 80 questions with 42
required fact definitions and 60 source spans after exact-verbatim expansion.
Source and question hashes are checked before retrieval. Original context labels,
original benchmark execution, and held-out questions remain intact. The new bank
is still **AI draft, independent review pending, strict eligibility zero**. No
quality threshold is approved by this repair.

`prepare_answer_evidence.py` takes operator-authored, question-bank-bound seeds.
It validates primary quotes against original plain-text files, optionally adds
verbatim alternatives, and writes a separate draft annotation file and hash audit.
It does not consume retrieval outputs, train a model, change questions, or rewrite
original labels. Local questions/quotes are excluded from Git.

## Implemented quality components

- `build --chunk-strategy sections` coalesces neighboring prose within the same
  section and physical page before bounded character chunking. Code and source
  line gaps stay separate. This avoids tiny HTML paragraph-only chunks. New
  builds record `section-chars-v2`; the default `blocks` strategy and its original
  chunk identity remain supported.
- `build --token-aware` additionally fits every chunk to the verified embedding
  tokenizer's actual token budget, including prefix/special tokens. This permits
  larger semantic sections without failed embeddings or dropped tails. Source
  intervals/lines and character overlap remain intact. The tokenizer hash,
  library version, prefix and limit bind the pipeline identity; old chunk IDs
  are unchanged when this option is disabled. It requires a balanced model.
- `build --reranker DIR --rerank-candidates 100` packages a prepared local ONNX
  cross-encoder. The explicit provisioning script downloads the pinned
  `cross-encoder/ms-marco-MiniLM-L6-v2` revision
  `233902d25c440f23af6f7d6e94d2946bac0bee0a`, approximately 24 MB, Apache-2.0.
  This is an English model; other-language quality has not been established.
- `enhance BASE --output NEW --reranker DIR` creates a fully verified new bundle
  version, copying the existing index/model bytes without re-embedding. It checks
  the original and new inventories, keeps source IDs/citations, and never changes
  the original version. Aggregate storage checks are available with `--storage-root`.
- Dense/hybrid queries on a configured bundle rerank by default. Raw BM25 remains
  a model-free baseline. `use --rerank` explicitly enables reranking even for
  BM25; `--no-rerank` disables it. The same optional `rerank` request field is
  available in MCP and REST. A request to rerank a bundle lacking a model fails.
- Candidate pools are explicit, 50â€“200 per branch, at most 400 hybrid candidates.
  Both candidate branches apply collection/document permissions **before**
  reranking. The reranker checks that scope again. Output top-k and character
  budgets are unchanged; returned text is original indexed text, not model output.
- Cross-encoder scores are logits, not probabilities. Pair inference is CPU-only,
  telemetry disabled, batches of eight, no model hub calls. Only the passage input
  to the reranker is truncated at the recorded token budget; the query is retained
  or rejected if too long. The returned source text is never silently truncated.
  Embedding generation retains its existing strict no-truncation behavior.
- `--max-chunks-per-document` is an explicit optional diversity cap. It is not the
  default: early RFC development showed that diversity can improve document
  recall while reducing evidence coverage.

Reranker inference needs the existing `balanced` dependencies. Explicitly adding
one to a lexical-only bundle does not add dense indexing; raw BM25 still does not
load the model. The model package and its license are inventoried separately from
the embedding model. RAGForge's own license remains undecided.

## Reproducible comparison and promotion

`scripts/run_quality_comparison.py` compares raw and reranked real-engine queries
on the **same** bundle, labels, top-k=10 and 16,000-character budget. It freezes
runtime/driver/network guard hashes, records dependencies, checks question/fact
hashes, checkpoints each query and rejects changed recipes/runtime on resume.
It supports development/tuning splits; it does not run or tune on final-test cases.
Detailed outputs stay local; `safe-summary.json` contains numerical aggregates
and hashes. No questions, quotes or retrieved text are exported in that report.

A full RFC candidate with 1,000-character chunks / 150 overlap was built over all
9,854 sources. Its paired comparison is a development experiment, not a final
quality claim. The earlier 350-character lexical probe measured document recall
0.48125 raw / 0.5375 reranked / 0.55 with a two-chunk diversity cap, over 80 questions;
these are RFC development figures, not improvements over the separate kernel test.
That probe timed all variants together, so its per-method latency fields are not
valid independent latency measurements and are not used for comparisons.

Select changes on development/tuning evidence, then use a locked test once for
confirmation. Never select a threshold, chunking/model, or alternative citation
because it makes a held-out failed question pass. Promotion needs independent
annotation review, no-error execution, sufficient evidence coverage and an explicit
quality decision. A green software CI or a repaired label file does not meet 95%.

Model documentation:
[upstream model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2),
[Sentence Transformers cross-encoder usage](https://sbert.net/docs/cross_encoder/usage/usage.html).


## Completed matched development measurement

[Safe numerical report](benchmarks/rfc-quality-dev-v1.json), all 80 RFC dev questions,
all 9,854 documents, identical fact annotations, top-k=10 and 16,000-char output cap:

| Pipeline | Complete accepted fact support | Doc Recall@5 | Mean fact coverage |
|---|---:|---:|---:|
| Original 350-char chunks, BM25 | 20.00% (16/80) | 48.125% | 29.99% |
| 1,000-char chunks, BM25 | 36.25% (29/80) | 46.25% | 41.20% |
| 1,000-char chunks, BM25 + reranker | 45.00% (36/80) | 60.00% | 53.42% |

All calls completed without errors. Larger chunks use more of the same allowed
context budget; this is part of the pipeline change, not an isolated ranking gain.
The paired same-chunk reranker comparison is 29/80 to 36/80. These are measured
improvements, **well below the user's target**, with draft labels and unjudged
paraphrases. They are not a comparison against kernel's separate dense 75% result.
No test-set tuning, promotion, quality approval or generated-answer accuracy is
claimed. Full balanced RFC comparisons remain queued behind its original build.


A second queued follow-up can rebuild the complete balanced collection with
`--rebuild --model MODEL --ingest-job SNAPSHOT`: 1,000-char section chunks,
150-char overlap, actual model token fitting, sharded ANN and the same local
reranker. It waits for original baseline publication, freezes its own source,
checks model/cache hashes, preserves all source records, resumes embeddings and
compares all three methods on the same dev fact bank. CPU threads=2, aggregate
benchmark storage cap=60 GB, free-space reserve=15 GB. This is an overnight local
experiment, not an adopted default or a claimed >=95% result.


## Semantic audit of actual returned development context

The [complete review aggregate](benchmarks/rfc-semantic-review-dev-v1.json)
assesses all 80 RFC development responses from the existing 1,000-character
BM25-plus-reranker run: 67 have complete relevant information and 13 lack at
least one required fact. Of these cases, 36 have mechanically verified complete
reference quotations; 44 were additionally assessed by the development AI using
quotes from the actual returned passages. No human or independent review is
claimed. This 83.75% judgment is an evaluation audit, **not a retrieval gain** over
the same run's 36/80 literal-quotation score, and does not meet the user's target.

`scripts/review_retrieval.py export` requires a complete selected split, verifies
the artifact and frozen question/fact hashes, reconstructs original returned
chunks and validates citation metadata and output limits. Reviewer packets omit
method, scores and rank. `summarize` requires unchanged packet receipts and exact
returned-text proof, assesses every required fact and keeps all cases in the
denominator even when reviews are pending. Wrong protocol/version scope cannot
be marked supported; source quotes alone do not automate the semantic judgment.
All question text, reference facts and proof ledgers remain local. Automatic
quality approval is always false.

`scripts/audit_candidate_recall.py` separately measures a diagnostic ceiling over
up to 400 real candidates and their neighbors. Those pools can contain thousands
of chunks and exceed the output budget; their coverage is **not** retrieval or
answer accuracy. It never supplies reference labels to the ranking algorithm.

## Optional parent-context bundle experiment

`ragforge recontextualize DENSE_BASE CONTEXT_BASE --output NEW` creates a new
balanced bundle using the small-chunk base's existing vectors/query model and the
larger context base's SQLite text. Both verified bases must have identical source
paths, document IDs and source hashes. The original artifacts remain intact.
The new bundle inventories its own copied child SQLite, dense index, query model,
parent SQLite and optional reranker. No source files or original bundle paths are
needed after relocation. `--storage-root` enables aggregate storage checks.

The shared engine ranks at most 200 actual child candidates, maps them to parent
chunks using matching document/page/available line provenance **and actual text
overlap**, and fuses parent BM25 and mapped dense ranks before local reranking.
Each child maps to at most three real windows; duplicate parents retain the best
child score. Returned text and citations are always original parent index rows,
not concatenated or invented context. Document grants apply before dense ranking
and are checked again during mapping/reranking. Raw BM25 remains model-free.
Mapping caches at most eight documents and eight million source characters;
individual context documents above 20,000 chunks or two million characters are
explicitly refused. Existing unmapped bundle identities are preserved.

This is an optional development candidate. A full RFC paired-budget experiment
is running with top-k=10, a 16,000-character cap, two CPU threads, the same dev
questions/facts and no network access. The evidence ceiling, early successes and
software tests do not establish >=95% or justify changing default quality claims.


### Completed parent control and source topic metadata

The [complete parent-context review](benchmarks/rfc-parent-review-dev-v1.json)
found 67/80 fully supported development responses, exactly the same as the prior
lexical reranked control: two cases improved and two regressed. Complete literal
reference support was 35/80. Parent mapping therefore remains optional; it has
not demonstrated a net semantic quality gain and has not replaced defaults.
Prototype timings exclude replayed query embedding/ANN work and are not reported
as end-to-end latency. All 80 contexts were assessed, with no independent review.

The next isolated candidate adds source topic metadata to reranking. Optional
`DocumentRecord.title` values change the manifest identity and are checked
against the first 8,192 characters / 16 chunks of indexed source lead text or an
actual indexed heading. They do not replace returned source text or citations.
Absent titles preserve old v1 build identities. `recontextualize --document-titles
TITLES.json` accepts source-path/hash/title records; duplicate paths, stale source
hashes and invented titles are rejected, including at bundle verification.
Titles are embedded in the new manifest, so no external catalogue is needed at
runtime. The same BundleEngine supplies the prefix for CLI, MCP and HTTP.

`scripts/prepare_rfc_titles.py ARTIFACT CATALOGUE.xml TITLES.json` is an explicit
offline preparation step, independent of questions/retrieval results. The frozen
RFC catalogue yielded 9,583 source-verified titles over 9,854 documents; missing
or unmatched titles remain absent. A two-question development probe recovered a
previously missing DoH-method fact when the topic title was present; this small
probe does not establish an overall improvement. The full 80-question comparison
uses the same source bundles, candidate widths and top-10 / 16,000-character cap,
with source/runtime hashes and per-candidate score checkpoints.

Additional rejected/experimental probes remain local. A literal focus branch
uses only explicit uncommon technical names from the query; the shared default
engine does not call it. It is not an answer lookup or a claimed quality gain.
The optional pinned BGE-base ONNX candidate is prepared only through explicit
`prepare_reranker.py OUTPUT --model bge-base`; default provisioning stays MiniLM.
Its 279,252,659-byte graph is SHA-256 verified, source/model-card/license metadata
are retained, and inference uses batches of one. The explicit graph download
allowance is bounded at 384 MiB; ordinary embedding downloads retain 256 MiB.
A failed owned download is removed without overwriting or deleting existing files.
Neither the larger model nor broader candidates improved the initial matched
probe without topic metadata. No model switch or >=95% claim has been made.

Model sources: [BGE upstream model card](https://huggingface.co/BAAI/bge-reranker-base),
[pinned ONNX conversion](https://huggingface.co/onnx-community/bge-reranker-base-ONNX/tree/f131ae72114cb18333648a2ee6b0942849e8ab95).


## Completed topic and context-budget development comparison

The [numeric-only checkpoint](benchmarks/rfc-context-budget-dev-v1.json) records
all 80 reviewed RFC development responses. Source titles with the same top-10 /
16,000-character cap provide complete relevant facts for **70/80 (87.5%)**. This
is five improvements and two regressions versus the previous 67/80 parent
control. Complete literal reference support is 41/80; 38 cases were mechanically
seeded and 42 were assessed by the development AI with actual source quotes.
No independent or human review is claimed.

A separate **top-50 / 48,000-character** output profile provides complete relevant
facts for **79/80 (98.75%)** in the development replay: 53 mechanical reference
matches and 27 AI reviews, nine improvements and no regressions versus the
top-10 title control. Actual responses contain 49-50 passages and average
47,423 characters versus 9,666 characters in the top-10 control. This is about
five times the returned text. It is a larger context budget, **not** a top-10
ranking gain, independent >=95% confirmation, or generated-answer accuracy.
All original questions/facts remain frozen; actual quoted equivalent sources
count, and wrong protocol/version scopes do not. Prototype query-embedding/ANN
and score replay exclude end-to-end latency.

At the original 16,000-character ceiling, allowing up to 20 passages produces
46/80 complete literal matches and a conservative 72/80 reused-proof coverage
lower bound. New semantic judgments are still needed for this diagnostic; it is
not reported as a new accuracy result. Diversity and first-stage score mixtures
did not establish a benefit and remain outside the shared engine.

A source-title portable balanced bundle and a frozen full actual-engine run
are now being prepared locally. The actual run performs query embeddings, ANN,
parent mapping, BM25 and reranking through BundleEngine for all 80 questions;
its wider profile is explicit. Artifact verification, adapter parity and actual
returned-source reviews are required before adopting that candidate. No default
profile or global quality claim has changed.

### Optional source-proven acronym experiment

`prepare_rfc_aliases.py ARTIFACT CATALOGUE.xml OUTPUT.json` mines explicit
parenthesized initialisms from local catalogue abstracts, requires at least
three distinct source documents, and verifies each exact definition in indexed
source lead text with source hashes. This question-independent step yielded
306 definitions. `recontextualize --query-aliases OUTPUT.json` embeds the
verified optional bank in an inventoried, portable component. Missing/stale
proofs, duplicate names and mismatching initials are refused.

Only uppercase query terms are eligible for expansion: ordinary words such as
'in' and 'as' must not be interpreted as IN and AS. At most three names are
appended, preserving the original words and query/token budgets. Document
grants must include a verified definition source before its expansion is fed
to inference. Raw BM25 and --no-rerank preserve the original query; dense
embedding also keeps the original query.

Replacing lexical and reranker query text with these expansions did not improve
the matched complete set: **69/80**, versus 70/80 with source titles alone, with
two improvements and three regressions. It therefore remains optional, is not
embedded in the selected title candidate and is not an adopted retrieval
setting. Correct acronym definitions can still shift ranking toward general
introductions and displace a precise fact. The case guard fixes a separate
implementation bug; it does not establish a quality gain.


### Actual portable engine and first frozen test (2026-11-04)

The complete actual portable-engine development measurement is now finished:
80 calls, zero errors, 53 literal complete cases and 79/80 source-quoted complete
relevant fact judgments (53 mechanical, 27 AI, zero human). This confirms the
wide-context development replay through actual query embedding, ANN, parent
mapping, BM25 and reranking; it does not confirm quality on unseen questions.
[Numeric actual development results](benchmarks/rfc-actual-packaged-dev-v1.json).

The first frozen 24-question RFC test completed without errors but supports
complete relevant facts in only 21/24 (87.5%): 15 mechanical matches and nine AI
reviews, of which three are incomplete. This misses the >=95% target. The
profile was locked before test annotation; its original labels and result are
preserved. After failure inspection, this split is consumed diagnostic data
for subsequent changes and cannot be reused as untouched confirmation.
[Numeric frozen test results](benchmarks/rfc-first-frozen-test-v1.json).

A local dev-only experiment now supplements the original query with bounded
syntactic question facets, explicit inventory-matched file identifiers and
optional candidate-only source-proven aliases. It preserves the original main
query and original reranker text, limits the aggregate to 400 scored pairs, and
compares both existing output budgets. All 80 development cases and controls
are retained. No adoption or improvement is claimed while it is running. The
kernel context preparation uses source documents alone; its individual test
questions remain unopened until the next candidate is selected and frozen.


### Supplemental candidate planning (optional facets-v1)

`recontextualize ... --plan-queries` embeds a versioned hybrid-only planning
configuration in a new verified bundle. It requires the local reranker and
100 candidates per method. Existing bundle identities and defaults are
preserved. Raw BM25 and explicit `--no-rerank` bypass this mode.

The original query supplies 100 lexical and 100 mapped dense candidates and
remains the main reranker query. Optional source-proven uppercase aliases add
at most 50 new lexical candidates; their expansions do not replace the
reranker text. Up to four explicit file stems/letter-number identifiers add
eight scoped lexical candidates each. At most three English syntactic facets
reuse words from the query, preserve distinct named subjects, and inherit a
shared explicit name only when needed. Long or unmatched questions retain the
original branch. No answer labels, query lookup bank, external LLM or network
participates in planning.

Each facet uses 32 lexical candidates and 64 dense children mapped to 32
parents. Aggregate reranker inference is capped at 400 pairs across every
branch, including repeated passages scored for different facets. The final
merge uses the best reciprocal rank of each passage across the separately
reranked branches (k=60, deterministic chunk-ID ties). These scores express
relative rank, not answer confidence. Request character limits and per-document
limits apply to the final returned context. Grants scope aliases, reference
routing, lexical/dense candidates and text before inference; text loading
checks the grant again.

The complete 80-question development comparison retains the original wide
output budget. Source-quoted support is 79/80 for the title control, 80/80 for
candidate-only aliases, 79/80 for facets/references, and 80/80 for their
combination. Literal complete cases are 53, 54, 54 and 55 respectively. The
combined result has 55 mechanical cases and 25 AI-reviewed cases, zero human
reviews. Two new equivalent DNS-source proofs were explicitly assessed;
changed context was not automatically marked incomplete when an earlier
quote disappeared. [Numeric planning comparison](benchmarks/rfc-supplemental-planning-dev-v1.json).

This experiment reuses verified identical main candidate scores and performs
actual inference for supplemental branches. Full packaged calls are being
measured separately. At top-10, literal counts are 41, 41, 43 and 43; new
semantic cases remain pending and no smaller-budget gain is claimed. The
combined wide profile and source runtime are frozen before kernel test
inspection. Kernel titles and 68 multi-source acronym definitions use source
text alone, with no question or answer inputs. The original first RFC test
result remains 21/24 and is not erased by these development results.


2026-11-04 frozen kernel result: all 120 actual packaged queries completed with
zero retrieval errors. Source-quoted review supports 112/120 complete minimal
fact sets (93.3333%): 93 mechanical matches and 27 AI-reviewed cases, zero
human reviews. Eight cases remain incomplete; the 95% target is not met.
The original first result is preserved in benchmarks/kernel-first-frozen-test-v1.json.
Kernel questions are now consumed; future improvements on this set are diagnostic
regressions, not a fresh independent test. All 80 actual RFC dev calls have
also completed and their source-proof review is being finalized.


Optional section-start-v1 context completion (2026-11-04): structured short
sections of at most four chunks can supply their first chunk and physical
successor. The first 20 hits and each section's sole returned representative
are protected. At most eight lower-ranked same-document exchanges preserve
the output count, document counts, exact source text/citations and character
budget. Document grants apply before metadata/body access. Metadata reads are
bounded to 20,000 rows / 2,000,000 characters per document; no extra neural calls.
Raw and --no-rerank retrieval keep their behavior. Use recontextualize
--complete-sections to opt in; absent configuration preserves old build IDs.

The selected production algorithm exactly matches deterministic replay of all
120 consumed kernel results and leaves all 80 actual RFC dev contexts unchanged.
Source proofs establish at least 114/120 kernel cases (95%); all previous 112
complete cases retain their proofs, and two additional full frozen fact spans
are covered. Six cases remain unconfirmed. This is development diagnostic
selection, not a fresh unseen test or independent human approval. See numeric
benchmarks/section-context-diagnostic-v1.json. Actual new-bundle adapter probes
and complete required checks are pending.


To opt in when composing already-built source-identical child/context bundles:

```powershell
.\scripts\dev.ps1 run ragforge recontextualize kb/child kb/parent --output kb/planned-sections-v1 --plan-queries --complete-sections
.\scripts\dev.ps1 run ragforge use kb/planned-sections-v1 --query "Your question" --search-method hybrid --top-k 50 --max-output-chars 48000 --threads 2
```

Both base bundles must already exist and the selected reranker must be included.
Use a new output directory. Titles/aliases remain separate source-verified optional
inputs. The measured 50/48,000 profile returns much more text than the default
five results; its quality measurements cannot be assigned to the smaller default.
No generated-agent answer accuracy or cross-domain 95% guarantee is implied.


2026-11-04 completed section-runtime validation: all 16 actual queries on the
previously selection-unused RFC tuning split contain all frozen requested facts;
zero retrieval errors. Nine are mechanical full-span matches and seven are
source-quoted AI semantic reviews, including correct alternative DNS/HTTP
sources. There are eight question families and no independent human reviews.
The original split remains tuning; earlier raw-baseline split execution is
explicitly disclosed. Runtime and minimal fact bank were frozen before outputs;
no settings or expected facts changed during this run. The observed 16/16 is
not a cross-domain 99% guarantee or independent release approval.
Numeric report: benchmarks/rfc-section-first-unused-tuning-validation-v1.json.

The code commit cfcdcc5 passed all six Windows/Linux CI jobs, including pinned
pretrained models and Linux OS network isolation:
https://github.com/NemanjaZelic/RAGForge/actions/runs/41825162622.
Local full checks: 307 passed, four platform skips, no warnings, lint/format,
53-file type check and schema drift all pass. Engine/CLI/actual stdio MCP parity
also passes. The first frozen kernel 112/120 and RFC 21/24 results stay unchanged;
subsequent consumed-set diagnostics are kernel >=114/120 and RFC 23/24.
Independent quality annotation, agent-generated answers and PDF quality remain
open; neither development diagnostics nor the 16-case validation close them.


2026-11-04 version-two checkpoint: query-only technical source-stem routing
and additional explicit combine/compare/distinguish facets change 16 kernel
plans and one RFC plan. Fresh real model inference was performed for those
17 cases; unchanged plans use source-verified exact-context replay. No runtime
question/answer lookup or label-derived routing is introduced. The original
400-pair budget and 50/48,000 output profile remain unchanged. The observed
maximum is 314 pairs. The narrow planner supports 117/120 kernel cases; the
composed short-section boundary policy supports 118/120 (93 mechanical,
27 AI reviews including two incomplete cases). RFC remains 119/120 across all
120 consumed cases, with no lost prior support. Original frozen first results
and minimal fact banks are retained. This is diagnostic selection, not a new
independent quality confirmation; human review count remains zero.

Production helpers match the frozen selected prototypes for all 240 existing
cases. Legacy context behavior and both existing base artifact identities are
also exactly preserved. New policies are opt-in via recontextualize
--query-planning facets-v2 --section-context section-start-v2. Existing boolean
flags continue selecting version one. One bounded cross-document exchange may
complete a short section missing only its first chunk; first 20 hits, character
limit, document grants/caps and the sole section representative stay protected.
At most eight documents / 32 metadata groups / eight exchanges are considered.

All required local checks pass: 321 tests, four platform skips, no warnings,
Ruff lint/format (171 files), mypy (54 source files), schema drift and 27 focused
checks. Actual large version-two bundle/CLI/MCP probes are the next step.
Safe numeric reports: planning-and-boundary-v2-kernel-diagnostic.json,
planning-v2-rfc-diagnostic.json and production-v2-parity.json under benchmarks/.

The previous terminal-owned large corpus workers were no longer active at the
start of this continuation. A native WMI-brokered one-shot supervisor has now
been observed advancing the full RFC build from 323,584 to at least 352,256
of 662,398 chunks. It installs no service or recurring task. The maintained
scripts/start_background_benchmarks.ps1 entry point has frozen-input preview,
private aggregate publication choice, duplicate-controller protection, local
status/logs and process-scoped sleep prevention. Native preview/parser and
refusal of duplicate live controllers were checked. Current active workers
remain under the equivalent local prototype supervisor to avoid restarting
healthy runs. [Usage and limitations](BACKGROUND-BENCHMARKS.md).


Actual version-two portable checks have completed: both artifacts verify, three
large-kernel engine probes and real CLI/stdio MCP match exact ordered source
contexts and citations offline, including MCP context fetch. See
benchmarks/production-v2-artifacts.json and
benchmarks/production-v2-artifact-adapter-parity.json. Six CI jobs for d64287d
and the subsequent numeric-report checkpoint 40bdfb6 passed on Windows/Linux.

An additional source-only sampled validation of the selected version returns
complete support for 16/16 new questions (33 facts, eight new source families,
zero errors). Runtime, questions and facts were frozen before retrieval, with
no settings changed during this run. All exact source-span matches have also
received explicit AI scope/meaning inspection; human independent review is zero.
This is a small English, early-source, two-questions-per-family draft sample,
not a representative cross-domain guarantee. Exact provenance/limitations:
benchmarks/kernel-first-additional-source-validation-v1.json.

`integrate` now gives planned section bundles explicit wide-evidence search
instructions (hybrid, top_k=50, max_output_chars=48000) and a structured
recommended_search_request in the generated collection metadata. The generated
files are passive for user review; no host config is installed. Direct request
defaults remain their existing values. The measured wide-profile scores do not
apply to requests using smaller limits. See [agent integration](MCP.md).


## 2026-11-09 completed 3GPP review and source-context integration

All 3,966 scheduled baseline calls and 1,322 multilingual calls are complete,
with zero retrieval errors and no pending source reviews. On all 1,322 unchanged
questions, the frozen MM response contexts support 1,215 (91.91%). The selected
source-context policy supports 1,239 (93.72%), a paired gain of 24 with no losses.
There are 83 insufficient cases. This is retrospective source-evidence support,
not generated-answer accuracy or independent/unseen quality approval. The 95%
all-four-corpora/all-language target remains unmet.

The optional policy is implemented in the common engine. Production selection
matches the frozen prototype in all 1,322 payloads, source citations and orders;
no new neural calls were needed for that parity check. The full-corpus catalogue
was built from indexed sources only, verified, and used successfully in a real
local CLI query. Offline CLI/stdio, portable relocation and authenticated HTTP
document grants are covered by functional tests. See [commands and limits](SOURCE-CONTEXT.md)
and [numeric provenance](benchmarks/gpp-source-context-complete-v1.json).

The MM upstream model selection is experimental and distinct from the retained
L6 Kernel/RFC policies. Source-context parity preserves a consumed MM result;
it does not establish the default bundle's accuracy or a single configuration
that achieves 95% on every corpus. Historical first-frozen results stay unchanged.
