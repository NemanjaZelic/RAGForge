# Query latency

Latest: [large-corpus exact retrieval and cache optimization (v2)](QUERY-LATENCY-V2.md).
The v1 measurements below remain historical; v2 permits one individual 3GPP probe.

The current target is **under 10 seconds from a RAG request to returned sources**
in an already started process. Bundle verification, loading and warm-up are
reported separately. Text generation by the calling agent is outside this target.
A timeout or fewer evidence candidates is not a successful speed improvement.

## Identical-batch CPU execution

The reranker now executes independent original model batches concurrently on one
shared ONNX Runtime CPU session. Batch membership, order, padding, query, passage
truncation, model weights and precision are preserved. This matters because changing
batch size or sorting by length can change dynamic-quantization scores.
The caller receives scores in the original passage order even when tasks finish
out of order. Tokenization remains on the caller thread. Worker exceptions cancel
queued tasks, await active tasks and reset tokenizer truncation before returning.

`--threads` remains the total model CPU budget. `--rerank-workers` selects up to
eight concurrent batches, capped by that budget; intra-op threads per batch are
`max(1, threads // workers)`. The default is four workers, capped by `--threads`.
One worker selects reference serial scheduling. At one CPU thread, scheduling is
unchanged. No inference pool persists after a scoring call and no extra copies
of the model are loaded.

```bash
# Long-lived local MCP process; reuse it for subsequent requests.
ragforge serve ./bundle --threads 4 --rerank-workers 4
# Explicit eight-thread configuration measured on the local eight-logical-CPU host.
ragforge serve ./bundle --threads 8 --rerank-workers 8
# Reference serial scheduling with the same model and evidence policy.
ragforge use ./bundle --query 'your question' --threads 4 --rerank-workers 1
```

The same resource setting is supported by local CLI, stdio MCP and shared HTTP
server startup. Shared clients cannot select the server's local worker count.
Bundle identities and retrieval request schemas do not change. Models, candidate
counts, source text, output limits and evidence policies are unchanged.

## Measured limits

The local host has an Intel i7-1195G7 (four physical/eight logical CPUs), about
12 GB RAM and Intel Iris Xe integrated graphics. Current product inference uses
the CPU provider. A stronger CPU can address the measured bottleneck, but a
hardware name alone cannot establish the target latency. A new GPU requires a
supported and quality-validated execution path; installing hardware does not
move the current CPU sessions to it.

On three deterministically selected consumed T7 queries (English, Serbian Cyrillic
and Serbian Latin), the old two-thread serial timings were 26.88, 34.85 and
41.75 seconds. Eight-thread/eight-worker timings were 15.72, 20.44 and 23.65
seconds. All three complete ordered responses, including scores, text and source
citations, matched exactly. All 1,009 captured pair scores also matched exactly.
This is a small engineering regression sample, not a new independent quality
benchmark or a p95/max latency guarantee. Initial lazy model/ANN setup remains
in the first request of these measurements and is explicitly marked.

The first T7 query spent 24.87 of 26.88 seconds in reranking. ANN was about
0.04 seconds and BM25 about 0.08 seconds; overlapping component timings must
not be added. Faster vector lookup alone would not solve this workload.

The larger-batch alternative changed ranking and was slower, so it was rejected.
Existing isolated OpenVINO CPU/GPU probes also changed ranking; neither was
adopted. No models or dependencies were downloaded for these probes. The user
requested Kernel/RFC/T7 validation instead of another 3GPP run; no new 3GPP query
was executed during the v1 measurements. The subsequent v2 scope explicitly permits individual 3GPP probes.

**The under-10-second target is not achieved for every question.** Retain the
quality result and continue profiling the remaining neural cost. Broader latency
validation and any future GPU backend require separate measurements with the same
request scope, evidence budgets and output-quality checks. Do not claim a speedup
from shrinking the corpus or measuring repeated-query cache hits.

See the numeric report in `docs/benchmarks/query-latency-v1.json` for measured
samples and verification scope. Source-bearing query/candidate/response records
remain local and are not committed.


Two Kernel probes with the same four-thread budget improved from 14.18/8.75 s
to 10.31/6.95 s; two RFC probes improved from 25.11/18.80 s to 12.07/14.27 s.
Every serial/parallel response matched exactly, and the four source payloads also
matched their original frozen selected responses. Unlike the T7 comparison,
these comparisons hold the requested CPU thread budget fixed.

The complete local software suite passes (388 tests; 17 explicitly skipped
platform/external-data/model cases), as do lint, format, types and schema checks.
The optimized runtime still exceeds 10 seconds on six of the seven measured
queries. Further work stays on this laptop without new costs. The later v2 scope permits individual 3GPP probes while excluding a full 3GPP benchmark.

Reference: [ONNX Runtime threading](https://onnxruntime.ai/docs/performance/tune-performance/threading.html).
