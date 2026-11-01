# Veliki benchmark — usvojeni obim i pripremljeni test set

Datum: 2026-11-01. Ovaj obim ima prednost nad ranijim malim pilotom.
Originalni `RAGForge-Project-Plan.md` ostaje neizmenjen.

Korisnik cilja zbirke poput 3GPP specifikacija. Ranijih 9 fajlova / 3,14 MiB
ostaju smoke/regresioni fixture, bez tvrdnje o kvalitetu ili skalabilnosti
proizvoda. Novi korpusi nisu mali izbor pogodnih vodiča.

## Preuzeti puni izvori

| Korpus | Dokumenata | Jedna input kopija | Raw + input |
| --- | ---: | ---: | ---: |
| 3GPP preko zvaničnog ETSI mirrora | 4.723 PDF-a | 3,565 GB | 7,130 GB |
| Cela dostupna HTML dokumentacija Linux kernel 6.18.0 iz Sphinx inventara | 3.857 HTML stranica | 0,132 GB | 0,264 GB |
| Cela RFC kolekcija iz zamrznutog zvaničnog XML indeksa | 9.854 dokumenta | 0,546 GB | 1,093 GB |
| **Ukupno** | **18.434** | **4,244 GB** | **8,487 GB** |

GB ovde znači 1.000.000.000 bajtova. Raw i input su zasebne kopije, obe
proverene SHA-256. Izvori su pod `D:/RAGForge/data/benchmarks/scale-v1`,
van Git-a. Manifest ima URL, veličinu, hash i stabilan document ID za svaki
fajl, i content hash celog snapshot-a. Modeli i indeksi nisu kreirani.

3GPP osnovni inventar obuhvata 99 grupa, 1.868 direktorijuma specifikacija i
4.709 PDF verzija iz 1.680 TS/TR porodica. Izabrana je poslednja objavljena
revizija unutar svakog izabranog release-a: 8, 15, 18, 19 i 20, uz fiksirane
konkretne URL-ove. Stvarno nađeno: Rel-8 768 fajlova, Rel-15 1.101, Rel-18
1.393, Rel-19 1.447. U popisanom ETSI PDF izvoru nije nađen Rel-20 sloj.
Scope serija: 21,22,23,24,26,28,29,31,32,33,35,36,37,38.

Dodato je i 14 tačnih originalnih legacy verzija na koje se stručni QA skup
poziva. Verzije su proverene na PDF cover-u. One su eksplicitni dodatak
inventaru, uključujući starije tehnologije; nisu predstavljene kao nove 5G/6G
specifikacije. Ne zamenjivati originalnu verziju odgovarajućim novijim PDF-om.

RFC kolekcija uključuje svih 9.854 objavljenih zapisa iz sačuvanog indeksa:
9.847 TXT/HTML reprezentacija i sedam PDF-only dokumenata. PDF-only izvori
nisu izbačeni. Budući ingestion test mora prijaviti eventualan nedostajući
tekstualni sloj, bez tihog OCR fallback-a. Kernel input sadrži sve dokumente
navedene u verzionisanom Sphinx inventaru; pomoćne slike/CSS/JS asseti nisu
zaseban tekstualni retrieval korpus. Kod iz dokumenata nije izvršavan.

To nije tvrdnja da su obuhvaćene sve 3GPP serije/sve istorijske revizije ili
završen normativni 6G standard. Rel-20 studije i Rel-21 normativni rad moraju
ostati odvojeni po statusu, izvoru i datumu. Ovaj snapshot ima prijavljen gap
za Rel-20 PDF izvore; njih ne zamenjuje pretpostavkama o 6G zahtevima.

Alternativni TSpec-LLM je takođe popisan: 15.420 Markdown fajlova,
4.727.725.277 bajtova, commit `2deccaebf031bb1eb063dcc87cc4392eb37a71a7`.
Ceo njihov repozitorijum ima 15.621.249.730 bajtova i uključuje druge formate.
Sadržaj nije preuzet: pristup zahteva korisnikovo prihvatanje uslova na
Hugging Face-u. Uslovi nisu prihvatani u njegovo ime. To je alternativna
konvertovana verzija 3GPP podataka, ne četvrti nezavisan domen i ne test
našeg PDF parsera.

