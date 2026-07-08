"""Faz 2 — admin uçları testleri.

- /api/admin/* yalnız admin: user 403, kimliksiz 401.
- Soft delete: listeden düşer, login engellenir, kayıt durur.
- Rol değişimi; admin kendi hesabını silemez.
- Etik guardrail: kullanıcı listesi ve stats kişi metriği İÇERMEZ.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_team
from tests.test_auth import login, make_user


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def auth_headers(client, session, email="admin@corp.local", password="admin123",
                 role="admin"):
    make_user(session, email, password, role=role)
    token = login(client, email, password).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_kimliksiz_admin_ucu_401(client, session):
    assert client.get("/api/admin/users").status_code == 401


def test_user_rolu_admin_ucunda_403(client, session):
    headers = auth_headers(client, session, "u@corp.local", "gizli123", role="user")
    assert client.get("/api/admin/users").status_code == 401
    assert client.get("/api/admin/users", headers=headers).status_code == 403
    assert client.get("/api/admin/stats", headers=headers).status_code == 403
    assert client.delete("/api/admin/users/1", headers=headers).status_code == 403


def test_admin_kullanici_listesi(client, session):
    headers = auth_headers(client, session)
    make_user(session, "u@corp.local", "gizli123", role="user")
    body = client.get("/api/admin/users", headers=headers).json()
    emails = [u["email"] for u in body]
    assert "admin@corp.local" in emails and "u@corp.local" in emails
    # Etik: hesap listesinde metrik alanı olamaz (liste+metrik = leaderboard)
    assert all("value" not in u and "metrics" not in u for u in body)


def test_soft_delete(client, session):
    headers = auth_headers(client, session)
    victim = make_user(session, "u@corp.local", "gizli123", role="user")
    resp = client.delete(f"/api/admin/users/{victim.id}", headers=headers)
    assert resp.status_code == 200
    # Listeden düşer
    emails = [u["email"] for u in client.get("/api/admin/users", headers=headers).json()]
    assert "u@corp.local" not in emails
    # Login engellenir
    assert login(client, "u@corp.local", "gizli123").status_code == 401
    # Kayıt DB'de durur (soft)
    from app.models import User

    session.expire_all()
    assert session.get(User, victim.id) is not None
    assert session.get(User, victim.id).is_active is False


def test_admin_kendi_hesabini_silemez(client, session):
    headers = auth_headers(client, session)
    from sqlalchemy import select

    from app.models import User

    admin = session.scalars(select(User).where(User.email == "admin@corp.local")).first()
    assert client.delete(f"/api/admin/users/{admin.id}", headers=headers).status_code == 400


def test_rol_degisimi(client, session):
    headers = auth_headers(client, session)
    u = make_user(session, "u@corp.local", "gizli123", role="user")
    resp = client.put(f"/api/admin/users/{u.id}", headers=headers, json={"role": "admin"})
    assert resp.status_code == 200 and resp.json()["role"] == "admin"
    assert client.put(f"/api/admin/users/{u.id}", headers=headers,
                      json={"role": "patron"}).status_code == 422
    # Yeni admin, admin ucuna erişebilir
    token = login(client, "u@corp.local", "gizli123").json()["access_token"]
    assert client.get("/api/admin/users",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_stats_agregat_kisiye_inmez(client, session):
    headers = auth_headers(client, session)
    make_team(session)
    body = client.get("/api/admin/stats", headers=headers).json()
    assert set(body) == {"total_users", "repo_count", "commits_last_7d",
                         "overall_health_pct", "health_metric_count"}
    # Metrik yoksa sağlık yüzdesi uydurulmaz (İlke A)
    assert body["overall_health_pct"] is None
    assert body["repo_count"] == 1


def test_me_hesap_bilgisi_doner(client, session):
    team, repo, devs, mgr = make_team(session)
    make_user(session, "dev1@corp.local", "gizli123", developer=devs[0])
    token = login(client, "dev1@corp.local", "gizli123").json()["access_token"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["account"] == {"email": "dev1@corp.local", "role": "user"}
    assert me["id"] == devs[0].id
    # Developer'a bağlı olmayan admin de authenticated'dır
    headers = auth_headers(client, session)
    me = client.get("/api/me", headers=headers).json()
    assert me["authenticated"] is True
    assert me["account"]["role"] == "admin"
    assert "id" not in me
