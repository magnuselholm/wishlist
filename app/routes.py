from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.auth import hent_aktuel_bruger, login_påkrævet
from app.billeder import BilledFejl, gem_upload, gyldig_billed_url, slet_upload
from app.models import (
    forny_del_nøgle,
    hent_liste,
    hent_lister,
    hent_ønske,
    hent_ønsker,
    opdater_liste,
    opdater_ønske,
    opret_liste,
    slet_liste,
    slet_ønske,
    tilføj_ønske,
)
from app.skrab import SkrabFejl, læs_pris, skrab

### HTTP endpoints

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if hent_aktuel_bruger():
        return redirect(url_for("main.lister"))
    return render_template("forside.html")


### ønskelister


@bp.route("/lister")
@login_påkrævet
def lister():
    return render_template("lister.html", lister=hent_lister(hent_aktuel_bruger()["id"]))


@bp.route("/lister/opret", methods=["POST"])
@login_påkrævet
def opret_ny_liste():
    titel = (request.form.get("titel") or "").strip()
    beskrivelse = (request.form.get("beskrivelse") or "").strip()
    if not titel:
        flash("Ønskelisten skal have en titel.", "fejl")
        return redirect(url_for("main.lister"))

    liste_id = opret_liste(hent_aktuel_bruger()["id"], titel[:120], beskrivelse[:500])
    return redirect(url_for("main.vis_liste", liste_id=liste_id))


@bp.route("/liste/<int:liste_id>")
@login_påkrævet
def vis_liste(liste_id):
    liste = _min_liste(liste_id)
    ønsker = hent_ønsker(liste_id)
    samlet = sum(ø["pris"] for ø in ønsker if ø["pris"])
    return render_template("liste.html", liste=liste, ønsker=ønsker, samlet=samlet)


@bp.route("/liste/<int:liste_id>/rediger", methods=["POST"])
@login_påkrævet
def rediger_liste(liste_id):
    _min_liste(liste_id)
    titel = (request.form.get("titel") or "").strip()
    beskrivelse = (request.form.get("beskrivelse") or "").strip()
    if not titel:
        flash("Ønskelisten skal have en titel.", "fejl")
    else:
        opdater_liste(liste_id, hent_aktuel_bruger()["id"], titel[:120], beskrivelse[:500])
        flash("Ønskelisten er opdateret.", "ok")
    return redirect(url_for("main.vis_liste", liste_id=liste_id))


@bp.route("/liste/<int:liste_id>/nyt-link", methods=["POST"])
@login_påkrævet
def nyt_delelink(liste_id):
    _min_liste(liste_id)
    forny_del_nøgle(liste_id, hent_aktuel_bruger()["id"])
    flash("Listen har fået et nyt link. Det gamle virker ikke længere.", "ok")
    return redirect(url_for("main.vis_liste", liste_id=liste_id))


@bp.route("/liste/<int:liste_id>/slet", methods=["POST"])
@login_påkrævet
def fjern_liste(liste_id):
    liste = _min_liste(liste_id)
    for ønske in hent_ønsker(liste_id):
        slet_upload(ønske["billede"])
    slet_liste(liste_id, hent_aktuel_bruger()["id"])
    flash(f"“{liste['titel']}” er slettet.", "ok")
    return redirect(url_for("main.lister"))


### ønsker


@bp.route("/liste/<int:liste_id>/nyt-ønske", methods=["GET", "POST"])
@login_påkrævet
def nyt_ønske(liste_id):
    liste = _min_liste(liste_id)

    if request.method == "POST":
        felter, fejl = _læs_ønske_formular()
        if fejl:
            flash(fejl, "fejl")
            return render_template("ønske_form.html", liste=liste, ønske=felter, onske_id=None), 400

        tilføj_ønske(
            liste_id,
            felter["titel"],
            felter["pris"],
            felter["link"],
            felter["billede"],
            felter["størrelse"],
            felter["beskrivelse"],
        )
        flash("Ønsket er tilføjet.", "ok")
        return redirect(url_for("main.vis_liste", liste_id=liste_id))

    return render_template("ønske_form.html", liste=liste, ønske=None, onske_id=None)


