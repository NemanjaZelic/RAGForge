# RAGForge — važeći radni plan

Ovo je ulazna tačka za razvoj. Poslednja dopuna: 2026-11-01.

1. [Originalni plan](RAGForge-Project-Plan.md) — neizmenjena polazna specifikacija.
2. [Usvojeni obim v0.1](RELEASE-SCOPE.md) — obavezan tekstualni PDF i hybrid;
   default balanced, BM25 kao brza runtime opcija, OCR kasnije.
3. [Jasan pregled izmena](PLAN-CHANGES.md) — prihvaćene promene i status.
4. [Pregled plana](PLAN-REVIEW.md) — procena i predložena pojednostavljenja.
5. [Arhitektonske odluke](ARCHITECTURE.md) — radni ugovori i granice.
6. [Optimizacija prilagođena hardveru](OPTIMIZATION-PLAN.md) — korisnička dopuna
   sekcija 4.3/8 i Faze 6: četiri nivoa obima; trajanje se procenjuje merenjem,
   Max ima najmanje 8 h automatskog budžeta.
7. [Testiranje na stvarnoj dokumentaciji](TESTING-PLAN.md) — 3–7 raznovrsnih
   korpusa, golden pitanja i zasebna provera proizvoda; pilot 3 × 30 pitanja.
8. [Backlog](BACKLOG.md) — operativni zadaci i uslovi prihvatanja.
9. [Stanje pripreme](PREPARATION.md) — šta je stvarno završeno i provereno.

Optimizer je planiran, nije implementiran. Nema fiksnih vremena po nivoima.
Procena uzima u obzir stvarni CPU/GPU, memoriju, disk, korpus i planirane probe.
Za Max pod od 8 h ne sprečava opravdan raniji kraj pri potvrđenoj konvergenciji
u definisanom prostoru, iscrpljenom prostoru ili eksplicitnom prekidu.
Ne obećava se globalni optimum ili garantovan rast kvaliteta.
Osnovni bundle se dobija pre optimizacije i ostaje upotrebljiv nezavisno od nje.

Redosled je lokalni v0.1 sa MD/TXT/HTML/tekstualnim PDF ulazom i stvarnim
BM25+dense/hybrid engine-om, zatim agent integracije, pa mrežni/compute adapteri.
BM25-only međukorak nije završeni v0.1. Osnovna evaluacija dolazi uz prvu pretragu.
Ostale ranije preporuke korisnik je prihvatio; PDF i hybrid se ne odlažu.
Važeći usvojeni obim je u RELEASE-SCOPE.md, koji ima prednost pri neslaganju.
Optimizer je odvojeni opcioni završni korak; njegova prva verzija može raditi
lokalno bez čekanja cloud ili serverless podrške.
