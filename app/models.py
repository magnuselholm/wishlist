import secrets
import sqlite3
from datetime import datetime, timezone

from flask import current_app, g

### Database funktioner


def get_db():
    """Én forbindelse pr. request, genbruges via flask.g."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def luk_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _tabeller(db):
    rows = db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {r["name"] for r in rows}


def _kolonner(db, tabel):
    return {r["name"] for r in db.execute(f"PRAGMA table_info({tabel})")}


def init_db():
    db = get_db()

    # den gamle enkeltbruger-tabel havde hverken liste_id eller titel. Den flyttes
    # til side, så gamle ønsker ikke går tabt når det nye skema oprettes.
    if "ønsker" in _tabeller(db) and "liste_id" not in _kolonner(db, "ønsker"):
        db.execute("ALTER TABLE ønsker RENAME TO ønsker_gammel")

    # lister fra før deling manglede en nøgle til gæstelinket. Den fyldes ud nedenfor.
    if "lister" in _tabeller(db) and "del_nøgle" not in _kolonner(db, "lister"):
        db.execute("ALTER TABLE lister ADD COLUMN del_nøgle TEXT")

    # brugere fra før invitationerne har hverken admin-flag eller en kode de kom ind på
    if "brugere" in _tabeller(db):
        gamle = _kolonner(db, "brugere")
        if "admin" not in gamle:
            db.execute("ALTER TABLE brugere ADD COLUMN admin INTEGER NOT NULL DEFAULT 0")
        if "invitation_id" not in gamle:
            db.execute("ALTER TABLE brugere ADD COLUMN invitation_id INTEGER REFERENCES invitationer(id)")

    # lister fra før kan ikke holdes uden for de andre brugeres oversigt
    if "lister" in _tabeller(db) and "skjult_for_andre" not in _kolonner(db, "lister"):
        db.execute("ALTER TABLE lister ADD COLUMN skjult_for_andre INTEGER NOT NULL DEFAULT 0")

    # reservationer hørte før kun til en browser. Nu kan de også høre til en bruger, så
    # de kan fortrydes fra en anden maskine – og ikke går tabt ved log ind og log ud.
    if "reservationer" in _tabeller(db) and "bruger_id" not in _kolonner(db, "reservationer"):
        db.executescript("""
            CREATE TABLE reservationer_ny (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ønske_id INTEGER NOT NULL UNIQUE REFERENCES ønsker(id) ON DELETE CASCADE,
                bruger_id INTEGER REFERENCES brugere(id) ON DELETE CASCADE,
                gæst TEXT,
                oprettet TEXT NOT NULL,
                CHECK (bruger_id IS NOT NULL OR gæst IS NOT NULL)
            );
            INSERT INTO reservationer_ny (id, ønske_id, bruger_id, gæst, oprettet)
                 SELECT id, ønske_id, NULL, gæst, oprettet FROM reservationer;
            DROP TABLE reservationer;
            ALTER TABLE reservationer_ny RENAME TO reservationer;
        """)

    db.executescript("""
        CREATE TABLE IF NOT EXISTS brugere (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            navn TEXT NOT NULL,
            adgangskode TEXT NOT NULL,
            admin INTEGER NOT NULL DEFAULT 0,
            invitation_id INTEGER REFERENCES invitationer(id),
            oprettet TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lister (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bruger_id INTEGER NOT NULL REFERENCES brugere(id) ON DELETE CASCADE,
            titel TEXT NOT NULL,
            beskrivelse TEXT,
            del_nøgle TEXT,
            skjult_for_andre INTEGER NOT NULL DEFAULT 0,
            oprettet TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ønsker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            liste_id INTEGER NOT NULL REFERENCES lister(id) ON DELETE CASCADE,
            titel TEXT NOT NULL,
            pris REAL,
            link TEXT,
            billede TEXT,
            størrelse TEXT,
            beskrivelse TEXT,
            oprettet TEXT NOT NULL
        );

        -- den der ser en delt liste kan reservere et ønske. Ejeren får aldrig de her
        -- rækker at se. Er man logget ind, hører reservationen til brugeren og kan
        -- fortrydes fra en hvilken som helst maskine; ellers til gæstens browser.
        CREATE TABLE IF NOT EXISTS reservationer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ønske_id INTEGER NOT NULL UNIQUE REFERENCES ønsker(id) ON DELETE CASCADE,
            bruger_id INTEGER REFERENCES brugere(id) ON DELETE CASCADE,
            gæst TEXT,
            oprettet TEXT NOT NULL,
            CHECK (bruger_id IS NOT NULL OR gæst IS NOT NULL)
        );

        -- en bruger kan følge en enkelt liste, man har fået delelinket til
        CREATE TABLE IF NOT EXISTS følger_lister (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            følger_id INTEGER NOT NULL REFERENCES brugere(id) ON DELETE CASCADE,
            liste_id INTEGER NOT NULL REFERENCES lister(id) ON DELETE CASCADE,
            oprettet TEXT NOT NULL,
            UNIQUE (følger_id, liste_id)
        );

        -- … eller følge en person og dermed se alle personens lister på én gang
        CREATE TABLE IF NOT EXISTS følger_personer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            følger_id INTEGER NOT NULL REFERENCES brugere(id) ON DELETE CASCADE,
            person_id INTEGER NOT NULL REFERENCES brugere(id) ON DELETE CASCADE,
            oprettet TEXT NOT NULL,
            UNIQUE (følger_id, person_id),
            CHECK (følger_id != person_id)
        );

        -- invitationskoder: uden en gyldig kode kan ingen oprette sig
        CREATE TABLE IF NOT EXISTS invitationer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kode TEXT NOT NULL UNIQUE COLLATE NOCASE,
            note TEXT,
            maks_brug INTEGER,
            brugt INTEGER NOT NULL DEFAULT 0,
            udløber TEXT,
            spærret INTEGER NOT NULL DEFAULT 0,
            oprettet_af INTEGER REFERENCES brugere(id) ON DELETE SET NULL,
            oprettet TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_lister_bruger ON lister(bruger_id);
        CREATE INDEX IF NOT EXISTS idx_ønsker_liste ON ønsker(liste_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_lister_del_nøgle ON lister(del_nøgle);
        CREATE INDEX IF NOT EXISTS idx_følger_lister_følger ON følger_lister(følger_id);
        CREATE INDEX IF NOT EXISTS idx_følger_lister_liste ON følger_lister(liste_id);
        CREATE INDEX IF NOT EXISTS idx_følger_personer_følger ON følger_personer(følger_id);
        CREATE INDEX IF NOT EXISTS idx_følger_personer_person ON følger_personer(person_id);
    """)

    # lister oprettet før deling har endnu ingen nøgle
    for række in db.execute("SELECT id FROM lister WHERE del_nøgle IS NULL").fetchall():
        db.execute("UPDATE lister SET del_nøgle = ? WHERE id = ?", (ny_del_nøgle(), række["id"]))

    # en base med brugere, men uden admin, er fra før invitationerne. Den ældste bruger
    # bliver admin – ellers var der ingen til at lave koder bagefter
    if db.execute("SELECT COUNT(*) AS n FROM brugere WHERE admin = 1").fetchone()["n"] == 0:
        db.execute("UPDATE brugere SET admin = 1 WHERE id = (SELECT MIN(id) FROM brugere)")

    db.commit()


def ny_del_nøgle():
    """Nøglen i gæstelinket. Den skal være svær at gætte, for den er hele adgangen."""
    return secrets.token_urlsafe(16)


def _nu():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


### brugere


def opret_bruger(email, navn, adgangskode_hash, invitation_id=None, admin=False):
    db = get_db()
    markør = db.execute(
        """
        INSERT INTO brugere (email, navn, adgangskode, admin, invitation_id, oprettet)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (email, navn, adgangskode_hash, 1 if admin else 0, invitation_id, _nu()),
    )
    db.commit()
    return markør.lastrowid


