import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

from flask import current_app

### billeder kan enten være en adresse ude i verden eller en fil brugeren uploader

UPLOAD_PRÆFIKS = "/static/uploads/"

# endelse -> de første bytes filen skal starte med
SIGNATURER = {
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF87a", b"GIF89a"],
    ".webp": [b"RIFF"],
}


class BilledFejl(Exception):
    """Vises direkte til brugeren."""


def gem_upload(fil):
    """Gemmer en uploadet fil og returnerer adressen den kan vises på."""
    endelse = Path(fil.filename or "").suffix.lower()
    if endelse not in SIGNATURER:
        raise BilledFejl("Billedet skal være en PNG, JPG, GIF eller WEBP.")

    start = fil.stream.read(12)
    fil.stream.seek(0)
    if not any(start.startswith(s) for s in SIGNATURER[endelse]):
        raise BilledFejl("Filen ligner ikke et billede.")
    if endelse == ".webp" and start[8:12] != b"WEBP":
        raise BilledFejl("Filen ligner ikke et billede.")

    mappe = Path(current_app.config["UPLOAD_MAPPE"])
    mappe.mkdir(parents=True, exist_ok=True)

    navn = secrets.token_hex(16) + endelse
    fil.save(mappe / navn)
    return UPLOAD_PRÆFIKS + navn


def gyldig_billed_url(url):
    return urlparse(url).scheme in ("http", "https")


def slet_upload(sti):
    """Rydder op i uploads-mappen når et billede bliver skiftet ud eller slettet."""
    if not sti or not sti.startswith(UPLOAD_PRÆFIKS):
        return
    navn = os.path.basename(sti)
    fil = Path(current_app.config["UPLOAD_MAPPE"]) / navn
    try:
        fil.unlink(missing_ok=True)
    except OSError:
        pass
