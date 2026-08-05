"""Şifremi unuttum akışı — 3 adım: kod iste → kodu doğrula → parolayı belirle.

Mail gönderimi test boyunca sahtelenir; gerçek ağ çağrısı yapılmaz. Kod
yalnızca MAİLE gittiği için testler kodu mail gövdesinden okur — uçların
kodu yanıtta sızdırmadığını da böylece doğrulamış oluyoruz.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def mails(monkeypatch):
    """Gönderilen mailleri yakalar; SMTP/HTTP'ye çıkmaz."""
    kutu: list[dict] = []

    def sahte_send(to, subject, html):
        kutu.append({"to": to, "subject": subject, "html": html})

    monkeypatch.setattr("app.services.mailer.is_configured", lambda: True)
    monkeypatch.setattr("app.services.mailer.send_email", sahte_send)
    return kutu


def _mk_user(session, email="calisan@x.com", password="parola12345", is_active=True):
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    u = User(email=email.lower(), password_hash=hash_password(password), role="user",
             is_active=is_active, must_change_password=False, created_at=now, updated_at=now)
    session.add(u)
    session.commit()
    return u


def _kod(mail: dict) -> str:
    """Mail gövdesindeki 6 haneli kodu ayıklar."""
    m = re.search(r">(\d{6})<", mail["html"])
    assert m, f"Mailde 6 haneli kod bulunamadı:\n{mail['html'][:400]}"
    return m.group(1)


def _kod_iste(client, email="calisan@x.com"):
    r = client.post("/api/auth/forgot-password", json={"email": email})
    assert r.status_code == 200, r.text
    return r


def _dogrula(client, code, email="calisan@x.com"):
    return client.post("/api/auth/verify-reset-code", json={"email": email, "code": code})


# --- 1. adım: kod iste --------------------------------------------------------

def test_kod_maille_gider_ve_yanitta_SIZMAZ(client, session, mails):
    _mk_user(session)

    r = _kod_iste(client)

    assert len(mails) == 1
    assert mails[0]["to"] == "calisan@x.com"
    kod = _kod(mails[0])
    assert len(kod) == 6 and kod.isdigit()
    # En kritik kural: kod yalnız posta kutusuna gider.
    assert kod not in r.text


def test_kod_veritabaninda_DUZ_METIN_tutulmaz(client, session, mails):
    from sqlalchemy import select

    from app.models import PasswordResetCode

    _mk_user(session)
    _kod_iste(client)
    kod = _kod(mails[0])

    kayit = session.scalars(select(PasswordResetCode)).one()
    assert kayit.code_hash != kod
    assert len(kayit.code_hash) == 64  # sha256 hexdigest


def test_bastaki_sifirlar_korunur(client, session, mails, monkeypatch):
    """000123 gibi kodlar 123'e düşmemeli — string olarak saklanmalı."""
    monkeypatch.setattr("app.api.auth._secrets.randbelow", lambda n: 123)
    _mk_user(session)

    _kod_iste(client)

    assert _kod(mails[0]) == "000123"


def test_var_olmayan_eposta_ayni_yaniti_alir(client, session, mails):
    """Kullanıcı numaralandırma: yanıt hesabın varlığını sızdırmamalı."""
    _mk_user(session, email="gercek@x.com")

    var = client.post("/api/auth/forgot-password", json={"email": "gercek@x.com"})
    yok = client.post("/api/auth/forgot-password", json={"email": "hayalet@x.com"})

    assert var.status_code == yok.status_code == 200
    assert var.json() == yok.json()
    assert [m["to"] for m in mails] == ["gercek@x.com"]  # mail yalnız gerçeğe gitti


def test_yeni_kod_isteyince_eskisi_gecersizlesir(client, session, mails):
    _mk_user(session)
    _kod_iste(client)
    eski_kod = _kod(mails[0])
    _kod_iste(client)

    assert _dogrula(client, eski_kod).status_code == 400
    assert _dogrula(client, _kod(mails[1])).status_code == 200


def test_mail_gonderilemezse_kod_KAYDEDILMEZ(client, session, monkeypatch):
    """Sıra kritik: mail patlarsa kullanıcı eline geçmeyecek kodu beklemesin."""
    from sqlalchemy import select

    from app.models import PasswordResetCode
    from app.services.mailer import MailError

    def patla(to, subject, html):
        raise MailError("saglayici reddetti")

    monkeypatch.setattr("app.services.mailer.is_configured", lambda: True)
    monkeypatch.setattr("app.services.mailer.send_email", patla)
    _mk_user(session)

    r = client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"})

    assert r.status_code == 502
    assert "saglayici reddetti" not in r.text  # sağlayıcı ayrıntısı sızmaz
    assert session.scalars(select(PasswordResetCode)).all() == []


