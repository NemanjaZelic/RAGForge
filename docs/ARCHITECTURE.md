# Početne arhitektonske odluke

Status: radni nacrt i usvojeni v0.1 cilj; originalni plan ostaje neizmenjen.
[RELEASE-SCOPE.md](RELEASE-SCOPE.md) ima prednost nad ranijim minimal-only predlogom.
V0.1 zahteva tekstualni PDF i dense/hybrid; OCR je kasnije.

## Struktura

Jedna distribucija `ragforge`, Python >=3.11, `src` layout:

- `core/`: tipovi/protokol, scan/parse/chunk, PDF adapter i SQLite BM25 engine.
- `artifacts/`: manifest i buduća verifikacija/izvoz.
- `cli.py`: Typer adapter; ne nosi retrieval logiku.
- `schemas/`: generisani JSON Schema dokumenti.
- `examples/mini-docs/`, `examples/eval.jsonl`: originalni mali razvojni korpus.
- `tests/`: ugovori, lokalna CLI provera i fixtures.

Runtime zavisnosti su Typer, Pydantic i zaključani pypdf; lokalni SQLite
FTS5 koristi standardnu biblioteku. Opcioni balanced CPU sloj koristi ONNX Runtime, Tokenizers i NumPy; Read-only stdio MCP je opcioni adapter nad istim BundleEngine-om; shared HTTP/MCP su kasnije. ReportLab/Pillow su samo dev fixture alati.
Lockfile obuhvata implementiranu F1 osnovu.

## Minimalni bundle v1 — nacrt

```text
kb/
  manifest.json
  collections/
    mini/
      index.sqlite
```

Prikaz iznad je minimal profil, koji ostaje eksplicitna opcija.
Podrazumevani balanced paket dodatno sadrži embedded dense indeks i lokalno
query-model pakovanje sa verzijama, checksum-ima, dimenzijom i runtime zahtevima.
Jedna SQLite baza sadržaće dokumente, chunk tekst, provenance i FTS5 indeks.
Manifest sadrži inventar dokumenta, hash svakog podatkovnog fajla, veličine,
backend/DB verziju, verzije parsera i chunkera i runtime zahteve.
Hash-evi su SHA-256 nad sirovim bajtovima. Manifest ne hash-uje sam sebe;
dodatni checksums.txt u v0.1 nije potreban, jer bi duplirao inventar.

Manifest šema ima verziju `1`; ovo je pre-release nacrt, ne objavljen stabilan
format. Nepoznata verzija i nepoznata polja se odbijaju. Do prvog release-a
promene zahtevaju ažuriranje modela, primera, šema i testova u istom diff-u.
Nakon release-a nekompatibilna promena dobija novu verziju.
Sama validacija šeme nije verifikacija sadržaja paketa ili bezbednosti SQLite-a.

Minimalni bundle ne uključuje Python interpreter ili univerzalne binarne fajlove.
Potrebna je kompatibilna instalacija RAGForge runtime-a. Samostalno OS/arch
pakovanje dolazi zasebno. RF-000 modeli i šeme sada opisuju minimal i balanced profil, lokalni query model,
dense indeks i podržane metode. Početni pilot bira E5-small i NumPy exact cosine; izbor je privremen do šire evaluacije. RF-009/004/005 sada grade i pretražuju stvarni lokalni hybrid bundle.

## Identitet i provenance

- Kolekcija: eksplicitan mali ASCII slug.
- Putanje: relativne POSIX putanje, bez drive oznake, backslash-a, praznih,
  dot/dot-dot segmenata ili apsolutnih putanja; Unicode NFC.
- `document_id`: SHA-256 kanonskog JSON niza
  `["ragforge-document-v1", collection_id, relative_path]`, UTF-8,
  `ensure_ascii=False`, `separators=(",", ":")`.
- Izmena sadržaja ne menja document ID; menja njegov content hash.
  Preimenovanje menja document ID; praćenje preimenovanja je van v0.1.
  Dva fajla istog sadržaja zadržavaju dva izvora i različite ID-jeve.
