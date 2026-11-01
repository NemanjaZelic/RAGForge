# Dopuna plana — optimizacija prilagođena hardveru

Status: planirano, nije implementirano. Datum: 2026-11-01.
Ova dopuna proširuje sekcije 4.3, 8 i Fazu 6 originalnog plana.
Original ostaje sačuvan bez izmena; ova specifikacija i BACKLOG.md određuju
novi obim rada. Inicijativa: korisnički predlog četiri nivoa optimizacije.
Revizija: obim određuje nivo, vreme se procenjuje na hardveru; Max ima pod od 8 h.

## Procena izvodljivosti

Izvodljivo je automatski porediti retrieval konfiguracije za konkretan korpus.
To je podešavanje pipeline-a, a ne treniranje novog jezičkog modela.
Prvi oblik koristi postojeći v0.1 balanced/hybrid engine i ograničen skup
konfiguracija; minimal/BM25 ostaje podržana opcija. Širi izbor modela i
rerankera dodaje se kasnije. [RELEASE-SCOPE.md](RELEASE-SCOPE.md) određuje
obavezni PDF i dense/hybrid obim proizvoda pre samog optimizer-a.

Nivoi određuju dubinu pretrage, a trajanje i budžet se procenjuju prema
hardveru i dokumentaciji. Bez konkretnog korpusa, evaluacionih pitanja i
kalibracije ne postoji poštena procena trajanja ili porasta kvaliteta.
U ovoj dopuni nisu izvršeni benchmark-i.

Za malu dokumentaciju početna konfiguracija može biti gotova za sekunde ili
minute; nema razloga namerno trošiti sat. Na velikom korpusu i jedna ponovna
izgradnja može premašiti sat. Duži budžet daje više prilika za proveru, ne
garantovano bolji rezultat. Max treba biti opcija za opravdano veliki posao,
a ne podrazumevana preporuka.

## Mesto u korisničkom toku

`documents → build → usable bundle → optional optimize → new validated bundle → use/integrate`

Korisnik prvo dobija upotrebljiv osnovni paket. Optimizacija je poseban,
dobrovoljan završni korak, pre ili posle prve integracije. Nije uslov za upit,
ne pokreće se implicitno i ne produžava svaki build za sate.
Planirani `--profile auto` iz originala kasnije može biti prečica ka istom
optimizer-u, bez zasebne implementacije ili promene ovog podrazumevanog toka.

Postoje tri odvojene dimenzije:

- `profile=minimal|balanced|quality`: dozvoljene retrieval komponente.
- `effort=first-try|light|high|max`: dubina pretrage i obim provere.
- `compute=local|ssh|...`: gde se posao izvršava, kada odgovarajući runner postoji.

Veći effort ne uključuje automatski GPU, veći model, mrežu ili plaćeni compute.
High/max ostaju dozvoljeni za minimal/BM25. Završetak pretrage prati jasne
kriterijume u nastavku; isti bundle i ugovor ostaju cilj svih nivoa.

## Četiri nivoa određuju obim rada

| Nivo | Obim optimizacije | Vreme |
|---|---|---|
| First try (`first-try`) | Jedna razumna početna konfiguracija, validacija i početno merenje; bez pretrage parametara. | Procena na stvarnom hardveru i korpusu. |
| Malo optimizacije (`light`) | Mali skup najkorisnijih promena, jeftine probe i ograničena potvrda finalista. | Automatska procena prema planiranom poslu. |
| High (`high`) | Širi prostor parametara, adaptivni izbor i potpunije merenje finalista. | Automatska procena prema planiranom poslu. |
| Max (`max`) | Najdublja opravdana pretraga podržanih konfiguracija, ponovljene provere i robusnost. | Automatski budžet najmanje 8 h, čak i na najbržem hardveru. |

**Ukinuti su fiksni podrazumevani maksimumi 1/6/16/72 h.**
Jači hardver obrađuje isti izabrani obim brže; nivo se ne smanjuje samo zato
što je mašina brza. Za Max bolji hardver može omogućiti dodatne korisne probe
unutar njegovog budžeta. Ne uvoditi besmislena ponavljanja samo radi potrošnje vremena.

First try znači razuman opšti početak, ne univerzalno optimalne parametre.
Izbor Max ne uključuje automatski GPU, veće modele ili plaćeni compute.

## Procena na dostupnom hardveru

Planer koristi merenja konkretnog posla, ne samo naziv CPU/GPU-a:

