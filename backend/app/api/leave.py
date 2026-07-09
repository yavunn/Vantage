"""İzin / İK modülü uçları (Faz 5).

Kullanıcının "genel İK takip sistemi" fikrinin ÇERÇEVEYE UYGUN hâli:
self-servis izin talebi + admin/yönetici onayı + izin bağlamının metriğe
yansıması (metrik entegrasyonu metrics/engine + services/leave'de).

Etik guardrail'ler (spec Faz 5):
- Çalışan yalnız KENDİ taleplerini görür (`/api/user/leave-requests`).
- Onay yalnız admin ya da kişinin YÖNETİCİSİ içindir; başka takım göremez/onaylayamaz.
- `description` hassastır: takvim ucuna ve başka kişilere sızmaz.
- Takvim operasyonel müsaitlik içindir (kim ne zaman yok); izin SEBEBİ/türü
  sızdırılmaz, anonim modda isimler maskelenir.
- Hiçbir uç birden çok kişinin METRİĞİNİ yan yana döndürmez (leaderboard yok).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.api.routes import _is_manager_of, _mask_name
from app.core.config import get_config
from app.core.db import get_session
from app.models import Developer, Leave, TeamMembership, User

router = APIRouter()

LEAVE_TYPES = ("yillik", "hastalik", "rapor")


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "Kimlik gerekli (Bearer token)")
    return user


def _managed_dev_ids(session: Session, user: User) -> set[int] | None:
    """Onaylayanın erişebildiği developer id'leri. None = tümü (admin).
    Boş küme = ne admin ne yönetici → onay yetkisi yok."""
    if user.role == "admin":
        return None
    if user.developer_id is None:
        return set()
    mgr = session.get(Developer, user.developer_id)
    if mgr is None:
        return set()
    managed_team_ids = {m.team_id for m in mgr.memberships if m.role == "manager"}
    if not managed_team_ids:
        return set()
    rows = session.scalars(
        select(TeamMembership).where(TeamMembership.team_id.in_(managed_team_ids))
    )
    return {ms.developer_id for ms in rows}


def require_approver(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> User:
    """Admin ya da en az bir takımın yöneticisi. Aksi halde 403."""
    scope = _managed_dev_ids(session, user)
    if scope is not None and not scope:
        raise HTTPException(403, "Bu uç yalnızca admin ya da takım yöneticisi içindir")
    return user


def _can_approve(session: Session, approver: User, leave: Leave) -> bool:
    if approver.role == "admin":
        return True
    if approver.developer_id is None or leave.developer_id is None:
        return False
    mgr = session.get(Developer, approver.developer_id)
    target = session.get(Developer, leave.developer_id)
    if mgr is None or target is None:
        return False
    return _is_manager_of(session, mgr, target)


def _leave_payload(lv: Leave, *, description: bool) -> dict:
    """`description` yalnız sahibi/yetkili onaylayan için döner (hassas alan)."""
    return {
        "id": lv.id,
        "user_id": lv.user_id,
        "developer_id": lv.developer_id,
        "start_date": lv.start_date.isoformat(),
        "end_date": lv.end_date.isoformat(),
        "leave_type": lv.leave_type,
        "status": lv.status,
        "description": lv.description if description else None,
        "approved_by": lv.approved_by,
        "approved_at": lv.approved_at.isoformat() if lv.approved_at else None,
        "created_at": lv.created_at.isoformat() if lv.created_at else None,
    }


# --- çalışan self-servis --------------------------------------------------------

class LeaveCreate(BaseModel):
    start_date: date
    end_date: date
    leave_type: str
    description: str | None = Field(default=None, max_length=1000)


@router.post("/api/user/leave-requests", status_code=201)
def create_leave(
    body: LeaveCreate,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if body.leave_type not in LEAVE_TYPES:
        raise HTTPException(422, f"leave_type şunlardan biri olmalı: {', '.join(LEAVE_TYPES)}")
    if body.end_date < body.start_date:
        raise HTTPException(422, "Bitiş tarihi başlangıçtan önce olamaz")
    leave = Leave(
        user_id=user.id,
        developer_id=user.developer_id,  # metrik penceresi düşümü bu bağdan yapılır
        start_date=body.start_date,
        end_date=body.end_date,
        leave_type=body.leave_type,
        description=body.description,
        status="pending",
    )
    session.add(leave)
    session.commit()
    return _leave_payload(leave, description=True)


@router.get("/api/user/leave-requests")
def my_leaves(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Yalnız KENDİ talepleri. Başkasının izni bu uçtan asla görünmez."""
    leaves = session.scalars(
        select(Leave).where(Leave.user_id == user.id).order_by(Leave.start_date.desc())
    ).all()
    return [_leave_payload(lv, description=True) for lv in leaves]


