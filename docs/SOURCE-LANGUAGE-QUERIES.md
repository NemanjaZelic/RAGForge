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
