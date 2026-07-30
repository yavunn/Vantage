"""Kullanıcı erişim anahtarlarının at-rest şifrelemesi.

Kullanıcı kendi GitHub PAT'ini giriyor; bu, kişisel bir kimlik bilgisi ve DB'ye
düz metin yazılamaz. Anket cevaplarıyla (survey_crypto) aynı Fernet kalıbını
kullanır ama AYRI bir anahtarla: anket anahtarını döndürmek kullanıcıların
GitHub bağlantılarını da kırmasın — iki veri sınıfı bağımsız yaşamalı.

Anahtar config.yaml'a ASLA yazılmaz; .secrets.env'de CREDENTIALS_ENC_KEY olarak
durur ve ilk açılışta yoksa üretilir (ensure_credentials_key). Anahtar yoksa
şifreleme yapılmaz — düz metne ASLA düşülmez.
"""
from __future__ import annotations

import os

CREDENTIALS_KEY_ENV = "CREDENTIALS_ENC_KEY"


class CredentialKeyMissing(RuntimeError):
    """CREDENTIALS_ENC_KEY tanımlı değil — anahtar şifrelenemez."""


def key_configured() -> bool:
    return bool(os.environ.get(CREDENTIALS_KEY_ENV))


def ensure_credentials_key() -> None:
    """Anahtar yoksa üretip .secrets.env'e yazar (ensure_jwt_secret ile aynı
    yaklaşım). Zaten varsa DOKUNMAZ — döndürmek kayıtlı tüm PAT'leri okunamaz
    hale getirirdi."""
    if key_configured():
        return
    from cryptography.fernet import Fernet

    from app.core.secrets import set_secret

    set_secret(CREDENTIALS_KEY_ENV, Fernet.generate_key().decode("ascii"))


def _fernet():
    from cryptography.fernet import Fernet

    key = os.environ.get(CREDENTIALS_KEY_ENV)
    if not key:
        raise CredentialKeyMissing(
            "CREDENTIALS_ENC_KEY tanımlı değil — erişim anahtarı saklanamaz."
        )
    return Fernet(key.encode("ascii"))


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")


def hint(plain: str) -> str:
    """Kullanıcıya "hangi anahtarı girmiştim" dedirtmeyecek kadar bilgi:
    yalnız son 4 karakter. Anahtarın kendisi HİÇBİR uçtan geri dönmez."""
    tail = (plain or "")[-4:]
    return f"…{tail}" if tail else ""
