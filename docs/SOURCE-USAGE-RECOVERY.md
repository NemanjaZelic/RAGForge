# Source-use question recovery

Date: 2026-11-10. Baseline application commit:
`02f83ca71e5d6039761417b59c93f3ee4ee6f2e8`.

The optional source-definition catalogue now recognizes short technical-use
questions such as the fictional `What is ZQP used for?`, `What does ZQP do?`
and `What is the purpose of ZQP?`. Previously these forms skipped the existing
multi-meaning definitions. The change restores the previously lost technical
usage-list case in the faster English 3GPP profile.

No domain acronym, reference answer, case ID or benchmark-specific document is
encoded in the retrieval rule. Definitions remain literal source candidates;
multiple meanings are retained rather than guessing the user's intended one.

## Fixed subset evidence

| Consumed subset | Previous English GPU profile | Updated profile | New lost supported cases |
|---|---:|---:|---:|
| Previous 16-case development check | 14/16 | 15/16 | 0 |
| Additional 16-case validation check | 14/16 | 14/16 | 0 |

The development result is 93.75% and recovers the same 15 cases that the earlier
multilingual source-context profile supported on that subset. The additional
subset was fixed by query metadata/hash before implementation: eight technical
usage-intent questions, six other native questions and two explicit-version
questions, excluding the previous sixteen and repeated single latency question.
It was held aside for this change, but belongs to an already consumed benchmark;
it is not an independent unseen-quality certificate.

Required information is assessed in actual returned sources, accepting complete
equivalent information from correct sources. This is not generated-answer
accuracy. All 32 questions used fresh upstream neural query plans with result
cache capacity zero. The same upstream result was then given to the baseline
and updated postprocessors. This isolates the changed selection logic without
repeating the expensive model for each variant. Every resulting source entry,
provenance location and excerpt was checked against the physical index. Both
paths kept the 48,000-character budget, at most 50 ranked results and 32 context
entries. Questions, requirements, answers, indexes and model files were not
changed.

Previously reviewed full-question proofs were retained only when present in the
actual response, respecting explicit version scope. The baseline development
responses reproduced the earlier verified check. Two remaining validation cases
needed explicit AI reading: their old and new responses were identical and
insufficient for the complete question. Both failures remain in the score.
All review bindings were validated; no independent human approval is claimed.
The ambiguous development failure also remains. These subsets do not establish
95% accuracy across the whole 3GPP corpus.

## Cost and unchanged limits

The change adds **zero embedding or reranker query plans**. It does not increase
candidate counts, model size, reranker batch size or evidence budgets. It uses
existing source-index reads rather than an additional neural pass.

Exact authorized catalogue matches now avoid enumerating every short form.
Plural and one-edit fallback retain their previous behavior. Once all duplicate
replacement slots are filled, focused searches and neighbor reads that could
no longer affect the result are skipped.

Across 32 cases, three paired postprocessor comparisons per case used a
counterbalanced order. The median per-case processing-time change was
**+1.94 ms**; the mean was **+2.50 ms**. Individual measurements varied from
-110 to +115 ms. This is a small measured cost, not proof of zero overhead under
every load. Startup was separate and no question-specific result cache was
enabled.

A separate actual stdio MCP check used three fixed questions in A/B/B/A order
(with the inverse order for the second question), two calls per variant per
question. All twelve complete responses matched their paired quality-check
responses, including the recovered case. The pooled round-trip median was
**8.25 s before / 6.38 s after**, with **5/6 below ten seconds in each variant**.
This small observation includes first-question/kernel/page-cache effects; the
entire difference cannot be attributed to a millisecond postprocessor change.
The slowest updated call was 11.49 s, so a universal ten-second limit remains
unproven.

Six further actual MCP regression requests over Kernel, RFC and T7
English/Serbian returned exactly the complete responses of the previous
verified version. Those selected bundles do not use the optional catalogue;
their source-selection path is unchanged. No full 1,322-case 3GPP neural
benchmark was run.

## Product scope and checks

This improvement applies when a verified [source-context catalogue](SOURCE-CONTEXT.md)
is configured. Existing compatible catalogues can be reused without model or
index rebuilds. Plain bundles without a catalogue retain their current behavior.
There is no additional online step during local retrieval.

Local validation: **505 passed, 19 skipped**, lint, formatting, strict types and
schema drift all passed. Synthetic tests cover multiple acronym meanings,
document grants before source reads, bounded replacements, exact lookup and
unchanged plural/typo fallback. Source/wheel packaging checks exclude generated
local data. Raw questions, sources, proof quotations, models and complete
responses remain outside Git.