@bp.route("/ønske/<int:onske_id>/rediger", methods=["GET", "POST"])
@login_påkrævet
def rediger_ønske(onske_id):
    ønske = hent_ønske(onske_id, hent_aktuel_bruger()["id"])
    if ønske is None:
        abort(404)
    liste = _min_liste(ønske["liste_id"])

    if request.method == "POST":
        felter, fejl = _læs_ønske_formular(nuværende_billede=ønske["billede"])
        if fejl:
            flash(fejl, "fejl")
            return render_template("ønske_form.html", liste=liste, ønske=felter, onske_id=onske_id), 400

        if ønske["billede"] != felter["billede"]:
            slet_upload(ønske["billede"])

        opdater_ønske(
            onske_id,
            felter["titel"],
            felter["pris"],
            felter["link"],
            felter["billede"],
            felter["størrelse"],
            felter["beskrivelse"],
        )
        flash("Ønsket er opdateret.", "ok")
        return redirect(url_for("main.vis_liste", liste_id=ønske["liste_id"]))

    return render_template("ønske_form.html", liste=liste, ønske=ønske, onske_id=onske_id)


@bp.route("/ønske/<int:onske_id>/slet", methods=["POST"])
@login_påkrævet
def fjern_ønske(onske_id):
    ønske = hent_ønske(onske_id, hent_aktuel_bruger()["id"])
    if ønske is None:
        abort(404)
    slet_upload(ønske["billede"])
    slet_ønske(onske_id)
    flash("Ønsket er slettet.", "ok")
    return redirect(url_for("main.vis_liste", liste_id=ønske["liste_id"]))


### automatisk udfyldning fra et link


@bp.route("/api/skrab", methods=["POST"])
@login_påkrævet
def api_skrab():
    data = request.get_json(silent=True) or {}
    try:
        resultat = skrab(data.get("url", ""))
    except SkrabFejl as fejl:
        return jsonify({"fejl": str(fejl)}), 400
    except Exception:
        return jsonify({"fejl": "Kunne ikke læse siden. Udfyld felterne selv."}), 502
    return jsonify(resultat)


### hjælpefunktioner


def _min_liste(liste_id):
    liste = hent_liste(liste_id, hent_aktuel_bruger()["id"])
    if liste is None:
        abort(404)
    return liste


def _læs_ønske_formular(nuværende_billede=None):
    """Returnerer (felter, fejltekst). Felterne sendes tilbage til formularen ved fejl."""
    felter = {
        "titel": (request.form.get("titel") or "").strip()[:200],
        "link": (request.form.get("link") or "").strip()[:2000],
        "størrelse": (request.form.get("størrelse") or "").strip()[:60],
        "beskrivelse": (request.form.get("beskrivelse") or "").strip()[:1000],
        "billede": nuværende_billede,
        "pris": None,
    }

    if not felter["titel"]:
        return felter, "Ønsket skal have et navn."

    pris_tekst = (request.form.get("pris") or "").strip()
    if pris_tekst:
        felter["pris"] = læs_pris(pris_tekst)
        if felter["pris"] is None or felter["pris"] < 0:
            return felter, "Prisen skal være et tal, fx 249 eller 1.299,95."

    if felter["link"] and not gyldig_billed_url(felter["link"]):
        return felter, "Linket skal starte med http:// eller https://."

    if request.form.get("fjern_billede"):
        felter["billede"] = None

    billed_url = (request.form.get("billede_url") or "").strip()[:2000]
    fil = request.files.get("billede_fil")

    if fil and fil.filename:
        try:
            felter["billede"] = gem_upload(fil)
        except BilledFejl as fejl:
            return felter, str(fejl)
    elif billed_url:
        if not gyldig_billed_url(billed_url):
            return felter, "Billedadressen skal starte med http:// eller https://."
        felter["billede"] = billed_url

    return felter, None