- RF-002 `chunk_id`: SHA-256 kanonskog JSON niza
  [ragforge-chunk-v1, document_id, content_sha256, pipeline_hash, ordinal].
  Pipeline hash uključuje parser/chunker verzije, veličinu i overlap;
  tačna serijalizacija i provenance su u [PARSING.md](PARSING.md).
- Putanja u citatu je relativna; originalni apsolutni root nije u deljivom bundle-u.
  Redovi su 1-based uključive granice; stranica je 1-based; nepoznato je null.

RF-001 odbija symlink, Windows reparse/junction i casefold kolizije.
Nenormalizovana Unicode NFC putanja se odbija bez tihog preimenovanja.
Validacija teksta putanje sama ne potvrđuje da fizički fajl ostaje unutar root-a.

## Ugovor pretrage v1 — nacrt

`RetrievalEngine` je Python Protocol za `retrieve`, `fetch_context` i
`list_collections`; RF-003 SQLiteEngine ga sada implementira za BM25.
Request modeli ograničavaju query na 8192 znaka, top_k na 1–50 i tekst odgovora
na najviše 100000 znakova ukupno. Ograničenja su znakovi, ne tokeni.
Prazan/whitespace query se odbija. Verzija odgovora je `contract_version="1"`.
Request prihvata `search_method=bm25|dense|hybrid`; null znači default iz
manifest-a. Rezultat identifikuje izvršenu metodu. Engine mora odbiti nepodržanu
metodu bez tihog fallback-a. RF-000 definiše ugovor, ne izvršava pretragu.

U v0.1 je dozvoljen samo filter po listi document ID-jeva; proizvoljan
`filters: object` odlaže stvarnu specifikaciju. ID kolekcije može izostati samo
kada postoji tačno jedna kolekcija; konkretni engine to proverava.

Rezultati su uređeni po rank_score opadajuće; za SQLite je to `-bm25(...)`.
Za hybrid koristiti dokumentovanu RRF rang vrednost, za dense eksplicitnu
metriku i smer. Kod jednakog score-a sortirati po chunk_id. Score nije confidence i ne poredi
se između metoda, pipeline-a ili nezavisnih upita.
`fetch_context` koristi tačan par collection_id/chunk_id i ograničen broj
susednih chunkova. ACL dolazi pre zajedničkog mrežnog runtime-a.

## Izvršavanje

Build compute i runtime mode ostaju nezavisni. Početne podržane vrednosti su
`compute=local`, `mode=local`, `profile=balanced` i hybrid pretraga kao cilj v0.1.
`profile=minimal` ostaje eksplicitni paket bez modela. Nad balanced paketom
`--search-method bm25` preskače embedding inference i ne radi rebuild.
Hybrid bez neophodnog modela daje grešku, bez tihog downgrade-a ili download-a.
Ne dodavati opcije koje tiho glume implementiranu remote podršku.
Build ne pokreće deployment niti pita o cloudu po završetku.

Read-only runtime ne menja bundle. Build piše u novi staging direktorijum,
zatvara bazu, proverava sadržaj, pa objavljuje novu verziju bez uništavanja stare.
Detalje atomskog objavljivanja i checksum verifikaciju implementirati uz builder.

## Opciona optimizacija posle build-a — planirano

Detalji: [OPTIMIZATION-PLAN.md](OPTIMIZATION-PLAN.md).
Profile određuje dozvoljene komponente; effort određuje obim pretrage;
compute određuje mesto izvršavanja. Te odluke ostaju nezavisne.
Trajanje i automatski budžet procenjuju se kalibracijom na stvarnom hardveru
za konkretan korpus i planirane kandidate. Max ima pod od 8 h budžeta; raniji
kraj zahteva iscrpljen prostor ili proverenu konvergenciju, uz odvojene statuse
za prekid, grešku i resursni limit. Globalni optimum se ne garantuje.

