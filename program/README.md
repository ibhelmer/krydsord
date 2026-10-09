# Kryds & Tværs Generator

**Version 1.0.0 · Oktober 2026**

Et lokalt Python-program til at opbygge en orddatabase, konstruere krydsord og eksportere dem som PDF. Brugerfladen er på dansk. Python-navne og kodekommentarer er på engelsk.

Programmet laver **nummererede krydsord med vandrette og lodrette ordforklaringer uden for gitteret**. Det laver ikke skandinaviske pilekrydsord med forklaringer inde i felterne.

![Programmets brugerflade](examples/Brugerflade.png)

## Kom hurtigt i gang på Windows

Installer Python **3.11 eller nyere** med Tcl/Tk-understøttelse. Pak hele ZIP-filen ud i en almindelig mappe, før du starter programmet. Kør ikke direkte inde fra ZIP-filen.

Dobbeltklik på **`start_windows.bat`**. Første gang opretter startfilen et virtuelt Python-miljø i `.venv` og installerer ReportLab. Det kræver internetadgang til installationen. Efter installationen arbejder selve programmet lokalt og foretager ingen netværkskald.

Startfilen er almindelig, læsbar batchkode; du behøver ikke administratorrettigheder for selve programmet. Organisationens politikker kan dog begrænse installation eller kørsel af scripts.

### Manuel installation og start i PowerShell

Åbn PowerShell i den udpakkede projektmappe:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Miljøet behøver ikke at blive aktiveret, så kommandoerne kræver ikke ændring af PowerShell Execution Policy. Efter første installation er det kun den sidste kommando, der skal køres. Hvis `py` ikke findes, men `python` gør, bruges `python -m venv .venv` i den første linje.

Kontrollér Tkinter separat med:

```powershell
py -3 -m tkinter
```

Det skal åbne et lille testvindue. Mangler Tkinter på Windows, tilføjes Tcl/Tk-komponenten i Python-installationen.

## Linux og macOS

