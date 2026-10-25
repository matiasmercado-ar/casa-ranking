import re
import sqlite3

from fastapi.testclient import TestClient

from app import db
from app.linkpreview import _MetaParser
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
    assert s["overall"] == 8  # unrated topics are ignored, not counted as zero
    assert s["amenities_yes"] == 1
    page = ana.get("/").text
    assert page.index("Casa B") < page.index("Casa A")
    assert "USD 150.000" in page
    assert "Te falta puntuar" in page  # neither house has all four topics from Ana


def test_zero_is_a_score_and_empty_clears(users):
    ana, _ = users
    h = add_house(ana)
    assert ana.post(f"/houses/{h}/scores", data={"r2_ubicacion": "0"}, headers=JSON).json()["overall"] == 0
    assert ana.post(f"/houses/{h}/scores", data={"r2_ubicacion": ""}, headers=JSON).json()["overall"] is None
    assert ana.post(f"/houses/{h}/scores", data={"r2_ubicacion": "11"}, headers=JSON).json()["overall"] is None


def test_weights_change_overall(admin, users):
    ana, _ = users
    h = add_house(ana)
    admin.post("/settings/weights", data={"ubicacion": "3", "vecindario": "1", "construccion": "1", "antiguedad": "1"})
    s = ana.post(f"/houses/{h}/scores", data={"r2_ubicacion": "10", "r2_construccion": "0"}, headers=JSON).json()
    assert s["overall"] == 7.5


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


def test_questions_adjust_score(admin, users):
    ana, _ = users
    h = add_house(ana)
    base = {"r2_ubicacion": "6"}
    s = ana.post(f"/houses/{h}/scores", data=base, headers=JSON).json()
    assert s["overall"] == 6 and s["bonus"] == 0
    # Normal importance: each Yes +0.3, each No -0.3, unknown 0.
    s = ana.post(f"/houses/{h}/scores", data={**base, "pileta": "1", "pet_friendly": "1", "colegio": "0", "plaza": ""},
                 headers=JSON).json()
    assert s["bonus"] == 0.3 and round(s["overall"], 2) == 6.3
    # Very important = double, not important = nothing.
    admin.post("/settings/weights", data={"importance_pileta": "2", "importance_colegio": "0"})
    s = ana.post(f"/houses/{h}/scores", data={**base, "pileta": "1", "pet_friendly": "1", "colegio": "0"},
                 headers=JSON).json()
    assert s["bonus"] == 0.9 and s["base"] == 6


def test_questions_need_stars_and_score_is_clamped(users):
    ana, _ = users
    h = add_house(ana)
    yes = {f: "1" for f in db.FEATURES}
    assert ana.post(f"/houses/{h}/scores", data=yes, headers=JSON).json()["overall"] is None
    s = ana.post(f"/houses/{h}/scores", data={**yes, "r2_ubicacion": "10"}, headers=JSON).json()
    assert s["overall"] == 10 and s["raw"] > 10


def test_ties_at_ten_sorted_by_raw_score(users):
    ana, _ = users
    a = add_house(ana, title="Diez pelada")
    b = add_house(ana, title="Diez con pileta")
    ana.post(f"/houses/{a}/scores", data={"r2_ubicacion": "10"})
    ana.post(f"/houses/{b}/scores", data={"r2_ubicacion": "10", "pileta": "1"})
    page = ana.get("/").text
    assert page.index("Diez con pileta") < page.index("Diez pelada")


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
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
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


def test_meta_parser():
    p = _MetaParser()
    p.feed('<html><head><title> Fallback </title><meta property="og:title" content="Casa linda">'
           '<meta property="og:image" content="/img.jpg"></head></html>')
    assert p.meta["og:title"] == "Casa linda" and p.meta["og:image"] == "/img.jpg" and p.title == "Fallback"


def test_static_assets_are_versioned(admin):
    assert re.search(r'/static/style\.css\?v=[\d.]+', admin.get("/").text)
