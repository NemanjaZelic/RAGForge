# English documentation, questions in your language

The explicit English profile uses the already supported, pinned
`cross-encoder/ms-marco-MiniLM-L6-v2` reranker for English **sources**. Questions
may be in another language: the generated agent skill directs the agent to
form a faithful English query, read the actual returned evidence and answer in
the user's language. This does not add a translation API to RAGForge.

## Setup, build, generate the skill

On Linux, from the repository directory:

```bash
bash setup.sh --document-language en
bash ragforge.sh build /path/to/documents
bash ragforge.sh agent
```

On Windows PowerShell:

```powershell
.\setup.cmd -DocumentLanguage en
.\ragforge.cmd build "D:\My Documents"
.\ragforge.cmd agent
```

The website alternative remains `build --url "https://example.org/docs/"`.
Install both the generated skill and its MCP connection using its `INSTALL.md`.
The final `agent` command remains the main outcome of the workflow.

Setup is the explicit download step. Reuse existing models with
`--models-directory` / `-ModelDirectory`; add `--offline` / `-Offline` when the
locked environment and selected models are already available. Source documents
and queries stay local during retrieval. The external agent follows its own
provider configuration.

`build` copies the selected model into a new portable bundle and records its
batch size and retrieval policies. The prepared source-model directory and
existing bundles are preserved. Rerun `build` and `agent` after changing setup
profiles; switching setup alone does not change the active bundle.

Without the language option, setup keeps the multilingual reranker. English
source mode is explicit; it does not infer the language from a filename or
claim support for arbitrary non-English source collections.

## Query behavior and evidence

The generated skill recommends hybrid reranked search with `top_k=50` and
`max_output_chars=48000`. For another question language it supplies a faithful
English question as `query`, retaining technical identifiers, versions,
conditions and negation. If an existing client supplies original `query` plus
English `query_translation`, this profile uses the supplied English query
through the same bounded engine. The runtime does not translate it.

CLI `ask` receives the query literally, so use English for this profile. A
translated question is prepared by the connected agent, not by `ask`.

Read both ranked `results` and attached `context`. Context contains indexed
source chunks from the same source section/page, or immediate neighbors in
unheaded text. Up to 32 context entries share the caller's existing character
budget. Ranked source text and scores are preserved. When only a boundary
excerpt of a plain-text neighbor fits, `text_offset` marks its starting Unicode
character in the indexed chunk; its text is a verbatim substring. Use
`fetch_context` with its chunk ID to read the full source when needed. Context
entries are evidence, not additional ranked hits or model confidence scores.

## Execution and validation scope

Single-pair batches avoid padding short passages up to longer neighbors. This
can change quantized-model scores, so quality must be checked against required
source facts rather than score equality. No candidates or returned primary
source text are shortened as part of this profile.

On supported AVX-512 VNNI CPUs, an optional in-memory weight representation
preserves integer products and is checked against original model outputs at
startup. Other CPUs, missing optional support or failed self-checks keep the
original graph. Model files are never rewritten. Set `RAGFORGE_DISABLE_VNNI=1`
to disable this optional execution optimization.

The development checks use existing, consumed evaluation sets and supplied
faithful translations. They measure required information in returned sources,
not generated-answer accuracy, an unseen final test, or the translation skill
of every possible agent. A new collection still needs its own quality check.

Time a few actual MCP requests, with startup separate and the neural cache off:

```bash
.venv/bin/python scripts/measure_query_latency.py kb/your-bundle --query "Your English question"
```

Windows uses `.venv\Scripts\python.exe`. This command accepts at most five
questions and does not start a full corpus benchmark.