På Debian/Ubuntu kan Python, virtuelle miljøer og Tkinter installeres med:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk
```

Kontrollér, at Python-versionen er mindst 3.11. Installer derefter programmets afhængighed og start:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Alternativt kan `sh start_linux.sh` bruges, når Python og Tkinter er til rådighed. Samme manuelle Python-kommandoer kan bruges på macOS med en Python-installation, der indeholder Tkinter. Der skal være et grafisk skrivebord for at starte brugerfladen. PDF-generering via kommandolinjen kræver ikke et grafisk skrivebord.

Programmet er udviklet med henblik på Windows, Linux og macOS. Den gennemførte kørselstest er på Linux; Windows-startfilen og macOS-kørsel er ikke afprøvet på de respektive operativsystemer.

## Den første opstart

Programmet opretter selv en SQLite-database og indlæser **142 forskellige ord med 144 ordforklaringer**. Startordbogen omfatter Natur, Dyr, Hverdag, Mad, IT og Sprog. MUS og ORD har hver to forklaringer. Ordforklaringerne er eksempelmateriale skrevet til denne prototype, ikke en komplet eller fagligt valideret dansk ordbog.

Indlæsningen sker kun én gang pr. database. Sletning af eksempelord er derfor varig; de kommer ikke tilbage ved næste opstart. Eksempelmaterialet kan genindlæses ved at importere `krydsord/sample_words.csv`.

## 1. Tilføj og redigér ord

Åbn fanen **Orddatabase** og vælg **Tilføj ord**. Indtast svarord, forklaring og eventuelt kategori. Ændringer i orddatabasen gemmes straks.

Et svar kan have flere ordforklaringer. Markér eksempelvis MUS og vælg **Ny forklaring til ord** for at tilføje en anden betydning. Under generering bruges højst én forklaring pr. normaliseret svarord. Markeres flere forklaringer til det samme ord, vælger generatoren én af dem.

**Redigér** ændrer den markerede forklaring. Ændres svarordet i denne dialog, flyttes netop den forklaring til det nye ord; andre forklaringer til det gamle ord bevares. **Slet** sletter de markerede forklaringer. Et ord uden forklaringer fjernes automatisk fra orddatabasen.

Søgning kan ske med fritekst, kategori eller et bogstavmønster:

| Mønster | Betydning |
|---|---|
| `?A?` | Tre bogstaver med A i midten |
| `K??` | Tre bogstaver, der begynder med K |
| `?????` | Præcis fem bogstaver |
| `??Æ?` | Fire bogstaver med Æ som tredje bogstav |

Et spørgsmålstegn står for præcis ét ukendt bogstav. Punktum og understregning accepteres også som ukendte felter. Stjerne accepteres ikke. Fritekstsøgning skelner ikke mellem store og små bogstaver, heller ikke ved Æ, Ø og Å.

Svarord normaliseres til store bogstaver. Mellemrum, bindestreger og apostroffer fjernes; eksempelvis bliver `IT-sikkerhed` til `ITSIKKERHED`. Der accepteres 2-35 bogstaver fra A-Z samt Æ, Ø og Å. Tal og andre accentbogstaver understøttes ikke i svarord i denne version. Forklaringer kan være op til 500 tegn, kategorier op til 80 tegn og titler op til 120 tegn.

## 2. Generér et krydsord

På fanen **Krydsord** angives titel, eventuel beskrivelse, rækker, kolonner og ønsket antal ord. Et godt første forsøg er et gitter på **17 × 17** med **20 ord**, **100 søgeforsøg** og **8 sekunders** maksimal søgetid.

**Ordgrundlag** bestemmer kategorien. Med **Alle kategorier** bruges hele orddatabasen. Alternativt markeres bestemte forklaringer i Orddatabase med Ctrl eller Shift, hvorefter **Kun markerede forklaringer i orddatabasen** aktiveres. Kategorifilter og markering gælder samtidig. Fritekst- og mønstersøgning afgrænser kun ordbogsvisningen; de afgrænser ikke automatisk generatoren. Brug markeringer for at overføre et bestemt søgeresultat.

Tryk **Generér forslag**. Generatoren søger efter et sammenhængende krydsord og nummererer automatisk startfelterne. Ord, som starter i samme felt i hver sin retning, får samme nummer. Søgningen kører i en baggrundstråd, så brugerfladen fortsat kan reagere.

Det ønskede antal ord er et mål, ikke en garanti. Programmet viser, hvor mange ord der blev indsat. Det kan være nødvendigt at øge gitterstørrelsen, tilføje flere korte ord eller forsøge igen med en anden kombination. **Stop søgning** stopper videre søgning og beholder det bedste fundne resultat med mindst to ord. Hvis der ikke blev fundet et brugbart resultat, bevares det tidligere krydsord.

Et tomt **Seed** giver en ny tilfældig søgning. Et bestemt heltal kan bruges ved gentagne forsøg. Samme ordgrundlag, parametre og seed giver samme resultat, hvis det samme antal forsøg bliver gennemført. En tidsgrænse kan afbryde på forskellige tidspunkter på forskellige computere; derfor er seed alene ikke en ubetinget reproducerbarhedsgaranti. Gem selve krydsordet eller en JSON-fil for at bevare det nøjagtige layout.

## 3. Konstruér eller justér manuelt

Brug **Nyt tomt gitter** for at begynde fra bunden. Vælg en forklaring i Orddatabase og klik **Brug i krydsord**. Klik derefter på startfeltet i gitteret, vælg Vandret eller Lodret og tryk **Indsæt ord**.

**Foreslå placering** finder gyldige placeringer til det valgte ord i det eksisterende gitter. Gentagne klik skifter mellem mulighederne. En grøn ramme viser en gyldig placering; en rød ramme viser en ugyldig placering. Visningen er kun en forhåndsvisning, indtil der trykkes Indsæt ord.

Det første ord kan placeres frit inden for gitteret. Hvert efterfølgende ord skal krydse et eksisterende ord med samme bogstav. Parallel overlapning, kontakt umiddelbart før/efter et ord og nabobogstaver, der danner utilsigtede ord, afvises.

Markér et ord i **Ord i krydsordet** for at fremhæve det i gitteret. **Ret forklaring** ændrer kun forklaringen i dette krydsord, ikke den tilhørende databasepost. **Fjern ord** sletter ordet fra krydsordet, men ikke fra orddatabasen. Fjernelse af et forbindelsesord afvises, hvis de resterende ord bliver opdelt i adskilte grupper. Fjern i så fald først de yderste ord.

Der er ikke indført fri flytning af ord, fortryd/gentag, låste felter eller generering omkring et eksisterende sæt fastlåste ord. En ny automatisk generering erstatter layoutet efter advarsel om ikke-gemte ændringer. Rækker/kolonner øverst bruges ved et nyt eller genereret gitter; de ændrer ikke straks det aktuelle layout.

## 4. Gem, genåbn og del

**Gem** eller Ctrl+S gemmer krydsordet i databasen. **Gem kopi** opretter en ny post. Gemte krydsord åbnes fra fanen **Gemte krydsord** og kan redigeres videre. Også tomme kladder kan gemmes. En stjerne i vinduets titel viser ikke-gemte ændringer.

Gemte krydsord indeholder kopier af svar, forklaringer og placeringer. Senere ændringer eller sletninger i orddatabasen ændrer derfor ikke eksisterende krydsord. Der er ikke automatisk lagring af selve krydsordet ved hvert klik; gem løbende.

Via **Filer → Eksportér krydsordsfil (JSON)** kan det aktuelle krydsord gemmes som en selvstændig, redigerbar fil. Filen genåbnes med **Filer → Åbn krydsordsfil (JSON)**. Den indlæste fil er ikke føjet til databasen, før der trykkes Gem. Eksemplet `examples/Hverdagskryds.krydsord.json` kan åbnes direkte.

**JSON-filer og SQLite-databaser indeholder svarene.** Send opgave-PDF'en, ikke disse filer, til personer der skal løse krydsordet uden facit.

## 5. Eksportér PDF

Klik **Eksportér PDF** og vælg et af tre indhold:

| Valg | Indhold |
|---|---|
| Opgave uden svar | Nummereret, tomt gitter og ordforklaringer |
| Opgave og facit | Opgaven først og facit på separate efterfølgende sider |
| Kun facit | Udfyldt gitter samt forklaringer med svar |

Standardvalget er opgave uden svar. Afkrydsningen **Vis svar i gitteret** styrer kun brugerfladens visning; PDF-indholdet bestemmes uafhængigt i eksportdialogen.

PDF'en formateres til A4 med titel, feltantal, vandrette/lodrette forklaringer og sidetal. Lange forklaringslister fortsætter på ekstra sider. Store gitre giver mindre skrivefelter; vælg et moderat gitter til almindelig A4-udskrivning. Udskriv gerne ved 100 % størrelse.

Programmet bruger en egnet lokal skrifttype, når den findes, og ellers PDF-standardskrifttypen Helvetica. Æ, Ø og Å understøttes. Der distribueres ingen separate skrifttypefiler med programmet. Tegn, som eksportens skrifttype ikke understøtter, afvises med en fejlmeddelelse frem for tavst at blive erstattet af firkanter.

Se `examples/Hverdagskryds.pdf` og `examples/Hverdagskryds_facit.pdf` for opgave og facit. De to medfølgende eksempel-PDF'er fylder hver én A4-side.

## CSV-import og -eksport

Vælg funktionerne i Orddatabase eller i menuen Database. En CSV-fil kan eksempelvis indeholde:

```csv
word;clue;category
ROUTER;Videresender pakker mellem netværk;IT
MUS;Pegeenhed til en computer;IT
MUS;Lille gnaver;Dyr
ÆBLE;Frugt, der kan være rød eller grøn;Mad
```

`word` og `clue` er obligatoriske; `category` er valgfri. Danske kolonnenavne `ord`, `ordforklaring` og `kategori` accepteres også. Filer skal være UTF-8, eventuelt med BOM. Semikolon, komma og tabulator genkendes. Felter med skilletegn skal stå i anførselstegn efter almindelige CSV-regler.

Alle rækker kontrolleres før indsættelse, så en ugyldig række ikke efterlader en delvist indlæst ordbog. Dubletter af samme normaliserede ord og samme forklaring springes over. CSV-import er en tilføjelse, ikke en masseopdatering: ændret kategori på en ellers identisk ord/forklaring opdateres ikke ved genimport. Eksport indeholder alle ord/forklaringer, ikke kun de viste søgeresultater. CSV indeholder ikke gemte krydsord og er ikke en fuld databasebackup.

## Placering af data og sikkerhedskopiering

Databasen ligger som udgangspunkt her:

```text
Windows: %LOCALAPPDATA%\KrydsOgTvaersGenerator\krydsord.sqlite3
Linux:   ~/.local/share/KrydsOgTvaersGenerator/krydsord.sqlite3
macOS:   ~/Library/Application Support/KrydsOgTvaersGenerator/krydsord.sqlite3
```

På Linux respekteres `XDG_DATA_HOME`, når den er sat. Den præcise aktive filsti vises under **Hjælp / Om**. Eventuelle fejl logges i `krydsord.log` i samme mappe. Hvis programmappen slettes eller flyttes, slettes datafilen derfor ikke automatisk.

**Database → Tag sikkerhedskopi af databasen** laver en konsistent kopi via SQLite-backup-API'et. Den indeholder både ordbogen og alle gemte krydsord, men ikke ikke-gemte ændringer. Brug denne funktion frem for at kopiere den aktive databasefil alene, mens programmet kører, fordi SQLite kan have ændringer i en separat WAL-fil.

En sikkerhedskopi kan åbnes som en alternativ database:

```powershell
.\.venv\Scripts\python.exe app.py --database "D:\Backup\krydsord_backup.sqlite3"
```

Dette åbner backupfilen til normal redigering; lav en kopi først, når originalbackup skal bevares urørt. En alternativ database kan også vælges ved første opstart med `--database`. Programmet er beregnet til lokal brug på én computer, ikke til deling af en aktiv database over netværksdrev eller som flerbrugerwebsystem.

## Algoritmen

Generatoren implementerer en **randomiseret multi-start greedy-heuristik**, ikke en udtømmende backtracking- eller constraint-solver.

1. Svar normaliseres og samles, så samme svar ikke bruges flere gange. Ord, der er for lange til begge gitterdimensioner, udelukkes og rapporteres.
2. For hvert søgeforsøg vælges en varieret rækkefølge og et ankerord, som placeres omtrent i midten.
3. Et bogstavindeks foreslår positioner, hvor et nyt ord kan krydse eksisterende bogstaver. Placeringer kontrolleres for grænser, bogstavlighed, overlap og utilsigtet nabokontakt.
4. Gyldige placeringer scores ud fra krydsninger, ændring i omsluttende areal og et lille tilfældigt bidrag. Ord uden en aktuel placering prøves igen, hvis andre ord har ændret gitteret.
5. De fundne gitre sammenlignes først på antal ord, derefter antal krydsninger og til sidst kompakthed. Det bedste resultat beholdes.
6. En uafhængig validator scanner alle vandrette/lodrette bogstavforløb og kontrollerer, at de svarer nøjagtigt til de registrerede ord, og at alle ord er forbundet via krydsninger.

Ved store orddatabaser undersøges højst 250 tilfældigt udvalgte forskellige ord pr. forsøg. Forskellige forsøg kan undersøge forskellige delmængder. Denne begrænsning holder arbejdet pr. forsøg nede; den er ikke en garanti for, at alle databaseord undersøges inden en tidsgrænse.

Heuristikken garanterer ikke globalt optimum, placering af alle ønskede ord, rotationssymmetri eller krydsning af hvert enkelt bogstav. Gitteret bliver typisk et frit konstrueret krydsord med sorte ubrugte felter, ikke et tæt, fuldt kontrolleret aviskrydsord. Programmet vurderer heller ikke sproglig kvalitet eller sværhedsgrad.

## Programstruktur og database

```text
KrydsOgTvaersGenerator/
├── app.py                         Startpunkt og kommandolinje
├── requirements.txt               Afhængighed til PDF-eksport
├── start_windows.bat              Windows-start med virtuelt miljø
├── start_linux.sh                 Unix-start med virtuelt miljø
├── README.md                      Denne vejledning
├── TEST_REPORT.md                 Gennemført kontrol og begrænsninger
├── krydsord/
│   ├── __init__.py                 Versionsnummer
│   ├── models.py                  Domænemodel og validering
│   ├── database.py                SQLite, CSV og backup
│   ├── generator.py               Heuristik og manuel placeringskontrol
│   ├── gui.py                     Dansk Tkinter-brugerflade
│   ├── pdf_export.py              PDF-layout og eksport
│   └── sample_words.csv           Redigerbar startordbog
├── tests/
│   ├── test_core.py               Automatiserede kerne-/PDF-tests
│   └── smoke_gui.py               GUI-kontrol med midlertidig database
└── examples/
    ├── Hverdagskryds.pdf           Opgave uden svar
    ├── Hverdagskryds_facit.pdf     Separat facit
    ├── Hverdagskryds.krydsord.json Redigerbart eksempel med svar
    ├── Brugerflade.png            Skærmbillede af konstruktion
    └── Orddatabase.png            Skærmbillede af ordbogen
