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
- [ ] Prvo izvršavanje CI na GitHub-u (repo nije objavljen).

Lokalna validacija i precizni rezultati su u PREPARATION.md.
F0 ne znači da je retrieval MVP gotov.

## F1 — Lokalni v0.1: mešani formati, PDF i hybrid

Usvojeni release uslovi: [RELEASE-SCOPE.md](RELEASE-SCOPE.md).
Tekstualni PDF i dense/hybrid su obavezni pre v0.1 release-a.
BM25-only rezultat je interni međukorak ili eksplicitni minimal profil.

### RF-000 — Proširiti Phase 0 ugovore za v0.1

Trenutne šeme su minimal/BM25 nacrt. Dodati balanced manifest, identitet i
lokalno pakovanje query modela, dimenziju/metriku dense indeksa, capability-je
bm25/dense/hybrid i search-method izbor. Sačuvati minimal profil.
Done: modeli, generisane šeme, primeri i testovi su usklađeni; ništa ne tvrdi
da trenutna implementacija već pretražuje ili gradi indekse.

### RF-001 — Bezbedan scan i identitet

MD/TXT/HTML i PDF sa tekstom; sortirane relativne putanje; deterministički document ID; odvojeni
content hash; eksplicitna politika symlink-a i Unicode/case kolizija.
Done: testovi duplih sadržaja, praznih fajlova, traversal-a, velikih fajlova i
ponovljenog skeniranja. Greške se ne pretvaraju tiho u uspešan build.

### RF-002 — Parser i chunker

MD naslovi, TXT i HTML tekst bez script/style sadržaja; jasna encoding politika;
1-based source lokacije kada su stvarno poznate. Deterministički chunking sa
ograničenom dužinom, overlap-om i code-block slučajevima. Deliti normalizovan ulaz i PDF provenance
iz RF-007; parser adapter nije poseban retrieval engine.
Done: ponovljeni build daje iste identitete i tekst; citati odgovaraju originalu.
Ne tvrditi tačne HTML redove dok ne postoji proverena provenance mapa.

### RF-007 — Obavezni tekstualni PDF u v0.1

PDF parser je release zahtev, ne dodatak posle v0.1.
Ekstrahovati postojeći tekst, čuvati fizičke 1-based stranice i proveriti
tipične tabele/kod/više kolona. Ograničiti memoriju i prijaviti delimičnu obradu.
OCR ostaje kasnije prema eksplicitnoj odluci korisnika; skenirani delovi se
prijavljuju, bez tihog preskakanja ili automatskog OCR download-a.
Done: stvarni PDF fixtures i najmanje jedan realni PDF u v0.1 benchmark-u,
tačne stranice u citatu i dokumentovane granice parsera.

### RF-003 — SQLite FTS5 i retrieval

Jedna kolekcija; metadata i FTS u jednoj bazi; parametrizovan SQL; bezbedna
normalizacija običnog upita; veći javni score znači bolji rang.
Done: retrieve vraća ugovorene rezultate; prazna i nepostojeća kolekcija imaju
jasno ponašanje; apostrofi/operatori/ćirilica/dijakritici ne ruše query.

### RF-009 — Obavezni dense i hybrid u v0.1

Jedan CPU query embedding model, jedan embedded dense backend i RRF nad
istim kolekcijama/izvorima kao BM25. Balanced je podrazumevani build profil.
Izbor backend-a/modela potvrditi pilotom i Windows/Linux kompatibilnošću.
Done: pravi semantic/hybrid upit bez mreže, lokalno dostupan model,
parafrazirana golden pitanja i poređenje BM25/dense/hybrid pod istim uslovima.
Ovaj zadatak je premešten iz F2 u F1; reranker i više modela ostaju kasnije.

### RF-004 — Builder i integritet bundle-a

Zatvorena SQLite baza, dense indeks i lokalno query-model pakovanje za balanced;
potpuni inventar, licence/verzije/hash-evi; build u staging-u; bez prepisivanja
postojećeg paketa po defaultu. Minimal profil ostaje manji BM25-only paket.
Done: kvar fajla, lažni hash, neočekivana putanja i nepoznata verzija se odbijaju;
neuspešan build ne kvari stari paket; nema WAL/SHM zavisnosti u izvezenom bundle-u.

### RF-005 — Stvarni build/use/context CLI

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

- [ ] RF-006A: postojeći mini-korpus i 20 pitanja ostaju brza razvojna provera;
  implementirati stvarni build/query E2E. To nije dokaz kvaliteta na realnim docs.
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

Spoljašnji korpusi i golden skupovi su planirani, još nisu preuzeti/izrađeni.
Pilot ne blokira prvi mali demo; realni benchmark je potreban pre širih
tvrdnji o kvalitetu proizvoda i automatskoj optimizaciji.

## F2 — Agent-ready nad postojećim v0.1 hybrid engine-om

RF-008: MCP stdio nad istim engine-om, validan skill generator i odvojen config.
Done: stvarni MCP klijent poziva search/context; primer agenta citira izvor;
generisanje ne menja korisnički agent config bez izbora. Testirati hybrid
podrazumevani tok i eksplicitan BM25 izbor. Dense/hybrid već pripadaju F1.

## Posle toga

RF-010: shared HTTP/MCP, auth i izolacija pre production preporuke, parity i rollback.
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
- Jedan dense backend i model za v0.1 biraju se kroz rani pilot; dodatni modeli kasnije.
- Mrežni/cloud provider se ne bira za F0/F1.
