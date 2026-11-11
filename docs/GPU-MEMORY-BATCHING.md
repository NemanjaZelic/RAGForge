# GPU memory and length grouping checkpoint

This bounded development check keeps the original **30/32 (93.75%)** complete
source-information score. No previously supported case was lost. The two
previously insufficient questions, original labels and denominator remain.
The result is not 95% or an unseen-test / generated-answer accuracy claim.

## Runtime change

The optional Intel GPU adapter uses batches of at most four and groups pairs
by their truncated token lengths. It restores logits to the caller's original
passage order. Every pair keeps the same query, passage tokens, masks and token
types; unnecessary padding is reduced for short pairs. CPU batching stays
unchanged. The packaged model descriptor remains a capacity of eight; no model
or index is replaced. There are still at most two GPU inference requests.
Sequence lengths are right-padded to a multiple of 16, capped by the packaged
token limit. Additional positions have zero attention masks. This bounds the
number of dynamic GPU shapes encountered across a long session.

The implementation tokenizes bounded batches and retains only the truncated
integer arrays. Tokenizer overflow objects from long passages do not accumulate
across the entire request. The existing candidate union, 400-pair limit and
48,000-character evidence budget are unchanged. Same model bytes and FP16
execution do not imply exact logits when batch membership / padding changes.

## Isolated measurements

The batch-size experiment replays the same three captured reranking plans in
fresh processes without result caching. Two size-eight controls took
15.70 / 15.49 s;
the size-four trial took 15.88 s. Maximum private
process memory was about 905.18 / 905.67
MiB for the controls and 666.32 MiB for size four.
This demonstrates a memory reduction, not a reranking speed improvement by itself.

A separate three-plan ABBA experiment compares original size-four grouping with
length grouping. The original controls took
13.51 / 12.95 s;
length grouping took 12.44 /
12.08 s: 7.3% less scoring time on
average. Private process memory was approximately
767.94 MiB versus
675.50 MiB. Maximum absolute
logit difference in that experiment was 0.03125, requiring the source gate below.
These are separate experiments; their memory savings are not added into a
single measured end-to-end reduction.

A read-only token inventory over the 32 existing questions found 2,410,306 padded
size-four tokens with original grouping versus 2,134,849 with length grouping alone,
before alignment to 16,
with all 2,106,158 actual tokens retained. There was no extra inference in that
inventory.

An additional eight-plan experiment compares that unrestricted length grouping
with sequence alignment. Unrestricted controls took
29.05 /
29.30 s and used 175
GPU shapes, reaching 916.43 /
930.76 MiB of private process memory.
Alignment to 16 took 27.28 s,
used 24 shapes and reached 677.62 MiB.
Alignment to 32 was also measured: 26.94 s,
13 shapes and 700.37 MiB. The final
choice is 16 for its lower observed memory use and smaller padding/logit change.
The largest logit difference for alignment to 16 tokens was 0.03125. This is a separate
replay with identical inputs across variants, not eight fresh ANN searches.

## Actual source and latency checks

Every source check below used actual local `search_docs` calls and an empty neural-output
cache. Returned source rows, exact indexed substrings, provenance and output
budgets were verified. Complete prior fact proofs were retained or actual changed
source text was reviewed; matching a document name alone was insufficient.

| Bounded check | Supported source-information cases | Actual search calls |
|---|---:|---:|
| Unchanged consumed 3GPP subset | 30/32 before and after; zero new losses | 36, including four repeats |
| Kernel subset | 6/6 | 6 |
| RFC subset | 6/6 | 6 |
| T7 English / Serbian Cyrillic / Serbian Latin | 4/4 in each language | 12 |

The smaller groups retain the prior slow cases and the compound-question
counterexample. Remaining cases were selected by fixed hash from a previously
frozen regression sample before their current outputs. Translated variants are
not statistically independent questions. No full 1,322-case 3GPP evaluation was
started, and these subset scores do not replace historical full-corpus scores.

| Actual MCP run | Median | Maximum | Calls below 10 s |
|---|---:|---:|---:|
| Size-four only, original grouping | 11.23 s | 15.99 s | 12/36 |
| Size-four with unrestricted length grouping | 8.49 s | 10.56 s | 32/36 |
| Size-four, length grouping and alignment to 16 tokens | 7.69 s | 11.04 s | 35/36 |
| Smaller groups with length grouping | 4.68 s | 11.57 s | 22/24 |

The three large-bundle runs were sequential, not a counterbalanced end-to-end A/B
experiment. Available shared RAM varied; do not attribute their entire latency
difference to grouping. All runs are retained, including slow calls. Startup
was measured separately: original grouping 477.93 s,
unrestricted length grouping 376.80 s,
and alignment to 16 tokens 384.13 s.
The isolated replay experiments support the narrower reranking improvement.

Long sessions matter: unrestricted length grouping grew to a higher private
memory total in the real 36-call process despite its favorable three-query
microbenchmark. The alignment experiment was added for that reason. Actual
process observations are retained below; host RAM and process allocator state
varied, so this is not a causal end-to-end memory A/B comparison.

| Large-bundle process | Maximum private memory | Final private memory | Minimum available host RAM |
|---|---:|---:|---:|
| Size-four original grouping | 1867.96 MiB | 1853.81 MiB | 5.25 MiB |
| Unrestricted length grouping | 2024.37 MiB | 1955.88 MiB | 144.03 MiB |
| Length grouping with alignment to 16 tokens | 1792.06 MiB | 1752.22 MiB | 17.04 MiB |

A reliable ten-second bound and the original 95% target remain open.

## Verification and use

Local checks: **537 passed, 19 skipped**; Ruff, formatting, mypy and schema drift
passed. Synthetic GPU tests verify full unmasked tensors, nonzero padding IDs,
original score slots, package batch limits, alignment clamping at non-multiple
token limits, error recovery and CPU behavior.
Actual model/GPU runs validate the real hardware path; ordinary hosted CI does
not claim to own an Intel GPU.

See [Intel GPU setup](INTEL-GPU.md). Existing GPU bundles use the updated execution
policy after updating the application; changing runtime selection still requires
setup, build and agent generation. Raw questions, corpora, proof quotes, full
responses and models stay outside Git.
