# Explicit-reference lookup probe: not adopted

A bounded source-only probe tried following explicit clause/section references
inside retrieved paragraphs. **All 60 complete responses stayed identical;
no extra source evidence was returned. The prototype was not adopted.**
The original consumed 3GPP result remains 30/32 (93.75%), with no new absolute
full-corpus or language-wide accuracy claim.

The probe reused the same 60 real upstream results as the
[preceding acronym experiment](ACRONYM-CONTEXT-EXPERIMENT.md). No new neural
queries, full 3GPP run or source/index rebuild was needed. Questions, labels and
source files were unchanged. Every baseline reproduced its stored full response;
actual returned text, provenance and output limits were verified against the index.

Only a literal same-document reference supported by at least two question terms
was eligible, from the first sixteen primary passages. At most one target was
looked up per request, with at most 64 FTS rows. There was no recursion or remote
fetch. Primary results were preserved. An additional passage also had to fit the
existing output budget and existing same-page/section context-anchor contract.
An early private prototype rejected by that contract was corrected by checking
the existing anchor requirement before selection; no response schema was changed.

| Completed comparison | Result |
|---|---:|
| Replayed questions | 60 |
| Complete responses identical | 60/60 |
| Requests triggering a target lookup | 9 |
| Repeats per variant | 2 |
| Added source chunks | 0 |
| Median lookup cost across eligible per-case medians | 1.008 s |
| Largest eligible per-case median lookup cost | 3.709 s |

These costs time the extra source lookup stage, not a new independent end-to-end
MCP benchmark. Filesystem caching and host scheduling affect them. The completed
comparison performed 18 FTS lookups; other requests skipped the lookup.
One earlier private lookup stopped at response-contract validation; it is
additional to those 18 and has no completed timing. The experiment introduces no
shipped latency overhead because retrieval code remains unchanged.

The current response budget was often nearly full. Useful distant passages
could not simply be appended without changing the existing context contract or
displacing other evidence. Numeric clause lookups through the full-text index
also proved expensive in this sample. This rejects this particular bounded
runtime implementation, not every possible cross-reference design. A separate
prebuilt heading index was not implemented or measured.

Only this aggregate account and a documentation link enter Git. Native questions,
case identifiers, source quotes, responses and prototype scripts remain private.
This is a documentation-only checkpoint; unchanged local software tests were not
repeated. Exact-commit CI is checked separately before main updates.