1. Evidentirati dostupne CPU jezgre, slobodan RAM, podržan GPU/VRAM, storage i
   dozvoljen paralelizam. Hardverski identitet služi kao ključ rezultata merenja,
   bez serijskih brojeva i telemetrije; sam po sebi ne daje trajanje.
2. Analizirati veličinu i strukturu korpusa, formate, dužine sekcija/chunkova,
   potrebne modele i već postojeće validne cache rezultate.
3. Na istom compute hostu zagrejati model ako postoji i izmeriti parsiranje,
   indeksiranje, embeddings i evaluaciju na više reprezentativnih uzoraka.
   Uračunati učitavanje modela i disk I/O; ne ekstrapolirati iz samo jednog
   vrlo malog ili lakog fajla.
4. Napraviti verzionisan plan kandidata, rundi i završnih provera za izabrani
   effort. Uračunati deljene indekse/cache, memorijska ograničenja i realno
   ostvariv paralelizam. Paralelni broj jezgara nije automatski linearno ubrzanje.
5. Prikazati očekivano trajanje kao raspon, nivo nesigurnosti, planirani obim i
   automatski budžet sa rezervom. Procena se ažurira na osnovu završenih pokušaja;
   to nije garantovani rok.
6. Budžet i obim se ne povećavaju neprimetno tokom izvršavanja. Promena plana,
   hosta ili ukupnog limita beleži se; povećanje raspoloživog vremena je eksplicitno.

Konceptualno: procenjeno vreme = kalibracija + trajanje pretrage uz stvarno
ostvariv paralelizam i cache + finalna izgradnja/provera/izvoz.
Automatski budžet koristi konzervativnu gornju procenu sa rezervom.
Za Max važi `B_auto = max(8 h, procenjeni budžet sa rezervom)`.
Za ostale nivoe nema fiksnog broja sati.

Max pod od 8 h odnosi se na planirani ukupni budžet posla. Posao nastavlja da
traži korisne konfiguracije do svog roka ako još nema dovoljno dokaza da treba
stati. Ovo ne znači garantovanih osam sati rada, niti čekanje kada je pretraga
zaista završena. Kraj pre 8 h je dozvoljen po pravilima u sledećoj sekciji.

Korisnik može zadati zaseban `--max-time` kao čvršću operativnu granicu.
Ako je limit manji od procenjenog posla, jasno prikazati koji deo pretrage
neće stati u vreme; završetak na limitu nije konvergencija.
Za `effort=max` limit kraći od 8 h se odbija uz objašnjenje i predlog nižeg
nivoa. Korisnik u svakom trenutku može sam prekinuti posao.
Nema ugrađenog podrazumevanog plafona od tri dana: sporiji hardver i veći korpus
mogu zahtevati duže, a prikaz procene prethodi pokretanju pune pretrage.
Bez merenja se ne objavljuje izmišljena procena.

Budžet obuhvata kalibraciju/preflight, baseline, pokušaje, finalnu proveru i
izvoz. Pri `estimate` pa `run` proverena kalibracija istog posla se ponovo
koristi i njeno vreme ulazi u ukupan obračun; ne daje se novi besplatan budžet.
Ranije završen osnovni build nije retroaktivno deo optimize budžeta.
Budžet je aktivno wall-clock vreme posla, ne zbir CPU/GPU sati procesa.
Remote procena meri remote build host; ciljana runtime latencija mora se
posebno izmeriti na mestu korišćenja.

## Šta znači optimalno i kada se završava ranije

U opštem slučaju ne obećavati globalno optimalne parametre. Izveštaj kaže
**najbolja proverena konfiguracija unutar definisanog prostora i dostupnih
pitanja**, uz granice i nesigurnost.

Za Max je kvalitetom opravdan kraj pre 8 h dozvoljen ako:

- iscrpljen je čitav unapred definisan konačan prostor validnih konfiguracija,
  a najbolji kandidat je potpuno proveren; ili
- ispunjen je unapred definisan kriterijum konvergencije: minimalna pokrivenost
  različitih porodica parametara, ponovljena potvrda najboljih na punom tuning
  skupu i dovoljno stabilan izostanak smislenog dobitka pri daljem proširenju.
  Proveriti i resursne granice i izvršiti zasebnu završnu evaluaciju.

Pragove pokrivenosti, minimum pokušaja, patience/min-delta i način provere
zapisati u verzionisanu politiku pre izvršavanja. Par neuspešnih pokušaja,
istek početne kratke liste ili jedan visok skor nisu dovoljan dokaz.
Prijaviti `converged_within_scope` ili `search_space_exhausted`, a ne tvrdnju
da je pronađen univerzalni optimum. Kada nema odgovarajućih oznaka, nema osnova
za ovakvu quality konvergenciju; prvo prijaviti nedostatak uslova.

