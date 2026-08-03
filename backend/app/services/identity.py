"""Kişi kayıtlarının birleştirilmesi.

NEDEN: Aynı insan kaynaklarda birden çok kimlikle görünür — git'te e-posta
(üstelik GitHub'ın `…@users.noreply.github.com` adresi ayrı bir e-postadır),
Trello'da üye id'si. İngest bunları eşleştiremez ve iki ayrı Developer açar.
Sonuç sessiz ve yanıltıcıdır: takım kadrosu şişer, WIP kişi başına bölündüğü
için metrik olduğundan İYİ görünür; commit'ler bir kayda, görevler diğerine
düşer ve hiçbir kişi bazlı görünüm doğru çıkmaz.

KRİTİK: kopyayı silmeden ÖNCE developers.id'ye bakan TÜM referanslar taşınmalı.
Eksik bırakılan tek tablo, PostgreSQL'de foreign key hatası (SQLite'ta sessiz
yetim kayıt) demektir. Bu yüzden liste tek yerde tutulur ve testi vardır.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CodeAnalysis,
    Commit,
    Developer,
    Leave,
    PRReview,
    PullRequest,
    Task,
    TeamMembership,
    User,
)

# (model, developers.id'ye bakan kolon) — models/__init__.py'deki
# ForeignKey("developers.id") geçen HER yer burada olmalı.
_REFERANSLAR = (
    (Commit, "author_id"),
    (PullRequest, "author_id"),
    (PRReview, "reviewer_id"),
    (Task, "assignee_id"),
    (Leave, "developer_id"),
    (CodeAnalysis, "developer_id"),
    (User, "developer_id"),
)


class MergeError(ValueError):
    """Birleştirme yapılamaz (aynı kayıt, eksik kayıt vb.)."""


def merge_developers(session: Session, target_id: int, duplicate_id: int) -> dict:
    """`duplicate_id`'yi `target_id` içine birleştirir ve kopyayı siler.

    Geri alınamaz: çağıran taraf onay almalı. Döner: neyin taşındığı (sayılarla),
    ki arayüz "5 commit ve 2 görev taşındı" diyebilsin — sessiz başarı yok.
    """
    if target_id == duplicate_id:
        raise MergeError("Bir kayıt kendisiyle birleştirilemez.")
    target = session.get(Developer, target_id)
    duplicate = session.get(Developer, duplicate_id)
    if target is None or duplicate is None:
        raise MergeError("Kişi bulunamadı.")

    moved: dict[str, int] = {}
    for model, column in _REFERANSLAR:
        col = getattr(model, column)
        rows = session.scalars(select(model).where(col == duplicate.id)).all()
        for row in rows:
            setattr(row, column, target.id)
        if rows:
            moved[model.__tablename__] = len(rows)

    # Takım üyeliği ayrı: hedef zaten o takımdaysa kopya üyelik TAŞINMAZ, silinir
    # (team_id + developer_id benzersiz).
    hedef_takimlar = {
        m.team_id for m in session.scalars(
            select(TeamMembership).where(TeamMembership.developer_id == target.id)
        )
    }
    tasinan_uyelik = 0
    for m in session.scalars(
        select(TeamMembership).where(TeamMembership.developer_id == duplicate.id)
    ):
        if m.team_id in hedef_takimlar:
            session.delete(m)
        else:
            m.developer_id = target.id
            tasinan_uyelik += 1
    if tasinan_uyelik:
        moved["team_memberships"] = tasinan_uyelik

    # Kopyanın kimlikleri hedefe geçsin ki bir sonraki senkron aynı kopyayı
    # yeniden AÇMASIN. Hedefte zaten varsa hedefinki korunur.
    ext = dict(target.external_ids or {})
    for k, v in (duplicate.external_ids or {}).items():
        ext.setdefault(k, v)
    target.external_ids = ext

    session.flush()
    session.delete(duplicate)
    session.commit()
    return {
        "ok": True,
        "target_id": target.id,
        "merged_developer_id": duplicate_id,
        "moved": moved,
        "task_identities": {k: v for k, v in ext.items() if k != "git"},
    }
