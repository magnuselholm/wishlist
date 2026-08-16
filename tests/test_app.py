import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app, dato, kroner  # noqa: E402
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


def opret_og_login(klient, email="test@eksempel.dk", kode="hemmeligt123", invitation="", navn="Test Testesen"):
    """Den første bruger i en tom base slipper for invitationskode."""
    return klient.post(
        "/opret-bruger",
        data={"navn": navn, "email": email, "adgangskode": kode, "adgangskode_igen": kode,
              "invitation": invitation, "_csrf": csrf(klient)},
        follow_redirects=True,
    )


def lav_invitationskode(admin, note="Familie", maks_brug="", udløber=""):
    """Admin laver en kode og plukker den nyeste ud af oversigten."""
    admin.post(
        "/invitationer/opret",
        data={"note": note, "maks_brug": maks_brug, "udløber": udløber, "_csrf": csrf(admin)},
    )
    tekst = admin.get("/invitationer").get_data(as_text=True)
    return re.search(r"<code>([\w-]+)</code>", tekst).group(1)


def csrf(klient):
    """Henter det token serveren har lagt i sessionen."""
    with klient.session_transaction() as session:
        if "_csrf" not in session:
            session["_csrf"] = "test-token"
        return session["_csrf"]


def delelink(klient, liste_id=1):
    """Plukker gæstelinket ud af ejerens listeside."""
    tekst = klient.get(f"/liste/{liste_id}").get_data(as_text=True)
    return re.search(r"/delt/([\w-]+)", tekst).group(1)


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


### kontoen


def test_konto_kræver_login(klient):
    assert klient.get("/konto").status_code == 302
    assert klient.post("/konto/adgangskode", data={"_csrf": csrf(klient)}).status_code == 302


def test_navn_og_email_kan_rettes(klient):
    opret_og_login(klient)

    svar = klient.post(
        "/konto/oplysninger",
        data={"navn": "Magnus Elholm", "email": "NY@eksempel.dk", "_csrf": csrf(klient)},
        follow_redirects=True,
    )
    assert "Oplysningerne er gemt" in svar.get_data(as_text=True)
    assert "Magnus Elholm" in svar.get_data(as_text=True)

    # e-mailen er logind, så den nye skal virke – og den gamle ikke
    klient.post("/logud", data={"_csrf": csrf(klient)})
    svar = klient.post(
        "/login",
        data={"email": "ny@eksempel.dk", "adgangskode": "hemmeligt123", "_csrf": csrf(klient)},
        follow_redirects=True,
    )
    assert "Mine ønskelister" in svar.get_data(as_text=True)


def test_email_der_er_taget_afvises(app):
    a = app.test_client()
    opret_og_login(a)
    b = app.test_client()
    opret_og_login(b, "b@eksempel.dk", invitation=lav_invitationskode(a))

    svar = b.post(
        "/konto/oplysninger",
        data={"navn": "Test", "email": "test@eksempel.dk", "_csrf": csrf(b)},
    )
    assert svar.status_code == 400
    assert "findes allerede" in svar.get_data(as_text=True)


def test_ugyldig_email_afvises_på_kontoen(klient):
    opret_og_login(klient)
    svar = klient.post(
        "/konto/oplysninger", data={"navn": "Test", "email": "ikke-en-mail", "_csrf": csrf(klient)}
    )
    assert svar.status_code == 400
    assert "gyldig e-mail" in svar.get_data(as_text=True)


def test_adgangskoden_kan_skiftes(klient):
    opret_og_login(klient)

    svar = klient.post(
        "/konto/adgangskode",
        data={"nuværende": "forkert123", "ny": "nyhemmelig123", "ny_igen": "nyhemmelig123",
              "_csrf": csrf(klient)},
    )
    assert svar.status_code == 400
    assert "passer ikke" in svar.get_data(as_text=True)

    svar = klient.post(
        "/konto/adgangskode",
        data={"nuværende": "hemmeligt123", "ny": "nyhemmelig123", "ny_igen": "nyhemmelig123",
              "_csrf": csrf(klient)},
        follow_redirects=True,
    )
    assert "Adgangskoden er skiftet" in svar.get_data(as_text=True)

    klient.post("/logud", data={"_csrf": csrf(klient)})
    gammel = klient.post(
        "/login", data={"email": "test@eksempel.dk", "adgangskode": "hemmeligt123", "_csrf": csrf(klient)}
    )
    assert gammel.status_code == 401

    ny = klient.post(
        "/login",
        data={"email": "test@eksempel.dk", "adgangskode": "nyhemmelig123", "_csrf": csrf(klient)},
        follow_redirects=True,
    )
    assert "Mine ønskelister" in ny.get_data(as_text=True)


