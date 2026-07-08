"""Faz 1 — kimlik doğrulama testleri.

- Login: doğru parola token verir, yanlış parola 401.
- Geçersiz / süresi dolmuş token 401.
- Refresh akışı; refresh token access yerine GEÇMEZ.
- JWT ile bireysel görünüm: kişi kendini görür, başkasını göremez (etik).
- Demo modu kapatılınca X-Dev-Id reddedilir (tek kimlik noktası JWT olur).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_team


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def make_user(session, email, password, developer=None, role="user"):
    from app.core.security import hash_password
    from app.models import User

    user = User(
        email=email,
        password_hash=hash_password(password),
        role=role,
        developer_id=developer.id if developer else None,
    )
    session.add(user)
    session.commit()
    return user


def login(client, email, password):
    return client.post("/api/auth/login", data={"username": email, "password": password})


def test_login_dogru_parola_token_verir(client, session):
    make_user(session, "a@corp.local", "gizli123")
    resp = login(client, "a@corp.local", "gizli123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_login_yanlis_parola_401(client, session):
    make_user(session, "a@corp.local", "gizli123")
    assert login(client, "a@corp.local", "yanlis").status_code == 401
    assert login(client, "yok@corp.local", "gizli123").status_code == 401


def test_parola_plain_saklanmaz(client, session):
    user = make_user(session, "a@corp.local", "gizli123")
    assert "gizli123" not in user.password_hash
    assert user.password_hash.startswith("$2")  # bcrypt


def test_gecersiz_token_401(client, session):
    team, repo, devs, mgr = make_team(session)
    resp = client.get(
        f"/api/developers/{devs[0].id}/summary",
        headers={"Authorization": "Bearer bozuk.token.degeri"},
    )
    assert resp.status_code == 401


def test_suresi_dolmus_token_401(client, session):
    from app.core.security import create_access_token

    team, repo, devs, mgr = make_team(session)
    user = make_user(session, "a@corp.local", "gizli123", developer=devs[0])
    expired = create_access_token(user.id, expires_minutes=-5)
    resp = client.get(
        f"/api/developers/{devs[0].id}/summary",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert resp.status_code == 401


def test_jwt_ile_bireysel_gorunum(client, session):
    """JWT → User → Developer zinciri; etik kural aynen geçerli."""
    team, repo, devs, mgr = make_team(session)
    make_user(session, "dev1@corp.local", "gizli123", developer=devs[0])
    token = login(client, "dev1@corp.local", "gizli123").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Kendisi: 200
    resp = client.get(f"/api/developers/{devs[0].id}/summary", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["developer"]["id"] == devs[0].id
    # Başkası: 403 (etik çerçeve JWT'de de delinmez)
    resp = client.get(f"/api/developers/{devs[1].id}/summary", headers=headers)
    assert resp.status_code == 403


def test_refresh_akisi(client, session):
    team, repo, devs, mgr = make_team(session)
    make_user(session, "dev1@corp.local", "gizli123", developer=devs[0])
    tokens = login(client, "dev1@corp.local", "gizli123").json()
    resp = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    new_access = resp.json()["access_token"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {new_access}"}).json()
    assert me["authenticated"] is True and me["id"] == devs[0].id


def test_refresh_token_access_yerine_gecmez(client, session):
    team, repo, devs, mgr = make_team(session)
    make_user(session, "dev1@corp.local", "gizli123", developer=devs[0])
    tokens = login(client, "dev1@corp.local", "gizli123").json()
    resp = client.get(
        f"/api/developers/{devs[0].id}/summary",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )
    assert resp.status_code == 401
    # access token da refresh ucunda geçmez
    resp = client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


def test_demo_modu_kapaliyken_x_dev_id_reddedilir(client, session, app_env):
    """Prod yolu: demo_auth_enabled=false → X-Dev-Id yok sayılır, yalnız JWT."""
    from app.core.config import reset_config_cache

    team, repo, devs, mgr = make_team(session)
    text = app_env.read_text(encoding="utf-8").replace(
        "anonymize_individuals: false",
        "anonymize_individuals: false\n  demo_auth_enabled: false",
    )
    app_env.write_text(text, encoding="utf-8")
    reset_config_cache()

    resp = client.get(f"/api/developers/{devs[0].id}/summary",
                      headers={"X-Dev-Id": str(devs[0].id)})
    assert resp.status_code == 401
    # JWT ile aynı istek çalışır
    make_user(session, "dev1@corp.local", "gizli123", developer=devs[0])
    token = login(client, "dev1@corp.local", "gizli123").json()["access_token"]
    resp = client.get(f"/api/developers/{devs[0].id}/summary",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