# --- onay (admin ya da yönetici) -----------------------------------------------

@router.get("/api/admin/leave-requests")
def list_for_approval(
    status: str | None = Query(default=None),
    approver: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    """Onaylayanın kapsamındaki talepler. Admin hepsini; yönetici yalnız
    KENDİ takımını görür. Kişi metriği İÇERMEZ (leaderboard değil)."""
    scope = _managed_dev_ids(session, approver)
    stmt = select(Leave)
    if scope is not None:  # yönetici: yalnız yönettiği developer'lar
        stmt = stmt.where(Leave.developer_id.in_(scope))
    if status is not None:
        stmt = stmt.where(Leave.status == status)
    leaves = session.scalars(stmt.order_by(Leave.created_at.desc())).all()
    out = []
    for lv in leaves:
        payload = _leave_payload(lv, description=True)  # yetkili onaylayan görebilir
        requester = session.get(User, lv.user_id)
        payload["requester_email"] = requester.email if requester else None
        out.append(payload)
    return out


class LeaveDecision(BaseModel):
    decision: str  # approve | reject


@router.put("/api/admin/leave-requests/{leave_id}")
def decide_leave(
    leave_id: int,
    body: LeaveDecision,
    approver: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    if body.decision not in ("approve", "reject"):
        raise HTTPException(422, "decision 'approve' ya da 'reject' olmalı")
    leave = session.get(Leave, leave_id)
    # Kapsam dışı talep de 'yok' gibi davranır — varlığı sızdırılmaz (404).
    if leave is None or not _can_approve(session, approver, leave):
        raise HTTPException(404, "İzin talebi bulunamadı")
    leave.status = "approved" if body.decision == "approve" else "rejected"
    leave.approved_by = approver.id
    leave.approved_at = datetime.now(timezone.utc)
    session.commit()
    return _leave_payload(leave, description=True)


# --- takvim (operasyonel müsaitlik) --------------------------------------------

@router.get("/api/leave/calendar")
def leave_calendar(
    team_id: int | None = Query(default=None),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Takım müsaitlik takvimi: kim ne zaman yok. Operasyonel bilgidir,
    performans kıyası DEĞİL. İzin SEBEBİ/türü ve `description` sızdırılmaz;
    anonim modda isimler maskelenir."""
    cfg = get_config()
    stmt = select(Leave).where(Leave.status == "approved")
    if team_id is not None:
        member_dev_ids = {
            ms.developer_id
            for ms in session.scalars(
                select(TeamMembership).where(TeamMembership.team_id == team_id)
            )
        }
        stmt = stmt.where(Leave.developer_id.in_(member_dev_ids or {-1}))
    leaves = session.scalars(stmt.order_by(Leave.start_date)).all()
    out = []
    for lv in leaves:
        dev = session.get(Developer, lv.developer_id) if lv.developer_id else None
        out.append(
            {
                "developer_id": lv.developer_id,
                "developer": _mask_name(dev, cfg) if dev else "—",
                "start_date": lv.start_date.isoformat(),
                "end_date": lv.end_date.isoformat(),
                # SEBEP/tür ve açıklama bilinçli olarak yok (sağlık mahremiyeti)
            }
        )
    return out
