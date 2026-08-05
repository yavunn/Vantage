"""Şifremi unuttum akışı — kendi kendine sıfırlama.

TASARIM: bu kurulum on-prem ve mail altyapısı YOK. Uç, hesabı e-postayla
bulur, yeni bir geçici parolayı DOĞRUDAN uygular ve yanıtla birlikte döner;
arayüz bunu ekranda gösterir ve kullanıcının kendi e-postasına göndermesi
için bir mailto bağlantısı sunar. İkinci bir kimlik doğrulama adımı
(e-postaya gönderilen link/kod) YOKTUR — bu, kapalı/tek kuruluşluk bir araç
için bilinçli kabul edilmiş bir ödündür (bkz. app/api/auth.py::forgot_password
docstring'i).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, email, role="user", password="parola12345", is_active=True):
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    u = User(email=email.lower(), password_hash=hash_password(password), role=role,
             is_active=is_active, must_change_password=False, created_at=now, updated_at=now)
    session.add(u)
    session.commit()
    return u


def test_var_olan_hesap_yeni_parola_alir(client, session):
    u = _mk_user(session, "calisan@x.com")
    onceki_hash = u.password_hash

    r = client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["account_exists"] is True
    assert data["new_password"]
    assert len(data["new_password"]) >= 10

    session.expire_all()
    assert u.password_hash != onceki_hash
    assert u.must_change_password is True
    # Yeni parolayla giriş yapılabiliyor olmalı.
    login = client.post("/api/auth/login",
                        json={"email": "calisan@x.com", "password": data["new_password"]})
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True


def test_eski_parola_artik_calismaz(client, session):
    _mk_user(session, "calisan@x.com")
    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    r = client.post("/api/auth/login",
                    json={"email": "calisan@x.com", "password": "parola12345"})
    assert r.status_code == 401


def test_var_olmayan_eposta_parola_donmez(client, session):
    r = client.post("/api/auth/forgot-password", json={"email": "hayalet@x.com"})

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["account_exists"] is False
    assert data["new_password"] is None


def test_pasif_hesap_sifirlanmaz(client, session):
    _mk_user(session, "pasif@x.com", is_active=False)

    r = client.post("/api/auth/forgot-password", json={"email": "pasif@x.com"})

    assert r.json()["account_exists"] is False


def test_eski_oturumlar_dusurulur(client, session):
    _mk_user(session, "calisan@x.com")
    eski_auth = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "calisan@x.com", "password": "parola12345"}
    ).json()["access_token"]}
    assert client.get("/api/auth/me", headers=eski_auth).status_code == 200

    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    assert client.get("/api/auth/me", headers=eski_auth).status_code == 401


def test_talep_ucu_hiz_sinirli(client, session):
    """Sınırsız bırakılırsa toplu e-posta taraması ucuzlar."""
    from app.api.auth import RESET_RATE_MAX, _reset_attempts

    _reset_attempts.clear()
    kodlar = [
        client.post("/api/auth/forgot-password", json={"email": f"k{i}@x.com"}).status_code
        for i in range(RESET_RATE_MAX + 2)
    ]
    assert 429 in kodlar
    _reset_attempts.clear()


def test_kendi_kendine_sifirlama_denetim_kaydina_yazilir(client, session):
    from sqlalchemy import select

    from app.models import AuditLog

    _mk_user(session, "calisan@x.com")
    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    kayitlar = session.scalars(select(AuditLog)).all()
    kendi_sifirlama = [a for a in kayitlar if a.action == "self_reset_password"]
    assert len(kendi_sifirlama) == 1
    assert kendi_sifirlama[0].target_email == "calisan@x.com"
    assert kendi_sifirlama[0].actor_user_id is None  # kimliksiz uç — aktör yok


def test_password_requests_ucu_artik_yok(client, session):
    """Eski yönetici-kuyruğu tasarımı tamamen kaldırıldı."""
    _mk_user(session, "admin@x.com", role="admin")
    auth = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "admin@x.com", "password": "parola12345"}
    ).json()["access_token"]}
    assert client.get("/api/auth/password-requests", headers=auth).status_code == 404
