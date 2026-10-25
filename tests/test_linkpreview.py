"""Extractor tests on minimal HTML that mirrors each portal's real structure."""
import json

from app.linkpreview import extract, normalize_url, site_of


def ld(obj):
    return f'<script type="application/ld+json">{json.dumps(obj)}</script>'


def test_site_detection_and_url_normalization():
    assert site_of("https://casa.mercadolibre.com.ar/MLA-1-x_JM") == "MercadoLibre"
    assert site_of("https://inmoclick.com/1-a/inmuebles/2/ficha/x") == "Inmoclick"
    assert site_of("https://www.remax.com.ar/listings/x") == "Remax"
    assert site_of("https://example.com/x") == ""
    assert normalize_url("https://inmoup.com.ar/a/ficha/b?btid=1#top") == "https://inmoup.com.ar/a/ficha/b"
    assert normalize_url("https://casa.mercadolibre.com.ar/MLA-1-x_JM#polycard=1") == "https://casa.mercadolibre.com.ar/MLA-1-x_JM"
    assert normalize_url("https://example.com/p?id=7#x") == "https://example.com/p?id=7"  # unknown site keeps its query


def test_inmoup_json_ld():
    html = "<html><head>" + ld({"@context": "https://schema.org", "@graph": [{
        "@type": ["Accommodation", "RealEstateListing"],
        "name": "Casa en Venta en Godoy Cruz, Mendoza - USD 90.000 | Inmoup",
        "image": ["https://img/1.jpg", "https://img/2.jpg"],
        "address": {"@type": "PostalAddress", "streetAddress": "Dr. Perinetti 116", "addressLocality": "Godoy Cruz",
                    "addressRegion": "Mendoza"},
        "geo": {"latitude": -32.93, "longitude": -68.84},
        "additionalProperty": [{"name": "Dormitorios", "value": "3"}, {"name": "Superficie Cubierta m2", "value": "160"},
                               {"name": "Antigüedad", "value": "40  Años"}],
        "offers": {"@type": "Offer", "price": 90000, "priceCurrency": "USD"}}]}) + "</head></html>"
    d = extract(html, "https://inmoup.com.ar/x/inmuebles/5/ficha/casa")
    assert d["price"] == 90000 and d["currency"] == "USD"
    assert d["address"] == "Dr. Perinetti 116, Godoy Cruz, Mendoza"
    assert d["image_url"] == "https://img/1.jpg" and d["lat"] == -32.93
    assert d["facts"] == "Dormitorios: 3 · Superficie Cubierta: 160 m² · Antigüedad: 40 Años"
    assert d["title"] == "Casa en Venta en Godoy Cruz, Mendoza - USD 90.000"
    assert d["site"] == "Inmoup"


def test_mercadolibre_json_ld_plus_state():
    html = ('<meta property="og:title" content="Venta De Casa - US$ 67.000"/>'
            + ld({"@type": "Product", "name": "Venta De Casa", "image": "https://http2.mlstatic.com/a.webp",
                  "offers": {"price": 67000, "priceCurrency": "USD", "@type": "Offer"}})
            + '<script>{"item_address":"Alpatacal  Al 1000","item_location":"Guaymallén, Mendoza"},'
              '"map_info":{"location":{"latitude":"-32.89","longitude":"-68.78"}}</script>')
    d = extract(html, "https://casa.mercadolibre.com.ar/MLA-4073716076-venta-_JM")
    assert d["price"] == 67000 and d["currency"] == "USD"
    assert d["address"] == "Alpatacal Al 1000, Guaymallén, Mendoza"
    assert d["image_url"].endswith("a.webp") and d["lng"] == -68.78


def test_remax_ng_state():
    state = {"k": {"b": {"data": {"title": "Venta Casa Moderna", "displayAddress": "Calle 451 400", "price": 73500,
                                  "priceExposure": True, "currency": {"id": 1, "value": "USD"}, "bedrooms": 3,
                                  "dimensionCovered": 85, "yearBuilt": 2018,
                                  "photos": [{"value": "listings/x/b.jpg", "position": 1},
                                             {"value": "listings/x/a.jpg", "position": 0}],
                                  "location": {"type": "Point", "coordinates": [-57.58, -38.1]},
                                  "geo": {"label": "Mar del Plata, General Pueyrredon, Buenos Aires"}}}}}
    html = (f'<meta property="og:image" content="https://cdn/og.jpg">'
            f'<script id="ng-state" type="application/json">{json.dumps(state)}</script>')
    d = extract(html, "https://www.remax.com.ar/listings/venta-casa")
    assert d["price"] == 73500 and d["currency"] == "USD"
    assert d["address"] == "Calle 451 400, Mar del Plata, General Pueyrredon, Buenos Aires"
    assert d["image_url"] == "https://d1acdg20u0pmxj.cloudfront.net/listings/x/a.jpg"
    assert (d["lat"], d["lng"]) == (-38.1, -57.58)
    assert d["facts"] == "Dormitorios: 3 · Superficie Cubierta: 85 m² · Año: 2018"


