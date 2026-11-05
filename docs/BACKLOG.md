# Zadaci i uslovi prihvatanja

Ovo je operativni redosled; nije zamena originalne specifikacije niti procena roka.

## F0 — Priprema (ovaj korak)

- [x] Original plana sačuvan byte-for-byte uz SHA-256.
- [x] Pregled plana i evidentirane odluke/odstupanja.
- [x] Python paket, CLI help/version/doctor, ugovor engine-a i manifest modeli.
- [x] Generisane JSON šeme i testovi validacije.
- [x] Originalni mini-korpus i 20 autorski označenih razvojnih upita.
- [x] Izolovani alati, cache i okruženje na D; zaključane zavisnosti.
- [x] GitHub Actions konfiguracija za Windows i Linux.
- [x] Prvo izvršavanje CI na privatnom GitHub repo-u; Windows/Linux i
  Python 3.11/3.13 prolaze, uključujući RF-002. Rezultati su u PROGRESS.md.

Lokalna validacija i precizni rezultati su u PREPARATION.md.
F0 ne znači da je retrieval MVP gotov.

## F1 — Lokalni v0.1: mešani formati, PDF i hybrid

Usvojeni release uslovi: [RELEASE-SCOPE.md](RELEASE-SCOPE.md).
Tekstualni PDF i dense/hybrid su obavezni pre v0.1 release-a.
BM25-only rezultat je interni međukorak ili eksplicitni minimal profil.

### RF-000 — Proširiti Phase 0 ugovore za v0.1 [završeno]

Implementirano 2026-11-01; 56 testova i sve lokalne provere prolaze.
Ugovori ne izvršavaju retrieval. Zadatak: balanced manifest, identitet i
lokalno pakovanje query modela, dimenziju/metriku dense indeksa, capability-je
bm25/dense/hybrid i search-method izbor. Sačuvati minimal profil.
Done: modeli, generisane šeme, primeri i testovi su usklađeni; ništa ne tvrdi
da trenutna implementacija već pretražuje ili gradi indekse.

### RF-001 — Bezbedan scan i identitet [završeno]

Implementirano 2026-11-01: API i stvarna `scan` CLI komanda, hash u blokovima,
limiti po fajlu/zbiru/broju unosa. PDF je ovde samo otkriven kao ulaz; provera
teksta i parser pripadaju RF-007. 71 test prolazi, 3 platform/privilege skip-a;
Windows junction test prolazi.

MD/TXT/HTML i PDF sa tekstom; sortirane relativne putanje; deterministički document ID; odvojeni
content hash; eksplicitna politika symlink-a i Unicode/case kolizija.
Done: testovi duplih sadržaja, praznih fajlova, traversal-a, velikih fajlova i
ponovljenog skeniranja. Greške se ne pretvaraju tiho u uspešan build.

### RF-002 — Parser i chunker [završeno]

Implementirano 2026-11-01: MD/TXT/HTML, verifikovani source bajtovi, zajednički
TextBlock za budući PDF adapter, tačni fizički redovi za MD/TXT i null redovi
za HTML, bounded chunking i stvarna chunk CLI komanda.
102 testa prolaze, 3 platform/privilege skip-a. Detalji: [PARSING.md](PARSING.md).
PDF adapter ostaje odvojeni obavezni RF-007.

MD naslovi, TXT i HTML tekst bez script/style sadržaja; jasna encoding politika;
1-based source lokacije kada su stvarno poznate. Deterministički chunking sa
ograničenom dužinom, overlap-om i code-block slučajevima. Deliti normalizovan ulaz i PDF provenance
iz RF-007; parser adapter nije poseban retrieval engine.
Done: ponovljeni build daje iste identitete i tekst; citati odgovaraju originalu.
Ne tvrditi tačne HTML redove dok ne postoji proverena provenance mapa.

### RF-007 — Obavezni tekstualni PDF u v0.1 [parser implementiran]

Implementiran parser, page provenance/status, limiti i eksplicitni partial tok;
113 lokalnih testova prolazi, 3 platform skip-a. Realni RFC 9110 pilot:
194 extracted stranice. [Detalji i granice](PDF.md). Retrieval benchmark
sa stvarnim PDF-om ostaje uslov RF-006 pre v0.1.

