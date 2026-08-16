from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import limiter
from app.auth import hent_aktuel_bruger, login_påkrævet
from app.models import (
    bloker,
    er_blokeret,
    følg_person,
    følger_person,
    hent_blokerede,
    hent_bruger,
    hent_bruger_på_email,
    hent_fulgte_lister,
    hent_fulgte_personer,
    hent_følgere,
    hent_lister_til_følger,
    ophæv_blokering,
    stop_med_at_følge_person,
)

### venner: at følge en person giver alle personens lister på én gang

bp = Blueprint("venner", __name__)


@bp.route("/venner")
@login_påkrævet
def oversigt():
    bruger = hent_aktuel_bruger()
    return render_template(
        "venner.html",
        personer=hent_fulgte_personer(bruger["id"]),
        lister=hent_fulgte_lister(bruger["id"]),
        følgere=hent_følgere(bruger["id"]),
        blokerede=hent_blokerede(bruger["id"]),
    )


@bp.route("/venner/følg", methods=["POST"])
@login_påkrævet
@limiter.limit("10 per minute")  # så man ikke kan lede sig frem til hvem der har en bruger
def følg():
    bruger = hent_aktuel_bruger()
    email = (request.form.get("email") or "").strip().lower()
    person = hent_bruger_på_email(email) if email else None

    if person is not None and person["id"] == bruger["id"]:
        flash("Det er din egen e-mail – dine egne lister står under Mine ønskelister.", "fejl")
    # en blokering ser ud som om brugeren slet ikke findes, så den ikke kan mærkes
    elif person is None or er_blokeret(person["id"], bruger["id"]):
        flash("Der er ingen bruger med den e-mail.", "fejl")
    elif følg_person(bruger["id"], person["id"]):
        flash(f"Du følger nu {person['navn']} og kan se alle deres ønskelister.", "ok")
    else:
        flash(f"Du følger allerede {person['navn']}.", "ok")

    return redirect(url_for("venner.oversigt"))


@bp.route("/venner/<int:person_id>/følg-ikke", methods=["POST"])
@login_påkrævet
def følg_ikke(person_id):
    if stop_med_at_følge_person(hent_aktuel_bruger()["id"], person_id):
        flash("Du følger ikke længere den person.", "ok")
    return redirect(url_for("venner.oversigt"))


@bp.route("/venner/<int:person_id>/fjern", methods=["POST"])
@login_påkrævet
def fjern_følger(person_id):
    """Fjerner en der følger mig – og lukker døren, så de ikke bare følger igen."""
    bruger = hent_aktuel_bruger()
    person = hent_bruger(person_id)
    if person is None or person["id"] == bruger["id"]:
        abort(404)

    bloker(bruger["id"], person_id)
    flash(f"{person['navn']} følger dig ikke længere og kan ikke se dine lister.", "ok")
    return redirect(url_for("venner.oversigt"))


@bp.route("/venner/<int:person_id>/luk-ind", methods=["POST"])
@login_påkrævet
def luk_ind(person_id):
    if ophæv_blokering(hent_aktuel_bruger()["id"], person_id):
        flash("Personen kan følge dig igen, hvis de vil.", "ok")
    return redirect(url_for("venner.oversigt"))


@bp.route("/ven/<int:person_id>")
@login_påkrævet
def vis_person(person_id):
    """Alle personens lister – dem de ikke har skjult for dem, de følges af."""
    bruger = hent_aktuel_bruger()
    person = hent_bruger(person_id)

    # kun den der følger personen, kommer ind – og kun hvis døren ikke er lukket
    if person is None or not følger_person(bruger["id"], person_id):
        abort(404)
    if er_blokeret(person_id, bruger["id"]):
        abort(404)

    return render_template("ven.html", person=person, lister=hent_lister_til_følger(person_id))
