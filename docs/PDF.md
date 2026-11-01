# RF-007: tekstualni PDF

Adapter koristi zaključani pypdf 6.21.4 u istom load/parse/chunk toku kao
MD/TXT/HTML. Ne izvršava PDF JavaScript, actions, priloge ili URL-ove, ne
dekodira slike, ne pokreće spoljne dekodere i ne instalira OCR.

Jedan blok predstavlja izdvojeni tekst jedne fizičke PDF stranice.
Source page je 1-based fizički indeks, nezavisno od štampane oznake/roman
broja. Line/section ostaju null: ekstrakcija ne dokazuje izvorne redove
ili semantički naslov. Chunk ne prelazi granicu stranice.

## Nepotpuni dokumenti

Svaka stranica ima status extracted/no_text/error, broj znakova i eventualnu
poruku. No_text znači da tekst nije izdvojen: stranica može biti prazna ili
slika. Ne tvrdi se pouzdana automatska detekcija skena. OCR ostaje isključen.
Chunk preview uključuje status incomplete i warnings; dokument nije sakriven.

Greška jedne stranice podrazumevano prekida ceo dokument bez delimičnog
stdout-a. --allow-partial-pdf eksplicitno dopušta page error i zadržava
ostale stranice. Limiti celog dokumenta i nečitljiva/enkriptovana datoteka
i dalje prekidaju obradu. Pipeline identitet uključuje pypdf verziju,
sve PdfOptions vrednosti i (page,status) niz; delimična obrada ne može dobiti
isti chunk ID kao ceo rezultat na drugoj stranici sa istim ordinalom.

## Stvarne granice

Default: 500 stranica, 8 MiB po deklarisanom/dekompresovanom stream-u,
64 MiB zbirno glavnih page content stream-ova, 200000 znakova po stranici,
2000000 tekstualnih znakova po dokumentu i 500000 parsing work operacija
po stream-u. Xref, page tree, filter chain i XForm invocations su takođe
ograničeni u pypdf configuration kontekstu. Kontekst se obnavlja i posle greške.
Obični scan limit od 32 MiB ulaznih bajtova i dalje važi.

To su prekidne granice parser podataka/rada, ne hard OS RSS ili vremenski
sandbox. Biblioteka može alocirati dodatne objekte i XForm stream-ove;
zbirni page-content limit nije mera ukupnog dekompresovanog dokumenta.
Za hostile corpus u kasnijem production worker-u potreban je OS limit memorije
i deadline. Ne tvrditi da postoji izolacija koja nije implementirana.

Strict PDF parsing odbija neke popravljive dokumente umesto tihog recovery-ja.
Enkriptovani PDF se odbija; korisnik priprema lokalnu dekriptovanu kopiju.
Replacement/NUL tekst se odbija kao nepouzdano dekodiranje. Plain extraction
zadržava sadržaj tabela/koda, ali ne garantuje raspored kolona, ćelije,
indentaciju ili reading order. Ne predstavljati izdvojeni tekst kao render.

## Provera

Tri originalna stvarna PDF fixture-a u tests/fixtures/pdf: tekst/tabela/kod
i dve kolone; image-only stranica; njihov mixed PDF. Poppler PNG pregled
potvrdio je čitljivost, raspored i sadržaj. Testovi proveravaju fizičke
stranice, tekstualne činjenice, neizmišljene redove, no-text status,
page/text/stream limite, compression bomb, enkripciju, partial identitete
i offline CLI podproces sa blokiranim socket/DNS pozivima.

[Realni parser pilot](benchmarks/pdf-rfc9110.json) koristi
[zvanični RFC 9110 PDF](https://www.rfc-editor.org/rfc/rfc9110.pdf):
194/194 extracted stranice, 461098 izdvojenih znakova, bez warnings.
PDF i izdvojeni tekst su samo u lokalnom ignorisanom cache-u.
U repo-u su URL, prava/izvor, hash, verzije, konfiguracija i rezultati.
Ovo je parser smoke/pilot; [BM25 PDF smoke](benchmarks/bm25-rfc9110-smoke.json) dodaje 3 proverena
page probe-a nad 600 chunk-ova. Širi retrieval benchmark i dense/hybrid
poređenje ostaju RF-006 release uslov.

Zvanične granice:
[pypdf configuration](https://pypdf.readthedocs.io/en/6.21.4/modules/configuration.html),
[text extraction](https://pypdf.readthedocs.io/en/6.21.4/user/extract-text.html).

```powershell
.\scripts\dev.ps1 run ragforge chunk tests/fixtures/pdf --collection pdf
.\scripts\dev.ps1 run ragforge chunk tests/fixtures/pdf --allow-partial-pdf
```

