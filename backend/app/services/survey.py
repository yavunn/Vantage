"""Anonim memnuniyet anketi servisi.

Anonimlik tasarımı (üç sütun):
1. İki-tablo ayrımı: cevap (SurveyResponse) kimliksiz; "doldurdu mu"
   (SurveyParticipation) ayrı. Ortak/sıralı anahtar yok → eşleştirilemez.
2. Şifreleme: payload save'den önce Fernet ile şifrelenir (SURVEY_ENC_KEY).
3. k-anonimlik: admin sonucu ancak min_responses aşılınca AGREGE görür.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Config
from app.core.survey_crypto import decrypt_payload, encrypt_payload, key_configured
from app.models import SurveyCycle, SurveyParticipation, SurveyResponse, User

SCHEMA_VERSION = 1


def _window_for(today: date, epoch: date, interval_days: int) -> tuple[date, date]:
    """Bugünün ait olduğu döngü penceresi [opens, closes) — epoch hizalı."""
    if today < epoch:
        # Epoch gelecekteyse ilk pencereyi kullan (negatif indeks üretme).
        return epoch, epoch + timedelta(days=interval_days)
    idx = (today - epoch).days // interval_days
    opens = epoch + timedelta(days=idx * interval_days)
    return opens, opens + timedelta(days=interval_days)


def _cycle_key(opens: date, closes: date) -> str:
    return f"{opens.strftime('%Y%m%d')}-{(closes - timedelta(days=1)).strftime('%Y%m%d')}"


def get_or_create_active_cycle(
    session: Session, cfg: Config, today: date | None = None
) -> SurveyCycle:
    """Bugüne denk gelen döngüyü döner; yoksa oluşturur. Yeni oluşturulduğunda
    doldurmamış aktif kullanıcılara bir kez hatırlatma bildirimi düşer."""
    today = today or date.today()
    opens, closes = _window_for(today, cfg.survey.epoch, cfg.survey.interval_days)
    key = _cycle_key(opens, closes)
    cycle = session.scalar(select(SurveyCycle).where(SurveyCycle.key == key))
    if cycle is None:
        cycle = SurveyCycle(key=key, opens_at=opens, closes_at=closes, is_open=True)
        session.add(cycle)
        session.flush()
        _notify_pending(session, cycle)
    return cycle


def has_submitted(session: Session, cycle_id: int, user_id: int) -> bool:
    return session.scalar(
        select(SurveyParticipation.id).where(
            SurveyParticipation.cycle_id == cycle_id,
            SurveyParticipation.user_id == user_id,
        )
    ) is not None


def submit_response(
    session: Session, cfg: Config, cycle: SurveyCycle, user_id: int,
    answers: dict[str, int], comment: str | None,
) -> None:
    """Cevabı ANONİM + ŞİFRELİ kaydeder. Katılımı ayrı tabloya işler.

    KRİTİK: SurveyResponse satırına kullanıcı kimliği YAZILMAZ. Katılım kaydı
    yalnız (cycle, user) — cevapla bağı yoktur. Tekrar doldurma engellenir."""
    if not key_configured():
        raise RuntimeError("SURVEY_ENC_KEY yok — anket şifrelenemez (hazır değil).")
    if has_submitted(session, cycle.id, user_id):
        raise ValueError("already_submitted")

    valid_keys = {q.key for q in cfg.survey.questions if q.type == "likert"}
    clean = {k: int(v) for k, v in answers.items() if k in valid_keys and 1 <= int(v) <= 5}
    payload = {
        "answers": clean,
        "comment": (comment or "").strip()[:2000] or None,
        "schema_version": SCHEMA_VERSION,
    }
    # 1) Kimliksiz + şifreli cevap.
    session.add(SurveyResponse(
        cycle_id=cycle.id,
        ciphertext=encrypt_payload(payload),
        schema_version=SCHEMA_VERSION,
    ))
    # 2) Katılım defteri (kim doldurdu — ama cevabı değil).
    session.add(SurveyParticipation(cycle_id=cycle.id, user_id=user_id))
    session.commit()


def _active_user_count(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    ) or 0


def aggregate_results(session: Session, cfg: Config, cycle: SurveyCycle) -> dict:
    """Bir döngünün AGREGE sonucu. k-eşiği altında maskeli döner (kişi ifşası
    önleme). Ham per-cevap ASLA dönmez; yorumlar yalnız eşik aşılınca ve
    KARIŞIK sırada (insert sırası sızmasın)."""
    resp_count = session.scalar(
        select(func.count()).select_from(SurveyResponse).where(
            SurveyResponse.cycle_id == cycle.id
        )
    ) or 0
    part_count = session.scalar(
        select(func.count()).select_from(SurveyParticipation).where(
            SurveyParticipation.cycle_id == cycle.id
        )
    ) or 0
    active = _active_user_count(session)
    base = {
        "cycle_key": cycle.key,
        "opens_at": cycle.opens_at.isoformat(),
        "closes_at": cycle.closes_at.isoformat(),
        "is_open": cycle.is_open,
        "response_count": resp_count,
        "participation": part_count,
        "active_users": active,
        "participation_rate": round(part_count / active, 3) if active else None,
        "min_responses": cfg.survey.min_responses,
        "questions": [{"key": q.key, "label": q.label} for q in cfg.survey.questions
                      if q.type == "likert"],
    }
    # k-anonimlik: eşik altında agrega bile kişiyi ele verebilir → maskele.
    if resp_count < cfg.survey.min_responses:
        base["masked"] = True
        return base
    base["masked"] = False

    likert_keys = [q.key for q in cfg.survey.questions if q.type == "likert"]
    sums = {k: 0 for k in likert_keys}
    counts = {k: 0 for k in likert_keys}
    dist = {k: {i: 0 for i in range(1, 6)} for k in likert_keys}
    comments: list[str] = []

    for row in session.scalars(
        select(SurveyResponse).where(SurveyResponse.cycle_id == cycle.id)
    ):
        try:
            data = decrypt_payload(row.ciphertext)
        except Exception:
            continue  # bozuk/eski anahtar — atla, çökme
        for k, v in (data.get("answers") or {}).items():
            if k in sums and isinstance(v, int) and 1 <= v <= 5:
                sums[k] += v
                counts[k] += 1
                dist[k][v] += 1
        c = data.get("comment")
        if c:
            comments.append(str(c))

    base["scores"] = [
        {
            "key": k,
            "average": round(sums[k] / counts[k], 2) if counts[k] else None,
            "count": counts[k],
            "distribution": dist[k],
        }
        for k in likert_keys
    ]
    random.shuffle(comments)  # sıra sızmasın
    base["comments"] = comments
    return base


def _notify_pending(session: Session, cycle: SurveyCycle) -> int:
    """Yeni döngüde doldurmamış aktif kullanıcılara bir kez nötr hatırlatma.
    dedup: döngü başına tek. commit ÇAĞIRMAZ (çağıran commit eder)."""
    from app.services.notifications import notify

    submitted = {
        p.user_id for p in session.scalars(
            select(SurveyParticipation).where(SurveyParticipation.cycle_id == cycle.id)
        )
    }
    count = 0
    for u in session.scalars(select(User).where(User.is_active.is_(True))):
        if u.id in submitted:
            continue
        n = notify(
            session, u.id,
            kind="survey",
            title="Yeni memnuniyet anketi açıldı",
            body="İki haftalık anonim memnuniyet anketi açıldı. Görüşün bize yol "
                 "gösterir — cevapların tamamen anonimdir, kimseye bağlanmaz.",
            dedup_key=f"survey:{cycle.key}",
            link="/?survey=1",
        )
        if n is not None:
            count += 1
    return count