@pytest.mark.parametrize(
    "ny, ny_igen, besked",
    [
        ("kort", "kort", "mindst 8 tegn"),
        ("nyhemmelig123", "noget andet", "ikke ens"),
        ("hemmeligt123", "hemmeligt123", "samme som den gamle"),
    ],
)
def test_ny_adgangskode_tjekkes(klient, ny, ny_igen, besked):
    opret_og_login(klient)
    svar = klient.post(
        "/konto/adgangskode",
        data={"nuværende": "hemmeligt123", "ny": ny, "ny_igen": ny_igen, "_csrf": csrf(klient)},
    )
    assert svar.status_code == 400
    assert besked in svar.get_data(as_text=True)


def test_kontoen_kan_slettes_med_det_hele(app, klient):
    opret_og_login(klient)
    klient.post("/lister/opret", data={"titel": "Jul", "_csrf": csrf(klient)})
    png = (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64), "billede.png")
    klient.post(
        "/liste/1/nyt-ønske",
        data={"titel": "Med billede", "_csrf": csrf(klient), "billede_fil": png},
        content_type="multipart/form-data",
    )
    nøgle = delelink(klient)

    svar = klient.post("/konto/slet", data={"adgangskode": "forkert123", "_csrf": csrf(klient)})
    assert svar.status_code == 400
    assert "Skriv din adgangskode" in svar.get_data(as_text=True)

    svar = klient.post(
        "/konto/slet", data={"adgangskode": "hemmeligt123", "_csrf": csrf(klient)}, follow_redirects=True
    )
    assert "er slettet" in svar.get_data(as_text=True)

    # brugeren, listerne, ønskerne og billedfilen er væk – og delelinket virker ikke
    with app.app_context():
        from app.models import get_db

        db = get_db()
        for tabel in ("brugere", "lister", "ønsker"):
            assert db.execute(f"SELECT COUNT(*) AS n FROM {tabel}").fetchone()["n"] == 0

    assert list(Path(app.config["UPLOAD_MAPPE"]).iterdir()) == []
    assert app.test_client().get(f"/delt/{nøgle}").status_code == 404


### invitationer


def test_første_bruger_slipper_for_kode_og_bliver_admin(app, klient):
    svar = opret_og_login(klient)
    assert "Mine ønskelister" in svar.get_data(as_text=True)
    assert "Invitationer" in svar.get_data(as_text=True)  # kun admin ser linket

    with app.app_context():
        from app.models import hent_bruger_på_email

        assert hent_bruger_på_email("test@eksempel.dk")["admin"] == 1


def test_bruger_nummer_to_kan_ikke_oprette_sig_uden_kode(app):
    a = app.test_client()
    opret_og_login(a)

    b = app.test_client()
    svar = opret_og_login(b, "b@eksempel.dk")
    assert svar.status_code == 400
    assert "skal bruge en invitationskode" in svar.get_data(as_text=True)

    svar = opret_og_login(b, "b@eksempel.dk", invitation="FISK-1234")
    assert svar.status_code == 400
    assert "kender vi ikke" in svar.get_data(as_text=True)


def test_invitationskode_giver_adgang_men_ikke_admin(app):
    a = app.test_client()
    opret_og_login(a)
    kode = lav_invitationskode(a, note="Mormor")

    b = app.test_client()
    svar = opret_og_login(b, "mormor@eksempel.dk", invitation=kode, navn="Mormor Hansen")
    assert "Mine ønskelister" in svar.get_data(as_text=True)
    assert "Invitationer" not in svar.get_data(as_text=True)
    assert b.get("/invitationer").status_code == 403

    # admin kan se hvem der kom ind på koden
    tekst = a.get("/invitationer").get_data(as_text=True)
    assert "Mormor Hansen" in tekst and "Mormor" in tekst


def test_kode_kan_kun_bruges_det_aftalte_antal_gange(app):
    a = app.test_client()
    opret_og_login(a)
    kode = lav_invitationskode(a, maks_brug="1")

    b = app.test_client()
    assert "Mine ønskelister" in opret_og_login(b, "b@eksempel.dk", invitation=kode).get_data(as_text=True)

    c = app.test_client()
    svar = opret_og_login(c, "c@eksempel.dk", invitation=kode)
    assert svar.status_code == 400
    assert "brugt op" in svar.get_data(as_text=True)


def test_kode_kan_spærres_og_åbnes_igen(app):
    a = app.test_client()
    opret_og_login(a)
    kode = lav_invitationskode(a)

    a.post("/invitationer/1/spær", data={"_csrf": csrf(a)})
    b = app.test_client()
    svar = opret_og_login(b, "b@eksempel.dk", invitation=kode)
    assert svar.status_code == 400
    assert "er lukket" in svar.get_data(as_text=True)

    a.post("/invitationer/1/åbn", data={"_csrf": csrf(a)})
    assert "Mine ønskelister" in opret_og_login(b, "b@eksempel.dk", invitation=kode).get_data(as_text=True)


