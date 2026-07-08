"""Yönetim uçları (Faz 2) — yalnızca admin rolü.

Etik sınır: bu uçlar hesap yönetimi ve TAKIM-AGREGAT istatistik içindir.
Kullanıcı listesi metrik İÇERMEZ, istatistikler kişiye inmez — hesap
listesi + metrik birleşimi leaderboard doğurur, o uç bilerek yoktur.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.config import get_config
from app.core.db import get_session
from app.models import Commit, MetricResult, Repo, User
from app.services.health import health_status

router = APIRouter(prefix="/api/admin")


def check_admin_role(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "Kimlik gerekli (Bearer token)")
    if user.role != "admin":
        raise HTTPException(403, "Bu uç yalnızca admin içindir")
    return user


@router.get("/users")
def list_users(
    admin: User = Depends(check_admin_role),
    session: Session = Depends(get_session),
):
    """Aktif hesaplar. Soft-delete edilenler görünmez; metrik alanı YOK."""
    users = session.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.id)
    ).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "developer_id": u.developer_id,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


class RoleUpdate(BaseModel):
    role: str  # admin | user


@router.put("/users/{user_id}")
def update_user_role(
    user_id: int,
    body: RoleUpdate,
    admin: User = Depends(check_admin_role),
    session: Session = Depends(get_session),
):
    if body.role not in ("admin", "user"):
        raise HTTPException(422, "Rol admin ya da user olmalı")
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    user.role = body.role
    session.commit()
    return {"id": user.id, "email": user.email, "role": user.role}


@router.delete("/users/{user_id}")
def soft_delete_user(
    user_id: int,
    admin: User = Depends(check_admin_role),
    session: Session = Depends(get_session),
):
    """Soft delete: is_active=False → login engellenir, listeden düşer.
    Kayıt silinmez (denetim izi)."""
    if user_id == admin.id:
        raise HTTPException(400, "Kendi hesabınızı silemezsiniz")
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    user.is_active = False
    session.commit()
    return {"id": user.id, "deleted": True}


@router.get("/stats")
def stats(
    admin: User = Depends(check_admin_role),
    session: Session = Depends(get_session),
):
    """Agregat istatistik kartları. Kişi kıyas tablosu DEĞİLDİR:
    hiçbir alan kişiye inmez, sağlık oranı takım metriklerinden gelir."""
    cfg = get_config()
    total_users = session.scalar(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    )
    repo_count = session.scalar(select(func.count()).select_from(Repo))
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    commits_7d = session.scalar(
        select(func.count()).select_from(Commit).where(Commit.committed_at >= week_ago)
    )
    # Genel sağlık: takım kapsamındaki pencere (overall) metriklerinde yeşil oranı.
    rows = session.scalars(
        select(MetricResult).where(MetricResult.scope == "team")
    ).all()
    statuses = []
    for row in rows:
        try:
            p_start, p_end = row.period.split("/")
            span = (datetime.fromisoformat(p_end) - datetime.fromisoformat(p_start)).days
        except ValueError:
            continue
        if span < cfg.app.window_days - 1:  # yalnız pencere metrikleri, kovalar değil
            continue
        status = health_status(row.metric_key, row.value, row.data_completeness, cfg)
        if status != "insufficient_data":
            statuses.append(status)
    health_pct = (
        round(100 * sum(1 for s in statuses if s == "green") / len(statuses))
        if statuses
        else None  # veri yetersizse yüzde UYDURULMAZ
    )
    return {
        "total_users": total_users,
        "repo_count": repo_count,
        "commits_last_7d": commits_7d,
        "overall_health_pct": health_pct,
        "health_metric_count": len(statuses),
    }
