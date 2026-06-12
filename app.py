from flask import Flask, render_template, request, redirect
import sqlite3

app = Flask(__name__)

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

init_db()

@app.route("/")
def index():
    db = get_db()
    ønsker = db.execute("SELECT * FROM ønsker").fetchall()
    return render_template("index.html", ønsker=ønsker)

@app.route("/tilføj", methods=["POST"])
def tilføj():
    ønske = request.form.get("ønske")
    if ønske:
        db = get_db()
        db.execute("INSERT INTO ønsker (ønske) VALUES (?)", (ønske,))
        db.commit()
    return redirect("/")

@app.route("/slet/<int:id>", methods=["POST"])
def slet(id):
    db = get_db()
    db.execute("DELETE FROM ønsker WHERE id = ?", (id,))
    db.commit()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)