Svi nivoi se prekidaju na korisnikov zahtev, istekom dozvoljenog budžeta,
greškom ili nedostatkom resursa; to su zasebni razlozi, ne potvrda optimalnosti.
Niži nivoi mogu završiti i kada odrade svoj manji plan. Max početnu listu
proširuje korisnim kandidatima dok ne ispuni navedeni kriterijum ili rok.

## Šta se optimizuje

| Sloj | Kandidati | Potrebna ponovna obrada |
|---|---|---|
| Chunking | veličina fragmenata, overlap, granice sekcija/koda | novi chunkovi i indeks; za dense i novi embeddings promenjenih chunkova |
| BM25/FTS5 | težine naslov/sekcija/telo, podržane varijante pripreme upita | težine uglavnom bez novog indeksa; promena tokenizacije/indeksiranog teksta zahteva rebuild |
| Dense/hybrid (postojeći v0.1 engine) | eksplicitno dozvoljen model, retrieval candidate pool, RRF konstanta | novi model traži nove embeddings; fuzija uglavnom koristi postojeće indekse |
| Reranking (kasnije) | dozvoljeni reranker, broj internih kandidata, uključeno/isključeno | tipično bez promene osnovnog indeksa, ali sa novom runtime zavisnošću |

Početna implementacija bira mali, verzionisan prostor pretrage. Ne isprobavati
pun kartesijanski proizvod i ne nuditi parametre koje backend ne podržava.
SQLite FTS5 ugrađeni BM25 ima fiksne k1=1.2 i b=0.75; njegova dokumentovana
podešavanja uključuju težine kolona. Zato k1/b nisu slider-i prvog optimizer-a.
Promena samog backend-a zbog dodatnih parametara je zasebna odluka.

Konačni top_k, maksimalna količina vraćenog konteksta i skup pitanja su isti
pri poređenju kandidata. Interni retrieval/rerank pool može da se menja uz
ograničenje latencije i memorije. Ne proglašavati kvalitet boljim samo zato
što je jedan kandidat vratio mnogo više teksta.

Optimizacija ne menja značenje originalne dokumentacije, javni retrieval
ugovor, dozvole, skill instrukcije ili mrežnu politiku.

## Odakle znamo da je konfiguracija bolja

Zajednički postupak izbora realnih korpusa, golden pitanja i završne provere
opisan je u [TESTING-PLAN.md](TESTING-PLAN.md). Optimizer koristi isti evaluator
kao proizvod; sopstveni povoljniji benchmark nije dozvoljen.

First try može raditi bez eval skupa, ali tada meri samo validnost i resurse,
ne relevantnost. Za light/high/max podrazumevano je potreban relevance skup
za konkretan korpus:
stvarna ili ručno pripremljena pitanja sa relevantnim dokumentima ili dokaznim
rasponima. Početnih 20 repo pitanja su razvojni fixture, ne dovoljan dokaz za
višednevno prilagođavanje nekoj drugoj dokumentaciji.

- Kandidati se biraju na tuning skupu; unapred zaključan test skup koristi se
  jednom za završno poređenje baseline-a i unapred izabranog pobednika.
- Srodna pitanja i parafraze drže se u istoj grupi pri podeli, kako se odgovor
  ne bi praktično ponavljao u tuning i test delu. Dokumentacija ostaje isti
  pretraživani korpus; razdvajaju se pitanja/oznake, ne nasumično sve datoteke.
- Ako nema dovoljno označenih pitanja, prikazati ograničenje i tražiti dopunu.
  Ne predstavljati automatske heuristike kao izmeren rast relevantnosti.
- Opciona sintetička pitanja mogu dati preliminarni signal samo uz eksplicitan
  izbor. Ne skidati LLM ili slati dokumente na API automatski. Izveštaj jasno
  razlikuje ljudske i sintetičke oznake; sintetički skor ne postaje tvrdnja o
  potvrđenom kvalitetu.
- Ako postoje samo relevantni document ID-jevi, prvo svesti rezultate na
  dokumente uz uklanjanje duplikata i jasno prijaviti document-level metriku.
  Takav skor ne dokazuje kvalitet konkretnog citiranog fragmenta.
