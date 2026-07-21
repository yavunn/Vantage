"""Yönetici işlemleri denetim kaydı (audit log).

Kim, neyi, kime yaptı — hesap verebilirlik için. Hassas içerik (parola vb.)
ASLA saklanmaz; yalnızca eylem türü, hedef ve insan-okur meta tutulur.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record_audit(
    session: Session,
    actor: User | None,
    action: str,
    *,
    target_user_id: int | None = None,
    target_email: str | None = None,
    detail: dict | None = None,
) -> None:
    """Denetim satırı ekler. session.commit() ÇAĞIRMAZ — çağıran kendi
    işlemiyle aynı transaction'da commit eder (atomik kayıt)."""
    session.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            action=action,
            target_user_id=target_user_id,
            target_email=target_email,
            detail=detail,
            created_at=datetime.now(timezone.utc),
        )
    )


def list_audit(session: Session, limit: int = 200) -> list[dict]:
    rows = session.scalars(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    ).all()
    return [
        {
            "id": r.id,
            "actor_email": r.actor_email,
            "action": r.action,
            "target_email": r.target_email,
            "target_user_id": r.target_user_id,
            "detail": r.detail,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
