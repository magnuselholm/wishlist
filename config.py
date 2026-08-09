import os
from pathlib import Path

### indstillinger

BASE_DIR = Path(__file__).resolve().parent


class Config:
    DRIFT = os.environ.get("DRIFT") == "1"

    SECRET_KEY = os.environ.get("SECRET_KEY", "TEST")
    DATABASE = os.environ.get("DATABASE", str(BASE_DIR / "ønsker.db"))

    # uploadede billeder lægges her og serveres via /static/uploads/
    UPLOAD_MAPPE = os.environ.get("UPLOAD_MAPPE", str(BASE_DIR / "static" / "uploads"))
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB pr. upload

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = DRIFT  # kun HTTPS