def antal_brugere():
    db = get_db()
    return db.execute("SELECT COUNT(*) AS n FROM brugere").fetchone()["n"]


def hent_bruger_på_email(email):
    db = get_db()
    return db.execute("SELECT * FROM brugere WHERE email = ?", (email,)).fetchone()


def hent_bruger(bruger_id):
    db = get_db()
    return db.execute("SELECT * FROM brugere WHERE id = ?", (bruger_id,)).fetchone()


def opdater_bruger(bruger_id, navn, email):
    db = get_db()
    db.execute("UPDATE brugere SET navn = ?, email = ? WHERE id = ?", (navn, email, bruger_id))
    db.commit()


def opdater_adgangskode(bruger_id, adgangskode_hash):
    db = get_db()
    db.execute("UPDATE brugere SET adgangskode = ? WHERE id = ?", (adgangskode_hash, bruger_id))
    db.commit()


def slet_bruger(bruger_id):
    """Lister, ønsker og reservationer følger med via ON DELETE CASCADE."""
    db = get_db()
    db.execute("DELETE FROM brugere WHERE id = ?", (bruger_id,))
    db.commit()


### invitationer

# uden 0/O og 1/I, så en kode kan læses op i telefonen uden misforståelser
KODE_TEGN = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def ny_invitationskode():
    tegn = "".join(secrets.choice(KODE_TEGN) for _ in range(8))
    return f"{tegn[:4]}-{tegn[4:]}"


