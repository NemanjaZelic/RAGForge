# Bounded parent context for paginated sources

The full 3GPP index is complete. The first selected-profile evaluation exposed
an execution bug: parent mapping loaded every context chunk from a PDF before
checking the hit page. Documents larger than the two-million-character read
budget caused otherwise valid page-local requests to fail. That first attempt
was stopped after 74 committed calls, including 58 execution errors. Its frozen
runtime, original questions, labels, bundle and all committed outputs are kept.
Those partial calls are not a completed accuracy result.

Parent context now loads and caches the exact `(document_id, page)` scope before
applying the existing bounds. Unpaginated sources retain a null-page scope. The
mapper still checks actual shared text, document identity, page and available
line overlap. Document grants, deterministic ranking, the 200-candidate limit,
20,000-row/two-million-character scope bounds and the eight-entry/eight-million-
character cache bounds remain enforced. It reads the full eligible page; no
arbitrary tail is discarded and no memory limit is increased.

A regression fixture has more than two million characters across pages. Both
requested pages map to the correct real parent text and remain isolated in the
cache. A pathological matching page still triggers the original guard, and a
subsequent valid page request still succeeds. Existing offline exact/ANN mapped-
bundle, relocation and scope tests also pass. Complete software checks and
actual full-corpus replay results are recorded separately when finished.

The corrected evaluation uses the same verified bundle and all 1,322 original
questions, with the same gold/source identities and request limits. It is stored
in a new run rather than overwriting the aborted attempt. No embeddings or ANN
index need rebuilding. This is a runtime correction and regression measurement,
not a newly unseen test. Numerical reports must distinguish the two attempts
and retain the native provided-context reference limitation.

Local checks: 354 passed, 14 explicit optional/platform skips, external frozen-bank
drift enabled, Ruff and formatting (180 files), mypy (56 source files) and schema
drift pass. Eight focused parent-mapping and offline exact/ANN portability tests
pass. Actual corrected full-corpus query smoke checks are next.

Actual full-corpus replay: the three initially failing questions now return
source-verified results without errors. The fourth previously successful response
is exactly preserved. All 200 returned chunks match the immutable context index,
and output/reranker bounds pass. These four rows become the first four rows of
the corrected full run; they are not an independent quality sample. All six CI
jobs pass (42085776467). Complete native support and semantic review remain pending.