- Kada chunking menja chunk ID-jeve, iste oznake se ne smeju slepo kopirati.
  Koristiti stabilne oznake dokumenta/izvornog dokaznog raspona i provereno
  mapiranje na nove chunkove. Nedovoljno precizne oznake traže dopunu.

Podrazumevani cilj: maksimizovati nDCG@10 na tuning skupu uz eksplicitne
granice p95 latencije, peak RAM-a, veličine paketa i istog output limita.
Za uporedni benchmark fiksirati top_k=10 i isti context/output limit; Recall@5
računati na prvih pet rezultata. Prijaviti i Recall@10 i MRR@10; unsupported
pitanja prikazati odvojeno.
Porediti iste merne uslove, warm/cold start i broj merenja.
Kod malog skupa ili male razlike prikazati nesigurnost, ne precizne marketinške
tvrdnje o procentu poboljšanja. Formalna statistička potvrda zahteva dovoljan
uzorak i unapred određen postupak.

Ako više kandidata daje sličan rezultat, preferirati jednostavniji/brži/manji.
Sačuvati pregled kompromisa, ne izmišljati jedan univerzalno najbolji sistem.
Ako bolji validan kandidat nije nađen, ostaviti baseline i status
`no_measured_improvement`. Ako završna provera pobednika pokaže regresiju,
zadržati baseline; ne birati sledećeg kandidata na osnovu istog test skupa.
Ponovno optimizovanje na istom već korišćenom test skupu označiti kao razvojno
poređenje, ili obezbediti novi nezavisan test za novu tvrdnju o kvalitetu.

## Predloženi algoritam

1. **Preflight:** proveriti bundle, dostupne izvore, eval oznake, lokalne modele,
   slobodan disk/RAM i compute. Prikazati šta može da se menja i efektivne limite.
2. **Baseline:** proveriti postojeći paket, izmeriti polaznu konfiguraciju,
   uzeti kratki uzorak build/query troškova i proceniti red veličine posla.
   Ako ni jedna validna konfiguracija ne staje u budžet, to jasno prijaviti.
3. **Rezerva za završetak:** unapred izdvojiti procenjeno vreme finalnog indeksa,
   testiranja i izvoza. Novu skupu probu pokretati samo ako procena plus rezerva
   staju u preostali budžet. Procena ostaje procena; finalni rezultat nije
   obećan ako nijedan kandidat ne bude potpuno završen.
4. **Jeftine promene prvo:** ponovno koristiti postojeće indekse za težine i
   fuziju, pre novih chunk konfiguracija ili embedding modela.
5. **Postepeno poređenje:** iste kandidate prvo porediti na istom determinističkom,
   reprezentativnom uzorku i istom tuning podskupu. Nezavisne rezultate iz
   različitih veličina korpusa ne tretirati kao direktno uporedive.
   Promovisati samo najbolje na veći uzorak/pun korpus.
6. **Adaptivna pretraga:** prvo ograničeni random/grid kandidati; kasnije TPE
   preko opcionog Optuna adaptera ako merenja opravdaju složenost.
   Successive halving je obrazac raspodele resursa, ne obavezna biblioteka.
7. **Finalisti:** proveriti na punom korpusu i punom tuning skupu, uz fiksne
   output granice i ponovljene latency/RAM provere gde budžet dozvoljava.
8. **Završetak:** jedan izabrani kandidat i baseline na zaključanom testu;
   verifikacija integriteta i izvoza. Novi bundle ide u novi direktorijum.
   Aktivni paket se ne menja automatski.

Optuna je kandidat za opcioni optimizer extra tek pri implementaciji.
Nema novih zavisnosti u minimalnom runtime-u zbog ovog plana.

## Izvori, cache i ponovna upotreba

Za promenu chunkinga potrebni su originalni dokumenti ili verifikovan
normalizovan snapshot, ne samo već iseckani tekstovi. `--source` mora odgovarati
hash-evima korpusa u paketu. Ako izvor nije dostupan, dozvoliti samo podešavanja
nad postojećim indeksom i prijaviti ograničen prostor pretrage.
Promenjena dokumentacija znači novi build/job, ne tiho nastavljanje starog.

Cache ključ uključuje corpus hash, parser/chunker konfiguraciju, model i
njegovu verziju/checksum, backend i relevantne verzije.
Eval cache dodatno uključuje eval skup, podelu i metriku. Performance cache
uključuje hardverski profil, driver/runtime verzije i dozvoljen paralelizam.
Latenciju ponovo meriti na stvarnom ciljnom runtime hardveru; GPU build host
nije dokaz latencije na korisnikovom laptopu.
Snapshot i cache mogu sadržati celu dokumentaciju i ne ulaze automatski u
deljivi knowledge bundle. Na ovoj mašini ostaju na D particiji.

