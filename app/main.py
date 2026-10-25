import csv
import hmac
import io
import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db, linkpreview
from .db import AMENITIES, FEATURES, STATUSES, TOPICS
from .i18n import DEFAULT_LANG, LANGS, translate
from .scoring import house_scores, ranking, weights

__version__ = "1.0.0"
BASE = Path(__file__).parent
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
CURRENCIES = ("USD", "ARS", "EUR")


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
db.init()


def lang_of(request: Request) -> str:
    lang = request.cookies.get("lang", "")
    return lang if lang in LANGS else DEFAULT_LANG


@app.middleware("http")
async def require_login(request: Request, call_next):
    open_paths = ("/login", "/static/", "/healthz", "/lang/")
    if APP_PASSWORD and not request.session.get("ok") and not request.url.path.startswith(open_paths):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


# Added after require_login so it wraps it (last added = outermost).
app.add_middleware(SessionMiddleware, secret_key=_secret_key(), same_site="lax", max_age=60 * 60 * 24 * 90)


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    lang = lang_of(request)
    ctx.update(
        lang=lang,
        langs=LANGS,
        t=lambda key, **kw: translate(key, lang, **kw),
        TOPICS=TOPICS,
        FEATURES=FEATURES,
        AMENITIES=AMENITIES,
        STATUSES=STATUSES,
        CURRENCIES=CURRENCIES,
        auth_enabled=bool(APP_PASSWORD),
        version=__version__,
        path=request.url.path,
    )
    return templates.TemplateResponse(request, name, ctx)


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


# --- pages -----------------------------------------------------------------


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, all: int = 0):
    with db.session() as conn:
        rows = ranking(conn, include_discarded=bool(all))
        raters = conn.execute("SELECT COUNT(*) FROM raters").fetchone()[0]
        discarded = conn.execute("SELECT COUNT(*) FROM houses WHERE status = 'descartada'").fetchone()[0]
    return render(request, "index.html", rows=rows, show_all=bool(all), raters=raters, discarded=discarded)


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
        raters = conn.execute("SELECT * FROM raters ORDER BY position, id").fetchall()
        rows = conn.execute("SELECT * FROM ratings WHERE house_id = ?", (house_id,)).fetchall()
        scores = house_scores(h, rows, weights(conn))
    by_rater = {r["rater_id"]: r for r in rows}
    return render(request, "house_detail.html", house=h, raters=raters, by_rater=by_rater, scores=scores)


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
    """One form for star ratings, Yes/No features and status. Autosaved by app.js."""
    form = await request.form()
    with db.session() as conn:
        h = _house_or_404(conn, house_id)
        for rater in conn.execute("SELECT id FROM raters"):
            values = {}
            for t in TOPICS:
                raw = form.get(f"r{rater['id']}_{t}", "")
                values[t] = int(raw) if str(raw).isdigit() and 0 <= int(raw) <= 10 else None
            conn.execute(
                f"INSERT INTO ratings (house_id, rater_id, {', '.join(TOPICS)}) VALUES (?, ?, ?, ?, ?) "
                f"ON CONFLICT(house_id, rater_id) DO UPDATE SET "
                f"{', '.join(f'{t} = excluded.{t}' for t in TOPICS)}, updated_at = datetime('now')",
                (house_id, rater["id"], *[values[t] for t in TOPICS]),
            )
        status = form.get("status")
        conn.execute(
            f"UPDATE houses SET {', '.join(f'{f} = ?' for f in FEATURES)}, status = ?, "
            f"updated_at = datetime('now') WHERE id = ?",
            (*[_tri(form.get(f)) for f in FEATURES], status if status in STATUSES else h["status"], house_id),
        )
        h = _house_or_404(conn, house_id)
        rows = conn.execute("SELECT * FROM ratings WHERE house_id = ?", (house_id,)).fetchall()
        scores = house_scores(h, rows, weights(conn))
    if request.headers.get("accept") == "application/json":
        return JSONResponse(scores)
    return RedirectResponse(f"/houses/{house_id}", status_code=303)


# --- settings --------------------------------------------------------------


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    with db.session() as conn:
        raters = conn.execute("SELECT * FROM raters ORDER BY position, id").fetchall()
        w = weights(conn)
    return render(request, "settings.html", raters=raters, weights=w)


@app.post("/settings/raters")
async def save_raters(request: Request):
    form = await request.form()
    with db.session() as conn:
        for r in conn.execute("SELECT id FROM raters").fetchall():
            if form.get(f"remove_{r['id']}"):
                conn.execute("DELETE FROM raters WHERE id = ?", (r["id"],))
            elif (name := str(form.get(f"name_{r['id']}", "")).strip()):
                conn.execute("UPDATE raters SET name = ? WHERE id = ?", (name[:40], r["id"]))
        if (new := str(form.get("new_name", "")).strip()):
            pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM raters").fetchone()[0]
            conn.execute("INSERT INTO raters (name, position) VALUES (?, ?)", (new[:40], pos))
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/weights")
async def save_weights(request: Request):
    form = await request.form()
    with db.session() as conn:
        for t in TOPICS:
            try:
                value = min(10.0, max(0.0, float(str(form.get(t, "1")).replace(",", "."))))
            except ValueError:
                value = 1.0
            db.set_setting(conn, f"weight_{t}", f"{value:g}")
    return RedirectResponse("/settings", status_code=303)


@app.get("/lang/{code}")
def set_lang(request: Request, code: str, next: str = "/"):
    resp = RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/", status_code=303)
    if code in LANGS:
        resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


# --- export ----------------------------------------------------------------


def _export_rows(conn) -> list[dict]:
    raters = {r["id"]: r["name"] for r in conn.execute("SELECT * FROM raters")}
    out = []
    for row in ranking(conn, include_discarded=True):
        h = row["house"]
        item = {"rank": row["rank"], "id": h["id"], "title": h["title"], "url": h["url"], "address": h["address"],
                "price": h["price"], "currency": h["currency"], "status": h["status"],
                "score": round(row["overall"], 2) if row["overall"] is not None else None}
        item.update({f"avg_{t}": round(v, 2) if v is not None else None for t, v in row["topics"].items()})
        item.update({f: {1: True, 0: False}.get(h[f]) for f in FEATURES})
        item["notes"] = h["notes"]
        for r in conn.execute("SELECT * FROM ratings WHERE house_id = ?", (h["id"],)):
            for t in TOPICS:
                item[f"{raters.get(r['rater_id'], r['rater_id'])}_{t}"] = r[t]
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
    if not APP_PASSWORD:
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", error=False)


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form("")):
    if APP_PASSWORD and hmac.compare_digest(password.encode(), APP_PASSWORD.encode()):
        request.session["ok"] = True
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", error=True)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
