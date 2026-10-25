import re

from app.linkpreview import _MetaParser


def add_house(client, **data):
    data.setdefault("title", "Casa test")
    r = client.post("/houses", data=data, follow_redirects=False)
    assert r.status_code == 303
    return int(r.headers["location"].rsplit("/", 1)[1])


def test_index_is_spanish_by_default(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'lang="es"' in r.text
    assert "Todavía no hay casas" in r.text


def test_english_toggle(client):
    r = client.get("/lang/en?next=/")
    assert r.status_code == 200  # followed the redirect
    assert "No houses yet" in r.text
    assert 'lang="en"' in r.text


def test_lang_redirect_rejects_external_urls(client):
    r = client.get("/lang/en?next=//evil.example", follow_redirects=False)
    assert r.headers["location"] == "/"


def test_raters_seeded_from_env(client):
    r = client.get("/settings")
    assert 'value="Ana"' in r.text and 'value="Beto"' in r.text


def test_rating_and_ranking_order(client):
    a = add_house(client, title="Casa A", price="150.000")
    b = add_house(client, title="Casa B")
    # Ana=1, Beto=2. B gets better marks than A.
    client.post(f"/houses/{a}/scores", data={"r1_ubicacion": "4", "r2_ubicacion": "6", "status": "activa"})
    r = client.post(
        f"/houses/{b}/scores",
        data={"r1_ubicacion": "9", "r1_construccion": "7", "supermercado": "1", "plaza": "0", "status": "favorita"},
        headers={"Accept": "application/json"},
    )
    s = r.json()
    assert s["topics"]["ubicacion"] == 9
    assert s["overall"] == 8  # unrated topics are ignored, not counted as zero
    assert s["amenities_yes"] == 1

    page = client.get("/").text
    assert page.index("Casa B") < page.index("Casa A")
    assert "USD 150.000" in page


def test_zero_is_a_score_and_empty_clears(client):
    h = add_house(client)
    s = client.post(f"/houses/{h}/scores", data={"r1_ubicacion": "0"}, headers={"Accept": "application/json"}).json()
    assert s["overall"] == 0
    s = client.post(f"/houses/{h}/scores", data={"r1_ubicacion": ""}, headers={"Accept": "application/json"}).json()
    assert s["overall"] is None


def test_out_of_range_scores_ignored(client):
    h = add_house(client)
    s = client.post(f"/houses/{h}/scores", data={"r1_ubicacion": "11"}, headers={"Accept": "application/json"}).json()
    assert s["overall"] is None


def test_weights_change_overall(client):
    h = add_house(client)
    client.post(f"/houses/{h}/scores", data={"r1_ubicacion": "10", "r1_construccion": "0"})
    client.post("/settings/weights", data={"ubicacion": "3", "construccion": "1", "antiguedad": "1"})
    s = client.post(
        f"/houses/{h}/scores", data={"r1_ubicacion": "10", "r1_construccion": "0"}, headers={"Accept": "application/json"}
    ).json()
    assert s["overall"] == 7.5


def test_discarded_hidden_by_default(client):
    h = add_house(client, title="Descartable")
    client.post(f"/houses/{h}/scores", data={"status": "descartada"})
    assert "Descartable" not in client.get("/").text
    assert "Descartable" in client.get("/?all=1").text


def test_edit_and_delete(client):
    h = add_house(client)
    client.post(f"/houses/{h}", data={"title": "Renombrada", "currency": "ARS", "price": "1000"})
    assert "Renombrada" in client.get(f"/houses/{h}").text
    client.post(f"/houses/{h}/delete")
    assert client.get(f"/houses/{h}").status_code == 404


def test_remove_rater_deletes_ratings(client):
    h = add_house(client)
    client.post(f"/houses/{h}/scores", data={"r2_ubicacion": "5"})
    client.post("/settings/raters", data={"name_1": "Ana", "name_2": "Beto", "remove_2": "on"})
    s = client.post(f"/houses/{h}/scores", data={}, headers={"Accept": "application/json"}).json()
    assert s["overall"] is None


def test_exports(client):
    h = add_house(client, title="Exportada")
    client.post(f"/houses/{h}/scores", data={"r1_ubicacion": "8", "colegio": "1"})
    data = client.get("/export.json").json()
    assert data[0]["title"] == "Exportada" and data[0]["Ana_ubicacion"] == 8 and data[0]["colegio"] is True
    csv = client.get("/export.csv").text
    assert "Exportada" in csv and "Ana_ubicacion" in csv


def test_password_protection(make_client):
    c = make_client(APP_PASSWORD="secreto")
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/healthz").status_code == 200
    assert "Contraseña incorrecta" in c.post("/login", data={"password": "mal"}).text
    assert "Todavía no hay casas" in c.post("/login", data={"password": "secreto"}).text


def test_meta_parser():
    p = _MetaParser()
    p.feed('<html><head><title> Fallback </title><meta property="og:title" content="Casa linda">'
           '<meta property="og:image" content="/img.jpg"></head></html>')
    assert p.meta["og:title"] == "Casa linda" and p.meta["og:image"] == "/img.jpg" and p.title == "Fallback"


def test_static_assets_are_versioned(client):
    html = client.get("/").text
    assert re.search(r'/static/style\.css\?v=[\d.]+', html)