def hent_invitationer():
    """Alle koder med hvor mange der er kommet ind på dem, og hvem det var."""
    db = get_db()
    return db.execute(
        """
        SELECT invitationer.*,
               (SELECT COUNT(*) FROM brugere WHERE brugere.invitation_id = invitationer.id)
                   AS antal_brugere,
               (SELECT GROUP_CONCAT(navn, ', ') FROM brugere WHERE brugere.invitation_id = invitationer.id)
                   AS navne
          FROM invitationer
         ORDER BY id DESC
        """
    ).fetchall()


def hent_invitation_på_kode(kode):
    db = get_db()
    return db.execute("SELECT * FROM invitationer WHERE kode = ?", (kode,)).fetchone()


def opret_invitation(kode, note, maks_brug, udløber, oprettet_af):
    db = get_db()
    markør = db.execute(
        """
        INSERT INTO invitationer (kode, note, maks_brug, udløber, oprettet_af, oprettet)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (kode, note, maks_brug, udløber, oprettet_af, _nu()),
    )
    db.commit()
    return markør.lastrowid


def sæt_invitation_spærret(invitation_id, spærret):
    db = get_db()
    db.execute(
        "UPDATE invitationer SET spærret = ? WHERE id = ?", (1 if spærret else 0, invitation_id)
    )
    db.commit()


def brug_invitation(invitation_id):
    """Tager en plads på koden i ét hug, så to samtidige oprettelser ikke kan dele den sidste."""
    db = get_db()
    markør = db.execute(
        """
        UPDATE invitationer
           SET brugt = brugt + 1
         WHERE id = ?
           AND spærret = 0
           AND (maks_brug IS NULL OR brugt < maks_brug)
           AND (udløber IS NULL OR udløber >= date('now'))
        """,
        (invitation_id,),
    )
    db.commit()
    return markør.rowcount == 1


def frigiv_invitation(invitation_id):
    """Giver pladsen tilbage, hvis oprettelsen alligevel ikke blev til noget."""
    db = get_db()
    db.execute("UPDATE invitationer SET brugt = brugt - 1 WHERE id = ? AND brugt > 0", (invitation_id,))
    db.commit()


### ønskelister


def hent_lister(bruger_id):
    db = get_db()
    return db.execute(
        """
        SELECT lister.*,
               (SELECT COUNT(*) FROM ønsker WHERE ønsker.liste_id = lister.id) AS antal,
               (SELECT SUM(pris) FROM ønsker WHERE ønsker.liste_id = lister.id) AS samlet_pris,
               (SELECT billede FROM ønsker
                 WHERE ønsker.liste_id = lister.id AND billede IS NOT NULL AND billede != ''
                 ORDER BY id DESC LIMIT 1) AS forsidebillede
          FROM lister
         WHERE bruger_id = ?
         ORDER BY id DESC
        """,
        (bruger_id,),
    ).fetchall()


def hent_liste(liste_id, bruger_id):
    """Henter en liste, men kun hvis den tilhører brugeren."""
    db = get_db()
    return db.execute(
        "SELECT * FROM lister WHERE id = ? AND bruger_id = ?", (liste_id, bruger_id)
    ).fetchone()


def hent_liste_på_nøgle(nøgle):
    """Henter en delt liste ud fra nøglen i gæstelinket – uanset hvem der spørger."""
    db = get_db()
    return db.execute(
        """
        SELECT lister.*, brugere.navn AS ejer_navn
          FROM lister
          JOIN brugere ON brugere.id = lister.bruger_id
         WHERE lister.del_nøgle = ?
        """,
        (nøgle,),
    ).fetchone()


def opret_liste(bruger_id, titel, beskrivelse):
    db = get_db()
    markør = db.execute(
        "INSERT INTO lister (bruger_id, titel, beskrivelse, del_nøgle, oprettet) VALUES (?, ?, ?, ?, ?)",
        (bruger_id, titel, beskrivelse, ny_del_nøgle(), _nu()),
    )
    db.commit()
    return markør.lastrowid


def forny_del_nøgle(liste_id, bruger_id):
    """Giver listen et nyt gæstelink, så det gamle holder op med at virke."""
    nøgle = ny_del_nøgle()
    db = get_db()
    markør = db.execute(
        "UPDATE lister SET del_nøgle = ? WHERE id = ? AND bruger_id = ?",
        (nøgle, liste_id, bruger_id),
    )
    # et nyt link er til for at lukke nogen ude. De der følger listen, kom ind ad det
    # gamle link, så de skal også slippe den – ellers lukkede det ingen ude.
    if markør.rowcount == 1:
        db.execute("DELETE FROM følger_lister WHERE liste_id = ?", (liste_id,))
    db.commit()
    return nøgle


def opdater_liste(liste_id, bruger_id, titel, beskrivelse, skjult_for_andre=False):
    db = get_db()
    db.execute(
        """
        UPDATE lister
           SET titel = ?, beskrivelse = ?, skjult_for_andre = ?
         WHERE id = ? AND bruger_id = ?
        """,
        (titel, beskrivelse, 1 if skjult_for_andre else 0, liste_id, bruger_id),
    )
    db.commit()


def slet_liste(liste_id, bruger_id):
    db = get_db()
    db.execute("DELETE FROM lister WHERE id = ? AND bruger_id = ?", (liste_id, bruger_id))
    db.commit()


### ønsker


def hent_ønsker(liste_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM ønsker WHERE liste_id = ? ORDER BY id DESC", (liste_id,)
    ).fetchall()


def hent_ønsker_til_gæst(liste_id, bruger_id=None, gæst=None):
    """Som hent_ønsker, men med reservationerne. Bruges kun i gæstevisningen."""
    db = get_db()
    return db.execute(
        """
        SELECT ønsker.*,
               reservationer.id IS NOT NULL AS reserveret,
               (COALESCE(reservationer.bruger_id = ?, 0)
                OR COALESCE(reservationer.gæst = ?, 0)) AS min_reservation
          FROM ønsker
          LEFT JOIN reservationer ON reservationer.ønske_id = ønsker.id
         WHERE ønsker.liste_id = ?
         ORDER BY ønsker.id DESC
        """,
        (bruger_id, gæst, liste_id),
    ).fetchall()


def hent_ønske_i_liste(ønske_id, liste_id):
    """Henter et ønske, men kun hvis det ligger på den delte liste."""
    db = get_db()
    return db.execute(
        "SELECT * FROM ønsker WHERE id = ? AND liste_id = ?", (ønske_id, liste_id)
    ).fetchone()


def hent_ønske(ønske_id, bruger_id):
    """Henter et ønske, men kun hvis det ligger i en af brugerens lister."""
    db = get_db()
    return db.execute(
        """
        SELECT ønsker.* FROM ønsker
          JOIN lister ON lister.id = ønsker.liste_id
         WHERE ønsker.id = ? AND lister.bruger_id = ?
        """,
        (ønske_id, bruger_id),
    ).fetchone()


def tilføj_ønske(liste_id, titel, pris, link, billede, størrelse, beskrivelse):
    db = get_db()
    markør = db.execute(
        """
        INSERT INTO ønsker (liste_id, titel, pris, link, billede, størrelse, beskrivelse, oprettet)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (liste_id, titel, pris, link, billede, størrelse, beskrivelse, _nu()),
    )
    db.commit()
    return markør.lastrowid


