# Optional Intel GPU retrieval

Use the laptop's existing Intel GPU for the English-documentation reranker.
CPU remains the default. This option requires a supported Intel GPU and its
installed graphics driver; setup does not install operating-system drivers or
rent hardware. The GPU backend is optional on Windows and Linux x86-64.

## Setup, build, connect the agent

Windows PowerShell:

```powershell
.\setup.cmd -DocumentLanguage en -Accelerator intel-gpu
.\ragforge.cmd build "D:\My Documents"
.\ragforge.cmd agent
```

Linux:

```bash
bash setup.sh --document-language en --accelerator intel-gpu
bash ragforge.sh build /path/to/documents
bash ragforge.sh agent
```

The alternative document input remains `build --url "https://example.org/docs/"`.
Install the generated skill together with its MCP connection using `INSTALL.md`.
The agent uses a faithful English search query for English sources and can
answer in Serbian or another user language. RAGForge itself calls no translation
service. This profile is not a quality guarantee for non-English source documents.

Setup downloads the pinned OpenVINO SDK and the FP32 ONNX graph from the same
English MiniLM-L6 model revision as the CPU profile. The graph checksum is
verified before publication. Computation uses GPU FP16 and batches of eight
with at most two concurrent inference requests. Embeddings, indexing and
lexical search keep their existing CPU implementations. Reranking candidates,
source text and evidence budgets are not reduced.

GPU logits can differ from the quantized CPU model. Source-information
regression checks are required; this is not a bit-for-bit CPU optimization.

Existing bundles keep their recorded runtime. After changing setup, run `build`
and `agent` to create a new bundle and connection. Prepared CPU model files are
preserved in their separate directory. For CPU use, rerun setup with
`--document-language en --accelerator cpu` on Linux, or `-DocumentLanguage en
-Accelerator cpu` on Windows, then build a new bundle.

The selected GPU must be available at runtime. A missing SDK, unavailable GPU or
failed compilation produces an explicit error rather than switching backends.
Moving a GPU bundle to another machine requires the optional `intel-gpu` extra
and a supported driver there. `balanced` alone remains sufficient for CPU
bundles; install both extras if using pip directly.

## Local operation and measurement

Model downloads occur only during explicit online setup. Existing selected
models and the locked environment can be reused with `--offline` / `-Offline`.
A neutral GPU inference check must succeed before setup changes the active
model selection. Failed setup leaves that previous selection intact.

Retrieval reads the verified graph from memory without resolving external model
files. SDK analytics import is blocked before SDK initialization, selecting its
own no-op telemetry implementation. No telemetry preferences are written.
A local smoke check ran the actual GPU backend with socket and DNS calls
blocked. Queries and source documents stay local during retrieval; the external
agent follows its own provider configuration.

Measure a few warmed, uncached MCP calls, with startup reported separately:

```bash
.venv/bin/python scripts/measure_query_latency.py kb/your-bundle --query "Your English question"
```

Windows uses `.venv\Scripts\python.exe`. This command accepts at most five
questions and does not start a full corpus benchmark. GPU compilation and
bundle validation belong to startup, not the per-question retrieval time.

Development source-quality and latency results are reported separately from
unseen-test or generated-answer accuracy. Previously used test sets and
supplied translations cannot certify all future queries below ten seconds.

See [recorded development validation](INTEL-GPU-VALIDATION.md) for the measured
latency and preserved source-information counts, including earlier misses.

A [later bounded quality spot check](QUALITY-SPOTCHECK-20261110.md) retained all
68 checked cases in the smaller groups, but scored 14/16 on 3GPP versus 15/16
for its earlier multilingual profile. One required-information case was lost;
a current English CPU control repeated the same blind spot. The larger 3GPP
sample also included five engine calls above ten seconds. Quality retention and
a universal ten-second limit for 3GPP remain unproven.

A subsequent [source-use recognition change](SOURCE-USAGE-RECOVERY.md) restores
the lost case in that development subset: 15/16, with an additional 16-case check
unchanged at 14/16 and no newly lost supported cases. It adds no neural passes
and applies when an existing source-context catalogue is configured. The full
3GPP quality and latency targets still require further validation.
