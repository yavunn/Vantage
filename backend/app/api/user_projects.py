"""Kullanıcının proje bağlama uçları (Faz 3).

Güvenlik kuralları:
- Tüm uçlar giriş ister (JWT); kimliksiz 401.
- Token yalnız Fernet ile şifreli yazılır; HİÇBİR response/log'da dönmez —
  liste yalnız "bağlı mı" bilgisini verir.
- Sahiplik: kullanıcı yalnız KENDİ projelerini görür/siler. Başkasının
  projesi 404 döner — varlığı da sızdırılmaz.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import json

from app.api.auth import current_user
from app.core.config import get_config
from app.core.crypto import encrypt_secret
from app.core.db import get_session
from app.models import Commit, Developer, MetricResult, ProjectCredential, User, UserProject

router = APIRouter(prefix="/api/user/projects")

SOURCE_TYPES = ("github", "gitlab", "jira", "trello")


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "Kimlik gerekli (Bearer token)")
    return user


def _project_payload(p: UserProject) -> dict:
    """Credential ASLA payload'a girmez; yalnız bağlı/değil durumu."""
    return {
        "id": p.id,
        "project_name": p.project_name,
        "source_type": p.source_type,
        "source_url": p.source_url,
        "connected": p.credential is not None,
        "last_run_at": p.last_run_at.isoformat() if p.last_run_at else None,
        "last_status": p.last_status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _owned_project(
    project_id: int, user: User, session: Session
) -> UserProject:
    """Sahiplik: başkasının projesi de 'yok' gibi davranır (404)."""
    project = session.get(UserProject, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(404, "Proje bulunamadı")
    return project


class ProjectCreate(BaseModel):
    project_name: str = Field(min_length=1, max_length=200)
    source_type: str
    source_url: str = Field(min_length=1, max_length=500)
    token: str = Field(min_length=1)


@router.post("", status_code=201)
def create_project(
    body: ProjectCreate,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if body.source_type not in SOURCE_TYPES:
        raise HTTPException(422, f"source_type şunlardan biri olmalı: {', '.join(SOURCE_TYPES)}")
    project = UserProject(
        user_id=user.id,
        project_name=body.project_name,
        source_type=body.source_type,
        source_url=body.source_url,
    )
    session.add(project)
    session.flush()
    session.add(
        ProjectCredential(project_id=project.id, encrypted_value=encrypt_secret(body.token))
    )
    session.commit()
    return _project_payload(project)


@router.get("")
def list_projects(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    projects = session.scalars(
        select(UserProject).where(UserProject.user_id == user.id).order_by(UserProject.id)
    ).all()
    return [_project_payload(p) for p in projects]


@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    project = _owned_project(project_id, user, session)
    if project.credential is not None:
        session.delete(project.credential)
    session.delete(project)
    session.commit()
    return {"id": project_id, "deleted": True}


# --- Faz 4: analiz -------------------------------------------------------------

# Hijyen sinyali eşikleri — destek dili: kırmızı "süreç zorlanıyor" demektir,
# ceza değil. Kişi bazlı değil, proje bazlıdır.
HYGIENE_META = {
    "commit_message_convention": {
        "name": "Commit mesajı konvansiyonu",
        "description": "feat/fix/chore... önekli mesaj oranı — takım hijyeni",
        "higher_is_better": True, "green": 0.8, "red": 0.5,
    },
    "large_commit_share": {
        "name": "Geniş commit oranı",
        "description": "10+ dosyaya dokunan commit oranı — küçük adımlar akışı kolaylaştırır",
        "higher_is_better": False, "green": 0.15, "red": 0.35,
    },
}
HYGIENE_LABELS = {
    "green": "Akıyor",
    "yellow": "İzlenmeli",
    "red": "Zorlanıyor — yardım gerekebilir",
    "insufficient_data": "Veri yetersiz",
}


def _hygiene_status(key: str, value: float | None, completeness: float) -> str:
    cfg = get_config()
    meta = HYGIENE_META[key]
    if value is None or completeness < cfg.health_thresholds.data_completeness_min:
        return "insufficient_data"
    if meta["higher_is_better"]:
        if value >= meta["green"]:
            return "green"
        if value <= meta["red"]:
            return "red"
    else:
        if value <= meta["green"]:
            return "green"
        if value >= meta["red"]:
            return "red"
    return "yellow"


@router.post("/{project_id}/analyze", status_code=202)
def start_analysis(
    project_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    from app.services.analysis import schedule_analysis

    project = _owned_project(project_id, user, session)
    if project.credential is None:
        raise HTTPException(400, "Projeye bağlı credential yok")
    if project.last_status in ("pending", "running"):
        return {"id": project.id, "status": project.last_status}
    project.last_status = "pending"
    session.commit()
    schedule_analysis(project.id)
    return {"id": project.id, "status": "pending"}


@router.get("/{project_id}/analysis")
def analysis_status(
    project_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    project = _owned_project(project_id, user, session)
    rows = session.scalars(
        select(MetricResult).where(
            MetricResult.scope == "project", MetricResult.scope_id == project.id
        )
    ).all()
    metrics = []
    for row in rows:
        meta = HYGIENE_META.get(row.metric_key)
        if meta is None:
            continue
        status = _hygiene_status(row.metric_key, row.value, row.data_completeness)
        metrics.append(
            {
                "key": row.metric_key,
                "name": meta["name"],
                "description": meta["description"],
                "value": row.value,
                "status": status,
                "status_label": HYGIENE_LABELS[status],
                "data_completeness": row.data_completeness,
                "source_layer": row.source_layer,
                "period": row.period,
            }
        )
    detail = None
    if project.last_detail:
        try:
            detail = json.loads(project.last_detail)
        except ValueError:
            detail = project.last_detail  # hata mesajı düz metin olabilir
    return {
        "id": project.id,
        "status": project.last_status,
        "last_run_at": project.last_run_at.isoformat() if project.last_run_at else None,
        "detail": detail,
        "metrics": metrics,
        "note": "Sinyaller proje/takım hijyenidir; kişi puanı değildir. "
                "Kırmızı 'yardım gerekebilir' demektir.",
    }


@router.get("/{project_id}/commits")
def project_commits(
    project_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Projenin son commit'leri (operasyonel görünüm). Kişi bazlı sayaç ya da
    sıralama üretmez; anonim modda yazar adı maskelenir."""
    from app.api.routes import _mask_name
    from app.services.analysis import CONVENTIONAL_RE

    cfg = get_config()
    project = _owned_project(project_id, user, session)
    if project.repo_id is None:
        return []
    commits = session.scalars(
        select(Commit)
        .where(Commit.repo_id == project.repo_id)
        .order_by(Commit.committed_at.desc().nulls_last())
        .limit(50)
    ).all()
    out = []
    for c in commits:
        author = session.get(Developer, c.author_id) if c.author_id else None
        out.append(
            {
                "sha": c.sha[:8],
                "message": c.message,
                "committed_at": c.committed_at.isoformat() if c.committed_at else None,
                "author": _mask_name(author, cfg) if author else None,
                "files_changed": len(c.changed_files) if c.changed_files is not None else None,
                "additions": c.additions,
                "deletions": c.deletions,
                "conventional": bool(CONVENTIONAL_RE.match(c.message)) if c.message else None,
            }
        )
    return out
