import importlib
import sys

import pytest
from fastapi.testclient import TestClient

ADMIN_PW = "admin-pass-123"


def load_app(monkeypatch):
    # Keep tests offline: the link preview must never hit the network.
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    monkeypatch.setattr(main.linkpreview, "fetch", lambda url, timeout=6.0: {})
    return main


def login(client, email, password):
    r = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    return tmp_path


@pytest.fixture
def main(env, monkeypatch):
    return load_app(monkeypatch)


@pytest.fixture
def admin(main):
    return login(TestClient(main.app), "admin", ADMIN_PW)


@pytest.fixture
def users(main, admin):
    """Two raters, Ana (id 2) and Beto (id 3), each with their own logged-in client."""
    for name in ("Ana", "Beto"):
        r = admin.post("/admin/users", data={"name": name, "email": f"{name.lower()}@x.com",
                                             "password": "secret-123", "can_rate": "1"})
        assert "msg=user_added" in str(r.url)
    ana = login(TestClient(main.app), "ana@x.com", "secret-123")
    beto = login(TestClient(main.app), "beto@x.com", "secret-123")
    return ana, beto