## Budžet, prekid i nastavak

- Ograničiti istovremene pokušaje, disk/cache, RAM i compute. Više paralelnih
  pokušaja troši više compute-a iako wall-clock budžet ostaje isti.
- Svaki pokušaj ima zaseban proces i timeout. Planirati nadzor stabla procesa;
  sam `study.optimize(timeout=...)` nije zamena za kontrolu zauzetog worker-a.
- Pri isteku roka ne pokretati nove pokušaje; prekinuti predugačak worker,
  sačuvati stanje i prijaviti završetak/prekoračenje uz kratko dokumentovano
  vreme za gašenje. Ne obećavati apsolutni OS ili cloud billing hard limit.
- Za svaki završeni pokušaj transakciono sačuvati parametre, rezultat i lokaciju
  verifikovanog kandidata. Nezavršeni kandidat nikada ne postaje pobednik.
- Ctrl+C, pad procesa ili restart ne uništavaju prethodni bundle.
  Resume koristi istu verziju korpusa/eval skupa/konfiguracije. Promena hardvera
  traži novu kalibraciju i invalidaciju performance cache-a, bez automatskog
  proširenja budžeta.
- Prilikom nastavka sabirati ranije potrošeno aktivno vreme svih nastavaka
  istog posla. Pauza ne troši aktivni lokalni budžet; ne resetovati automatski
  ceo automatski budžet. Povećanje ukupnog budžeta je eksplicitan izbor.
- Udaljeni naplativi resursi mogu koštati i za vreme pauze. Njihov lifecycle
  ostaje odgovornost runner-a i ne menja se izborom optimization nivoa.
- Modeli se prethodno pribavljaju zasebno. Nema implicitnog cloud fallback-a,
  API troškova, uploada ili instalacije agent konfiguracije.

## Planirani CLI — nije implementiran

```bash
# Osnovni build vraća upotrebljiv paket pre opcione optimizacije.
ragforge build ./docs --compute local --offline --profile balanced --output ./kb

# Kratka kalibracija na postojećem hardveru i procena obima/trajanja.
ragforge optimize estimate ./kb --source ./docs --eval ./eval.jsonl --effort max --offline

# Nema fiksnih vremena u presetima; planer računa auto budžet.
ragforge optimize run ./kb --effort first-try --time-budget auto --offline
ragforge optimize run ./kb --source ./docs --eval ./eval.jsonl --effort light --time-budget auto --output ./kb-tuned --offline
ragforge optimize run ./kb --source ./docs --eval ./eval.jsonl --effort high --time-budget auto --output ./kb-tuned --offline
ragforge optimize run ./kb --source ./docs --eval ./eval.jsonl --effort max --time-budget auto --output ./kb-tuned --offline

# Opcioni korisnički plafon; Max zahteva najmanje 8 h dozvoljenog budžeta.
ragforge optimize run ./kb --source ./docs --eval ./eval.jsonl --effort max --max-time 24h --output ./kb-tuned --offline

ragforge optimize status <job-id>
ragforge optimize resume <job-id>
```

`estimate` izvršava kalibracioni uzorak i čuva izveštaj; nije isto što i
pregled hardverskih specifikacija bez rada. `run` proverava identitet kalibracije
pre ponovne upotrebe. Auto procena, efektivni budžet i korisnički plafon imaju
odvojena polja u job manifestu. Ovo su planirane komande, ne postojeći CLI.
Compute se bira odvojeno; nijedna opcija ne aktivira remote runner implicitno.

## Izlaz

Uz novi bundle, izvan deljivog artefakta podrazumevano sačuvati:

- verzionisan `optimization-report.json` i čitljiv pregled;
- početnu i izabranu konfiguraciju, metrike na tuning/test skupu, razlike i
  merne uslove, uz oznake real/synthetic i ograničenja;
- sve završene/pruned/failed pokušaje, utrošeno vreme, razlog zaustavljanja,
  automatski i efektivni budžet, ETA raspon i nesigurnost, verziju plana,
  kalibraciona merenja, preostali budžet, resume evidenciju i eventualni trošak;
- corpus/eval/split/config/model hash-eve, verzije, seed, hardver,
  granice resursa i koje komponente zahtevaju rebuild;