PDF parser je release zahtev, ne dodatak posle v0.1.
Ekstrahovati postojeći tekst, čuvati fizičke 1-based stranice i proveriti
tipične tabele/kod/više kolona. Ograničiti memoriju i prijaviti delimičnu obradu.
OCR ostaje kasnije prema eksplicitnoj odluci korisnika; skenirani delovi se
prijavljuju, bez tihog preskakanja ili automatskog OCR download-a.
Done: stvarni PDF fixtures i najmanje jedan realni PDF u v0.1 benchmark-u,
tačne stranice u citatu i dokumentovane granice parsera.

### RF-003 — SQLite FTS5 i retrieval [završeno]

Implementirano: stvarni SQLiteEngine, index/search/context razvojni CLI,
read-only retrieval, literal query, scope/filter/output granice i kontekst.
132 lokalna testa prolaze, 3 platform skip-a. [Detalji](RETRIEVAL.md).
Postoje mini BM25 baseline i tri realna PDF page probe-a; balanced bundle
i širi RF-006 benchmark još nisu gotovi.

Jedna kolekcija; metadata i FTS u jednoj bazi; parametrizovan SQL; bezbedna
normalizacija običnog upita; veći javni score znači bolji rang.
Done: retrieve vraća ugovorene rezultate; prazna i nepostojeća kolekcija imaju
jasno ponašanje; apostrofi/operatori/ćirilica/dijakritici ne ruše query.

### RF-009 — Obavezni dense i hybrid u v0.1 [implementirano]

Implementirano: lokalni ONNX CPU provider, NumPy exact cosine backend i RRF
nad istim SQLite izvorima. Izmerena dva pinovana kandidata; početni višejezični
izbor je E5-small, privremeno do reprezentativne evaluacije. Offline model
build/query radi na Windows/Linux CI. [Detalji](LOCAL-BUNDLES.md).
Reprezentativne test setove priprema drugi agent; ovaj korak ih ne menja.

Jedan CPU query embedding model, jedan embedded dense backend i RRF nad
istim kolekcijama/izvorima kao BM25. Balanced je podrazumevani build profil.
Izbor backend-a/modela potvrditi pilotom i Windows/Linux kompatibilnošću.
Done: pravi semantic/hybrid upit bez mreže, lokalno dostupan model,
parafrazirana golden pitanja i poređenje BM25/dense/hybrid pod istim uslovima.
Ovaj zadatak je premešten iz F2 u F1; reranker i više modela ostaju kasnije.

### RF-004 — Builder i integritet bundle-a [završeno]

Implementirano: staging build, no-replace publikacija na Windows/Linux,
potpun inventar, checksum i cross-component provere; nema automatskog download-a
ili deploy-a. Testovi odbijaju kvarove, lažne inventare i racing prazni cilj.
Odluka o licenci samog projekta i korpusa ostaje NOASSERTION.

Zatvorena SQLite baza, dense indeks i lokalno query-model pakovanje za balanced;
potpuni inventar, licence/verzije/hash-evi; build u staging-u; bez prepisivanja
postojećeg paketa po defaultu. Minimal profil ostaje manji BM25-only paket.
Done: kvar fajla, lažni hash, neočekivana putanja i nepoznata verzija se odbijaju;
neuspešan build ne kvari stari paket; nema WAL/SHM zavisnosti u izvezenom bundle-u.

### RF-005 — Stvarni build/use/context CLI [lokalni tok završen]

Implementirano: build/use/verify/context nad bundle engine-om, balanced/hybrid
default i eksplicitni bm25/dense izbor. --compute/--mode prihvataju samo local.
Kopirani balanced paket prolazi socket/DNS-blocked build/use sa stvarnim
pretrained modelom. Linux CI dodatno prolazi unshare --net.
MCP/shared/cloud tokovi ostaju F2 i naredne faze.

Implementirati komande iz plana nad istim engine-om, stabilan JSON na stdout,
dijagnostiku na stderr, nedvosmislene exit kodove.
Dodati --search-method hybrid|bm25|dense; balanced default je hybrid.
BM25 izbor nad balanced paketom ne učitava model i ne zahteva rebuild.
Nedostajući model kod hybrid upita daje grešku, bez tihog fallback-a.
Done: docs → build → use → fetch_context radi u kopiranom bundle-u na drugoj
putanji; build compute i runtime mode nezavisni; bez HTTP servera.

