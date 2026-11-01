# Usvojeni obim v0.1 — PDF i hybrid retrieval

Status: usvojeni radni plan, implementacija još nije završena.
Ovaj dokument ima prednost nad ranijim predlozima o minimalnom BM25 demou.
Originalni dostavljeni plan ostaje neizmenjen.

## Odluka korisnika

- Ostala predložena pojednostavljenja su prihvaćena: jedna Python distribucija,
  jedan engine, objedinjena SQLite metadata/FTS baza, rani benchmark, precizni
  identifikatori, izvori, limiti i odvojeno runtime pakovanje.
- **PDF sa postojećim tekstom je obavezan deo v0.1.** OCR je izričito kasnije.
- **Semantička i hybrid pretraga su obavezne za v0.1.** BM25-only implementacija
  može biti interni razvojni korak, ali ne završeni v0.1 proizvod.
- BM25 je brz eksplicitni režim izvršavanja upita i obavezan benchmark baseline.
- Optimizacija sa hardverskom procenom i Max budžetom najmanje 8 h ostaje
  kasniji opcioni korak; nivoi i pravila ranijeg završetka se ne menjaju.

## Proizvod koji isporučujemo u v0.1

`MD/TXT/HTML/PDF sa tekstom → parse/chunk → BM25 + dense indeks → portable bundle → local hybrid query → citabilan dokaz`

Podrazumevani build profil je `balanced`, a podrazumevani search metod tog
paketa je `hybrid`: leksički rezultati i dense rezultati spajaju se RRF-om.
Minimal profil ostaje manja instalacija/bundle za eksplicitno BM25 korišćenje.
Napredni reranker i veći izbor modela nisu uslov v0.1.

Jedna v0.1 isporuka mora stvarno podržati PDF i hybrid nad istim engine-om.
Interna podela na zadatke/commitove ne pomera te funkcije u naredni release.
MCP/skill integracije i shared/remote/serverless ostaju kasnije etape.

## Zašto BM25 i dense imaju različite uloge

BM25 rangira delove teksta prema poklapanju termina uz statistiku korpusa.
To je korisno za precizne nazive API-ja, opcije, kodove grešaka i citate.
Sam po sebi ne daje opštu semantičku pretragu parafraza.

Dense model pretvara upit i fragmente u embedding reprezentacije; može
pronaći sadržaj sa srodnim značenjem bez istih izraza.
Na primer: pitanje o prekidanju neuspele transakcije može tražiti odeljak
koji koristi izraz rollback. Ovo je ilustracija cilja, ne izmeren rezultat.

Hybrid kombinuje komplementarne rezultate. Ne obećavati da u svakom upitu
pobeđuje BM25 ili dense. Benchmark mora prikazati sva tri metoda i njihove
troškove, sa istim pitanjima, korpusom i izlaznim ograničenjima.

RAGForge vrednost uključuje obradu formata, očuvanje strukture i citata,
prenosivost, modele i engine za lokalni rad i kasnije agent integracije.
Predlog da prvo dovršimo BM25 bio je način da se proveri cevovod; korisnik
je sada jasno odredio da javni v0.1 mora uključiti semantički deo.

## Profili izgradnje i metoda upita su odvojeni

| Izbor | Sadržaj / ponašanje |
|---|---|
| `build --profile balanced` (default) | Metadata/FTS5 + dense indeks + query model ili proverljivo lokalno model pakovanje. |
| `build --profile minimal` | Metadata/FTS5; bez modela i dense indeksa. Eksplicitna opcija. |
| `use --search-method hybrid` | Nad balanced paketom: embed upit, BM25 i dense, RRF. Default balanced pretrage. |
| `use --search-method bm25` | Nad balanced ili minimal paketom: koristi postojeći FTS5, bez učitavanja embedding modela ili rerankera. |
| `use --search-method dense` | Nad balanced paketom: semantička grana, korisna i za zasebno benchmark poređenje. |

`--mode local/shared/serverless` i dalje opisuje runtime okruženje, a ne
algoritam pretrage. `--effort` opisuje dubinu buduće optimizacije.
To nisu sinonimi za `--search-method`.

Za balanced paket promena hybrid → bm25 ne zahteva rebuild ili brisanje
vektora/modela. Promena embedding modela zahteva reindeksiranje.
Minimal paket ne može da izvrši hybrid bez dopune/rebuild-a.
Ne obećavati da je BM25 uvek brži: to je opcija sa manjim inference zahtevom,
a stvarna latencija se meri po korpusu i hardveru.

Ako nedostaje dense model ili indeks, hybrid prijavljuje grešku sa jasnim
korakom oporavka; nema tihog prelaska na BM25, download ili cloud API.
Za izričit BM25 upit nije potreban embedding inference čak ni u balanced paketu.
Integritet paketa se i dalje proverava prema deklarisanim pravilima; preskakanje
model inference-a ne znači prihvatanje oštećenog bundle-a. Minimal je profil za
korisnika koji želi paket u kome model uopšte nije prisutan.

## Obavezna PDF podrška

Podržati tekstualne PDF dokumente, uključujući page provenance, ograničenje
memorije i testove teksta/tabela/koda/više kolona.
Ne obećavati savršenu ekstrakciju svih rasporeda: zabeležiti probleme i testirati
tipične slučajeve. Parser biblioteka se bira kroz mali proverljiv zadatak,
uz kompatibilnost, licence, kvalitet i offline ponašanje.

