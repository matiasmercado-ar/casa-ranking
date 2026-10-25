import csv
import io
import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db, linkpreview
from .db import AMENITIES, FEATURES, HOUSE_QUESTIONS, NEARBY, STATUSES, TOPICS
from .i18n import DEFAULT_LANG, LANGS, translate
from .scoring import BONUS_STEP, IMPORTANCE, house_scores, ranking, weights

__version__ = "1.2.0"
BASE = Path(__file__).parent
CURRENCIES = ("USD", "ARS")
MIN_PASSWORD = 8
log = logging.getLogger("uvicorn.error")


def _secret_key() -> str:
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    # Persist a generated key next to the DB so sessions survive restarts.
    path = db.db_path().parent / "secret.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)
    return path.read_text().strip()


app = FastAPI(title="Casa Ranking", version=__version__, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

if (generated := db.init()):
    log.warning("Created admin account. User: %s  Password: %s  (change it in Ajustes)",
                os.environ.get("ADMIN_EMAIL") or "admin", generated)


def lang_of(request: Request) -> str:
    lang = request.cookies.get("lang", "")
    return lang if lang in LANGS else DEFAULT_LANG


@app.middleware("http")
async def require_login(request: Request, call_next):
    request.state.user = None
    if (uid := request.session.get("uid")):
        with db.session() as conn:
            request.state.user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if request.state.user is None:
            request.session.clear()
    open_paths = ("/login", "/static/", "/healthz", "/lang/")
    if request.state.user is None and not request.url.path.startswith(open_paths):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


# Added after require_login so it wraps it (last added = outermost).
app.add_middleware(SessionMiddleware, secret_key=_secret_key(), same_site="lax", max_age=60 * 60 * 24 * 90)


def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    lang = lang_of(request)
    ctx.update(
        lang=lang,
        langs=LANGS,
        t=lambda key, **kw: translate(key, lang, **kw),
        me=request.state.user,
        TOPICS=TOPICS,
        FEATURES=FEATURES,
        AMENITIES=AMENITIES,
        NEARBY=NEARBY,
        HOUSE_QUESTIONS=HOUSE_QUESTIONS,
        BONUS_STEP=BONUS_STEP,
        IMPORTANCE=IMPORTANCE,
        STATUSES=STATUSES,
        CURRENCIES=CURRENCIES,
        version=__version__,
        path=request.url.path,
    )
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _admin(request: Request):
    if not request.state.user["is_admin"]:
        raise HTTPException(403)
    return request.state.user


def _house_or_404(conn, house_id: int):
    h = conn.execute("SELECT * FROM houses WHERE id = ?", (house_id,)).fetchone()
    if not h:
        raise HTTPException(404)
    return h


def _price(value: str):
    value = (value or "").replace(".", "").replace(",", "").replace("$", "").strip()
    return float(value) if value.isdigit() else None


def _tri(value) -> int | None:
    return {"1": 1, "0": 0}.get(str(value))


def _users(conn):
    return conn.execute("SELECT * FROM users ORDER BY position, id").fetchall()


def _raters(conn):
    return conn.execute("SELECT * FROM users WHERE can_rate = 1 ORDER BY position, id").fetchall()


# --- pages -----------------------------------------------------------------


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, all: int = 0, visitada: str = ""):
    visitada = visitada if visitada in ("si", "no") else ""
    with db.session() as conn:
        rows = ranking(conn, include_discarded=bool(all), visited=visitada)
        raters = len(_raters(conn))
        discarded = conn.execute("SELECT COUNT(*) FROM houses WHERE status = 'descartada'").fetchone()[0]
    me = request.state.user
    for r in rows:
        mine = r["ratings"].get(me["id"])
        r["pending_me"] = bool(me["can_rate"]) and (mine is None or any(mine[t] is None for t in TOPICS))
    return render(request, "index.html", rows=rows, show_all=bool(all), raters=raters, discarded=discarded,
                  visitada=visitada)


