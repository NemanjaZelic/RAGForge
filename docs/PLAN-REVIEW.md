# Pregled plana

Datum: 2026-11-01. Izvor: [neizmenjeni original](RAGForge-Project-Plan.md).
SHA-256 originala: `1023b17b63b39957b71dfbf490099c89537f34434bdb16fbb907cc478dde6524`.

## Razumevanje proizvoda

RAGForge gradi prenosiv paket za pronalaženje i citiranje dokumentacije.
Generisanje odgovora prepušta agentu. Mesto izgradnje i mesto korišćenja
nezavisne su odluke. Lokalni režim je prvi proizvod; mrežni adapteri i
iznajmljeni compute dolaze nakon dokazano korisne lokalne pretrage.

Najvažniji prvi korisnik je programer koji ima lokalnu dokumentaciju i želi
da agent može da je pretraži bez obaveznog servera ili spoljnog LLM API-ja.
Ovo je izveden fokus za početak, a ne dodatni zahtev iz originala.

## Šta treba zadržati

Jedan engine iza više adaptera; stvarno offline korišćenje; odvojeni skill,
konekcija i kredencijali; izvori u svakom rezultatu; eksplicitni remote upload;
odsustvo SaaS zavisnosti. Odlaganje serverless-a i provisioninga je razumno.

## Važeće odluke nakon korisničkog pregleda

Ostale preporuke su prihvaćene; PDF sa tekstom i dense/hybrid su obavezni u
v0.1 prema [RELEASE-SCOPE.md](RELEASE-SCOPE.md). OCR je kasnije.
Prethodno minimal-only predstavljanje v0.1 više ne važi.

| Prioritet | Nalaz | Važeća odluka |
|---|---|---|
| P0 | Evaluacija je kao funkcija tek u Fazi 6, iako bez nje rano ne znamo da li pretraga radi dobro. | BM25 baseline i dense/hybrid benchmark uvesti u Fazu 1. Automatska optimizacija ostaje Faza 6. |
| P0 | Sedam paketa pre prvog toka uvodi granice distribucije i zavisnosti koje još nemaju dokazanu potrebu. | Jedan Python distributivni paket sa modulima; izdvajati pakete tek zbog konkretne potrebe. |
| P0 | Bundle istovremeno liči na podatke, Python okruženje i izvršnu aplikaciju. | Odvojiti verzionisane podatke od OS/arch runtime pakovanja. Minimalni bundle traži instaliran kompatibilan runtime. |
| P0 | Stabilni identifikatori i checksum nisu dovoljno definisani. | Dokument vezati za kolekciju i relativnu putanju; hash sadržaja odvojiti. Precizirati promene chunk ID-jeva, inventar fajlova i pravila verifikacije. |
| P0 | SQLite BM25 i ilustrativni score 0.81 mogu navesti na pogrešan redosled ili tumačenje. | Javno izložiti score gde je veće bolje: negativna vrednost SQLite bm25 rezultata. Ne predstavljati ga kao confidence. |
| P0 | Offline flag i jedna provera bez interneta nisu potpuna specifikacija. | Testirati zabranu socket/DNS poziva u procesu i stvarni CLI kao zaseban proces; kontrolisati podprocese i implicitne download-e pri kasnijim ML integracijama. |
| P1 | Dve SQLite baze za metadata i BM25 zahtevaju dodatnu koordinaciju. | Jedna baza po kolekciji u minimalnom profilu: metadata i FTS5 zajedno. |
| P1 | PDF i hybrid moraju zadovoljiti cilj pretraživanja raznovrsne dokumentacije. | V0.1 obavezno podržava MD/TXT/HTML i tekstualni PDF, lokalne embeddings i hybrid/RRF. BM25 ostaje opciona brza pretraga nad istim paketom; MCP kasnije koristi isti engine. |
| P1 | Prompt-injection kriterijum zvuči kao garancija kontrole tuđeg agenta. | Garantovati da RAGForge ne izvršava dokumente i ne promoviše ih u instrukcije; ponašanje pojedinačnih agenata meriti regresionim testovima, bez univerzalne garancije. |
| P1 | Neodređeni jezici i parsiranje mogu prikriti loš kvalitet na srpskom. | Testirati latinicu, ćirilicu, dijakritike, kod i HTML. Ne obećavati transliteraciju, stemming ili semantičko prevođenje za BM25. |
| P1 | Granice memorije i budžeta deluju kao hard limit, a uglavnom su procene. | Za svaki limit navesti jedinicu, šta se meri i da li se samo procenjuje ili zaista prekida izvršavanje. |
| P1 | Automatski izbor GPU-a i interaktivni deployment posle build-a otežavaju ponovljivost i automatizaciju. | Minimalni build CPU-only; interaktivna pitanja samo na eksplicitan zahtev, nikakav deployment kao sporedni efekat build-a. |

