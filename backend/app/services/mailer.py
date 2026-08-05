"""Giden e-posta (Resend HTTP API).

NEDEN SMTP DEĞİL: SMTP host/port/TLS/kimlik ayarı kurulum yükü getiriyordu.
Resend tek bir HTTPS çağrısıdır — `.env`'e yalnız API anahtarı + gönderen
adresi konur, başka sunucu ayarı yoktur. httpx zaten projede var, yeni
bağımlılık eklenmedi.

TASARIM: gönderim SESSİZ BAŞARISIZ OLMAZ. "Şifremi unuttum" akışı buna
güvenerek kodu ancak mail gittikten sonra kalıcılaştırıyor; hata yutulsaydı
kullanıcı hiç gelmeyecek bir kodu beklerdi.

SendGrid'e geçmek istenirse yalnız `send_email` gövdesi değişir; çağıranlar
(auth.py) bu modülün arayüzüne bağlıdır, sağlayıcıya değil.
"""
from __future__ import annotations

import os

import httpx

DEFAULT_API_URL = "https://api.resend.com/emails"
API_KEY_ENV = "RESEND_API_KEY"
API_URL_ENV = "RESEND_API_URL"   # kurum içi vekil / uçtan uca test için
FROM_ENV = "MAIL_FROM"

# Resend'in doğrulama gerektirmeyen test göndericisi. Kendi alan adını
# doğrulayana kadar YALNIZ hesabının kendi adresine mail atabilirsin —
# üretimde MAIL_FROM'u kendi doğrulanmış alan adınla değiştir.
DEFAULT_FROM = "Vantage <onboarding@resend.dev>"

TIMEOUT_SECONDS = 15.0


class MailError(RuntimeError):
    """Mail yapılandırması eksik ya da gönderim başarısız."""


def _api_key() -> str:
    return (os.environ.get(API_KEY_ENV) or "").strip()


def _api_url() -> str:
    return (os.environ.get(API_URL_ENV) or "").strip() or DEFAULT_API_URL


def sender() -> str:
    return (os.environ.get(FROM_ENV) or "").strip() or DEFAULT_FROM


def is_configured() -> bool:
    """Mail gönderilebilir mi? Tek koşul: API anahtarı tanımlı olsun."""
    return bool(_api_key())


def send_email(to: str, subject: str, html: str) -> None:
    """HTML e-posta gönderir. Başarısızlıkta MailError fırlatır."""
    key = _api_key()
    if not key:
        raise MailError(f"{API_KEY_ENV} tanımlı değil")
    try:
        resp = httpx.post(
            _api_url(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"from": sender(), "to": [to], "subject": subject, "html": html},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as e:
        raise MailError(f"E-posta gönderilemedi: {e}") from e
    if resp.status_code >= 400:
        # Gövde sağlayıcının hata açıklamasını taşır (ör. "domain not verified").
        # Bu metin YÖNETİCİ/log içindir; uç katmanı kullanıcıya genel mesaj verir.
        raise MailError(f"E-posta gönderilemedi ({resp.status_code}): {resp.text[:300]}")
