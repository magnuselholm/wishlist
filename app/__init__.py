from pathlib import Path

from flask import Flask, render_template

from app.models import init_db, luk_db
from config import Config

### samler appen


def create_app(config=Config):
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static"
    )
    app.config.from_object(config)

    Path(app.config["UPLOAD_MAPPE"]).mkdir(parents=True, exist_ok=True)

    app.teardown_appcontext(luk_db)
    with app.app_context():
        init_db()

    from app import auth, routes

    app.register_blueprint(auth.bp)
    app.register_blueprint(routes.bp)

    app.before_request(auth.tjek_csrf)
    app.jinja_env.filters["kroner"] = kroner

    @app.context_processor
    def skabelon_variabler():
        return {"bruger": auth.hent_aktuel_bruger(), "csrf_token": auth.csrf_token}

    @app.errorhandler(404)
    def ikke_fundet(e):
        return render_template("fejl.html", kode=404, besked="Siden findes ikke."), 404

    @app.errorhandler(413)
    def for_stor(e):
        return render_template("fejl.html", kode=413, besked="Filen er for stor (maks. 5 MB)."), 413

    return app


def kroner(beløb):
    """1299.5 -> "1.299,50 kr." — hele kroner vises uden decimaler."""
    if beløb is None:
        return ""
    beløb = float(beløb)
    if beløb == int(beløb):
        tal = f"{int(beløb):,}".replace(",", ".")
    else:
        tal = f"{beløb:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{tal} kr."
