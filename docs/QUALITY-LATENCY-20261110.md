# Quality and latency checkpoint: bounded GPU overlap

Date: 2026-11-10. Baseline application: `c6ea00fbb060a59a66acdc3b9016b29886c489ef`.

The requested joint target is **not yet achieved**. A fixed consumed 3GPP subset
improved from **29/32 to 30/32 (93.75%)**, without a newly lost supported case.
A separate counterbalanced MCP measurement reduced the median round trip from
**10.37 s to 8.80 s**. Five of six updated calls were below ten seconds; the
slowest was **10.90 s**. These are bounded development observations, not a new
full-bank, independent unseen or generated-answer accuracy score.

## Implemented changes

For English hybrid plans using the optional Intel GPU and lexical prefetch,
reranking the known dense candidates now overlaps the unfinished lexical search.
The primary union contains at most 100 dense and 100 lexical candidates, so all
dense candidates survive the 200-item fusion limit. After lexical search returns,
only candidate IDs not already scored are passed to the model. No candidate is
scored twice, no search branch is removed and the total 400-pair cap stays intact.
Question facets, aliases, document grants, source verification, the 50 primary /
32 context entry limits and 48,000-character request budget remain enforced.
CPU, BM25-only and default multilingual execution retain their previous plan.

This changes GPU batch membership/padding. Individual logits and source ordering
can differ, so it is **not** a bit-for-bit numerical optimization. It requires
source-information regression checks even though the model, precision, complete
passages, query and candidate union are unchanged.

The optional source-context catalogue also improves longer questions about
purpose, role or function. One bounded lexical branch keeps the leading subject
terms and a single explicit technical actor while relaxing later wording. Within
the existing 64-row branch budget, source sentences explaining what something
allows/enables receive priority for these questions. The same maximum three FTS
branches, six focused candidates and sixteen duplicate replacements apply.
Unique primary information, document scope and output limits remain protected.
There are no benchmark acronyms, answers, case IDs or document mappings in the
product rule. The previously missing explanation is now present in the actual
returned paragraph; no question or requirement was rewritten.

## Frozen subset source evidence

| Consumed subset | Baseline | Updated | Newly lost supported cases |
|---|---:|---:|---:|
| Previous development 16 | 15/16 | 15/16 | 0 |
| Additional validation 16 | 14/16 | 15/16 | 0 |
| Combined diagnostic | 29/32 | 30/32 | 0 |

The same thirty-two questions and requirements from the prior recovery check
were locked before this change. They belong to an already consumed bank and
cannot serve as a new unseen certificate. An actual stdio MCP run made 41
requests: the thirty-two distinct questions plus counterbalanced baseline /
candidate repetitions on three previously slow questions. Six baseline calls
reproduced the complete prior responses, and repeated candidate responses were
deterministic. Every returned excerpt and location was checked against the
physical index; result cache capacity was zero.

Previously reviewed complete source proofs were carried forward only when
present in the actual response, with explicit version scope retained. Two
changed cases needed AI reading with proof quotes bound to their actual returned
chunks: equivalent complete timing information was retained, and the previously
missing purpose explanation was recovered. Thirty cases are supported and two
remain insufficient, with zero pending reviews and no independent human approval.
One remaining question refers to unspecified work; another asks for a configured
policy value that the retrieved text only uses as an input. Both failures stay
in the score. They have not been reworded, removed or counted as correct abstentions.
The historical complete 1,322-case multilingual result is unchanged; it was not
rerun or replaced by this subset.

Six actual MCP regression requests over Kernel, RFC and T7 English / Serbian
Cyrillic / Serbian Latin retained exactly the full previously verified evidence
sets. Some source ordering changed; there were no missing previous evidence
pieces in those six checks. These small checks do not establish a new full-bank
score for the three corpora.

## Latency evidence and limits

Profiling three previously slow 3GPP questions found approximately 7.8 seconds in
lexical search and 3.5 seconds in reranking, with some work already concurrent.
A separate twelve-call A/B/B/A check (inverse order on the second question) used
those three fixed questions, two calls per variant and question. No other test
or inference worker was active during its measured requests. Earlier software
checks and the smaller-corpus requests finished before its first timed call.

| Actual MCP round trip | Baseline | Updated |
|---|---:|---:|
| Calls | 6 | 6 |
| Median | 10.37 s | 8.80 s |
| Mean | 10.70 s | 9.01 s |
| Maximum | 13.95 s | 10.90 s |
| Below 10 s | 3/6 | 5/6 |

All twelve complete responses matched their corresponding quality-check
responses. Query-result cache hits were zero. Startup was separate, approximately
276 seconds for this large verified bundle. Neutral startup work uses no user
question. Repeated questions still share OS page-cache and compiled GPU-kernel
state; counterbalancing reduces but cannot eliminate those effects. The earlier
41-call quality run partly overlapped software checks and is not used as the
controlled causal latency comparison. That broader run also contained calls
above ten seconds. There is no universal latency guarantee, p95 guarantee or
claim that every query now meets the target.

SQLite mmap sizes of 256 MiB, 1 GiB and 2 GiB preserved exact lexical ranks but
showed only a small local gain. A separate BLAS scheduling experiment preserved
ANN / lexical ranks but had inconsistent wall-time results. Neither experiment
was adopted: no global BLAS setting or extra dependency was introduced.

## Software checks

Local checks passed: **509 tests, 19 explicit skips**, Ruff lint and formatting,
strict type checking and schema drift. Synchronization tests require dense
reranking to begin while lexical search is blocked, verify exactly-once scoring
of the complete fused union and preserve document grants. Synthetic source tests
cover purpose recovery and unchanged unique-information / budget protections.
Source and wheel packaging are checked separately. No raw questions, source
quotations, complete responses, model files or local proof packets are published.