### RF-006 — Offline E2E i benchmark stvarnog proizvoda

20 početnih upita koristiti kao razvojnu proveru. Izračunati Recall@5/MRR@10
za označene pozitivne upite; negativne prijaviti odvojeno. Zabeležiti corpus i
config hash, verzije i merne uslove; ne izmišljati univerzalni quality prag.
Pre v0.1 uporediti BM25/dense/hybrid na istom golden skupu i uključiti stvarni
PDF sa page dokazima. Testirati da BM25 upit nad balanced bundle-om ne učitava
embedding model, a hybrid offline upit koristi lokalni model i dense indeks.
Done: pravi CLI podproces sa zabranjenom mrežom napravi i pretraži bundle;
izveštaj sa citatima i latencijom; isti test na Windows i Linux CI.
Za potpuno mrežno izolovan OS test dodati poseban Linux job pre v0.1 release-a.

Detaljna metodologija: [TESTING-PLAN.md](TESTING-PLAN.md).

Mini razvojni baseline i BM25/dense/hybrid upoređenje postoje na istim
postojećim pitanjima. OS offline build/query provera sada je u Linux CI.
To ne zatvara širi RF-006: reprezentativni korpusi, nezavisni evidence labels
i final holdout pripadaju zasebnom test-set poslu drugog agenta.

- [x] RF-006A: mini-korpus/20 pitanja i stvarni bundle build/query E2E su
  implementirani, uključujući kopiranje, BM25 bez ML imports i stvarni offline
  pretrained-model upit na Windows/Linux. To nije dokaz kvaliteta na realnim docs.
- [ ] RF-006B: odabrati i pinovati 3 raznovrsna realna korpusa, zabeležiti izvore,
  hash-eve i licence; napraviti 30 pilot pitanja po korpusu sa proverom oznaka.
- [ ] RF-006C: izmeriti proizvod na pilotu i proširiti ka 5 korpusa sa po
  50–100 pitanja; ukupno dozvoljen raspon je 3–7 korpusa.
- [ ] Izbor po kategorijama veličine/formata/urednosti/jezika, uz ponovljivo
  nasumično uzorkovanje; bar jedan ceo korpus van razvoja opštih default-a.
- [ ] Odvojeni tuning i završni upiti, grupisane parafraze, oznake izvornog
  dokaza nezavisne od chunkinga i pregledani slučajevi bez odgovora.
- [ ] Izveštaj po korpusu: retrieval, stvarni dokazi/citati, ingestion gubici,
  memorija/latencija/build i uspeh CLI toka; agent test dolazi uz RF-008.
- [ ] Isti evaluator za BM25 baseline, dense, hybrid i RF-013 optimizer, bez ulepšavanja
  rezultata povećanjem outputa ili ponovnim podešavanjem na završnom testu.

Reprezentativne korpuse i golden skupove priprema drugi agent u zasebnoj isporuci.
Pilot ne blokira prvi mali demo; realni benchmark je potreban pre širih
tvrdnji o kvalitetu proizvoda i automatskoj optimizaciji.

## F2 — Agent-ready nad postojećim v0.1 hybrid engine-om

RF-008A implementirano: MCP stdio nad istim engine-om, validan skill generator
i odvojen pasivni config. Detalji i granice: [MCP.md](MCP.md).
Done: stvarni MCP klijent poziva search/context; primer agenta citira izvor;
generisanje ne menja korisnički agent config bez izbora. Testirati hybrid
podrazumevani tok i eksplicitan BM25 izbor. Dense/hybrid već pripadaju F1.

RF-008B ostaje otvoren: nezavisni LLM agent i reprezentativna evaluacija citata/
uspeha zadatka. Stvarni deterministički MCP klijent nije zamena za taj benchmark.

## Posle toga

RF-010A: implementirani shared REST/stateless MCP HTTP, isti engine/CLI klijent,
JWT issuer/resource/subject/scope provera, document grants, TLS, Host/Origin/body
limiti i stvarni minimal/exact/ANN parity testovi. [SHARED.md](SHARED.md).
RF-010B: implementirani pasivni deploy/connection profili, kontrolisana atomska
aktivacija sa smoke upitima i ponovna provera pri rollback-u. Dodat je systemd
primer i dokumentovan restart/backup postupak. Pokrenuti server koristi startup
snapshot do eksplicitnog restarta; nema automatskog hot-reload-a ili brisanja.
RF-010C ostaje: stvarna instalacija i provera sa dva udaljena uređaja, izbor hosta/
issuer-a/sertifikata i backup automatizacija. Nije kreiran production host.
RF-011: SSH runner; isti builder, preuzimanje i kontrolisani cleanup.
RF-012: jedan compute provider sa ownership evidencijom i troškovnim recovery-jem.

