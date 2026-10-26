import re
import sqlite3

from fastapi.testclient import TestClient

from app import db
from conftest import ADMIN_PW, load_app, login

JSON = {"Accept": "application/json"}


def add_house(client, **data):
    data.setdefault("title", "Casa test")
    r = client.post("/houses", data=data, follow_redirects=False)
    assert r.status_code == 303
    return int(r.headers["location"].rsplit("/", 1)[1])


# --- auth --------------------------------------------------------------------


def test_login_required(main):
    c = TestClient(main.app)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/healthz").status_code == 200
    assert "Iniciá sesión" in c.get("/login").text


def test_bad_login(main, monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    r = TestClient(main.app).post("/login", data={"email": "admin", "password": "nope"})
    assert r.status_code == 401 and "incorrectos" in r.text


def test_generated_admin_password(env, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD")
    assert len(db.init()) >= 12  # first start creates admin and returns the password
    assert db.init() is None  # only once


def test_logout(admin):
    admin.post("/logout")
    assert admin.get("/", follow_redirects=False).status_code == 303


def test_change_password(admin, main):
    r = admin.post("/account/password", data={"current": "wrong", "new": "whatever-1"})
    assert "err=bad_current" in str(r.url)
    r = admin.post("/account/password", data={"current": ADMIN_PW, "new": "short"})
    assert "err=short_password" in str(r.url)
    admin.post("/account/password", data={"current": ADMIN_PW, "new": "new-admin-pass"})
    login(TestClient(main.app), "admin", "new-admin-pass")


# --- admin ---------------------------------------------------------------------


def test_only_admin_manages_users(users):
    ana, _ = users
    assert ana.post("/admin/users", data={"name": "X", "email": "x@x.com", "password": "12345678"}).status_code == 403
    assert ana.post("/settings/weights", data={"ubicacion": "5"}).status_code == 403
    page = ana.get("/settings").text
    assert 'id="users"' not in page and "Mi cuenta" in page


def test_admin_user_management(admin, users):
    page = admin.get("/settings").text
    assert "ana@x.com" in page and "beto@x.com" in page
    r = admin.post("/admin/users", data={"name": "Otra", "email": "ANA@x.com", "password": "12345678"})
    assert "err=email_taken" in str(r.url)
    r = admin.post("/admin/users/1/delete")
    assert "err=cannot_delete_self" in str(r.url)
    # Admin can't demote themselves.
    admin.post("/admin/users/1", data={"name": "Admin", "email": "admin", "is_admin": ""})
    assert 'id="users"' in admin.get("/settings").text


def test_deleted_user_is_logged_out_and_ratings_removed(admin, users):
    ana, beto = users
    h = add_house(ana)
    beto.post(f"/houses/{h}/scores", data={"r3_ubicacion": "5"})
    admin.post("/admin/users/3/delete")
    assert beto.get("/", follow_redirects=False).status_code == 303
    assert ana.post(f"/houses/{h}/scores", data={}, headers=JSON).json()["overall"] is None


# --- ratings -------------------------------------------------------------------


def test_cannot_change_other_users_ratings(users):
    ana, beto = users
    h = add_house(ana)
    ana.post(f"/houses/{h}/scores", data={"r2_ubicacion": "8"})
    # Beto tries to overwrite Ana's score and to clear it; only his own row counts.
    s = beto.post(f"/houses/{h}/scores", data={"r2_ubicacion": "1", "r3_ubicacion": "4"}, headers=JSON).json()
    assert s["topics"]["ubicacion"] == 6  # (8 + 4) / 2
    s = beto.post(f"/houses/{h}/scores", data={"r3_ubicacion": "4"}, headers=JSON).json()
    assert s["topics"]["ubicacion"] == 6  # Ana's 8 was not cleared by Beto's form


def test_detail_shows_own_stars_editable_others_read_only(users):
    ana, beto = users
    h = add_house(ana)
    page = beto.get(f"/houses/{h}").text
    assert 'name="r3_ubicacion"' in page and 'name="r2_ubicacion"' not in page
    assert "Solo Ana puede cambiar" in page


def test_admin_without_rating_cannot_rate(admin, users):
    h = add_house(admin)
    s = admin.post(f"/houses/{h}/scores", data={"r1_ubicacion": "9", "supermercado": "1"}, headers=JSON).json()
    assert s["overall"] is None and s["amenities_yes"] == 1


def test_rating_and_ranking_order(users):
    ana, beto = users
    a = add_house(ana, title="Casa A", price="150.000")
    b = add_house(ana, title="Casa B")
    ana.post(f"/houses/{a}/scores", data={"r2_ubicacion": "4", "status": "activa"})
    s = ana.post(f"/houses/{b}/scores", data={"r2_ubicacion": "9", "r2_vecindario": "7", "supermercado": "1",
                                               "plaza": "0", "status": "favorita"}, headers=JSON).json()
    # Unrated topics count as a neutral 5: (9*2 + 7 + 5 + 5) / 5 = 7 stars.
    assert s["base"] == 7
    # 1 Yes, 1 No, 9 unknown = 5.5 of 11 -> 5.0; 85% stars + 15% questions.
    assert s["questions"] == 5 and round(s["overall"], 2) == 6.7
    assert s["amenities_yes"] == 1
    page = ana.get("/").text
    assert page.index("Casa B") < page.index("Casa A")
    assert "USD 150.000" in page
    assert "Te falta puntuar" in page  # neither house has all four topics from Ana


def test_zero_is_a_score_and_empty_clears(users):
    ana, _ = users
    h = add_house(ana)
    assert ana.post(f"/houses/{h}/scores", data={"r2_ubicacion": "0"}, headers=JSON).json()["base"] == 3  # (0 + 15) / 5
    assert ana.post(f"/houses/{h}/scores", data={"r2_ubicacion": ""}, headers=JSON).json()["overall"] is None
    assert ana.post(f"/houses/{h}/scores", data={"r2_ubicacion": "11"}, headers=JSON).json()["overall"] is None


def test_weights_change_overall(admin, users):
    ana, _ = users
    h = add_house(ana)
    admin.post("/settings/weights", data={"ubicacion": "3", "vecindario": "1", "construccion": "1", "antiguedad": "1"})
    s = ana.post(f"/houses/{h}/scores", data={"r2_ubicacion": "10", "r2_construccion": "0"}, headers=JSON).json()
    assert round(s["base"], 2) == 6.67  # (10*3 + 0 + 5 + 5) / 6


def test_visited_flag_and_filter(users):
    ana, _ = users
    v = add_house(ana, title="Fuimos")
    add_house(ana, title="Online")
    ana.post(f"/houses/{v}/scores", data={"visitada": "1"})
    page = ana.get("/").text
    assert "ribbon visited" in page and "ribbon not-visited" in page and "No visitada" in page
    only = ana.get("/?visitada=si").text
    assert "Fuimos" in only and "Online" not in only
    assert "Online" in ana.get("/?visitada=no").text and "Fuimos" not in ana.get("/?visitada=no").text


def test_discarded_hidden_by_default(users):
    ana, _ = users
    h = add_house(ana, title="Descartable")
    ana.post(f"/houses/{h}/scores", data={"status": "descartada"})
    assert "Descartable" not in ana.get("/").text
    assert "Descartable" in ana.get("/?all=1").text


def test_edit_and_delete(users):
    ana, _ = users
    h = add_house(ana)
    ana.post(f"/houses/{h}", data={"title": "Renombrada", "currency": "ARS", "price": "1000"})
    assert "Renombrada" in ana.get(f"/houses/{h}").text
    ana.post(f"/houses/{h}/delete")
    assert ana.get(f"/houses/{h}").status_code == 404


def test_exports(users):
    ana, _ = users
    h = add_house(ana, title="Exportada")
    ana.post(f"/houses/{h}/scores", data={"r2_vecindario": "8", "colegio": "1", "visitada": "1"})
    data = ana.get("/export.json").json()
    assert data[0]["title"] == "Exportada" and data[0]["Ana_vecindario"] == 8
    assert data[0]["colegio"] is True and data[0]["visitada"] is True
    assert "Ana_vecindario" in ana.get("/export.csv").text





def stars(uid, **topics):
    """Form fields for one user's stars, e.g. stars(2, ubicacion=8)."""
    return {f"r{uid}_{t}": str(v) for t, v in topics.items()}


def test_questions_are_a_share_of_the_score(admin, users):
    ana, _ = users
    h = add_house(ana)
    base = stars(2, ubicacion=6, vecindario=6, construccion=6, antiguedad=6)
    # Everything unknown = half credit.
    s = ana.post(f"/houses/{h}/scores", data=base, headers=JSON).json()
    assert s["base"] == 6 and s["questions"] == 5 and round(s["overall"], 2) == 5.85
    yes = {f: "1" for f in db.FEATURES}
    no = {f: "0" for f in db.FEATURES}
    assert round(ana.post(f"/houses/{h}/scores", data={**base, **yes}, headers=JSON).json()["overall"], 2) == 6.6
    assert round(ana.post(f"/houses/{h}/scores", data={**base, **no}, headers=JSON).json()["overall"], 2) == 5.1
    # Very important = double weight within the questions, 0 = ignored.
    admin.post("/settings/weights", data={"importance_pileta": "2", "importance_colegio": "0"})
    s = ana.post(f"/houses/{h}/scores", data={**base, **no, "pileta": "1"}, headers=JSON).json()
    assert round(s["questions"], 2) == round(10 * 2 / 11, 2)  # pileta 2 of total 2 + colegio 0 + 9 others x 1
    # The admin can change how much the questions are worth.
    admin.post("/settings/weights", data={"questions_share": "0"})
    assert ana.post(f"/houses/{h}/scores", data={**base, **yes}, headers=JSON).json()["overall"] == 6


def test_questions_need_stars(users):
    ana, _ = users
    h = add_house(ana)
    yes = {f: "1" for f in db.FEATURES}
    assert ana.post(f"/houses/{h}/scores", data=yes, headers=JSON).json()["overall"] is None


def test_only_a_perfect_house_gets_ten(users):
    ana, beto = users
    h = add_house(ana)
    yes = {f: "1" for f in db.FEATURES}
    ana.post(f"/houses/{h}/scores", data={**stars(2, **dict.fromkeys(db.TOPICS, 10)), **yes})
    s = beto.post(f"/houses/{h}/scores", data={**stars(3, **dict.fromkeys(db.TOPICS, 10)), **yes}, headers=JSON).json()
    assert s["overall"] == 10
    # One "No sé", one 9-star topic from one person, or one person not having rated: no longer perfect.
    s = beto.post(f"/houses/{h}/scores", data={**stars(3, **dict.fromkeys(db.TOPICS, 10)), **yes, "gimnasio": ""},
                  headers=JSON).json()
    assert 9.9 < s["overall"] < 10
    s = beto.post(f"/houses/{h}/scores", data={**stars(3, **{**dict.fromkeys(db.TOPICS, 10), "antiguedad": 9}), **yes},
                  headers=JSON).json()
    assert 9.8 < s["overall"] < 10
    s = beto.post(f"/houses/{h}/scores", data={**stars(3, ubicacion=10), **yes}, headers=JSON).json()
    assert s["overall"] < 9  # Beto's missing topics count as 5


def test_typical_good_house_is_not_ten(users):
    """The v1.3 bug: 8-9 stars and mostly Yes answers used to hit the 10.0 cap."""
    ana, _ = users
    h = add_house(ana)
    yes = {f: "1" for f in db.FEATURES}
    s = ana.post(f"/houses/{h}/scores", data={**stars(2, ubicacion=9, vecindario=9, construccion=8, antiguedad=9),
                                               **yes, "pileta": ""}, headers=JSON).json()
    assert 8.5 < s["overall"] < 9.5


def test_location_weighs_double_by_default(users):
    ana, _ = users
    a = add_house(ana, title="Buena ubicacion")
    b = add_house(ana, title="Buena construccion")
    sa = ana.post(f"/houses/{a}/scores", data=stars(2, ubicacion=10, vecindario=5, construccion=5, antiguedad=5),
                  headers=JSON).json()
    sb = ana.post(f"/houses/{b}/scores", data=stars(2, ubicacion=5, vecindario=5, construccion=10, antiguedad=5),
                  headers=JSON).json()
    assert sa["base"] == 7 and sb["base"] == 6


def test_both_opinions_count(users):
    ana, beto = users
    loved = add_house(ana, title="Le encanta a Ana")
    shared = add_house(ana, title="Les gusta a los dos")
    ana.post(f"/houses/{loved}/scores", data=stars(2, **dict.fromkeys(db.TOPICS, 10)))
    s = beto.post(f"/houses/{loved}/scores", data=stars(3, **dict.fromkeys(db.TOPICS, 5)), headers=JSON).json()
    # Average 7.5, lowest 5 -> 6.25: the one who isn't convinced pulls it down.
    assert s["people"] == {"2": 10, "3": 5} and s["base"] == 6.25
    ana.post(f"/houses/{shared}/scores", data=stars(2, **dict.fromkeys(db.TOPICS, 8)))
    beto.post(f"/houses/{shared}/scores", data=stars(3, **dict.fromkeys(db.TOPICS, 7)))
    page = ana.get("/").text
    assert page.index("Les gusta a los dos") < page.index("Le encanta a Ana")
    # Each person's own score is shown on the card.
    assert 'data-uid="2"' in page and 'data-uid="3"' in page


def test_missing_opinion_is_shown(users):
    ana, _ = users
    h = add_house(ana, title="Solo Ana")
    ana.post(f"/houses/{h}/scores", data=stars(2, ubicacion=8))
    page = ana.get("/").text
    assert "Falta Beto" in page


def test_new_questions_and_unknown_option(users):
    ana, _ = users
    h = add_house(ana)
    ana.post(f"/houses/{h}/scores", data={"pelopincho": "1", "pet_friendly": "0"})
    page = ana.get(f"/houses/{h}").text
    for text in ("¿Pet friendly?", "¿Tiene o puede tener pileta?", "¿Lugar para pelopincho?", "? No sé"):
        assert text in page
    assert 'id="pelopincho_yes" name="pelopincho" value="1" checked' in page
    assert 'id="pileta_unknown" name="pileta" value="" checked' in page


def test_currency_usd_default_or_ars(users):
    ana, _ = users
    form = ana.get("/houses/new").text
    assert re.findall(r"<option[^>]*>(\w+)</option>", form) == ["USD", "ARS"]
    h = add_house(ana, price="1000", currency="EUR")
    assert "USD 1.000" in ana.get(f"/houses/{h}").text


def test_importance_settings_admin_only(admin, users):
    ana, _ = users
    assert ana.post("/settings/weights", data={"importance_pileta": "2"}).status_code == 403
    admin.post("/settings/weights", data={"importance_pileta": "2"})
    assert '<option value="2" selected>2 · Muy importante' in admin.get("/settings").text


# --- migration -----------------------------------------------------------------


def test_migration_from_v1_keeps_data(env, monkeypatch):
    conn = sqlite3.connect(env / "casa-ranking.db")
    conn.executescript(db.SCHEMA_V1)
    conn.executescript("""
        INSERT INTO raters (id, name, position) VALUES (1, 'Matias', 0), (2, 'Analia', 1);
        INSERT INTO houses (id, title, status, supermercado, currency) VALUES (2, 'Casa vieja', 'visitada', 1, 'EUR');
        INSERT INTO ratings (house_id, rater_id, ubicacion, construccion) VALUES (2, 1, 7, 5), (2, 2, 9, NULL);
        INSERT INTO settings VALUES ('weight_ubicacion', '2');
        PRAGMA user_version = 1;
    """)
    conn.commit()
    conn.close()
    main = load_app(monkeypatch)
    admin = login(TestClient(main.app), "admin", ADMIN_PW)
    # Existing raters keep their ratings; admin gives them a login.
    admin.post("/admin/users/1", data={"name": "Matias", "email": "m@x.com", "password": "secret-123", "can_rate": "1"})
    matias = login(TestClient(main.app), "m@x.com", "secret-123")
    with db.session() as c:
        h = c.execute("SELECT * FROM houses WHERE id = 2").fetchone()
        assert h["visitada"] == 1 and h["status"] == "activa" and h["supermercado"] == 1
        assert h["currency"] == "USD" and h["pileta"] is None
        assert c.execute("PRAGMA user_version").fetchone()[0] == 5
        assert h["a_visitar"] == 0
        assert c.execute("SELECT COUNT(*) FROM ratings").fetchone()[0] == 2
        assert db.get_setting(c, "weight_ubicacion") == "2"
    page = matias.get("/houses/2").text
    assert 'name="r1_ubicacion" value="7" checked' in page
    assert "Solo Analia puede cambiar" in page


# --- misc ----------------------------------------------------------------------


def test_english_toggle(admin):
    assert "Ranking" in admin.get("/lang/en?next=/").text
    assert 'lang="en"' in admin.get("/").text


def test_lang_redirect_rejects_external_urls(main):
    r = TestClient(main.app).get("/lang/en?next=//evil.example", follow_redirects=False)
    assert r.headers["location"] == "/"


# --- importing from a link -------------------------------------------------------

LISTING = {"site": "Inmoup", "title": "Casa en Venta", "price": 90000.0, "currency": "USD",
           "address": "Dr. Perinetti 116, Godoy Cruz, Mendoza", "image_url": "https://img/1.jpg",
           "lat": -32.9, "lng": -68.8, "facts": "Dormitorios: 3"}


def test_add_from_link_fills_everything(main, users, monkeypatch):
    ana, _ = users
    monkeypatch.setattr(main.linkpreview, "fetch", lambda url, timeout=10.0: dict(LISTING))
    r = ana.post("/houses", data={"url": "https://inmoup.com.ar/a/ficha/casa?btid=99#x"})
    page = r.text
    assert "Importado de Inmoup: foto, precio, ubicación, características (en Notas)." in page
    assert "USD 90.000" in page and "Dr. Perinetti 116" in page and "Dormitorios: 3" in page
    assert "https://www.google.com/maps/search/?api=1&amp;query=-32.9,-68.8" in page
    with db.session() as c:
        h = c.execute("SELECT * FROM houses").fetchone()
    assert h["url"] == "https://inmoup.com.ar/a/ficha/casa" and h["image_url"] == "https://img/1.jpg"
    # Flash shows once only.
    assert "Importado de" not in ana.get(r.url.path).text


def test_add_from_link_reports_missing_fields(main, users, monkeypatch):
    ana, _ = users
    monkeypatch.setattr(main.linkpreview, "fetch", lambda url, timeout=10.0: {"site": "Remax", "title": "X"})
    page = ana.post("/houses", data={"url": "https://www.remax.com.ar/listings/x"}).text
    assert "No pudimos leer: foto, precio, ubicación." in page


def test_network_failure_explains_why_and_keeps_house(main, users, monkeypatch):
    ana, _ = users
    monkeypatch.setattr(main.linkpreview, "fetch",
                        lambda url, timeout=10.0: {"error": "dns", "detail": "timeout", "site": "MercadoLibre"})
    page = ana.post("/houses", data={"url": "https://casa.mercadolibre.com.ar/MLA-4017162980-venta-de-casa-guaymallen-_JM"}).text
    assert "No pudimos leer la publicación de MercadoLibre: no se pudo resolver el nombre del sitio" in page
    assert "Venta de casa guaymallen" in page  # title from the URL instead of "Casa sin título"
    monkeypatch.setattr(main.linkpreview, "fetch",
                        lambda url, timeout=10.0: {"error": "http_5xx", "detail": "503", "site": "MercadoLibre"})
    h = re.search(r'href="/houses/(\d+)"', ana.get("/").text).group(1)
    page = ana.post(f"/houses/{h}/refresh-preview").text
    assert "el sitio respondió con error 503" in page


def test_single_add_button_on_ranking(users):
    ana, _ = users
    page = ana.get("/").text
    assert page.count("Agregar casa") == 1 and 'href="/houses/new#manual"' in page


def test_duplicate_link_goes_to_existing_house(main, users, monkeypatch):
    ana, beto = users
    monkeypatch.setattr(main.linkpreview, "fetch", lambda url, timeout=10.0: dict(LISTING))
    first = ana.post("/houses", data={"url": "https://casa.mercadolibre.com.ar/MLA-1-x_JM#a"}, follow_redirects=False)
    again = beto.post("/houses", data={"url": "https://casa.mercadolibre.com.ar/MLA-1-x_JM?tracking=2"},
                      follow_redirects=False)
    assert again.headers["location"] == first.headers["location"]
    assert "ya estaba cargada" in beto.get(again.headers["location"]).text


def test_typed_values_win_over_imported(main, users, monkeypatch):
    ana, _ = users
    monkeypatch.setattr(main.linkpreview, "fetch", lambda url, timeout=10.0: dict(LISTING))
    ana.post("/houses", data={"url": "https://inmoup.com.ar/b", "price": "5000000", "currency": "ARS",
                              "address": "Mi dirección"})
    with db.session() as c:
        h = c.execute("SELECT * FROM houses").fetchone()
    assert (h["price"], h["currency"], h["address"]) == (5000000, "ARS", "Mi dirección")


def test_refresh_updates_and_reports_price_change(main, users, monkeypatch):
    ana, _ = users
    monkeypatch.setattr(main.linkpreview, "fetch", lambda url, timeout=10.0: dict(LISTING))
    h = int(ana.post("/houses", data={"url": "https://inmoup.com.ar/c"}, follow_redirects=False)
            .headers["location"].rsplit("/", 1)[1])
    monkeypatch.setattr(main.linkpreview, "fetch", lambda url, timeout=10.0: {**LISTING, "price": 85000.0})
    page = ana.post(f"/houses/{h}/refresh-preview").text
    assert "El precio cambió: USD 90.000 → USD 85.000" in page
    monkeypatch.setattr(main.linkpreview, "fetch", lambda url, timeout=10.0: {})
    page = ana.post(f"/houses/{h}/refresh-preview").text
    assert "No pudimos leer la publicación" in page and "USD 85.000" in page


def test_static_assets_are_versioned(admin):
    assert re.search(r'/static/style\.css\?v=[\d.]+', admin.get("/").text)


# --- tabs and "ir a visitar" ------------------------------------------------------


def _titles(page):
    return re.findall(r'<h2>([^<]+)</h2>', page.split('<ol class="cards">', 1)[1]) if '<ol class="cards">' in page else []


def test_to_visit_button_and_tabs(users):
    ana, beto = users
    fuimos = add_house(ana, title="Fuimos")
    plan = add_house(ana, title="Vamos el sabado")
    add_house(ana, title="Solo online")
    ana.post(f"/houses/{fuimos}/scores", data={"visitada": "1"})
    r = beto.post(f"/houses/{plan}/a-visitar", data={"on": "1"}, headers=JSON)
    assert r.json() == {"a_visitar": True, "visit": "a_visitar"}
    # The tabs split the houses with no overlap.
    assert _titles(ana.get("/?tab=visitadas").text) == ["Fuimos"]
    assert _titles(ana.get("/?tab=a_visitar").text) == ["Vamos el sabado"]
    assert _titles(ana.get("/?tab=sin_visitar").text) == ["Solo online"]
    page = ana.get("/").text
    assert len(_titles(page)) == 3
    for tab, n in (("todas", 3), ("visitadas", 1), ("a_visitar", 1), ("sin_visitar", 1)):
        assert re.search(rf'class="tab tab-{tab}"[^>]*>\s*[^<]+<span class="tab-n">{n}</span>', page), tab
    # Every unvisited card has the button; it shows its state.
    assert page.count('class="to-visit-form"') == 2 and 'aria-pressed="true"' in page
    # Without JS: a plain POST toggles and goes back to the page it came from.
    r = ana.post(f"/houses/{plan}/a-visitar", headers={"referer": "http://testserver/?tab=a_visitar"},
                 follow_redirects=False)
    assert r.headers["location"] == "/?tab=a_visitar"
    assert _titles(ana.get("/?tab=a_visitar").text) == []


def test_visiting_clears_to_visit(users):
    ana, _ = users
    h = add_house(ana)
    ana.post(f"/houses/{h}/a-visitar", data={"on": "1"})
    s = ana.post(f"/houses/{h}/scores", data={"visitada": "1"}, headers=JSON).json()
    assert s["visit"] == "visitadas"
    with db.session() as c:
        assert c.execute("SELECT a_visitar FROM houses WHERE id = ?", (h,)).fetchone()[0] == 0
    # A visited house has no "Ir a visitar" button any more.
    assert 'class="to-visit-form"' not in ana.get(f"/houses/{h}").text


def test_old_visited_links_still_work(users):
    ana, _ = users
    v = add_house(ana, title="Fuimos")
    add_house(ana, title="Online")
    ana.post(f"/houses/{v}/scores", data={"visitada": "1"})
    assert _titles(ana.get("/?visitada=si").text) == ["Fuimos"]
    assert _titles(ana.get("/?visitada=no").text) == ["Online"]


def test_to_visit_unknown_house_404(users):
    ana, _ = users
    assert ana.post("/houses/999/a-visitar").status_code == 404


# --- filters ---------------------------------------------------------------------


def _filter_houses(ana, beto):
    a = add_house(ana, title="Cara y buena", price="120000")
    b = add_house(ana, title="Barata con pileta", price="60000")
    c = add_house(ana, title="En pesos", price="90000", currency="ARS")
    add_house(ana, title="Sin puntuar")
    ana.post(f"/houses/{a}/scores", data=stars(2, ubicacion=9, vecindario=9, construccion=9, antiguedad=9))
    ana.post(f"/houses/{b}/scores", data={**stars(2, ubicacion=6, vecindario=7, construccion=5, antiguedad=5),
                                           "pileta": "1", "colegio": "1"})
    ana.post(f"/houses/{c}/scores", data=stars(2, ubicacion=7, vecindario=7, construccion=7, antiguedad=7))
    return a, b, c


def test_filter_by_score_and_stars(users):
    ana, beto = users
    _filter_houses(ana, beto)
    assert _titles(ana.get("/?min_score=8").text) == ["Cara y buena"]
    assert _titles(ana.get("/?min_vecindario=7").text) == ["Cara y buena", "En pesos", "Barata con pileta"]
    assert _titles(ana.get("/?min_ubicacion=7&min_construccion=7").text) == ["Cara y buena", "En pesos"]
    page = ana.get("/?min_score=8").text
    assert "Filtros (1)" in page and "Limpiar filtros" in page
    # A filtered house keeps its overall rank number.
    page = ana.get("/?min_ubicacion=7&min_construccion=7").text
    assert re.search(r'rank-(\d+)" data-visit[^>]*>(?:(?!</li>).)*En pesos', page, re.S).group(1) == "2"


def test_filter_by_features_and_price(users):
    ana, beto = users
    _filter_houses(ana, beto)
    assert _titles(ana.get("/?has=pileta&has=colegio").text) == ["Barata con pileta"]
    assert _titles(ana.get("/?has=pileta&has=gimnasio").text) == []
    assert "Ninguna casa cumple" in ana.get("/?has=pileta&has=gimnasio").text
    assert _titles(ana.get("/?price_max=100.000").text) == ["Barata con pileta"]
    assert _titles(ana.get("/?price_min=100000").text) == ["Cara y buena"]
    assert _titles(ana.get("/?price_max=100000&currency=ARS").text) == ["En pesos"]
    # Bad values are ignored, not errors.
    assert len(_titles(ana.get("/?min_score=abc&min_ubicacion=99&has=nope&currency=EUR").text)) == 4


def test_filters_combine_with_tabs_and_pending(users):
    ana, beto = users
    a, b, _ = _filter_houses(ana, beto)
    ana.post(f"/houses/{b}/a-visitar", data={"on": "1"})
    assert _titles(ana.get("/?tab=a_visitar&has=pileta").text) == ["Barata con pileta"]
    assert _titles(ana.get("/?tab=a_visitar&min_score=8").text) == []
    page = ana.get("/?min_score=8").text
    # Tab links keep the filters; counts follow them.
    assert 'href="/?min_score=8&amp;tab=visitadas"' in page
    assert re.search(r'class="tab tab-todas"[^>]*>\s*[^<]+<span class="tab-n">1</span>', page)
    beto.post(f"/houses/{a}/scores", data=stars(3, **dict.fromkeys(db.TOPICS, 8)))
    assert _titles(beto.get("/?pending=1").text) == ["En pesos", "Barata con pileta", "Sin puntuar"]


# --- comments --------------------------------------------------------------------


def test_comments_have_author_and_kind(users):
    ana, beto = users
    h = add_house(ana)
    ana.post(f"/houses/{h}/comments", data={"body": "Las fotos muestran humedad", "kind": "online"})
    r = beto.post(f"/houses/{h}/comments", data={"body": "Fuimos: la humedad es real\nel patio es enorme",
                                                  "kind": "visita"}, follow_redirects=False)
    assert r.headers["location"] == f"/houses/{h}?c=visita#comments"
    ana.post(f"/houses/{h}/comments", data={"body": "   ", "kind": "online"})  # empty: ignored
    page = ana.get(f"/houses/{h}").text
    assert page.count('<li class="comment kind-') == 2
    assert re.search(r'kind-online">.*?<strong>Ana</strong>.*?Las fotos muestran humedad', page, re.S)
    assert re.search(r'kind-visita">.*?<strong>Beto</strong>.*?el patio es enorme', page, re.S)
    # Counts per kind, and the list can open on one kind.
    assert re.search(r'data-show="visita"[^>]*>\s*[^<]*<span class="tab-n">1</span>', page)
    assert 'class="panel comments" data-show="visita"' in ana.get(f"/houses/{h}?c=visita").text
    # Comment count on the ranking card.
    assert f'href="/houses/{h}#comments"' in ana.get("/").text


def test_comment_kind_defaults(users):
    ana, _ = users
    h = add_house(ana)
    assert 'id="ck_online" name="kind" value="online" checked' in ana.get(f"/houses/{h}").text
    ana.post(f"/houses/{h}/scores", data={"visitada": "1"})
    assert 'id="ck_visita" name="kind" value="visita" checked' in ana.get(f"/houses/{h}").text
    ana.post(f"/houses/{h}/comments", data={"body": "x", "kind": "hack"})
    with db.session() as c:
        assert c.execute("SELECT kind FROM comments").fetchone()[0] == "online"


def test_comment_html_is_escaped(users):
    ana, _ = users
    h = add_house(ana)
    ana.post(f"/houses/{h}/comments", data={"body": "<script>alert(1)</script>"})
    page = ana.get(f"/houses/{h}").text
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page


def test_only_author_or_admin_deletes_comments(admin, users):
    ana, beto = users
    h = add_house(ana)
    ana.post(f"/houses/{h}/comments", data={"body": "de Ana"})
    ana.post(f"/houses/{h}/comments", data={"body": "otro de Ana"})
    with db.session() as c:
        first, second = [r[0] for r in c.execute("SELECT id FROM comments ORDER BY id")]
    assert beto.post(f"/comments/{first}/delete").status_code == 403
    assert 'action="/comments/' not in beto.get(f"/houses/{h}").text  # no delete button on others' comments
    ana.post(f"/comments/{first}/delete")
    admin.post(f"/comments/{second}/delete")
    with db.session() as c:
        assert c.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0
    assert ana.post("/comments/999/delete").status_code == 404


def test_comments_survive_user_deletion_and_go_with_house(admin, users):
    ana, beto = users
    h = add_house(ana)
    beto.post(f"/houses/{h}/comments", data={"body": "comentario de Beto"})
    admin.post("/admin/users/3/delete")
    page = ana.get(f"/houses/{h}").text
    assert "comentario de Beto" in page and "Usuario borrado" in page
    ana.post(f"/houses/{h}/delete")
    with db.session() as c:
        assert c.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0


def test_export_includes_comments_and_people(users):
    ana, beto = users
    h = add_house(ana, title="Exportada")
    ana.post(f"/houses/{h}/scores", data=stars(2, ubicacion=8))
    beto.post(f"/houses/{h}/comments", data={"body": "linda", "kind": "visita"})
    ana.post(f"/houses/{h}/a-visitar", data={"on": "1"})
    row = ana.get("/export.json").json()[0]
    assert row["comments"][0]["author"] == "Beto" and row["comments"][0]["kind"] == "visita"
    assert row["Ana_score"] == 6.2 and row["a_visitar"] is True and "questions_score" in row
    assert "Beto (visita): linda" in ana.get("/export.csv").text


def test_compare_shows_people_and_visit_state(users):
    ana, beto = users
    h = add_house(ana)
    ana.post(f"/houses/{h}/scores", data=stars(2, ubicacion=8))
    ana.post(f"/houses/{h}/a-visitar", data={"on": "1"})
    page = ana.get("/compare").text
    assert "<th title=\"Opinión de cada uno\">Ana</th>" in page and "visit-a_visitar" in page


def test_settings_show_topic_shares_and_questions_share(admin):
    page = admin.get("/settings").text
    assert "40%" in page and 'name="questions_share"' in page and 'value="15"' in page
    admin.post("/settings/weights", data={"questions_share": "99"})  # out of range: kept
    assert 'name="questions_share" min="0" max="50" step="1" value="15"' in admin.get("/settings").text
