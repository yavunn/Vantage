"""Trend anotasyonları — tatil/incident/sürüm işaretleri.

Okuma oturum açmış her kullanıcıya açık (grafiklerde ve izin takviminde bağlam
gösterilir); yazma/silme admin + İK (izin takvimine tatil/olay işaretleyebilsinler).
Anotasyon metrik verisini DEĞİŞTİRMEZ; sadece görsel bağlamdır.

GÜVENLİK: JWT zorunluluğu ROUTER seviyesindedir — etiketler ("ödeme servisi
çöktü", sürüm adları) şirket içi bilgidir ve tokensiz okunmamalıdır. Router'a
sonradan eklenen her uç da otomatik olarak bu korumayı alır.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, require_admin_or_hr
from app.core.db import get_session
from app.core.i18n import tr_error
from app.models import TrendAnnotation, User

router = APIRouter(prefix="/api/annotations", dependencies=[Depends(current_user)])

VALID_KINDS = {"holiday", "incident", "release", "other"}


class AnnotationIn(BaseModel):
    date: date
    label: str
    kind: str = "other"
    team_id: int | None = None  # None = tüm takımlar (ör. resmi tatil)


def _out(a: TrendAnnotation) -> dict:
    return {
        "id": a.id,
        "team_id": a.team_id,
        "date": a.date.isoformat(),
        "label": a.label,
        "kind": a.kind,
    }


@router.get("")
def list_annotations(
    team_id: int | None = None,
    session: Session = Depends(get_session),
):
    """Bir takımın anotasyonları + global (team_id NULL) olanlar."""
    stmt = select(TrendAnnotation)
    if team_id is not None:
        stmt = stmt.where(
            (TrendAnnotation.team_id == team_id) | (TrendAnnotation.team_id.is_(None))
        )
    rows = session.scalars(stmt.order_by(TrendAnnotation.date)).all()
    return [_out(a) for a in rows]


@router.post("", status_code=201)
def create_annotation(
    payload: AnnotationIn,
    session: Session = Depends(get_session),
    actor: User = Depends(require_admin_or_hr),
):
    if payload.kind not in VALID_KINDS:
        raise HTTPException(422, tr_error("kind yalnızca {list} olabilir", list=sorted(VALID_KINDS)))
    if not payload.label.strip():
        raise HTTPException(422, tr_error("label boş olamaz"))
    a = TrendAnnotation(
        team_id=payload.team_id,
        date=payload.date,
        label=payload.label.strip(),
        kind=payload.kind,
        created_by=actor.id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return _out(a)


@router.delete("/{annotation_id}")
def delete_annotation(
    annotation_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin_or_hr),
):
    a = session.get(TrendAnnotation, annotation_id)
    if a is None:
        raise HTTPException(404, tr_error("Anotasyon bulunamadı"))
    session.delete(a)
    session.commit()
    return {"ok": True}
