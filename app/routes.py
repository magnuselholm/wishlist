from flask import Blueprint, redirect, request, render_template
from app.models import hent_ønsker, tilføj_ønske, slet_ønske

### HTTP endpoints

bp = Blueprint("main", __name__)

@bp.route("/")
def index():
    ønsker = hent_ønsker()
    return render_template("index.html", ønsker=ønsker)

@bp.route("/tilføj", methods=["POST"])
def tilføj():
    ønske = request.form.get("ønske")
    pris = request.form.get("pris")
    link = request.form.get("link")
    billede = request.form.get("billede")
    if ønske:
        tilføj_ønske(ønske, pris, link, billede)
    return redirect("/")

@bp.route("/slet/<int:id>", methods=["POST"])
def slet(id):
    slet_ønske(id)
    return redirect("/")