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

        -- en gæst kan reservere et ønske. Ejeren får aldrig de her rækker at se.
        CREATE TABLE IF NOT EXISTS reservationer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ønske_id INTEGER NOT NULL UNIQUE REFERENCES ønsker(id) ON DELETE CASCADE,
            gæst TEXT NOT NULL,
            oprettet TEXT NOT NULL
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
    db.execute(
        "UPDATE lister SET del_nøgle = ? WHERE id = ? AND bruger_id = ?",
        (nøgle, liste_id, bruger_id),
    )
    db.commit()
    return nøgle


def opdater_liste(liste_id, bruger_id, titel, beskrivelse):
    db = get_db()
    db.execute(
        "UPDATE lister SET titel = ?, beskrivelse = ? WHERE id = ? AND bruger_id = ?",
        (titel, beskrivelse, liste_id, bruger_id),
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


def hent_ønsker_til_gæst(liste_id, gæst):
    """Som hent_ønsker, men med reservationerne. Bruges kun i gæstevisningen."""
    db = get_db()
    return db.execute(
        """
        SELECT ønsker.*,
               reservationer.id IS NOT NULL AS reserveret,
               COALESCE(reservationer.gæst = ?, 0) AS min_reservation
          FROM ønsker
          LEFT JOIN reservationer ON reservationer.ønske_id = ønsker.id
         WHERE ønsker.liste_id = ?
         ORDER BY ønsker.id DESC
        """,
        (gæst, liste_id),
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


def reserver_ønske(ønske_id, gæst):
    """Reserverer et ønske. Falsk hvis en anden nåede det først."""
    db = get_db()
    markør = db.execute(
        "INSERT OR IGNORE INTO reservationer (ønske_id, gæst, oprettet) VALUES (?, ?, ?)",
        (ønske_id, gæst, _nu()),
    )
    db.commit()
    return markør.rowcount == 1


def fortryd_reservation(ønske_id, gæst):
    """Fjerner en reservation. Falsk hvis den tilhører en anden gæst."""
    db = get_db()
    markør = db.execute(
        "DELETE FROM reservationer WHERE ønske_id = ? AND gæst = ?", (ønske_id, gæst)
    )
    db.commit()
    return markør.rowcount == 1
