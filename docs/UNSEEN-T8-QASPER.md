# T8 QASPER: first independent retrieval test

On 2026-11-11, the frozen application completed **120 first MCP requests** on a
new test set for this project. **Speed passed; the 95% quality target failed.**
No retrieval code, model or hyperparameter was changed after seeing these results.
This test is now consumed; future changes measured against it are development results.

| Measurement | First result |
| --- | ---: |
| Complete native evidence, any eligible annotator alternative | 97/120 (80.83%) |
| Native evidence plus additional source-quoted AI support judgments | 104/120 (86.67%) |
| Still not confirmed sufficient | 16/120 |
| Actual MCP requests below 10 seconds | 120/120 |
| MCP latency median / empirical p95 / maximum | 2.634 / 3.151 / 4.270 s |
| MCP and grading errors | 0 / 0 |
| Server startup, measured separately | 8.009 s |
| Corpus build, measured separately | 905.335 s |

The first quality row requires every textual evidence paragraph for at least one
valid native annotation. It is a strict evidence-sufficiency lower bound, not a
minimal-answer or generated-answer score. The second row preserves the first
97 passes and adds seven cases judged sufficient after reading the actual saved
sources. All 23 native-incomplete cases received a separate typed AI review;
positive reviews include exact returned quotes bound to the query, build, run
recipe and full response. Seven add support; 16 remain partial, ambiguous or
insufficient. **There is no independent human validation of these output reviews.**
The combined figure is a secondary AI-assisted support estimate, not an official
QASPER leaderboard score or automatic quality approval. The original 97/120 is
unchanged. Wilson 95% intervals are 72.88-86.87% for native complete evidence and
79.44-91.62% for the secondary estimate; the latter interval does not account for
reviewer error. Neither result reaches 95%.

## Dataset and prospective protocol

[QASPER by AllenAI](https://huggingface.co/datasets/allenai/qasper) contains
expert-authored questions about NLP research papers. The
[authors' paper](https://arxiv.org/abs/2105.03011) describes the benchmark. We used
the official v0.3 **test split**, not a previously used RAGForge collection:
416 papers and 1,451 questions in the downloaded JSON.
The archive was downloaded from the official dataset location; downloaded
Python evaluator code was not executed. Dataset licensing is CC BY 4.0;
underlying papers retain their own terms. Raw material is not redistributed here.

The [prospective protocol](benchmarks/t8-qasper-unseen-protocol-v1.json) was
published in commit `b3db9714e50d0823a467068e779acb9e5b651cf6` **before any
measured query**, with the frozen runtime and source/question/reference hashes.
Application commit: `94d61d233bd90b449f42acda144a2e245bd924ad` (69 product Python
files verified unchanged throughout). No questions, answers, labels, per-case
responses or private review quotes are committed to this public repository.

Eligibility required an answerable annotation with nonempty, entirely textual
evidence locatable in the supplied paper. Figure/table-only evidence and
unlocatable evidence were excluded prospectively. This left 1,232 questions on
403 papers; 219 questions were ineligible (79 all-unanswerable, 140 without an
eligible textual alternative). A fixed SHA-256 seed selected one native question
per paper and then **120 different papers**, independently of runtime results.
All valid native textual annotation alternatives were retained.

The index contains **all 416 papers / 15,490 chunks**, including titles, abstracts,
supplied full sections and textual captions. It excludes question, answer and
annotation fields. Every query is the **unchanged English native question plus
its original paper title**. The title supplies the native paper scope, available
to question authors; all corpus documents remain searchable, with **no oracle
document filter**. This is an adapted cross-paper source-retrieval evaluation,
not QASPER's official generated-answer F1 task. The selected first annotation
answer types were 86 extractive, 18 free-form and 16 yes/no.

## Runtime and integrity

The build used the existing explicit-English GPU quickstart policy: balanced
E5-small embeddings, ANN, token-aware sections (1000/100), facets-v3 and
section-gaps-v3, and the existing MS MARCO MiniLM GPU reranker. No special
source-context artifact or additional model was introduced. Retrieval used
hybrid search, reranking, top-k 50, at most 32 context chunks, 48,000 output
characters, eight threads, two reranker workers and no neural batch cache.

Measurements used the actual stdio MCP `search_docs` RPC on the existing laptop
(i7-1195G7, 12 GB RAM, integrated Iris Xe). A neutral warm-up preceded the
measured questions. Times cover retrieval until sources return; startup, grading
and any downstream answer generation are separate. Every first structured
response was saved before scoring; no measured question was retried or replaced.
All returned text and physical source locations and output limits were verified.
Maximum reranker pairs: 322; neural cache hits: zero.

The server had a tested Python audit guard denying access to the raw dataset,
private questions, labels and document map. Python external socket/DNS calls
were denied; retrieval allowed no connections. This was an application-level
guard, not an operating-system isolation claim. No new model, service or hardware
was purchased, and no full 3GPP evaluation was started.

## What the misses show

Several returned introductions or methods sections omit the requested evaluation
dataset, a complete comparison-method list, or a numeric corpus size. Returning
the right paper or an unrelated paper using the same dataset name does not prove
the requested fact. The seven supplemental passes instead supply the answer from
other returned passages, such as captions, results or a shorter architecture
identification. They do not require literal copying of a complete original label.

Some remaining cases also have native answer disagreement or a question/reference
granularity mismatch. Those cases stay in the denominator and remain conservatively
unconfirmed; neither their labels nor their first outputs were rewritten. Native
human annotations and the supplementary AI judgments are both imperfect measures.
The original consumed 3GPP development subset remains **30/32 (93.75%)**, unchanged.

This new English-only sample does **not** establish Serbian or all-language
quality, sub-10-second latency on the 4.7-million-chunk 3GPP index, or generated
answer truthfulness. The public benchmark may have appeared in pretrained model
training; that overlap is unknown. New to this project's tuning does not mean
unseen by the pretrained models. The result therefore supports a limited claim:
fast retrieval on this corpus, with a substantial remaining quality gap.

Machine-readable [first-result aggregate](benchmarks/t8-qasper-first-result-v1.json)
retains the protocol, question/reference locks, build identity, metrics and limits.
