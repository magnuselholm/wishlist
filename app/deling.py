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
    følg_liste,
    følger_liste,
    hent_liste_på_nøgle,
    hent_ønske_i_liste,
    hent_ønsker,
    hent_ønsker_til_gæst,
    reserver_ønske,
    stop_med_at_følge_liste,
)

### gæstevisningen: alle med linket kan se listen og reservere ønsker

bp = Blueprint("deling", __name__)


def gæst_id():
    """Et tilfældigt id pr. browser, så en gæst uden bruger kan fortryde sin egen
    reservation. Er man logget ind, hænger reservationen i stedet på brugeren."""
    if "gæst" not in session:
        session["gæst"] = secrets.token_urlsafe(16)
        # reservationen skal overleve at browseren lukkes
        session.permanent = True
    return session["gæst"]


def hvem_reserverer():
    """(bruger_id, gæst) – kun det ene af dem er sat."""
    bruger = hent_aktuel_bruger()
    if bruger is not None:
        return bruger["id"], None
    return None, gæst_id()


@bp.route("/delt/<noegle>")
def vis_delt_liste(noegle):
    liste = _delt_liste(noegle)
    bruger = hent_aktuel_bruger()

    if _er_ejer(liste):
        # ejeren ser sin egen liste som gæsterne ser den – men uden reservationerne
        ønsker = hent_ønsker(liste["id"])
    else:
        bruger_id, gæst = hvem_reserverer()
        ønsker = hent_ønsker_til_gæst(liste["id"], bruger_id, gæst)

    samlet = sum(ønske["pris"] for ønske in ønsker if ønske["pris"])
    return render_template(
        "delt.html",
        liste=liste,
        ønsker=ønsker,
        samlet=samlet,
        noegle=noegle,
        ejer=_er_ejer(liste),
        følger=bruger is not None and følger_liste(bruger["id"], liste["id"]),
    )


@bp.route("/delt/<noegle>/ønske/<int:onske_id>/reserver", methods=["POST"])
def reserver(noegle, onske_id):
    _gæstens_ønske(noegle, onske_id)

    bruger_id, gæst = hvem_reserverer()
    if reserver_ønske(onske_id, bruger_id, gæst):
        flash("Ønsket er reserveret. Det kan ejeren ikke se.", "ok")
    else:
        flash("En anden nåede desværre at reservere det ønske.", "fejl")
    return redirect(url_for("deling.vis_delt_liste", noegle=noegle))


@bp.route("/delt/<noegle>/ønske/<int:onske_id>/fortryd", methods=["POST"])
def fortryd(noegle, onske_id):
    _gæstens_ønske(noegle, onske_id)

    bruger_id, gæst = hvem_reserverer()
    if fortryd_reservation(onske_id, bruger_id, gæst):
        flash("Reservationen er fjernet.", "ok")
    else:
        flash("Du kan kun fortryde din egen reservation.", "fejl")
    return redirect(url_for("deling.vis_delt_liste", noegle=noegle))


### at følge listen: så skal linket ikke findes frem igen næste gang


@bp.route("/delt/<noegle>/følg", methods=["POST"])
def følg(noegle):
    liste = _delt_liste(noegle)
    if _er_ejer(liste):
        abort(403, "Din egen liste ligger allerede under “Mine ønskelister”.")

    bruger = hent_aktuel_bruger()
    if bruger is None:
        return _log_ind_først(noegle)

    if følg_liste(bruger["id"], liste["id"]):
        flash(f"Du følger nu “{liste['titel']}”. Den står ved siden af dine egne lister.", "ok")
    return redirect(url_for("deling.vis_delt_liste", noegle=noegle))


@bp.route("/delt/<noegle>/følg-ikke", methods=["POST"])
def følg_ikke(noegle):
    liste = _delt_liste(noegle)

    bruger = hent_aktuel_bruger()
    if bruger is None:
        return _log_ind_først(noegle)

    if stop_med_at_følge_liste(bruger["id"], liste["id"]):
        flash(f"Du følger ikke længere “{liste['titel']}”.", "ok")
    return redirect(url_for("deling.vis_delt_liste", noegle=noegle))


def _log_ind_først(noegle):
    """Sender til login og tilbage til listen bagefter – ikke til den POST der ikke kan gentages."""
    flash("Log ind for at følge listen.", "fejl")
    return redirect(
        url_for("auth.login", næste=url_for("deling.vis_delt_liste", noegle=noegle))
    )


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