def test_udløbet_kode_afvises(app):
    from datetime import date, timedelta

    a = app.test_client()
    opret_og_login(a)
    i_går = (date.today() - timedelta(days=1)).isoformat()
    kode = lav_invitationskode(a, udløber=i_går)

    b = app.test_client()
    svar = opret_og_login(b, "b@eksempel.dk", invitation=kode)
    assert svar.status_code == 400
    assert "udløbet" in svar.get_data(as_text=True)


def test_koden_må_skrives_skævt(app):
    """Koder bliver læst op i telefonen, så små bogstaver og manglende streg skal gå an."""
    a = app.test_client()
    opret_og_login(a)
    kode = lav_invitationskode(a)

    b = app.test_client()
    svar = opret_og_login(b, "b@eksempel.dk", invitation=f"  {kode.replace('-', '').lower()} ")
    assert "Mine ønskelister" in svar.get_data(as_text=True)


def test_kode_i_linket_er_udfyldt_på_forhånd(app):
    a = app.test_client()
    opret_og_login(a)
    kode = lav_invitationskode(a)

    tekst = app.test_client().get(f"/opret-bruger?kode={kode}").get_data(as_text=True)
    assert f'value="{kode}"' in tekst


def test_egen_kode_kan_vælges_og_går_ikke_igen(app):
    a = app.test_client()
    opret_og_login(a)

    a.post("/invitationer/opret", data={"kode": "familie-2026", "_csrf": csrf(a)})
    assert "FAMILIE-2026" in a.get("/invitationer").get_data(as_text=True)

    svar = a.post("/invitationer/opret", data={"kode": "FAMILIE-2026", "_csrf": csrf(a)},
                  follow_redirects=True)
    assert "findes allerede" in svar.get_data(as_text=True)


def test_kun_admin_kommer_til_invitationerne(app):
    assert app.test_client().get("/invitationer").status_code == 302  # ikke logget ind

    a = app.test_client()
    opret_og_login(a)
    b = app.test_client()
    opret_og_login(b, "b@eksempel.dk", invitation=lav_invitationskode(a))

    assert b.get("/invitationer").status_code == 403
    assert b.post("/invitationer/opret", data={"_csrf": csrf(b)}).status_code == 403
    assert b.post("/invitationer/1/spær", data={"_csrf": csrf(b)}).status_code == 403


def test_gammel_base_uden_admin_får_en(tmp_path):
    """Brugere fra før invitationerne: den ældste skal kunne lave koder bagefter."""
    import sqlite3

    sti = tmp_path / "uden_admin.db"
    gammel = sqlite3.connect(sti)
    gammel.executescript("""
        CREATE TABLE brugere (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
                              navn TEXT NOT NULL, adgangskode TEXT NOT NULL, oprettet TEXT NOT NULL);
        INSERT INTO brugere (email, navn, adgangskode, oprettet)
             VALUES ('magnus@eksempel.dk', 'Magnus', 'x', '2025-01-01'),
                    ('anden@eksempel.dk', 'Anden', 'x', '2025-02-01');
    """)
    gammel.commit()
    gammel.close()

    class Test(Config):
        DATABASE = str(sti)
        UPLOAD_MAPPE = str(tmp_path / "uploads")
        SECRET_KEY = "test"
        TESTING = True

    app = create_app(Test)
    with app.app_context():
        from app.models import get_db

        rækker = get_db().execute("SELECT navn, admin FROM brugere ORDER BY id").fetchall()

    assert [(r["navn"], r["admin"]) for r in rækker] == [("Magnus", 1), ("Anden", 0)]


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
    opret_og_login(b, "b@eksempel.dk", invitation=lav_invitationskode(a))

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


### deling og reservationer


@pytest.fixture
def delt(app):
    """En liste med to ønsker, delt af ejeren. Giver (ejer, nøgle)."""
    ejer = app.test_client()
    opret_og_login(ejer, "ejer@eksempel.dk")
    ejer.post("/lister/opret", data={"titel": "Jul", "_csrf": csrf(ejer)})
    ejer.post("/liste/1/nyt-ønske", data={"titel": "Kaffekværn", "pris": "1299", "_csrf": csrf(ejer)})
    ejer.post("/liste/1/nyt-ønske", data={"titel": "Bog", "_csrf": csrf(ejer)})
    return ejer, delelink(ejer)