Optimizer koristi isti builder i engine, izolovane job direktorijume, keš sa
hash ključevima i odvojene evaluacione skupove. Novi chunking ili embedding
model traže novu obradu; potrebni su verifikovani izvori/snapshot.
Pobednik mora biti potpuno izgrađen i proveren. Prethodni bundle se ne menja
automatski; query ugovor i agent integracije ne zavise od optimization nivoa.
Prvi optimizer koristi već podržan balanced/hybrid engine, uz opcioni minimal
profil. Optuna je eventualni opcioni dodatak.
Manifest/JSON šeme se sada ne menjaju zbog buduće funkcije.

## Offline i bezbednosna granica

Core i minimalni CLI nemaju mrežne klijente i ne izvršavaju dokumente.
Trenutni testovi blokiraju socket u CLI podprocesu; to potvrđuje ponašanje
proverenih komandi, ne predstavlja OS sandbox ili završeni offline build test.
Ingestion mora imati limite veličine fajla/ukupnog korpusa i politiku symlink-a.
Nepouzdan bundle se proverava pre otvaranja; potpisi i arhivsko raspakivanje
nisu implementirani u Fazi 0.

## RF-000 — implementirani draft ugovori

Balanced zahteva sva tri capability-ja, hybrid default i potpuno inventorisan
lokalni query model (identitet, pinovana revizija, runtime/verzija, dimenzije,
licenca i fajlovi pod models/query/). Dense indeks ima backend/verziju,
dimenzije i metriku; dimenzije modela i indeksa moraju biti jednake. Canonical
putanja indeksa je collections/<id>/dense.index. Imenovanje backend-a/modela
je podatak manifest-a; fixture vrednosti nisu izabrani produkcioni backend.
Minimal ostaje samo BM25, bez dense konfiguracije. L2 udaljenost engine mora
pretvoriti u higher-is-better score; skorovi nisu uporedivi između metoda.
Primeri u examples/manifests su sintetički: hash-evi i modeli nisu stvarni
bundle i ne dokazuju integritet. Python validatori dopunjuju JSON Schema;
strukturna validacija ne zamenjuje buduću proveru bajtova i model pakovanja.

## RF-001 — politika skeniranja

`ragforge scan ROOT --collection ID` vraća ceo sortirani JSON izveštaj tek
po uspehu. Hash je SHA-256 sirovih bajtova u blokovima 64 KiB; prazni fajlovi
se inventarišu i dobijaju hash praznog sadržaja. Podržane ekstenzije su
.md/.txt/.html/.htm/.pdf bez obzira na veličinu slova. Ostali regularni
fajlovi se prijavljuju u ignored_paths. Direktorijumi se obilaze bez
izvršavanja dokumenata; linkovi/reparse tačke se odbijaju i kada bi bili
ignorisani kao nepodržani format. Sve putanje moraju biti prenosive i NFC;
casefold kolizije između fajlova i direktorijuma odbijaju se pre hash-ovanja.

Default hard limiti: 32 MiB po podržanom fajlu, 512 MiB ukupno podržanih
bajtova, 100000 svih unosa uključujući direktorijume i ignorisane fajlove.
Prekoračenje, greška čitanja ili detektovana zamena/promena fajla obaraju
ceo scan; CLI daje exit 2, JSON grešku na stderr i prazan stdout. Nepodržani
regularni fajlovi ne ulaze u byte budžet i sadržaj im se ne čita. Nema
automatskih isključenja direktorijuma: korisnik bira korpus root.

Root mora biti stabilan tokom rada. Lstat/resolve, O_NOFOLLOW gde postoji,
fstat i završna provera hvataju linkove i uobičajene promene, ali nisu
OS sandbox protiv procesa koji istovremeno menja direktorijume. Scan nije
transakcioni snapshot: parser/builder mora ponovo proveriti source hash i
čitati iste bajtove koje obrađuje. Taj nastavak pripada RF-002/RF-004.
Skeniranje PDF-a ne tvrdi da u njemu postoji tekst; provera dolazi u RF-007.

