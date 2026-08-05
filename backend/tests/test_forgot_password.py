"""Şifremi unuttum akışı — yeni parola KULLANICIYA E-POSTAYLA gider.

TASARIM: parola ekranda gösterilmez. Postayı alabilmek, isteği gerçekten
hesap sahibinin yaptığını doğrulayan tek adımdır; parolayı yanıtta döndürmek
e-posta adresini bilen herkese hesabı açardı.

SIRA KRİTİK: önce mail gönderilir, ancak başarılı olursa parola kaydedilir.
Tersi sırada, mail gidemeyince kullanıcı yeni parolayı hiç öğrenemeden
hesabından kilitlenirdi.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def smtp(monkeypatch):
    """SMTP'yi yapılandırılmış say ve gönderilen mailleri yakala."""
    gonderilenler: list[dict] = []

    def sahte_send(to, subject, body, cfg=None):
        gonderilenler.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr("app.services.mailer.is_configured", lambda cfg=None: True)
    monkeypatch.setattr("app.services.mailer.send_email", sahte_send)
    return gonderilenler


def _mk_user(session, email, role="user", password="parola12345", is_active=True):
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    u = User(email=email.lower(), password_hash=hash_password(password), role=role,
             is_active=is_active, must_change_password=False, created_at=now, updated_at=now)
    session.add(u)
    session.commit()
    return u


def _yeni_parola(mail_body: str) -> str:
    """Mail gövdesindeki geçici parolayı ayıklar (girintili tek satır)."""
    for satir in mail_body.splitlines():
        if satir.startswith("    ") and satir.strip():
            return satir.strip()
    raise AssertionError(f"Mail gövdesinde parola bulunamadı:\n{mail_body}")


def test_yeni_parola_kullaniciya_maillenir(client, session, smtp):
    u = _mk_user(session, "calisan@x.com")
    onceki_hash = u.password_hash

    r = client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert len(smtp) == 1
    assert smtp[0]["to"] == "calisan@x.com"

    session.expire_all()
    assert u.password_hash != onceki_hash
    assert u.must_change_password is True
    # Mailde giden parola gerçekten çalışmalı.
    login = client.post("/api/auth/login",
                        json={"email": "calisan@x.com",
                              "password": _yeni_parola(smtp[0]["body"])})
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True


def test_parola_yanitta_DONMEZ(client, session, smtp):
    """En kritik kural: parola yalnız posta kutusuna gider."""
    _mk_user(session, "calisan@x.com")

    govde = client.post("/api/auth/forgot-password",
                        json={"email": "calisan@x.com"}).json()

    assert "new_password" not in govde
    # Gönderilen parola yanıtın hiçbir yerinde geçmemeli.
    assert _yeni_parola(smtp[0]["body"]) not in str(govde)


def test_var_olmayan_eposta_ayni_yaniti_alir(client, session, smtp):
    """Hesap numaralandırma: yanıt hesabın varlığını sızdırmamalı."""
    _mk_user(session, "gercek@x.com")

    var = client.post("/api/auth/forgot-password", json={"email": "gercek@x.com"})
    yok = client.post("/api/auth/forgot-password", json={"email": "hayalet@x.com"})

    assert var.status_code == yok.status_code == 200
    assert var.json() == yok.json()
    # Ama mail yalnız gerçek hesaba gitmiş olmalı.
    assert [m["to"] for m in smtp] == ["gercek@x.com"]


def test_eski_parola_artik_calismaz(client, session, smtp):
    _mk_user(session, "calisan@x.com")
    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    r = client.post("/api/auth/login",
                    json={"email": "calisan@x.com", "password": "parola12345"})
    assert r.status_code == 401


def test_pasif_hesap_sifirlanmaz(client, session, smtp):
    _mk_user(session, "pasif@x.com", is_active=False)

    r = client.post("/api/auth/forgot-password", json={"email": "pasif@x.com"})

    assert r.status_code == 200      # yanıt yine aynı (numaralandırma yok)
    assert smtp == []                 # ama mail gitmez


def test_eski_oturumlar_dusurulur(client, session, smtp):
    _mk_user(session, "calisan@x.com")
    eski_auth = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "calisan@x.com", "password": "parola12345"}
    ).json()["access_token"]}
    assert client.get("/api/auth/me", headers=eski_auth).status_code == 200

    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    assert client.get("/api/auth/me", headers=eski_auth).status_code == 401


def test_smtp_kapaliyken_sifirlama_da_kapali(client, session, monkeypatch):
    """Parolayı değiştirip iletemezsek kullanıcıyı kilitleriz — hiç değiştirme."""
    monkeypatch.setattr("app.services.mailer.is_configured", lambda cfg=None: False)
    u = _mk_user(session, "calisan@x.com")
    onceki_hash = u.password_hash

    r = client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    assert r.status_code == 503
    session.expire_all()
    assert u.password_hash == onceki_hash
    # Kullanıcı hâlâ eski parolasıyla girebilmeli.
    assert client.post("/api/auth/login",
                       json={"email": "calisan@x.com", "password": "parola12345"}).status_code == 200


def test_mail_gonderilemezse_parola_DEGISMEZ(client, session, monkeypatch):
    """SIRA KRİTİK: mail patlarsa kullanıcı eski parolasıyla kalmalı."""
    from app.services.mailer import MailError

    def patla(to, subject, body, cfg=None):
        raise MailError("relay reddetti")

    monkeypatch.setattr("app.services.mailer.is_configured", lambda cfg=None: True)
    monkeypatch.setattr("app.services.mailer.send_email", patla)
    u = _mk_user(session, "calisan@x.com")
    onceki_hash = u.password_hash

    r = client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    assert r.status_code == 502
    # Sunucu adı/kimlik ipucu kullanıcıya sızmamalı.
    assert "relay reddetti" not in r.text
    session.expire_all()
    assert u.password_hash == onceki_hash
    assert client.post("/api/auth/login",
                       json={"email": "calisan@x.com", "password": "parola12345"}).status_code == 200


def test_talep_ucu_hiz_sinirli(client, session, smtp):
    """Sınırsız bırakılırsa toplu e-posta taraması ucuzlar."""
    from app.api.auth import RESET_RATE_MAX, _reset_attempts

    _reset_attempts.clear()
    kodlar = [
        client.post("/api/auth/forgot-password", json={"email": f"k{i}@x.com"}).status_code
        for i in range(RESET_RATE_MAX + 2)
    ]
    assert 429 in kodlar
    _reset_attempts.clear()


def test_kendi_kendine_sifirlama_denetim_kaydina_yazilir(client, session, smtp):
    from sqlalchemy import select

    from app.models import AuditLog

    _mk_user(session, "calisan@x.com")
    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    kayitlar = [a for a in session.scalars(select(AuditLog)) if a.action == "self_reset_password"]
    assert len(kayitlar) == 1
    assert kayitlar[0].target_email == "calisan@x.com"
    assert kayitlar[0].actor_user_id is None  # kimliksiz uç — aktör yok
    # Parolanın kendisi ASLA kaydedilmez.
    assert _yeni_parola(smtp[0]["body"]) not in str(kayitlar[0].detail or "")


def test_password_requests_ucu_artik_yok(client, session):
    """Eski yönetici-kuyruğu tasarımı tamamen kaldırıldı."""
    _mk_user(session, "admin@x.com", role="admin")
    auth = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "admin@x.com", "password": "parola12345"}
    ).json()["access_token"]}
    assert client.get("/api/auth/password-requests", headers=auth).status_code == 404
