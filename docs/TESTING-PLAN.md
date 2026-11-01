# Plan testiranja proizvoda na stvarnoj dokumentaciji

Status: planirano, nije izvršeno. Datum: 2026-11-01.
Korisnički predlog: 3–7 različitih dokumentacija i golden skup za svaku.
Ovaj plan proširuje RF-006 i koristi isti evaluator kao budući RF-013.

## Polazna odluka

Usvojiti predlog, uz izbor korpusa po kategorijama i zaključanu završnu proveru.
Nasumičan izbor sam po sebi može dati nekoliko veoma sličnih, urednih
dokumentacija. Prvo definisati razlike koje želimo da pokrijemo, pa nasumično
izabrati iz odgovarajućih kandidata uz zabeležen seed i pravila izbora.

Trenutnih 39 testova proverava pripremljenu osnovu: ugovore, validaciju i CLI.
Postojeći mini-docs i 20 razvojnih pitanja nisu benchmark stvarnog proizvoda.
Retrieval još nije implementiran; nema izmerenog rezultata realnog benchmark-a.

## Obim i izbor korpusa

Pilot: **3 korpusa × 30 pitanja = 90 pitanja**.
Zatim cilj: **5 korpusa × 50–100 pitanja**, uz mogućnost 3–7 korpusa ukupno.
Brojevi su početni plan obima, ne dokaz statističke reprezentativnosti.
Pisanje i nezavisna provera dobrih oznaka biće značajan deo rada.

| Grupa | Šta želimo da proverimo |
|---|---|
| Mala, uredna dokumentacija | Osnovno nalaženje činjenica i izvora, bez kompleksnosti velikog indeksa. |
| Srednja dokumentacija sa kodom, tabelama i primerima | Očuvanje značenja, komandi, opcija i code blokova. |
| Velika dokumentacija sa sličnim odeljcima | Precizno rangiranje, razlika između sličnih tema, vreme i memorija. |
| Stvarna neujednačena dokumentacija | README/wiki/guide rasuti po fajlovima, ponavljanja, nepotpuni opisi i neujednačena struktura. |
| Drugi jezik ili domen | Provera da pravila nisu podešena samo za engleske Python biblioteke. |

Veličinu meriti brojem fajlova, bajtovima teksta i kasnije brojem chunkova.
Kvalitet opisati opaženim osobinama: struktura naslova, duplikati, nepotpuni
primeri, mrtve reference, mešanje verzija. Ne proglašavati projekat lošim na
osnovu subjektivnog utiska. V0.1 pilot mora uključiti MD/TXT/HTML i najmanje
jedan stvarni tekstualni PDF korpus, sa tačnim stranicama u golden dokazima.
Mešani korpus proverava zajednički build svih podržanih formata. RF-007 i
RF-009 su obavezni F1 zadaci; OCR je kasnije prema odluci korisnika.

Provereni početni izvori kandidata, ne već izabrani ili preuzeti korpusi:

