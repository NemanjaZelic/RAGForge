# RF-003: stvarna SQLite BM25 pretraga

Jedan SQLite fajl sadrži kolekciju, document/content identitete, tekst chunk-ova,
source JSON, parser verzije, warnings/page izveštaje i FTS5 external-content
indeks nad istim chunk tekstom. SQLiteEngine implementira postojeći
RetrievalEngine protokol: retrieve, fetch_context i list_collections.

To je funkcionalan lokalni development indeks, sa stvarnim index/search/context
CLI komandama. Portable bundle, manifest/checksum verifikacija i planirane
build/use komande ostaju RF-004/RF-005. Balanced/hybrid je i dalje release
default iz RELEASE-SCOPE.md; standalone indeks trenutno podržava samo BM25.

## Pisanje i čitanje

index proverava source bajtove kroz postojeći loader i parser. Otvara novi
fajl ekskluzivno i odbija postojeći bez prepisivanja. Neuspeh uklanja samo
novi fajl koji taj poziv poseduje, posle zatvaranja SQLite-a. To još nije
atomski bundle publisher. Zatvorena baza koristi DELETE journal i ne zavisi
od WAL/SHM fajlova. Prazna kolekcija je dozvoljena za development indeks.

Pored scan/PDF limita važe 100000 chunk-ova i 100000000 izlaznih tekstualnih
znakova po indeksu. Overlap ulazi u tekstualni budžet. PDF sa no_text/error
stranicama zahteva eksplicitan --allow-incomplete; --allow-partial-pdf dodatno
određuje da li je dozvoljena sama delimična ekstrakcija. Status nije sakriven.

Engine koristi mode=ro, query_only, trusted_schema=OFF i proverava application
ID, DB schema verziju i jednu kolekciju. Čitanje ne menja bazu. Ovde se otvaraju
lokalno proizvedeni development indeksi: ovo ne zamenjuje RF-004 verifikaciju
nepouzdanog paketa, potpise ili OS sandbox za zlonameran SQLite fajl.

## Upit i rangiranje

Query se NFC normalizuje i pretvara u najviše 64 različita alfanumerička
Unicode termina. Svaki je citiran kao literal; spajaju se OR-om. Punctuation-only
upit daje prazan rezultat; previše termina daje grešku. Nema prolaza sirovog
FTS jezika: AND/OR/NEAR, apostrofi, navodnici i SQL delovi nisu operatori.
Sve korisničke SQL vrednosti idu kroz parametre.

Tokenizer je unicode61 remove_diacritics 2. To nije transliteracija, stemming
ili semantička pretraga. Public score je -bm25(...), veće je bolje; pri
jednakom score-u raste chunk_id. Score nije confidence ili abstention signal.
Dense/hybrid zahtev na ovom indeksu daje grešku, bez tihog fallback-a.

Filtri ograničavaju document ID-jeve; nepostojeća kolekcija/chunk daje jasnu
grešku. Top-k i max_output_chars iz ugovora se poštuju. Vraćaju se celi
chunk-ovi sa originalnim source lokacijama, bez tihog sečenja dokaza.
Ako prvi rezultat ne staje u budget, sledi greška; inače se vraća rangirani
prefiks koji staje. Korisnik može smanjiti chunk size ili povećati output limit.

fetch_context uvek uključuje anchor i uzima do 5 suseda po strani iz istog
dokumenta; dodaje najbliže koji staju. Context je nerangiran (score=0), sa
stabilnim chunk_id redosledom. Score tu nije BM25 skor upita.
Redovi MD/TXT i fizičke PDF stranice koriste isti source ugovor kao parser.

CLI daje JSON stdout i JSON processing error na stderr sa exit 2. Model JSON
se ASCII-escape-uje kako ćirilica/Unicode ne bi srušili Windows cp1252 pipe.
JSON dekodiranje vraća originalne Unicode stringove bez gubitka sadržaja.

## Izmereno, bez release tvrdnji

[Mini baseline](benchmarks/bm25-mini.json): 6 autorskih dokumenata, 16
pozitivnih i 4 pitanja bez odgovora. Recall@5=1.0 i MRR@10=1.0 na pozitivnim
document-level oznakama; 2/4 negativna pitanja vraćaju rezultate.
Oznake su cele datoteke, ne tačni evidence spans, a skup je mali razvojni
fixture. Rezultat ne dokazuje kvalitet na stvarnoj raznovrsnoj dokumentaciji
ili sposobnost odbijanja pitanja bez odgovora.

[Realni PDF smoke](benchmarks/bm25-rfc9110-smoke.json): pinovani RFC 9110,
194 stranice, 600 chunk-ova. Tri unapred navedena exact-term probe-a vraćaju
očekivane fizičke stranice 138, 73 i 89 na prvom mestu; stranice su nezavisno
proverene u PDF renderu. Ovo nije held-out benchmark ili više-korpusni pilot.
Ne redistribuiraju se RFC PDF, tekst ili lokalni indeks.

Testovi pokrivaju read-only hash, ponovljiv rang, validne citate, scope,
Unicode/operator upite, budžete, failure cleanup i zatvoren indeks kopiran
na novu putanju. Stvarni MD+PDF index/search/context CLI podprocesi rade uz
blokiran Python socket/DNS. To nije OS mrežna izolacija; ona ostaje RF-006.

```powershell
.\scripts\dev.ps1 run ragforge index examples/mini-docs .cache/demo.sqlite --collection mini
.\scripts\dev.ps1 run ragforge search .cache/demo.sqlite rollback
.\scripts\dev.ps1 run ragforge context .cache/demo.sqlite CHUNK_ID --collection mini
```

Ponovljeni index na istoj putanji se odbija; za novi indeks izabrati novu putanju.
