# Compound definition source recovery

A source-only change recovers one demonstrated missed definition of a compound
technical term. It adds no neural pass, model or dependency. It keeps the
unchanged consumed 3GPP subset at **30/32 (93.75%)**, with zero new losses;
**95% across all complete collections/languages is still unconfirmed**.

## Behavior

Dense/reranked results can be dominated by conformance tables repeating a term
without explaining it. When the bounded focused search has two branches and the
question is a short unqualified `What is/are ...?` definition, keep its original
literal branch and look for an explicit parenthetical label of the entire
compound term. Use only literal words from the original question.

If that source label is found, use it instead of the broad fallback. If the
probe is empty, restore the original fallback. The maximum is still three SQL
statements, 64 rows per statement, six focused candidates and 16 duplicate-slot
replacements. Already-saturated three-branch plans stay unchanged. Qualified,
versioned, quoted and multi-part questions keep their previous behavior.

The match predicate handles ordinary source line wrapping and spacing. Returned
source text is verbatim, with its original provenance. Document grants and
unique-source conservation are enforced. This changes neither embeddings, ANN,
reranking tensors nor the existing 400-pair / 50-primary / 32-context /
48,000-character measurement budgets. A failed empty probe can add one SQL
statement within that ceiling; it adds no neural inference.

This operates through the existing optional source-context catalogue in the
common engine used by CLI/MCP/HTTP. Plain bundles without it keep their behavior.
Existing verified catalogue/index/model assets can be reused. Restart the local
MCP process after updating the application; no corpus rebuild is required for
this change. See [source-context setup](SOURCE-CONTEXT.md).

## Source-quality evidence

Questions, reference answers and splits were unchanged. A six-case diagnostic
selection and additional sixteen-case selection were locked before current
inference and candidate code. The additional sample used a fixed hash from the
previously annotated bank, excluding the diagnostic cases and prior 32.
These are consumed regression data, not a new independent unseen benchmark.

| Check | Result |
|---|---|
| Six diagnostic cases | One previously missing complete definition recovered; other five complete responses identical |
| Original 32-case subset | 30/32 before and after; all previous supported cases retained |
| Additional locked 16 cases | All 16 complete responses identical; no new absolute accuracy score assigned |
| Kernel / RFC / T7 controls | Six actual MCP responses identical to their prior verified sources |

The recovered case was reviewed against the entire original question and actual
returned source paragraphs. The new paragraph supplies the defining relation;
a document-name or keyword match alone was insufficient. Typed AI reviews bind
the before/after judgments to their exact observations. There is no independent
human approval or generated-answer accuracy claim.

The original 32 baselines reproduced their previously measured MCP responses.
Only one candidate response changed, and its complete prior question proofs
were retained. Neither of the two previously insufficient original questions
was rewritten, dropped or relabelled. The additional sixteen identical outputs
establish retention, not 100% new-test accuracy.

The paired gate performed **48 fresh upstream retrievals**, then compared the
old and new postprocessors on each same result, three times in alternating
order. It did not perform 96 neural retrievals. Every returned chunk or exact
substring, original provenance and output budget was checked against the index.
Raw questions, source quotes, responses, review packets and models stay outside
Git. No full 1,322-case 3GPP run was started.

## Cost and actual MCP calls

Across the 48 paired full postprocessing checks, the median difference was
**2.18 ms**, the mean **6.10 ms**, and the observed
range **-52.62 to 75.49 ms** (observed 95th percentile
48.47 ms). Positive and negative deltas also occurred for
byte-identical responses with unchanged SQL plans. These include normal
scheduling/file-cache variability; they are not all extra software work.

A separate eight-repeat alternating source-only check examined the four eligible
plans, including the recovered development case, without neural work:

| Plan | SQL branches before / after | Median before | Median after |
|---|---:|---:|---:|
| Saturated control A | 3 / 3 | 122.26 ms | 125.14 ms |
| Definition control | 2 / 2 | 146.53 ms | 141.63 ms |
| Saturated control B | 3 / 3 | 168.80 ms | 164.67 ms |
| Recovered definition | 2 / 2 | 236.00 ms | 166.88 ms |

Actual `search_docs` calls separately checked the recovered case and two earlier
slow controls in counterbalanced ABBA order, two calls per variant per case.
Neural-output caching was disabled, and every complete response reproduced the
corresponding verified paired source gate:

| Actual local MCP | Calls | Median | Maximum | Below 10 s |
|---|---:|---:|---:|---:|
| Before | 6 | 6.83 s | 9.60 s | 6/6 |
| After | 6 | 5.14 s | 6.58 s | 6/6 |
| Kernel / RFC / T7 controls | 6 | 3.98 s | 8.96 s | 6/6 |

Do not attribute the entire end-to-end difference to this small source-only
change: warm-up, filesystem caching and shared host state also matter. Startup
for the large-bundle ABBA process was 254.10 s, measured
separately. The smaller-corpus controls included English and the existing supplied
Serbian Cyrillic/Latin translations; no automatic translation quality was tested.
No material slowdown was observed in this bounded check. This is not a guarantee
of zero overhead or a universal ten-second bound; the earlier broader slow
results remain in [the preceding checkpoint](GPU-MEMORY-BATCHING.md).

Local software verification: **560 passed, 19 skipped**, with Ruff, formatting,
mypy and schema drift checks passing. Real FTS tests include repetitive decoys,
a missing authorized alias, wrapped source labels, unchanged saturated plans,
verbatim provenance and the two-/three-statement limits. Platform/runtime CI
is checked separately before main is updated.

A final grammar guard excludes explicit negations and exception-only subjects.
It was added after the model measurements, with seven negative unit cases.
An equivalence check confirms identical definition plans for all 54 measured
3GPP questions and unchanged executable code outside that guard. The timings
above were not rerun for this guard; its query plans on those cases are identical.
