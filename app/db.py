"""SQLite storage. Plain sqlite3, schema versioned with PRAGMA user_version."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

TOPICS = ("ubicacion", "vecindario", "construccion", "antiguedad", "mejorable", "me_gusta")
# Yes/No/unknown questions. Order is the order shown in the UI.
NEARBY = ("supermercado", "colegio", "transporte", "gimnasio", "ciclovia", "plaza", "hospital")
HOUSE_QUESTIONS = ("pet_friendly", "pileta", "pelopincho")
FEATURES = HOUSE_QUESTIONS + NEARBY
AMENITIES = NEARBY  # counted in the "Cerca x/7" summary
STATUSES = ("activa", "favorita", "descartada")
# Where a comment was made from: looking at the listing online, or after seeing the house in person.
COMMENT_KINDS = ("online", "visita")
COMMENT_MAX = 2000

# Version 1 as first released; later versions are migrations on top of it so
# fresh installs and upgraded ones always end up with the same schema.
SCHEMA_V1 = """
CREATE TABLE houses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    price REAL,
    currency TEXT NOT NULL DEFAULT 'USD',
    image_url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'activa',
    mejorable INTEGER, supermercado INTEGER, colegio INTEGER, transporte INTEGER,
    gimnasio INTEGER, ciclovia INTEGER, plaza INTEGER, hospital INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE raters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE ratings (
    house_id INTEGER NOT NULL REFERENCES houses(id) ON DELETE CASCADE,
    rater_id INTEGER NOT NULL REFERENCES raters(id) ON DELETE CASCADE,
    ubicacion INTEGER CHECK (ubicacion BETWEEN 0 AND 10),
    construccion INTEGER CHECK (construccion BETWEEN 0 AND 10),
    antiguedad INTEGER CHECK (antiguedad BETWEEN 0 AND 10),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (house_id, rater_id)
);
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# v2: raters become login users, "vecindario" topic, "visitada" split out of status.
MIGRATION_V2 = """
ALTER TABLE raters RENAME TO users;
ALTER TABLE ratings RENAME COLUMN rater_id TO user_id;
ALTER TABLE users ADD COLUMN email TEXT;
ALTER TABLE users ADD COLUMN password_hash TEXT;
ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN can_rate INTEGER NOT NULL DEFAULT 1;
CREATE UNIQUE INDEX users_email ON users (lower(email)) WHERE email IS NOT NULL AND email != '';
ALTER TABLE ratings ADD COLUMN vecindario INTEGER CHECK (vecindario BETWEEN 0 AND 10);
ALTER TABLE houses ADD COLUMN visitada INTEGER NOT NULL DEFAULT 0;
UPDATE houses SET visitada = 1, status = 'activa' WHERE status = 'visitada';
"""

# v3: more house questions; EUR dropped (prices are USD or ARS).
MIGRATION_V3 = """
ALTER TABLE houses ADD COLUMN pet_friendly INTEGER;
ALTER TABLE houses ADD COLUMN pileta INTEGER;
ALTER TABLE houses ADD COLUMN pelopincho INTEGER;
UPDATE houses SET currency = 'USD' WHERE currency NOT IN ('USD', 'ARS');
"""

# v4: coordinates read from the listing, for the map link.
MIGRATION_V4 = """
ALTER TABLE houses ADD COLUMN lat REAL;
ALTER TABLE houses ADD COLUMN lng REAL;
"""

# v5: "ir a visitar" (planned visit) flag and per-house comments with their author.
MIGRATION_V5 = """
ALTER TABLE houses ADD COLUMN a_visitar INTEGER NOT NULL DEFAULT 0;
CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    house_id INTEGER NOT NULL REFERENCES houses(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind TEXT NOT NULL DEFAULT 'online' CHECK (kind IN ('online', 'visita')),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX comments_house ON comments (house_id, created_at);
"""

# v6: "mejorable" goes from a shared Yes/No question to per-person stars (how much better the
# house could be); new "me gusta" stars. The old houses.mejorable answers are cleared, unused since.
MIGRATION_V6 = """
ALTER TABLE ratings ADD COLUMN mejorable INTEGER CHECK (mejorable BETWEEN 0 AND 10);
ALTER TABLE ratings ADD COLUMN me_gusta INTEGER CHECK (me_gusta BETWEEN 0 AND 10);
UPDATE houses SET mejorable = NULL;
DELETE FROM settings WHERE key = 'importance_mejorable';
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


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    try:
        _, salt, digest = (stored or "").split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    except ValueError:
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def init() -> str | None:
    """Create or migrate the DB. Returns a generated admin password if one was created."""
    with session() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            conn.executescript(SCHEMA_V1)
            version = 1
        if version == 1:
            conn.executescript(MIGRATION_V2)
            version = 2
        if version == 2:
            conn.executescript(MIGRATION_V3)
            version = 3
        if version == 3:
            conn.executescript(MIGRATION_V4)
            version = 4
        if version == 4:
            conn.executescript(MIGRATION_V5)
            version = 5
        if version == 5:
            conn.executescript(MIGRATION_V6)
            version = 6
        conn.execute(f"PRAGMA user_version = {version}")
        return ensure_admin(conn)


def ensure_admin(conn) -> str | None:
    if conn.execute("SELECT 1 FROM users WHERE is_admin = 1").fetchone():
        return None
    email = os.environ.get("ADMIN_EMAIL", "").strip() or "admin"
    password = os.environ.get("ADMIN_PASSWORD", "") or secrets.token_urlsafe(12)
    pos = conn.execute("SELECT COALESCE(MIN(position), 0) - 1 FROM users").fetchone()[0]
    conn.execute(
        "INSERT INTO users (name, email, password_hash, is_admin, can_rate, position) VALUES (?, ?, ?, 1, 0, ?)",
        ("Admin", email, hash_password(password), pos),
    )
    return None if os.environ.get("ADMIN_PASSWORD") else password


def get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