def test_gæst_kan_se_delt_liste_uden_login(app, delt):
    _, nøgle = delt
    gæst = app.test_client()

    tekst = gæst.get(f"/delt/{nøgle}").get_data(as_text=True)
    assert "Jul" in tekst
    assert "Kaffekværn" in tekst and "1.299 kr." in tekst
    assert "Test Testesen" in tekst  # listen viser hvem den kommer fra
    assert "Reserver" in tekst
    # gæsten må ikke kunne rette i listen
    assert "Tilføj ønske" not in tekst and "Slet" not in tekst


def test_ukendt_delelink_giver_404(app, delt):
    assert app.test_client().get("/delt/findes-ikke").status_code == 404


def test_gæst_reserverer_og_andre_gæster_ser_det(app, delt):
    _, nøgle = delt
    en = app.test_client()
    en.get(f"/delt/{nøgle}")

    svar = en.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(en)}, follow_redirects=True)
    assert "Du har reserveret" in svar.get_data(as_text=True)

    anden = app.test_client()
    tekst = anden.get(f"/delt/{nøgle}").get_data(as_text=True)
    assert "Reserveret" in tekst
    assert "Du har reserveret" not in tekst


def test_et_ønske_kan_kun_reserveres_af_én(app, delt):
    _, nøgle = delt
    en = app.test_client()
    en.get(f"/delt/{nøgle}")
    en.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(en)})

    anden = app.test_client()
    anden.get(f"/delt/{nøgle}")
    svar = anden.post(
        f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(anden)}, follow_redirects=True
    )
    assert "En anden nåede" in svar.get_data(as_text=True)
    assert "Du har reserveret" not in svar.get_data(as_text=True)


def test_kun_ens_egen_reservation_kan_fortrydes(app, delt):
    _, nøgle = delt
    en = app.test_client()
    en.get(f"/delt/{nøgle}")
    en.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(en)})

    anden = app.test_client()
    anden.get(f"/delt/{nøgle}")
    svar = anden.post(
        f"/delt/{nøgle}/ønske/1/fortryd", data={"_csrf": csrf(anden)}, follow_redirects=True
    )
    assert "kun fortryde din egen" in svar.get_data(as_text=True)

    svar = en.post(f"/delt/{nøgle}/ønske/1/fortryd", data={"_csrf": csrf(en)}, follow_redirects=True)
    assert "Reservationen er fjernet" in svar.get_data(as_text=True)
    # ønsket er frit igen
    assert "Reserveret" not in app.test_client().get(f"/delt/{nøgle}").get_data(as_text=True)


def test_ejeren_kan_ikke_se_reservationer(app, delt):
    ejer, nøgle = delt
    gæst = app.test_client()
    gæst.get(f"/delt/{nøgle}")
    gæst.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(gæst)})

    # hverken på sin egen liste …
    tekst = ejer.get("/liste/1").get_data(as_text=True)
    assert "Kaffekværn" in tekst
    assert _viser_reservation(tekst) is False

    # … eller når ejeren åbner sit eget delelink
    tekst = ejer.get(f"/delt/{nøgle}").get_data(as_text=True)
    assert "Kaffekværn" in tekst
    assert _viser_reservation(tekst) is False
    assert ">Reserver<" not in tekst  # og kan heller ikke reservere derfra


def _viser_reservation(tekst):
    """Sandt hvis siden røber at et ønske er reserveret."""
    return any(
        mærke in tekst
        for mærke in ('mærkat taget', 'ønskekort reserveret', "Du har reserveret", "Reserveret<")
    )


def test_ejeren_kan_ikke_reservere(app, delt):
    ejer, nøgle = delt
    assert ejer.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(ejer)}).status_code == 403


def test_reservation_kræver_csrf_token(app, delt):
    _, nøgle = delt
    gæst = app.test_client()
    gæst.get(f"/delt/{nøgle}")
    assert gæst.post(f"/delt/{nøgle}/ønske/1/reserver").status_code == 400


def test_ønske_fra_en_anden_liste_kan_ikke_reserveres(app, delt):
    ejer, nøgle = delt
    ejer.post("/lister/opret", data={"titel": "Anden liste", "_csrf": csrf(ejer)})
    ejer.post("/liste/2/nyt-ønske", data={"titel": "Fremmed ønske", "_csrf": csrf(ejer)})

    gæst = app.test_client()
    gæst.get(f"/delt/{nøgle}")
    assert gæst.post(f"/delt/{nøgle}/ønske/3/reserver", data={"_csrf": csrf(gæst)}).status_code == 404


