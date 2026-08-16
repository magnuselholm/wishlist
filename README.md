# Ønskeseddel

En lille webside hvor man kan oprette en bruger, lave flere ønskelister og fylde dem
med ønsker – med link, pris i kroner, billede, størrelse og beskrivelse. Ønskerne vises
i et gitter med billede, pris og link.

Indsætter man et produktlink, kan siden selv hente titel, pris og billede fra siden.

## Kontoen

Klik på dit navn i topbjælken for at komme til **Min konto**. Her retter du navn og
e-mail (e-mailen er den, du logger ind med) og skifter adgangskode – det sidste kræver
den nuværende kode. Nederst kan kontoen slettes: ønskelister, ønsker og uploadede
billeder følger med, og delelinkene holder op med at virke. Det kræver adgangskoden og
kan ikke fortrydes.

## Invitationer

Siden er lukket: man kan kun oprette en bruger med en invitationskode. Koderne laves
under **Invitationer** i topbjælken, og hver kode kan have en note om hvem den er til,
et loft over hvor mange der må bruge den, og en udløbsdato. Koden står i linket
(`/opret-bruger?kode=ABCD-2345`), så den ikke skal skrives af – men den kan også tastes
i hånden, og små bogstaver og manglende bindestreg går an.

Går en kode et forkert sted hen, lukker **Luk** den uden at røre de andre. Oversigten
viser hvem der er kommet ind på hver kode.

Kun brugere med admin-flaget kan se og lave koder. Første gang appen møder en tom
database, slipper den allerførste bruger for kode og bliver admin – ellers var der ingen
til at invitere de andre. I en base der allerede har brugere, bliver den ældste bruger
admin, når appen starter første gang med invitationerne slået til.

Gæster med et delelink skal ikke bruge nogen kode – de opretter sig jo ikke.

## Deling og reservationer

Hver ønskeliste har sit eget link, som du finder under **Del liste**. Alle med linket kan
se ønskerne uden at oprette en bruger, og de kan reservere et ønske, så de andre gæster
kan se at det er taget. Et ønske kan kun reserveres af én, og man kan fortryde sin egen
reservation igen.

Er man logget ind, hører reservationen til brugeren. Så kan den fortrydes fra en anden
maskine bagefter, og den overlever at man logger ud og ind igen. Er man ikke logget ind,
hører den som før til browseren – og reserverer man som gæst og logger ind bagefter,
følger reservationerne med over på brugeren, så de ikke bliver hængende uden ejermand.

Ejeren af listen får aldrig reservationerne at se – hverken på sin egen liste eller når
ejeren åbner sit eget delelink. (Logger man ud og åbner linket, er man en gæst som alle
andre, så helt gemt er det kun for den der ikke leder.)

Er linket havnet et forkert sted, laver **Lav nyt link** en ny nøgle, og det gamle link
holder op med at virke. De der fulgte listen, følger den heller ikke længere – ellers
lukkede det nye link jo ingen ude.

## Venner

Under **Venner** samler man de lister, man gerne vil holde øje med.

Har man fået et delelink til en enkelt liste, kan man trykke **Følg listen**, når man er
logget ind. Så står den under Venner bagefter, og linket skal ikke findes frem igen.
Ejeren kan se hvem der følger listen – men stadig ikke hvad de har reserveret.

Vil man se alle en persons lister, følger man personen i stedet. Det gøres med den
e-mail, personen logger ind med, og det kræver ikke personens accept: her på siden
kender folk hinanden i forvejen. Nye lister kommer med af sig selv bagefter.

Skal en liste holdes uden for det – typisk gaven til en, der følger dig – sættes flueben
i **Skjul listen for dem der følger mig** under Rediger liste. Listen forsvinder fra
Venner, men delelinket virker stadig, så den kan deles med alle de andre.

Under **Dem der følger dig** står de personer, der følger dig. **Fjern** lukker en person
ude igen: de kan ikke længere se listerne, hverken under Venner eller gennem et delelink
de har fået, og de kan ikke bare følge dig igen. Fortryder man, står de under **Lukket
ude**, hvor de kan lukkes ind igen.

## Kom i gang

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

export SECRET_KEY="en-lang-tilfældig-tekst"
python app.py
```

Siden kører nu på http://127.0.0.1:5000.

Databasen (`ønsker.db`) og mappen `static/uploads/` bliver oprettet automatisk første
gang appen starter.

## Indstillinger

Alt sættes med miljøvariabler (se `config.py`):

| Variabel | Betydning | Standard |
| --- | --- | --- |
| `SECRET_KEY` | nøgle til session-cookies – **skal** sættes i drift | `TEST` |
| `DATABASE` | sti til SQLite-filen | `ønsker.db` i projektmappen |
| `UPLOAD_MAPPE` | hvor uploadede billeder gemmes | `static/uploads/` |

I drift startes appen med gunicorn (se `Procfile`):

```bash
gunicorn "app:create_app()"
```

## Test

```bash
pip install pytest
python -m pytest tests
```

## Sådan hænger det sammen

```
app.py              starter appen
config.py           indstillinger
app/__init__.py     samler appen: blueprints, CSRF, filtre
app/models.py       SQLite-skema og alle forespørgsler
app/auth.py         opret bruger, log ind/ud, kontoen, login-krav, admin-krav og CSRF
app/invitationer.py invitationskoder: oversigt, nye koder og spærring
app/routes.py       ønskelister, ønsker og /api/skrab
app/deling.py       gæstevisningen på /delt/<nøgle>, reservationer og at følge en liste
app/venner.py       at følge en person, og hvem der følger dig
app/skrab.py        henter titel, pris og billede fra et produktlink
app/billeder.py     uploadede billeder
templates/          sider (Jinja2)
static/             style.css og app.js
```

### Om skrabningen

`/api/skrab` henter siden bag linket og leder efter produktdata i JSON-LD
(`schema.org/Product`), derefter i OpenGraph- og andre meta-tags, og til sidst i
`<title>`. Priser læses både som `1.299,00` og `1,299.00`.

Fordi serveren henter en adresse brugeren selv skriver, tjekkes adressen først:
kun http/https, kun port 80 og 443, og aldrig adresser der peger indad i netværket
(localhost, 10.x, 169.254.169.254 osv.). Omdirigeringer følges manuelt, så hvert nyt
mål bliver tjekket på samme måde. Svar større end 2 MB læses ikke færdigt.

Nogle webshops blokerer for automatisk hentning. Så siger siden det, og felterne
kan udfyldes i hånden.

### Gamle data

Havde du den tidligere udgave (én fælles liste uden brugere), bliver den gamle tabel
omdøbt til `ønsker_gammel` første gang appen starter. Ingenting slettes, men ønskerne
skal oprettes igen under din egen bruger.

Reservationstabellen bliver bygget om første gang appen starter med vennerne, så en
reservation også kan høre til en bruger. De gamle reservationer bliver stående som de
er – de hører til browseren, indtil gæsten logger ind.
