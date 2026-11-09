# Završni korak: dokumentacija kao skill za agenta

Glavni rezultat RAGForge-a je agent koji može da pronađe i pročita potrebnu
dokumentaciju, a zatim odgovori sa izvorima. Priprema baze daje podatke i alate;
skill govori agentu **kada i kako da ih koristi**.

## Jedna komanda posle build-a

Linux:

```bash
bash ragforge.sh agent
```

Windows:

```powershell
.\ragforge.cmd agent
```

Komanda pamti poslednji uspešan build i ispisuje gde su skill, MCP konfiguracije
i `INSTALL.md`. Za postojeći paket koristi `agent --bundle "/putanja/do/baze"`.
Svako generisanje ide u novi direktorijum `agent/<verzija>/`; postojeća podešavanja
klijenata se ne menjaju. Samostalni napredni ekvivalent je `ragforge integrate`.

## Šta dobijaš

```text
agent/<verzija>/
  skills/<ime>/SKILL.md
  skills/<ime>/agents/openai.yaml
  skills/<ime>/references/collection.json
  skills/<ime>/references/tool-usage.md
  mcp.json
  codex.toml
  INSTALL.md
```

`SKILL.md` je glavni deo: aktivacija za pitanja o dokumentovanim API-jima,
podešavanjima, greškama, ponašanju i postupcima, uključujući pisanje koda koji
zavisi od tih činjenica. Uputstva vode od `search_docs` do čitanja vraćenog teksta,
po potrebi `fetch_context`, dodatnih pretraga za zasebne činjenice i odgovora sa
putanjama/stranicama/linijama izvora. Ako dokaz nedostaje ili postoje protivrečne
verzije, agent treba to da kaže. Ocena rangiranja nije verovatnoća tačnosti.

Za dokumentaciju na drugom jeziku skill navodi podržani način upita ili vernog
prevoda, bez skrivenog servisa za prevođenje. Ne traži pretragu za nepovezane
zadatke i ne ponavlja već dovoljne izvore. Tekst dokumentacije ostaje nepoverljiv
podatak, odvojen od instrukcija agenta.

## Povezivanje sa klijentom

**Codex / OpenAI lokalni klijenti:** skill folder kopiraj u projektni
`.agents/skills/`, a blok iz `codex.toml` dodaj u postojeći projektni
`.codex/config.toml` ili korisnički `~/.codex/config.toml`. Sačuvaj ostala
podešavanja. Posle ponovnog otvaranja proveri `/mcp`; skill se može odabrati
po zadatku ili eksplicitno kao `$ime-skilla`.
[Zvanična skill dokumentacija](https://learn.chatgpt.com/docs/build-skills) i
[MCP podešavanje](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

**Claude Code:** skill folder kopiraj u `.claude/skills/`, a server iz `mcp.json`
spoji sa postojećim `.mcp.json` projekta. Posle standardnog odobrenja i provere
`/mcp`, skill može da se odabere po zadatku ili pozove kao `/ime-skilla`.
[Zvanični skills format](https://code.claude.com/docs/en/skills) i
[MCP format](https://code.claude.com/docs/en/mcp).

Za druge klijente koristi `mcp.json` i njihov podržani mehanizam za skill ili
instrukcije. Učitavanje MCP konfiguracije samo po sebi ne instalira skill.
Web chat ne dobija pristup lokalnom procesu prostim upload-om skill fajla;
potreban je klijent/connector koji podržava taj pristup. Ovaj generator ne
pokreće HTTP deployment niti poziva Claude/OpenAI API.

## Provera i ažuriranje

Postavi agentu konkretno pitanje iz dokumentacije. Proveri da koristi alat,
čita stvarni rezultat i navodi postojeći izvor; ako deo odgovora zavisi od
okolnog teksta, treba da zatraži kontekst. Eksplicitan poziv skill-a pomaže pri
prvoj proveri povezivanja. Automatski izbor zavisi od klijenta i modela.

Posle novog build-a, pomeranja baze ili promene interpretera ponovo generiši
agent paket i ažuriraj/restartuj povezani server. Konfiguracija namerno pokazuje
na jednu nepromenljivu verziju baze. Duži startup limit u Codex profilu omogućava
verifikaciju velikog paketa; nije tvrdnja o brzini upita.

Generator i profili proveravaju se validacijom YAML/TOML formata i stvarnim
MCP pozivima za pretragu i čitanje konteksta. To ne predstavlja novu nezavisnu
evaluaciju autonomnog Claude/OpenAI agenta niti potvrdu benchmark ciljeva.