Skenirani PDF bez tekstualnog sloja prijavljuje da je potreban OCR.
OCR/VLM nisu implicitni fallback i ne preuzimaju modele automatski.
Kod dokumenta sa mešavinom čitljivih i skeniranih strana, prijaviti nedostupne
delove. Prazna stranica sama po sebi nije dovoljan dokaz da je potreban OCR.
Rezultat ne sme prikazati nepročitan deo dokumenta kao uspešno indeksiran.

Izvor sadrži relativnu putanju i stvaran broj stranice; redovi su null kada
ih PDF ne definiše pouzdano. Page broj znači 1-based fizičku stranicu fajla;
odštampani broj u dokumentu može biti zaseban metapodatak.
Ako chunk obuhvata više strana, čuvati raspon u internom modelu ili ga podeliti
tako da javni citat bude tačan; ne pripisati ceo chunk jednoj pogrešnoj stranici.

## Korpus raznih formata

Cilj je jedan ulazni korpus mešanih dokumentacija. V0.1 podržava MD/TXT/HTML
i tekstualni PDF u istom build-u. Ostali formati dolaze kroz parser adaptere;
ne tvrditi da svaka ekstenzija već radi.

Build izveštaj navodi svaki fajl: obrađen, prazan, nepodržan ili neuspešan.
Ne proglašavati ceo korpus uspešno obrađenim uz tiho preskočene dokumente.
Podrazumevano neuspešna/nepodržana obrada sprečava status potpunog uspeha;
nastavak sa delimičnim korpusom traži eksplicitnu opciju i vidljivo partial stanje.

## Model i portable paket

V0.1 mora imati jedan stvarno podržan CPU query embedding model i jedan
embedded dense backend. Izbor jezika/modela potvrditi pilotom, posebno za
srpski/ćirilicu; semantička pretraga ne znači automatski kvalitet na svim jezicima.

Manifest mora da identifikuje model, verziju/reviziju, checksum, dimenziju,
tokenizer/query/document pripremu, normalizaciju, metriku i format indeksa,
runtime zavisnosti, licence i dostupne search metode.
Modeli se pribavljaju zasebno ili uključuju u prenosivi paket u skladu sa
licencom. Offline upit nikada ne pokušava preuzimanje.
Prenos balanced bundle-a testira se sa modelom i indeksom na novoj putanji.

Postojeći Phase 0 Pydantic modeli i JSON šeme trenutno opisuju minimal/BM25
nacrt. To nije dovoljan ugovor za v0.1. RF-000 mora proširiti manifest i search
ugovor, primere, generisane šeme i testove pre implementacije balanced builder-a.
Ovaj plan ne predstavlja postojeći kod kao da već podržava hybrid.

## Release uslovi

V0.1 nije gotov dok svi sledeći uslovi nisu ispunjeni:

- [ ] Jedan build nad mešanim MD/TXT/HTML/PDF korpusom, sa proverljivim izveštajem.
- [ ] Stvarna PDF ekstrakcija i tačne stranice; OCR slučaj jasno prijavljen.
- [ ] Balanced build, lokalni embeddings, dense indeks i RRF za pravi hybrid upit.
- [ ] Parafrazirana pitanja u golden skupu, precizni nazivi/kodovi i PDF pitanja.
- [ ] Isti evaluator upoređuje BM25, dense i hybrid na istom snapshot-u.
- [ ] `--search-method bm25` nad balanced paketom radi bez model inference-a,
  bez ponovnog indeksiranja i sa proverom da se model ne učitava.
- [ ] Pravi offline CLI E2E i kopiranje kompletnog balanced paketa na novu putanju.
- [ ] Nedostajući model ne izaziva skriveni download ili BM25/cloud fallback.
- [ ] Izmereni RAM, build vreme, veličina i cold/warm query latencija.
- [ ] Trenutni minimal-only ugovori prošireni za v0.1 i šeme/testovi usklađeni.

## Planirani CLI — nije implementiran

```bash
ragforge build ./docs --compute local --offline --profile balanced --output ./kb
ragforge use ./kb --mode local --search-method hybrid --query "How can I undo a failed transaction?"
ragforge use ./kb --mode local --search-method bm25 --query "ROLLBACK"
ragforge use ./kb --mode local --search-method dense --query "Undo unsuccessful changes"

# Eksplicitni paket bez ML modela:
ragforge build ./docs --compute local --offline --profile minimal --output ./kb-lexical
```

Bez eksplicitnog search-method, balanced paket bira hybrid, minimal bira bm25.
Ovo je dispatch prema javno vidljivom profilu paketa, ne fallback posle greške.

## Relevantni izvori

- [SQLite FTS5/BM25](https://www.sqlite.org/fts5.html#the_bm25_function):
  rangiranje po terminima, frekvencijama i dužini.
- [FastEmbed semantic search](https://qdrant.tech/documentation/fastembed/fastembed-semantic-search/):
  lokalna generacija embeddings kao mogući implementacioni put.
- [BEIR](https://arxiv.org/abs/2104.08663):
  nezavisan lexical baseline ostaje koristan; ne zaključivati unapred da
  svaki neuralni sistem ili hybrid univerzalno nadmašuje lexical.
- [pypdf extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html):
  razlika tekstualnog PDF-a i OCR-a, kao i ograničenja ekstrakcije.
