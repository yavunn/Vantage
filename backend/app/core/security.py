"""Kimlik doğrulama yardımcıları: parola hash'leme (bcrypt) + JWT üretimi/çözümü.

On-prem kısıt: sır JWT imza anahtarı ortam değişkeninden (EHD_SECRET) okunur;
yoksa geliştirme varsayılanı kullanılır (üretimde MUTLAKA env verilmelidir).
Parolalar asla düz metin saklanmaz — yalnızca bcrypt hash'i tutulur.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

ALGORITHM = "HS256"
TOKEN_TTL_HOURS = 12


def _secret() -> str:
    return os.environ.get("EHD_SECRET", "dev-insecure-secret-change-in-prod")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=TOKEN_TTL_HOURS)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except JWTError:
        return None