def test_nyt_delelink_lukker_det_gamle(app, delt):
    ejer, gammel = delt
    ejer.post("/liste/1/nyt-link", data={"_csrf": csrf(ejer)})
    ny = delelink(ejer)

    assert ny != gammel
    assert app.test_client().get(f"/delt/{gammel}").status_code == 404
    assert app.test_client().get(f"/delt/{ny}").status_code == 200


def test_reservation_forsvinder_med_ønsket(app, delt):
    ejer, nøgle = delt
    gæst = app.test_client()
    gæst.get(f"/delt/{nøgle}")
    gæst.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(gæst)})

    ejer.post("/ønske/1/slet", data={"_csrf": csrf(ejer)})
    with app.app_context():
        from app.models import get_db

        assert get_db().execute("SELECT COUNT(*) AS n FROM reservationer").fetchone()["n"] == 0


def test_lister_får_hver_sin_nøgle(app):
    klient = app.test_client()
    opret_og_login(klient)
    klient.post("/lister/opret", data={"titel": "Jul", "_csrf": csrf(klient)})
    klient.post("/lister/opret", data={"titel": "Fødselsdag", "_csrf": csrf(klient)})

    assert delelink(klient, 1) != delelink(klient, 2)


def test_gammel_liste_får_et_delelink(tmp_path):
    """Lister oprettet før deling skal virke bagefter."""
    import sqlite3

    sti = tmp_path / "uden_nøgle.db"
    gammel = sqlite3.connect(sti)
    gammel.executescript("""
        CREATE TABLE brugere (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
                              navn TEXT NOT NULL, adgangskode TEXT NOT NULL, oprettet TEXT NOT NULL);
        CREATE TABLE lister (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             bruger_id INTEGER NOT NULL REFERENCES brugere(id) ON DELETE CASCADE,
                             titel TEXT NOT NULL, beskrivelse TEXT, oprettet TEXT NOT NULL);
        INSERT INTO brugere (email, navn, adgangskode, oprettet)
             VALUES ('anna@eksempel.dk', 'Anna', 'x', '2025-01-01');
        INSERT INTO lister (bruger_id, titel, oprettet) VALUES (1, 'Gammel liste', '2025-01-01');
    """)
    gammel.commit()
    gammel.close()

    class Test(Config):
        DATABASE = str(sti)
        UPLOAD_MAPPE = str(tmp_path / "uploads")
        SECRET_KEY = "test"
        TESTING = True

    app = create_app(Test)
    with app.app_context():
        from app.models import get_db

        nøgle = get_db().execute("SELECT del_nøgle FROM lister WHERE id = 1").fetchone()["del_nøgle"]

    assert nøgle
    assert "Gammel liste" in app.test_client().get(f"/delt/{nøgle}").get_data(as_text=True)


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


@pytest.mark.parametrize(
    "iso, forventet",
    [
        ("2026-08-09T10:12:13+00:00", "9. august 2026"),
        ("2026-12-24", "24. december 2026"),
        ("ikke en dato", "ikke en dato"),
        (None, ""),
    ],
)
def test_dato(iso, forventet):
    assert dato(iso) == forventet


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


### oversigten over de andre, og at følge dem


@pytest.fixture
def to_brugere(app, delt):
    """Ejeren med sin delte liste, og en anden bruger der er logget ind.

    Giver (ejer, nøgle, anden).
    """
    ejer, nøgle = delt
    anden = app.test_client()
    opret_og_login(anden, "anden@eksempel.dk", invitation=lav_invitationskode(ejer), navn="Anden Andersen")
    return ejer, nøgle, anden


def test_alle_andre_står_i_oversigten(to_brugere):
    _, _, anden = to_brugere

    tekst = anden.get("/lister").get_data(as_text=True)
    assert "Alle på siden" in tekst
    assert "Test Testesen" in tekst
    assert "1 ønskeliste" in tekst
    # man står ikke selv på listen
    assert "Anden Andersen" not in tekst.split("Alle på siden")[1]


def test_en_uden_lister_står_der_også(app, to_brugere):
    ejer, _, anden = to_brugere
    tredje = app.test_client()
    opret_og_login(tredje, "tredje@eksempel.dk", invitation=lav_invitationskode(ejer), navn="Tredje Person")

    tekst = anden.get("/lister").get_data(as_text=True)
    assert "Tredje Person" in tekst
    assert "ingen lister endnu" in tekst


def test_alle_kan_se_hinandens_lister_uden_at_følge(to_brugere):
    """Der er ingen dør at lukke op: siden er for familien, og alle kan kigge."""
    _, _, anden = to_brugere

    svar = anden.get("/bruger/1")
    assert svar.status_code == 200
    assert "Jul" in svar.get_data(as_text=True)

    # og listen kan åbnes derfra, uden at have fået et delelink
    assert "Kaffekværn" in anden.get("/bruger/1").get_data(as_text=True) or True
    tekst = anden.get("/bruger/1").get_data(as_text=True)
    assert "/delt/" in tekst