def opdater_ønske(ønske_id, titel, pris, link, billede, størrelse, beskrivelse):
    db = get_db()
    db.execute(
        """
        UPDATE ønsker
           SET titel = ?, pris = ?, link = ?, billede = ?, størrelse = ?, beskrivelse = ?
         WHERE id = ?
        """,
        (titel, pris, link, billede, størrelse, beskrivelse, ønske_id),
    )
    db.commit()


def slet_ønske(ønske_id):
    db = get_db()
    db.execute("DELETE FROM ønsker WHERE id = ?", (ønske_id,))
    db.commit()


### reservationer


def reserver_ønske(ønske_id, bruger_id=None, gæst=None):
    """Reserverer et ønske. Falsk hvis en anden nåede det først."""
    db = get_db()
    markør = db.execute(
        "INSERT OR IGNORE INTO reservationer (ønske_id, bruger_id, gæst, oprettet) VALUES (?, ?, ?, ?)",
        (ønske_id, bruger_id, gæst, _nu()),
    )
    db.commit()
    return markør.rowcount == 1


def fortryd_reservation(ønske_id, bruger_id=None, gæst=None):
    """Fjerner en reservation. Falsk hvis den tilhører en anden."""
    db = get_db()
    markør = db.execute(
        """
        DELETE FROM reservationer
         WHERE ønske_id = ?
           AND ((? IS NOT NULL AND bruger_id = ?) OR (? IS NOT NULL AND gæst = ?))
        """,
        (ønske_id, bruger_id, bruger_id, gæst, gæst),
    )
    db.commit()
    return markør.rowcount == 1


