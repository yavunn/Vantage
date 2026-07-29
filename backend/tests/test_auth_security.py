"""Güvenlik: dashboard JWT zorunluluğu + parola değişince oturum geçersizleşmesi."""
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


def _login(client, email, password="parola1"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_dashboard_tokensiz_401(client, session):
    _mk_user(session, "u@x.com")
    # Kimlik yok → 401 (public değil).
    assert client.get("/api/directory").status_code == 401
    assert client.get("/api/teams").status_code == 401
    # Geçerli token → geçer.
    t = _login(client, "u@x.com")
    assert client.get("/api/teams", headers=_auth(t)).status_code == 200


def test_anotasyon_okumasi_tokensiz_401(client, session):
    """Anotasyon etiketleri ("ödeme servisi çöktü", sürüm adları) şirket içi
    bilgidir. Bu uç bir dönem router bağımlılığı olmadan public kalmıştı."""
    _mk_user(session, "u@x.com")
    assert client.get("/api/annotations").status_code == 401
    assert client.get("/api/annotations?team_id=1").status_code == 401
    t = _login(client, "u@x.com")
    assert client.get("/api/annotations", headers=_auth(t)).status_code == 200


def test_anotasyon_yazma_duz_kullaniciya_kapali(client, session):
    """Okuma herkese açıldı diye yazma da açılmasın: düz kullanıcı 403 almalı."""
    _mk_user(session, "u@x.com")
    t = _login(client, "u@x.com")
    r = client.post("/api/annotations",
                    headers=_auth(t),
                    json={"date": "2026-01-01", "label": "Yılbaşı", "kind": "holiday"})
    assert r.status_code == 403, r.text
    assert client.delete("/api/annotations/1", headers=_auth(t)).status_code == 403


def test_parola_degisince_eski_token_gecersiz(client, session):
    _mk_user(session, "u@x.com", password="eski123")
    t_old = _login(client, "u@x.com", "eski123")
    # Eski token çalışıyor
    assert client.get("/api/auth/me", headers=_auth(t_old)).status_code == 200
    # Parola değiştir → yeni token döner
    r = client.post("/api/auth/change-password",
                    headers=_auth(t_old),
                    json={"current_password": "eski123", "new_password": "yeniParola456"})
    assert r.status_code == 200, r.text
    t_new = r.json()["access_token"]
    # ESKİ token artık geçersiz (token_version arttı) → 401
    assert client.get("/api/auth/me", headers=_auth(t_old)).status_code == 401
    # YENİ token geçerli
    assert client.get("/api/auth/me", headers=_auth(t_new)).status_code == 200


def test_admin_parola_sifirlayinca_hedefin_token_dus(client, session):
    _mk_user(session, "admin@x.com", role="admin")
    target = _mk_user(session, "t@x.com", password="eski123")
    t_target = _login(client, "t@x.com", "eski123")
    assert client.get("/api/auth/me", headers=_auth(t_target)).status_code == 200
    at = _login(client, "admin@x.com")
    r = client.post(f"/api/auth/employees/{target.id}/password",
                    headers=_auth(at), json={"new_password": "resetParola789"})
    assert r.status_code == 200, r.text
    # Hedefin eski oturumu düşer.
    assert client.get("/api/auth/me", headers=_auth(t_target)).status_code == 401
