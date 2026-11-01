# Jasan pregled izmena plana

Status: radni plan u D:\RAGForge. Originalni korisnički dokument je sačuvan bez
izmena. Ovaj pregled razlikuje korisničke dopune, naše radne odluke i ono što
je stvarno implementirano. Detalji: [radni plan](PROJECT-PLAN.md).

## Korisničke dopune optimizacije — važeća revizija

| Prethodna dopuna | Sadašnji zahtev i plan | Razlog |
|---|---|---|
| Nivoi su imali fiksne budžete u satima. | First try, Light, High i Max određuju obim i dubinu pretrage. | Isti posao različito traje na različitom hardveru i korpusu. |
| Vreme je bilo izabrano presetom. | Kratko meriti stvarno parsiranje, indeksiranje, embeddings i evaluaciju; prikazati ETA raspon i budžet. | Naziv procesora ili GPU-a nije dovoljno pouzdana procena. |
| Max je imao fiksan plafon od tri dana. | Automatska procena sa rezervom, uz najmanje 8 h dozvoljenog budžeta za Max. | Najviši nivo ne postaje trivijalan zbog brzog hardvera; trajanje može biti i duže na sporijem hardveru. |
| Rano zaustavljanje je bilo opisano opštom stagnacijom. | Pre 8 h Max završava zbog iscrpljenog celog prostora ili unapred definisane i dovoljno proverene konvergencije; prekid/greška/limit se prijavljuju zasebno. | Par pokušaja bez napretka nije dokaz optimalnosti. |
| Reč optimalno može zvučati kao garancija. | Izveštaj kaže najbolji provereni parametri u definisanom prostoru i eval skupu. | Globalni optimum uglavnom ne može da se dokaže. |
| Optimizacija je već predložena kao opcioni korak posle build-a. | To ostaje: prvo osnovni bundle, zatim zasebna optimizacija. | Dokumentacija je upotrebljiva i dok se traži bolja konfiguracija. |

**Pod od 8 h je zahtev za planirani Max budžet, ne zabrana korisniku da prekine
proces.** Ne čeka se besmisleno ako je stvarno ispunjen kriterijum ranijeg kraja.
Max sa eksplicitnim korisničkim plafonom ispod 8 h se odbija uz objašnjenje;
za kraći posao bira se niži nivo. Nema fiksnih sati za ostala tri nivoa.

Sve iz ovog odeljka je specifikacija buduće funkcije. Nisu izvršeni
kalibracija, višesatna optimizacija ili benchmark nad korisničkim korpusom.

## Korisnička dopuna testiranja proizvoda

Usvojen je pristup 3–7 stvarnih dokumentacija sa zasebnim golden skupom za svaku.
Pilot je 3 korpusa sa po 30 pitanja, zatim cilj 5 sa po 50–100 pitanja.
Brojevi su plan obima, ne potvrda kvaliteta ili statističke reprezentativnosti.

Dodatna preciziranja: izbor po kategorijama uz nasumično uzorkovanje, zamrznute
verzije, proverene oznake izvornog dokaza, odvojen tuning i završni test, bar
jedan ceo korpus van razvoja opštih default-a i izveštaji po svakom korpusu.
Pretraga, ingestion, citati, performanse i stvarni agent tok proveravaju se
zasebno. Dosadašnjih 39 testova ostaju provere osnove, bez tvrdnje da je proizvod
već kvalitetno testiran na dokumentaciji.

Detalji: [TESTING-PLAN.md](TESTING-PLAN.md). Spoljašnji korpusi i golden
pitanja još nisu pribavljeni/napravljeni; RF-006A/B/C prati taj rad.

## Usvojene izmene i dve ispravljene preporuke

Korisnik je prihvatio ostale ranije preporuke. PDF i hybrid su razjašnjeni:
[RELEASE-SCOPE.md](RELEASE-SCOPE.md) zahteva tekstualni PDF i semantičku/hybrid
pretragu u v0.1; OCR je eksplicitno kasnije. BM25 ostaje brz runtime izbor.
Taj usvojeni obim ima prednost nad ranijim minimal-only predlogom.
Status u tabeli razlikuje plan od stvarne implementacije.