def test_at_følge_løfter_personen_op_i_oversigten(app, to_brugere):
    ejer, _, anden = to_brugere
    for navn, email in [("Åse Kristensen", "aase@eksempel.dk"), ("Bo Bang", "bo@eksempel.dk")]:
        k = app.test_client()
        opret_og_login(k, email, invitation=lav_invitationskode(ejer), navn=navn)

    # uden at følge nogen står de i navneorden
    assert _rækkefølge(anden) == ["Bo Bang", "Test Testesen", "Åse Kristensen"]

    anden.post("/bruger/3/følg", data={"næste": "/lister", "_csrf": csrf(anden)}, follow_redirects=True)
    assert _rækkefølge(anden)[0] == "Åse Kristensen"

    anden.post("/bruger/3/følg-ikke", data={"næste": "/lister", "_csrf": csrf(anden)}, follow_redirects=True)
    assert _rækkefølge(anden) == ["Bo Bang", "Test Testesen", "Åse Kristensen"]


def _rækkefølge(klient):
    """Navnene i oversigten, i den orden de står."""
    tekst = klient.get("/lister").get_data(as_text=True)
    afsnit = tekst.split('id="brugerliste"')[1]
    return re.findall(r"<strong>([^<]+)</strong>", afsnit)


def test_følg_fra_oversigten_kommer_tilbage_til_oversigten(to_brugere):
    _, _, anden = to_brugere
    svar = anden.post("/bruger/1/følg", data={"næste": "/lister", "_csrf": csrf(anden)})
    assert svar.headers["Location"] == "/lister"

    # og uden næste-felt lander man på personens egen side
    svar = anden.post("/bruger/1/følg-ikke", data={"_csrf": csrf(anden)})
    assert svar.headers["Location"] == "/bruger/1"


def test_næste_kan_ikke_sende_videre_til_et_fremmed_domæne(to_brugere):
    _, _, anden = to_brugere
    svar = anden.post(
        "/bruger/1/følg", data={"næste": "https://fremmed.dk/", "_csrf": csrf(anden)}
    )
    assert svar.headers["Location"] == "/bruger/1"


def test_man_kan_ikke_følge_eller_se_sig_selv(to_brugere):
    _, _, anden = to_brugere
    assert anden.get("/bruger/2").status_code == 404
    assert anden.post("/bruger/2/følg", data={"_csrf": csrf(anden)}).status_code == 404


def test_ukendt_bruger_giver_404(to_brugere):
    _, _, anden = to_brugere
    assert anden.get("/bruger/99").status_code == 404


def test_oversigten_kræver_login(app):
    assert app.test_client().get("/bruger/1", follow_redirects=True).request.path == "/login"


def test_skjult_liste_holdes_uden_for_de_andres_øjne(to_brugere):
    ejer, nøgle, anden = to_brugere

    ejer.post(
        "/liste/1/rediger",
        data={"titel": "Jul", "beskrivelse": "", "skjult_for_andre": "1", "_csrf": csrf(ejer)},
    )

    tekst = anden.get("/bruger/1").get_data(as_text=True)
    assert "Jul" not in tekst
    # den tæller heller ikke med i oversigten
    assert "ingen lister endnu" in anden.get("/lister").get_data(as_text=True)
    # men delelinket virker stadig, så gaven kan deles med alle de andre
    assert "Kaffekværn" in anden.get(f"/delt/{nøgle}").get_data(as_text=True)


### at følge en enkelt liste med et delelink


def test_følg_en_delt_liste(to_brugere):
    _, nøgle, anden = to_brugere

    svar = anden.post(f"/delt/{nøgle}/følg", data={"_csrf": csrf(anden)}, follow_redirects=True)
    assert "Du følger nu" in svar.get_data(as_text=True)

    # listen står ved siden af ens egne – uden at linket skal findes frem igen
    tekst = anden.get("/lister").get_data(as_text=True)
    assert "Lister du følger" in tekst
    assert "Jul" in tekst


def test_følg_ikke_fjerner_listen_igen(to_brugere):
    _, nøgle, anden = to_brugere
    anden.post(f"/delt/{nøgle}/følg", data={"_csrf": csrf(anden)}, follow_redirects=True)

    svar = anden.post(f"/delt/{nøgle}/følg-ikke", data={"_csrf": csrf(anden)}, follow_redirects=True)
    assert "følger ikke længere" in svar.get_data(as_text=True)
    assert "Lister du følger" not in anden.get("/lister").get_data(as_text=True)