def test_remax_hidden_price_is_not_read():
    state = {"displayAddress": "X 1", "price": 1, "priceExposure": False, "currency": {"value": "USD"}, "photos": []}
    html = f'<script id="ng-state" type="application/json">{json.dumps(state)}</script>'
    assert "price" not in extract(html, "https://www.remax.com.ar/listings/x")


def test_inmoclick_page_blocks():
    html = ('<meta property="og:image" content="https://fotosinmoclick.s3.amazonaws.com/440/925/1024x576" />'
            '<meta property="og:title" content="Fernando Puebla Inmobiliaria - ID#925 - Casa en Venta" />'
            # a "similar listings" card first: must not be taken as this listing's price
            '<div class="item venta" precio="U$S 65.000"><p class="price">U$S 65.000</p></div>'
            '<div class="price" style="padding: 20px 15px"> <span>Venta</span><br> US$ 58.000 </div>'
            '<ul><li> <div>Dormitorios</div> <div>3</div> </li><li> <div>Superficie Cubierta m2</div> <div>163</div> </li>'
            '<li> <div>Antigüedad</div> <div>41  Años</div> </li></ul>'
            '<h3>Ubicación</h3> <p>Granaderos 2020, Ciudad,Mendoza</p>')
    d = extract(html, "https://inmoclick.com/440-x/inmuebles/925/ficha/casa-en-venta")
    assert d["price"] == 58000 and d["currency"] == "USD"
    assert d["address"] == "Granaderos 2020, Ciudad, Mendoza"
    assert d["title"] == "Casa en Venta en Granaderos 2020"
    assert d["facts"] == "Dormitorios: 3 · Superficie Cubierta: 163 m² · Antigüedad: 41 Años"
    assert d["image_url"].startswith("https://fotosinmoclick")


def test_generic_site_falls_back_to_open_graph_and_title_price():
    html = ('<title>x</title><meta property="og:title" content="Casa linda - $ 150.000.000">'
            '<meta property="og:image" content="/img.jpg">')
    d = extract(html, "https://otra.example/casa/1")
    assert d["image_url"] == "https://otra.example/img.jpg"
    assert d["price"] == 150000000 and d["currency"] == "ARS"
    assert d["site"] == ""


# --- fetch: retries and error reasons ------------------------------------------

import socket  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

from app import linkpreview  # noqa: E402


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(linkpreview.time, "sleep", lambda s: None)


def public_dns(monkeypatch):
    monkeypatch.setattr(linkpreview.socket, "getaddrinfo", lambda h, p: [(0, 0, 0, "", ("8.8.8.8", 0))])


def test_dns_failure_is_retried_then_reported(monkeypatch, no_sleep):
    calls = []

    def broken(host, port):
        calls.append(host)
        raise socket.gaierror("Temporary failure in name resolution")

    monkeypatch.setattr(linkpreview.socket, "getaddrinfo", broken)
    d = linkpreview.fetch("https://www.remax.com.ar/listings/x")
    assert d["error"] == "dns" and d["site"] == "Remax"
    assert len(calls) == 3  # first try + 2 retries


def test_transient_error_recovers_on_retry(monkeypatch, no_sleep):
    public_dns(monkeypatch)
    answers = iter([httpx.ConnectTimeout("slow"),
                    httpx.Response(200, headers={"content-type": "text/html"},
                                   text='<meta property="og:title" content="Casa - USD 50.000">')])

    def get(self, url):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        a.request = httpx.Request("GET", url)
        return a

    monkeypatch.setattr(httpx.Client, "get", get)
    d = linkpreview.fetch("https://inmoup.com.ar/a/ficha/b")
    assert "error" not in d and d["price"] == 50000


def test_http_404_is_not_retried(monkeypatch, no_sleep):
    public_dns(monkeypatch)
    calls = []

    def get(self, url):
        calls.append(url)
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", get)
    d = linkpreview.fetch("https://inmoup.com.ar/gone")
    assert d["error"] == "http" and d["detail"] == "404" and len(calls) == 1


def test_private_address_blocked(monkeypatch):
    monkeypatch.setattr(linkpreview.socket, "getaddrinfo", lambda h, p: [(0, 0, 0, "", ("192.168.1.10", 0))])
    assert linkpreview.fetch("http://router.lan/")["error"] == "blocked"


def test_title_from_url():
    t = linkpreview.title_from_url
    assert t("https://casa.mercadolibre.com.ar/MLA-4017162980-venta-de-casa-guaymallen-mendoza-_JM") == \
        "Venta de casa guaymallen mendoza"
    assert t("https://inmoclick.com/1-x/inmuebles/2/ficha/casa-en-venta-en-paso-de-guana-0") == \
        "Casa en venta en paso de guana 0"
    assert t("https://example.com/") == ""
