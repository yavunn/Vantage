"""Anonim memnuniyet anketi servisi.

Anonimlik tasarımı (üç sütun):
1. İki-tablo ayrımı: cevap (SurveyResponse) kimliksiz; "doldurdu mu"
   (SurveyParticipation) ayrı. Ortak/sıralı anahtar yok → eşleştirilemez.
2. Şifreleme: payload save'den önce Fernet ile şifrelenir (SURVEY_ENC_KEY).
3. k-anonimlik: admin sonucu ancak min_responses aşılınca AGREGE görür.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Config
from app.core.survey_crypto import decrypt_payload, encrypt_payload, key_configured
from app.models import (
    SurveyCycle,
    SurveyParticipation,
    SurveyQuestionTemplate,
    SurveyResponse,
    User,
)

# v1: {answers, comment}. v2: {answers, texts, schema_version}. decrypt HER İKİSİNİ
# de işler (geriye uyum); yazma her zaman v2.
SCHEMA_VERSION = 2


def is_respondent(cfg: Config, user: User) -> bool:
    """Kullanıcı anketi DOLDURAN biri mi? Yönetici rolleri (exclude_roles)
    anketi yönetir, doldurmaz; katılım paydasına da sayılmaz."""
    return bool(user.is_active) and user.role not in set(cfg.survey.exclude_roles or [])


def _default_template(cfg: Config) -> list[dict]:
    """config.survey.questions → taslak dict listesi. Eski tek serbest-yorum
    alanının yerine sonda bir 'comment' text sorusu eklenir (v1 uyumu: eski
    payload'ların 'comment' alanı bu anahtara denk gelir)."""
    out = [
        {"key": q.key, "label": q.label, "type": q.type, "required": q.required}
        for q in cfg.survey.questions
    ]
    if not any(q["type"] == "text" for q in out):
        out.append({"key": "comment", "label": "Eklemek istediğin bir şey",
                    "type": "text", "required": False})
    return out


def get_template(session: Session, cfg: Config) -> list[dict]:
    """Düzenlenebilir soru taslağı (sıralı). Boşsa config'ten seed'ler + kalıcılar."""
    rows = session.scalars(
        select(SurveyQuestionTemplate)
        .where(SurveyQuestionTemplate.is_active.is_(True))
        .order_by(SurveyQuestionTemplate.position)
    ).all()
    if rows:
        return [{"key": r.key, "label": r.label, "type": r.type, "required": r.required}
                for r in rows]
    tmpl = _default_template(cfg)
    for i, q in enumerate(tmpl):
        session.add(SurveyQuestionTemplate(
            position=i, key=q["key"], label=q["label"],
            type=q["type"], required=q["required"], is_active=True,
        ))
    session.flush()
    return tmpl


def set_template(session: Session, items: list[dict]) -> list[dict]:
    """Taslağı komple değiştirir (sıra dahil). Doğrulama ÇAĞIRANIN sorumluluğu
    (api katmanı). Açık/geçmiş döngüleri ETKİLEMEZ — onlar snapshot kullanır."""
    for r in session.scalars(select(SurveyQuestionTemplate)).all():
        session.delete(r)
    session.flush()
    out = []
    for i, q in enumerate(items):
        session.add(SurveyQuestionTemplate(
            position=i, key=q["key"], label=q["label"],
            type=q["type"], required=q["required"], is_active=True,
        ))
        out.append({"key": q["key"], "label": q["label"],
                    "type": q["type"], "required": q["required"]})
    session.commit()
    return out


def cycle_questions(cycle: SurveyCycle, cfg: Config) -> list[dict]:
    """Bir döngünün DONDURULMUŞ soruları. Snapshot yoksa (eski döngü) config'e
    düşülür (geriye uyum)."""
    if cycle.questions_json:
        try:
            data = json.loads(cycle.questions_json)
            if isinstance(data, list) and data:
                return data
        except (ValueError, TypeError):
            pass
    return _default_template(cfg)


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
        # Soru taslağını bu döngüye DONDUR — sonraki taslak değişiklikleri
        # açık döngüyü bozmasın (agrega/anonimlik tutarlı kalsın).
        snapshot = get_template(session, cfg)
        cycle = SurveyCycle(
            key=key, opens_at=opens, closes_at=closes, is_open=True,
            questions_json=json.dumps(snapshot, ensure_ascii=False),
        )
        session.add(cycle)
        session.flush()
        _notify_pending(session, cfg, cycle)
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
    answers: dict[str, int], texts: dict[str, str] | None,
) -> None:
    """Cevabı ANONİM + ŞİFRELİ kaydeder. Katılımı ayrı tabloya işler.

    KRİTİK: SurveyResponse satırına kullanıcı kimliği YAZILMAZ. Katılım kaydı
    yalnız (cycle, user) — cevapla bağı yoktur. Tekrar doldurma engellenir.
    Sorular DÖNGÜNÜN snapshot'ından okunur (config'ten değil)."""
    if not key_configured():
        raise RuntimeError("SURVEY_ENC_KEY yok — anket şifrelenemez (hazır değil).")
    if has_submitted(session, cycle.id, user_id):
        raise ValueError("already_submitted")

    questions = cycle_questions(cycle, cfg)
    likert_keys = {q["key"] for q in questions if q["type"] == "likert"}
    text_keys = {q["key"] for q in questions if q["type"] == "text"}
    clean_answers = {
        k: int(v) for k, v in (answers or {}).items()
        if k in likert_keys and 1 <= int(v) <= 5
    }
    clean_texts = {}
    for k, v in (texts or {}).items():
        if k in text_keys and isinstance(v, str) and v.strip():
            clean_texts[k] = v.strip()[:2000]
    payload = {
        "answers": clean_answers,
        "texts": clean_texts,
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


def _eligible_user_count(session: Session, cfg: Config) -> int:
    """Katılım paydası: aktif VE anketi dolduran (yönetici rolleri hariç)
    kullanıcı sayısı. Böylece admin hariç tutulunca oran %100'e ulaşabilir."""
    excl = set(cfg.survey.exclude_roles or [])
    stmt = select(func.count()).select_from(User).where(User.is_active.is_(True))
    if excl:
        stmt = stmt.where(User.role.notin_(excl))
    return session.scalar(stmt) or 0


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
    active = _eligible_user_count(session, cfg)
    # Sorular DÖNGÜNÜN snapshot'ından (config'ten değil) — geçmiş döngü kendi
    # sorularına göre doğru agrega edilir.
    questions = cycle_questions(cycle, cfg)
    likert_keys = [q["key"] for q in questions if q["type"] == "likert"]
    text_qs = [q for q in questions if q["type"] == "text"]
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
        "questions": [{"key": q["key"], "label": q["label"], "type": q["type"]}
                      for q in questions],
    }
    # k-anonimlik: eşik altında agrega bile kişiyi ele verebilir → maskele.
    if resp_count < cfg.survey.min_responses:
        base["masked"] = True
        return base
    base["masked"] = False

    sums = {k: 0 for k in likert_keys}
    counts = {k: 0 for k in likert_keys}
    dist = {k: {i: 0 for i in range(1, 6)} for k in likert_keys}
    # Her text sorusu için AYRI yorum kovası (karışık gösterilecek).
    text_map: dict[str, list[str]] = {q["key"]: [] for q in text_qs}
    # v1 payload'ın tek 'comment' alanını bağlayacağımız kova: 'comment' anahtarı
    # varsa oraya, yoksa ilk text sorusuna.
    v1_key = "comment" if "comment" in text_map else (text_qs[0]["key"] if text_qs else None)

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
        # v2: sorulara göre metinler
        for k, v in (data.get("texts") or {}).items():
            if k in text_map and isinstance(v, str) and v.strip():
                text_map[k].append(v.strip())
        # v1 geriye uyum: tek 'comment'
        c = data.get("comment")
        if c and v1_key:
            text_map[v1_key].append(str(c))

    base["scores"] = [
        {
            "key": k,
            "average": round(sums[k] / counts[k], 2) if counts[k] else None,
            "count": counts[k],
            "distribution": dist[k],
        }
        for k in likert_keys
    ]
    # Her text sorusu ayrı blok, KARIŞIK sırada (insert sırası sızmasın).
    texts_out = []
    for q in text_qs:
        cs = text_map.get(q["key"], [])
        random.shuffle(cs)
        texts_out.append({"key": q["key"], "label": q["label"], "comments": cs})
    base["texts"] = texts_out
    # Geriye uyumlu düz liste (tüm yorumlar birleşik, karışık) — eski tüketiciler.
    flat = [c for t in texts_out for c in t["comments"]]
    random.shuffle(flat)
    base["comments"] = flat
    return base


def _notify_pending(session: Session, cfg: Config, cycle: SurveyCycle) -> int:
    """Yeni döngüde doldurmamış KATILIMCI kullanıcılara bir kez nötr hatırlatma.
    Yönetici rolleri (exclude_roles) hatırlatma almaz. dedup: döngü başına tek.
    commit ÇAĞIRMAZ (çağıran commit eder)."""
    from app.services.notifications import notify

    excl = set(cfg.survey.exclude_roles or [])
    submitted = {
        p.user_id for p in session.scalars(
            select(SurveyParticipation).where(SurveyParticipation.cycle_id == cycle.id)
        )
    }
    count = 0
    for u in session.scalars(select(User).where(User.is_active.is_(True))):
        if u.id in submitted or u.role in excl:
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
