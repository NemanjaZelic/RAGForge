# T7: first unseen fourth-corpus check

The user requested completion of 3GPP/ETSI quality measurement and a fourth
previously unused test set. T7 uses the complete official PostgreSQL 18.0 HTML
manual: 1,143 source documents, downloaded from
https://download.postgresql.org/pub/source/v18.0/postgresql-18.0-docs.tar.gz.
The 3,845,019-byte archive and every original HTML source have frozen SHA-256
records. Archive SHA-256:
`f0dfc5b0882aa68ca471e9930a0dcfe4644a10a9b9613c60d6d14bfc9c224d44`.
Document commands/scripts are never executed. Acquisition is an explicit network
preparation step; build and retrieval deny sockets and DNS.

## Freeze and sampling

Selected retrieval code is ad942620e29b2e46a5e407ca1b4a3eaf81e57bf9, frozen
before source questions or query outputs. The only evaluator extension extracts
visible HTML body text independently of product parsing. The ranking engine,
models and all existing evidence canonicalizers are unchanged.

Thirty eligible chapters are chosen by seeded SHA-256 ordering from 64 eligible
chapters. One source per chapter is chosen by another seeded ordering; three
unique substantive paragraphs are sampled around 15%, 50% and 85% of that source.
There are 120 source-authored questions, 90 English and 30 Serbian, including
60 multi-fact questions. The 90 source fact groups have 180 question assignments.
Questions and exact minimal requirements are frozen before the first query.
All 1,143 documents remain in retrieval; no gold document filters are supplied.
The full quotes may contain context; unasked detail is not another requirement.

## Fixed measurement

Primary method: hybrid, facets-v2, section-start-v2, pinned E5-small and local
MiniLM-L6 reranker. Controls: raw BM25 and raw dense, without reranking.
Each receives top_k=50, max_output_chars=48000 and two inference threads; the
planned method keeps its 400-pair reranker cap. Child chunks use 350/50 characters,
parent contexts use sections at 1000/100. Source titles come from verified
indexed headings, independently of questions. Query alias expansions remain off.

Every requested fact must be supported by actual returned source text with a
valid citation. Document recall is reported separately and is not answer accuracy.
Exact full source spans are sufficient lower bounds; correctly scoped equivalent
information requires source-quoted semantic review. All first outputs, errors,
original requirements and run hashes are preserved. T7 is never silently retuned
or relabeled to reach a threshold. If later used for development it becomes a
consumed diagnostic set and a new holdout is needed.

This is previously unused for RAGForge tuning/evaluation. Pretrained models'
unknown training data are not claimed to exclude PostgreSQL. Questions and
source annotations are AI authored, with zero independent human approvals.
Related questions within a source are clustered. English and Serbian, single-
and multi-fact support must be reported separately. No 95%/99% claim exists yet.

Numeric/provenance lock: [t7-unseen-locked-protocol-v1.json](benchmarks/t7-unseen-locked-protocol-v1.json).
Detailed questions, quotes, sources, models and per-case outputs stay local and
ignored; only code, protocol descriptions and numerical summaries enter private Git.

## 3GPP scheduling

The original 3GPP native/version bank and full-corpus build remain unchanged.
The frozen bank contains 1,310 native test questions and 12 explicit-version test
questions, plus its original development/tuning splits. Native context-source
alignment diagnostics must remain distinct from complete answer-fact support.
The older full RFC rebuild is deferred with an intact dense checkpoint and exact
resume command to release RAM for 3GPP and T7. Corpus sources, original results,
labels and frozen recipes have not been deleted or rewritten.


## First result — 2026-11-05

All 360 actual queries completed without errors. Primary fixed hybrid supports
all requested facts for **104/120 questions (86.6667%)** after verifying all
6,000 returned chunks against the selected index. English: 88/90 (97.7778%);
Serbian: 16/30 (53.3333%). Single-fact: 58/60 (96.6667%); multi-fact: 46/60
(76.6667%). Across question assignments, 161/180 required facts are supported.
There are 16 incomplete questions; 95% and 99% targets are not met.

101 cases have complete original-source quote/span proofs. Nineteen cases
received explicit source-quoted AI review: three additional cases have complete
equivalent support and sixteen remain insufficient. Zero cases await primary
review; zero independent human approvals exist. This measures evidence available
to an answering agent, not generated-answer correctness. A source document
match alone earns no credit. Partial recommendations or wrong-scope rules do
not establish a complete answer. Some failures contain the right document but
stop before a key rule, while others return only related material.

Raw controls' strict complete-original-span lower bounds are BM25 103/120 and
dense 94/120, compared with hybrid 101/120 on the same mechanical diagnostic.
These are not final semantic accuracy estimates; raw-control semantic review
is not complete. Do not compare them directly with hybrid's reviewed 104/120.

The Serbian questions are all multi-fact and related source families occur
across languages, so these breakdowns do not isolate a randomized language
effect. The 30 source families also limit independent sample size. The original
first outputs, source requirements and retrieval settings remain unchanged.
The set has now been observed; any future tuning on it must label it consumed
and require a fresh holdout for a new unseen-test claim.

[Numeric result and provenance](benchmarks/t7-first-unseen-result-v1.json).

## Full 3GPP check in progress

The complete parent/context artifact is built and verified: 4,723 original
source records, of which 4,717 contain searchable text and six retain their
original extraction failure/zero-chunk status. The original 4,686,456-row dense
index is still building. No new full-corpus 3GPP accuracy is available yet.

Before any selected-profile quality output, the 1,322 original test questions
(1,310 native and 12 explicit-version cases) are bound to their unchanged native
reference answers and exact physical source pages. For 721 questions another
source PDF has identical raw bytes; these exact copies count as source
alternatives, verified by SHA-256 before measurement. Runtime query aliases
and gold-source filters remain off. Native provided-context reference support
will be reported separately from exhaustive standalone answer completeness.

A fixed one-shot local supervisor waits for the original full build, verifies
the published artifact, gives the selected hybrid check priority, and records
1,322 hybrid plus 2,644 raw control calls. It preserves all first outputs and
uses the original aggregate 60 GB benchmark limit and 15 GB free-space reserve.
Only verified duplicate derived assets or regenerable published-build float
cache may be retired; original corpora, labels, published indexes and original
measurements remain. Deferred original controls/RFC work resume afterwards.
No scheduler/service is installed and no semantic quality approval is automatic.

[Locked 3GPP reference protocol](benchmarks/gpp-first-native-reference-protocol-v1.json).
