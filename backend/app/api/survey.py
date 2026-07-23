"""Anonim çalışan memnuniyet anketi uçları.

- GET  /api/survey/current   : (çalışan) açık döngü + doldurdu mu + sorular
- POST /api/survey/current   : (çalışan) anonim + şifreli cevap gönder
- GET  /api/survey/results   : (admin) AGREGE sonuç (k-eşiği altında maskeli)
- GET  /api/survey/cycles    : (admin) döngü listesi
- GET  /api/survey/status    : (admin) modül/anahtar durumu
- POST /api/survey/genkey    : (owner) şifreleme anahtarı üret + .secrets.env'e yaz

Anonimlik: cevap kaydında kullanıcı kimliği YOK; "doldurdu mu" ayrı defterde.
Admin bireysel cevabı ASLA görmez — yalnız agrega + (eşik aşılınca) karışık yorum.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, require_admin, require_owner
from app.core.config import get_config
from app.core.db import get_session
from app.core.survey_crypto import (
    SURVEY_KEY_ENV,
    generate_key,
    key_configured,
)
from app.models import SurveyCycle, SurveyParticipation, SurveyResponse, User
from app.services import survey as survey_svc

router = APIRouter(prefix="/api/survey")


class SubmitBody(BaseModel):
    answers: dict[str, int] = Field(default_factory=dict)
    comment: str | None = None


def _questions_out(cfg) -> list[dict]:
    return [{"key": q.key, "label": q.label, "type": q.type} for q in cfg.survey.questions]


@router.get("/current")
def get_current(
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Çalışanın göreceği açık anket. already_submitted KATILIM defterinden
    okunur (cevaptan değil). Modül kapalı ya da anahtar yoksa dürüstçe söyler."""
    cfg = get_config()
    if not cfg.survey.enabled:
        return {"enabled": False}
    if not key_configured():
        # Şifreleme kurulmadan cevap toplanmaz (düz metin riski yok).
        return {"enabled": True, "ready": False,
                "note": "Anket şifrelemesi kurulmadı — baş yönetici anahtarı üretmeli."}
    cycle = survey_svc.get_or_create_active_cycle(session, cfg)
    session.commit()  # yeni döngü + hatırlatma bildirimleri kalıcı olsun
    return {
        "enabled": True,
        "ready": True,
        "cycle_key": cycle.key,
        "opens_at": cycle.opens_at.isoformat(),
        "closes_at": cycle.closes_at.isoformat(),
        "is_open": cycle.is_open,
        "already_submitted": survey_svc.has_submitted(session, cycle.id, user.id),
        "questions": _questions_out(cfg),
    }


@router.post("/current")
def submit_current(
    body: SubmitBody,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    cfg = get_config()
    if not cfg.survey.enabled:
        raise HTTPException(400, detail="Anket modülü kapalı")
    if not key_configured():
        raise HTTPException(503, detail="Anket şifrelemesi kurulmadı (hazır değil)")
    cycle = survey_svc.get_or_create_active_cycle(session, cfg)
    if not cycle.is_open:
        raise HTTPException(400, detail="Anket döngüsü kapalı")
    try:
        survey_svc.submit_response(session, cfg, cycle, user.id, body.answers, body.comment)
    except ValueError:
        raise HTTPException(409, detail="Bu dönem anketini zaten doldurdun")
    except RuntimeError as e:
        raise HTTPException(503, detail=str(e))
    return {"ok": True}


def _cycle_by_key_or_current(session: Session, cfg, key: str | None) -> SurveyCycle | None:
    if key:
        return session.scalar(select(SurveyCycle).where(SurveyCycle.key == key))
    return survey_svc.get_or_create_active_cycle(session, cfg)


@router.get("/results")
def get_results(
    cycle: str | None = None,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Admin: AGREGE sonuç. Bireysel cevap DÖNMEZ; eşik altında maskeli."""
    cfg = get_config()
    c = _cycle_by_key_or_current(session, cfg, cycle)
    session.commit()
    if c is None:
        raise HTTPException(404, detail="Döngü bulunamadı")
    return survey_svc.aggregate_results(session, cfg, c)


@router.get("/cycles")
def list_cycles(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Döngü listesi + cevap sayısı (en yeni önce). Bireysel bağ yok."""
    from sqlalchemy import func

    rows = session.scalars(select(SurveyCycle).order_by(SurveyCycle.opens_at.desc())).all()
    out = []
    for c in rows:
        rc = session.scalar(
            select(func.count()).select_from(SurveyResponse).where(
                SurveyResponse.cycle_id == c.id
            )
        ) or 0
        pc = session.scalar(
            select(func.count()).select_from(SurveyParticipation).where(
                SurveyParticipation.cycle_id == c.id
            )
        ) or 0
        out.append({
            "key": c.key, "opens_at": c.opens_at.isoformat(),
            "closes_at": c.closes_at.isoformat(), "is_open": c.is_open,
            "response_count": rc, "participation": pc,
        })
    return out


@router.get("/status")
def survey_status(_: User = Depends(require_admin)):
    """Modül açık mı + şifreleme anahtarı tanımlı mı."""
    cfg = get_config()
    return {
        "enabled": cfg.survey.enabled,
        "key_env": SURVEY_KEY_ENV,
        "key_configured": key_configured(),
        "interval_days": cfg.survey.interval_days,
        "min_responses": cfg.survey.min_responses,
    }


@router.post("/genkey")
def gen_key(_: User = Depends(require_owner)):
    """Baş yönetici şifreleme anahtarını üretir ve .secrets.env'e yazar.
    Zaten varsa DEĞİŞTİRMEZ (eski cevaplar çözülemez hale gelmesin)."""
    from app.core.secrets import set_secret

    if key_configured():
        return {"ok": True, "key_configured": True, "created": False,
                "note": "Anahtar zaten tanımlı — korunuyor."}
    set_secret(SURVEY_KEY_ENV, generate_key())
    return {"ok": True, "key_configured": True, "created": True}
