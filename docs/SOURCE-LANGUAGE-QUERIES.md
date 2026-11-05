# Original and documentation-language queries

The source-language-query path closes the measured Serbian/English gap on the
PostgreSQL evaluation. A caller or agent supplies a faithful English formulation
beside the original Serbian question, matching the documentation language.

| Query language/script | Consumed T7 development | First new-family questions |
|---|---:|---:|
| English | 90/90 (100%) | 31/32 (96.875%) |
| Serbian Cyrillic | 30/30 (100%) | 31/32 (96.875%) |
| Serbian Latin | 30/30 (100%) | 31/32 (96.875%) |

Scores require all requested facts in actually returned source evidence. They
do not measure generated-answer accuracy. Previously, the multilingual model
alone had 25/30 Cyrillic and 26/30 Latin. T7 is consumed development; its original
first score of 104/120 remains intact. New-family support exceeds 95% for each
measured language/script, while 96.875% falls short of the excellent 99% target.

## Supplying a faithful question

`RetrieveRequest.query_translation` accepts the documentation-language question
from the caller or agent; the original `query` is retained and searched. The
runtime does not invoke a translation API, download a translator or certify
semantic equivalence. Preserve identifiers, numbers, requested facts and
negation. Generated passive agent instructions explain the field; final answers
should remain in the user's language. Raw Serbian without this field retains
its earlier path. These scores do not evaluate automatic translation generation.

The shared engine supports CLI `use --query-translation`, MCP `search_docs` and
HTTP `/retrieve`. It requires hybrid retrieval, a local reranker and 100
candidates per method. Unsupported modes and standalone BM25 reject the field.
English without it, or an identical original and translation, keeps the prior
path. The measured profile uses multilingual E5, pinned mMARCO, facets-v3 and
section-start-v2. This PostgreSQL result does not globally replace other corpus
profiles. Kernel/RFC candidate reviews and GPP build/evaluation remain separate
and pending; original default preparation and original artifacts are unchanged.

## Bounds and software checks

At most 80 original and 120 translated root candidates are scored. Remaining
pairs cover four scoped explicit references and up to three translated facets
within an aggregate cap of 400 pairs. Source-language branches define the main
order; original fallback has rank weight 0.85. Rank values are not probabilities.
Technical subjects propagated between clauses come only from query terms and
do not override clauses naming different subjects. Both formulations preserve
grants, result count and text limits. No answer lookup, gold-source filter,
network or document execution participates. Output caps: 50 chunks and 48,000
text characters per response.

Software checks: 353 tests pass, 14 explicit optional-model/platform skips,
external frozen-bank drift, Ruff (178 files), mypy (56 source files), schema
drift and all six CI jobs on production-code commit e10bedd. Focused checks cover
offline exact/ANN retrieval, CLI, stdio MCP parity, grants and the pair cap.
Software checks are not quality samples.

## New-family validation

The candidate and protocol were frozen before exposing reserved source paragraphs
or writing new questions. Sixteen families exclude all 30 original T7 chapters.
There are 32 matched base questions per language and 96 actual queries: 16
one-paragraph and 16 two-paragraph fact-group questions per language. Questions,
minimum requirements, source spans and translations were locked before first
retrieval. All 1,143 PostgreSQL 18 documents remain searchable, with no gold
document constraint passed to the engine.

All 96 calls completed without errors; all 4,800 returned chunks were verified
against the immutable index. There are 93 full source-quote/span proof cases and
three source-quoted AI judgments of incomplete evidence. The same two-part
question fails in each language: a function prototype appears without the
required argument-direction explanation. Names alone are not credited as that
explanation. This is a shared retrieval failure. Supported fact groups: 141/144.
No case reviews are pending; there are zero independent human approvals. The
two-paragraph subgroup is 45/48 (93.75%), while each language's overall score is
31/32. The first result is preserved, without retuning or relabeling this bank.

These are paired variants and 16 source clusters, not 96 independent samples.
The corpus is still indexed PostgreSQL. References and translations are
AI-authored, with zero independent human approval. This is not a universal 95%
guarantee, a new-domain evaluation or a claim about unknown pretraining data.
Additional languages need their own cases. Separately, all 150 consumed T7 calls
are reviewed: 7,500 chunks verified, 149 mechanical source proofs and one AI
judgment of equivalent information, zero pending reviews and zero humans.

## Portable candidate and records

The verified local package is
`data/benchmarks/scale-v1/runs/quality-v4/t7-source-language-mmarco-v1-bundle`.
Nine retained index/query-model assets are byte-identical to the frozen physical
input. A real offline Cyrillic query returns exactly the same full response as
the development candidate. This proves packaging parity, not an independent
quality sample. The package and model stay local.

Exact counts, hashes and limits:

- [Consumed T7 result](benchmarks/source-language-t7-development-reviewed-v1.json).
- [First new-family result](benchmarks/source-language-new-family-reviewed-v1.json).
- [Historical frozen protocol](benchmarks/source-language-quality-protocol-v1.json).

Only code, protocol and numerical aggregates go to the private repository.
Source questions, evidence text and detailed outputs remain local. Original
first T7 results, source banks and GPP jobs remain intact.