@app.get("/compare", response_class=HTMLResponse)
def compare(request: Request):
    with db.session() as conn:
        rows = ranking(conn, include_discarded=False)
    return render(request, "compare.html", rows=rows)


@app.get("/houses/new", response_class=HTMLResponse)
def new_house(request: Request, url: str = ""):
    return render(request, "house_form.html", house=None, prefill_url=url)


@app.post("/houses")
def create_house(
    url: str = Form(""),
    title: str = Form(""),
    address: str = Form(""),
    price: str = Form(""),
    currency: str = Form("USD"),
    image_url: str = Form(""),
    notes: str = Form(""),
):
    url = url.strip()
    if url and (not title.strip() or not image_url.strip()):
        meta = linkpreview.fetch(url)
        title = title.strip() or meta.get("title", "")
        image_url = image_url.strip() or meta.get("image_url", "")
    with db.session() as conn:
        cur = conn.execute(
            "INSERT INTO houses (url, title, address, price, currency, image_url, notes) VALUES (?,?,?,?,?,?,?)",
            (url, title.strip(), address.strip(), _price(price), currency if currency in CURRENCIES else "USD",
             image_url.strip(), notes.strip()),
        )
        house_id = cur.lastrowid
    return RedirectResponse(f"/houses/{house_id}", status_code=303)


@app.get("/houses/{house_id}", response_class=HTMLResponse)
def house_detail(request: Request, house_id: int):
    with db.session() as conn:
        h = _house_or_404(conn, house_id)
        raters = _raters(conn)
        rows = conn.execute("SELECT * FROM ratings WHERE house_id = ?", (house_id,)).fetchall()
        w = weights(conn)
        scores = house_scores(h, rows, w)
    # The logged-in user's row first: it is the only one they can edit.
    me = request.state.user
    raters = sorted(raters, key=lambda r: r["id"] != me["id"])
    return render(request, "house_detail.html", house=h, raters=raters, by_rater=scores["ratings"], scores=scores, w=w)


@app.get("/houses/{house_id}/edit", response_class=HTMLResponse)
def edit_house(request: Request, house_id: int):
    with db.session() as conn:
        h = _house_or_404(conn, house_id)
    return render(request, "house_form.html", house=h, prefill_url="")


@app.post("/houses/{house_id}")
def update_house(
    house_id: int,
    url: str = Form(""),
    title: str = Form(""),
    address: str = Form(""),
    price: str = Form(""),
    currency: str = Form("USD"),
    image_url: str = Form(""),
    notes: str = Form(""),
):
    with db.session() as conn:
        _house_or_404(conn, house_id)
        conn.execute(
            "UPDATE houses SET url=?, title=?, address=?, price=?, currency=?, image_url=?, notes=?, "
            "updated_at=datetime('now') WHERE id=?",
            (url.strip(), title.strip(), address.strip(), _price(price),
             currency if currency in CURRENCIES else "USD", image_url.strip(), notes.strip(), house_id),
        )
    return RedirectResponse(f"/houses/{house_id}", status_code=303)


@app.post("/houses/{house_id}/refresh-preview")
def refresh_preview(house_id: int):
    with db.session() as conn:
        h = _house_or_404(conn, house_id)
        meta = linkpreview.fetch(h["url"]) if h["url"] else {}
        if meta:
            conn.execute(
                "UPDATE houses SET title = ?, image_url = ?, updated_at = datetime('now') WHERE id = ?",
                (meta.get("title") or h["title"], meta.get("image_url") or h["image_url"], house_id),
            )
    return RedirectResponse(f"/houses/{house_id}", status_code=303)


@app.post("/houses/{house_id}/delete")
def delete_house(house_id: int):
    with db.session() as conn:
        conn.execute("DELETE FROM houses WHERE id = ?", (house_id,))
    return RedirectResponse("/", status_code=303)


