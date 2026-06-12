import sqlite3
from config import Config

def get_db():
    db = sqlite3.connect("ønsker.db")
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS ønsker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ønske TEXT NOT NULL
        )
    """)
    db.commit()

def hent_ønsker():
    db = get_db()
    return db.execute("SELECT * FROM ønsker").fetchall()

def tilføj_ønske(tekst):
    db = get_db()
    db.execute("INSERT INTO ønsker (ønske) VALUES (?)", (tekst,))
    db.commit()

def slet_ønske(id):
    db = get_db()
    db.execute("DELETE FROM ønsker WHERE id = ?", (id,))
    db.commit()