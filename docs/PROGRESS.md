# Razvojni dnevnik

Datum: 2026-11-01. Kanonska radna kopija: `D:\RAGForge`.

## Sačuvan razvoj

- `5abdd61`: postojeći originalni plan i proverena F0 osnova, 39 uspešnih testova.
- `73a0e88`: RF-000 minimal/balanced manifest, lokalni query model i dense
  metadata/inventar, search-method ugovori, generisane šeme i sintetički primeri.
  56 uspešnih testova; lint, format, mypy i schema drift prolaze.
- `d62db93` RF-001: API i stvarna `ragforge scan` komanda sa sortiranim putanjama,
  identitetima i hash-evima. Provereni limiti, prazni/dupli sadržaji,
  nečitljivi i zamenjeni fajlovi, NFC, Windows junction i CLI offline subprocess.
  71 uspešan test, 3 preskočena zbog case-insensitive filesystem-a i nedostatka
  privilegije za symlink. Ti testovi ostaju aktivni za druge CI platforme.
  Ruff, mypy i schema drift prolaze. GitHub CI još nije pokrenut.
- `7ae1a59` GitHub maintenance alat dodatno ima 6 testova koji sprečavaju slanje u javni
  ili pogrešan repo i proveravaju remote HEAD. Ukupno: 77 passed, 3 skipped.

Originalni plan je sačuvan neizmenjen; njegov SHA-256 ostaje
`1023b17b63b39957b71dfbf490099c89537f34434bdb16fbb907cc478dde6524`.

## GitHub

Privatni repo: [NemanjaZelic/RAGForge](https://github.com/NemanjaZelic/RAGForge).
Pristup je potvrđen GitHub konektorom; standardna Git prijava obnovljena je
postojećim Git Credential Manager-om. Postavljen je origin i main prati
origin/main. Prvih pet commit-a uspešno je poslato i remote main potvrđen je
kao f89790f35583acc9086bc034a8ffda92220686bd. Raniji 401/404 blokatori su rešeni.

Za naredne sinhronizacije, iz D:\RAGForge:

```powershell
.\scripts\dev.ps1 run python scripts/github_sync.py --push
```

Alat koristi postojeći Git credential helper, ne pravi nove tokene niti
ispisuje/čuva kredencijale. Proverava nalog, privatnost, identitet repo-a,
čist main i postojeći origin. Nema force push-a ni promene vidljivosti.
Posle push-a poredi remote main SHA sa lokalnim HEAD. `--open` otvara formu;
bez `--create`/`--push` nema API upisa ni slanja koda. Ovo je zaseban
maintenance alat; lokalni scan/retrieval ga ne uvoze i nemaju mrežne pozive.

## Sledeći korak

RF-002 je završen: normalizovani MD/TXT/HTML tekst, source hash provera,
provenance i deterministički chunking. Novi ukupan rezultat: 102 passed,
3 skipped; pytest, ruff, mypy i schema drift prolaze. Chunk CLI subprocess
prolazi uz blokirane Python socket/DNS pozive.

Sledeći zadatak je RF-007: obavezni tekstualni PDF adapter, fizičke 1-based
stranice, stvarni PDF fixtures i prijavljene granice parsiranja.
Retrieval/build/use još nisu implementirani. PDF parser i pravi dense/hybrid
ostaju obavezan deo v0.1 prema RELEASE-SCOPE.md.