## RF-002 — parser i chunker

Implementirani zajednički source reader, MD/TXT/HTML parser i deterministički
chunker. Tačna encoding, source-map i budget pravila: [PARSING.md](PARSING.md).
TextBlock ima opcioni page/line provenance za obavezni RF-007 PDF adapter.
Chunk CLI je pregled fragmentacije, bez indeksa ili retrieval simulacije.

## RF-003 — implementirani lokalni engine

Jedna metadata/FTS5 baza, read-only SQLiteEngine i stvarni development
index/search/context CLI. Detalji scoring-a, scope-a, output limita i merne
granice su u [RETRIEVAL.md](RETRIEVAL.md). RF-009 proširuje isti ugovor
dense/hybrid metodama; RF-004 tek pakuje i verifikuje bundle.

## RF-009/004/005 — implementirani lokalni balanced tok

[LOCAL-BUNDLES.md](LOCAL-BUNDLES.md) opisuje pinovani ONNX CPU model,
exact cosine/RRF, lazy inference, bundle inventar i atomic no-replace build.
BundleEngine jedinstveno rutira metode; SQLiteEngine ostaje zajednički
metadata/FTS backend. BM25 ne učitava ML biblioteke ili dense matricu.
Query model/descriptor/licence su lokalno spakovani i hash verifikovani.
Parser konfiguracija, uključujući PDF opcije, eksplicitno je u manifestu.
Reprezentativni quality gate ostaje odvojeni RF-006 test-set posao.


## Shared transport decision (2026-11-02)

RF-010A uses the MCP SDK's existing Starlette ASGI app for thin REST routes rather
than introducing FastAPI as a second web stack. CLI, REST and MCP still call one
BundleEngine through a source-permission wrapper; no retrieval algorithm is
duplicated. HTTP is an explicit optional extra/listener, not a side effect of
local build/query. Offline pinned-key RS256 verification binds issuer, resource,
subject and read scope; token issuance remains with the operator's issuer.
TLS, strict Host/Origin checks, request bounds and safe errors apply to REST and
MCP. Operational rollout/version lifecycle remains the following milestone.
See [SHARED.md](SHARED.md) for the implemented contract and limits.


## Optional retrieval quality components

The common engine now accepts an inventoried local reranker configured in the
manifest. Dense/hybrid use it when present; raw BM25 stays a baseline, and a
request can explicitly enable/disable reranking. All candidate retrieval and
reranking honor the same source grants and budgets. The optional new manifest
field is excluded from build identity when absent/null to retain older v1
bundle identities. Models and index bytes stay immutable across an `enhance`
new-version publication. Section-aware character chunking is an explicit new
pipeline; no existing build or frozen benchmark is rewritten.

Answer-evidence annotations are evaluator inputs, never engine/reranker inputs.
They bind exact questions and verified minimal facts, allow equivalent citations,
and retain an independent-review gate. Original broad-window span metrics remain
separate. Details, limitations and the unachieved >=95% goal: [QUALITY.md](QUALITY.md).


### Optional mapped dense source rows

A dense index may declare `source_chunks` with an inventoried canonical child
SQLite path, originating build ID and `text-overlap-v1` mapping version. Vector
row counts and row IDs then refer to that child SQLite, while lexical ranking,
returned text and citations use the primary context SQLite. Verification checks
both inventories, SQLite integrity and identical source identities. Mapping runs
inside BundleEngine for CLI/MCP/HTTP; adapters have no alternate ranking path.
Absent mapping metadata is omitted from build identity calculation to preserve
existing v1 bundles. The new `recontextualize` command copies verified assets to
a separate staged/published version without re-embedding or activating it.


Optional document titles live beside source path/hash in the manifest. Verifier
checks them against indexed source lead text/heading metadata. They are used only
as reranker topic prefixes; original indexed text and source locations remain the
retrieval payload. Null titles are omitted from build identity for v1 compatibility.
Title preparation uses local source/catalogue data, independently of questions.
