import secrets

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    session,
    url_for,
)

from app.auth import hent_aktuel_bruger
from app.models import (
    fortryd_reservation,
    hent_liste_på_nøgle,
    hent_ønske_i_liste,
    hent_ønsker,
    hent_ønsker_til_gæst,
    reserver_ønske,
)

### gæstevisningen: alle med linket kan se listen og reservere ønsker

bp = Blueprint("deling", __name__)


def gæst_id():
    """Et tilfældigt id pr. browser, så en gæst kan fortryde sin egen reservation."""
    if "gæst" not in session:
        session["gæst"] = secrets.token_urlsafe(16)
        # reservationen skal overleve at browseren lukkes
        session.permanent = True
    return session["gæst"]


@bp.route("/delt/<noegle>")
def vis_delt_liste(noegle):
    liste = _delt_liste(noegle)

    if _er_ejer(liste):
        # ejeren ser sin egen liste som gæsterne ser den – men uden reservationerne
        ønsker = hent_ønsker(liste["id"])
    else:
        ønsker = hent_ønsker_til_gæst(liste["id"], gæst_id())

    samlet = sum(ønske["pris"] for ønske in ønsker if ønske["pris"])
    return render_template(
        "delt.html",
        liste=liste,
        ønsker=ønsker,
        samlet=samlet,
        noegle=noegle,
        ejer=_er_ejer(liste),
    )


@bp.route("/delt/<noegle>/ønske/<int:onske_id>/reserver", methods=["POST"])
def reserver(noegle, onske_id):
    _gæstens_ønske(noegle, onske_id)

    if reserver_ønske(onske_id, gæst_id()):
        flash("Ønsket er reserveret. Det kan ejeren ikke se.", "ok")
    else:
        flash("En anden nåede desværre at reservere det ønske.", "fejl")
    return redirect(url_for("deling.vis_delt_liste", noegle=noegle))


@bp.route("/delt/<noegle>/ønske/<int:onske_id>/fortryd", methods=["POST"])
def fortryd(noegle, onske_id):
    _gæstens_ønske(noegle, onske_id)

    if fortryd_reservation(onske_id, gæst_id()):
        flash("Reservationen er fjernet.", "ok")
    else:
        flash("Du kan kun fortryde din egen reservation.", "fejl")
    return redirect(url_for("deling.vis_delt_liste", noegle=noegle))


### hjælpefunktioner


def _delt_liste(noegle):
    liste = hent_liste_på_nøgle(noegle)
    if liste is None:
        abort(404)
    return liste


def _er_ejer(liste):
    bruger = hent_aktuel_bruger()
    return bruger is not None and bruger["id"] == liste["bruger_id"]


def _gæstens_ønske(noegle, onske_id):
    """Et ønske må kun reserveres af en gæst, og kun via listens eget link."""
    liste = _delt_liste(noegle)
    if _er_ejer(liste):
        abort(403, "Du kan ikke reservere ønsker på din egen liste.")

    ønske = hent_ønske_i_liste(onske_id, liste["id"])
    if ønske is None:
        abort(404)
    return ønske