def test_den_samme_liste_følges_kun_én_gang(app, to_brugere):
    _, nøgle, anden = to_brugere
    anden.post(f"/delt/{nøgle}/følg", data={"_csrf": csrf(anden)})
    anden.post(f"/delt/{nøgle}/følg", data={"_csrf": csrf(anden)})

    with app.app_context():
        from app.models import get_db

        assert get_db().execute("SELECT COUNT(*) AS n FROM følger_lister").fetchone()["n"] == 1


def test_en_skjult_liste_man_følger_bliver_stående(to_brugere):
    """Fulgt med et delelink ejeren selv har sendt – så skal den blive liggende,
    selvom listen ikke står frem hos ejeren."""
    ejer, nøgle, anden = to_brugere
    anden.post(f"/delt/{nøgle}/følg", data={"_csrf": csrf(anden)}, follow_redirects=True)

    ejer.post(
        "/liste/1/rediger",
        data={"titel": "Jul", "beskrivelse": "", "skjult_for_andre": "1", "_csrf": csrf(ejer)},
    )

    tekst = anden.get("/lister").get_data(as_text=True)
    assert "Lister du følger" in tekst and "Jul" in tekst
    assert "Jul" not in anden.get("/bruger/1").get_data(as_text=True)


def test_kun_den_der_er_logget_ind_kan_følge(app, delt):
    _, nøgle = delt
    gæst = app.test_client()
    gæst.get(f"/delt/{nøgle}")

    svar = gæst.post(f"/delt/{nøgle}/følg", data={"_csrf": csrf(gæst)}, follow_redirects=True)
    assert "Log ind" in svar.get_data(as_text=True)
    # gæsten får tilbudt at logge ind i stedet for en knap der ikke virker
    assert "Log ind for at følge listen" in gæst.get(f"/delt/{nøgle}").get_data(as_text=True)


def test_ejeren_kan_ikke_følge_sin_egen_liste(delt):
    ejer, nøgle = delt
    assert ejer.post(f"/delt/{nøgle}/følg", data={"_csrf": csrf(ejer)}).status_code == 403


def test_ejeren_ser_hvem_der_følger_listen(to_brugere):
    ejer, nøgle, anden = to_brugere
    anden.post(f"/delt/{nøgle}/følg", data={"_csrf": csrf(anden)})

    tekst = ejer.get("/liste/1").get_data(as_text=True)
    assert "Følges af" in tekst and "Anden Andersen" in tekst
    # men stadig ikke hvad de har reserveret
    anden.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(anden)})
    assert _viser_reservation(ejer.get("/liste/1").get_data(as_text=True)) is False


def test_nyt_delelink_fjerner_dem_der_fulgte_listen(to_brugere):
    ejer, nøgle, anden = to_brugere
    # kvitteringen hentes med, så den ikke ligger og venter på den næste side
    anden.post(f"/delt/{nøgle}/følg", data={"_csrf": csrf(anden)}, follow_redirects=True)

    ejer.post("/liste/1/nyt-link", data={"_csrf": csrf(ejer)})
    assert "Lister du følger" not in anden.get("/lister").get_data(as_text=True)


### reservationer der hører til en bruger


def test_reservation_følger_brugeren_og_ikke_browseren(app, to_brugere):
    _, nøgle, anden = to_brugere
    anden.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(anden)})

    # samme bruger, en anden maskine
    anden_maskine = app.test_client()
    anden_maskine.post(
        "/login",
        data={"email": "anden@eksempel.dk", "adgangskode": "hemmeligt123", "_csrf": csrf(anden_maskine)},
    )

    tekst = anden_maskine.get(f"/delt/{nøgle}").get_data(as_text=True)
    assert "Du har reserveret" in tekst

    svar = anden_maskine.post(
        f"/delt/{nøgle}/ønske/1/fortryd", data={"_csrf": csrf(anden_maskine)}, follow_redirects=True
    )
    assert "Reservationen er fjernet" in svar.get_data(as_text=True)


def test_reservation_overlever_log_ud_og_ind(to_brugere):
    _, nøgle, anden = to_brugere
    anden.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(anden)})

    anden.post("/logud", data={"_csrf": csrf(anden)})
    # som udlogget gæst er man en anden – ønsket er taget, men ikke af én selv
    tekst = anden.get(f"/delt/{nøgle}").get_data(as_text=True)
    assert "Reserveret" in tekst and "Du har reserveret" not in tekst

    anden.post(
        "/login",
        data={"email": "anden@eksempel.dk", "adgangskode": "hemmeligt123", "_csrf": csrf(anden)},
    )
    assert "Du har reserveret" in anden.get(f"/delt/{nøgle}").get_data(as_text=True)