```

SQLite-skemaet har `words` (ét normaliseret svar pr. række), `clues` (mange forklaringer pr. ord), `puzzles` (selvstændige JSON-snapshots med metadata) og `settings` (blandt andet markering af indlæst startordbog). Databaseversionen er 1 og gemmes i `PRAGMA user_version`. Svar/forklaringer gemmes med parameteriserede SQL-forespørgsler. Indlæste JSON-filer behandles som data og eksekveres ikke.

Tkinter og databaseforbindelsen bruges kun i hovedtråden. Generatortråden modtager almindelige Python-objekter og afleverer resultater gennem en kø. PDF-eksport skrives først til en midlertidig fil, som derefter erstatter målfilen.

## Kommandolinje uden brugerflade

```bash
python app.py --demo --output eksempel.pdf --seed 42
python app.py --demo --output eksempel_med_facit.pdf --with-solution
python app.py --demo --category IT --words 15 --rows 17 --cols 17 --output it_krydsord.pdf
python app.py --help
```

`--demo` bruger orddatabasen, genererer en PDF og afslutter. En manglende database oprettes og initialiseres også i denne tilstand. Det genererede krydsord gemmes ikke automatisk i listen Gemte krydsord ved kommandolinjekørsel.

## Test

Kerne-, database-, generator- og PDF-tests køres fra projektmappen:

```bash
python -m unittest discover -s tests -v
```

GUI-smoketesten kræver et grafisk miljø og kan køres særskilt:

```bash
python -m tests.smoke_gui
```

På et Linux-system med Xvfb kan den køres uden fysisk skærm:

```bash
xvfb-run -a python -m tests.smoke_gui
```

Testene bruger midlertidige databaser og ændrer ikke brugerens normale data. Se `TEST_REPORT.md` for det faktisk afprøvede miljø og de gennemførte kontroller.

## Dokumentation for de anvendte biblioteker

```text
Tkinter:   https://docs.python.org/3/library/tkinter.html
SQLite:    https://docs.python.org/3/library/sqlite3.html
venv:      https://docs.python.org/3/library/venv.html
ReportLab: https://docs.reportlab.com/reportlab/userguide/ch2_graphics/
```