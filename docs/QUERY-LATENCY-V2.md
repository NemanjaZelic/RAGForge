# Query latency: large-corpus exact optimizations (v2)

The target remains RAG retrieval to returned sources in under 10 seconds on the
existing i7-1195G7 laptop, without changing the evidence policy. Application
startup and generated answer text are outside that target. **The target is still
open for new questions.** A repeated-query cache hit is reported separately.
No new hardware, paid service, model or dependency was added.

## What changed

ANN still searches every original shard with the same candidate count and graph
parameters. Each shard retains the original vector matrix shape and exact score
calculation. The runtime determines the global score cutoff before resolving
SQLite chunk identities, eliminating SQL reads only for strictly losing scores.
All cutoff ties survive until the original chunk-ID tie break. Up to eight
independent shards run concurrently within the requested thread budget. Filtered
search retains exhaustive authorized-vector scoring, with grants checked before
vector reads.

Parent mapping groups anchors by document and physical page. Bounded document
page ranges narrow reads through the existing ordinal index; the original page
predicate remains, including for interleaved page ordinals. Matching text probes,
line overlap, best-three selection and maximum-score merging are unchanged.
Oversized range catalogues fall back to the original SQL. The catalogue holds at
most 20,000 page ranges across 16 documents. Existing text cache and per-page
limits remain enforced; child bodies and parent cursors are streamed.

The optional in-memory reranker cache keys the **entire actual tensor batch**:
all graph input names, types, dimensions and array bytes, including query,
neighboring passages, padding and attention masks. A quantized batch cannot be
cached safely by passage text alone. The cache stores only SHA-256 keys and
score tuples, has bounded LRU eviction and shares identical in-flight work.
Failed inference is not cached; replacing a model session invalidates entries.
Every original model batch and numerical precision remains unchanged.

Explicit server warm-up loads the default model/index and exercises neutral model
inputs before accepting requests. It does not search a benchmark question. This
moves genuine initialization into startup, rather than labeling it query speed.
A minimal BM25 bundle remains independent of ML imports.

## Measured large-corpus behavior

Only **one deterministic existing 3GPP question** was selected, without using
reference answers. Three end-to-end requests used that same question: optimized
first execution, optimized repetition and legacy warmed execution with the new
neural cache disabled. No full 3GPP benchmark was run.

| Measurement | Seconds | Scope |
|---|---:|---|
| Optimized first real question after explicit startup | 27.96 | Zero neural cache hits; 191 original model pairs |
| Optimized repeated question | 7.35 | 96 batch hits, zero neural inference misses |
| Legacy warmed question, neural cache disabled | 28.93 | Same question, model and 191 pairs |

All three complete responses, including ordered IDs, scores, text and citations,
matched the original response exactly. Every model input pair and all 191 scores
also matched. This is regression evidence for one question, not a new quality
benchmark, a 95% quality certification or a p95 latency guarantee.

The first optimized execution spent 17.77 seconds in neural reranking, 3.33 in
ANN and 2.31 in parent mapping. Stage measurements are partial and must not be
summed as a complete decomposition. Verification took 140.30 seconds, reranker
construction 1.84 seconds, and explicit model/index warm-up 23.78 seconds, all
outside the request timer. The earlier 59.55-second baseline included lazy model
and ANN initialization; **59.55 to 27.96 is not an isolated algorithm speedup**.
The three-request comparison also retains cache/order effects; it does not prove
a steady-state gain for every new query.

Isolated replays of the exact same dense vector searched all 188 shards and
returned identical ordered 200 IDs and floating-point scores. Identity resolution
fell from 188 SQL queries / 37,600 rows to one query / 200 rows. Alternating warmed
legacy timings were 3.75 and 3.28 seconds; the optimized probe between them was
0.274 seconds. The initial legacy run was 9.88 seconds and the initial optimized
run 0.299 seconds, so the larger first-run ratio is not a fair warm comparison.
The complete request still has memory/cache effects and neural work absent from
this isolated microbenchmark.

On the same 200 captured child anchors, parent mapping returned the same 100
parents and scores. A warmed original replay took 0.674 seconds versus 0.283 for
grouped range reads. This subsystem replay does not predict full-query timing.

## Use

Keep one engine/server alive to reuse verified models, mapped indices and cache:

```sh
ragforge serve ./bundle --threads 8 --rerank-workers 8 --warm-up
```

The same options work for authenticated HTTP startup. The default exact cache
holds 512 batches; `--rerank-cache-batches 0` disables it and 4096 is the maximum.
`ragforge use` also accepts the cache setting, but a new CLI process has an empty
cache each time. Shared clients cannot override server-local resource settings.
Warm-up prepares the bundle's default search method, not every optional method.

## Validation and rejected changes

Tests cover complete-boundary ties exceeding one SQL batch, strict losers,
authorized-only filtered vectors, interleaved page ordinals, bounded fallback,
actual tensor-batch identity, batch-dependent scores, LRU eviction, session
invalidation, inference failure recovery and concurrent tokenizer access. CLI,
actual offline MCP and engine warm-up retain response parity.

SQLite mmap/cache tuning and a native BM25 LIMIT probe did not establish a useful
controlled improvement, so no database policy changed. Reranker thread/worker
probes on 64 captured pairs retained exact scores but did not beat the current
8/8 scheduling. Operator profiling attributes most neural time to quantized
matrix multiplication. Reducing candidates, shortening source inputs, changing
quantization or batch membership, and skipping difficult queries were not used.
Existing GPU/larger-batch alternatives that changed scores remain rejected.
A longest-batch-first scheduling probe retained all 191 scores, but alternating
original/sorted/original timings were 12.46/13.66/14.95 seconds. The increasing
times do not establish a sorting benefit; original scheduling remains unchanged.

The numerical report is [query-latency-v2.json](benchmarks/query-latency-v2.json).
Source-bearing questions, captured pairs and responses remain local and are
excluded from Git. The original project plan, models, corpora and accepted
quality measurements remain unchanged.

## Software and non-3GPP regression result

The complete local suite passes 410 tests with 17 explicit optional/platform skips.
Ruff lint/format, mypy and generated-schema drift checks pass.

Five previously captured complete responses were rerun with neural caching
disabled. All IDs, scores, text, ordering and citations remain identical.
These probes are regression samples, not a rerun of the full quality banks.

| Corpus / language | New uncached question (seconds) | Exact response |
|---|---:|---|
| kernel | 11.01 | Yes |
| rfc | 12.01 | Yes |
| t7 / en | 17.53 | Yes |
| t7 / sr-Cyrl | 25.63 | Yes |
| t7 / sr-Latn | 23.08 | Yes |