@app.post("/houses/{house_id}/scores")
async def save_scores(request: Request, house_id: int):
    """Own star ratings + shared Yes/No features, visited and status. Autosaved by app.js.

    Only the logged-in user's ratings are read from the form: other people's
    stars are never written here, whatever the request contains.
    """
    form = await request.form()
    me = request.state.user
    with db.session() as conn:
        h = _house_or_404(conn, house_id)
        if me["can_rate"]:
            values = {}
            for t in TOPICS:
                raw = str(form.get(f"r{me['id']}_{t}", ""))
                values[t] = int(raw) if raw.isdigit() and 0 <= int(raw) <= 10 else None
            conn.execute(
                f"INSERT INTO ratings (house_id, user_id, {', '.join(TOPICS)}) VALUES (?, ?, {', '.join('?' * len(TOPICS))}) "
                f"ON CONFLICT(house_id, user_id) DO UPDATE SET "
                f"{', '.join(f'{t} = excluded.{t}' for t in TOPICS)}, updated_at = datetime('now')",
                (house_id, me["id"], *[values[t] for t in TOPICS]),
            )
        status = form.get("status")
        conn.execute(
            f"UPDATE houses SET {', '.join(f'{f} = ?' for f in FEATURES)}, visitada = ?, status = ?, "
            f"updated_at = datetime('now') WHERE id = ?",
            (*[_tri(form.get(f)) for f in FEATURES], 1 if form.get("visitada") == "1" else 0,
             status if status in STATUSES else h["status"], house_id),
        )
        h = _house_or_404(conn, house_id)
        rows = conn.execute("SELECT * FROM ratings WHERE house_id = ?", (house_id,)).fetchall()
        scores = house_scores(h, rows, weights(conn))
    if request.headers.get("accept") == "application/json":
        scores.pop("ratings")
        return JSONResponse(scores)
    return RedirectResponse(f"/houses/{house_id}", status_code=303)


# --- settings --------------------------------------------------------------


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request, msg: str = "", err: str = ""):
    with db.session() as conn:
        users = _users(conn)
        w = weights(conn)
    return render(request, "settings.html", users=users, weights=w, msg=msg, err=err)


def _back(msg: str = "", err: str = "", anchor: str = "") -> RedirectResponse:
    q = f"?msg={msg}" if msg else f"?err={err}" if err else ""
    return RedirectResponse(f"/settings{q}{anchor}", status_code=303)


@app.post("/account/password")
def change_password(request: Request, current: str = Form(""), new: str = Form("")):
    me = request.state.user
    if not db.check_password(current, me["password_hash"]):
        return _back(err="bad_current", anchor="#account")
    if len(new) < MIN_PASSWORD:
        return _back(err="short_password", anchor="#account")
    with db.session() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (db.hash_password(new), me["id"]))
    return _back(msg="password_changed", anchor="#account")


@app.post("/settings/weights")
async def save_weights(request: Request):
    _admin(request)
    form = await request.form()
    with db.session() as conn:
        for t in TOPICS:
            try:
                value = min(10.0, max(0.0, float(str(form.get(t, "1")).replace(",", "."))))
            except ValueError:
                value = 1.0
            db.set_setting(conn, f"weight_{t}", f"{value:g}")
        for f in FEATURES:
            value = str(form.get(f"importance_{f}", "1"))
            db.set_setting(conn, f"importance_{f}", value if value in ("0", "1", "2") else "1")
    return _back(msg="saved", anchor="#weights")