- status: `baseline_only`, `improved`, `no_measured_improvement`,
  `provisional`, `budget_exhausted`, `converged_within_scope`,
  `search_space_exhausted`, `interrupted` ili `failed`,
  kao odvojena polja outcome i stop_reason, ne jedna nejasna zastavica.

Query tekst, relevantni delovi dokumenata i privatne putanje ne ulaze u javni
report po defaultu. Detaljni lokalni eval podaci su eksplicitna opcija.
Generisani skill i konekcija se ne menjaju kao sporedni efekat optimizacije.

## Uslovi prihvatanja i redosled

**Prva isporuka optimizer-a:** first-try/light nad postojećim balanced/hybrid
profilom, uz opcioni minimal/BM25; nekoliko stvarnih kandidata, isto baseline
poređenje, stvarni timeout i checkpoint/resume.
**Zatim:** high/max scheduler, širi adaptivni izbor, dodatni modeli i rerankeri.
Dense/hybrid engine već je obavezni deo v0.1; kasnija faza ovde opisuje njegovu
optimizaciju, ne odlaganje njegove implementacije.
Osnovna evaluacija ostaje ranije u Fazi 1; optimizer ostaje završni opcioni
korak Faze 6 i ne blokira lokalni MVP.

Prihvatni testovi:

- Četiri preseta imaju dokumentovane limite; nijedan ne uključuje plaćeni compute.
- Virtuelni sat simulira 8 h pod i duge poslove bez višesatnih CI testova.
- Isti obim rada na različitoj izmerenoj brzini daje različite ETA procene;
  Max automatski budžet nikada nije kraći od 8 h.
- Max sa korisničkim plafonom ispod 8 h se odbija; konvergencija, prekid i
  budget exhaustion su različiti razlozi završetka.
- Kratka stagnacija ne završava Max pre 8 h; dokumentovan kriterijum
  konvergencije ili iscrpljen ceo prostor dozvoljavaju raniji kraj.
- Zaustavljanje i nastavak poštuju ukupan budžet; popunjen cache ne menja
  hash-eve/oznake niti dozvoljava curenje test rezultata u izbor kandidata.
- First try ne radi parameter search; ne čeka proizvoljan broj sati.
- Bez pouzdanog eval-a nema tvrdnje o potvrđenom kvalitetu; sintetički
  režim je jasno preliminaran i eksplicitan.
- Promena chunkinga ne koristi zastarele chunk ID oznake.
- Poređenje koristi iste top_k/output limite; document-level rezultat ne
  predstavlja se kao preciznost dokaznog fragmenta.
- Nema poboljšanja ili prekid zadržavaju postojeći validan bundle.
- Novi paket prolazi isti integrity i retrieval contract test kao običan build.
- Izveštaj je dovoljan za audit, bez tajni i privatnog sadržaja po defaultu.

## Tehnička osnova i izvori

Provereno 2026-11-01. Ovi izvori potvrđuju obrasce i ograničenja, ne trajanje
RAGForge poslova ili obećan rast kvaliteta.

- [Optuna Study](https://optuna.readthedocs.io/en/stable/reference/generated/optuna.study.Study.html):
  ograničenje pokušaja/vremena i sampler; konkretni worker deadline-i su deo
  našeg scheduler-a.
- [Successive halving](https://optuna.readthedocs.io/en/stable/reference/generated/optuna.pruners.SuccessiveHalvingPruner.html):
  postepena dodela resursa; maksimalan resurs i smislene runde definiše aplikacija.
- [Optuna više ciljeva](https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/002_multi_objective.html):
  kvalitet i resursi mogu se porediti zajedno; u prvoj verziji preferiramo
  jedan quality cilj uz eksplicitne resursne granice.
- [Odvajanje izbora parametara i konačne evaluacije](https://scikit-learn.org/stable/modules/cross_validation.html):
  korišćenje istog test skupa za izbor i potvrdu parametara vodi pristrasnom skoru.
- [SQLite BM25](https://www.sqlite.org/fts5.html#the_bm25_function):
  fiksni k1/b i podržane težine kolona.
- [IR metrike](https://ir-measur.es/en/latest/measures.html):
  precizno navesti metriku, cutoff i nivo oznaka.

## Otvorene odluke pre implementacije

Tačan prostor kandidata, patience/min-delta vrednosti, veličina uzoraka,
rezerva finalizacije i model ETA procene usklađuju se sa RF-006 merenjima.
Ovi detalji ne zahtevaju odluku sada i ne predstavljaju razlog da se odloži MVP.
