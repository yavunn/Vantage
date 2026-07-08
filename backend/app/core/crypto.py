"""Credential şifreleme (Faz 3) — Fernet (AES-128-CBC + HMAC).

Anahtar ENCRYPTION_KEY ortam değişkeninden okunur (Fernet.generate_key()
çıktısı). Yoksa dev/demo için sabit bir anahtar kullanılır ve uyarı
loglanır — gerçek kurulumda env zorunlu kabul edin. Anahtar da token da
config dosyasına, log'a ya da URL'ye yazılmaz.
"""
from __future__ import annotations

import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Yalnız dev/demo: deterministik anahtar (Fernet: 32 bayt urlsafe base64).
_DEV_KEY = base64.urlsafe_b64encode(b"dev-anahtar-degistir-prod-da-32b")
_warned = False


def _fernet() -> Fernet:
    global _warned
    key = os.environ.get("ENCRYPTION_KEY")
    if key:
        return Fernet(key.encode("ascii"))
    if not _warned:
        logger.warning(
            "ENCRYPTION_KEY tanımlı değil — dev anahtarı kullanılıyor. "
            "Gerçek kurulumda Fernet.generate_key() ile üretip env'e koyun."
        )
        _warned = True
    return Fernet(_DEV_KEY)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(encrypted: str) -> str | None:
    """Çözülemiyorsa (anahtar değişti / bozuk kayıt) None — sistem çökmez."""
    try:
        return _fernet().decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
