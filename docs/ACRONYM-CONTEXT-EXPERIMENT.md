# Acronym context experiment: not adopted

Three private source-only prototypes were compared with the shipped retrieval
code at `b85f73f`. **No additional failed whole-question case was confirmed as
recovered. None of these prototypes is enabled in the application.** The prior
consumed 3GPP score remains **30/32 (93.75%)**; this experiment establishes no new
full-corpus, language-wide, independent or unseen accuracy score.

## Tested changes

1. Prefer acronym expansions whose words spell the acronym through initials,
   handling both hyphenated and space-separated forms.
2. Add literal question-term overlap to that preference.
3. Keep the original leading expansion; change only the secondary expansion
   when definition proofs belong to source families supported more strongly by
   the original question's terms in the existing top sixteen source results.
   Duplicate anchor texts were counted once. Version-qualified questions kept
   their prior behavior. This prototype required no additional source query.

These were private alternatives to the focused source lookup. Embeddings, ANN,
reranker inputs, neural passes and existing evidence budgets were unchanged.
This experiment did not implement or benchmark a broader compound-definition
index or cross-reference following; those remain separate proposals.

## Scope and checks

The comparison covered **60 distinct unchanged questions**:

- 54 reused real upstream results: the previous six diagnostic cases, original
  32-case subset and additional locked sixteen-case subset;
- six additional diagnostic cases, selected by a fixed salted hash among
  previously unused questions whose proposed expansion plan would change.
  Selection was frozen before current inference. This eligibility rule is
  diagnostic selection, not evidence of generalization to an unseen benchmark.

Each baseline and alternative processed the same upstream results, twice in
alternating order. Every baseline reproduced its stored complete response.
Returned text, offsets, provenance and output limits were checked against the
actual index. No full 1,322-case 3GPP evaluation was started. No other-corpus or
new language-wide quality measurement was performed in this experiment.

| Prototype | Complete responses unchanged | Changed | Confirmed newly recovered whole-question cases |
|---|---:|---:|---:|
| Initial-letter preference | 55/60 | 5 | 0 |
| Initial letters plus question terms | 55/60 | 5 | 0 |
| Conservative source-family context | 59/60 | 1 | 0 |

Existing answer-span annotations were available for 58 of these cases. Their
literal coverage did not improve or decline. Two additional cases lacked those
annotations; no missing score was converted into success. Literal span coverage
alone is not a semantic answer-quality judgment: equivalent correct passages
can differ from a labelled quote. No absolute semantic accuracy was assigned to
any of the three prototypes.

Inspection of changed source passages found undesirable domain shifts in the
first two prototypes. Acronyms need not consist of word initials, and identical
letters can name unrelated technical concepts. A spelling-based preference can
insert certificate-related passages into a radio-frequency discussion.

The conservative prototype kept all original 32, additional sixteen and six
fresh complete responses identical. Its sole change added a more directly
related procedure/configuration passage to an already-supported diagnostic
question. That is a relevance improvement, but it did not recover a previously
failed question, so it did not meet this experiment's adoption criterion.

## Cost and execution accounting

There were **seven fresh upstream retrieval attempts for six completed cases**.
A diagnostic harness stopped on a missing answer-span annotation after its
second retrieval. The first completed case was retained; the interrupted case
was repeated once after correcting the harness to save raw outputs before
optional scoring. Both unannotated questions stayed in the frozen selection.
Neither questions nor reference labels were rewritten to recover the run.

All postprocessor comparisons shared their upstream result; they were not
independent repeated neural queries. Source postprocessing timings are retained
privately, including both faster and slower observations. They are affected by
filesystem caching and scheduling, and establish no new end-to-end speed gain.
Direct-engine estimates also share the upstream retrieval and are not new
independent MCP latency measurements. Startup was measured separately at
291.47 s and 246.09 s for the two diagnostic processes.

The prototypes were rejected on the quality evidence above. The shipped
retrieval source files are byte-identical to the preceding checkpoint, so no
new runtime overhead was introduced. See the [preceding source recovery and
actual MCP measurements](COMPOUND-DEFINITION-RECOVERY.md) for the retained
implementation and its latency limits.

Only this aggregate account and a documentation link are committed. Questions,
source quotations, responses, case identifiers, review material, prototype
scripts, models and corpora remain outside Git. This is a documentation-only
checkpoint; local software tests were not repeated for unchanged product code.
The preceding code checkpoint passed 560 tests (19 skipped) and its required
checks. Exact-commit cross-platform CI is checked separately before main updates.
