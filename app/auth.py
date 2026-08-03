import re
import secrets
from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import hent_bruger, hent_bruger_på_email, opret_bruger

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
def opret():
    if hent_aktuel_bruger():
        return redirect(url_for("main.lister"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        navn = (request.form.get("navn") or "").strip()
        kode = request.form.get("adgangskode") or ""
        kode_igen = request.form.get("adgangskode_igen") or ""

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

        if fejl:
            flash(fejl, "fejl")
            return render_template("opret_bruger.html", email=email, navn=navn), 400

        bruger_id = opret_bruger(email, navn, generate_password_hash(kode))
        session.clear()
        session["bruger_id"] = bruger_id
        flash(f"Velkommen, {navn}!", "ok")
        return redirect(url_for("main.lister"))

    return render_template("opret_bruger.html")


@bp.route("/login", methods=["GET", "POST"])
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