### RF-013 — Opciono podešavanje parametara prilagođeno hardveru

Specifikacija: [OPTIMIZATION-PLAN.md](OPTIMIZATION-PLAN.md); proširenje Faze 6.
Zavisi od RF-003/RF-004/RF-006/RF-009; koristi već podržani balanced/hybrid profil. Lokalna verzija ne
zavisi od cloud/SSH/serverless implementacije i ne blokira lokalni v0.1.

- [ ] Četiri nivoa obima: first try/light/high/max, bez fiksnih sati.
- [ ] Stvarna kalibracija CPU/GPU/RAM/I/O i korpusa, ETA raspon i nesigurnost,
  verzionisan plan kandidata i automatski budžet sa rezervom.
- [ ] Max budžet najmanje 8 h čak i na najbržem hardveru; kraći korisnički
  plafon se odbija. Raniji završetak zbog kvaliteta zahteva iscrpljen ceo
  prostor ili unapred definisanu proverenu konvergenciju.
- [ ] Kratka stagnacija ne završava Max pre 8 h; prekid/greška/istek budžeta
  nisu optimalnost. Testovi sa virtuelnim satom potvrđuju sve razloge završetka.
- [ ] Prvo osnovni upotrebljiv paket, zatim odvojeni optimize run/status/resume.
- [ ] Prva isporuka first-try/light nad postojećim balanced/hybrid profilom,
  uz podršku minimal/BM25 profila; potom high/max i širi scheduler.
- [ ] Metrike baseline-a, odvojen tuning i zaključan završni test; isti top_k,
  output limit i merna konfiguracija; oznake ostaju validne pri novom chunkingu.
- [ ] Ponovna upotreba verifikovane kalibracije, finalizacija u proceni i
  ponovno merenje pri promeni hardvera; bez tihog proširenja budžeta.
- [ ] Jeftine promene prvo, cache i postepeno testiranje; promena chunkinga/modela
  planira stvarnu cenu reindeksiranja i zahteva proverene izvore.
- [ ] Deadline worker-a, checkpoint i nastavak sa preostalim ukupnim budžetom.
- [ ] Izveštaj pokušaja i metrika; bez dokaza nema tvrdnje o rastu relevantnosti.
- [ ] Ako nema potvrđenog boljeg rezultata, postojeći bundle ostaje aktivan.
- [ ] Novi bundle prolazi postojeći integrity/contract test; nema promene API-ja,
  automatskog cloud compute-a, prenosa podataka ili instalacije konfiguracije.

Done: pravi optimizer testira stvarne konfiguracije, daje ponovljiv izveštaj,
poštuje budžet i bezbedno se nastavlja. CI koristi kratke testne budžete,
ne višednevne poslove. Ovo je planiran zadatak; nije implementiran.


RF-014: jedan serverless BM25 PoC sa merenjima i eksplicitnom matricom podrške.

## Odluke koje čekaju podatke ili vlasnika projekta

- Licenca javnog projekta: Apache-2.0 ili MIT prema originalnom predlogu.
- Realan reprezentativni korpus, jezici i ciljevi kvaliteta/veličine/latencije.
- Prvi agent za podršku uz generic MCP.
- Početni pilot bira E5-small i exact cosine; potvrda kvaliteta sledi na novom test setu.
- Mrežni/cloud provider se ne bira za F0/F1.


## RF-006Q — User-requested retrieval quality improvement (active)

User target: >=95% good, 99% excellent, measured on relevant correct information
rather than exact filename agreement. [Implementation and measurement](QUALITY.md).

