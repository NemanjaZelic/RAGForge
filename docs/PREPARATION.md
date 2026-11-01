# Priprema projekta — završeno

Datum: 2026-11-01. Kanonska lokacija: `D:\RAGForge`.

## Šta je urađeno

Original priloga je sačuvan bez izmena kao `docs/RAGForge-Project-Plan.md`.
SHA-256: `1023b17b63b39957b71dfbf490099c89537f34434bdb16fbb907cc478dde6524`.
Git atribut sprečava normalizaciju njegovih krajeva redova.

- PLAN-REVIEW.md: razumevanje proizvoda, kritika i predložene izmene.
- ARCHITECTURE.md: početne odluke, identiteti i granice ugovora.
- RELEASE-SCOPE.md: usvojeni v0.1 cilj obavezno uključuje tekstualni PDF i
  dense/hybrid, sa balanced default-om i BM25 runtime opcijom. OCR je kasnije.
  Trenutna Faza 0 i njene minimal-only šeme još ne ispunjavaju taj release cilj.
- BACKLOG.md: proverljivi zadaci i redosled implementacije.
- PROJECT-PLAN.md: ulazna tačka radnog plana; PLAN-CHANGES.md navodi svaku
  preporuku, razlog i status. OPTIMIZATION-PLAN.md definiše četiri nivoa obima,
  ETA prema merenjima na hardveru i automatski Max budžet od najmanje 8 h,
  uz dokumentovane uslove ranijeg završetka. Fiksni sati po nivoima su ukinuti.
  Optimizacija je specifikovana, ali još nije implementirana.
- Jedan Python paket sa Typer CLI-jem, Pydantic modelima i generisanim šemama.
- Mini-korpus: 6 dokumenata i 20 razvojnih upita; 16 pozitivnih i 4 bez odgovora.
- Lokalni Git repozitorijum, grana main; bez commit-a, remote-a ili objave.
- CI konfiguracija za Linux/Windows i Python 3.11/3.13; GitHub CI još nije izvršen.

## Okruženje

| Stavka | Provereno |
|---|---|
| Git | 2.46.0.windows.1 |
| Python | 3.13.5 (postojeći sistemski interpreter) |
| SQLite | 3.49.1, FTS5 uspešno testiran |
| uv | 0.13.6 u .tools |
| Projekat/venv | D:\RAGForge / D:\RAGForge\.venv |
| Cache i temp | D:\RAGForge\.cache |
| Dev alati | pytest 9.2.0, ruff 0.17.3, mypy 1.20.2 |
| Runtime zavisnosti | typer 0.27.3, pydantic 2.14.2 |
| Lockfile | uv.lock |

Sistemski Python je već instaliran na C; projekat i njegova nova okruženja,
preuzeti alati, cache i privremeni build fajlovi su na D.
Node nije potreban za ovu osnovu. Docker i uv ranije nisu bili u PATH-u;
Docker nije instaliran za ovaj korak i nije uslov za lokalni minimalni profil.
Modeli, GPU biblioteke, MCP/HTTP i PDF zavisnosti nisu instalirani.

## Lokalna validacija

- 39 pytest testova prolazi.
- Ruff lint i format provera prolaze.
- Mypy strict prolazi.
- Generisane šeme odgovaraju modelima.
- Stvarne komande --help, --version i doctor rade.
- CLI help/doctor/schema podprocesi prolaze sa blokiranim Python socket/DNS
  pozivima i potvrđenim aktivnim test guard-om.
- Izgrađeni su wheel i source distribution; proveren sadržaj bez .cache,
  .venv, .tools i .git direktorijuma.

Ove provere pokrivaju Fazu 0 na ovom Windows/Python 3.13 okruženju.
Nisu dokaz završenog offline build/retrieval toka, kvaliteta pretrage ili
kompatibilnosti ostalih OS/Python kombinacija. Te provere su u backlog-u.

## Nastavak rada

```powershell
cd D:\RAGForge
.\scripts\dev.ps1 check
.\scripts\dev.ps1 run ragforge doctor
```

Za vraćanje zavisnosti iz lockfile-a: `scripts/dev.ps1 setup` (potrebna mreža
ako paketi nisu u cache-u). Za svakodnevne provere i CLI: wrapper koristi već
instalirano okruženje, bez automatskog preuzimanja i sinhronizacije.

Prvi razvojni zadatak je RF-000: proširiti minimal-only ugovore za balanced
profil i metode pretrage, zatim RF-001 skeniranje mešanog korpusa.
Parser/chunker, RF-007 PDF i RF-009 dense/hybrid su obavezni F1/v0.1 zadaci.
BM25-only je interni međukorak i opciona pretraga, ne završen v0.1 proizvod.
Build/use još nisu implementirani i nisu izloženi kao lažno funkcionalne komande.
