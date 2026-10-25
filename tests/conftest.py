import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    def _make(**env):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("RATERS", env.pop("RATERS", "Ana,Beto"))
        monkeypatch.setenv("APP_PASSWORD", env.pop("APP_PASSWORD", ""))
        # Keep tests offline: the link preview must never hit the network.
        sys.modules.pop("app.main", None)
        main = importlib.import_module("app.main")
        monkeypatch.setattr(main.linkpreview, "fetch", lambda url, timeout=6.0: {})
        return TestClient(main.app)

    return _make


@pytest.fixture
def client(make_client):
    return make_client()
