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

from app.api.auth import current_user, require_admin_or_hr
from app.core.db import get_session
from app.models import Developer, Leave, TeamMembership, User

router = APIRouter(prefix="/api/leaves")

_TYPES = {"annual", "sick", "other"}
_STATUSES = {"pending", "approved", "rejected"}


def _can_manage(user: User) -> bool:
    """İzinleri yönetebilen (herkesi gör, onayla/reddet, başkasına ekle): admin + hr."""
    return user.role in ("admin", "hr")


class CreateLeaveBody(BaseModel):
    start_date: date
    end_date: date
    leave_type: str = "annual"
    description: str | None = None
    target_user_id: int | None = None  # yalnızca admin/İK başkasına ekleyebilir
    target_all: bool = False  # yalnızca admin/İK: tüm aktif çalışanlara (şirket tatili)


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
    manage = _can_manage(user)
    # Ay ile kesişen izinler.
    stmt = select(Leave).where(Leave.start_date <= m_end, Leave.end_date >= m_start)
    if not manage:
        stmt = stmt.where(Leave.user_id.in_(_team_user_ids(session, user)))
    rows = session.scalars(stmt.order_by(Leave.start_date)).all()
    out = []
    for lv in rows:
        status = lv.status or "approved"
        own = lv.user_id == user.id
        # Takvime YALNIZ onaylı işlenir. Reddedilen takvimde görünmez (sahibi
        # kendi istek listesinde /mine ile gerekçesiyle görür). Başkasının
        # BEKLEYEN isteği takvimi kirletmez — yalnız sahibi/yönetici görür.
        if status == "rejected":
            continue
        if status == "pending" and not (own or manage):
            continue
        out.append({
            "id": lv.id,
            "user_id": lv.user_id,
            "person": _person_name(session, lv.user_id, lv.developer_id),
            "leave_type": lv.leave_type,
            "start_date": lv.start_date.isoformat(),
            "end_date": lv.end_date.isoformat(),
            "description": lv.description,
            "status": status,
            # Gizlilik: karar notu yalnız sahibi/yöneticiye açılır.
            "decision_note": lv.decision_note if (own or manage) else None,
            "own": own,
            "can_delete": own or manage,
            "can_decide": manage and status == "pending",
        })
    return out


