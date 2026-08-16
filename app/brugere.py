from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.auth import hent_aktuel_bruger, login_påkrævet, sikker_næste
from app.models import (
    følg_person,
    følger_person,
    hent_bruger,
    hent_synlige_lister,
    stop_med_at_følge_person,
)

### de andre på siden: alle kan se hinandens ønskelister, og man kan følge dem
### man vil have øverst i oversigten

bp = Blueprint("brugere", __name__)


@bp.route("/bruger/<int:bruger_id>")
@login_påkrævet
def vis(bruger_id):
    person = hent_bruger(bruger_id)
    if person is None or person["id"] == hent_aktuel_bruger()["id"]:
        # sine egne lister ser man under Mine ønskelister, med det hele
        abort(404)

    return render_template(
        "bruger.html",
        person=person,
        lister=hent_synlige_lister(bruger_id),
        følger=følger_person(hent_aktuel_bruger()["id"], bruger_id),
    )


@bp.route("/bruger/<int:bruger_id>/følg", methods=["POST"])
@login_påkrævet
def følg(bruger_id):
    person = _en_anden(bruger_id)
    if følg_person(hent_aktuel_bruger()["id"], bruger_id):
        flash(f"{person['navn']} står nu øverst i oversigten.", "ok")
    return _tilbage(bruger_id)


@bp.route("/bruger/<int:bruger_id>/følg-ikke", methods=["POST"])
@login_påkrævet
def følg_ikke(bruger_id):
    person = _en_anden(bruger_id)
    if stop_med_at_følge_person(hent_aktuel_bruger()["id"], bruger_id):
        flash(f"{person['navn']} står ikke længere øverst.", "ok")
    return _tilbage(bruger_id)


def _en_anden(bruger_id):
    person = hent_bruger(bruger_id)
    if person is None or person["id"] == hent_aktuel_bruger()["id"]:
        abort(404)
    return person


def _tilbage(bruger_id):
    """Tilbage til den side knappen blev trykket på – oversigten eller personens side."""
    return redirect(
        sikker_næste(request.form.get("næste")) or url_for("brugere.vis", bruger_id=bruger_id)
    )
