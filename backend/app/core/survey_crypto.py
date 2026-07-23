"""Anket cevaplarının at-rest şifrelemesi (anonimlik güvencesi).

Cevap payload'ı DB'ye yazılmadan ÖNCE simetrik şifrelenir (Fernet / AES-128-CBC
+ HMAC). Anahtar config.yaml'a ASLA yazılmaz; .secrets.env'de SURVEY_ENC_KEY
olarak yaşar (bkz. app.core.secrets). Anahtar yoksa modül "hazır değil" der ve
düz metin ASLA yazılmaz — sessizce şifresiz kayda düşmez.
"""
from __future__ import annotations

import json
import os

SURVEY_KEY_ENV = "SURVEY_ENC_KEY"


class SurveyKeyMissing(RuntimeError):
    """SURVEY_ENC_KEY tanımlı değil — şifreleme yapılamaz."""


def key_configured() -> bool:
    return bool(os.environ.get(SURVEY_KEY_ENV))


def generate_key() -> str:
    """Yeni bir Fernet anahtarı (urlsafe base64, 44 karakter) üretir."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def _fernet():
    from cryptography.fernet import Fernet

    key = os.environ.get(SURVEY_KEY_ENV)
    if not key:
        raise SurveyKeyMissing(
            "SURVEY_ENC_KEY tanımlı değil — anket şifrelenemez (modül hazır değil)."
        )
    return Fernet(key.encode("ascii"))


def encrypt_payload(payload: dict) -> str:
    """dict → şifreli metin (str). Kimlik/zaman içermemeli — çağıran sorumlu."""
    token = _fernet().encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return token.decode("ascii")


def decrypt_payload(ciphertext: str) -> dict:
    """Şifreli metin → dict. Bozuk/yanlış anahtarda cryptography hata verir."""
    raw = _fernet().decrypt(ciphertext.encode("ascii"))
    return json.loads(raw.decode("utf-8"))