@router.get("/mine")
def my_leaves(
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Çalışanın kendi izin istekleri (tüm durumlar, en yeni önce). Reddedilenler
    dahil — red gerekçesi (decision_note) burada gösterilir."""
    rows = session.scalars(
        select(Leave).where(Leave.user_id == user.id).order_by(Leave.created_at.desc())
    ).all()
    return [{
        "id": lv.id,
        "leave_type": lv.leave_type,
        "start_date": lv.start_date.isoformat(),
        "end_date": lv.end_date.isoformat(),
        "description": lv.description,
        "status": lv.status or "approved",
        "decision_note": lv.decision_note,
        "created_at": lv.created_at.isoformat() if lv.created_at else None,
        "can_cancel": (lv.status or "approved") == "pending",
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

    # Şirket geneli tatil: tüm aktif çalışanlara tek seferde onaylı izin.
    if body.target_all:
        if not _can_manage(user):
            raise HTTPException(status_code=403, detail="Herkese izin ekleme yetkisi yok")
        now = datetime.now(timezone.utc)
        actives = session.scalars(
            select(User).where(User.is_active.is_(True))
        ).all()
        count = 0
        for u in actives:
            session.add(Leave(
                user_id=u.id, developer_id=u.developer_id,
                start_date=body.start_date, end_date=body.end_date,
                leave_type=body.leave_type, description=body.description,
                status="approved", approved_by=user.id, approved_at=now, created_at=now,
            ))
            count += 1
        session.commit()
        return {"ok": True, "status": "approved", "count": count}

    target = user
    if body.target_user_id and body.target_user_id != user.id:
        if not _can_manage(user):
            raise HTTPException(status_code=403, detail="Başkasına izin ekleme yetkisi yok")
        target = session.get(User, body.target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Hedef kullanıcı yok")

    # Yönetici/İK eklediyse doğrudan onaylı; çalışan kendine istek açtıysa
    # onay bekler (pending) — İK onaylayana kadar. Geriye uyumlu: eski satırlar approved.
    manager = _can_manage(user)
    now = datetime.now(timezone.utc)
    lv = Leave(
        user_id=target.id, developer_id=target.developer_id,
        start_date=body.start_date, end_date=body.end_date, leave_type=body.leave_type,
        description=body.description,
        status="approved" if manager else "pending",
        approved_by=user.id if manager else None,
        approved_at=now if manager else None,
        created_at=now,
    )
    session.add(lv)
    session.flush()  # lv.id
    # Onay bekleyen istekte admin + hr'a bildirim (İK panosunu açmadan haber alsın).
    if lv.status == "pending":
        from app.services.notifications import notify
        person = _person_name(session, target.id, target.developer_id)
        approvers = session.scalars(
            select(User).where(User.role.in_(("admin", "hr")), User.is_active.is_(True))
        ).all()
        for a in approvers:
            notify(
                session, a.id, kind="leave_pending", severity="info",
                title="Yeni izin isteği onay bekliyor",
                body=f"{person} · {lv.start_date.isoformat()} → {lv.end_date.isoformat()} ({lv.leave_type})",
                dedup_key=f"leave_pending:{lv.id}", link="leaves",
            )
    session.commit()
    return {"id": lv.id, "ok": True, "status": lv.status}


@router.delete("/{leave_id}")
def delete_leave(
    leave_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    lv = session.get(Leave, leave_id)
    if lv is None:
        raise HTTPException(status_code=404, detail="İzin bulunamadı")
    if lv.user_id != user.id and not _can_manage(user):
        raise HTTPException(status_code=403, detail="Bu izni silme yetkiniz yok")
    session.delete(lv)
    session.commit()
    return {"ok": True}


@router.get("/summary")
def leave_summary(
    month: str = Query(...),
    session: Session = Depends(get_session),
    _: User = Depends(require_admin_or_hr),
):
    """Admin/İK: ay içinde kişi başına toplam izin günü (İK takibi)."""
    m_start, m_end = _month_range(month)
    rows = session.scalars(
        select(Leave).where(Leave.start_date <= m_end, Leave.end_date >= m_start)
    ).all()
    agg: dict[int, dict] = {}
    for lv in rows:
        s = max(lv.start_date, m_start)
        e = min(lv.end_date, m_end)
        days = (e - s).days + 1
        rec = agg.setdefault(lv.user_id, {
            "person": _person_name(session, lv.user_id, lv.developer_id),
            "days": 0,
            # Tür kırılımı: İK "kaç gün yıllık, kaç gün rapor" görebilsin.
            # Mevcut 'days' alanı korunur (geriye uyumlu).
            "annual": 0, "sick": 0, "other": 0,
        })
        if (lv.status or "approved") == "rejected":
            continue  # reddedilen izin kapasiteye sayılmaz
        rec["days"] += days
        bucket = lv.leave_type if lv.leave_type in ("annual", "sick", "other") else "other"
        rec[bucket] += days
    return sorted(agg.values(), key=lambda r: -r["days"])


class LeaveDecisionBody(BaseModel):
    decision: str  # approved | rejected
    note: str | None = None  # redde ZORUNLU (gerekçe), onayda opsiyonel


@router.get("/pending")
def pending_leaves(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin_or_hr),
):
    """Admin/İK: onay bekleyen tüm izin istekleri (onay kuyruğu)."""
    rows = session.scalars(
        select(Leave).where(Leave.status == "pending").order_by(Leave.start_date)
    ).all()
    return [{
        "id": lv.id,
        "user_id": lv.user_id,
        "person": _person_name(session, lv.user_id, lv.developer_id),
        "leave_type": lv.leave_type,
        "start_date": lv.start_date.isoformat(),
        "end_date": lv.end_date.isoformat(),
        "description": lv.description,
        "created_at": lv.created_at.isoformat() if lv.created_at else None,
    } for lv in rows]


@router.post("/{leave_id}/decision")
def decide_leave(
    leave_id: int,
    body: LeaveDecisionBody,
    session: Session = Depends(get_session),
    actor: User = Depends(require_admin_or_hr),
):
    """Admin/İK bir izin isteğini onaylar ya da reddeder. Redde gerekçe (note)
    ZORUNLU — çalışan neden reddedildiğini görsün. Karar sonrası izin sahibine
    bildirim düşer (destek dili)."""
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=422, detail="decision: approved | rejected")
    note = (body.note or "").strip()
    if body.decision == "rejected" and not note:
        raise HTTPException(status_code=422, detail="Red için gerekçe gerekli")
    lv = session.get(Leave, leave_id)
    if lv is None:
        raise HTTPException(status_code=404, detail="İzin bulunamadı")
    lv.status = body.decision
    lv.decision_note = note or None
    lv.approved_by = actor.id
    lv.approved_at = datetime.now(timezone.utc)

    # İzin sahibine karar bildirimi (kendi hesabına düşer).
    from app.services.notifications import notify
    span = lv.start_date.isoformat() if lv.start_date == lv.end_date \
        else f"{lv.start_date.isoformat()} → {lv.end_date.isoformat()}"
    if body.decision == "approved":
        notify(session, lv.user_id, kind="leave_decision", severity="info",
               title="İzin isteğin onaylandı",
               body=f"{span} ({lv.leave_type}) izni onaylandı ve takvime işlendi.",
               dedup_key=f"leave_decision:{lv.id}:approved", link="leaves")
    else:
        notify(session, lv.user_id, kind="leave_decision", severity="info",
               title="İzin isteğin reddedildi",
               body=f"{span} ({lv.leave_type}) izni reddedildi. Gerekçe: {note}",
               dedup_key=f"leave_decision:{lv.id}:rejected", link="leaves")

    from app.services.audit import record_audit
    target = session.get(User, lv.user_id)
    record_audit(session, actor, f"leave_{body.decision}", target_user_id=lv.user_id,
                 target_email=target.email if target else None,
                 detail={"leave_id": lv.id, "type": lv.leave_type,
                         **({"note": note[:120]} if note else {})})
    session.commit()
    return {"ok": True, "status": lv.status}


@router.get("/balances")
def leave_balances(
    year: int | None = Query(default=None),
    session: Session = Depends(get_session),
    _: User = Depends(require_admin_or_hr),
):
    """Admin/İK: kişi başına yıllık izin bakiyesi (hak / kullanılan / kalan).
    Yalnızca 'annual' türü hakka sayılır; onaylı izinler kullanılan, pending
    istekler tentatif (beklemede) olarak ayrı gösterilir."""
    y = year or date.today().year
    y_start, y_end = date(y, 1, 1), date(y, 12, 31)
    users = session.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.id)
    ).all()
    # Yıl ile kesişen annual izinleri kişiye grupla.
    rows = session.scalars(
        select(Leave).where(
            Leave.leave_type == "annual",
            Leave.start_date <= y_end, Leave.end_date >= y_start,
        )
    ).all()
    used: dict[int, int] = {}
    pending: dict[int, int] = {}
    for lv in rows:
        s = max(lv.start_date, y_start)
        e = min(lv.end_date, y_end)
        days = (e - s).days + 1
        status = lv.status or "approved"
        if status == "approved":
            used[lv.user_id] = used.get(lv.user_id, 0) + days
        elif status == "pending":
            pending[lv.user_id] = pending.get(lv.user_id, 0) + days
    out = []
    for u in users:
        allowance = u.annual_allowance or 0
        u_used = used.get(u.id, 0)
        u_pending = pending.get(u.id, 0)
        out.append({
            "user_id": u.id,
            "person": _person_name(session, u.id, u.developer_id),
            "allowance": allowance,
            "used": u_used,
            "pending": u_pending,
            "remaining": allowance - u_used,
        })
    out.sort(key=lambda r: r["remaining"])
    return {"year": y, "balances": out}
