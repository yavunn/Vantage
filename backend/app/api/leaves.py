"""İzin panosu uçları (İK/kapasite).

Gizlilik: çalışan kendi iznini + kendi takım arkadaşlarının izinli günlerini
(isim + tip) görür; admin herkesi görür. İzin verisi metrik/performans
hesaplarına KARIŞMAZ — yalnızca kapasite bağlamı ve İK takibi.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.auth import current_user, require_admin
from app.core.db import get_session
from app.models import Developer, Leave, TeamMembership, User

router = APIRouter(prefix="/api/leaves")

_TYPES = {"annual", "sick", "other"}


class CreateLeaveBody(BaseModel):
    start_date: date
    end_date: date
    leave_type: str = "annual"
    description: str | None = None
    target_user_id: int | None = None  # yalnızca admin başkasına ekleyebilir


def _month_range(month: str) -> tuple[date, date]:
    try:
        y, m = map(int, month.split("-"))
        last = calendar.monthrange(y, m)[1]
        return date(y, m, 1), date(y, m, last)
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail="month biçimi YYYY-MM olmalı")


def _person_name(session: Session, user_id: int, developer_id: int | None) -> str:
    if developer_id:
        dev = session.get(Developer, developer_id)
        if dev:
            return dev.display_name
    u = session.get(User, user_id)
    return u.email.split("@")[0] if u else "?"


def _team_user_ids(session: Session, user: User) -> set[int]:
    """Kullanıcının takım arkadaşlarının user_id kümesi (kendisi dahil)."""
    ids = {user.id}
    if user.developer_id is None:
        return ids
    team_ids = [
        m.team_id for m in session.scalars(
            select(TeamMembership).where(TeamMembership.developer_id == user.developer_id)
        ).all()
    ]
    if not team_ids:
        return ids
    dev_ids = [
        m.developer_id for m in session.scalars(
            select(TeamMembership).where(TeamMembership.team_id.in_(team_ids))
        ).all()
    ]
    if dev_ids:
        for u in session.scalars(select(User).where(User.developer_id.in_(dev_ids))).all():
            ids.add(u.id)
    return ids


@router.get("")
def list_leaves(
    month: str = Query(...),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    m_start, m_end = _month_range(month)
    # Ay ile kesişen izinler.
    stmt = select(Leave).where(Leave.start_date <= m_end, Leave.end_date >= m_start)
    if user.role != "admin":
        stmt = stmt.where(Leave.user_id.in_(_team_user_ids(session, user)))
    rows = session.scalars(stmt.order_by(Leave.start_date)).all()
    return [{
        "id": lv.id,
        "user_id": lv.user_id,
        "person": _person_name(session, lv.user_id, lv.developer_id),
        "leave_type": lv.leave_type,
        "start_date": lv.start_date.isoformat(),
        "end_date": lv.end_date.isoformat(),
        "description": lv.description,
        "own": lv.user_id == user.id,
        "can_delete": lv.user_id == user.id or user.role == "admin",
    } for lv in rows]


@router.post("", status_code=201)
def create_leave(
    body: CreateLeaveBody,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    if body.leave_type not in _TYPES:
        raise HTTPException(status_code=422, detail="leave_type: annual | sick | other")
    if body.end_date < body.start_date:
        raise HTTPException(status_code=422, detail="Bitiş tarihi başlangıçtan önce olamaz")

    target = user
    if body.target_user_id and body.target_user_id != user.id:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Başkasına izin ekleme yetkisi yok")
        target = session.get(User, body.target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Hedef kullanıcı yok")

    lv = Leave(
        user_id=target.id, developer_id=target.developer_id,
        start_date=body.start_date, end_date=body.end_date, leave_type=body.leave_type,
        description=body.description, status="approved",
        approved_by=user.id if user.role == "admin" else None,
        approved_at=datetime.now(timezone.utc) if user.role == "admin" else None,
        created_at=datetime.now(timezone.utc),
    )
    session.add(lv)
    session.commit()
    return {"id": lv.id, "ok": True}


@router.delete("/{leave_id}")
def delete_leave(
    leave_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    lv = session.get(Leave, leave_id)
    if lv is None:
        raise HTTPException(status_code=404, detail="İzin bulunamadı")
    if lv.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu izni silme yetkiniz yok")
    session.delete(lv)
    session.commit()
    return {"ok": True}


@router.get("/summary")
def leave_summary(
    month: str = Query(...),
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Admin: ay içinde kişi başına toplam izin günü (İK takibi)."""
    m_start, m_end = _month_range(month)
    rows = session.scalars(
        select(Leave).where(Leave.start_date <= m_end, Leave.end_date >= m_start)
    ).all()
    agg: dict[int, dict] = {}
    for lv in rows:
        s = max(lv.start_date, m_start)
        e = min(lv.end_date, m_end)
        days = (e - s).days + 1
        rec = agg.setdefault(lv.user_id, {"person": _person_name(session, lv.user_id, lv.developer_id), "days": 0})
        rec["days"] += days
    return sorted(agg.values(), key=lambda r: -r["days"])
