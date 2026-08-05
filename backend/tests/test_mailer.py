"""Giden e-posta katmanı (SMTP).

Kritik davranış: yapılandırma EKSİKSE gönderim denenmez ve hata YUTULMAZ —
"şifremi unuttum" akışı buna güvenerek parolayı ancak mail gittikten sonra
kaydediyor.
"""
from __future__ import annotations

import smtplib

import pytest

from app.core.config import Config, SmtpSettings
from app.services.mailer import MailError, is_configured, send_email, sender_address


def _cfg(**kw) -> Config:
    c = Config()
    c.smtp = SmtpSettings(**kw)
    return c


def test_kapaliyken_yapilandirilmamis_sayilir():
    assert is_configured(_cfg(enabled=False, host="smtp.x.com", from_address="a@x.com")) is False


def test_host_yoksa_yapilandirilmamis():
    assert is_configured(_cfg(enabled=True, host="", from_address="a@x.com")) is False


def test_gonderen_adresi_yoksa_yapilandirilmamis():
    assert is_configured(_cfg(enabled=True, host="smtp.x.com")) is False


def test_kullanici_adi_gonderen_adresine_dusgun():
    """Çoğu sağlayıcı gönderen olarak kullanıcı adını ister; ayrıca yazmak
    zorunda kalmayalım."""
    cfg = _cfg(enabled=True, host="smtp.x.com", username="vantage@x.com")
    assert sender_address(cfg) == "vantage@x.com"
    assert is_configured(cfg) is True


def test_acik_relay_kimlik_dogrulamasiz_gecerli():
    """Kurum içi relay kullanıcı adı/parola istemeyebilir — bu geçerli bir
    yapılandırmadır, engellenmemeli."""
    cfg = _cfg(enabled=True, host="relay.local", security="none", from_address="vantage@x.com")
    assert is_configured(cfg) is True


def test_yapilandirilmamisken_gonderim_hata_verir():
    with pytest.raises(MailError):
        send_email("a@x.com", "konu", "gövde", cfg=_cfg(enabled=False))


def test_smtp_hatasi_MailError_olarak_yuzeye_cikar(monkeypatch):
    """Hata yutulursa çağıran parolayı kaydeder ve kullanıcı kilitlenir."""
    class PatlayanSMTP:
        def __init__(self, *a, **kw):
            raise smtplib.SMTPConnectError(421, "yok")

    monkeypatch.setattr(smtplib, "SMTP", PatlayanSMTP)
    cfg = _cfg(enabled=True, host="smtp.x.com", from_address="a@x.com")
    with pytest.raises(MailError):
        send_email("b@x.com", "konu", "gövde", cfg=cfg)


def test_basarili_gonderimde_mesaj_dogru_kurulur(monkeypatch):
    yakalanan = {}

    class SahteSMTP:
        def __init__(self, host, port, timeout=None):
            yakalanan["host"] = host
            yakalanan["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            yakalanan["starttls"] = True

        def login(self, u, p):
            yakalanan["login"] = u

        def send_message(self, msg):
            yakalanan["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", SahteSMTP)
    monkeypatch.setenv("SMTP_PASSWORD", "gizli")
    cfg = _cfg(enabled=True, host="smtp.x.com", port=587, security="starttls",
               username="vantage@x.com", from_name="Vantage")

    send_email("kisi@x.com", "Konu", "Gövde", cfg=cfg)

    assert yakalanan["host"] == "smtp.x.com"
    assert yakalanan["port"] == 587
    assert yakalanan["starttls"] is True
    assert yakalanan["login"] == "vantage@x.com"
    msg = yakalanan["msg"]
    assert msg["To"] == "kisi@x.com"
    assert msg["Subject"] == "Konu"
    assert "vantage@x.com" in msg["From"]
    assert "Gövde" in msg.get_content()


def test_parolasiz_relay_login_denemez(monkeypatch):
    yakalanan = {}

    class SahteSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            yakalanan["login"] = True

        def send_message(self, msg):
            yakalanan["gonderildi"] = True

    monkeypatch.setattr(smtplib, "SMTP", SahteSMTP)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    cfg = _cfg(enabled=True, host="relay.local", security="none", from_address="a@x.com")

    send_email("b@x.com", "k", "g", cfg=cfg)

    assert "login" not in yakalanan
    assert yakalanan["gonderildi"] is True