PDF i dense mogu biti zasebni implementacioni zadaci, ali nisu naredni release:
v0.1 nije završen bez oba. Skenirani PDF/OCR je izričito odložen prema odgovoru
korisnika. Nepodržani ili nečitljivi delovi korpusa se jasno prijavljuju.

## Dodatne tehničke odluke pre završetka MVP-a

- Portabilan SQLite fajl i kompatibilna FTS5 funkcionalnost nisu ista garancija.
  Proveravati FTS5 pri pokretanju i verziju DB šeme u manifestu.
- Objavljivati zatvorenu, završenu bazu bez zavisnosti od WAL/SHM fajlova.
  Nova verzija ide u novi direktorijum; Windows otvoreni fajlovi zahtevaju test
  zamene aktivne verzije i oporavka, ne pretpostavku da svako rename uspeva.
- Checksum otkriva promenu u odnosu na pouzdan manifest; ne dokazuje autora.
  Proveravati putanje, symlink izlazak iz bundle-a, nedostajuće i neočekivane
  fajlove. Ne izvršavati runtime/skripte iz nepouzdanog paketa automatski.
- Parametrizovani SQL sprečava SQL interpolaciju, ali sam ne rešava FTS5 query
  sintaksu. Za običan korisnički upit definisati bezbedno pretvaranje u termine;
  operatorski query je eventualno zasebna eksplicitna opcija.
- Kod nepoznate PDF lokacije vratiti null, a ne izmišljene redove. Za HTML
  definisati provenance mapu; izvučeni tekst nije automatski isti kao red u izvoru.
- Ograničenja izlaza početi jasnim brojem znakova i rezultata; token limit zahteva
  imenovan tokenizer i ne sme biti obična procena predstavljena kao tačan broj.
- Početnih 20 pitanja su mali razvojni skup, ne reprezentativan dokaz kvaliteta.
  Za izbor chunkinga/modela biće potreban odvojen skup, bez podešavanja na testu.
- Licencu projekta potvrditi pre javnog release-a. Modeli i dokumenti imaju
  zasebne uslove; nikakvi modeli se sada ne preuzimaju niti redistribuiraju.

## Provera zvaničnih izvora

Izvori su provereni za odluke pripreme, ne kao potvrda svih budućih integracija.

- [SQLite FTS5 / BM25](https://www.sqlite.org/fts5.html#the_bm25_function):
  SQLite rangira boljim manjim vrednostima; potreban je eksplicitan score smer.
- [SQLite portability](https://www.sqlite.org/onefile.html):
  format fajla je prenosiv, ali runtime i proširenja proveravamo zasebno.
- [SQLite WAL](https://www.sqlite.org/wal.html):
  WAL može imati pomoćne fajlove; završetak artefakta mora to uzeti u obzir.
- [Typer](https://typer.tiangolo.com/): izabrani CLI sloj.
- [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/):
  modeli su izvor generisanih šema; dodatne semantičke provere ostaju u Pythonu.
- [uv caching](https://docs.astral.sh/uv/concepts/cache/):
  lokalni wrapper postavlja cache na D.
- [MCP specifikacija iz plana](https://modelcontextprotocol.io/specification/2026-07-28)
  i [Agent Skills](https://agentskills.io/specification) su dostupni.
  Konkretne SDK/client verzije testirati kada počne agent integracija.

## Dopuna: nivoi optimizacije

Korisnički predlog je tehnički izvodljiv kao budžetirana pretraga retrieval
konfiguracija, bez treniranja novog jezičkog modela.
[Posebna specifikacija](OPTIMIZATION-PLAN.md) proširuje postojeću Fazu 6 sa
četiri nivoa obima: first try, light, high i max. Raniji fiksni sati su ukinuti.
Trajanje se procenjuje merenjem na konkretnom hardveru i korpusu; Max dobija
najmanje 8 h automatskog budžeta, uz opravdan raniji kraj po zadatim kriterijumima.

Nema univerzalno optimalnog first-try profila niti garancije da veći budžet
daje veći kvalitet. [Pregled izmena](PLAN-CHANGES.md) jasno odvaja preporuke
od onoga što je implementirano.
Za tvrdnju o poboljšanju potrebne su relevance oznake i odvojen završni test;
bez toga rezultat ostaje preliminaran. Predlog je dodat u RF-013 i ne pomera MVP.

## Zaključak za rad

Razvijati jedan lokalni engine kroz proverljive zadatke, sa v0.1 release uslovom:
PDF sa tekstom i balanced/hybrid pretraga. BM25-only je razvojni međukorak,
benchmark i eksplicitna opcija; ne predstavlja završeni cilj proizvoda.
