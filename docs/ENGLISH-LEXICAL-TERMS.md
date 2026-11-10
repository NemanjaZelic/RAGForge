# English content terms: bounded latency improvement

Date: 2026-11-10. Baseline application `5be996a36be0306063249de39ca16588af71b9c8`.

The optional English GPU hybrid profile now removes grammatical filler from the
lexical query of a **single-facet plan**. A bounded “According to …, [question]”
preface may be removed from that lexical input. The original question remains
the dense and reranker input, including its source/version wording. Caller
collection and document grants are retained. No online translation, answer
lookup, new model or dependency is introduced.

BM25-only, CPU and default multilingual plans retain their previous behavior.
Existing compatible English GPU bundles use this runtime change after upgrading
and restarting the server; rebuilding models or indexes is unnecessary.

## Preserved meaning and regression guard

Negation, conditions and normative words such as `not`, `without`, `if`, `must`,
`shall` and `should` remain. Uppercase technical names remain even if they resemble
a grammatical word. Quoted text, code, paths and argument forms use the original
lexical query. The original sixty-four-literal-term limit is checked before any
reformulation. If fewer than two content terms remain, the original query is used.

This changes lexical candidates and is **not an exact-score BM25 optimization**.
The unmodified question is still used for embeddings and reranking; this alone
cannot guarantee equal source quality. Final candidate, model-pair, character and
source-location constraints stay enforced.

The first unrestricted prototype failed a compound RFC source check: an answer
clause's prior proof was no longer available. That prototype is not the shipped
policy. Plans split into several question facets now retain every original
literal lexical branch. A synthetic regression test protects this behavior, and
an actual final RFC MCP call reproduces the complete previously verified response,
including its source ordering and all required evidence.

## Unchanged strict source score

The same thirty-two consumed 3GPP questions were kept unchanged. The initial
candidate run made 41 actual MCP requests: thirty-two distinct questions plus
counterbalanced repetitions of three previously slow questions. All returned
source bodies, offsets and locations were verified against the physical index;
result cache capacity was zero. The strict complete-source-fact result remains
**30/32 (93.75%)**, with zero newly lost supported cases and zero pending reviews.
The previous timing and purpose proofs remain in actual returned chunks.

These thirty-two questions all produce a single-facet plan. The final compound
guard leaves their executed candidate path unchanged; the final sixteen-call
check again requires its complete candidate responses to match that source gate.
This is not a second full thirty-two-query final rerun or a new unseen test.

The two earlier insufficient cases stay in the score. One lacks an identified
work item; the other lacks a specified local policy. The native test package
records provided-context QA scope and leaves standalone full-corpus question
scope unapproved. No label, question, source requirement or denominator has been
changed to reach 95%. Optional context-assisted diagnostics would need to be
reported separately. The complete historical 1,322-case score is unchanged.

Six smaller-corpus MCP requests also checked Kernel, RFC and T7 English / Serbian
Cyrillic / Serbian Latin. Their factual checks informed the compound guard above;
the failed unrestricted RFC check is retained. The final RFC repeat verifies the
fix against the complete prior response. These bounded checks are not new full
quality scores for those corpora or languages.

## Two latency observations, both retained

The first A/B/B/A comparison (inverse order on the second question) used the same
three previously slow 3GPP questions, two calls per variant and question. Software
checks completed before timed requests began.

| Actual MCP round trip, first comparison | Baseline | Content terms |
|---|---:|---:|
| Calls | 6 | 6 |
| Median | 11.76 s | 4.86 s |
| Maximum | 16.94 s | 7.18 s |
| Below 10 s | 0/6 | 6/6 |

Across all 35 candidate calls in that first run, 34/35 were below ten seconds;
median 6.77 s, maximum 10.24 s. The broader observation therefore still
includes a missed latency target.

A later final comparison used those three questions plus the slowest updated
case, in a counterbalanced sixteen-call sequence. Its candidate responses all
matched the prior source-quality gate. This repeat was substantially slower:

| Actual MCP round trip, later comparison | Baseline | Content terms |
|---|---:|---:|
| Calls | 8 | 8 |
| Median | 25.83 s | 16.09 s |
| Maximum | 30.98 s | 19.33 s |
| Below 10 s | 0/8 | 1/8 |

During that later run, an OS snapshot reported only 333 MiB available physical
RAM out of 11,931 MiB, with 1,568 MiB virtual-memory headroom. This is evidence of
memory pressure, not an isolated causal attribution of all delay. No user
application was closed or reconfigured. Startup was measured separately:
450.4 seconds in the later large-bundle process. Every timed request waited
for local software checks to finish; no other benchmark worker ran concurrently.

Both variants slowed in the later observation. The optimization remains faster
in aggregate, but **a stable sub-ten-second guarantee is not established**.
The favorable earlier run is not substituted for the slower repeat. Repeated
questions can share OS page-cache and compiled GPU-kernel state even with neural
result caches disabled. No universal or p95 guarantee is claimed.

## Checks

Final local checks: **527 tests passed, 19 explicit skips**, Ruff lint and
formatting, strict types and schema drift. Tests cover literal/code preservation,
negation and normative words, grants, original input limits, caller immutability
and compound-plan protection. Packaging is checked separately. Raw questions,
source quotations, full responses, model assets and per-case proof packets remain
outside Git. No complete 3GPP neural evaluation was rerun.
