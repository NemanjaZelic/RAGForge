# Od preuzimanja do pretrage — Windows i Linux

Preuzmi i raspakuj repozitorijum ili ga kloniraj. Komande ispod pokreću se iz
njegovog direktorijuma. Git nije potreban ako koristiš Download ZIP.

Potreban je 64-bit Python 3.11 ili noviji; 3.13 je proveren. Na Windows-u mora
biti dostupan kao `python`. Na Linux-u kao `python3`, sa modulima `venv` i `pip`.
Setup ne instalira sistemski Python niti traži administratorska prava. Za drugi
Linux interpreter koristi `bash setup.sh --python /putanja/do/python3.13`.

## 1. Jedna setup komanda

Windows, u PowerShell-u:

```powershell
.\setup.cmd
```

Linux:

```bash
bash setup.sh
```

Setup priprema lokalno okruženje, zaključane zavisnosti, model za pretragu i
višejezički reranker. Internet je potreban za prvi setup. Dokumenti se ne šalju
na internet. Postojeći validni modeli se proveravaju i ponovo koriste.
Preuzimanje prvo ide u privremeni direktorijum; neuspešno preuzimanje ne ostavlja
polupripremljen ciljni model. Setup može ponovo da se pokrene.

Ako je sve već pripremljeno, koristi `setup.cmd -Offline` na Windows-u ili
`bash setup.sh --offline` na Linux-u. Offline setup nikada ne preuzima pakete
ili modele; potrebni su prethodno pripremljeni lokalni alati i keš. Za postojeće
modele u drugom direktorijumu postoje Windows `-ModelDirectory` i Linux
`--models-directory` opcije.

## 2. Dokumenti do spremne baze — jedna komanda

Setup napravi prazan direktorijum `documents`. Ubaci svoju dokumentaciju u njega,
uključujući poddirektorijume. Zatim pokreni:

```powershell
.\ragforge.cmd build
```

ili na Linux-u:

```bash
bash ragforge.sh build
```

Za dokumente koji su već negde drugde:

```powershell
.\ragforge.cmd build "D:\Moja dokumentacija"
```

```bash
bash ragforge.sh build "/home/korisnik/Moja dokumentacija"
```

Kao drugu opciju, umesto lokalnog foldera prosledi javni sajt sa dokumentacijom:

```bash
bash ragforge.sh build --url "https://example.org/docs/"
```

Windows: `.\ragforge.cmd build --url "https://example.org/docs/"`.
Preuzimanje je eksplicitan korak pre lokalnog build-a. Čuva se lokalni snimak i
originalni URL svakog izvora. Podrazumevano: 100 stranica, dubina dva linka, isti
sajt i izabrani poddirektorijum, uz `robots.txt`. Nepotpuno preuzimanje ne menja
aktivnu bazu. Detalji i ograničenja su u [uvozu sajta](WEBSITE-IMPORT.md).
Zatim koristi isti završni `agent` korak ispod.

Komanda čita dokumente, deli ih na delove, gradi leksički i ANN indeks, uključuje
pripremljeni lokalni reranker i proverava završen paket. Ispisuje `Ready:` i
putanju nove baze u `kb/`. Tek nakon uspešne provere pamti bazu kao aktivnu.
Podržani su UTF-8 MD/TXT/HTML i PDF sa postojećim tekstom; OCR nije uključen.

Kod izmene dokumentacije ponovo pokreni isti `build`. Dobijaš novu verziju;
prethodne ostaju sačuvane. Neuspešan build ne menja prethodnu aktivnu bazu.
Postojeći izlazni direktorijumi se ne prepisuju.

Za samostalnu pretragu:

```powershell
.\ragforge.cmd ask "Kako funkcioniše autentifikacija?"
```

```bash
bash ragforge.sh ask "Kako funkcioniše autentifikacija?"
```

Rezultat su tekstualni izvori sa originalnim URL-ovima ili lokalnim putanjama
i dostupnim stranicama/linijama.
RAGForge pronalazi dokaze; povezani AI agent sastavlja konačan odgovor. Za pitanje
na drugom jeziku možeš eksplicitno dodati veran prevod u jezik dokumentacije:
`--query-translation "How does authentication work?"`. Runtime ne poziva servis
za automatsko prevođenje.

## 3. Završni korak — skill i veza za agenta

```powershell
.\ragforge.cmd agent
```

```bash
bash ragforge.sh agent
```

Dobijaš `SKILL.md` sa pravilima kada i kako agent pretražuje i čita dokumentaciju,
`mcp.json` za Claude Code/kompatibilne klijente, `codex.toml` za Codex/OpenAI lokalne
klijente i `INSTALL.md` sa tačnim koracima. **Poveži i skill i MCP** — samo MCP
konfiguracija ne učitava uputstva skill-a. Ovo je glavni završetak toka za rad sa
agentom; direktni `ask` ostaje dostupan za samostalnu proveru izvora.

[Agent integracija](AGENT-INTEGRATION.md) objašnjava gde se fajlovi postavljaju.
Generator ne menja postojeća podešavanja drugih aplikacija. Posle novog build-a,
pomeranja baze ili prelaska na drugi računar ponovo generiši konfiguraciju i
ažuriraj/restartuj povezani MCP server.

MCP server možeš pokrenuti i preko `ragforge.cmd serve` ili
`bash ragforge.sh serve`. On čeka MCP klijenta; nije interaktivni terminalski chat.

## Postojeći paketi i napredna upotreba

Ako imaš gotov paket sa `manifest.json`, ne moraš da ga gradiš ponovo:

```bash
bash ragforge.sh ask "Your question" --bundle "/data/my-bundle"
bash ragforge.sh agent --bundle "/data/my-bundle"
```

Ista `--bundle` opcija postoji na Windows-u. To omogućava korišćenje ranije posebno
pripremljenih paketa, uključujući njihov postojeći profil pretrage.

Jednostavni build je standardni balanced/hybrid tok: E5-small, višejezički
mMARCO reranker sa 100 kandidata, sections/token-aware delovi i ANN. Ne zamenjuje
posebne parent/context/facets recepte korišćene u pojedinim benchmarkovima i
ne daje novu garanciju njihove tačnosti ili vremena ispod 10 sekundi.

Važe postojeći osnovni limiti builder-a: 32 MiB po izvornom fajlu, 512 MiB ukupnih
izvornih bajtova, 500 stranica po PDF-u i 100.000 indeksiranih delova. Prekoračenje
se prijavljuje kao greška; dokumenti se ne izostavljaju prećutno. Za veće korpuse,
prilagođene limite i nastavak dugog ingest/build-a koristi napredni CLI:

```bash
.venv/bin/ragforge build --help
.venv/bin/ragforge ingest --help
.venv/bin/ragforge --help
```

Na Windows-u ekvivalent je `.\scripts\dev.ps1 run ragforge ...`.
Napredni build/use/verify/context/evaluation/MCP/shared HTTP koriste isti engine
na Windows-u i Linux-u. Linux provere u CI-ju obuhvataju testove, stvarne modele,
Bash setup, build/pretragu i izvršavanje generisane MCP konfiguracije. Windows
provere obuhvataju CMD pokretač i isti Python engine.

Repozitorijum sadrži kod i mali demo, a ne naše pune benchmark korpuse ili modele.
Lokalni `models/`, `documents/`, `kb/`, `.cache/` i `agent/` ostaju van Git praćenja.