- [x] Preserve original benchmark and distinguish document recall from answer support.
- [x] Support question-bound, source-verified fact alternatives and complete multi-fact scoring.
- [x] Separate local draft repair for all 80 RFC dev questions; independent eligibility remains zero.
- [x] Section-aware chunks, actual-token-budget splitting, bounded local reranking, explicit raw baseline.
- [x] Verified new-version reranker upgrade without re-embedding the original index.
- [x] Frozen offline comparison driver, same top-k/context budget, checkpoint/tamper tests.
- [x] Matched RFC lexical comparison: complete accepted fact support 16/80 -> 29/80 -> 36/80.
- [ ] Complete full balanced comparisons and select candidates on development/tuning data.
- [ ] Independently review minimal facts, paraphrases, equivalent sources and version scope.
- [ ] Confirm >=95% on a locked independent fact-support evaluation; generated-agent answers
  require the separate RF-008B benchmark. No threshold has been achieved or approved yet.


RF-006Q follow-up (2026-11-03): all 80 lexical reranked development contexts
received a source-quoted semantic audit (67 supported, 13 incomplete; 44 AI
judgments, 36 mechanical matches, zero independent reviews). This corrects the
assessment of equivalent information without claiming a retrieval improvement.
Implemented optional source-matched child/parent bundles, scope/provenance and
legacy-identity tests; full RFC candidate evaluation is in progress. >=95%
confirmation, independent annotation review and generated-agent evaluation remain
open. Baseline artifacts and held-out questions remain unchanged.


RF-006Q context-budget follow-up: source titles completed the full development
review at 70/80 with top-10, and a separate top-50 / 48,000-character replay
reached 79/80 at about five times the returned text. This has zero independent
reviews and does not fulfill the locked independent quality gate. Source-proven
acronym query replacement regressed to 69/80 and is not adopted. Its independent
case/permission correctness fixes are implemented. Frozen actual portable-bundle
evaluation is now running; selection within the smaller budget, adapter parity,
independent annotations and generated-agent answer checks remain open.


RF-006Q supplemental follow-up (2026-11-04): the first frozen RFC test returned
complete relevant facts in 21/24 and did not meet the target. Its labels/result
are retained; subsequent use is diagnostic. A new 400-pair bounded hybrid
planning candidate reaches 80/80 on the fully reviewed wide-context dev
experiment (55 mechanical, 25 AI, no independent review). It is implemented as
an optional shared-engine configuration, with actual packaged evaluation and
a source-only prepared, previously uninspected kernel test still pending.
No release quality checkbox is closed by the development score.


2026-11-04 frozen kernel result: all 120 actual packaged queries completed with
zero retrieval errors. Source-quoted review supports 112/120 complete minimal
fact sets (93.3333%): 93 mechanical matches and 27 AI-reviewed cases, zero
human reviews. Eight cases remain incomplete; the 95% target is not met.
The original first result is preserved in benchmarks/kernel-first-frozen-test-v1.json.
Kernel questions are now consumed; future improvements on this set are diagnostic
regressions, not a fresh independent test. All 80 actual RFC dev calls have
also completed and their source-proof review is being finalized.

RF-006Q section-context checkpoint: software and real CLI/MCP parity pass;
consumed kernel >=114/120 and RFC 23/24; first selected-runtime validation on
16 previously selection-unused tuning questions supports all 16 (nine mechanical,
seven AI, eight question families, no human review). Observed local threshold
reached; independent quality/agent/PDF gates remain open. First results retained.

RF-006Q v2 checkpoint: 118/120 consumed kernel contexts supported, RFC119/120
preserved; 240-case production/legacy parity and 321 software tests pass.
Version-two large portable-bundle probes, new independent/agent/PDF validation
remain open. Existing first results and source-fact requirements are unchanged.


RF-006Q v2 artifact checkpoint: both real portable artifacts verify; actual
large-kernel engine, CLI and stdio MCP parity probes pass offline. All six
Windows/Linux CI jobs for d64287d succeeded and private main is fast-forwarded.
The two consumed kernel misses and one RFC miss remain; source-only semantic
document routing is an unadopted experiment. Independent/agent/PDF quality
gates remain open. Numeric reports: production-v2-artifacts.json and
production-v2-artifact-adapter-parity.json under benchmarks/.


