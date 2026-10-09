# Test- og kontrolrapport

**Kryds & Tværs Generator 1.0.0 · 8. oktober 2026**

## Faktisk afprøvet miljø

| Komponent | Afprøvet værdi |
|---|---|
| Operativsystem | Linux i udviklingsmiljøet |
| Python | CPython 3.13.5 |
| PDF-bibliotek | ReportLab 4.4.9 |
| Grafisk brugerflade | Tkinter/Ttk med Xvfb som virtuel skærm |
| PDF-kontrol | Rendering til PNG og visuel kontrol; tekst-/geometrikontrol med PyMuPDF |

Minimumsversionen i programmet er Python 3.11. Python 3.11, 3.12 og 3.14 er ikke særskilt afprøvet. Windows-startfilen og macOS-instruktionerne er medleveret, men der er ikke gennemført kørsel på Windows eller macOS. Dialoger til filvalg er erstattet af faste midlertidige filstier i den automatiske GUI-test.

## Automatiserede kerne- og PDF-tests

Kommando:

```bash
python -m unittest discover -s tests -v
```

**Resultat: 39 tests bestået.**

Testene omfatter normalisering, danske bogstaver, tekstgrænser, flere forklaringer pr. ord, dubletkontrol, Unicode-søgning, mønstersøgning, redigering/sletning, CSV-import/-eksport, validering før import, transaktionsrollback, databasebackup, gemte krydsord og uafhængige kopier af forklaringer.

Placeringskontrollen testes for korrekte krydsninger, grænseoverskridelser, forkerte bogstaver, parallel overlapning, dublerede svar, utilsigtede naboord, forbindelser mellem ord, fælles startnummer og fjernelse af forbindelsesord. JSON testes både med gyldige roundtrips og med ugyldige data.

Generatoren er afprøvet med **15 seeds og 5 gitterstørrelser**, i alt **75 kombinationer**: 9 × 9, 13 × 19, 17 × 17, 25 × 25 og 35 × 35. Hver kombination gennemfører fem søgeforsøg og validerer resultatet uafhængigt. Desuden testes reproducerbarhed uden tidsgrænse, flere forklaringer til samme ord, umulige ordkombinationer, for lange ord og afbrydelse før start.

PDF-testene omfatter alle tre eksportformer, danske bogstaver, XML-specialtegn i forklaringer, lange forklaringer, Helvetica som reservefont og afvisning af tomme krydsord.

## GUI-smoketest

Kommando i testmiljøet:

```bash
xvfb-run -a -s '-screen 0 1440x1000x24' python -m tests.smoke_gui
```

**Resultat: gennemført uden registrerede brugerfladefejl.**

Følgende arbejdsgange blev udført gennem brugerfladens metoder og widgets:

- Opstart med 144 forklaringer og synlige konstruktionskontroller.
- Tilføjelse af et ord, ekstra forklaring og mønstersøgning.
- Manuel placering af to krydsende ord samt gem, gem kopi og lokal rettelse af en forklaring.
- PDF-eksport, eksport/import af redigerbar JSON og databasebackup.
- Automatisk generering i baggrundstråd, behandling af beskeder i hovedtråden og genetablering af knapper efter søgningen.
- Stop af søgning og bevarelse af tidligere krydsord, når der ikke findes et brugbart nyt resultat.

Brugerfladen er desuden gengivet og visuelt inspiceret. Kontroller er afprøvet ved vinduesstørrelserne 1340 × 860 og 1100 × 760. På små vinduer eller ved store gitre kan rulning være nødvendig.

## PDF-kontrol

`examples/Hverdagskryds.pdf` og `examples/Hverdagskryds_facit.pdf` er genereret fra samme gemte JSON-krydsord. Begge indeholder **20 ord** i et **17 × 17-gitter** og fylder hver **én A4-side**.

Begge PDF'er er renderet til billeder og visuelt inspiceret for placering, nummerering, danske bogstaver og læsbarhed. En tekstkontrol af opgaven fandt ikke de konkrete testsvar TOMAT, NETVÆRK og KARTOFFEL. Eksportkoden tegner ikke svarbogstaver eller tilføjer svarlister, annotationer eller skjulte svarfelter i opgave-only-tilstanden.

En ekstra stressprøve med 20 lange forklaringer og både opgave/facit gav **6 sider**. Alle 20 forklaringers identifikatorer blev fundet præcis to gange i tekstudtrækket, én gang i opgaven og én gang i facit. Tekstblokke lå inden for sidernes grænser.

## Hvad kontrollen ikke dokumenterer

Disse tests er ikke en garanti for fejlfri drift under alle forhold. De omfatter ikke en fuld sikkerhedsrevision, en stor dansk ordbog, belastning med mange samtidige brugere, fysiske printere, skærmlæsertilgængelighed eller alle kombinationer af operativsystem, skærmskalering og skrifttyper.

Generatorens resultater er heuristiske. Testene dokumenterer validerede placeringer og konkrete arbejdsgange, ikke en garanti for tæt gitterfyldning, sproglig kvalitet eller et bestemt antal placerede ord for vilkårlige ordbøger.