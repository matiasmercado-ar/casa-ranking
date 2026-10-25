"""Reads photo, price, address and title from a listing URL.

Supported sites, best source first:
- Inmoup: JSON-LD RealEstateListing with offers, address, geo.
- MercadoLibre: JSON-LD Product (price, photo) + address from the embedded page state.
- Remax: Angular state (`ng-state`) with the full listing.
- Inmoclick: no structured data; the page's own price box, "Ubicación" block and
  "Datos de la propiedad" list (its URLs look like Inmoup's but it's another platform).
- Anything else: JSON-LD if present, then Open Graph tags, then a price in the title.

Portals change their markup, so every step is best effort and failures are
silent: whatever is not found can be typed by hand.
"""
import ipaddress
import json
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9", "Accept": "text/html,application/xhtml+xml"}
MAX_BYTES = 3_000_000

SITES = {
    "inmoup.com.ar": "Inmoup",
    "inmoclick.com": "Inmoclick",
    "inmoclick.com.ar": "Inmoclick",
    "mercadolibre.com.ar": "MercadoLibre",
    "remax.com.ar": "Remax",
}
REMAX_PHOTO = "https://d1acdg20u0pmxj.cloudfront.net/{path}"


def site_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for domain, name in SITES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return ""


def normalize_url(url: str) -> str:
    """Drop the #fragment always, and the tracking ?query on known sites (their URLs don't need it)."""
    url = url.strip()
    p = urlparse(url)
    if not p.scheme:
        return url
    query = "" if site_of(url) else p.query
    return urlunparse((p.scheme, p.netloc, p.path, p.params, query, ""))


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:title", "og:image", "twitter:title", "twitter:image") and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()


def _is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


# --- helpers ---------------------------------------------------------------


def _json_ld(html: str) -> list[dict]:
    nodes = []
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict):
                nodes.extend(item.get("@graph", [item]))
    return [n for n in nodes if isinstance(n, dict)]


def _types(node: dict) -> set[str]:
    t = node.get("@type", [])
    return set(t if isinstance(t, list) else [t])


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _currency(value) -> str:
    v = str(value or "").upper().replace("U$S", "USD").replace("US$", "USD")
    if v in ("USD", "DOLARES", "DÓLARES"):
        return "USD"
    if v in ("ARS", "$", "PESOS"):
        return "ARS"
    return ""


