"""Şifremi unuttum akışı + sunucu tarafı dil desteği.

TASARIM: kurulum on-prem ve mail altyapısı YOK. Token'lı sıfırlama linki
göndermek, var olmayan bir SMTP'yi varmış gibi kurgulamak olurdu. Talep bir
kuyruğa düşer; yönetici/İK zaten var olan sıfırlama akışını kullanır.

EN KRİTİK GÜVENLİK KURALI: uç, e-postanın sistemde olup olmadığını SIZDIRMAZ.
Aksi hâlde form bir hesap numaralandırma aracına dönerdi.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, email, role="user", password="parola12345"):
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    u = User(email=email.lower(), password_hash=hash_password(password), role=role,
             is_active=True, must_change_password=False, created_at=now, updated_at=now)
    session.add(u)
    session.commit()
    return u


def _token(client, email, password="parola12345"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- kullanıcı tarafı ---------------------------------------------------------

def test_talep_kimlik_gerektirmez(client, session):
    _mk_user(session, "calisan@x.com")
    r = client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_var_olmayan_eposta_ayni_yaniti_alir(client, session):
    """EN KRİTİK: yanıt hesabın varlığını sızdırmamalı."""
    _mk_user(session, "gercek@x.com")

    var = client.post("/api/auth/forgot-password", json={"email": "gercek@x.com"})
    yok = client.post("/api/auth/forgot-password", json={"email": "hayalet@x.com"})

    assert var.status_code == yok.status_code == 200
    assert var.json() == yok.json()


def test_talep_kaydedilir_ve_hesap_durumu_yalniz_yoneticide_gorunur(client, session):
    from sqlalchemy import select

    from app.models import PasswordResetRequest

    _mk_user(session, "calisan@x.com")
    client.post("/api/auth/forgot-password",
                json={"email": "calisan@x.com", "note": "telefonum yanımda değil"})

    rows = session.scalars(select(PasswordResetRequest)).all()
    assert len(rows) == 1
    assert rows[0].email == "calisan@x.com"
    assert rows[0].note == "telefonum yanımda değil"
    assert rows[0].user_id is not None      # yönetici hesabın var olduğunu görür
    assert rows[0].status == "pending"


def test_ayni_eposta_icin_ikinci_talep_kuyrugu_sismez(client, session):
    from sqlalchemy import select

    from app.models import PasswordResetRequest

    _mk_user(session, "calisan@x.com")
    for _ in range(3):
        client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    assert len(session.scalars(select(PasswordResetRequest)).all()) == 1


def test_talep_ucu_hiz_sinirli(client, session):
    """Sınırsız bırakılırsa hem yöneticinin kuyruğu spam'lenir hem de
    e-posta numaralandırma denemesi ucuzlar."""
    from app.api.auth import RESET_RATE_MAX, _reset_attempts

    _reset_attempts.clear()
    kodlar = [
        client.post("/api/auth/forgot-password", json={"email": f"k{i}@x.com"}).status_code
        for i in range(RESET_RATE_MAX + 2)
    ]
    assert 429 in kodlar
    _reset_attempts.clear()


# --- yönetici tarafı ----------------------------------------------------------

def test_talep_listesi_admin_disina_kapali(client, session):
    _mk_user(session, "calisan@x.com")
    auth = _token(client, "calisan@x.com")
    assert client.get("/api/auth/password-requests", headers=auth).status_code == 403


def test_admin_talepleri_gorur(client, session):
    _mk_user(session, "calisan@x.com")
    _mk_user(session, "admin@x.com", role="admin")
    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})
    client.post("/api/auth/forgot-password", json={"email": "hicyok@x.com"})

    rows = client.get("/api/auth/password-requests",
                      headers=_token(client, "admin@x.com")).json()

    assert len(rows) == 2
    by_email = {r["email"]: r for r in rows}
    assert by_email["calisan@x.com"]["account_exists"] is True
    # Yanlış yazılmış adres de bilgidir: yönetici bunu ayırt edebilmeli.
    assert by_email["hicyok@x.com"]["account_exists"] is False


def test_talep_kapatmak_parolayi_DEGISTIRMEZ(client, session):
    """Tasarım kararı: iki işi tek uca bindirmek, 'listeyi temizliyorum' derken
    farkında olmadan parola sıfırlamaya yol açardı."""
    u = _mk_user(session, "calisan@x.com")
    _mk_user(session, "admin@x.com", role="admin")
    onceki_hash = u.password_hash
    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})
    admin_auth = _token(client, "admin@x.com")
    req_id = client.get("/api/auth/password-requests", headers=admin_auth).json()[0]["id"]

    r = client.patch(f"/api/auth/password-requests/{req_id}",
                     json={"status": "resolved"}, headers=admin_auth)

    assert r.status_code == 200
    session.expire_all()
    assert u.password_hash == onceki_hash
    # Kullanıcı hâlâ eski parolasıyla girebiliyor olmalı.
    assert client.post("/api/auth/login",
                       json={"email": "calisan@x.com", "password": "parola12345"}).status_code == 200


def test_kapatilmis_talep_tekrar_kapatilamaz(client, session):
    _mk_user(session, "calisan@x.com")
    _mk_user(session, "admin@x.com", role="admin")
    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})
    auth = _token(client, "admin@x.com")
    req_id = client.get("/api/auth/password-requests", headers=auth).json()[0]["id"]

    assert client.patch(f"/api/auth/password-requests/{req_id}",
                        json={"status": "resolved"}, headers=auth).status_code == 200
    assert client.patch(f"/api/auth/password-requests/{req_id}",
                        json={"status": "dismissed"}, headers=auth).status_code == 409


def test_gecersiz_karar_reddedilir(client, session):
    _mk_user(session, "calisan@x.com")
    _mk_user(session, "admin@x.com", role="admin")
    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})
    auth = _token(client, "admin@x.com")
    req_id = client.get("/api/auth/password-requests", headers=auth).json()[0]["id"]

    r = client.patch(f"/api/auth/password-requests/{req_id}",
                     json={"status": "silindi"}, headers=auth)
    assert r.status_code == 422


def test_karar_denetim_kaydina_yazilir(client, session):
    from sqlalchemy import select

    from app.models import AuditLog

    _mk_user(session, "calisan@x.com")
    _mk_user(session, "admin@x.com", role="admin")
    client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})
    auth = _token(client, "admin@x.com")
    req_id = client.get("/api/auth/password-requests", headers=auth).json()[0]["id"]
    client.patch(f"/api/auth/password-requests/{req_id}",
                 json={"status": "resolved"}, headers=auth)

    kayitlar = [a.action for a in session.scalars(select(AuditLog))]
    assert "password_request_resolved" in kayitlar


# --- sunucu tarafı dil --------------------------------------------------------

def test_dil_basligi_metrik_adlarini_cevirir(client, session):
    """Arayüzü tek başına çevirmek panoyu yarı Türkçe bırakırdı: metrik adları,
    açıklamaları ve durum etiketleri API'den geliyor."""
    from app.core.config import get_config
    from app.metrics.engine import compute_all
    from tests.conftest import make_team

    team, repo, devs, _ = make_team(session)
    compute_all(session, get_config())
    _mk_user(session, "admin@x.com", role="admin")
    auth = _token(client, "admin@x.com")

    tr = client.get(f"/api/teams/{team.id}/summary",
                    headers={**auth, "Accept-Language": "tr"}).json()
    en = client.get(f"/api/teams/{team.id}/summary",
                    headers={**auth, "Accept-Language": "en-US,en;q=0.9"}).json()

    tr_adlar = {m["key"]: m["name"] for m in tr["metrics"]}
    en_adlar = {m["key"]: m["name"] for m in en["metrics"]}
    assert tr_adlar["deployment_frequency"] == "Teslim Sıklığı"
    assert en_adlar["deployment_frequency"] == "Delivery Frequency"

    tr_etiket = {m["key"]: m["status_label"] for m in tr["metrics"]}
    en_etiket = {m["key"]: m["status_label"] for m in en["metrics"]}
    assert "Veri yetersiz" in tr_etiket.values()
    assert "Not enough data" in en_etiket.values()


def test_desteklenmeyen_dil_turkceye_duser(client, session):
    from app.core.i18n import normalize_lang

    assert normalize_lang("de-DE,de;q=0.9") == "tr"
    assert normalize_lang(None) == "tr"
    assert normalize_lang("en-GB") == "en"


def test_ingilizce_durum_etiketi_ceza_dili_kullanmaz(client, session):
    """Etik çerçeve çeviride de korunmalı: kırmızı bir ceza değil, destek
    çağrısıdır. 'bad' / 'fail' gibi bir performans dili kullanılmaz."""
    from app.core.i18n import status_labels

    en = status_labels("en")
    assert "support" in en["red"].lower()
    for kotu in ("bad", "fail", "poor"):
        assert kotu not in " ".join(en.values()).lower()
