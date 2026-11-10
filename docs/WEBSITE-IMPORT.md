# Uvoz dokumentacije sa sajta

Umesto foldera sa dokumentima možeš da proslediš javni URL:

```bash
bash ragforge.sh build --url "https://example.org/docs/"
bash ragforge.sh agent
```

Windows PowerShell:

```powershell
.\ragforge.cmd build --url "https://example.org/docs/"
.\ragforge.cmd agent
```

Setup se pokreće jednom kao i za lokalne dokumente. `--url` eksplicitno preuzima
izvore, zatim koristi isti lokalni builder, model za pretragu i reranker. Ne poziva
LLM servis i ne šalje dokumente drugima. Posle build-a pretraga i MCP rade offline.
Završni `agent` korak i dalje generiše skill i konekciju za agenta; instaliraj oba.

## Šta ulazi u snimak

Importer prati obične HTML linkove unutar istog konačnog origin-a i izabranog
podstabla putanje. URL `/docs/` obuhvata `/docs/...`; URL datoteke, na primer
`/docs/index.html`, obuhvata njen direktorijum. Početno preusmeravanje može da
odredi konačan javni domen. Kasniji linkovi i preusmeravanja ostaju u tom opsegu.
Fragmenti se uklanjaju, query parametri ostaju. HTTP preusmeravanje sa HTTPS-a se
odbija. `robots.txt`, zabrane praćenja i traženi razmak između poziva se poštuju.

Podržani su statički HTML/XHTML, Markdown, tekst i PDF sa tekstom. Standardni
UTF-8 se koristi za indeksiranje; podržani deklarisani ASCII/Latin-1/Windows-1252
tekst se konvertuje u UTF-8. PDF se čuva bez konverzije. Skripte se ne izvršavaju;
slike, CSS, video i druge pomoćne datoteke se ne preuzimaju. JavaScript aplikacije,
login/cookie sajtovi, proxy-only mreže i privatne/mrežne IP adrese nisu podržani.
Za njih koristi eksplicitno izvezen lokalni folder. OCR nije deo ovog koraka.

## Granice i nepotpun uvoz

Podrazumevano je najviše 100 uspešno preuzetih stranica i dubina dva linka od
početne stranice. Dubina nula uvozi samo početni dokument. Promeni ih po potrebi:

```bash
bash ragforge.sh build --url "https://example.org/docs/" --site-max-pages 300 --site-max-depth 4
```

Gornje granice su 1000 stranica i dubina 10. Pojedinačan odgovor i konvertovan
izvor imaju limit 32 MiB, zbir preuzetih odgovora i zbir indeksiranih izvora po
512 MiB. Postoji limit otkrivanja 10.000 URL-ova, I/O rok po zahtevu do 20 s i
budžet uvoza 600 s, proveravan između zahteva. DNS može zavisiti od OS timeout-a.
Podrazumevani razmak je najmanje jedna sekunda između početaka zahteva ka origin-u;
robots pravila mogu da ga povećaju. Ove granice se odnose na preuzimanje;
izgradnja indeksa ima svoje postojeće limite.

Greška dokumenta, vremensko/stranično ograničenje ili prekinuto otkrivanje linkova
obeležavaju snimak kao nepotpun. Izabrana dubina i izuzeci robots/opseg/format
predstavljaju traženi opseg, pa `complete` ne znači da je kopiran ceo sajt.
Komanda podrazumevano ne gradi aktivnu bazu iz nepotpunog snimka. Čuva izveštaj i
prethodnu aktivnu bazu. Pregledaj `import-report.json`, povećaj granice ili svesno
prihvati nepotpun snimak opcijom `--allow-partial-site`.

## Sačuvani izvori i ponovno korišćenje

Svako preuzimanje dobija novi direktorijum `data/web/<vreme-id>/`:

- `pages/`: dokumenti za lokalni build, imenovani hash-om konačnog URL-a;
- `web-sources.json`: originalni URL-ovi, vreme snimka, opseg, status i SHA-256
  preuzetih i indeksiranih bajtova;
- `import-report.json`: brojevi i razlozi nepotpunog preuzimanja.

Ovi korisnički podaci su izuzeti iz Git-a. Novi uvoz ne prepisuje stari snimak.
Za offline ponavljanje build-a koristi sačuvani `pages` folder; susedni katalog
se automatski uključuje i proverava:

```bash
bash ragforge.sh build "data/web/<vreme-id>/pages"
```

Za ranije nepotpun snimak i ovde je potrebno eksplicitno `--allow-partial-site`.
Katalog se kopira u prenosivi bundle i ulazi u njegov inventar i identitet.
Verifier odbija promenjen katalog ili nepoklapanje URL zapisa sa dokumentima.
`search_docs` i `fetch_context` vraćaju dodatni `source.url` za ove dokumente;
putanje i dostupne stranice/linije se i dalje vraćaju. Skill upućuje agenta da
citira URL kada postoji. To je snimak u navedenom trenutku, ne potvrda da se živi
sajt od tada nije promenio. Lokalni dokumenti zadržavaju prethodni JSON oblik.

HTTPS koristi normalnu proveru sertifikata. Ako organizacija koristi svoj CA,
postavi njegov pouzdani PEM preko standardnog `SSL_CERT_FILE` pre pokretanja.
Ne postoji opcija za isključivanje TLS provere.
