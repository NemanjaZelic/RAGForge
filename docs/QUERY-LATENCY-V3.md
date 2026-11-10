# Query latency: stdio MCP follow-up

The goal remains **less than 10 seconds from an agent's RAG request to returned
source evidence**, on the current laptop, preserving retrieval quality. Startup,
explicit warmup, document acquisition/index building and agent answer generation
are measured separately. This update does not certify the target for all questions.

## Actual MCP round trips

Ten requests cover five fixed questions from already consumed Kernel, RFC and T7
sets. Both configurations use eight CPU threads, eight reranker workers, unchanged
models, candidates, context budgets and batch tensors. The neural cache is disabled.
Each complete response matches its earlier frozen response. Every reranker query,
passage, score and order matches between configurations. Source-bearing records
stay local; the [numeric report](benchmarks/query-latency-v3.json) contains aggregates.

| Selected sample | Existing scheduling | Proposed overlapping BM25/dense | Adopted? |
|---|---:|---:|---|
| Kernel, English | 7.89 s | 8.12 s | Existing |
| RFC, English | 9.53 s | 8.93 s | Existing |
| T7, English | 15.09 s | 14.57 s | Existing |
| T7, Serbian Cyrillic + supplied translation | 19.89 s | 19.25 s | Existing |
| T7, Serbian Latin + supplied translation | 21.96 s | 23.09 s | Existing |

The overlap proposal has mixed effects, consistent with contention and timing
variation on the laptop. It is **not enabled**. Kernel and RFC are below 10 seconds
for these selected requests; T7 remains above it. These are individual timing
probes, not new whole-bank accuracy scores, latency percentiles or a guarantee.

Measured MCP startup plus warmup was 11.88 s for Kernel, 53.63 s for RFC and 7.75 s
for T7. A persistent MCP server pays this separately from each question. The older
v2 probes used a different thread budget for Kernel/RFC, so their numbers are not
a controlled comparison against this update. No new 3GPP request or full 3GPP
benchmark was run. The previously measured uncached single 3GPP request remains
27.96 s; this update does not claim a fresh 3GPP result.

## Rejected extra session copies

A second diagnostic replays 64 previously captured pairs, with all original scores
unchanged. One shared session took 4.63 s initially and 4.67 s warm; four sessions
with eight total workers took 5.53 s initially and 4.54 s warm. The small warm
change is not reliable evidence of an improvement; extra model copies increase
memory. Session settings and the retrieval recipe remain unchanged.

The remaining large cost is cross-encoder inference over the full candidate plan.
Reducing candidates, changing batch padding, substituting a model/backend or
truncating evidence can change results and needs a separate quality evaluation.
None of those shortcuts is adopted here.

## Measure a few questions on your own bundle

After setup, use the prepared Python environment:

```bash
.venv/bin/python scripts/measure_query_latency.py kb/my-bundle --query "Your question" --output .cache/latency.json
```

Windows uses `.venv\Scripts\python.exe` with the same arguments. Supply the actual
bundle path printed by `build`. The tool starts a real stdio server, warms it,
then measures `search_docs` including context expansion, serialization and
transport. It explicitly disables the neural cache. Reports contain timing,
counts and response hashes, without the question or returned source text.

Repeat `--query` for up to five questions. `--query-translation` is available with
one question. `--repeats 2` or `3` checks identical complete responses; repeats
still run inference and must not be called unseen-question quality validation.
`--threads` controls the same existing CPU budget. Existing output reports and
immutable bundle contents are not overwritten. This tool never launches the full
3GPP benchmark.
