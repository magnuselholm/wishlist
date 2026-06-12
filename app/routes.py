from flask import Blueprint, redirect, request, render_template
from models import hent_ønsker, tilføj_ønske, slet_ønske

bp = Blueprint("main", __name__)

@bp.route("/")
def index():
    ønsker = hent_ønsker()
    return render_template("index.html", ønsker=ønsker)

@bp.route("/tilføj", methods=["POST"])
def tilføj():
    ønske = request.form.get("ønske")
    if ønske:
        tilføj_ønske(ønske)
    return redirect("/")

@bp.route("/slet/<int:id>", methods=["POST"])
def slet(id):
    slet_ønske(id)
    return redirect("/")