def test_mail_yapilandirilmamissa_503(client, session, monkeypatch):
    monkeypatch.setattr("app.services.mailer.is_configured", lambda: False)
    _mk_user(session)

    assert client.post("/api/auth/forgot-password",
                       json={"email": "calisan@x.com"}).status_code == 503


# --- 2. adım: kodu doğrula ----------------------------------------------------

def test_dogru_kod_reset_token_dondurur(client, session, mails):
    _mk_user(session)
    _kod_iste(client)

    r = _dogrula(client, _kod(mails[0]))

    assert r.status_code == 200
    assert r.json()["reset_token"]


def test_hatali_kod_reddedilir(client, session, mails):
    _mk_user(session)
    _kod_iste(client)

    r = _dogrula(client, "000000" if _kod(mails[0]) != "000000" else "111111")

    assert r.status_code == 400


def test_suresi_dolmus_kod_reddedilir(client, session, mails):
    from sqlalchemy import select

    from app.models import PasswordResetCode

    _mk_user(session)
    _kod_iste(client)
    kod = _kod(mails[0])
    kayit = session.scalars(select(PasswordResetCode)).one()
    kayit.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.commit()

    assert _dogrula(client, kod).status_code == 400


def test_deneme_limiti_asilinca_kod_iptal_olur(client, session, mails):
    """5 hatalı denemeden sonra DOĞRU kod bile artık kabul edilmemeli."""
    from app.api.auth import RESET_MAX_ATTEMPTS

    _mk_user(session)
    _kod_iste(client)
    dogru = _kod(mails[0])
    yanlis = "000000" if dogru != "000000" else "111111"

    for _ in range(RESET_MAX_ATTEMPTS):
        assert _dogrula(client, yanlis).status_code == 400

    assert _dogrula(client, dogru).status_code == 400


def test_kod_tekrar_kullanilamaz(client, session, mails):
    """Parola sıfırlandıktan sonra aynı kod yeniden doğrulanamaz."""
    _mk_user(session)
    _kod_iste(client)
    kod = _kod(mails[0])
    token = _dogrula(client, kod).json()["reset_token"]
    client.post("/api/auth/reset-password",
                json={"reset_token": token, "new_password": "yeniParola123"})

    assert _dogrula(client, kod).status_code == 400


def test_hata_mesajlari_adim_sizdirmaz(client, session, mails):
    """Hatalı kod / süresi dolmuş / hiç kod yok — hepsi AYNI mesaj."""
    _mk_user(session)
    hic_kod_yok = _dogrula(client, "123456").json()["detail"]
    _kod_iste(client)
    dogru = _kod(mails[0])
    hatali = _dogrula(client, "000000" if dogru != "000000" else "111111").json()["detail"]

    assert hic_kod_yok == hatali


# --- 3. adım: parolayı belirle ------------------------------------------------

def test_basarili_akis_ucdan_uca(client, session, mails):
    u = _mk_user(session)
    onceki_hash = u.password_hash

    _kod_iste(client)
    token = _dogrula(client, _kod(mails[0])).json()["reset_token"]
    r = client.post("/api/auth/reset-password",
                    json={"reset_token": token, "new_password": "yeniParola123"})

    assert r.status_code == 200
    session.expire_all()
    assert u.password_hash != onceki_hash
    # Kullanıcı parolayı KENDİ seçti — tekrar değiştirmesi istenmemeli.
    assert u.must_change_password is False
    # Yeni parolayla giriş çalışmalı, eskisi çalışmamalı.
    assert client.post("/api/auth/login",
                       json={"email": "calisan@x.com", "password": "yeniParola123"}
                       ).status_code == 200
    assert client.post("/api/auth/login",
                       json={"email": "calisan@x.com", "password": "parola12345"}
                       ).status_code == 401
    # Bilgilendirme maili gitmeli (kod maili + değişiklik maili).
    assert len(mails) == 2
    assert "değiştirildi" in mails[1]["subject"]


def test_reset_diger_oturumlari_sonlandirir(client, session, mails):
    _mk_user(session)
    eski = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "calisan@x.com", "password": "parola12345"}
    ).json()["access_token"]}
    assert client.get("/api/auth/me", headers=eski).status_code == 200

    _kod_iste(client)
    token = _dogrula(client, _kod(mails[0])).json()["reset_token"]
    client.post("/api/auth/reset-password",
                json={"reset_token": token, "new_password": "yeniParola123"})

    assert client.get("/api/auth/me", headers=eski).status_code == 401