RF-006Q additional-family checkpoint: first selected-runtime validation supports
all 16 newly drafted questions / 33 locked facts from eight previously unused
source families. Source-quoted mechanical checks and explicit AI source audits
complete; no independent human approval. Small clustered early-source English
sample limitations remain explicit. Semantically routed document candidates
are still unadopted and being prepared under a frozen serialized local runtime.
RF-008 integration now communicates the measured wide request limits for
planned section bundles. All 15 focused integration checks and complete local software checks pass:
313 tests, 14 explicit optional-model/platform skips, Ruff, mypy and schema
checks. Actual large-bundle passive generation also passes; CI with real models
will verify the new code checkpoint. No independent quality gate is closed.


RF-006Q current user priority: finish full 3GPP/ETSI quality measurement and first
unseen fourth-corpus T7 validation. T7 protocol and 120 questions are locked before
queries, with no prior RAGForge tuning and no independent human review. Whole
PostgreSQL 18.0 manual stays searchable. Primary fixed hybrid plus raw BM25/dense
controls are to be reported separately. Sources/requirements/first outputs stay
immutable. [UNSEEN-T7.md](UNSEEN-T7.md). Generic HTML evidence oracle and its source
integrity/offline tests pass; complete local checks pass. Actual T7 evaluation
and 3GPP complete-fact measurement are still pending, not threshold achievements.


RF-006Q T7 first-result checkpoint: 360 actual queries finish without errors.
Primary all-requested-fact support is 104/120 (86.6667%), so the 95%/99% targets
remain open. English 88/90 and Serbian 16/30; all primary cases reviewed with
actual source proofs, 101 mechanical and 19 AI judgments, zero human approvals.
Preserve this first result and require another holdout after any tuning on T7.
Raw-control original-span diagnostics are separate from semantic accuracy.
Full 3GPP context artifact and the original 1,322 native/version reference
bindings are ready; original dense build and actual quality calls remain open.
The one-shot fixed supervisor continues locally under the original disk budget.
See UNSEEN-T7.md and benchmarks/t7-first-unseen-result-v1.json.


2026-11-05 multilingual follow-up: user requests >=95% across languages after
T7 English88/90 and Serbian16/30. Installed embeddings are already multilingual;
current final reranker and facet syntax are English-focused. Added opt-in
facets-v3 with protected quoted/code/argument boundaries, inherited grants and
400-pair cap; provisioned pinned multilingual mMARCO cross-encoder. Newly
generated agent instructions also advise faithful source-language queries.
342 software tests pass, 14 optional/platform skips; external bank drift,
Ruff, mypy and schema checks pass. Two actual offline multilingual-reranker
build/relocation tests pass with exact/ANN and all three query modes.
T7 development comparison (180 calls, one thread, original first result kept)
is being frozen; it is not a new holdout or an adopted production winner.
No new 95% claim. Required languages/fresh per-language validation remain open.
The ongoing 3GPP runtime and original measurement inputs are unchanged.
See MULTILINGUAL.md and benchmarks/multilingual-preparation-v1.json.


2026-11-05 reviewed multilingual T7 repeat: 180/180 actual comparison calls,
zero query errors. New candidate complete-fact support: English90/90, Serbian
Cyrillic25/30, Latin26/30; 134 mechanical source proofs and16AI case judgments
(seven additional complete equivalents,nine incomplete),zero pending,zerohumans.
Original120 composition115/120=95.8333%; expanded variants141/150=94%.
Serbian per-language95 target remains unmet. Original unseen104/120 is intact.
The repeat is consumed development, not a new holdout or production adoption.
Fresh same-candidate Kernel/RFC calls are queued; new GPP candidate calls wait
for its unchanged first primary baseline. Old Kernel/RFC scores are not reused
as multilingual-candidate scores. Detailed numeric report:
benchmarks/t7-multilingual-development-reviewed-v1.json.


2026-11-05 further Serbian improvement: implemented optional query_translation
for one bounded original-plus-documentation-language hybrid search. Original
question/grants stay present; final50/48000 andaggregate400paircaps retained.
No online translation service or answer lookup. Added CLI/MCP/shared-contract
path, strict request validation, explicit unsupported-mode errors and technical
subject propagation from query text. 353 local tests pass,14skips; external
frozen-bank drift,Ruff178,mypy56,schema pass. Actual tiny-model offline exact/ANN,
CLI andstdioMCP parity/grants checks pass. Development translations60variants
plus90unchangedEnglishcontrols frozen before new outputs; quality notyetmeasured.
Fresh source-family holdout needed after selection. See SOURCE-LANGUAGE-QUERIES.md.
