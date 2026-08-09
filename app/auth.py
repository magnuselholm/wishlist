import re
import secrets
from datetime import date
from functools import wraps

from app import limiter

from flask import (
    Blueprint,
    abort,
    app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from app.billeder import slet_upload
from app.models import (
    antal_brugere,
    brug_invitation,
    frigiv_invitation,
    hent_bruger,
    hent_bruger_på_email,
    hent_invitation_på_kode,
    hent_lister,
    hent_ønsker,
    opdater_adgangskode,
    opdater_bruger,
    opret_bruger,
    slet_bruger,
)

### login, oprettelse af bruger og beskyttelse af requests

bp = Blueprint("auth", __name__)

EMAIL_MØNSTER = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_KODE_LÆNGDE = 8


def hent_aktuel_bruger():
    """Lægger den indloggede bruger på g, så templates og views kan bruge den."""
    if "bruger" not in g:
        bruger_id = session.get("bruger_id")
        g.bruger = hent_bruger(bruger_id) if bruger_id else None
        if bruger_id and g.bruger is None:
            # brugeren er slettet siden login
            session.clear()
    return g.bruger


def login_påkrævet(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if hent_aktuel_bruger() is None:
            return redirect(url_for("auth.login", næste=request.full_path))
        return view(*args, **kwargs)

    return wrapper


def admin_påkrævet(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        bruger = hent_aktuel_bruger()
        if bruger is None:
            return redirect(url_for("auth.login", næste=request.full_path))
        if not bruger["admin"]:
            abort(403, "Kun den der styrer invitationerne har adgang hertil.")
        return view(*args, **kwargs)

    return wrapper


### CSRF


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def tjek_csrf():
    """Kaldes før hver request der ændrer noget."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    indsendt = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
    gemt = session.get("_csrf", "")
    # to tomme strenge er ens, så et manglende token i sessionen skal fanges her
    if not gemt or not secrets.compare_digest(indsendt, gemt):
        abort(400, "Ugyldig eller udløbet formular. Prøv igen.")


### views


@bp.route("/opret-bruger", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def opret():
    if hent_aktuel_bruger():
        return redirect(url_for("main.lister"))

    # en helt tom base skal kunne få sin første bruger – ellers var der ingen til at
    # lave invitationer, og siden kunne aldrig komme i gang
    første_bruger = antal_brugere() == 0

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        navn = (request.form.get("navn") or "").strip()
        kode = request.form.get("adgangskode") or ""
        kode_igen = request.form.get("adgangskode_igen") or ""
        invitationskode = normaliser_invitationskode(request.form.get("invitation"))
        invitation = None

        fejl = None
        if not navn:
            fejl = "Skriv dit navn."
        elif not EMAIL_MØNSTER.match(email):
            fejl = "Skriv en gyldig e-mail."
        elif len(kode) < MIN_KODE_LÆNGDE:
            fejl = f"Adgangskoden skal være mindst {MIN_KODE_LÆNGDE} tegn."
        elif kode != kode_igen:
            fejl = "De to adgangskoder er ikke ens."
        elif hent_bruger_på_email(email):
            fejl = "Der findes allerede en bruger med den e-mail."
        elif not første_bruger:
            invitation = hent_invitation_på_kode(invitationskode) if invitationskode else None
            fejl = _invitation_fejl(invitationskode, invitation)

        # koden holdes fri først, så to der opretter sig samtidig ikke deler den sidste plads
        if not fejl and invitation is not None and not brug_invitation(invitation["id"]):
            fejl = "Invitationskoden blev brugt op lige nu. Spørg om en ny."

        if fejl:
            flash(fejl, "fejl")
            return render_template(
                "opret_bruger.html",
                email=email,
                navn=navn,
                invitation=invitationskode,
                første_bruger=første_bruger,
            ), 400

        try:
            bruger_id = opret_bruger(
                email,
                navn,
                generate_password_hash(kode),
                invitation_id=invitation["id"] if invitation else None,
                admin=første_bruger,
            )
        except Exception:
            if invitation is not None:
                frigiv_invitation(invitation["id"])
            raise

        session.clear()
        session["bruger_id"] = bruger_id
        flash(f"Velkommen, {navn}!", "ok")
        return redirect(url_for("main.lister"))

    return render_template(
        "opret_bruger.html",
        invitation=normaliser_invitationskode(request.args.get("kode")),
        første_bruger=første_bruger,
    )


def normaliser_invitationskode(tekst):
    """“ jul7k4m ” bliver til “JUL7-K4M” – koder læses op i telefonen og skrives forkert."""
    kode = "".join((tekst or "").split()).upper()
    if len(kode) == 8 and kode.isalnum():
        kode = f"{kode[:4]}-{kode[4:]}"
    return kode[:40]


def _invitation_fejl(kode, invitation):
    """Fortæller hvorfor en kode ikke kan bruges. None betyder at den er god."""
    if not kode:
        return "Du skal bruge en invitationskode for at oprette dig."
    if invitation is None:
        return "Den invitationskode kender vi ikke."
    if invitation["spærret"]:
        return "Den invitationskode er lukket."
    if invitation["udløber"] and invitation["udløber"] < date.today().isoformat():
        return "Den invitationskode er udløbet."
    if invitation["maks_brug"] is not None and invitation["brugt"] >= invitation["maks_brug"]:
        return "Den invitationskode er brugt op."
    return None


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])  # begrænser brute-force loginforsøg
def login():
    if hent_aktuel_bruger():
        return redirect(url_for("main.lister"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        kode = request.form.get("adgangskode") or ""
        bruger = hent_bruger_på_email(email)

        if bruger is None or not check_password_hash(bruger["adgangskode"], kode):
            flash("Forkert e-mail eller adgangskode.", "fejl")
            return render_template("login.html", email=email), 401

        session.clear()
        session["bruger_id"] = bruger["id"]
        return redirect(sikker_næste(request.form.get("næste")) or url_for("main.lister"))

    return render_template("login.html", næste=request.args.get("næste", ""))


### kontoen


@bp.route("/konto")
@login_påkrævet
def konto():
    return render_template("konto.html", konto=hent_aktuel_bruger())


@bp.route("/konto/oplysninger", methods=["POST"])
@login_påkrævet
def ret_oplysninger():
    bruger = hent_aktuel_bruger()
    navn = (request.form.get("navn") or "").strip()[:80]
    email = (request.form.get("email") or "").strip().lower()

    fejl = None
    if not navn:
        fejl = "Skriv dit navn."
    elif not EMAIL_MØNSTER.match(email):
        fejl = "Skriv en gyldig e-mail."
    else:
        anden = hent_bruger_på_email(email)
        if anden and anden["id"] != bruger["id"]:
            fejl = "Der findes allerede en bruger med den e-mail."

    if fejl:
        flash(fejl, "fejl")
        return render_template("konto.html", konto=bruger, navn=navn, email=email), 400

    opdater_bruger(bruger["id"], navn, email)
    flash("Oplysningerne er gemt.", "ok")
    return redirect(url_for("auth.konto"))


@bp.route("/konto/adgangskode", methods=["POST"])
@login_påkrævet
def ret_adgangskode():
    bruger = hent_aktuel_bruger()
    nuværende = request.form.get("nuværende") or ""
    ny = request.form.get("ny") or ""
    ny_igen = request.form.get("ny_igen") or ""

    fejl = None
    if not check_password_hash(bruger["adgangskode"], nuværende):
        fejl = "Den nuværende adgangskode passer ikke."
    elif len(ny) < MIN_KODE_LÆNGDE:
        fejl = f"Den nye adgangskode skal være mindst {MIN_KODE_LÆNGDE} tegn."
    elif ny != ny_igen:
        fejl = "De to nye adgangskoder er ikke ens."
    elif ny == nuværende:
        fejl = "Den nye adgangskode er den samme som den gamle."

    if fejl:
        flash(fejl, "fejl")
        return render_template("konto.html", konto=bruger), 400

    opdater_adgangskode(bruger["id"], generate_password_hash(ny))
    flash("Adgangskoden er skiftet.", "ok")
    return redirect(url_for("auth.konto"))


@bp.route("/konto/slet", methods=["POST"])
@login_påkrævet
def slet_konto():
    bruger = hent_aktuel_bruger()

    if not check_password_hash(bruger["adgangskode"], request.form.get("adgangskode") or ""):
        flash("Skriv din adgangskode for at slette kontoen.", "fejl")
        return render_template("konto.html", konto=bruger), 400

    # billederne ligger uden for basen, så de skal fjernes før rækkerne forsvinder
    for liste in hent_lister(bruger["id"]):
        for ønske in hent_ønsker(liste["id"]):
            slet_upload(ønske["billede"])

    slet_bruger(bruger["id"])
    session.clear()
    flash("Din konto og alle dine ønskelister er slettet.", "ok")
    return redirect(url_for("main.index"))


@bp.route("/logud", methods=["POST"])
def logud():
    session.clear()
    flash("Du er logget ud.", "ok")
    return redirect(url_for("auth.login"))

def sikker_næste(sti):
    """Kun relative stier accepteres, så login ikke kan sende folk videre til et fremmed domæne."""
    if not sti or not sti.startswith("/") or sti.startswith("//"):
        return None
    return sti
