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
