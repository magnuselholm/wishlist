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

    db.executescript("""
        CREATE TABLE IF NOT EXISTS brugere (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            navn TEXT NOT NULL,
            adgangskode TEXT NOT NULL,
            oprettet TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lister (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bruger_id INTEGER NOT NULL REFERENCES brugere(id) ON DELETE CASCADE,
            titel TEXT NOT NULL,
            beskrivelse TEXT,
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

        CREATE INDEX IF NOT EXISTS idx_lister_bruger ON lister(bruger_id);
        CREATE INDEX IF NOT EXISTS idx_ønsker_liste ON ønsker(liste_id);
    """)
    db.commit()


def _nu():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


### brugere


def opret_bruger(email, navn, adgangskode_hash):
    db = get_db()
    markør = db.execute(
        "INSERT INTO brugere (email, navn, adgangskode, oprettet) VALUES (?, ?, ?, ?)",
        (email, navn, adgangskode_hash, _nu()),
    )
    db.commit()
    return markør.lastrowid


def hent_bruger_på_email(email):
    db = get_db()
    return db.execute("SELECT * FROM brugere WHERE email = ?", (email,)).fetchone()


def hent_bruger(bruger_id):
    db = get_db()
    return db.execute("SELECT * FROM brugere WHERE id = ?", (bruger_id,)).fetchone()


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


def opret_liste(bruger_id, titel, beskrivelse):
    db = get_db()
    markør = db.execute(
        "INSERT INTO lister (bruger_id, titel, beskrivelse, oprettet) VALUES (?, ?, ?, ?)",
        (bruger_id, titel, beskrivelse, _nu()),
    )
    db.commit()
    return markør.lastrowid


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
