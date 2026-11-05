# Multilingual retrieval development

The first unseen T7 result remains 104/120 complete evidence-support cases,
including English 88/90 and Serbian 16/30. The PostgreSQL manual is English.
This is cross-language retrieval, not a Serbian-document-only test. All Serbian
questions also require multiple facts. No overall 95% claim exists.

The installed embedding model is already multilingual-e5-small. The current
final reranker is the English MS MARCO MiniLM-L6 model, and earlier question
facets recognize mainly English syntax. These are candidate bottlenecks, not
a demonstrated complete causal explanation of the observed language gap.
Original literal-span diagnostics also show BM25 at 18/30 Serbian cases, dense
at 11/30 and selected hybrid at 13/30. These strict lower bounds must not be
confused with the source-reviewed hybrid 16/30 result.

## Implemented experimental options

- Explicit `facets-v3` preserves the original query and supplements coordinated
  interrogative clauses, including Serbian Latin/Cyrillic and several other
  language patterns. Quotes, code and parenthesized arguments are protected.
  It does not translate, invent query terms or claim to parse every language.
  Original document grants, output bounds and the aggregate 400-pair reranker
  cap still apply. Existing facets-v1/v2 are unchanged.
- Explicit `prepare_reranker.py --model mmarco-minilm` provisions a pinned
  multilingual cross-encoder with a verified quantized ONNX graph. It uses
  the existing local runtime and requires no document upload or custom model
  code execution. Provisioning is separate from offline retrieval/build.
- Newly generated passive agent instructions recommend also searching a faithful
  query in the documentation language when it differs from the user's language,
  preserving identifiers, numbers and negation. Answers remain source-based
  and in the user's language. No existing agent host is modified automatically.

Official model cards: [current English reranker](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2),
[current multilingual embedder](https://huggingface.co/intfloat/multilingual-e5-small),
[candidate multilingual reranker](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1).
A multilingual model's supported vocabulary/training is not a 95% accuracy
guarantee for Serbian or any other language.

## Verification and next measurement

342 local software tests pass, 14 optional pretrained-model/platform tests skip.
External frozen-bank drift checks, Ruff, mypy and schema drift pass. Two actual
pretrained multilingual-reranker checks also pass: offline build, relocation
and BM25/dense/hybrid queries using exact and ANN dense backends.
These are compatibility checks, not benchmark quality measurements.

The next comparison uses observed T7 only as a consumed development diagnostic.
It retains the original first outputs and adds a deterministic Serbian Latin
transliteration of the existing Cyrillic questions; original ASCII identifiers
and fact requirements stay unchanged. The comparison has 180 calls: 30 Serbian
Cyrillic with facets-v3/current L6, followed by 30 Serbian Cyrillic, 30 Serbian
Latin and 90 English with facets-v3/multilingual mMARCO. Inference uses one
thread and lower OS priority while the prior frozen 3GPP job continues.

It is an explicitly recorded in-memory model/policy experiment over an
immutable verified input bundle, not a new portable production bundle. Model,
runtime, query-variant and recipe fingerprints are frozen before its outputs.
No source/evidence text is uploaded. Exact source-span support is a lower
bound; equivalent evidence needs separate source-quoted review.

The user's desired additional languages are still being clarified. Initial
development covers English and Serbian, both scripts. A final claim needs a
fresh held-out set and enough questions for each named supported language,
including queries in one language over documents in another. It must verify
all requested facts, correct scope and source citations, plus English regressions.
The first T7 score cannot become a fresh unseen score again after tuning.

[Software/model provenance](benchmarks/multilingual-preparation-v1.json).


## Reviewed measurement after language changes — 2026-11-05

All 180 comparison calls finished without query errors. The multilingual
candidate has 150 actual calls; every one of its 7,500 returned passages was
verified against the immutable source index. Source-fact review is complete:
134 full source-quote/span proofs and 16 source-quoted AI judgments, with seven
additional complete equivalent answers and nine incomplete cases. There are
zero pending primary reviews and zero independent human approvals.

| Query language/script | Complete required-fact support |
|---|---:|
| English | 90/90 (100%) |
| Serbian Cyrillic | 25/30 (83.3333%) |
| Serbian Latin | 26/30 (86.6667%) |

On the original 90-English/30-Cyrillic composition this is 115/120 (95.8333%).
Including the 30 extra Latin variants gives 141/150 (94%). The original mix
weights English three times as heavily as Serbian; its passing aggregate does
not establish the requested 95% for every language. Serbian still misses that
target. The first unseen score 104/120 remains unchanged and separately stored.
This repeat is a consumed development measurement and needs a new holdout for
a new unseen-test claim. It does not measure generated-answer accuracy.

The strict literal diagnostic was 89/90 English, 21/30 Cyrillic and 24/30 Latin.
Those lower bounds are not the final source-reviewed figures above.

[Exact counts, provenance and limits](benchmarks/t7-multilingual-development-reviewed-v1.json).

The same frozen candidate is now queued for fresh actual calls on the unchanged
120 Kernel and 120 RFC questions. A 1,322-question GPP candidate check waits for
the original full-corpus primary baseline. Old Kernel/RFC scores will not be
reported as new-candidate scores. The GPP reference-span metric retains its
provided-context/native-answer limitation until separate semantic review.
No first inputs/results, bundle assets or original GPP runtime are rewritten.
