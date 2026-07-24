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

import re
import unicodedata

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
    texts: dict[str, str] = Field(default_factory=dict)
    # Geriye uyum: eski istemci tek 'comment' göndermiş olabilir.
    comment: str | None = None


_EXCLUDED_NOTE = (
    "Bu anketi sen yönetiyorsun; doldurman gerekmez. "
    "Sonuçları Yönetim > Memnuniyet'te görürsün."
)


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
    # Yönetici rolleri anketi DOLDURMAZ — soru/döngü göndermeyiz.
    if not survey_svc.is_respondent(cfg, user):
        return {"enabled": True, "respondent": False, "note": _EXCLUDED_NOTE}
    if not key_configured():
        # Şifreleme kurulmadan cevap toplanmaz (düz metin riski yok).
        return {"enabled": True, "ready": False, "respondent": True,
                "note": "Anket şifrelemesi kurulmadı — baş yönetici anahtarı üretmeli."}
    cycle = survey_svc.get_or_create_active_cycle(session, cfg)
    session.commit()  # yeni döngü + hatırlatma bildirimleri kalıcı olsun
    return {
        "enabled": True,
        "ready": True,
        "respondent": True,
        "cycle_key": cycle.key,
        "opens_at": cycle.opens_at.isoformat(),
        "closes_at": cycle.closes_at.isoformat(),
        "is_open": cycle.is_open,
        "already_submitted": survey_svc.has_submitted(session, cycle.id, user.id),
        "questions": survey_svc.cycle_questions(cycle, cfg),
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
    if not survey_svc.is_respondent(cfg, user):
        raise HTTPException(403, detail="Anketi yöneticiler doldurmaz")
    if not key_configured():
        raise HTTPException(503, detail="Anket şifrelemesi kurulmadı (hazır değil)")
    cycle = survey_svc.get_or_create_active_cycle(session, cfg)
    if not cycle.is_open:
        raise HTTPException(400, detail="Anket döngüsü kapalı")
    # Geriye uyum: eski istemcinin tek 'comment' alanını 'comment' text sorusuna bağla.
    texts = dict(body.texts)
    if body.comment and "comment" not in texts:
        texts["comment"] = body.comment
    try:
        survey_svc.submit_response(session, cfg, cycle, user.id, body.answers, texts)
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


class QuestionItem(BaseModel):
    key: str | None = None  # yoksa label'dan üretilir; varsa SABİT kimlik
    label: str
    type: str = "likert"  # likert | text
    required: bool | None = None


def _slug(s: str) -> str:
    """Etiketten anahtar üret (Türkçe → ascii, boşluk → _)."""
    repl = {"ı": "i", "İ": "i", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u",
            "ş": "s", "Ş": "s", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"}
    s = "".join(repl.get(ch, ch) for ch in s).lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:32] or "soru"


_KEY_RE = re.compile(r"^[a-z0-9_]{1,32}$")


@router.get("/questions")
def get_questions(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Admin: düzenlenebilir soru taslağı (sıralı). Boşsa config'ten seed'lenir."""
    cfg = get_config()
    tmpl = survey_svc.get_template(session, cfg)
    session.commit()  # ilk çağrıda seed edildiyse kalıcı olsun
    return tmpl


@router.put("/questions")
def put_questions(
    items: list[QuestionItem],
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Admin: soru taslağını komple değiştirir. Doğrulama: ≥1 soru, ≥1 likert,
    benzersiz + geçerli anahtar, dolu etiket. DEĞİŞİKLİK BİR SONRAKİ DÖNGÜDE
    geçerli olur — açık/geçmiş döngüler dondurulmuş sorularını korur."""
    if not items:
        raise HTTPException(422, detail="En az bir soru gerekli")
    seen: set[str] = set()
    clean: list[dict] = []
    has_likert = False
    for it in items:
        typ = it.type
        if typ not in ("likert", "text"):
            raise HTTPException(422, detail=f"Geçersiz tip: {typ} (likert | text)")
        label = (it.label or "").strip()
        if not label:
            raise HTTPException(422, detail="Soru etiketi boş olamaz")
        if len(label) > 200:
            raise HTTPException(422, detail="Soru etiketi 200 karakteri aşamaz")
        key = (it.key or "").strip().lower() or _slug(label)
        if not _KEY_RE.match(key):
            raise HTTPException(422, detail=f"Geçersiz anahtar: '{key}' (yalnız a-z 0-9 _, 1-32)")
        if key in seen:
            raise HTTPException(422, detail=f"Anahtar tekrarı: '{key}'")
        seen.add(key)
        if typ == "likert":
            has_likert = True
        required = it.required if it.required is not None else (typ == "likert")
        clean.append({"key": key, "label": label, "type": typ, "required": required})
    if not has_likert:
        raise HTTPException(422, detail="En az bir likert (1-5 puan) sorusu gerekli")
    return survey_svc.set_template(session, clean)


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