## Pripremljeni slučajevi

| Sloj | Slučajeva | Poreklo/status |
| --- | ---: | --- |
| TeleQuAD extractive | 4.485 | Objavljena ručna anotacija; originali sačuvani neizmenjeni |
| TeleQuAD tabular | 278 | Upstream draft, 36 verzionisanih dokumenata |
| Eksplicitno verzionisani 3GPP upiti | 42 | Adaptacije native pitanja, tačna verzija i dokazni kandidati |
| RFC dopuna | 120 | 100 pojedinačnih + 20 multi-document AI draft slučajeva |
| Kernel dopuna | 120 | 100 pojedinačnih + 20 multi-document AI draft slučajeva |
| **Ukupno** | **5.045** | Korelisane varijante se ne računaju kao nezavisni uzorci |

TeleQuAD je pinovan na commit
`efb7f586b81f5b1d16805b7df4771c6e02d0c7dc`. Njegovi originalni QA fajlovi,
licencni opis i native metapodaci su sačuvani sa hash-evima. Upstream navodi
CC-BY-ND-4.0: originali ostaju neizmenjeni, lokalne adaptacije se ne
redistribuiraju. Lokalna banka i izvučeni konteksti su izvan Git-a.

Extractive deo ima 4.262 odgovorna i 223 neodgovorna pitanja u datom kontekstu.
**Native negative ne znači odsustvo odgovora u celoj zbirci.** Skup uključuje
web izvore i starije tehnologije; nije svih 4.485 pitanja o 5G/6G. Jedanaest
pozitivnih slučajeva izdvojeno je zbog neispravnih/praznih odgovornih raspona.

Za 3.439 pozitivnih pitanja sa 3GPP izvorom pribavljene su tačne originalne
specifikacije. Za 2.726 pitanja nađeni su kandidati dokaznih raspona u tačnom
PDF-u i fizičkoj stranici. To je provera poravnanja anotacija sa izvorom,
**nije rezultat RAGForge pretrage**. Normalizovano tekstualno poklapanje ne
zamenjuje nezavisan pregled semantike, naročito za formule i tabele.

RFC/kernel dopuna ima 240 pitanja i 100 izvornih dokumenata sa proverljivim
hash-evima fajlova i dokaznih raspona. Četrdeset slučajeva zahteva oba izvora.
Oznake su `ai_draft`, nezavisan pregled je pending, strogi score nije odobren.
Dokazni raspon je vezan za zamrznut izvor, ne za chunk ID. Za HTML se koristi
imenovana ekstrakcija glavnog Sphinx sadržaja; ne izmišljaju se javni brojevi
redova iz HTML-a. Tačni byte/text locator-i i hash-evi su u JSONL zapisima.

Dev/tuning/test za native banku je 2.022 / 828 / 1.913. Porodice specifikacija
i identični konteksti ostaju zajedno. Verzijske varijante zadržavaju podelu
originalnog pitanja. Dopunski multi-document slučajevi spajaju povezane
izvore pre podele. Ceo kernel korpus je rezervisan kao budući test opštih
podrazumevanih parametara, van njihovog razvoja. Test još nije zaključan:
nezavisan pregled oznaka i pravila evaluacije mora prethoditi zaključavanju.

## Stvarne granice koje test mora da otkrije

Osam 3GPP PDF-ova prelazi trenutni scan limit od 32 MiB po fajlu. Najvećih
osam imaju 5.790–7.123 fizičke stranice, provereno `pdfinfo` alatom; maksimum
u tom skupu je 7.123. Trenutni PDF default je 500 stranica i 2.000.000
tekstualnih znakova. Ukupan 3GPP korpus i RFC korpus prelaze scan default od
512 MiB. Podrazumevani limiti ne mogu da prime ovaj input bez odgovarajuće
konfiguracije/implementacionog rada.

Ovo je statički nalaz iz izvora i koda, ne pokrenut test proizvoda. Ne
skraćivati dokumente, izbacivati velike fajlove ili tiho praviti manji korpus
da bi budući test prošao. Test mora proveriti pun ingest ili jasno prijavljen
limit, gubitke, kompatibilnost i bezbedan prekid. Originalni runtime kod nije
menjan u ovom zadatku.

