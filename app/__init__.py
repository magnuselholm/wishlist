from werkzeug.middleware.proxy_fix import ProxyFix

from datetime import date
from pathlib import Path

from flask import Flask, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app.models import init_db, luk_db
from config import Config


### samler appen
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")

def create_app(config=Config):
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static"
    )
    app.config.from_object(config)

    if app.config["DRIFT"] and app.config["SECRET_KEY"] == "TEST":
        raise RuntimeError(
            "SECRET_KEY er stadig standardværdien. Sæt en rigtig nøgle" \
            "i .env (openssl rand -hex 32 eller lignende) og genstart serveren."
        )


    if app.config["DRIFT"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    Path(app.config["UPLOAD_MAPPE"]).mkdir(parents=True, exist_ok=True)

    limiter.init_app(app)

    app.teardown_appcontext(luk_db)
    with app.app_context():
        init_db()

    from app import auth, deling, invitationer, routes

    app.register_blueprint(auth.bp)
    app.register_blueprint(routes.bp)
    app.register_blueprint(deling.bp)
    app.register_blueprint(invitationer.bp)

    app.before_request(auth.tjek_csrf)
    app.jinja_env.filters["kroner"] = kroner
    app.jinja_env.filters["dato"] = dato

    @app.context_processor
    def skabelon_variabler():
        return {"bruger": auth.hent_aktuel_bruger(), "csrf_token": auth.csrf_token}

    @app.errorhandler(403)
    def forbudt(e):
        return render_template("fejl.html", kode=403, besked=e.description), 403

    @app.errorhandler(404)
    def ikke_fundet(e):
        return render_template("fejl.html", kode=404, besked="Siden findes ikke."), 404

    @app.errorhandler(413)
    def for_stor(e):
        return render_template("fejl.html", kode=413, besked="Filen er for stor (maks. 5 MB)."), 413

    @app.errorhandler(429)
    def for_mange(e):
        return render_template("fejl.html", kode=429, besked="For mange anmodninger. Prøv igen senere."), 429
    
    return app


MÅNEDER = ["januar", "februar", "marts", "april", "maj", "juni",
           "juli", "august", "september", "oktober", "november", "december"]


def dato(iso):
    """"2026-08-09T10:12:13+00:00" -> "9. august 2026"."""
    if not iso:
        return ""
    try:
        dag = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return f"{dag.day}. {MÅNEDER[dag.month - 1]} {dag.year}"


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