| # | Original / nepreciznost | Važeća usvojena izmena | Status |
|---|---|---|---|
| 1 | Evaluacione funkcije uglavnom su u Fazi 6, iako se u F0 traže fixtures. | BM25 baseline i poređenje dense/hybrid već u Fazi 1; automatski optimizer kasnije. | Fixtures postoje; pravi benchmark još planiran. |
| 2 | Predlog monorepo-a sa sedam paketa. | Jedna Python distribucija sa odvojenim modulima. | Osnova paketa napravljena. |
| 3 | Runtime je u bundle-u, ali granica portabilnosti ostaje široka. | Odvojiti prenosive podatke od OS/arch runtime pakovanja; početni bundle traži kompatibilno instaliran runtime. | Odluka dokumentovana; samostalno pakovanje nije napravljeno. |
| 4 | Odvojene metadata.sqlite i bm25.sqlite. | Jedna SQLite baza po kolekciji za metadata, tekst i FTS5. | Plan arhitekture; builder još ne postoji. |
| 5 | Stabilni ID-jevi i hash-evi bez konačnog algoritma. | Document ID vezati za kolekciju i relativnu putanju; content hash odvojiti; chunk ID vezati i za konfiguraciju obrade. | Document ID i manifest validacija postoje; chunk algoritam dolazi uz chunker. |
| 6 | rank_score nije precizno usklađen sa SQLite smerom. | Javni score veće=bolje; za SQLite koristiti -bm25. Score nije confidence. | Ugovor dokumentovan; retrieval još planiran. |
| 7 | MD/HTML/TXT i digitalni PDF u početnoj isporuci. | Tekstualni PDF je obavezan deo istog v0.1, uključujući stranice u citatima i stvarni PDF benchmark. OCR kasnije. | Prethodno izdvajanje PDF koraka povučeno kao release preporuka; RF-007 je obavezan F1 zadatak. |
| 8 | Dense/hybrid bili su u Fazi 2, a početak BM25-only. | Dense/hybrid ulaze u v0.1 kao glavni tok. Balanced je default; BM25 je eksplicitan brz runtime metod i minimal profil. MCP koristi taj isti engine kasnije. | Prethodno odlaganje dense/hybrid povučeno; RF-009 je premešten u F1. |
| 9 | Offline flag i E2E uslov traže preciziranje. | Provere mrežnih poziva u CLI podprocesu, zatim stvarni offline build/search i OS izolacija pre release-a. | Osnovne CLI provere postoje; build/search E2E još ne. |
| 10 | Prompt-injection kriterijum može zvučati kao garancija ponašanja svakog agenta. | Garantovati granice RAGForge alata i meriti ponašanje podržanih agenata, bez univerzalne garancije. | Bezbednosna granica dokumentovana; agent testovi kasnije. |
| 11 | Jezici i source lokacije nisu potpuno operacionalizovani. | Testirati latinicu/ćirilicu/dijakritike; tačne lokacije samo kada su poznate; ne obećavati automatski prevod/transliteraciju BM25-a. | Jezički fixtures i source ugovor postoje; parser još planiran. |
| 12 | Opšti filters object i neimenovan token limit. | Početno samo dokumentovani document-ID filter i jasan limit znakova; token limit tek uz imenovan tokenizer. | Request modeli postoje; engine tek dolazi. |
| 13 | Automatski GPU izbor i interaktivni izbor režima po završetku build-a. | Minimalni profil CPU-only; build se završava paketom. Deployment je posebna eksplicitna operacija. Kasniji planner koristi podržan i izabran hardver. | Dokumentovan lokalni tok; remote/GPU runner još planiran. |
| 14 | Memorijski, finansijski i runtime limiti mogu zvučati kao apsolutne garancije. | Razlikovati procenu, operativno ograničenje i stvarno sproveden prekid; beležiti prekoračenja i uslove. | Pravila u planu; enforcement dolazi uz konkretne poslove. |

## Šta ovaj korak menja

Ažurirani su usvojeni v0.1 obim, backlog, radni plan, arhitektura, testiranje i
optimizacija. Važeće odluke: PDF sa tekstom + hybrid u v0.1; BM25 runtime opcija;
OCR kasnije. Ostala prihvaćena pojednostavljenja su zadržana.
Runtime kod, zavisnosti i postojeće JSON šeme nisu menjani.
[OPTIMIZATION-PLAN.md](OPTIMIZATION-PLAN.md) sadrži kriterijume za buduću
implementaciju; ova dopuna ne pokreće nijedan dug posao ili cloud resurs.
