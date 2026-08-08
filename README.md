# Når starter filmen egentlig?

Kinoprogrammet for Nordisk Film Kino i Oslo, med reklameblokka trukket fra — så du
vet når selve filmen begynner, ikke bare når lyset dempes.

NFkino annonserer starttiden på *visningen*. Filmen selv starter et kvarters tid
senere. Denne siden henter spilletiden («Lengde») og alle Oslo-visningene fra
nfkino.no og regner:

    filmstart = annonsert tid + reklame
    slutt     = filmstart + spilletid

Kontroll mot en ekte billett: *Her Private Hell* på Klingenberg, annonsert 20:45,
«Slutter 22:52» = 127 min. Spilletid 1t 49m = 109 min → **18 min reklame**, og
filmen begynner 21:03.

## Hvordan det henger sammen

* `scrape.py` — henter og parser nfkino.no, skriver `program.json`. Kun Python 3
  standardbibliotek, ingen avhengigheter.
* `.github/workflows/update.yml` — kjører scraperen hver 6. time og committer
  `program.json` hvis noe har endret seg.
* `index.html` — hele frontenden. Leser `program.json` fra samme origin, så ingen
  CORS-triksing.

Reklameanslaget er 18 minutter som standard. Under «Reklametid og kalibrering»
kan du skrive inn annonsert tid og «Slutter»-tiden fra en billett, så regnes
nøyaktig reklametid ut for den kinoen. Innstillingene lagres i nettleseren og i
adressen.

## Kjøre lokalt

    python3 scrape.py --out program.json
    python3 -m http.server 8000
    # åpne http://localhost:8000

## Merk

* Scheduled workflows på GitHub slås av automatisk hvis repoet er helt uten
  aktivitet i 60 dager. Får du varsel om det, kjør jobben manuelt under
  **Actions → Oppdater kinoprogram → Run workflow**, så er den i gang igjen.
* Uoffisiell side. Data hentes fra nfkino.no; de individuelle visningssidene
  (som har «Slutter»-tiden) er sperret i robots.txt og røres ikke.
