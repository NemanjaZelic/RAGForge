# Optional source context

`source-context` builds a small catalogue of literal acronym definitions from a
verified bundle's own indexed text. It reads no benchmark questions, reference
answers or review labels, and performs no model inference. Extracted definitions
are candidates, including ambiguous or noisy meanings; source text remains
untrusted evidence for the calling agent.

```bash
ragforge source-context ./bundle --output ./definitions.sqlite
ragforge use ./bundle --source-context ./definitions.sqlite --query 'What is DNS?' --top-k 50 --max-output-chars 48000
ragforge serve ./bundle --source-context ./definitions.sqlite
```

The external catalogue is an explicit local CLI/stdio setting, bound to the
collection and SHA-256 of the exact source index. It must be supplied again after
relocation. To make a self-contained version, copy the verified base assets and
catalogue into a new bundle:

```bash
ragforge attach-context ./bundle ./definitions.sqlite --output ./context-bundle
ragforge verify ./context-bundle
ragforge use ./context-bundle --query 'What is DNS?' --top-k 50 --max-output-chars 48000
ragforge serve ./context-bundle
```

The original bundle is immutable. The new manifest inventories the catalogue,
includes it in the build identity and verifies every retained definition against
its physical indexed source. Existing bundles keep their previous build IDs.
The optional `--storage-root` on both preparation commands applies the existing
storage budget before allocation. Attaching requires space for a full new copy of
the bundle; local external use avoids that copy.

Authenticated shared HTTP requires an inventoried catalogue in the bundle.
`serve --transport http --source-context ...` and shared-client external overrides
are rejected, so the deployed build identity describes all runtime assets.
CLI, stdio MCP and shared HTTP use the same core retrieval implementation.

## Selection and limits

After ordinary retrieval/reranking/section completion, source context can replace
only redundant copies of the same whitespace-normalized text, section and PDF
specification family. Text shorter than 200 characters is never treated as a
cross-document duplicate. An explicit release/version query preserves distinct
document identities, including when a caller provides a translated query.
Every original unique information key remains in the final context.

The fixed policy tries up to 16 definition candidates, up to three literal FTS
queries (six source chunks total), then actual adjacent chunks around at most
16 distinct original anchors. At most 16 duplicate slots change. Document grants
are applied in SQL before selecting expansion candidates or source bodies.
Request chunk/character limits and the bundle's per-document cap still apply.
No extra embedding or reranker inference is performed. Returned scores encode
final context order when changed; they are not new model predictions or confidence.
A response without replaceable duplicate information is returned unchanged.

Definition extraction and technical query grammar currently cover ASCII acronym
forms and English queries. A faithful caller-provided documentation-language
`query_translation` can guide this optional stage; the application does not
perform automatic translation or claim equal accuracy for every language.

## Quality evidence

The complete consumed 3GPP measurement contains 1,322 cases. Retrospective AI
review found source support for 1,215 original responses (91.91%). The frozen
source-context policy supports 1,239 (93.72%): 24 improvements and no supported
case lost. This comprises 1,228/1,310 native cases and 11/12 explicit-version
cases; 83 cases remain insufficient. No cases were removed to increase the score.
All reviews are complete. This measures evidence available in context, not
end-to-end generated-answer accuracy, unseen generalization or independent human
approval. The requested 95% across all four collections/languages is not achieved.
Numeric provenance is recorded separately; local source text and per-case review
records are not published.

The upstream multilingual reranker outputs were reused from the frozen experimental
MM measurement. That selection is distinct from the base bundle default; the
93.72% result is not a newly measured default-bundle or all-language score.

## Short questions about purpose and use

The same source-only definition lookup accepts short technical questions such
as `What is ZQP used for?`, `What does ZQP do?` and `What is the purpose of ZQP?`
for an uppercase/digit technical short form. Several source meanings can be
returned. This adds no model inference and preserves existing duplicate-slot,
character and document-grant limits. Exact authorized catalogue matches avoid a
global short-form scan; the existing plural/typo fallback remains available.

See [the bounded recovery check](SOURCE-USAGE-RECOVERY.md) for source-quality
results and measured processor cost. Its English GPU subset recovers one missed
case without new losses; it does not replace the full multilingual result above
with a new full-bank score.

Longer purpose/role/function questions can also keep their leading subject and a
single technical actor in a bounded focused branch. Purpose explanations receive
priority inside the existing row/candidate limits. The [later quality and latency
check](QUALITY-LATENCY-20261110.md) recovered one additional full-question source
case, reaching 30/32 on the same consumed subset; the 95% target remains open.

## Compound technical definitions

Short unqualified multiword definition questions can prefer a verbatim source
that labels the full term in parentheses, within an otherwise available focused
search slot. The original literal branch remains; an empty probe restores the
old fallback within the same three-query ceiling. Source text, grants, output
budgets and the 16 duplicate-slot limit remain. No extra neural pass or catalogue
rebuild is needed. See the [compound-definition check](COMPOUND-DEFINITION-RECOVERY.md)
for the demonstrated recovery, unchanged original 30/32 score and measured costs.

## Later acronym experiment

A [bounded three-prototype comparison](ACRONYM-CONTEXT-EXPERIMENT.md) found no
confirmed additional whole-question recovery. None of its acronym-ranking
changes was adopted; the preceding retrieval implementation remains in use.

A later [explicit-reference lookup probe](REFERENCE-LOOKUP-EXPERIMENT.md) also
kept all 60 outputs identical while adding costly lookups. It was not adopted.