def _number(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    digits = re.sub(r"[^\d]", "", str(value or ""))
    return float(digits) if digits and int(digits) > 0 else None


def _price_from_text(text: str) -> tuple[float | None, str]:
    """'... - USD 90.000 | Inmoup', 'US$ 67.000', '$ 120.000.000'."""
    m = re.search(r"(USD|U\$S|US\$|\$)\s?([\d.]{4,})", text or "")
    if not m:
        return None, ""
    return _number(m.group(2)), "ARS" if m.group(1) == "$" else "USD"


def _join(*parts) -> str:
    seen = []
    for p in parts:
        p = re.sub(r"\s+", " ", str(p or "")).strip(" ,")
        if p and p.lower() not in (s.lower() for s in seen):
            seen.append(p)
    return ", ".join(seen)


def _fmt_area(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


# --- site extractors -------------------------------------------------------


def _from_json_ld(html: str, out: dict) -> None:
    for node in _json_ld(html):
        types = _types(node)
        if not types & {"RealEstateListing", "Product", "Offer", "Accommodation", "House", "Residence",
                        "SingleFamilyResidence", "Apartment"}:
            continue
        offer = _first(node.get("offers")) or {}
        if isinstance(offer, dict):
            out.setdefault("price", _number(offer.get("price")))
            out.setdefault("currency", _currency(offer.get("priceCurrency")))
        image = _first(node.get("image"))
        if isinstance(image, dict):
            image = image.get("url")
        if image:
            out.setdefault("image_url", str(image))
        addr = node.get("address")
        if isinstance(addr, dict):
            out.setdefault("address", _join(addr.get("streetAddress"), addr.get("addressLocality"),
                                            addr.get("addressRegion")))
        geo = node.get("geo")
        if isinstance(geo, dict) and geo.get("latitude") and geo.get("longitude"):
            out.setdefault("lat", float(geo["latitude"]))
            out.setdefault("lng", float(geo["longitude"]))
        props = node.get("additionalProperty")
        if isinstance(props, list):
            wanted = ("Dormitorios", "Baños", "Superficie Cubierta m2", "Superficie Total m2", "Antigüedad")
            facts = {p.get("name"): p.get("value") for p in props if isinstance(p, dict)}
            parts = [f"{k.replace(' m2', '')}: {facts[k]}{' m²' if 'm2' in k else ''}"
                     for k in wanted if facts.get(k) not in (None, "", "0")]
            if parts:
                out.setdefault("facts", " · ".join(parts))
        if node.get("name"):
            out.setdefault("title", str(node["name"]))


def _mercadolibre(html: str, out: dict) -> None:
    m = re.search(r'"item_address":"([^"]*)","item_location":"([^"]*)"', html)
    if m:
        out["address"] = _join(json.loads(f'"{m.group(1)}"'), json.loads(f'"{m.group(2)}"'))
    m = re.search(r'"location":\{"latitude":"(-?[\d.]+)","longitude":"(-?[\d.]+)"\}', html)
    if m:
        out["lat"], out["lng"] = float(m.group(1)), float(m.group(2))


def _remax(html: str, out: dict) -> None:
    m = re.search(r'<script id="ng-state" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        return
    try:
        state = json.loads(m.group(1))
    except ValueError:
        return

    def find(o):
        if isinstance(o, dict):
            if "displayAddress" in o and "price" in o and "photos" in o:
                return o
            o = list(o.values())
        if isinstance(o, list):
            for v in o:
                if (hit := find(v)) is not None:
                    return hit
        return None

    listing = find(state)
    if not listing:
        return
    if listing.get("priceExposure", True):
        out["price"] = _number(listing.get("price"))
        out["currency"] = _currency((listing.get("currency") or {}).get("value"))
    geo = listing.get("geo") or {}
    out["address"] = _join(listing.get("displayAddress"), geo.get("label"))
    photos = sorted((p for p in listing.get("photos") or [] if p.get("value")), key=lambda p: p.get("position") or 0)
    if photos:
        out["image_url"] = REMAX_PHOTO.format(path=photos[0]["value"])
    coords = (listing.get("location") or {}).get("coordinates")
    if isinstance(coords, list) and len(coords) == 2:
        out["lng"], out["lat"] = float(coords[0]), float(coords[1])
    if listing.get("title"):
        out["title"] = listing["title"]
    parts = []
    for key, label in (("bedrooms", "Dormitorios"), ("bathrooms", "Baños")):
        if listing.get(key):
            parts.append(f"{label}: {listing[key]}")
    for key, label in (("dimensionCovered", "Superficie Cubierta"), ("dimensionLand", "Terreno")):
        if listing.get(key):
            parts.append(f"{label}: {_fmt_area(listing[key])} m²")
    if listing.get("yearBuilt"):
        parts.append(f"Año: {listing['yearBuilt']}")
    if parts:
        out["facts"] = " · ".join(parts)


def _inmoclick(html: str, out: dict) -> None:
    m = re.search(r'<div class="price"[^>]*>\s*<span>[^<]*</span>\s*<br>\s*(US\$|U\$S|USD|\$)\s*([\d.]+)', html)
    if m:
        out["price"] = _number(m.group(2))
        out["currency"] = "ARS" if m.group(1) == "$" else "USD"
    m = re.search(r'<h3>\s*Ubicaci[oó]n\s*</h3>\s*<p>([^<]+)</p>', html)
    if m:
        out["address"] = _join(*unescape(m.group(1)).split(","))
    facts = {}
    for label, value in re.findall(r'<li>\s*<div>([^<]{2,40})</div>\s*<div>([^<]{1,40})</div>\s*</li>', html):
        facts.setdefault(label.strip(), re.sub(r"\s+", " ", value).strip())
    parts = []
    for key, label, unit in (("Dormitorios", "Dormitorios", ""), ("Baños", "Baños", ""),
                             ("Superficie Cubierta m2", "Superficie Cubierta", " m²"),
                             ("Superficie Total m2", "Superficie Total", " m²"), ("Antigüedad", "Antigüedad", "")):
        if facts.get(key) not in (None, "", "0"):
            parts.append(f"{label}: {facts[key]}{unit}")
    if parts:
        out["facts"] = " · ".join(parts)
    # og:title is "<Agency> - ID#925 - Casa en Venta"; "Casa en Venta en <street>" reads better.
    m = re.search(r'<meta property="og:title" content="[^"]*- ([^"-]+)"', html)
    if m and out.get("address"):
        out["title"] = f"{m.group(1).strip()} en {out['address'].split(',')[0]}"


# --- entry point -----------------------------------------------------------


def extract(html: str, url: str) -> dict:
    """Pure function: page HTML -> fields. Keys only present when found."""
    out: dict = {}
    site = site_of(url)
    if site == "Remax":
        _remax(html, out)
    if site == "MercadoLibre":
        _mercadolibre(html, out)
    if site == "Inmoclick":
        _inmoclick(html, out)
    _from_json_ld(html, out)
    p = _MetaParser()
    p.feed(html[:MAX_BYTES])
    title = p.meta.get("og:title") or p.meta.get("twitter:title") or p.title
    out.setdefault("title", title)
    image = p.meta.get("og:image") or p.meta.get("twitter:image")
    if image:
        out.setdefault("image_url", urljoin(url, image))
    if not out.get("price"):
        price, currency = _price_from_text(title)
        if price:
            out["price"], out["currency"] = price, currency
    out = {k: v for k, v in out.items() if v not in (None, "")}
    if "title" in out:
        title = re.sub(r"\s+", " ", unescape(out["title"])).strip()
        out["title"] = re.sub(r"\s*\|\s*(Inmoup|Inmoclick|REMAX|Mercado Libre)\s*$", "", title, flags=re.I)[:200]
    if "facts" in out:
        out["facts"] = re.sub(r"\s+", " ", out["facts"])
    if out.get("price") and not out.get("currency"):
        out["currency"] = "USD"
    out["site"] = site
    return out


def fetch(url: str, timeout: float = 10.0) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not _is_public(parsed.hostname):
        return {}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=HEADERS) as c:
            r = c.get(url)
            if r.status_code >= 400 or "html" not in r.headers.get("content-type", ""):
                return {}
            return extract(r.text[:MAX_BYTES], str(r.url))
    except (httpx.HTTPError, ValueError):
        return {}
