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
