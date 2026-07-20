"""Trend anotasyonları — tatil/incident/sürüm işaretleri.

Okuma herkese açık (grafiklerde bağlam gösterilir). Yazma/silme yalnızca
admin. Anotasyon metrik verisini DEĞİŞTİRMEZ; sadece görsel bağlamdır.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.core.db import get_session
from app.models import TrendAnnotation, User

router = APIRouter(prefix="/api/annotations")

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
    admin: User = Depends(require_admin),
):
    if payload.kind not in VALID_KINDS:
        raise HTTPException(422, f"kind yalnızca {sorted(VALID_KINDS)} olabilir")
    if not payload.label.strip():
        raise HTTPException(422, "label boş olamaz")
    a = TrendAnnotation(
        team_id=payload.team_id,
        date=payload.date,
        label=payload.label.strip(),
        kind=payload.kind,
        created_by=admin.id,
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
    _: User = Depends(require_admin),
):
    a = session.get(TrendAnnotation, annotation_id)
    if a is None:
        raise HTTPException(404, "Anotasyon bulunamadı")
    session.delete(a)
    session.commit()
    return {"ok": True}
