import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse
from curl_cffi import requests as browser

import requests
from bs4 import BeautifulSoup

### henter titel, pris og billede fra et produktlink

TIMEOUT = 8
MAKS_BYTES = 2_000_000
MAKS_OMDIRIGERINGER = 4
TILLADTE_PORTE = {80, 443}
BRUGERAGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class SkrabFejl(Exception):
    """Vises direkte til brugeren, så teksten skal være til at forstå."""


def skrab(url):
    """Returnerer {titel, pris, valuta, billede, url} — felter der ikke findes er None."""
    html, endelig_url = _hent_html(url)
    suppe = BeautifulSoup(html, "html.parser")

    fra_json = _fra_json_ld(suppe)
    pris, valuta = _find_pris(suppe, fra_json)

    return {
        "titel": _find_titel(suppe, fra_json),
        "pris": pris,
        "valuta": valuta,
        "billede": _find_billede(suppe, fra_json, endelig_url),
        "url": endelig_url,
    }


### hentning


def _hent_html(url):
    url = _normaliser(url)
    # curl_cffi efterligner en rigtig browsers TLS-håndtryk. Almindelig requests
    # har et genkendeligt fingeraftryk som mange sider afviser med 403.
    session = browser.Session()

    for _ in range(MAKS_OMDIRIGERINGER):
        _tjek_adresse(url)
        try:
            svar = session.get(
                url,
                impersonate="chrome",
                headers={"Accept-Language": "da-DK,da;q=0.9,en;q=0.8"},
                timeout=TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
        except browser.RequestsError:
            raise SkrabFejl("Kunne ikke hente siden. Tjek at linket virker.")

        try:
            if svar.status_code in (301, 302, 303, 307, 308):
                mål = svar.headers.get("Location")
                if not mål:
                    raise SkrabFejl("Siden sendte os videre uden at sige hvorhen.")
                url = urljoin(url, mål)
                continue

            if svar.status_code in (403, 429):
                raise SkrabFejl("Siden blokerer for automatisk hentning. Udfyld felterne selv.")
            if svar.status_code >= 400:
                raise SkrabFejl(f"Siden svarede med fejl {svar.status_code}.")

            indholdstype = svar.headers.get("Content-Type", "")
            if "html" not in indholdstype.lower():
                raise SkrabFejl("Linket peger ikke på en almindelig webside.")

            # loftet holdes, så et ondsindet link ikke kan fylde hukommelsen
            stykker, hentet = [], 0
            for stykke in svar.iter_content(chunk_size=65536):
                stykker.append(stykke)
                hentet += len(stykke)
                if hentet >= MAKS_BYTES:
                    break
            indhold = b"".join(stykker)[:MAKS_BYTES]
        finally:
            svar.close()

        return indhold.decode(svar.encoding or _tegnsæt(indhold), errors="replace"), url

    raise SkrabFejl("Siden sendte os videre for mange gange.")


def _tegnsæt(indhold):
    """Siger headeren ikke noget, leder vi efter <meta charset="..."> i selve siden."""
    fund = re.search(rb'charset=["\']?\s*([\w-]+)', indhold[:4096], re.IGNORECASE)
    if fund:
        try:
            navn = fund.group(1).decode("ascii")
            "".encode(navn)  # kaster hvis Python ikke kender tegnsættet
            return navn
        except (UnicodeDecodeError, LookupError):
            pass
    return "utf-8"


def _normaliser(url):
    url = (url or "").strip()
    if not url:
        raise SkrabFejl("Indsæt et link først.")
    if "://" not in url:
        url = "https://" + url
    return url


def _tjek_adresse(url):
    """Blokerer alt der ikke er en almindelig offentlig http(s)-adresse.

    Uden det her kunne et link få serveren til at hente interne adresser
    (fx http://169.254.169.254/ eller localhost) på brugerens vegne.
    """
    dele = urlparse(url)
    if dele.scheme not in ("http", "https"):
        raise SkrabFejl("Kun http- og https-links kan hentes.")
    if not dele.hostname:
        raise SkrabFejl("Linket mangler et domænenavn.")

    port = dele.port or (443 if dele.scheme == "https" else 80)
    if port not in TILLADTE_PORTE:
        raise SkrabFejl("Kun almindelige webporte (80 og 443) kan hentes.")

    try:
        oplysninger = socket.getaddrinfo(dele.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise SkrabFejl("Domænet findes ikke.")

    for _, _, _, _, adresse in oplysninger:
        ip = ipaddress.ip_address(adresse[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise SkrabFejl("Det link peger på en intern adresse og kan ikke hentes.")


### udtræk af felter


def _fra_json_ld(suppe):
    """Mange webshops lægger produktdata i <script type="application/ld+json">."""
    for mærke in suppe.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(mærke.string or "")
        except (ValueError, TypeError):
            continue
        for post in _udpak(data):
            if "product" in str(post.get("@type", "")).lower():
                return post
    return {}


def _udpak(data):
    """JSON-LD kan være et objekt, en liste eller pakket ind i @graph."""
    if isinstance(data, list):
        for element in data:
            yield from _udpak(element)
    elif isinstance(data, dict):
        yield data
        for element in data.get("@graph", []) or []:
            yield from _udpak(element)


def _meta(suppe, *navne):
    for navn in navne:
        for attribut in ("property", "name", "itemprop"):
            mærke = suppe.find("meta", attrs={attribut: navn})
            if mærke and mærke.get("content", "").strip():
                return mærke["content"].strip()
    return None


def _find_titel(suppe, fra_json):
    navn = fra_json.get("name")
    if isinstance(navn, str) and navn.strip():
        return navn.strip()

    tekst = _meta(suppe, "og:title", "twitter:title")
    if not tekst and suppe.title and suppe.title.string:
        tekst = suppe.title.string
    if not tekst and suppe.h1:
        tekst = suppe.h1.get_text()

    if not tekst:
        return None
    tekst = re.sub(r"\s+", " ", tekst).strip()
    return tekst[:200] or None


def _find_pris(suppe, fra_json):
    tilbud = fra_json.get("offers")
    if isinstance(tilbud, list):
        tilbud = tilbud[0] if tilbud else None
    if isinstance(tilbud, dict):
        pris = tilbud.get("price") or tilbud.get("lowPrice")
        if pris is None and isinstance(tilbud.get("priceSpecification"), dict):
            pris = tilbud["priceSpecification"].get("price")
        tal = læs_pris(pris)
        if tal is not None:
            return tal, (tilbud.get("priceCurrency") or "").upper() or None

    tekst = _meta(
        suppe,
        "product:price:amount",
        "og:price:amount",
        "twitter:data1",
        "price",
    )
    tal = læs_pris(tekst)
    if tal is not None:
        valuta = _meta(suppe, "product:price:currency", "og:price:currency", "priceCurrency")
        return tal, (valuta or "").upper() or None

    return None, None


def _find_billede(suppe, fra_json, grund_url):
    kandidat = fra_json.get("image")
    if isinstance(kandidat, list):
        kandidat = kandidat[0] if kandidat else None
    if isinstance(kandidat, dict):
        kandidat = kandidat.get("url")
    if not isinstance(kandidat, str) or not kandidat.strip():
        kandidat = _meta(suppe, "og:image:secure_url", "og:image", "twitter:image")
    if not kandidat:
        mærke = suppe.find("link", rel="image_src")
        kandidat = mærke.get("href") if mærke else None

    if not kandidat:
        return None

    fuld = urljoin(grund_url, kandidat.strip())
    return fuld if urlparse(fuld).scheme in ("http", "https") else None


def læs_pris(værdi):
    """Læser priser som "1.299,00 kr.", "1,299.00" og "DKK 249"."""
    if isinstance(værdi, (int, float)):
        return round(float(værdi), 2)
    if not isinstance(værdi, str):
        return None

    fund = re.search(r"\d[\d.,\s ]*", værdi)
    if not fund:
        return None

    tekst = re.sub(r"[\s ]", "", fund.group())
    komma, punktum = tekst.rfind(","), tekst.rfind(".")

    if komma > -1 and punktum > -1:
        # den sidste separator er decimaltegnet
        if komma > punktum:
            tekst = tekst.replace(".", "").replace(",", ".")
        else:
            tekst = tekst.replace(",", "")
    elif komma > -1 or punktum > -1:
        separator = "," if komma > -1 else "."
        efter = tekst.rsplit(separator, 1)[1]
        if len(efter) == 3 and tekst.count(separator) >= 1 and len(tekst.split(separator)[0]) <= 3:
            # fx "1.299" eller "1,299" — tusindtalsseparator
            tekst = tekst.replace(separator, "")
        else:
            tekst = tekst.replace(separator, ".")

    try:
        return round(float(tekst), 2)
    except ValueError:
        return None
