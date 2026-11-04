# Retrieval quality and answer-bearing evidence

The user target is at least **95%**, with **99%** considered excellent. Neither
threshold has been demonstrated. Document Recall@5 is a component diagnostic;
it is not answer accuracy. RAGForge returns sources, not generated answers.

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
- Candidate pools are explicit, 50–200 per branch, at most 400 hybrid candidates.
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
