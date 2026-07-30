"""Kullanıcı erişim anahtarları — okuma/yazma tek kapıdan.

Anahtarın düz metni yalnız iki anda var olur: kullanıcı girerken ve GitHub'a
istek atarken. Arada hep şifreli durur ve HİÇBİR uç geri döndürmez (yalnız
"tanımlı mı" + son 4 karakter).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.credential_crypto import (
    decrypt_secret,
    encrypt_secret,
    ensure_credentials_key,
    hint,
)
from app.models import UserCredential

GITHUB = "github"


def _row(session: Session, user_id: int, provider: str) -> UserCredential | None:
    return session.scalar(
        select(UserCredential).where(
            UserCredential.user_id == user_id, UserCredential.provider == provider
        )
    )


def get_token(session: Session, user_id: int, provider: str = GITHUB) -> str | None:
    """Kullanıcının anahtarını çözer. Anahtar bozuksa (ör. CREDENTIALS_ENC_KEY
    döndürülmüş) None döner — çağıran sunucu token'ına düşer ya da net hata
    verir; şifre çözme hatası tüm senkronu çökertmez."""
    row = _row(session, user_id, provider)
    if row is None:
        return None
    try:
        return decrypt_secret(row.encrypted_value)
    except Exception:  # noqa: BLE001 — bozuk/eski şifreli değer sistemi düşürmesin
        return None


def set_token(session: Session, user_id: int, value: str,
              provider: str = GITHUB) -> dict:
    """Anahtarı şifreleyip saklar. Boş değer anahtarı SİLER (bağlantıyı koparır)."""
    row = _row(session, user_id, provider)
    now = datetime.now(timezone.utc)
    value = (value or "").strip()

    if not value:
        if row is not None:
            session.delete(row)
            session.commit()
        return status(session, user_id, provider)

    ensure_credentials_key()  # ilk kullanımda anahtarı üret — kurulum adımı gerekmesin
    if row is None:
        row = UserCredential(user_id=user_id, provider=provider, created_at=now)
        session.add(row)
    row.encrypted_value = encrypt_secret(value)
    row.hint = hint(value)
    row.updated_at = now
    session.commit()
    return status(session, user_id, provider)


def status(session: Session, user_id: int, provider: str = GITHUB) -> dict:
    """Arayüz için: anahtarın KENDİSİ asla dönmez."""
    row = _row(session, user_id, provider)
    return {
        "provider": provider,
        "configured": row is not None,
        "hint": row.hint if row else None,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }
