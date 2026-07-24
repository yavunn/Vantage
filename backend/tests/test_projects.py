"""Projeler: admin proje EKLEYEMEZ ama TÜM kullanıcı projelerini görür."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, email, role="user", password="parola1"):
    from app.core.security import hash_password
    from app.models import Developer, User

    dev = Developer(display_name=email.split("@")[0], external_ids={}, anonymizable=True)
    session.add(dev)
    session.flush()
    now = datetime.now(timezone.utc)
    u = User(
        email=email.lower(), password_hash=hash_password(password), role=role,
        developer_id=dev.id, is_active=True, must_change_password=False,
        created_at=now, updated_at=now,
    )
    session.add(u)
    session.commit()
    return u


def _token(client, email, password="parola1"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _add_project(session, user_id, name="P1"):
    from app.models import UserProject

    now = datetime.now(timezone.utc)
    p = UserProject(
        user_id=user_id, project_name=name, source_type="github",
        source_url="https://github.com/a/b", created_at=now, updated_at=now,
    )
    session.add(p)
    session.commit()
    return p


def test_admin_proje_ekleyemez(client, session):
    _mk_user(session, "admin@x.com", role="admin")
    at = _token(client, "admin@x.com")
    r = client.post("/api/projects",
                    json={"name": "X", "github_url": "https://github.com/x/y"},
                    headers=_auth(at))
    assert r.status_code == 403


def test_admin_tum_projeleri_gorur(client, session):
    u = _mk_user(session, "u@x.com")
    _mk_user(session, "admin@x.com", role="admin")
    _add_project(session, u.id, "P1")

    at = _token(client, "admin@x.com")
    rows = client.get("/api/projects", headers=_auth(at)).json()
    assert len(rows) == 1 and rows[0]["name"] == "P1"
    assert "owner" in rows[0]  # admin sahibi de görür

    # kullanıcı yalnız kendininki (owner alanı yok)
    ut = _token(client, "u@x.com")
    urows = client.get("/api/projects", headers=_auth(ut)).json()
    assert len(urows) == 1 and "owner" not in urows[0]
