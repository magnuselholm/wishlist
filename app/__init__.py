from flask import Flask
from config import Config
from app.models import init_db

def create_app():
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static"
    )
    app.config.from_object(Config)

    init_db()

    from app.routes import bp
    app.register_blueprint(bp)

    return app