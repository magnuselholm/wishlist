import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app, kroner  # noqa: E402
from app.skrab import SkrabFejl, _find_billede, _find_pris, _find_titel, _tjek_adresse, læs_pris  # noqa: E402
from config import Config  # noqa: E402


@pytest.fixture
def app(tmp_path):
    class Test(Config):
        DATABASE = str(tmp_path / "test.db")
        UPLOAD_MAPPE = str(tmp_path / "uploads")
        SECRET_KEY = "test"
        TESTING = True

    return create_app(Test)


@pytest.fixture
def klient(app):
    return app.test_client()


def opret_og_login(klient, email="test@eksempel.dk", kode="hemmeligt123"):
    return klient.post(
        "/opret-bruger",
        data={"navn": "Test Testesen", "email": email, "adgangskode": kode,
              "adgangskode_igen": kode, "_csrf": csrf(klient)},
        follow_redirects=True,
    )


def csrf(klient):
    """Henter det token serveren har lagt i sessionen."""
    with klient.session_transaction() as session:
        if "_csrf" not in session:
            session["_csrf"] = "test-token"
        return session["_csrf"]


### brugere


def test_opret_bruger_og_login(klient):
    svar = opret_og_login(klient)
    assert svar.status_code == 200
    assert "Mine ønskelister" in svar.get_data(as_text=True)

    klient.post("/logud", data={"_csrf": csrf(klient)})
    svar = klient.get("/lister", follow_redirects=True)
    assert "Log ind" in svar.get_data(as_text=True)

    svar = klient.post(
        "/login",
        data={"email": "test@eksempel.dk", "adgangskode": "hemmeligt123", "_csrf": csrf(klient)},
        follow_redirects=True,
    )
    assert "Mine ønskelister" in svar.get_data(as_text=True)


def test_forkert_adgangskode_afvises(klient):
    opret_og_login(klient)
    klient.post("/logud", data={"_csrf": csrf(klient)})

    svar = klient.post(
        "/login",
        data={"email": "test@eksempel.dk", "adgangskode": "forkert123", "_csrf": csrf(klient)},
    )
    assert svar.status_code == 401


def test_samme_email_kan_kun_bruges_en_gang(klient):
    opret_og_login(klient)
    klient.post("/logud", data={"_csrf": csrf(klient)})

    svar = opret_og_login(klient)
    assert "findes allerede" in svar.get_data(as_text=True)


def test_adgangskode_gemmes_ikke_i_klartekst(app, klient):
    opret_og_login(klient)
    with app.app_context():
        from app.models import hent_bruger_på_email

        bruger = hent_bruger_på_email("test@eksempel.dk")
    assert bruger["adgangskode"] != "hemmeligt123"


def test_login_kræves_for_lister(klient):
    svar = klient.get("/lister")
    assert svar.status_code == 302
    assert "/login" in svar.headers["Location"]


### lister og ønsker


def test_flere_lister_og_ønsker(klient):
    opret_og_login(klient)

    klient.post("/lister/opret", data={"titel": "Jul", "beskrivelse": "", "_csrf": csrf(klient)})
    klient.post("/lister/opret", data={"titel": "Fødselsdag", "beskrivelse": "", "_csrf": csrf(klient)})

    svar = klient.get("/lister")
    tekst = svar.get_data(as_text=True)
    assert "Jul" in tekst and "Fødselsdag" in tekst

    klient.post(
        "/liste/1/nyt-ønske",
        data={"titel": "Kaffekværn", "pris": "1.299,95", "link": "https://eksempel.dk/vare",
              "billede_url": "https://eksempel.dk/billede.jpg", "størrelse": "M",
              "beskrivelse": "Gerne i sort", "_csrf": csrf(klient)},
    )

    tekst = klient.get("/liste/1").get_data(as_text=True)
    assert "Kaffekværn" in tekst
    assert "1.299,95 kr." in tekst
    assert "Størrelse: M" in tekst
    assert "Gerne i sort" in tekst
    assert "https://eksempel.dk/billede.jpg" in tekst
    assert "https://eksempel.dk/vare" in tekst


def test_ønske_kan_redigeres_og_slettes(klient):
    opret_og_login(klient)
    klient.post("/lister/opret", data={"titel": "Jul", "_csrf": csrf(klient)})
    klient.post("/liste/1/nyt-ønske", data={"titel": "Bog", "_csrf": csrf(klient)})

    klient.post("/ønske/1/rediger", data={"titel": "Bog om kaffe", "pris": "199", "_csrf": csrf(klient)})
    tekst = klient.get("/liste/1").get_data(as_text=True)
    assert "Bog om kaffe" in tekst and "199 kr." in tekst

    klient.post("/ønske/1/slet", data={"_csrf": csrf(klient)})
    assert "Bog om kaffe" not in klient.get("/liste/1").get_data(as_text=True)


