from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.auth import admin_påkrævet, hent_aktuel_bruger, normaliser_invitationskode
from app.models import (
    hent_invitation_på_kode,
    hent_invitationer,
    ny_invitationskode,
    opret_invitation,
    sæt_invitation_spærret,
)

### invitationskoder: kun den der styrer dem, kan se og lave dem

bp = Blueprint("invitationer", __name__)

DATO_LÆNGDE = len("2026-12-24")


@bp.route("/invitationer")
@admin_påkrævet
def oversigt():
    return render_template("invitationer.html", invitationer=hent_invitationer(), i_dag=date.today().isoformat())


@bp.route("/invitationer/opret", methods=["POST"])
@admin_påkrævet
def opret():
    kode = normaliser_invitationskode(request.form.get("kode")) or ny_invitationskode()
    note = (request.form.get("note") or "").strip()[:120]
    udløber = (request.form.get("udløber") or "").strip()[:DATO_LÆNGDE]

    fejl = None
    if len(kode) < 4:
        fejl = "Koden skal være mindst 4 tegn."
    elif hent_invitation_på_kode(kode):
        fejl = f"Koden “{kode}” findes allerede."

    maks_brug = None
    maks_tekst = (request.form.get("maks_brug") or "").strip()
    if not fejl and maks_tekst:
        if not maks_tekst.isdigit() or int(maks_tekst) < 1:
            fejl = "Antal brug skal være et helt tal på mindst 1 – eller stå tomt."
        else:
            maks_brug = int(maks_tekst)

    if not fejl and udløber:
        try:
            date.fromisoformat(udløber)
        except ValueError:
            fejl = "Udløbsdatoen skal skrives som 2026-12-24."

    if fejl:
        flash(fejl, "fejl")
        return redirect(url_for("invitationer.oversigt"))

    opret_invitation(kode, note or None, maks_brug, udløber or None, hent_aktuel_bruger()["id"])
    flash(f"Koden “{kode}” er klar. Send linket til den du vil invitere.", "ok")
    return redirect(url_for("invitationer.oversigt"))


@bp.route("/invitationer/<int:invitation_id>/spær", methods=["POST"])
@admin_påkrævet
def spær(invitation_id):
    return _skift_spærring(invitation_id, spærret=True)


@bp.route("/invitationer/<int:invitation_id>/åbn", methods=["POST"])
@admin_påkrævet
def åbn(invitation_id):
    return _skift_spærring(invitation_id, spærret=False)


def _skift_spærring(invitation_id, spærret):
    if not any(invitation["id"] == invitation_id for invitation in hent_invitationer()):
        abort(404)

    sæt_invitation_spærret(invitation_id, spærret)
    flash("Koden er lukket." if spærret else "Koden virker igen.", "ok")
    return redirect(url_for("invitationer.oversigt"))
