"""Kimlik doğrulama yardımcıları: parola hash'leme (bcrypt) + JWT üretimi/çözümü.

JWT kütüphanesi PyJWT'dir. Önceki python-jose, saf-Python `ecdsa` paketini
sürüklüyordu (CVE-2024-23342, "düzeltilmeyecek" damgalı yan-kanal). Bu proje
yalnız HS256 (HMAC) kullandığı için o kod yolu hiç çalışmıyordu — yani risk
teoriktı; yine de gereksiz bağımlılık ve saldırı yüzeyi kaldırıldı.

On-prem kısıt: JWT imza anahtarı ortam değişkeninden (EHD_SECRET) okunur.
GÜVENLİK: Tahmin edilebilir SABİT bir varsayılan YOKTUR (repo herkese açık —
sabit anahtar = token taklidi). EHD_SECRET yoksa `ensure_jwt_secret()` başlangıçta
güçlü bir anahtar üretip `.secrets.env`'e yazar; o çağrılmadıysa (ör. testte)
süreç-içi rastgele bir anahtar kullanılır. Parolalar yalnızca bcrypt hash'i.
"""
from __future__ import annotations

import os
import secrets as _secrets_mod
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from jwt import PyJWTError

ALGORITHM = "HS256"
TOKEN_TTL_HOURS = 12

_EPHEMERAL_SECRET: str | None = None


def _secret() -> str:
    s = os.environ.get("EHD_SECRET")
    if s:
        return s
    # Env yoksa SABİT/tahmin edilebilir anahtar KULLANMA — süreç-içi rastgele üret.
    # (Kalıcı anahtar ensure_jwt_secret() ile yazılır; bu yol yalnız o çalışmadıysa
    # devreye girer. Süreç yeniden başlarsa oturumlar düşer — prod'da EHD_SECRET ver.)
    global _EPHEMERAL_SECRET
    if _EPHEMERAL_SECRET is None:
        _EPHEMERAL_SECRET = _secrets_mod.token_hex(32)
    return _EPHEMERAL_SECRET


def ensure_jwt_secret() -> None:
    """Başlangıçta EHD_SECRET yoksa güçlü bir anahtar üretip .secrets.env'e yazar
    (yeniden başlatmada oturumlar korunur). Zaten varsa DOKUNMAZ."""
    if os.environ.get("EHD_SECRET"):
        return
    from app.core.secrets import set_secret

    set_secret("EHD_SECRET", _secrets_mod.token_hex(32))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, role: str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "tv": int(token_version),  # oturum sürümü — parola değişince eşleşmez
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=TOKEN_TTL_HOURS)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        # algorithms listesi TEK öğeli: "alg: none" ya da algoritma karıştırma
        # saldırısına kapı bırakmaz. Süre dolmuşsa PyJWT kendi hata verir.
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except PyJWTError:
        return None
