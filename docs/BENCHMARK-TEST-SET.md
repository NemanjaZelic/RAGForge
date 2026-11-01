# Pripremljeni pilot test set — RF-006B

> Ažuriranje 2026-11-01 po korisničkoj ispravci: ciljni test je velika zbirka poput 3GPP specifikacija. [LARGE-BENCHMARK-PLAN.md](LARGE-BENCHMARK-PLAN.md) ima prednost za obim korpusa i trenutni status. Mali pilot služi samo za smoke/regresione provere.

Datum: 2026-11-01. Projekat, retrieval i pytest nisu pokretani u ovom zadatku.

Napravljen je [pilot-v1](../tests/fixtures/benchmarks/pilot-v1/README.md) prema
[planu testiranja](TESTING-PLAN.md): **3 stvarna korpusa × 30 pitanja**.

| Korpus | Izvor | Format |
| --- | --- | --- |
| uv vodiči | 0.9.5, projects/scripts/tools i README | MD + README sa TXT ekstenzijom, bez izmene bajtova |
| Python tutorijal | 3.13.0, četiri kompletna rendered HTML poglavlja | HTML, kod i numerička tabela |
| HTTP Semantics | Originalni RFC 9110, 194 fizičke stranice | PDF sa tekstom |

Ukupno: 72 pitanja sa očekivanim činjenicama i dokazima, 18 pitanja bez
odgovora u zamrznutom inputu, 41 dokazni raspon. Svaki od dev/tuning/test
delova sadrži po 30 pitanja; po korpusu i delu ima 8 pozitivnih i 2 negativna.
Parafraze i povezane oznake ostaju zajedno. Pitanja uključuju kod, tabele,
ograničenja, poređenja, parafraze i više potrebnih grupa dokaza.

Izvori su lokalno preuzeti/fiksirani u
`D:/RAGForge/data/benchmarks/pilot-v1`, odvojeno od gold oznaka, build izlaza
i rezultata. Raw/input bajtovi imaju SHA-256; originalni raw fajlovi su
read-only. Postojeći `/data/` ignore sprečava commit izvornih dokumenata.
Metapodaci sadrže URL, reviziju, datum, transformacije i reference za prava.

Dodati su samostalni validator podataka, eksplicitni alat za pribavljanje
pinovanih izvora, 10 pytest slučajeva za integritet test seta, 8 kontrolisanih
fixture slučajeva sa 9 input fajlova i 19 budućih proizvodnih scenarija.
Testovi podataka ne uvoze RAGForge i ne simuliraju rezultate pretrage.
Scenariji za stvarni proizvod su označeni `not_run`; kasnije etape imaju
zasebne preduslove. Izvršene su samo statičke provere podataka i koda.

**Status oznaka je `ai_draft`.** Svih 90 pitanja zahteva nezavisan pregled;
nijedno nije podobno za strogi završni score. Vizuelno je provereno svih
14 PDF stranica korišćenih za dokaze, ali to nije nezavisna potvrda oznaka.
`test` deo je rezervisan i još nije zaključan. Ne postoje novi rezultati
retrieval kvaliteta, benchmark latencije ili memorije.

Izbor korpusa je dokumentovan pilot prema formatu, obimu i dostupnosti,
bez gledanja retrieval rezultata. Nije nasumičan reprezentativni uzorak;
seed se koristi za ponovljivu podelu grupa pitanja. Za proširenje ostaju
stvarna neujednačena dokumentacija, stvarni neengleski korpus i ceo korpus
van razvoja podrazumevanih parametara. Prevedena pitanja nisu novi korpus.

RF-006B time ima pripremljene izvore i nacrt pitanja. Ne zatvara se kao
potpuno završen dok ne bude nezavisno pregledan; RF-006C, proizvodni E2E,
BM25/dense/hybrid merenje i release gate ostaju neizvršeni.

Uputstva, pravila dokaznih lokacija, podele, metrika i budućeg pokretanja:
[tests/fixtures/benchmarks/pilot-v1/README.md](../tests/fixtures/benchmarks/pilot-v1/README.md).
Originalni projektni plan, runtime kod i postojeći testovi nisu menjani.
