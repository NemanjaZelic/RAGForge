# RF-002: tekst, chunking i citati

Implementirano: MD/TXT/HTML parser, zajednički ograničeni source reader,
deterministički chunker i `ragforge chunk ROOT --collection ID` pregled.
PDF adapter je implementiran u RF-007; detalji, page status i limiti su u
[PDF.md](PDF.md). BM25 index/search su implementirani u RF-003; bundle build/use još nisu.

## Encoding i integritet

Ulaz je strogi UTF-8 sa opcionim UTF-8 BOM-om. Nema detekcije ili tihog
fallback-a na Windows codepage/UTF-16; neispravni bajtovi se odbijaju.
CRLF i CR postaju LF. Unicode tekst se ne transliteriše/ne normalizuje.
Kontrolni znaci ispod U+0020 osim LF, tab i form-feed se odbijaju.

Parser čita ograničene bajtove iz istog reader-a kao scan; ponovo proverava
hash i veličinu naspram scan record-a i obrađuje baš pročitane bajtove.
Root i svi roditelji izvora proveravaju se za symlink/junction/reparse tačke.
Važi ista granica kao za scan: stabilan root, bez garancije OS sandbox-a
protiv istovremenog neprijateljskog menjanja direktorijuma.

## Normalizovani blokovi

`TextBlock` sadrži tekst, section, opcione line_start/line_end/page i kind
text/code. Ovaj isti oblik koristi RF-007 PDF adapter, bez novog engine-a.

- TXT čuva tekst posle encoding/newline normalizacije.
- Markdown podržava ATX i setext naslove, hijerarhiju sekcija i fenced code
  sa backtick/tilde markerima. Sirovi Markdown ostaje u tekstu: parser ne
  renderuje inline markup niti obećava punu CommonMark kompatibilnost.
  Naslovi unutar fenced code-a nisu sekcije. Nezatvoren fence ostaje code
  do kraja dokumenta i dobija warning. Indented code block semantika,
  frontmatter i složeni kontejneri nisu posebno interpretirani.
- HTML koristi standardni HTMLParser, bez browsera, mreže ili izvršavanja.
  Isključuje head/script/style/template/noscript i komentare. Izdvaja tekst
  sa blok granicama i h1–h6 sekcijama; prose whitespace se sažima, pre tekst
  zadržava razmake i indentaciju. Entiteti se dekodiraju u tekst. Ne
  renderuje CSS, ne garantuje vidljivost/DOM oporavak kao browser i ne učitava
  linkove, slike ili spoljne resurse. Nezatvoren isključen element može
  potisnuti ostatak HTML-a; izveštaj to označava warning-om.
- Prazan ili whitespace-only dokument ima warning no extractable text i
  nula chunk-ova; izveštaj ga zadržava.

Za MD/TXT fizički redovi su 1-based, uključive granice, računati samo po LF
nakon normalizacije CRLF/CR. Svaki chunk je tačan substring svog bloka.
Za HTML redovi ostaju null; ne postoji izmišljena source mapa. Za PDF je page fizička 1-based stranica; redovi ostaju null.

## Chunking i identitet

Default je 1000 Python Unicode znakova, overlap do 100 znakova unutar istog
bloka; to nisu tokeni ni grafemski klasteri. Veličina je 1–100000, overlap
mora biti manji od veličine. Granice sekcija/code blokova prekidaju overlap.
Manji code blok ostaje ceo; veliki se deli, uz preferenciju granice reda.
Prose prvo bira granicu reda, zatim whitespace u drugoj polovini prozora,
inače se deli na hard granici. Svi ne-whitespace znaci ostaju pokriveni;
izlaz zadržava originalni substring, uključujući whitespace.

Pipeline hash je SHA-256 UTF-8 kanonskog JSON objekta sa parser_version,
chunker_version, chunk_size_chars i overlap_chars; sort_keys=True,
ensure_ascii=False, separators=(',', ':'). Trenutne verzije su text-v1 i chars-v1.
Chunk ID je SHA-256 UTF-8 JSON niza
[ragforge-chunk-v1, document_id, raw_content_sha256, pipeline_hash, ordinal],
ensure_ascii=False, separators=(',', ':'). Ordinal je 0-based po dokumentu.
Promena source bajtova ili pipeline konfiguracije menja chunk ID čak i
kada je normalizovani tekst slučajno isti. Document ID ostaje vezan za
kolekciju i putanju.

Interni chunk sadrži block_index i char_start/char_end (0-based, half-open
offseti u normalizovanom bloku); to nisu HTML/source-file byte offseti.
Retrieval će koristiti isti source ugovor uz postojeće request granice.

## Limiti i CLI

Scan limiti ostaju 32 MiB po podržanom fajlu, 512 MiB korpusa i 100000 unosa.
Čitanje za parser je ograničeno istim limitima; parser u memoriji drži jedan
source i njegove normalizovane blokove. CLI prikuplja ograničen JSON preview.

Chunk API default: najviše 10000 chunk-ova i 10000000 izlaznih tekstualnih
znakova po pozivu. CLI default: najviše 10000 chunk-ova i 100000 tekstualnih
znakova za ceo korpus. Overlap se računa ponovo u output budžet; provera je
unutar chunkera pre nagomilavanja izlaza. Ovi limiti broje tekst, ne JSON
bajtove; metadata/escape overhead povećavaju veličinu serijalizovanog JSON-a.

Prekoračenje, encoding greška, promenjeni source ili nečitljiv PDF daju
exit 2 i JSON error na stderr bez delimičnog stdout-a. Chunk preview ne pravi indeks ili bundle; zasebni index/search koriste RF-003 engine.

```powershell
.\scripts\dev.ps1 run ragforge chunk examples/mini-docs --collection mini
.\scripts\dev.ps1 run ragforge chunk examples/mini-docs --chunk-size-chars 500 --overlap-chars 50
```

