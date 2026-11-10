# Intel GPU development validation

Recorded 2026-11-10 on the existing i7-1195G7 laptop, Intel Iris Xe GPU and
approximately 12 GB RAM. No new hardware or paid service was used.
This is a development regression report over consumed datasets, not an unseen
benchmark or a guarantee for every future question.

## Warmed retrieval through actual stdio MCP

The final ten selected MCP requests used the product GPU backend. Initialization,
bundle verification, metadata preparation and GPU compilation are recorded
separately. Query times include source retrieval and MCP serialization, with
neural result-cache capacity zero and zero cache hits. They exclude agent-side
translation, final answer generation and startup.

| Collection / question language | Requests | Query seconds | Startup seconds |
|---|---:|---:|---:|
| Kernel | 1 | 4.35 | 9.08 |
| RFC | 5 | 3.96–8.86 | 60.37 |
| T7 English | 1 | 5.17 | 6.69 |
| T7 Serbian Cyrillic | 1 | 3.99 | 6.69 |
| T7 Serbian Latin | 1 | 3.59 | 6.69 |
| 3GPP, one fixed question | 1 | 9.77 | 176.39 |

RFC selection includes slow earlier CPU cases, a source-completeness regression,
and two additional highest-latency GPU development cases. T7 includes the
original English wording and supplied faithful Serbian translations. The
3GPP row is exactly one previously fixed question, not a full 1,322-case run.
The frozen existing indexes were verified and reused with an explicit in-memory
English/GPU profile for these large-corpus probes. They were not rebuilt or
copied, and these numbers do not certify arbitrary new chunking recipes.

Earlier probes remain part of the record: the first GPU 3GPP call took 10.33 s;
a trial that serialized ANN before lexical prefetch took 10.55 s and was
rejected. The retained change prepares ANN pages after GPU allocations during
neutral startup. Its final single-question result was 9.77 s. The full returned
source response and all 191 neural inputs/logits were identical to the first
GPU probe. One near-threshold result does not establish a universal latency
limit; first-request variance, corpus contents and other laptop activity matter.

The earlier 120-case RFC model-quality gate included two engine calls above
10 s (maximum 10.42 s). The final MCP selection explicitly rechecked those
slow cases. A complete final-profile timing distribution has not been measured.

## Required information in sources

Checks preserve required facts in returned sources, accepting equivalent correct
source passages. They do not grade a generated agent answer. Gold requirements
were not changed. All returned evidence entries were verified as stored chunks
or exact indexed substrings with their original provenance and shared 48,000
character evidence budget. Candidate limits and source text were not reduced.

| Consumed development set | Logical checks | Fresh unique retrieval requests | Previously supported cases retained |
|---|---:|---:|---:|
| Kernel | 120 | 120 | 118 / 118 |
| RFC | 120 | 120 | 119 / 119 |
| T7 | 150 | 120 | 150 / 150 |
| Additional technical family | 96 | 32 | 96 / 96 |

Kernel retains at least 118/120 all-fact successes and RFC at least 119/120;
previously unsuccessful cases are not silently counted as successes. One Kernel
case required AI reading of an explicitly equivalent same-version source; this
was bound to the actual response and unchanged requirements. It is not
independent human approval. No previously supported minimum fact was lost.

T7 comprises 90 English, 30 Serbian Cyrillic and 30 Serbian Latin variants.
The additional family has 32 variants in each language. Variants with the same
faithful English query share one source retrieval, so logical counts are not
independent inference counts. All 392 unique retrieval requests above were
fresh neural evaluations, with no neural-output replay or result cache.

The full source gates used the same pinned FP32 model, GPU FP16 execution,
batch size eight, two requests and retrieval policies as the product adapter.
An additional 349-pair comparison confirmed identical float logits between
the evaluated prototype and product adapter. All nine final non-3GPP MCP
responses contained exactly the full evidence from their completed quality
gates. The single 3GPP response preserved both required facts; all 55 returned
source entries were verified against its index. Full 3GPP quality after this
GPU change has not been rerun.

## Product checks

Actual native Windows commands completed English GPU setup, mini-document
build and `agent` generation. The generated MCP configuration searched the
model, fetched context and returned a valid source citation. A fresh-process
hardware test ran the real GPU backend with sockets/DNS blocked and verified
that the SDK selected its no-op telemetry implementation.

The default CPU path remains the default. Optional SDK import, missing GPU,
external/nested graph rejection, bounded request-buffer ownership, runtime
identity and atomic setup failure are covered by tests. Hardware-dependent
GPU testing is explicit via `RAGFORGE_GPU_RERANKER_DIR`; ordinary hosted CI does
not claim to own a GPU. Windows and Linux CPU workflows are checked separately
by CI before main is updated.

Local software checks: **494 passed, 19 skipped**;
lint, formatting, types and schema drift passed. The opt-in actual GPU hardware
test also passed separately.

Use [the GPU setup guide](INTEL-GPU.md) to select the profile, then build and
generate the agent integration. Raw corpora, questions, evidence quotes, models
and complete responses stay outside Git.

## Later, broader subset check

The [84-request follow-up](QUALITY-SPOTCHECK-20261110.md) found one source-quality
regression in its 16-case 3GPP subset: 14/16 versus 15/16 for the earlier
multilingual profile. A fresh English CPU control repeated that miss. The other
68 selected language/technical cases retained their required information.
Five of the 16 3GPP engine calls exceeded ten seconds. These findings limit the
earlier selected-query success; they must be included when assessing readiness
for larger 3GPP collections. No full 3GPP run was performed.