- [uv dokumentacija](https://docs.astral.sh/uv/) — ograničeni vodiči kao kandidat
  za manji korpus; stvarna veličina se meri pri snapshot-u.
- [FastAPI dokumentacija](https://fastapi.tiangolo.com/) — kandidat za sadržaj
  sa kodom i primerima. Koristiti potpun odabrani sadržaj, uključujući referencirane
  code primere ili verifikovan rendered HTML, ne sirove neizvršene include direktive.
- [Python offline HTML dokumentacija](https://docs.python.org/3/download.html) —
  kandidat za veći korpus sa stabilnim lokalnim fajlovima.
- [Docker manuals](https://docs.docker.com/manuals/) — kandidat drugog domena
  sa operativnim postupcima i opcijama; odabrati precizno ograničen podskup.
- [PostgreSQL manuals](https://www.postgresql.org/docs/) — kandidat za stvarni
  tekstualni PDF u v0.1 benchmark-u. HTML i PDF istog sadržaja ne računati kao
  dva nezavisna korpusa pri tvrdnji o raznovrsnosti.

Nije poenta izabrati svih pet navedenih: oni ne pokrivaju automatski neurednu
ili srpsku dokumentaciju. Za te grupe izabrati dodatne odgovarajuće projekte
ili korpus za koji postoji dozvola. Jezički i kontrolisano oštećeni mini-fixtures
ostaju dopuna i ne predstavljaju dodatne nezavisne realne korpuse.

Pre izbora zapisati shortlist, kriterijume, dostupnost i format; nasumični
izbor unutar grupe je ponovljiv. Ne menjati korpuse zato što proizvod na njima
loše radi. Isključenja imaju zabeležen razlog nezavisan od retrieval skora.

## Preuzimanje i ponovljivost

Za svaki korpus zabeležiti URL, release/tag/commit ili hash arhive, datum,
jezik, obim, licence/obavezne atribucije, pravila preuzimanja i sve transformacije.
Stalno promenljivi latest/current URL nije identitet benchmark-a.

Originalni snapshot čuvati read-only u `D:\RAGForge\data\benchmarks`.
Odvojiti raw snapshot, izabrani input, gold, build output i rezultate.
Verifikovati checksum inputa pri svakom poređenju.
Download je zasebna priprema; build i pretraga zatim rade bez mreže.
Ne pokretati kod ili komande pronađene u dokumentaciji.

Za objavljivanje korpusa proveriti konkretne uslove redistribucije; ako nije
odgovarajuće deliti sadržaj, objaviti metapodatke i postupak pribavljanja gde
je dopušteno. Ne tretirati licencu koda kao automatsku potvrdu licence svih dokumenata.

## Kako pravimo golden skup

Za svako pitanje čuvati:

- stabilan query_id, corpus/snapshot identitet, tekst i jezik pitanja;
- tip zadatka i očekivanu mogućnost odgovora;
- relevantne dokumente i tačne odeljke/izvorne dokazne raspone, sa nivoom
  relevantnosti i alternativnim važećim izvorima;
- kod višedelnih pitanja, sve grupe dokaza koje su potrebne za potpun odgovor;
- kratke proverljive očekivane činjenice i rubriku za agent odgovor;
- podelu dev/tuning/test, autora/proveravača, status provere i obrazloženje oznaka.

Dokaz vezati za zamrznut izvor, ne za trenutni chunk ID.
Tako promena chunkinga ne menja značenje golden oznaka.

Pitanja obuhvataju direktne činjenice, parafraze, postupke kroz više odeljaka,
kod/tabele, slične nazive sa različitim značenjem, ograničenja i slučajeve bez
odgovora. Za pilot okvirno 20% bez odgovora u zamrznutom korpusu; odnos se beleži
i prilagođava stvarnom domenu. Ne praviti sva pitanja kopiranjem naslova.

Najpre pročitati izvore i napisati pitanja/oznake bez gledanja rezultata našeg
retriever-a. AI može pomoći sa nacrtom; rezultat nije automatski gold.
Drugi nezavisan prolaz proverava izvor i oznaku; kada nema nezavisne ljudske
provere, jasno navesti da su to AI-authored/draft oznake. Isti model koji napiše
pitanje i potom potvrdi sopstveni odgovor nije nezavisna potvrda.

Prilikom pregleda dodati sve pronađene legitimne alternativne izvore.
Nepregledan dokument nije automatski dokazano nerelevantan. Beležiti
nepotpunost relevance oznaka, posebno na velikim korpusima.
Za pitanje bez odgovora proveriti da nije samo propušten postojeći dokaz;
nejasne slučajeve izdvojiti iz strogog score-a do razrešenja.

## Odvojiti razvoj, optimizaciju i završnu proveru

- Pitanja i parafraze iste teme držati u istoj grupi pri podeli.
- Dev/tuning pitanja se koriste za popravke i izbor parametara.
- Zaključan test deo koristi se posle zamrzavanja kandidata; ne gledati ga
  iznova posle svake promene i zatim zvati nezavisnim testom.
- Pri pet korpusa ostaviti bar jedan ceo korpus van razvoja opštih default-a;
  poželjna su dva ako obim omogućava. U pilotu je rezultat preliminaran.
- Na takvom novom korpusu prvo proveriti zamrznuti first-try/default.
  Za zaseban test optimizer-a dozvoliti samo njegov izdvojeni tuning deo;
  završna pitanja ostaju skrivena izboru konfiguracije.
- Ako se završni skup koristi za razvoj, promeniti mu status u razvojni i
  obezbediti novu završnu proveru pre novih tvrdnji o generalizaciji.

Ovo ne znači da se dokumenti uklanjaju iz indeksa: korisnikova dokumentacija
mora biti pretraživa. Odvajaju se pitanja/oznake dostupne razvoju ili optimizer-u.

## Šta merimo

| Sloj | Provera |
|---|---|
| Ingestion | Broj prihvaćenih/odbijenih fajlova, izgubljen tekst, struktura koda/tabela i tačnost source lokacija. |
| Retrieval | Recall@5/10, MRR@10, nDCG@10 i pokrivenost potrebnih dokaznih raspona; fiksni top_k i isti output budžet. |
| Citati | Da citirani fajl/stranica/redovi postoje i podržavaju baš navedenu tvrdnju. |
| Performanse | Build vreme, peak RAM, veličina bundle-a, cold/warm median i p95 latencija, hardver i verzije. |
| Proizvod E2E | Stvarni build → kopiranje bundle-a na novu putanju → CLI query/context bez mreže. |
| Agent E2E (F2) | Stvarni tool pozivi, potkrepljen odgovor i citati; slučajevi nedovoljnih dokaza se jasno označavaju. |
| Optimizacija (RF-013) | Baseline naspram izabrane konfiguracije na istim završnim pitanjima; utrošeni resursi, ETA greška, razlozi prekida i resume. |

Metrike po dokumentima i po dokaznim rasponima prikazati odvojeno.
Duplikati chunkova istog dokumenta ne smeju napumpati document-level rezultat.
Za višedelno pitanje proveriti sve potrebne dokaze, ne samo jedan pogodak.
Skorovi bez odgovora ne ulaze kao obična nula u pozitivni recall/nDCG prosek;
izveštavati ih zasebno.

Raw retriever sme vratiti slične ali nedovoljne fragmente: nizak BM25 score
sam po sebi ne dokazuje da odgovora nema. Agent ne sme predstaviti takve
fragmente kao potvrdu izmišljene činjenice.
Tačan odgovor poznat modelu iz njegovog prethodnog znanja nije dovoljan za
agent E2E prolaz: traže se stvarni pozivi i proverljivi citati snapshot-a.

U v0.1 uporediti BM25 baseline, dense i podrazumevani hybrid, uz iste inpute,
pitanja i limite. Golden skup obavezno uključuje parafraze koje proveravaju
semantičko nalaženje dokaza, kao i precizne termine/kodove gde je lexical koristan.
Prikazati gde svaki metod uspeva i gde greši, bez pretpostavke da hybrid uvek
pobeđuje. Brzi BM25 upit nad balanced paketom proveriti sa blokiranim učitavanjem
embedding modela: isti postojeći indeks mora raditi bez model inference-a.
Rezultate prikazati po svakom korpusu i tipu pitanja, zatim ravnopravni prosek
korpusa; veliki korpus ne sme sakriti potpun neuspeh malog.
Prikazati broj pitanja i nesigurnost. Početne pragove kvaliteta postaviti tek
posle pregledanog pilota, pre zaključavanja završne provere.

## Kontrolisani kvarovi i granice

Realni benchmark dopuniti malim determinističkim slučajevima: prazni i
neispravni fajlovi, duplikati, veoma dugi code blokovi, latinica/ćirilica,
maliciozne instrukcije, pokvaren checksum, nedostajući modeli, prekinut build
i prekinuta optimizacija. Ovi slučajevi daju precizne regresione testove koje
slučajan realni korpus možda nikada ne sadrži.

Za etape bez implementacije prijaviti not_implemented/not_supported, ne prolaz.
Tekstualni PDF i hybrid se ne ubrajaju u uspešno testirane mogućnosti dok
implementacija i stvarni test ne postoje; bez njih v0.1 ne prolazi release gate.
OCR, MCP, shared i serverless ostaju kasnije mogućnosti sa odvojenim testovima.

## Izvršavanje i sledeći zadaci

1. RF-006A: zadržati postojeći mali fixture za brze regresije i pravi offline
   build/query tok čim engine bude implementiran.
2. RF-006B: odabrati/pinovati 3 realna korpusa, preuzeti ih na D, napraviti
   90 pilot pitanja i evidentirati proveru oznaka.
3. RF-006C: pokrenuti stvarni proizvod nad pilotom, pregledati greške po sloju,
   zaključati evaluator/pravila i proširiti na ciljnih 5 korpusa.
4. RF-007 PDF i RF-009 dense/hybrid su deo F1/v0.1 pilota; RF-008 kasnije
   proširuje isti test stvarnim agent pozivima.
5. RF-013 koristi istu evaluaciju za optimizer; ne pravi zaseban povoljniji score.

Brzi fixture testovi rade uz svaki relevantan commit. Mali zamrznuti realni
subset može raditi u CI bez download-a tokom query-ja; puni korpusi i skupi
agent/optimization poslovi rade ručno, periodično i pred release.
Pravi Max test se radi kada optimizer postoji; virtuelni sat u CI zasebno
proverava njegove rokove i pravilo najmanje 8 h budžeta.

U ovom koraku dopunjen je plan; eksterni korpusi i gold skupovi još nisu
preuzeti/napravljeni. Ta stanja se ne obeležavaju kao završena.

## Izvori za metodologiju

- [BEIR rad](https://arxiv.org/abs/2104.08663) — raznovrsni retrieval korpusi
  i nezavisan BM25 baseline kao koristan obrazac. BEIR nije zamena za naš
  ingestion/CLI/bundle/agent E2E test.
- [Odvojena selekcija i evaluacija](https://scikit-learn.org/stable/modules/cross_validation.html)
  — sprečavanje prilagođavanja završnom testu.
- [IR metrike](https://ir-measur.es/en/latest/measures.html) — precizno imenovanje
  metrike, cutoff-a i relevance pravila.

MTEB/BEIR mogu kasnije dati dopunski spoljašnji signal za dense backend.
Njihova pretraga nad već obrađenim tekstom ne potvrđuje ispravnost našeg
parsiranja, provenance-a ili pakovanja.
