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

Poslednja provera: automatsko kreiranje/slanje nije uspelo. Postojeći Git
credential dobija HTTP 401 od GitHub API-ja; povezani GitHub konektor radi za
nalog, ali za novi repo trenutno vraća 404 (nije napravljen ili nije dostupan
konektoru). Nema origin-a, push-a niti izvršenog GitHub CI-ja. Firefox prozor
potvrđen je sa naslovom "New repository" posle otvaranja pripremljenog URL-a.

Željeni repo: `NemanjaZelic/RAGForge`, obavezno private. Modeli, lokalni
cache, korpusi, alati i okruženja isključeni su kroz .gitignore. Nema
odabrane licence ni javnog release-a.

[Otvori pripremljenu formu za novi privatni repo](https://github.com/new?owner=NemanjaZelic&name=RAGForge&visibility=private&description=Portable+local+document+retrieval+for+agents).
Proveriti da je Private; ne uključivati početni README, .gitignore ili licencu
jer lokalni repo već ima istoriju. Kliknuti **Create repository**.

Posle kreiranja proveriti pristup novom repo-u preko povezanog GitHub
konektora. Za standardni Git tok treba obnoviti postojeću GitHub/Git prijavu
jer sada vraća 401; samo kreiranje repo-a ne popravlja sačuvani Git credential.
Nakon uspešne Git prijave, iz `D:\RAGForge`:

```powershell
.\scripts\dev.ps1 run python scripts/github_sync.py --push
```

Ako Git već ima sačuvan GitHub pristup, alat može i sam da kreira novi
privatni repo i sačuva commit-e:

```powershell
.\scripts\dev.ps1 run python scripts/github_sync.py --create --push
```

Alat koristi postojeći Git credential helper, ne pravi nove tokene niti
ispisuje/čuva kredencijale. Proverava nalog, privatnost, identitet repo-a,
čist main i postojeći origin. Nema force push-a ni promene vidljivosti.
Posle push-a poredi remote main SHA sa lokalnim HEAD. `--open` otvara formu;
bez `--create`/`--push` nema API upisa ni slanja koda. Ovo je zaseban
maintenance alat; lokalni scan/retrieval ga ne uvoze i nemaju mrežne pozive.

## Sledeći korak

RF-002: normalizovani tekst, provenance i deterministički chunking za
MD/TXT/HTML, uz ponovnu proveru source hash-a; zatim RF-007 tekstualni PDF.
Retrieval/build/use još nisu implementirani. PDF parser i pravi dense/hybrid
ostaju obavezan deo v0.1 prema RELEASE-SCOPE.md.