def test_token_tekrar_kullanilamaz(client, session, mails):
    _mk_user(session)
    _kod_iste(client)
    token = _dogrula(client, _kod(mails[0])).json()["reset_token"]
    assert client.post("/api/auth/reset-password",
                       json={"reset_token": token, "new_password": "yeniParola123"}
                       ).status_code == 200

    r = client.post("/api/auth/reset-password",
                    json={"reset_token": token, "new_password": "baskaParola456"})

    assert r.status_code == 400


def test_suresi_dolmus_token_reddedilir(client, session, mails):
    from sqlalchemy import select

    from app.models import PasswordResetCode

    _mk_user(session)
    _kod_iste(client)
    token = _dogrula(client, _kod(mails[0])).json()["reset_token"]
    kayit = session.scalars(select(PasswordResetCode)).one()
    kayit.reset_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.commit()

    assert client.post("/api/auth/reset-password",
                       json={"reset_token": token, "new_password": "yeniParola123"}
                       ).status_code == 400


def test_gecersiz_token_reddedilir(client, session, mails):
    _mk_user(session)

    r = client.post("/api/auth/reset-password",
                    json={"reset_token": "uydurma-token", "new_password": "yeniParola123"})

    assert r.status_code == 400


def test_kisa_parola_reddedilir(client, session, mails):
    """Parola kuralı hesap oluşturmadakiyle AYNI kaynaktan gelir."""
    from app.api.auth import MIN_PASSWORD_LENGTH

    _mk_user(session)
    _kod_iste(client)
    token = _dogrula(client, _kod(mails[0])).json()["reset_token"]

    r = client.post("/api/auth/reset-password",
                    json={"reset_token": token, "new_password": "a" * (MIN_PASSWORD_LENGTH - 1)})

    assert r.status_code == 422


def test_sifirlama_denetim_kaydina_yazilir(client, session, mails):
    from sqlalchemy import select

    from app.models import AuditLog

    _mk_user(session)
    _kod_iste(client)
    token = _dogrula(client, _kod(mails[0])).json()["reset_token"]
    client.post("/api/auth/reset-password",
                json={"reset_token": token, "new_password": "yeniParola123"})

    kayitlar = [a for a in session.scalars(select(AuditLog))
                if a.action == "self_reset_password"]
    assert len(kayitlar) == 1
    assert kayitlar[0].actor_user_id is None  # kimliksiz uç — aktör yok


# --- hız sınırı ---------------------------------------------------------------

def test_forgot_password_hiz_sinirli(client, session, mails):
    from app.api.auth import RESET_RATE_MAX, _reset_attempts

    _reset_attempts.clear()
    kodlar = [
        client.post("/api/auth/forgot-password", json={"email": f"k{i}@x.com"}).status_code
        for i in range(RESET_RATE_MAX + 2)
    ]
    assert 429 in kodlar
    _reset_attempts.clear()


def test_verify_hiz_sinirli(client, session, mails):
    from app.api.auth import VERIFY_RATE_MAX, _reset_attempts

    _mk_user(session)
    _reset_attempts.clear()
    kodlar = [_dogrula(client, "123456").status_code for _ in range(VERIFY_RATE_MAX + 2)]
    assert 429 in kodlar
    _reset_attempts.clear()


def test_verify_sayaci_forgot_kovasini_TUKETMEZ(client, session, mails):
    """Ayrı kovalar: aksi hâlde 1 kod isteği + 5 deneme sınırı doldurur ve
    RESET_MAX_ATTEMPTS'e hiç ulaşılamaz (deneme sayacı ölü kod olurdu)."""
    from app.api.auth import RESET_MAX_ATTEMPTS, _reset_attempts

    _mk_user(session)
    _reset_attempts.clear()
    _kod_iste(client)

    # Deneme sayacını doldur — hiçbiri 429 olmamalı.
    kodlar = [_dogrula(client, "000000").status_code for _ in range(RESET_MAX_ATTEMPTS)]

    assert 429 not in kodlar
    _reset_attempts.clear()


def test_ayni_mail_farkli_IP_de_sinirlanir(client, session, mails):
    """Sayaç hem IP hem e-posta başına: IP değiştirerek tek hesabı denemek de
    sınırlanmalı."""
    from app.api.auth import RESET_RATE_MAX, _reset_attempts

    _mk_user(session)
    _reset_attempts.clear()
    kodlar = [
        client.post("/api/auth/forgot-password", json={"email": "calisan@x.com"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
        for i in range(RESET_RATE_MAX + 2)
    ]
    assert 429 in kodlar
    _reset_attempts.clear()