def test_ugyldig_pris_afvises(klient):
    opret_og_login(klient)
    klient.post("/lister/opret", data={"titel": "Jul", "_csrf": csrf(klient)})

    svar = klient.post("/liste/1/nyt-ønske", data={"titel": "Bog", "pris": "dyr", "_csrf": csrf(klient)})
    assert svar.status_code == 400
    assert "Prisen skal være et tal" in svar.get_data(as_text=True)


def test_liste_slettes_med_sine_ønsker(app, klient):
    opret_og_login(klient)
    klient.post("/lister/opret", data={"titel": "Jul", "_csrf": csrf(klient)})
    klient.post("/liste/1/nyt-ønske", data={"titel": "Bog", "_csrf": csrf(klient)})
    klient.post("/liste/1/slet", data={"_csrf": csrf(klient)})

    with app.app_context():
        from app.models import get_db

        assert get_db().execute("SELECT COUNT(*) AS n FROM ønsker").fetchone()["n"] == 0


def test_man_kan_ikke_se_andres_lister(app):
    a = app.test_client()
    opret_og_login(a, "a@eksempel.dk")
    a.post("/lister/opret", data={"titel": "Hemmelig liste", "_csrf": csrf(a)})
    a.post("/liste/1/nyt-ønske", data={"titel": "Hemmeligt ønske", "_csrf": csrf(a)})

    b = app.test_client()
    opret_og_login(b, "b@eksempel.dk")

    assert b.get("/liste/1").status_code == 404
    assert b.get("/ønske/1/rediger").status_code == 404
    assert b.post("/liste/1/slet", data={"_csrf": csrf(b)}).status_code == 404
    assert b.post("/ønske/1/slet", data={"_csrf": csrf(b)}).status_code == 404

    # listen ligger der stadig hos ejeren
    assert "Hemmeligt ønske" in a.get("/liste/1").get_data(as_text=True)


def test_manglende_csrf_token_afvises(klient):
    opret_og_login(klient)
    svar = klient.post("/lister/opret", data={"titel": "Uden token"})
    assert svar.status_code == 400


### billeder


def test_upload_af_billede(klient, app):
    opret_og_login(klient)
    klient.post("/lister/opret", data={"titel": "Jul", "_csrf": csrf(klient)})

    png = (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64), "billede.png")
    svar = klient.post(
        "/liste/1/nyt-ønske",
        data={"titel": "Med billede", "_csrf": csrf(klient), "billede_fil": png},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "/static/uploads/" in svar.get_data(as_text=True)
    assert len(list(Path(app.config["UPLOAD_MAPPE"]).iterdir())) == 1


def test_falsk_billedfil_afvises(klient):
    opret_og_login(klient)
    klient.post("/lister/opret", data={"titel": "Jul", "_csrf": csrf(klient)})

    svar = klient.post(
        "/liste/1/nyt-ønske",
        data={"titel": "Snyd", "_csrf": csrf(klient), "billede_fil": (io.BytesIO(b"<?php ?>"), "ondt.png")},
        content_type="multipart/form-data",
    )
    assert svar.status_code == 400
    assert "ligner ikke et billede" in svar.get_data(as_text=True)


### skrabning af links


HTML = """
<html><head>
  <title>Butik</title>
  <meta property="og:title" content="Kaffekværn Deluxe">
  <meta property="og:image" content="/billeder/kværn.jpg">
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"Product","name":"Kaffekværn Deluxe",
   "image":["https://butik.dk/billeder/kværn.jpg"],
   "offers":{"@type":"Offer","price":"1299.00","priceCurrency":"DKK"}}
  </script>
</head><body><h1>Kaffekværn</h1></body></html>
"""


def _suppe(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


def test_skrab_læser_json_ld():
    from app.skrab import _fra_json_ld

    suppe = _suppe(HTML)
    fra_json = _fra_json_ld(suppe)

    assert _find_titel(suppe, fra_json) == "Kaffekværn Deluxe"
    assert _find_pris(suppe, fra_json) == (1299.0, "DKK")
    assert _find_billede(suppe, fra_json, "https://butik.dk/vare") == "https://butik.dk/billeder/kværn.jpg"


def test_skrab_falder_tilbage_på_meta_tags():
    html = """<html><head>
      <meta property="og:title" content="Løbesko">
      <meta property="product:price:amount" content="899,50">
      <meta property="product:price:currency" content="DKK">
      <meta property="og:image" content="/sko.png">
    </head></html>"""
    suppe = _suppe(html)

    assert _find_titel(suppe, {}) == "Løbesko"
    assert _find_pris(suppe, {}) == (899.5, "DKK")
    assert _find_billede(suppe, {}, "https://butik.dk/sko/1") == "https://butik.dk/sko.png"


def test_skrab_bruger_titel_når_intet_andet_findes():
    suppe = _suppe("<html><head><title>  Bare   en side </title></head></html>")
    assert _find_titel(suppe, {}) == "Bare en side"
    assert _find_pris(suppe, {}) == (None, None)
    assert _find_billede(suppe, {}, "https://butik.dk/") is None


@pytest.mark.parametrize(
    "tekst, forventet",
    [
        ("1.299,00 kr.", 1299.0),
        ("1,299.00", 1299.0),
        ("kr. 249", 249.0),
        ("19,95", 19.95),
        ("19.95", 19.95),
        ("1.299", 1299.0),
        ("DKK 1 299,50", 1299.5),
        (899, 899.0),
        ("udsolgt", None),
        (None, None),
    ],
)
def test_læs_pris(tekst, forventet):
    assert læs_pris(tekst) == forventet


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1:80/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "file:///etc/passwd",
        "http://eksempel.dk:22/",
    ],
)
def test_interne_adresser_blokeres(url):
    with pytest.raises(SkrabFejl):
        _tjek_adresse(url)


