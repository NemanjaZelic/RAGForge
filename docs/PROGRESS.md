# Razvojni dnevnik

Datum: 2026-11-01. Kanonska radna kopija: `D:\RAGForge`.

## Sačuvan razvoj

- `5abdd61`: postojeći originalni plan i proverena F0 osnova, 39 uspešnih testova.
- `73a0e88`: RF-000 minimal/balanced manifest, lokalni query model i dense
  metadata/inventar, search-method ugovori, generisane šeme i sintetički primeri.
  56 uspešnih testova; lint, format, mypy i schema drift prolaze.
- `d62db93` RF-001: API i stvarna `ragforge scan` komanda sa sortiranim putanjama,
  identitetima i hash-evima. Provereni limiti, prazni/dupli sadržaji,
  nečitljivi i zamenjeni fajlovi, NFC, Windows junction i CLI offline subprocess.
  71 uspešan test, 3 preskočena zbog case-insensitive filesystem-a i nedostatka
  privilegije za symlink. Ti testovi ostaju aktivni za druge CI platforme.
  Ruff, mypy i schema drift prolaze. Prvi GitHub CI naknadno uspešno izvršen; detalji ispod.
- `7ae1a59` GitHub maintenance alat dodatno ima 6 testova koji sprečavaju slanje u javni
  ili pogrešan repo i proveravaju remote HEAD. Tada ukupno: 77 passed, 3 skipped.