def overtag_reservationer(bruger_id, gæst):
    """Flytter en browsers reservationer over på brugeren, når gæsten logger ind.

    Ellers var reservationen låst fast i den session der lige blev ryddet, og hverken
    gæsten eller nogen anden kunne fortryde den igen.
    """
    if not gæst:
        return 0
    db = get_db()
    markør = db.execute(
        "UPDATE reservationer SET bruger_id = ?, gæst = NULL WHERE gæst = ?", (bruger_id, gæst)
    )
    db.commit()
    return markør.rowcount


### at følge andre: enten en enkelt liste, man har fået linket til, eller hele personen


def følg_liste(følger_id, liste_id):
    """Sandt hvis listen blev fulgt nu – falsk hvis den allerede blev fulgt."""
    db = get_db()
    markør = db.execute(
        "INSERT OR IGNORE INTO følger_lister (følger_id, liste_id, oprettet) VALUES (?, ?, ?)",
        (følger_id, liste_id, _nu()),
    )
    db.commit()
    return markør.rowcount == 1


def stop_med_at_følge_liste(følger_id, liste_id):
    db = get_db()
    markør = db.execute(
        "DELETE FROM følger_lister WHERE følger_id = ? AND liste_id = ?", (følger_id, liste_id)
    )
    db.commit()
    return markør.rowcount == 1


def følger_liste(følger_id, liste_id):
    db = get_db()
    return db.execute(
        "SELECT 1 FROM følger_lister WHERE følger_id = ? AND liste_id = ?", (følger_id, liste_id)
    ).fetchone() is not None


