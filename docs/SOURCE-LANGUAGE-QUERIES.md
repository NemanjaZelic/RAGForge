# Original and documentation-language queries

Serbian T7 development support improved to 25/30 Cyrillic and 26/30 Latin with
the multilingual reranker, while English reached 90/90 after source review.
The remaining multi-fact failures motivated an additional query path.

`RetrieveRequest.query_translation` is an optional faithful formulation of the
same question in the documentation language, supplied by the caller or agent.
The original `query` remains present and searched. The runtime does not call
a translation API, download a translator or certify semantic equivalence.
Identifiers, numbers, requested facts and negation must survive translation.
The generated passive agent instructions tell the agent how to supply this
field; the user's final answer should remain in the user's language.

This is one shared engine operation behind CLI `use --query-translation`, MCP
`search_docs` and HTTP `/retrieve`. It requires hybrid retrieval with a local
reranker and 100 candidates per method. Unsupported modes reject the field.
The standalone BM25 index rejects it rather than silently ignoring it.
English queries without this field retain their earlier retrieval path. An
identical original/translation uses that earlier path as well.

The fixed translated strategy scores at most 80 original and 120 translated
root candidates. Remaining pairs cover four scoped explicit references and up
to three translated question facets, with an aggregate cap of 400 pairs.
Source-language branches determine the main rank order; the original fallback
has rank weight 0.85. These rank values are not probabilities. Technical
subjects inherited from a first clause come only from the query and are not
added to clauses that explicitly name different subjects. No answer lookup or
gold source filter participates. Both queries preserve the caller's collection
and document grants, final result count and text budget.

All standard local software checks pass: 353 tests, 14 explicit optional-model/
platform skips, external frozen-bank drift enabled, Ruff (178 files), mypy
(56 source files) and schema drift. Focused checks cover actual offline exact/
ANN retrieval, CLI, stdio MCP parity, grant containment and the 400-pair cap.
These are software checks, not an accuracy claim.

The next development comparison freezes faithful translations of all 60 T7
Serbian script variants before any new query output, plus the unchanged 90
English controls. Original questions, fact requirements and first results remain
intact. This is consumed development data. A new source-family holdout will be
authored and locked after candidate selection, before its first retrieval.
Faithful AI-authored translations and zero independent human approvals must be
reported; a caller-supplied translation benchmark alone does not establish
translation generation accuracy for every possible agent or language.

No 95% Serbian claim is made before actual source-bound measurements complete.
The existing frozen multilingual and 3GPP runs continue with their exact earlier
runtimes; the new optional request field does not rewrite those jobs.


## Frozen measurement in progress

The first completed language group has 30/30 original T7 Cyrillic questions with
all original source facts supported. Every one of its 1,500 returned chunks was
checked against the immutable source index. The questions and required facts are
unchanged. Latin and English controls are still running; this is consumed data,
not a new unseen score. The earlier Cyrillic result was 25/30.

Before exposing new source paragraphs or writing new questions, the e10bedd
candidate and request/translation protocol were frozen. The new bank has 32
matched base questions in each of English, Serbian Cyrillic and Serbian Latin:
96 actual calls, 16 source families outside all 30 original T7 chapters, with
16 one-paragraph and 16 two-paragraph fact-group questions per language. Questions,
requirements, source spans and supplied translations were locked before first
retrieval. These are related variants and source clusters, not 96 independent
samples. The corpus is still the indexed PostgreSQL 18 manual. New-bank results
are pending. Its source content and per-case outputs remain local.

A real portable candidate containing the multilingual reranker is also verified:
`data/benchmarks/scale-v1/runs/quality-v4/t7-source-language-mmarco-v1-bundle`.
All nine retained index/query-model assets are byte-identical to the frozen
physical input. An actual offline Cyrillic query against this package returns
exactly the same complete response as the evaluated in-memory candidate. This
checks packaging parity; it is not another independent quality sample.

The exact hashes and scope are in
`benchmarks/source-language-quality-protocol-v1.json`. Only code, protocol and
numerical aggregates are saved to the private repository. Original GPP and
cross-corpus regression jobs retain their earlier frozen runtimes.