Potrebni su odvojeni rezultati ingestion-a, dokument/evidence retrieval-a,
verzijskog scope-a i resursa. BM25/dense/hybrid koriste iste input hash-eve,
pitanja, top_k i izlazni budžet. Citati moraju potkrepiti tvrdnju; tačan
odgovor poznat LLM-u iz memorije nije dovoljan. CLI/offline/moved-bundle,
prekid/resume i kasniji agent/shared testovi ostaju stvarni produktni tokovi,
bez simuliranih rezultata.

## Disk budžet

Korisnik ima oko 80 GB slobodno i traži najviše 60–70 GB za sve testove.
Usvojen je **zajednički plafon 65.000.000.000 bajtova**: izvori, kopije,
izdvojeni tekst, staging, indeksi, benchmark modeli i rezultati zajedno.
Acquisition ima poseban plafon od 15 GB i čuva 15 GB slobodne rezerve na disku.
Izvori koriste oko 8,49 GB sa obe kopije; konačno merenje svih pripremnih
fajlova je u `storage-report.json`. Pre buduće izgradnje proveriti preostali
budžet; veličina indeksa/modela još nije izmerena i nije unapred garantovana.
Ne preuzimati modele ili praviti indeks u ovoj fazi.

## Ponovljivost i trenutni status

[Manifest i testni fixture](../tests/fixtures/benchmarks/scale-v1/README.md)
sadrže source snapshot, SHA-256, byte veličine, document ID-jeve, disk
politiku, preflight nalaze i dopunske draft upite. Izvorni dokumenti nisu
commitovani. Alat za vraćanje koristi ovaj pinovani snapshot, ne trenutni
latest katalog:

```powershell
.\scripts\dev.ps1 run python scripts/restore_large_benchmark_sources.py --root D:/RAGForge/data/benchmarks/scale-v1 --download
.\scripts\dev.ps1 run python scripts/download_telequad_sources.py --root D:/RAGForge/data/benchmarks/scale-v1 --download
.\scripts\dev.ps1 run python scripts/align_telequad_sources.py --root D:/RAGForge/data/benchmarks/scale-v1
.\scripts\dev.ps1 run python scripts/prepare_large_benchmark.py --root D:/RAGForge/data/benchmarks/scale-v1
.\scripts\dev.ps1 run python scripts/validate_large_benchmark.py --root D:/RAGForge/data/benchmarks/scale-v1
.\scripts\dev.ps1 run python scripts/validate_large_drafts.py --source-root D:/RAGForge/data/benchmarks/scale-v1
```

Exact-source metadata za alignment je deo fixture-a; na novoj mašini ga
kopirati pod `data/benchmarks/scale-v1/metadata` kao što je objašnjeno u README.
Svi prikazani alati su priprema/provera podataka. Ne uvoze RAGForge engine,
ne preuzimaju modele i ne izvršavaju upite nad indeksom.

Projekat, pytest i retrieval benchmark **nisu pokretani**. Pripremljeni su
izvori i testovi; nema novog izmerenog retrieval kvaliteta ili release
odobrenja. Native span provere i source alignment nisu nezavisan stručni
pregled. Dopuniti/pregledati oznake pre stroge evaluacije, posebno negativne,
verzijske i multi-spec slučajeve. Status nije prikriven prolazom validatora.

## Izvori

- [ETSI TS katalog](https://www.etsi.org/deliver/etsi_ts/) i [TR katalog](https://www.etsi.org/deliver/etsi_tr/)
- [TSpec-LLM](https://huggingface.co/datasets/rasoul-nikbakht/TSpec-LLM)
- [TeleQuAD](https://github.com/EricssonResearch/TeleQuAD)
- [Kernel 6.18 dokumentacija](https://docs.kernel.org/6.18/)
- [RFC indeks](https://www.rfc-editor.org/rfc/rfc-index.xml)
- [3GPP Release 20](https://www.3gpp.org/specifications-technologies/releases/release-20)
