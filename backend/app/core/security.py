"""Parola hash'leme (bcrypt) ve JWT üretim/doğrulama (Faz 1).

- SECRET_KEY ortam değişkeninden okunur; config dosyasına yazılmaz.
- Token'lar yalnızca response gövdesinde döner: URL'de/log'da taşınmaz.
- Access 1 saat, refresh 7 gün; tip claim'i ("access"/"refresh") ile
  refresh token access yerine kullanılamaz.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60
REFRESH_TOKEN_DAYS = 7


def _secret_key() -> str:
    # Demo/dev varsayılanı; gerçek kurulumda SECRET_KEY env zorunlu kabul edin.
    return os.environ.get("SECRET_KEY", "dev-secret-degistir")


def hash_password(plain: str) -> str:
    # bcrypt 72 bayttan uzununu reddeder; standart pratikle kırpılır.
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


def _create_token(user_id: int, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def create_access_token(user_id: int, expires_minutes: int = ACCESS_TOKEN_MINUTES) -> str:
    return _create_token(user_id, "access", timedelta(minutes=expires_minutes))


def create_refresh_token(user_id: int, expires_days: int = REFRESH_TOKEN_DAYS) -> str:
    return _create_token(user_id, "refresh", timedelta(days=expires_days))


def decode_token(token: str, expected_type: str) -> int | None:
    """Geçerli ve süresi dolmamışsa user_id döner; aksi halde None.
    Yanlış tip (refresh'i access yerine kullanmak gibi) de geçersizdir."""
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
