import sqlite3
from config import Config

### Database funktioner

def get_db():
    db = sqlite3.connect("ønsker.db")
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS ønsker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ønske TEXT NOT NULL,
            pris TEXT,
            link TEXT,
            billede TEXT
        )
    """)
    db.commit()

def hent_ønsker():
    db = get_db()
    return db.execute("SELECT * FROM ønsker").fetchall()

def tilføj_ønske(tekst, pris, link, billede):
    db = get_db()
    db.execute("INSERT INTO ønsker (ønske, pris, link, billede) VALUES (?, ?, ?, ?)", (tekst, pris, link, billede))
    db.commit()

def slet_ønske(id):
    db = get_db()
    db.execute("DELETE FROM ønsker WHERE id = ?", (id,))
    db.commit()