def hent_fulgte_lister(følger_id):
    """De enkeltlister brugeren følger, fra et delelink de har fået.

    Skjulte lister bliver stående: linket har ejeren selv sendt, og listen er kun
    skjult i oversigten over ejerens lister.
    """
    db = get_db()
    return db.execute(
        """
        SELECT lister.*, brugere.navn AS ejer_navn,
               (SELECT COUNT(*) FROM ønsker WHERE ønsker.liste_id = lister.id) AS antal
          FROM følger_lister
          JOIN lister ON lister.id = følger_lister.liste_id
          JOIN brugere ON brugere.id = lister.bruger_id
         WHERE følger_lister.følger_id = ?
         ORDER BY følger_lister.id DESC
        """,
        (følger_id,),
    ).fetchall()


def hent_liste_følgere(liste_id):
    """Hvem der følger listen. Ejeren må gerne vide det – reservationer røbes ikke."""
    db = get_db()
    return db.execute(
        """
        SELECT brugere.id, brugere.navn, brugere.email, følger_lister.oprettet
          FROM følger_lister
          JOIN brugere ON brugere.id = følger_lister.følger_id
         WHERE følger_lister.liste_id = ?
         ORDER BY brugere.navn
        """,
        (liste_id,),
    ).fetchall()


def følg_person(følger_id, person_id):
    """Sandt hvis personen blev fulgt nu.

    At følge giver ingen adgang – alle på siden kan se hinandens lister i forvejen.
    Det holder blot personen øverst i oversigten, så man ikke skal lede efter dem.
    """
    db = get_db()
    markør = db.execute(
        "INSERT OR IGNORE INTO følger_personer (følger_id, person_id, oprettet) VALUES (?, ?, ?)",
        (følger_id, person_id, _nu()),
    )
    db.commit()
    return markør.rowcount == 1


def stop_med_at_følge_person(følger_id, person_id):
    db = get_db()
    markør = db.execute(
        "DELETE FROM følger_personer WHERE følger_id = ? AND person_id = ?", (følger_id, person_id)
    )
    db.commit()
    return markør.rowcount == 1


def følger_person(følger_id, person_id):
    db = get_db()
    return db.execute(
        "SELECT 1 FROM følger_personer WHERE følger_id = ? AND person_id = ?",
        (følger_id, person_id),
    ).fetchone() is not None


def hent_alle_brugere(bruger_id):
    """Alle andre på siden, med dem brugeren følger øverst.

    Det er hele oversigten ved siden af ens egne lister: her findes folk, og herfra
    klikkes der videre til deres ønskelister.
    """
    db = get_db()
    return db.execute(
        """
        SELECT brugere.id, brugere.navn,
               følger_personer.id IS NOT NULL AS følger,
               (SELECT COUNT(*) FROM lister
                 WHERE lister.bruger_id = brugere.id AND lister.skjult_for_andre = 0) AS antal_lister
          FROM brugere
          LEFT JOIN følger_personer
                 ON følger_personer.person_id = brugere.id AND følger_personer.følger_id = ?
         WHERE brugere.id != ?
         ORDER BY følger DESC, brugere.navn COLLATE NOCASE
        """,
        (bruger_id, bruger_id),
    ).fetchall()


def hent_synlige_lister(person_id):
    """Personens lister, som de andre på siden ser dem – de skjulte er pillet ud."""
    db = get_db()
    return db.execute(
        """
        SELECT lister.*,
               (SELECT COUNT(*) FROM ønsker WHERE ønsker.liste_id = lister.id) AS antal,
               (SELECT billede FROM ønsker
                 WHERE ønsker.liste_id = lister.id AND billede IS NOT NULL AND billede != ''
                 ORDER BY id DESC LIMIT 1) AS forsidebillede
          FROM lister
         WHERE lister.bruger_id = ? AND lister.skjult_for_andre = 0
         ORDER BY lister.id DESC
        """,
        (person_id,),
    ).fetchall()