@app.post("/admin/users")
def create_user(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    is_admin: str = Form(""),
    can_rate: str = Form(""),
):
    _admin(request)
    name, email = name.strip()[:40], email.strip().lower()[:120]
    if not name or not email:
        return _back(err="name_email_required", anchor="#users")
    if len(password) < MIN_PASSWORD:
        return _back(err="short_password", anchor="#users")
    try:
        with db.session() as conn:
            pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM users").fetchone()[0]
            conn.execute(
                "INSERT INTO users (name, email, password_hash, is_admin, can_rate, position) VALUES (?,?,?,?,?,?)",
                (name, email, db.hash_password(password), int(bool(is_admin)), int(bool(can_rate)), pos),
            )
    except sqlite3.IntegrityError:
        return _back(err="email_taken", anchor="#users")
    return _back(msg="user_added", anchor="#users")


@app.post("/admin/users/{user_id}")
def update_user(
    request: Request,
    user_id: int,
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    is_admin: str = Form(""),
    can_rate: str = Form(""),
):
    me = _admin(request)
    name, email = name.strip()[:40], email.strip().lower()[:120]
    if not name or not email:
        return _back(err="name_email_required", anchor="#users")
    if password and len(password) < MIN_PASSWORD:
        return _back(err="short_password", anchor="#users")
    # An admin can't demote themselves, so there is always at least one admin.
    admin_flag = 1 if user_id == me["id"] else int(bool(is_admin))
    try:
        with db.session() as conn:
            conn.execute("UPDATE users SET name = ?, email = ?, is_admin = ?, can_rate = ? WHERE id = ?",
                         (name, email, admin_flag, int(bool(can_rate)), user_id))
            if password:
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (db.hash_password(password), user_id))
    except sqlite3.IntegrityError:
        return _back(err="email_taken", anchor="#users")
    return _back(msg="saved", anchor="#users")


@app.post("/admin/users/{user_id}/delete")
def delete_user(request: Request, user_id: int):
    me = _admin(request)
    if user_id == me["id"]:
        return _back(err="cannot_delete_self", anchor="#users")
    with db.session() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return _back(msg="user_deleted", anchor="#users")


@app.get("/lang/{code}")
def set_lang(request: Request, code: str, next: str = "/"):
    resp = RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/", status_code=303)
    if code in LANGS:
        resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


# --- export ----------------------------------------------------------------


def _export_rows(conn) -> list[dict]:
    names = {u["id"]: u["name"] for u in _users(conn)}
    out = []
    for row in ranking(conn, include_discarded=True):
        h = row["house"]
        item = {"rank": row["rank"], "id": h["id"], "title": h["title"], "url": h["url"], "address": h["address"],
                "price": h["price"], "currency": h["currency"], "status": h["status"],
                "visitada": bool(h["visitada"]),
                "score": round(row["overall"], 2) if row["overall"] is not None else None,
                "stars_score": round(row["base"], 2) if row["base"] is not None else None,
                "questions_bonus": row["bonus"]}
        item.update({f"avg_{t}": round(v, 2) if v is not None else None for t, v in row["topics"].items()})
        item.update({f: {1: True, 0: False}.get(h[f]) for f in FEATURES})
        item["notes"] = h["notes"]
        for uid, r in row["ratings"].items():
            for t in TOPICS:
                item[f"{names.get(uid, uid)}_{t}"] = r[t]
        out.append(item)
    return out


@app.get("/export.json")
def export_json():
    with db.session() as conn:
        data = _export_rows(conn)
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=casa-ranking.json"})


@app.get("/export.csv")
def export_csv():
    with db.session() as conn:
        data = _export_rows(conn)
    buf = io.StringIO()
    fields = list(dict.fromkeys(k for row in data for k in row))
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    writer.writerows(data)
    # BOM so Excel opens accents correctly.
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=casa-ranking.csv"})


# --- login -----------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.state.user:
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", error=False, email="")


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(""), password: str = Form("")):
    with db.session() as conn:
        user = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email.strip().lower(),)).fetchone()
    if user and db.check_password(password, user["password_hash"]):
        request.session.clear()
        request.session["uid"] = user["id"]
        return RedirectResponse("/", status_code=303)
    time.sleep(1)  # slow down guessing
    return render(request, "login.html", status_code=401, error=True, email=email)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
