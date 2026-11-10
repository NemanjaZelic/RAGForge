# Source-quality spot check after the English GPU profile

Date: 2026-11-10. Tested application source commit:
`ed1db6dabeb13d34aeaed5a23e6dd79828505edd`.

The four smaller development subsets retained all checked information. The
3GPP subset lost one previously supported case. The accelerated English profile
therefore does **not** have demonstrated quality retention across 3GPP.

## Fixed subset results

| Group | Previously supported in this subset | Current supported | Current subset percent | Previously supported cases lost |
|---|---:|---:|---:|---:|
| Kernel | 16/16 | 16/16 | 100.00% | 0 |
| RFC | 16/16 | 16/16 | 100.00% | 0 |
| T7 language variants | 24/24 | 24/24 | 100.00% | 0 |
| Additional technical family | 12/12 | 12/12 | 100.00% | 0 |
| 3GPP | 15/16 | 14/16 | 87.50% | 1 |

These are required-information judgments on actual returned sources. Correct
equivalent passages count; a different document ID or quote does not by itself
cause failure. This is not generated-answer accuracy or a new independent
held-out benchmark. The percentages describe only these selected subsets.
In particular, 14/16 does not replace the earlier full-bank 3GPP result with a
new full-bank accuracy estimate.

T7 includes eight English, eight Serbian Cyrillic and eight Serbian Latin
variants. The additional technical family includes four of each. Serbian
requests use the existing frozen faithful English translations through the
English-documentation query route; agent-generated translation quality was not
re-evaluated. Every one of the 84 requests ran fresh neural inference, including
paired language variants. Result-cache capacity and cache hits were zero.

Kernel and RFC each contain eight single-topic and eight multi-part questions.
3GPP contains twelve native-context questions across declared source families
and four questions requiring a particular standard version. The four explicit
version cases retained all required information: 4/4. Native cases scored 10/12.

The earlier 3GPP comparison is the best previously reviewed multilingual
source-context profile on the exact same selected questions: 15/16. It is not
an unmeasured assumption about the preceding English CPU profile. The other
subsets compare with their previously established source support.

## What failed and what was checked

One already unsuccessful, context-dependent question remained unsuccessful.
A second case, previously supported by the multilingual profile, now retrieves
other senses of an ambiguous acronym and omits its required technical usage
list. It is counted as a genuine missing-information case. No failed question,
requirement or answer was removed or rewritten.

A separate, fresh single-query control used the current English MiniLM-L6 CPU
INT8 model with batch size one on that same failing case and corpus. It also
failed to return the required information. This suggests an English-profile
model/acronym-resolution blind spot; the observed loss is not isolated to GPU
FP16 execution. One control cannot certify equivalence of the backends on all
other questions.

All five 3GPP cases that lacked an intact previous full proof received explicit
AI source reading, bound to their actual returned chunks and unchanged question.
Three were supported by equivalent correct information; two were insufficient.
These are AI reviews, not independent human approval. Returned sources and
48,000-character budgets were checked for every request. The paired CPU control
also verified all 60 returned source entries.

## Selection and limits

A deterministic hash seed fixed the sample before its new outputs. No answer
or outcome was used to pick successful cases. The 3GPP export contains 2,765
questions, while the frozen reviewed evaluation universe contains 1,322.
A preflight detected this distinction before any 3GPP retrieval. The 3GPP-only
selection was corrected to the annotated universe and locked again before
inference, keeping the same seed, twelve-plus-four design and all other 68
selections. Original selection files and the correction record were preserved.
The previously repeated single 3GPP latency question was excluded.

Only 16 3GPP sample requests and one CPU diagnostic control were run. The full
3GPP benchmark was not started. Existing immutable indexes and prepared models
were reused; large corpora were not copied or rebuilt. Application source code,
model files, original questions and reference answers were not changed. Local
retrieval ran with sockets and DNS blocked. Raw questions, sources, proof quotes,
complete responses and per-case reviews remain outside Git.

This quality check also observed a larger latency tail: 5/16 GPU 3GPP engine
calls exceeded 10 seconds, with a maximum of 13.94 seconds. Startup is separate;
these are engine timings, not additional MCP measurements. The earlier ten
selected MCP timings remain their own small experiment and do not establish a
universal latency limit. This follow-up establishes a remaining quality and
latency gap for larger 3GPP use.

The next development target is recovering the lost acronym-related source
information while retaining the faster path, followed by another small paired
regression sample. Current evidence supports the smaller checked subsets and
requires more work before promising the same outcome throughout 3GPP.