- [2f5164c](https://github.com/NemanjaZelic/RAGForge/commit/2f5164c894ca1206d0856747221c939106b71466)
  RF-002: provereni MD/TXT/HTML parser, deterministički bounded chunker,
  tačni MD/TXT redovi, HTML bez izmišljenih redova, code blokovi i chunk CLI.
  Lokalno 102 passed, 3 skipped; sve obavezne provere prolaze.
  Mini-korpus: 6 dokumenata, 21 chunk, 2840 izlaznih tekstualnih znakova.
  Ovo je funkcionalna ingestion provera, bez benchmark tvrdnje o retrieval kvalitetu.

Originalni plan je sačuvan neizmenjen; njegov SHA-256 ostaje
`1023b17b63b39957b71dfbf490099c89537f34434bdb16fbb907cc478dde6524`.

## GitHub

Privatni repo: [NemanjaZelic/RAGForge](https://github.com/NemanjaZelic/RAGForge).
Pristup je potvrđen GitHub konektorom; standardna Git prijava obnovljena je
postojećim Git Credential Manager-om. Postavljen je origin i main prati
origin/main. Prvih pet commit-a uspešno je poslato i remote main potvrđen je
kao f89790f35583acc9086bc034a8ffda92220686bd. Raniji 401/404 blokatori su rešeni.

Za naredne sinhronizacije, iz D:\RAGForge:

```powershell
.\scripts\dev.ps1 run python scripts/github_sync.py --push
```

Alat koristi postojeći Git credential helper, ne pravi nove tokene niti
ispisuje/čuva kredencijale. Proverava nalog, privatnost, identitet repo-a,
čist main i postojeći origin. Nema force push-a ni promene vidljivosti.
Posle push-a poredi remote main SHA sa lokalnim HEAD. `--open` otvara formu;
bez `--create`/`--push` nema API upisa ni slanja koda. Ovo je zaseban
maintenance alat; lokalni scan/retrieval ga ne uvoze i nemaju mrežne pozive.

## GitHub CI — potvrđeno

[RF-002 CI run](https://github.com/NemanjaZelic/RAGForge/actions/runs/41277555420)
završen je uspešno za commit 2f5164c: Ubuntu i Windows, Python 3.11 i 3.13.
Svaki job izvršava pytest, lint, format, mypy, schema drift i izgradnju wheel/sdist.
Prethodni početni CI run 41277114172 takođe je uspešan.
Lokalna tri preskakanja su platform/privilege zavisna; ne predstavljaju CI grešku.

## Poslednja isporuka

- abae50f: RF-007 PDF adapter, stvarni fixtures i pinovani realni PDF pilot.
- 72e8cc3: RF-003 SQLiteEngine, index/search/context CLI, offline mixed MD/PDF
  E2E, Unicode stdout ispravka i izmereni BM25 mini/PDF smoke izveštaji.
- [RF-003 CI](https://github.com/NemanjaZelic/RAGForge/actions/runs/41278861087)
  uspešan je na Windows/Linux i Python 3.11/3.13; uključuje tests, lint,
  format, mypy, schema drift i wheel/sdist build.
- Lokalno 132 passed, 3 platform/privilege skipped. Originalni plan ima isti SHA-256.
  GitHub main i lokalni HEAD se proveravaju posle svakog push-a; lokalni Git bundle
  checkpoint se osvežava posle isporuke.

## Sledeći korak

RF-002 je završen: normalizovani MD/TXT/HTML tekst, source hash provera,
provenance i deterministički chunking. Novi ukupan rezultat: 102 passed,
3 skipped; pytest, ruff, mypy i schema drift prolaze. Chunk CLI subprocess
prolazi uz blokirane Python socket/DNS pozive.

RF-007 PDF adapter je implementiran: fizičke stranice, page status, strogi
limiti i eksplicitna delimična obrada; 113 testova prolazi, 3 skip-a.
Tri originalna PDF fixture-a vizuelno su proverena; realni RFC 9110 pilot
ima 194/194 extracted stranice. [Granice i pilot](PDF.md).

RF-003 je završen: SQLite FTS5/BM25 engine i stvarni index/search/context.
132 passed, 3 skipped; sve lokalne provere prolaze. Offline MD+PDF CLI E2E
proverava kopirani indeks, ćirilicu i PDF page citate.
Mini baseline: Recall@5=1.0, MRR@10=1.0 na 16 document-level razvojnih
pozitivnih upita; 2/4 negativna daju rezultate. Realni PDF smoke: 3/3
očekivane stranice na prvom mestu. [Granice](RETRIEVAL.md).

PDF commit abae50f ima uspešan Windows/Linux Python 3.11/3.13 CI:
https://github.com/NemanjaZelic/RAGForge/actions/runs/41278248319

Slede RF-009 izbor i pilot CPU query modela/dense backend-a, pa RF-004
bundle integritet i RF-005 build/use. Širi RF-006 benchmark ostaje uslov.
Bundle build/use još nisu implementirani. Pravi dense/hybrid
ostaju obavezan deo v0.1 prema RELEASE-SCOPE.md.

## Lokalni balanced tok — nova isporuka

- 5aa0c88: lokalni CPU ONNX provider, exact cosine/RRF, verifikovani
  minimal/balanced bundle-i i stvarni build/use/verify/context.
- [CI 41281667303](https://github.com/NemanjaZelic/RAGForge/actions/runs/41281667303)
  prošao je svih 6 poslova: Windows/Linux Python 3.11/3.13 provere i stvarni
  pinovani E5 build/query na Windows/Linux; Linux OS network namespace
  build/query korak takođe prolazi.
- Lokalno je proveren kompletan skup sa stvarnim E5 modelom: 158 passed,
  3 Windows platform/privilege skip-a; naknadni PDF bundle test takođe prolazi.
- [Pilot dva modela](benchmarks/model-runtime-pilot.json) meri isti postojeći
  mini-skup za BM25/dense/hybrid. Pozitivne document-level metrike su 1.0;
  dense/hybrid vraćaju rezultate na 4/4 negativna upita. To nije dokaz
  abstention-a ili kvaliteta na reprezentativnim korpusima.
- Modeli, alati, cache i lokalni bundle-i ostaju na D i van Git izvora.
  Code/model licence se ne mešaju: početni model MIT, projekat/korpus NOASSERTION.

RF-009 implementacija i RF-004/005 lokalni tok su završeni uz navedene granice.
Test setove priprema zaseban agent. Slede njihova evaluacija i agent/MCP sloj;
ne tvrdi se završen v0.1 release dok reprezentativni quality uslovi ne prođu.


## RF-008A — lokalni MCP i pasivna agent integracija

- `serve` pokreće stvarni stdio MCP nad jednim verifikovanim BundleEngine-om:
  search_docs/fetch_context/list_collections, strukturisani retrieval ugovor,
  bounded ulazi i read-only oznake. Podrazumevani balanced/hybrid i eksplicitni
  BM25/dense daju iste rezultate kao direktni engine.
- `integrate` atomski pravi novi direktorijum sa validnim Agent Skills fajlom,
  nepoverljivim metadata reference fajlom i zasebnim generic MCP config-om.
  Ne menja host podešavanja ili postojeće fajlove. Skill validator prolazi.
- [Stvarni MCP klijent](../examples/mcp_client.py) poziva discovery, search i context.
  [Zabeležen razvojni smoke](benchmarks/mcp-smoke.json) vraća hybrid citat
  `authentication.md:3-6` za prenos access tokena u Authorization/Bearer zaglavlju.
  Primer je deterministički klijent; nije nezavisna LLM agent evaluacija.
- Lokalno: 178 passed, 3 Windows platform/privilege skip-a. Pytest, ruff lint/format,
  mypy i schema drift prolaze. Stvarni pinovani E5 test sada uključuje MCP stdio;
  postojeći CI ga pokreće na Windows/Linux i u Linux OS network namespace-u.
- Protokolski testovi proveravaju auto/legacy tok, scope/filter/limit greške i
  oporavak, relocation, network guard, BM25 bez ML importa i izvorne instrukcije
  kao nepoverljive podatke. Originalni plan zadržava isti SHA-256.

[Detalji i povezivanje](MCP.md). RF-008B nezavisna evaluacija odabranog LLM agenta
na reprezentativnim korpusima ostaje otvorena. Test setovi drugog agenta nisu
menjani. Naredni mrežni korak je RF-010 sa auth i izolacijom pre produkcione preporuke.


## Full-source benchmark integration and ingestion checkpoints

- Integrated the prepared 18,434-document snapshots and independent fixture tests;
  native questions/contexts stay local, with no label promotion or source changes.
- Added resumable per-document journals, bounded parser processes, optional PDFium,
  explicit legacy-text policies, cache-bound bundle builds, streamed chunk/ID work,
  and finite larger index/file capacities. See [SCALING.md](SCALING.md).
- Full local checks: 203 passed, 3 Windows platform skips with external-data and
  real-model checks enabled. New worker OS memory/deadline and resume checks pass.
- Actual default scan limits reject the large 3GPP/RFC inputs. A configured audit
  over all three complete collections is running under the 65 GB storage policy;
  completed audit counts and retrieval measurements will be reported separately.
- These engineering checks do not approve draft labels or complete the release gate.


## 2026-11-01 — Full inventory audit and resumable evaluation

The complete 18,434-source inventory was attempted without sampling. Kernel:
3,857/3,857 parsed; RFC: 9,854/9,854 parsed, with 9 PDF pages without extracted
text; 3GPP: 4,717 parsed PDFs and 6 extraction-permission failures, all retained
in the inventory. These are text-layer diagnostics, not semantic completeness.
Historical RFC decoding/escaping and permission-aware PDF retry were explicit;
original bytes and frozen labels remain unchanged.

Implemented bounded ingestion, streaming indexing, persistent build/vector/shard
checkpoints, optional sharded ANN and source-bound actual-engine evaluation.
Normalized local-only draft banks contain 2,723 mapped native source questions,
42 version-scoped variants and 240 supplementary questions. No label was promoted
to independently reviewed ground truth. Context negatives and quarantined spans
are excluded with explicit reasons.

Local full checks: **220 passed, 3 Windows filesystem skips**, including actual
pretrained E5 exact/ANN offline build, relocation, query and MCP. Ruff, formatting,
mypy and schema drift checks passed. This records software verification; full
scale retrieval measurements are a separate long-running workload.

CPU calibration on the local i7-1195G7 measured approximately 49 segments/s for
bucketed 350-character inputs (1,024-segment development sample, not corpus
throughput). An isolated Intel GPU feasibility probe was substantially slower
and was not adopted. No remote compute or paid service was started.


## 2026-11-02 — Frozen full-scale execution

Complete source-evidence preflight passed for 3,005 local cases and 4,347 frozen
source spans; all 14 original PDF reference representations were reconstructed
with pinned pypdf in bounded offline workers. This is alignment validation, not
independent annotation approval. Aggregate audit: [scale-ingestion-v1.json](benchmarks/scale-ingestion-v1.json).

Added a frozen-runtime sequential build/evaluation runner with per-step status,
private detailed query journals and aggregate numerical reports. A real tiny-corpus
end-to-end test executes all 15 stages, checks all methods, resumes without
requerying completed steps and rejects modified runtime files. Empty build-job
locks left by scan interruption can recover safely. Local checks now pass:
**223 passed, 3 filesystem skips**, plus lint/format/mypy/schema checks.

The full run uses local E5, 350/50 character chunking, four CPU threads and
explicit sharded ANN. Kernel remains held out from parameter tuning. Full-scale
builds/evaluations are long-running and not completed by software CI. Status is
under `data/benchmarks/scale-v1/runs/execution-v1`; see [SCALING.md](SCALING.md)
for reproducible invocation/resume commands. No paid compute was provisioned.


### Background execution and private result backup

The actual full kernel index contains 573,041 chunks for all 3,857 documents.
Dense construction has started and checkpoints committed row prefixes. A separate
online maintenance watcher saves only numerical progress/results to the private
`results/scale-v1` branch; the offline build/query workers remain network blocked.
The source model, GPU feasibility environment and earlier local model copies total
641,875,338 logical bytes outside the data root, below the conservative 5 GB
allowance. Data has a 60 GB cap and 15 GB free-space reserve.

Linux CI exposed a test-only capacity assumption: a tiny test also requested the
15 GB production reserve on a smaller runner disk. Tests now explicitly request
a zero reserve; the real benchmark retains 15 GB. Resume binds the chosen reserve
and remains compatible with the already-running frozen recipe.

Full local suite after maintenance changes: 225 passed, 3 Windows filesystem skips;
the additional numerical-progress sanitizer regression also passes. All required
lint, format, type and schema checks pass. CI is rerun on the final commit.
Large retrieval measurements remain in progress; no final quality claim is made.


## 2026-11-02 — Authenticated shared transport (RF-010A)

Implemented optional shared REST/stateless MCP HTTP over the unchanged engine,
offline pinned-key RS256 verification with issuer/resource/subject/read scope,
collection/document grants, strict Host/Origin and body limits, TLS controls and
shared use/context/doctor CLI clients. Client credentials come from an explicit
environment variable, never a URL or command argument; redirects and environment
proxies cannot receive them. Public-JWKS preparation creates no tokens/accounts
and performs no network access. The source remains local and no host was deployed.

Actual loopback REST/MCP tests cover minimal/exact/ANN, parallel scoped callers,
modern/legacy protocol, forbidden filters/context, invalid tokens, real TLS and
CLI parity. Full local verification: **237 passed, 3 filesystem skips**, plus
ruff, formatting, mypy and schema drift checks. [SHARED.md](SHARED.md) describes
the actual API and remaining RF-010B lifecycle/operational work.

The independent frozen full-corpus benchmark keeps running on its earlier verified
source snapshot. Its numerical-only private results watcher continues saving
checkpoint progress. Shared code changes neither its parameters nor its runtime.


## 2026-11-02 — Version control and first complete scale measurement

Implemented local shared deployment preparation, passive connection profiles,
atomic verified activation and reverified rollback with a ten-version history.
Smoke queries execute every supported method before a pointer update; queries
and evidence are not saved in deployment metadata. Server startup checks the
expected build ID. Existing processes retain their startup snapshot until an
explicit restart. Added a reviewable systemd example and manual restart/backup
procedure; no service/account/remote host was installed. Shared exact/ANN parity
now also passes with the actual pretrained E5 model locally and is included in
the two-OS real-model CI job.

Full local checks: **245 passed, 4 skipped** (three Windows filesystem cases and
the unavailable systemd syntax tool), plus lint/format/mypy/schema drift. Linux
CI performs native systemd syntax verification when the tool is installed.

The complete kernel bundle finished: 3,857 searchable documents, 573,041 chunks,
5,293.70 seconds build wall time and 1,109,544,960 bytes measured peak process RSS.
The first evaluation stopped on my incorrect assumption that kernel had a dev
split; its entire 120-question bank is intentionally held out in test. The
explicit scheduler-v2 repair preserved original recipe/runtime/case bytes and
the completed artifact, retained that failure in history and covered all 3,005
cases in 13 real stages / 9,015 method calls. No questions moved between splits.

Kernel measurement completed with 360 actual queries and zero retrieval errors.
Document Recall@5: BM25 0.600, dense 0.750, hybrid 0.725. Mean source-span coverage
is 0.055/0.171/0.123, and no case meets 80% coverage for every marked group. Full
marked spans range from 915 to 1,324 canonical characters (median 1,308). These
are draft-label component diagnostics, not answer accuracy or release approval;
parameters will not be tuned on this held-out result.
[Full report](benchmarks/scale-kernel-retrieval-v1.json).

The controller continued into all 9,854 RFC documents (1,976,868 chunks) and local
embedding; 3GPP follows automatically. Numerical-only results are saved on private
`results/scale-v1`. A process-scoped Windows system-activity helper is attached to
the current controller for the long run and releases its request on completion,
failure or controller exit. No persistent power plan was changed.


## 2026-11-02 — Retrieval quality work requested by the user

The user considers >=95% good and 99% excellent, and explicitly accepts correct
information from alternative sources. No such threshold is demonstrated yet.
Document Recall@5 and broad-context span coverage are not answer accuracy.

Implemented explicit section-aware chunks, a pinned local ONNX cross-encoder,
bounded candidate pools and an immutable `enhance` upgrade without re-embedding.
Raw BM25 remains available without loading ML, including on reranker bundles.
CLI, MCP and REST use the same request/engine; filters apply before inference.

Added separate question-bound minimal-fact annotations and complete-support
scoring with accepted alternative citations. Inspection found some original RFC
context windows miss the requested fact. Original cases/artifacts/runtime remain
unchanged. Separate local dev-only labels cover 80 questions, 42 facts, 60 source
spans; independent review eligibility is still zero. Details: [QUALITY.md](QUALITY.md).

A complete 9,854-source RFC lexical/reranker candidate with 1,000-character chunks
and 150-character overlap built in 827.70 s on the busy workstation. A frozen
paired raw/reranked comparison is running, using identical top-k=10, 16,000-char
budgets and fact labels. Numerical-only progress is saved to the private
[quality results branch](https://github.com/NemanjaZelic/RAGForge/blob/results/quality-v1/docs/benchmarks/quality-runtime-v1.json).
A separately frozen follow-up supports comparing the full balanced RFC bundle
once the original offline build publishes; it does not modify or restart that build.

Local full checks: **261 passed, 4 platform skips**, with all six actual pretrained
embedding/reranker exact/ANN offline integration tests passing. Ruff, formatting,
mypy (46 source files) and schema checks passed. Additional focused tests cover
queued offline execution and private-report redaction. Software checks do not
approve retrieval quality or promote any draft labels.


### Matched result and automatic next experiments

The matched RFC development comparison is complete: with the **same** 80 questions,
accepted fact annotations, top-k=10 and 16,000-character output cap, full accepted
fact support was **16/80 (20%)** for the original 350-character lexical index,
**29/80 (36.25%)** for 1,000-character chunks, and **36/80 (45%)** after reranking.
[Safe report](benchmarks/rfc-quality-dev-v1.json). This is an improvement in
verified support, not generated-answer accuracy, and remains far below the user
target with independent annotation review pending. Larger chunks consume more of
the same permitted text budget. No quality promotion was made.

Added `build --token-aware`: actual tokenizer limits split oversized sections
without dropping source characters. Tokenizer/prefix/budget hashes identify that
pipeline; old chunk IDs stay unchanged when disabled. The complete local checks
now pass **265 tests, 4 platform skips**, including actual pretrained exact/ANN
builds with the new option. The queued rebuild path also passes its focused
end-to-end test. Previous quality commit 2d38234 passed all six private CI jobs:
https://github.com/NemanjaZelic/RAGForge/actions/runs/41494567317.

Two offline follow-ups support autonomous continuation: first compare the fully
published original balanced RFC bundle with/without reranking; then rebuild all
RFC sources with 1,000-character section chunks, 150 overlap, actual token fitting,
ANN and reranking. The rebuild waits for the prior quality comparison to finish,
uses two CPU threads, and keeps the 60 GB aggregate / 15 GB free-space policies.
Frozen runtime, model/cache hashes and persistent checkpoints protect both jobs.
Only whitelisted numerical reports publish, after checking repository privacy.
The original full-scale build/evaluation is unchanged and continues independently.

A separate metadata-only routing probe is not promoted: document candidate
availability is not answer support, and no end-to-end gain was demonstrated.
No cloud host, model API, document upload, paid compute or public release was used.


### Source-equivalent support audit and parent-context candidate (2026-11-03)

All 80 existing lexical reranked development responses were reviewed against
actual returned text: 67 supply complete relevant information, 13 lack at least
one requested fact. The aggregate separates 36 complete literal matches from
44 AI judgments and zero independent/human reviews. This is a corrected semantic
assessment of unchanged responses, not a pipeline gain or achieved 95% target.
[Numeric-only review report](benchmarks/rfc-semantic-review-dev-v1.json).

Added a source-quoted review workflow with request/artifact/recipe fingerprints,
full-case denominators, proof/scope validation and no automatic quality approval.
A separate real-candidate/neighbor audit labels its oversized oracle pools as
ceilings, never answer accuracy. Original annotations and test splits are intact.

Implemented `recontextualize` and shared-engine parent mapping, reusing real
350-character dense vectors with 1,000-character source-identical context rows.
The full portable RFC candidate is verified locally as
`d0aed8d98597f97cace3685c6f5c8d2d8aae8e9dddd0d59ea9ff322dc503c141`
with 15 inventoried assets. Its creation used a 60 GB aggregate cap and a 15 GB
free-space reserve. The full development comparison is still running. Early
successes and regressions are both retained; no quality/default promotion occurred.

Current complete ordinary checks: 275 passed, 15 opt-in/platform skips, Ruff lint
and formatting, strict mypy over 49 files and generated-schema consistency.
Focused context tests cover exact/ANN, offline relocated CLI, permissions,
original-text citations, immutable bases, source mismatch and legacy build IDs.
Actual pretrained integration and external drift checks are running separately.
The original plan SHA-256 remains unchanged. Original scale and token-aware
rebuild jobs retain their own frozen runtimes/checkpoints.


### Topic-context checkpoint and completed control

The full parent-context experiment and semantic review are complete: 67/80,
with two improvements and two regressions relative to the prior 67/80 lexical
control. Literal accepted-fact support is 35/80. There is no net semantic gain,
so no quality/default promotion occurred. See the [paired safe aggregate](benchmarks/rfc-parent-review-dev-v1.json).

Added optional source-verified document titles in the manifest and common
reranker input. Verification binds each title to actual source lead text or
indexed heading metadata; old null-title identities remain unchanged. Offline
RFC title preparation matched 9,583/9,854 documents without reading questions.
The complete title-only 80-question experiment has a frozen runtime, verified
metadata/cache provenance and per-candidate score checkpoints; review is ongoing.

Current full local checks: **291 passed, 4 platform skips**, including all actual
pretrained offline CLI/MCP/shared checks, the source-title CLI path, external
label/split drift validation, Ruff, formatting, mypy (50 files) and schemas.
Checkpoint 2ff0ca4 passed all six Windows/Linux private CI jobs:
https://github.com/NemanjaZelic/RAGForge/actions/runs/41588028928.

A separately prepared pinned BGE reranker is experimental, not an adopted model;
initial matched probes did not improve without topic context. Single-passage
batching and bounded failed-download cleanup are covered by tests. Question-
independent acronym expansion is being diagnosed locally; its two-question
success is not a full-set quality claim and is not part of default retrieval.
The >=95% target and independent confirmation remain open.


### Full topic review, rejected acronym replacement and wider-context checkpoint

All 80 title-only development responses have complete source-quoted reviews:
70 supported, 10 incomplete (87.5%); five improvements and two regressions
against the 67/80 parent control. Literal complete-fact support is 41/80.

A separately declared top-50 / 48,000-character replay supplies complete
relevant facts for 79/80 (98.75%); it returns about 47,423 characters on average,
versus about 9,666 for top-10. The complete review separates 53 mechanical
matches from 27 AI judgments, with zero human/independent reviews. This is
larger-context retrieval support, not an approved 95% application accuracy
claim or a gain at the smaller output budget.

The full source-proven acronym query-replacement candidate achieved 69/80 and
regressed three previously supported cases while fixing two. It is not adopted.
Fixed a separate ambiguity bug where ordinary lower-case 'in'/'as' expanded as
technical IN/AS; staged patch application and budget/natural-word regression
checks passed before applying it to canonical source. Source grants scope
expansion before inference, and raw BM25 keeps its original query.

The immutable numeric checkpoint is saved on private branch
results/context-budget-dev-20261103, commit
dd776fe4b58e137eb65aff16517f3a27617b161a. It captures software state before the
case guard was applied: 293 tests passed, 4 platform skips, Ruff/format/mypy/schema
checks passed. Its historical pending-write fields describe that checkpoint.
A temporary automatic approval-service capacity failure has since cleared;
the patch, all completed reviews and local experiment archive are now on D.
The original 71-review ledger was retained as a checkpoint. All 298 current
tests and actual pretrained integration checks are running again.

A frozen offline controller is building the actual portable title-only
balanced candidate with a 60 GB aggregate storage cap and 15 GB free reserve,
then evaluates all 80 development questions through the packaged common
engine with top-k=50 and a 48,000-character ceiling. This includes actual
query embeddings/ANN and does not substitute cached results for engine calls.
Original full-scale/rebuild jobs and frozen annotations remain unchanged.


Current packaged checkpoint: full **294 passed, 4 platform skips**, including
actual pretrained offline integration and external frozen-bank drift validation;
Ruff/format, mypy over 51 source files and schemas pass. The case guard now has
its natural-word regression test in canonical source.

The title-only mapped balanced bundle is built and verified as
`5a69e9f37b77c1691a4855858906c3dd7c99682cf55710932d3dd5d9a378d9b0`: 15 inventoried
assets, 4,977,425,431 logical bytes, 9,583 verified source titles, no acronym
replacement bank. Both frozen actual-engine runs have started. The selected
top-50 / 48,000-character profile was locked before the 24 held-out questions
were annotated: 43 question-bound minimal facts, 44 source alternatives, source-
only AI draft with zero independent eligibility. Original annotations remain
unchanged and held-out outputs will not tune this profile. Their results are
not yet available or claimed.


### First frozen RFC test: target not met (2026-11-04)

The selected title-only portable engine completed all 24 frozen test queries
without retrieval errors at top-50 / 48,000 characters. Complete relevant fact
support is 21/24 (87.5%): 15 mechanical matches and nine AI source-quoted reviews,
including three incomplete cases. No human or independent approval is claimed.
The >=95% target is not met. Numeric-only results are retained in
`benchmarks/rfc-first-frozen-test-v1.json`; question text, sources and review
quotes remain local. The first result and labels remain frozen. Since the
failures have now been inspected, this split becomes diagnostic for future
changes, which require new unseen validation.

Actual packaged development evaluation is resuming at 67/80 checkpoints with
the original frozen runtime. A question-independent kernel context index has
finished: 3,857 source documents and 310 source-verified first headings; all
other headings were conservatively omitted. Kernel test questions remain
unopened for selection. Original scale evaluation is also resumed and saving
numeric checkpoints on its existing private result branch.

Software checkpoint b777859 passed all six Windows/Linux CI jobs, including
the real pretrained checks. These software checks do not establish retrieval
quality: https://github.com/NemanjaZelic/RAGForge/actions/runs/41608520401.


Actual development measurement is now complete: all 80 common-engine calls
finished without errors and all 80 contexts have source-quoted reviews, with
79 complete cases (53 mechanical, 27 AI). This agrees with the development
replay but does not supersede the failed 21/24 frozen test.
`benchmarks/rfc-actual-packaged-dev-v1.json` records safe aggregates.

The actual large-bundle stdio MCP example now accepts top-k, character budget,
CPU threads and a bounded per-response timeout (600 seconds by default instead
of 30). With socket/DNS blocked in both processes, it completed discovery,
search and context on the full bundle: 49 returned passages, 47,481 characters,
identical ordered chunk IDs, text and citations to CLI. Total wall time was
210.28 seconds including opening/verification; this is one adapter parity
query, not an isolated latency benchmark or agent-answer quality result.
See `benchmarks/rfc-full-mcp-parity-v1.json`.

Kernel source-only metadata was corrected to select the first H1 inside the
actual HTML main region rather than the navigation logo. Source hashes and
indexed source text verify 3,839 main headings; 18 remain omitted. The initial
310-heading metadata file remains unchanged for traceability. No kernel test
question participated in either preparation.

MCP example changes passed the full local check suite with actual pretrained
models and external dataset drift checks: 294 passed, four platform skips,
Ruff lint/format, mypy over 51 source files and schema drift checks all pass.


### Bounded supplemental planning candidate (2026-11-04)

All 80 development cases and all four controls have complete wide-context
source-quoted audits: title control 79/80; candidate-only aliases 80/80;
facets/references 79/80; combined 80/80 (55 mechanical, 25 AI, zero human).
The original top-10 profile has no newly approved semantic score. Numeric-only
results are in `benchmarks/rfc-supplemental-planning-dev-v1.json`.

Implemented optional `--plan-queries` / manifest facets-v1 in the shared engine,
with original-query scoring, scoped source hints, explicit document references,
bounded question facets, a 400-pair total cap and deterministic branch-rank
fusion. Legacy IDs/defaults are retained. Twenty-four focused tests pass,
including exact/ANN portability, raw BM25, grants before passage inference,
original scorer text and adversarial aggregate fan-out. Full checks are running.

The candidate source/runtime, profile, 3,839 verified kernel main headings and
68 explicit uppercase acronym definitions were frozen before individual kernel
test inspection. Actual RFC branch-parity checks and all 80 real engine calls
are being started alongside source-only portable kernel packaging. These are
not yet claimed as finished measurements or independent target confirmation.

The earlier MCP/actual-engine checkpoint 6d81f7b passed all six Windows/Linux
CI jobs: https://github.com/NemanjaZelic/RAGForge/actions/runs/41805218395.

The optional planning implementation passed full local checks with actual
pretrained models and external bank drift checks: 300 passed, four platform
skips, Ruff lint/format, mypy over 52 source files and schema drift all pass.
The frozen planned portable artifacts are built: RFC
`218f3e7c70d33f02e3a6f26f2b9c2e214ce04db5ae8f768694a58622911fa8f7` and kernel
`e4c7a98b7dfe1323f2cc7ba23a45767ae6e29d20fa3afb22b5b042de009b3eee`.
Actual branch parity, source-only kernel annotation and complete actual-call
measurements remain separate pending steps.


The planning commit fc35320 passed all six Windows/Linux CI jobs, including
the real pretrained/network-isolated tests:
https://github.com/NemanjaZelic/RAGForge/actions/runs/41809368098.
GitHub remains private; a transient push server error was retried successfully.

All five actual large-RFC branch probes match the selected prototype's ordered
chunk IDs and citations. All 120 kernel questions were locked after runtime
selection and before individual inspection. Their source-only minimal fact bank
contains 72 distinct facts and 165 fact assignments; every question hash and
source span is validated. The fact bank and explicit requirements were frozen
before any returned kernel contexts were reviewed. Original cases are unchanged;
strict independent eligibility and human review counts remain zero.

Kernel actual inference and source-quoted review are in progress. Safe lock,
branch-parity and partial counts are in `benchmarks/kernel-planned-test-lock-v1.json`,
`benchmarks/rfc-planned-branch-parity-v1.json` and
`benchmarks/kernel-planned-test-partial-v1.json`. Pending cases remain in the
120-case denominator; no final accuracy or >=95% confirmation is claimed.
One tab-width question is conservatively incomplete: related eight-character
indentation advice does not explicitly establish the frozen tab-width fact.
Equivalent PM facts in other correctly scoped sources are accepted with quotes.

On this 12 GB host actual heavy inference is now serialized. All 39 completed
RFC dev records were checkpoint-backed and SQLite quick-checked before its
worker stopped; the exact frozen 50/48k/2-thread recipe is queued to resume
automatically after the kernel test. Full-corpus source builds remain running
with temporary process-only lower scheduling priority. No global power or
thread settings changed; concurrent, resumed wall times are not isolated speed
benchmarks.


2026-11-04 frozen kernel result: all 120 actual packaged queries completed with
zero retrieval errors. Source-quoted review supports 112/120 complete minimal
fact sets (93.3333%): 93 mechanical matches and 27 AI-reviewed cases, zero
human reviews. Eight cases remain incomplete; the 95% target is not met.
The original first result is preserved in benchmarks/kernel-first-frozen-test-v1.json.
Kernel questions are now consumed; future improvements on this set are diagnostic
regressions, not a fresh independent test. All 80 actual RFC dev calls have
also completed and their source-proof review is being finalized.

Actual RFC development measurement is complete: 80/80 calls, zero errors,
80/80 source-supported minimal fact sets (55 mechanical and 25 AI, no human
review). Numeric report: benchmarks/rfc-planned-actual-dev-v1.json. This
confirms selected prototype behavior in the portable engine, not independent
quality approval. The consumed 24-case RFC diagnostic is queued next.


Optional section-start-v1 context completion (2026-11-04): structured short
sections of at most four chunks can supply their first chunk and physical
successor. The first 20 hits and each section's sole returned representative
are protected. At most eight lower-ranked same-document exchanges preserve
the output count, document counts, exact source text/citations and character
budget. Document grants apply before metadata/body access. Metadata reads are
bounded to 20,000 rows / 2,000,000 characters per document; no extra neural calls.
Raw and --no-rerank retrieval keep their behavior. Use recontextualize
--complete-sections to opt in; absent configuration preserves old build IDs.

The selected production algorithm exactly matches deterministic replay of all
120 consumed kernel results and leaves all 80 actual RFC dev contexts unchanged.
Source proofs establish at least 114/120 kernel cases (95%); all previous 112
complete cases retain their proofs, and two additional full frozen fact spans
are covered. Six cases remain unconfirmed. This is development diagnostic
selection, not a fresh unseen test or independent human approval. See numeric
benchmarks/section-context-diagnostic-v1.json. Actual new-bundle adapter probes
and complete required checks are pending.

The consumed RFC 24-case actual diagnostic is complete: 23/24 supported,
17 mechanical + 7 AI reviews, zero errors, no independent human approval.
The JWT allowlist/header-versus-operation requirement is still unsupported.
Correctly scoped equivalent BGP/BFD source explanations are accepted with
quotes; original first frozen 21/24 is unchanged. This is diagnostic, not a
new test. A separate 16-case previously unused tuning split retains its
original split and has a source-only minimal fact bank frozen after runtime
selection, before output inspection. Its first actual calls are queued
after the serialized actual section-artifact adapter checks.

All three actual section-artifact engine probes match replay IDs, exact text
and citations. Actual CLI and real subprocess/stdio MCP also match; the MCP
context fetch succeeds with socket/DNS denied. The frozen runtime remains
unchanged; a repository-only SQL literal line split has an identical AST.
Verified new artifact identities and numeric adapter results are recorded in
benchmarks/section-artifacts-v1.json and section-artifact-adapter-parity-v1.json.
These are adapter checks, not independent answer-quality measurements.

Section completion final local checks: 307 passed, 4 Windows/platform skips,
zero warnings; actual pretrained E5/reranker and opt-in frozen external-bank
drift checks enabled. Ruff lint/format (166 files), mypy (53 source files)
and schema drift checks all pass. First unused-split source review remains
in progress; no complete validation or release approval is claimed yet.


2026-11-04 completed section-runtime validation: all 16 actual queries on the
previously selection-unused RFC tuning split contain all frozen requested facts;
zero retrieval errors. Nine are mechanical full-span matches and seven are
source-quoted AI semantic reviews, including correct alternative DNS/HTTP
sources. There are eight question families and no independent human reviews.
The original split remains tuning; earlier raw-baseline split execution is
explicitly disclosed. Runtime and minimal fact bank were frozen before outputs;
no settings or expected facts changed during this run. The observed 16/16 is
not a cross-domain 99% guarantee or independent release approval.
Numeric report: benchmarks/rfc-section-first-unused-tuning-validation-v1.json.

The code commit cfcdcc5 passed all six Windows/Linux CI jobs, including pinned
pretrained models and Linux OS network isolation:
https://github.com/NemanjaZelic/RAGForge/actions/runs/41825162622.
Local full checks: 307 passed, four platform skips, no warnings, lint/format,
53-file type check and schema drift all pass. Engine/CLI/actual stdio MCP parity
also passes. The first frozen kernel 112/120 and RFC 21/24 results stay unchanged;
subsequent consumed-set diagnostics are kernel >=114/120 and RFC 23/24.
Independent quality annotation, agent-generated answers and PDF quality remain
open; neither development diagnostics nor the 16-case validation close them.


2026-11-04 version-two checkpoint: query-only technical source-stem routing
and additional explicit combine/compare/distinguish facets change 16 kernel
plans and one RFC plan. Fresh real model inference was performed for those
17 cases; unchanged plans use source-verified exact-context replay. No runtime
question/answer lookup or label-derived routing is introduced. The original
400-pair budget and 50/48,000 output profile remain unchanged. The observed
maximum is 314 pairs. The narrow planner supports 117/120 kernel cases; the
composed short-section boundary policy supports 118/120 (93 mechanical,
27 AI reviews including two incomplete cases). RFC remains 119/120 across all
120 consumed cases, with no lost prior support. Original frozen first results
and minimal fact banks are retained. This is diagnostic selection, not a new
independent quality confirmation; human review count remains zero.

Production helpers match the frozen selected prototypes for all 240 existing
cases. Legacy context behavior and both existing base artifact identities are
also exactly preserved. New policies are opt-in via recontextualize
--query-planning facets-v2 --section-context section-start-v2. Existing boolean
flags continue selecting version one. One bounded cross-document exchange may
complete a short section missing only its first chunk; first 20 hits, character
limit, document grants/caps and the sole section representative stay protected.
At most eight documents / 32 metadata groups / eight exchanges are considered.

All required local checks pass: 321 tests, four platform skips, no warnings,
Ruff lint/format (171 files), mypy (54 source files), schema drift and 27 focused
checks. Actual large version-two bundle/CLI/MCP probes are the next step.
Safe numeric reports: planning-and-boundary-v2-kernel-diagnostic.json,
planning-v2-rfc-diagnostic.json and production-v2-parity.json under benchmarks/.

The previous terminal-owned large corpus workers were no longer active at the
start of this continuation. A native WMI-brokered one-shot supervisor has now
been observed advancing the full RFC build from 323,584 to at least 352,256
of 662,398 chunks. It installs no service or recurring task. The maintained
scripts/start_background_benchmarks.ps1 entry point has frozen-input preview,
private aggregate publication choice, duplicate-controller protection, local
status/logs and process-scoped sleep prevention. Native preview/parser and
refusal of duplicate live controllers were checked. Current active workers
remain under the equivalent local prototype supervisor to avoid restarting
healthy runs. [Usage and limitations](BACKGROUND-BENCHMARKS.md).


2026-11-04 portable version-two checkpoint completed: both kernel and RFC
artifacts verify with 16 inventoried files each. Three fresh large-kernel
engine probes, actual CLI and actual subprocess/stdio MCP match frozen expected
ordered IDs, exact source text and citations; MCP context fetch succeeds.
Socket/DNS calls are denied during the probes. Numeric artifact identities and
results are in benchmarks/production-v2-artifacts.json and
production-v2-artifact-adapter-parity.json. These are consumed-case adapter
checks, not additional independent quality cases.

Code d64287d passed all six Windows/Linux CI jobs, including real pinned models:
https://github.com/NemanjaZelic/RAGForge/actions/runs/41906129078.
The verified code is fast-forwarded to private main. Two duplicate derived
planning packages were retired after complete asset/inventory/source identity
comparison against retained section packages. Exact old manifests, a guarded
restorer and numeric receipts remain local; 6,167,136,633 bytes were reclaimed
before allocating the new versions inside the same storage cap. Original
sources, fact requirements, first measurements and review proofs are retained.

Two narrow title-only routing feasibility probes did not yield additional
supported context and are not adopted. A new source-only experimental coarse
index embeds verified document titles and leads using the same pinned E5 model.
It does not read question/answer banks or change the selected production recipe.
Its quality and resource effects still require measurement; current diagnostic
support remains kernel 118/120 and RFC 119/120, with independent validation open.


2026-11-04 additional source-family validation: 16 newly source-authored English
questions from eight deterministically sampled, previously unused source families
contain all 33 locked minimal facts in the actual returned contexts. Eight named
kernel documentation areas contribute one source and two questions each; sources
with 6-60 chunks are ordered by SHA-256 after excluding all existing question
source evidence. Questions use the first five source chunks. Source requirements,
questions and selected d64287d runtime were frozen before retrieval outputs.
All 16 actual offline queries completed with zero errors, unchanged 50/48,000
limits, two threads and at most 317 of 400 reranker pairs. Every original minimal
quote is present in its source-identity matched returned passage, and all full
proof paragraphs received an explicit AI meaning/scope audit. There are zero
independent human reviews. This small clustered, early-source English draft does
not establish representative PDF/multilingual/agent accuracy or a 99% guarantee.
First-result hashes, exact counts and limitations:
benchmarks/kernel-first-additional-source-validation-v1.json.

The selected production recipe remains unchanged by the unadopted semantic
routing experiment. A native one-shot local queue waits for the validation
worker to exit, resumes the source-only descriptor checkpoint, then runs six
consumed-case feasibility probes. Child imports and all hash guards now use the
same frozen source snapshot, isolating the experiment from further development.
It installs no service/recurrence, uploads no data and preserves original limits.
Local status: .cache/semantic-routing-queue-v2-status.json. Descriptors use
substantive source passages rather than navigation-only leads. Previous partial
preparations remain separate and are not quality results. The kernel checkpoint
resumes at 320/3857 documents. No semantic-routing quality gain is claimed yet.

Generated passive agent instructions now specify hybrid search with top_k=50
and max_output_chars=48000 for balanced bundles that enable both query planning
and section completion. Matching structured request recommendations accompany
the collection metadata. Other bundles retain their prior instructions; no
agent host configuration or existing bundle is installed/modified. Fifteen
focused integration checks pass. Complete local checks also pass: 313 tests,
14 skips (ten opt-in pretrained-model adapter checks and four platform checks),
Ruff lint/format (171 files), mypy (54 source files) and schema drift. External
frozen-bank drift checks are enabled. Actual large-bundle passive integration
generation verifies matching wide limits and the exact bundle target; its three
files stay local with no agent host installation. Numeric result:
benchmarks/production-v2-wide-agent-integration.json. The 16 new actual model
queries ran against the frozen selected retrieval runtime; the new generator
change is also queued for real-model Windows/Linux CI.