def test_skrab_kræver_login(klient):
    svar = klient.post("/api/skrab", json={"url": "https://eksempel.dk"})
    assert svar.status_code in (302, 400)


### visning


@pytest.mark.parametrize(
    "beløb, forventet",
    [(1299.0, "1.299 kr."), (1299.5, "1.299,50 kr."), (0.0, "0 kr."), (None, "")],
)
def test_kroner(beløb, forventet):
    assert kroner(beløb) == forventet


### hele vejen igennem: hentning + udtræk mod en rigtig HTTP-server


@pytest.fixture
def butik():
    """Lille lokal webserver der spiller webshop."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    sider = {
        "/vare": (200, "text/html; charset=utf-8", HTML),
        "/videre": (302, None, None),
        "/billede.jpg": (200, "image/jpeg", "ikke html"),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/videre":
                self.send_response(302)
                self.send_header("Location", "/vare")
                self.end_headers()
                return
            kode, type_, krop = sider.get(self.path, (404, "text/html", "findes ikke"))
            data = krop.encode("utf-8")
            self.send_response(kode)
            self.send_header("Content-Type", type_)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def uden_adressetjek(monkeypatch):
    """Serveren kører på 127.0.0.1, som skrab med vilje nægter at hente."""
    monkeypatch.setattr("app.skrab._tjek_adresse", lambda url: None)


def test_skrab_henter_og_læser_en_side(butik, uden_adressetjek):
    from app.skrab import skrab

    resultat = skrab(butik + "/vare")
    assert resultat["titel"] == "Kaffekværn Deluxe"
    assert resultat["pris"] == 1299.0
    assert resultat["valuta"] == "DKK"
    assert resultat["billede"] == "https://butik.dk/billeder/kværn.jpg"


def test_skrab_følger_omdirigering(butik, uden_adressetjek):
    from app.skrab import skrab

    resultat = skrab(butik + "/videre")
    assert resultat["titel"] == "Kaffekværn Deluxe"
    assert resultat["url"] == butik + "/vare"


def test_skrab_afviser_andet_end_websider(butik, uden_adressetjek):
    from app.skrab import skrab

    with pytest.raises(SkrabFejl, match="almindelig webside"):
        skrab(butik + "/billede.jpg")


def test_skrab_melder_fejl_ved_404(butik, uden_adressetjek):
    from app.skrab import skrab

    with pytest.raises(SkrabFejl, match="404"):
        skrab(butik + "/findes-ikke")


def test_api_skrab_tager_csrf_i_header(klient):
    opret_og_login(klient)

    svar = klient.post("/api/skrab", json={"url": "http://127.0.0.1/"})
    assert svar.status_code == 400  # uden token

    svar = klient.post(
        "/api/skrab", json={"url": "http://127.0.0.1/"}, headers={"X-CSRF-Token": csrf(klient)}
    )
    assert svar.status_code == 400
    assert "intern adresse" in svar.get_json()["fejl"]


def test_gammel_database_migreres(tmp_path):
    """Den tidligere udgave havde én tabel uden brugere – den skal ikke gå tabt."""
    import sqlite3

    sti = tmp_path / "gammel.db"
    gammel = sqlite3.connect(sti)
    gammel.execute("""CREATE TABLE ønsker (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ønske TEXT NOT NULL, pris TEXT, link TEXT, billede TEXT)""")
    gammel.execute("INSERT INTO ønsker (ønske, pris) VALUES ('Gammelt ønske', '99')")
    gammel.commit()
    gammel.close()

    class Test(Config):
        DATABASE = str(sti)
        UPLOAD_MAPPE = str(tmp_path / "uploads")
        SECRET_KEY = "test"
        TESTING = True

    app = create_app(Test)

    # den nye app virker …
    klient = app.test_client()
    opret_og_login(klient)
    klient.post("/lister/opret", data={"titel": "Ny liste", "_csrf": csrf(klient)})
    assert "Ny liste" in klient.get("/lister").get_data(as_text=True)

    # … og de gamle rækker ligger stadig i basen
    db = sqlite3.connect(sti)
    assert db.execute("SELECT ønske FROM ønsker_gammel").fetchone()[0] == "Gammelt ønske"
    db.close()
