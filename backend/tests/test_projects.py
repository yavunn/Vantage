"""Faz 3 — proje bağlama testleri.

- Token hiçbir response'ta plain görünmez; DB'de yalnız şifreli durur.
- Sahiplik: başkasının projesi görünmez/silinemez (404 — varlık sızmaz).
- Kimliksiz istek 401.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.test_auth import login, make_user


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


PLAIN_TOKEN = "ghp_cokgizlitoken123"


def user_headers(client, session, email="u@corp.local", password="gizli123"):
    make_user(session, email, password)
    token = login(client, email, password).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_project(client, headers, name="repo-a"):
    return client.post(
        "/api/user/projects",
        headers=headers,
        json={
            "project_name": name,
            "source_type": "github",
            "source_url": "https://github.com/corp/repo-a",
            "token": PLAIN_TOKEN,
        },
    )


def test_kimliksiz_401(client, session):
    assert client.get("/api/user/projects").status_code == 401
    assert client.post("/api/user/projects", json={}).status_code == 401


def test_olusturma_ve_liste_token_sizdirmaz(client, session):
    headers = user_headers(client, session)
    resp = create_project(client, headers)
    assert resp.status_code == 201
    assert PLAIN_TOKEN not in json.dumps(resp.json())
    body = client.get("/api/user/projects", headers=headers).json()
    assert len(body) == 1
    assert body[0]["connected"] is True
    assert body[0]["last_run_at"] is None
    dump = json.dumps(body)
    assert PLAIN_TOKEN not in dump and "token" not in dump and "credential" not in dump


def test_token_dbde_sifreli(client, session):
    from sqlalchemy import select

    from app.core.crypto import decrypt_secret
    from app.models import ProjectCredential

    headers = user_headers(client, session)
    create_project(client, headers)
    cred = session.scalars(select(ProjectCredential)).first()
    assert cred is not None
    assert PLAIN_TOKEN not in cred.encrypted_value  # plain yazılmadı
    assert decrypt_secret(cred.encrypted_value) == PLAIN_TOKEN  # geri çözülebilir


def test_gecersiz_source_type_422(client, session):
    headers = user_headers(client, session)
    resp = client.post(
        "/api/user/projects",
        headers=headers,
        json={"project_name": "x", "source_type": "svn",
              "source_url": "https://svn.local/x", "token": "t"},
    )
    assert resp.status_code == 422


def test_baskasinin_projesi_gorunmez_silinemez(client, session):
    owner = user_headers(client, session, "owner@corp.local")
    project_id = create_project(client, owner).json()["id"]
    other = user_headers(client, session, "other@corp.local")
    # Listede yok
    assert client.get("/api/user/projects", headers=other).json() == []
    # Silme: 404 (403 değil — varlık bilgisi de sızmaz)
    assert client.delete(f"/api/user/projects/{project_id}", headers=other).status_code == 404
    # Sahip silebilir; credential da gider
    assert client.delete(f"/api/user/projects/{project_id}", headers=owner).status_code == 200
    from sqlalchemy import select

    from app.models import ProjectCredential, UserProject

    assert session.scalars(select(UserProject)).first() is None
    assert session.scalars(select(ProjectCredential)).first() is None
