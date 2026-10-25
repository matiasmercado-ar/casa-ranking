"""SQLite storage. Plain sqlite3, schema versioned with PRAGMA user_version."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

TOPICS = ("ubicacion", "construccion", "antiguedad")
FEATURES = (
    "mejorable",
    "supermercado",
    "colegio",
    "transporte",
    "gimnasio",
    "ciclovia",
    "plaza",
    "hospital",
)
# "mejorable" is informational: it is not counted as a nearby amenity.
AMENITIES = tuple(f for f in FEATURES if f != "mejorable")
STATUSES = ("activa", "visitada", "favorita", "descartada")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS houses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    price REAL,
    currency TEXT NOT NULL DEFAULT 'USD',
    image_url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'activa',
    {", ".join(f"{f} INTEGER" for f in FEATURES)},
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS raters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ratings (
    house_id INTEGER NOT NULL REFERENCES houses(id) ON DELETE CASCADE,
    rater_id INTEGER NOT NULL REFERENCES raters(id) ON DELETE CASCADE,
    {", ".join(f"{t} INTEGER CHECK ({t} BETWEEN 0 AND 10)" for t in TOPICS)},
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (house_id, rater_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def db_path() -> Path:
    return Path(os.environ.get("DATA_DIR", "./data")) / "casa-ranking.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
            names = [n.strip() for n in os.environ.get("RATERS", "").split(",") if n.strip()]
            for i, name in enumerate(names or ["Persona 1", "Persona 2"]):
                conn.execute("INSERT INTO raters (name, position) VALUES (?, ?)", (name, i))
            conn.execute("PRAGMA user_version = 1")


def get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
