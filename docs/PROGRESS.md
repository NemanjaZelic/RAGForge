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
  Ruff, mypy i schema drift prolaze. Prvi GitHub CI naknadno uspešno izvršen; detalji ispod.
- `7ae1a59` GitHub maintenance alat dodatno ima 6 testova koji sprečavaju slanje u javni
  ili pogrešan repo i proveravaju remote HEAD. Tada ukupno: 77 passed, 3 skipped.

- [2f5164c](https://github.com/NemanjaZelic/RAGForge/commit/2f5164c894ca1206d0856747221c939106b71466)
  RF-002: provereni MD/TXT/HTML parser, deterministički bounded chunker,
  tačni MD/TXT redovi, HTML bez izmišljenih redova, code blokovi i chunk CLI.
  Lokalno 102 passed, 3 skipped; sve obavezne provere prolaze.
  Mini-korpus: 6 dokumenata, 21 chunk, 2840 izlaznih tekstualnih znakova.
  Ovo je funkcionalna ingestion provera, bez benchmark tvrdnje o retrieval kvalitetu.

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

## GitHub CI — potvrđeno

[RF-002 CI run](https://github.com/NemanjaZelic/RAGForge/actions/runs/41277555420)
završen je uspešno za commit 2f5164c: Ubuntu i Windows, Python 3.11 i 3.13.
Svaki job izvršava pytest, lint, format, mypy, schema drift i izgradnju wheel/sdist.
Prethodni početni CI run 41277114172 takođe je uspešan.
Lokalna tri preskakanja su platform/privilege zavisna; ne predstavljaju CI grešku.

## Poslednja isporuka

- abae50f: RF-007 PDF adapter, stvarni fixtures i pinovani realni PDF pilot.
- 72e8cc3: RF-003 SQLiteEngine, index/search/context CLI, offline mixed MD/PDF
  E2E, Unicode stdout ispravka i izmereni BM25 mini/PDF smoke izveštaji.
- [RF-003 CI](https://github.com/NemanjaZelic/RAGForge/actions/runs/41278861087)
  uspešan je na Windows/Linux i Python 3.11/3.13; uključuje tests, lint,
  format, mypy, schema drift i wheel/sdist build.
- Lokalno 132 passed, 3 platform/privilege skipped. Originalni plan ima isti SHA-256.
  GitHub main i lokalni HEAD se proveravaju posle svakog push-a; lokalni Git bundle
  checkpoint se osvežava posle isporuke.

## Sledeći korak

RF-002 je završen: normalizovani MD/TXT/HTML tekst, source hash provera,
provenance i deterministički chunking. Novi ukupan rezultat: 102 passed,
3 skipped; pytest, ruff, mypy i schema drift prolaze. Chunk CLI subprocess
prolazi uz blokirane Python socket/DNS pozive.

RF-007 PDF adapter je implementiran: fizičke stranice, page status, strogi
limiti i eksplicitna delimična obrada; 113 testova prolazi, 3 skip-a.
Tri originalna PDF fixture-a vizuelno su proverena; realni RFC 9110 pilot
ima 194/194 extracted stranice. [Granice i pilot](PDF.md).

RF-003 je završen: SQLite FTS5/BM25 engine i stvarni index/search/context.
132 passed, 3 skipped; sve lokalne provere prolaze. Offline MD+PDF CLI E2E
proverava kopirani indeks, ćirilicu i PDF page citate.
Mini baseline: Recall@5=1.0, MRR@10=1.0 na 16 document-level razvojnih
pozitivnih upita; 2/4 negativna daju rezultate. Realni PDF smoke: 3/3
očekivane stranice na prvom mestu. [Granice](RETRIEVAL.md).

PDF commit abae50f ima uspešan Windows/Linux Python 3.11/3.13 CI:
https://github.com/NemanjaZelic/RAGForge/actions/runs/41278248319

Slede RF-009 izbor i pilot CPU query modela/dense backend-a, pa RF-004
bundle integritet i RF-005 build/use. Širi RF-006 benchmark ostaje uslov.
Bundle build/use još nisu implementirani. Pravi dense/hybrid
ostaju obavezan deo v0.1 prema RELEASE-SCOPE.md.