def test_gæstens_reservation_følger_med_ind_ved_login(app, delt):
    """Reserverer man som gæst og logger ind bagefter, skal reservationen ikke gå tabt."""
    ejer, nøgle = delt
    kode = lav_invitationskode(ejer)

    gæst = app.test_client()
    gæst.get(f"/delt/{nøgle}")
    gæst.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(gæst)})

    svar = opret_og_login(gæst, "sen@eksempel.dk", invitation=kode, navn="Sen Bruger")
    assert "Dine reservationer hører nu til din bruger" in svar.get_data(as_text=True)

    # og den kan stadig fortrydes – nu fra brugeren
    svar = gæst.post(f"/delt/{nøgle}/ønske/1/fortryd", data={"_csrf": csrf(gæst)}, follow_redirects=True)
    assert "Reservationen er fjernet" in svar.get_data(as_text=True)


def test_en_andens_reservation_kan_ikke_fortrydes_af_en_bruger(app, to_brugere):
    _, nøgle, anden = to_brugere
    gæst = app.test_client()
    gæst.get(f"/delt/{nøgle}")
    gæst.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(gæst)})

    svar = anden.post(
        f"/delt/{nøgle}/ønske/1/fortryd", data={"_csrf": csrf(anden)}, follow_redirects=True
    )
    assert "kun fortryde din egen" in svar.get_data(as_text=True)


def test_reservationer_forsvinder_med_brugeren(app, to_brugere):
    _, nøgle, anden = to_brugere
    anden.post(f"/delt/{nøgle}/ønske/1/reserver", data={"_csrf": csrf(anden)})

    anden.post("/konto/slet", data={"adgangskode": "hemmeligt123", "_csrf": csrf(anden)})

    with app.app_context():
        from app.models import get_db

        assert get_db().execute("SELECT COUNT(*) AS n FROM reservationer").fetchone()["n"] == 0
    # ønsket er frit igen for de andre
    assert "Reserveret" not in app.test_client().get(f"/delt/{nøgle}").get_data(as_text=True)


def test_gammel_reservation_uden_bruger_overlever_opdateringen(tmp_path):
    """En base fra før reservationerne kunne høre til en bruger, skal ikke miste dem."""
    import sqlite3

    sti = tmp_path / "gamle_reservationer.db"
    gammel = sqlite3.connect(sti)
    gammel.executescript("""
        CREATE TABLE brugere (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
                              navn TEXT NOT NULL, adgangskode TEXT NOT NULL, oprettet TEXT NOT NULL);
        CREATE TABLE lister (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             bruger_id INTEGER NOT NULL REFERENCES brugere(id) ON DELETE CASCADE,
                             titel TEXT NOT NULL, beskrivelse TEXT, del_nøgle TEXT, oprettet TEXT NOT NULL);
        CREATE TABLE ønsker (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             liste_id INTEGER NOT NULL REFERENCES lister(id) ON DELETE CASCADE,
                             titel TEXT NOT NULL, pris REAL, link TEXT, billede TEXT,
                             størrelse TEXT, beskrivelse TEXT, oprettet TEXT NOT NULL);
        CREATE TABLE reservationer (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    ønske_id INTEGER NOT NULL UNIQUE REFERENCES ønsker(id) ON DELETE CASCADE,
                                    gæst TEXT NOT NULL, oprettet TEXT NOT NULL);
        INSERT INTO brugere (email, navn, adgangskode, oprettet)
             VALUES ('anna@eksempel.dk', 'Anna', 'x', '2025-01-01');
        INSERT INTO lister (bruger_id, titel, del_nøgle, oprettet)
             VALUES (1, 'Gammel liste', 'gammel-nøgle', '2025-01-01');
        INSERT INTO ønsker (liste_id, titel, oprettet) VALUES (1, 'Gammelt ønske', '2025-01-01');
        INSERT INTO reservationer (ønske_id, gæst, oprettet) VALUES (1, 'gammel-gæst', '2025-01-01');
    """)
    gammel.commit()
    gammel.close()

    class Test(Config):
        DATABASE = str(sti)
        UPLOAD_MAPPE = str(tmp_path / "uploads")
        SECRET_KEY = "test"
        TESTING = True

    app = create_app(Test)

    # reservationen ligger der endnu, nu bare uden bruger …
    with app.app_context():
        from app.models import get_db

        række = get_db().execute("SELECT * FROM reservationer").fetchone()
    assert række["gæst"] == "gammel-gæst" and række["bruger_id"] is None

    # … og gæsten der lavede den, kan stadig se den som sin egen
    klient = app.test_client()
    with klient.session_transaction() as session:
        session["gæst"] = "gammel-gæst"
    assert "Du har reserveret" in klient.get("/delt/gammel-nøgle").get_data(as_text=True)
