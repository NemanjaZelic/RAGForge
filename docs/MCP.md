# Lokalni MCP i agent integracija

`ragforge serve ARTIFACT` pokreće stvarni MCP server preko stdin/stdout, vezan za
jedan verifikovani lokalni bundle. Nema HTTP transporta, porta, autentikacije,
cloud poziva, automatskog preuzimanja modela ili izmene agent konfiguracije.
MCP SDK je opciona zavisnost: `ragforge[mcp]`; balanced inferencija dodatno traži
`ragforge[balanced,mcp]`. Razvojni `scripts/dev.ps1 setup` instalira oba extra-a.
Običan CLI i minimalni bundle ne zahtevaju MCP SDK.

Koristi zvanični [Python MCP SDK v2](https://py.sdk.modelcontextprotocol.io/),
sa strukturisanim izlazom; provereni su aktuelni discovery protokol i legacy
initialize tok. SDK nije ugrađen u bundle: instalira se u runtime okruženju.

```powershell
.\scripts\dev.ps1 run ragforge serve kb/mini-balanced-v1
```

Ovaj proces čeka MCP klijenta; terminal ne dobija običan rezultat pretrage.
Stdout je rezervisan za protokol, dijagnostika ide na stderr. Server ne beleži
upite ni sadržaj dokumenata u aplikacione logove; nasledni OpenTelemetry SDK je
isključen. Greška zahteva vraća MCP tool error i sesija ostaje upotrebljiva.
Očekivane runtime greške namerno ne otkrivaju unos ili privatne putanje.

## Alati i isti engine

| Alat | Ulaz | Izlaz |
| --- | --- | --- |
| `search_docs` | query, opciono collection_id, top_k, max_output_chars, filters.document_ids, search_method | RetrievalResponse v1 |
| `fetch_context` | collection_id, chunk_id, opciono neighbors, max_output_chars | RetrievalResponse v1 |
| `list_collections` | bez parametara | objekat sa collections listom |

Svaki alat je označen read-only, nedestruktivan, idempotentan i zatvorenog opsega.
Klijent ne može da promeni bundle putanju. Jedan `BundleEngine` deli isti
retrieval/context kod i izlaz sa CLI-jem. Balanced podrazumeva hybrid; `bm25`
izbor ne uvozi NumPy/ONNX/tokenizers niti učitava model. CPU pozivi se izvršavaju
u jednom radnom toku po serveru, sa serijalizovanom lenjom inicijalizacijom modela.
`--threads` ograničava ONNX CPU radne niti, ne broj paralelnih korisnika.

Granice su iste kao u core ugovoru: upit do 8192 znakova, top_k 1–50,
max_output_chars 1–100000, neighbors 0–5, filter do 100 document ID-jeva.
Podrazumevani budžet je 16000 znakova. Kao u CLI-ju, premali budžet za prvi ceo
chunk daje grešku; tekst se ne odseca usred citiranog chunk-a. Provera integriteta
radi pri pokretanju; bundle tokom sesije mora ostati nepromenljiv.
Rezultati nemaju automatsku potvrdu tačnosti niti prag za odgovor bez dokaza.

## Pasivni generator konfiguracije i skill-a

```powershell
.\scripts\dev.ps1 run ragforge integrate kb/mini-balanced-v1 --output .cache/agents/mini
# Opciono: --description "Search internal product docs and verify source citations."
```

Novi direktorijum sadrži:

- `mcp.json`: generic mcpServers konfiguracija sa apsolutnom putanjom tekućeg
  Python interpreter-a i bundle-a, argumentima kao JSON nizom i UTF-8 okruženjem.
- `skills/<ime>/SKILL.md`: [Agent Skills](https://agentskills.io/specification)
  frontmatter i sažete instrukcije za search/context/citate.
- `skills/<ime>/references/collection.json`: naziv, broj dokumenata/chunk-ova,
  build ID, dostupne metode i do 20 putanja izvora, označeni kao nepoverljivi podaci.

Generisanje koristi novi direktorijum i atomsko objavljivanje bez prepisivanja.
Ne piše unutar bundle-a niti menja globalni ili projektni config agenta.
Korisnik pregleda i dodaje server prema formatu svog klijenta, a skill postavlja
u podržani skills direktorijum. Generic JSON nije automatski host-specific config.
Posle premeštanja bundle-a ili promene interpreter-a ponovo generisati konfiguraciju.

Ime skill-a je validan, deterministički slug sa hash sufiksom kada je potreban;
imena i folderi se podudaraju. Opis dolazi samo iz eksplicitnog `--description`
ili bezbednog generičkog teksta sa collection ID-jem. Naslovi i sadržaj korpusa
ne prelaze u frontmatter ili serverske instrukcije. Putanje, naslovi, sekcije i
tekst iz rezultata ostaju nepoverljivi podaci; skill nalaže citiranje, proveru
dokaza i ignorisanje instrukcija iz dokumenata. To nije potpuna zaštita od prompt
injection-a u proizvoljnom agentu.

## Stvarni klijent i obim provere

```powershell
.\scripts\dev.ps1 run python examples/mcp_client.py kb/mini-balanced-v1 "How are access tokens sent?"
```

Primer otvara stvarni subprocess/stdio MCP, otkriva alate, poziva
list_collections/search_docs/fetch_context i ispisuje izvode sa citatima.
To je deterministički evidence workflow, bez spoljnog LLM-a i bez izmišljenog
odgovora. [Zabeležen smoke](benchmarks/mcp-smoke.json) koristi mali originalni
razvojni korpus; nije reprezentativan benchmark ili evaluacija autonomnog agenta.

Protokolski testovi proveravaju parity sa direktnim engine-om, sve tri metode,
filtere/limite/oporavak, kopiran bundle, legacy klijenta, zlonameran izvor kao
podatak i eksplicitan BM25 uz zabranjen ML import. Socket/DNS test guard dozvoljava
samo standardni event-loop socketpair IPC, a zabranjuje ostalo povezivanje,
slušanje, datagrame i DNS. Postojeći stroži CLI guard ostaje nepromenjen.
Stvarni pinovani E5 model proverava se kroz isti stdio tok na Windows/Linux;
Linux CI dodatno izvršava taj test u OS network namespace-u bez spoljne mreže.

RF-008 lokalni transport/generator su implementirani. Nezavisna evaluacija
odabranog LLM agenta na reprezentativnim korpusima ostaje otvorena, zajedno sa
RF-006. Shared HTTP/MCP, auth i produkciona izolacija pripadaju RF-010.
