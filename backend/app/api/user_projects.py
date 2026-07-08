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

from app.api.auth import current_user
from app.core.crypto import encrypt_secret
from app.core.db import get_session
from app.models import ProjectCredential, User, UserProject

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
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


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
    project = session.get(UserProject, project_id)
    # Sahiplik: başkasının projesi de "yok" gibi davranır (404) — sızıntı yok
    if project is None or project.user_id != user.id:
        raise HTTPException(404, "Proje bulunamadı")
    if project.credential is not None:
        session.delete(project.credential)
    session.delete(project)
    session.commit()
    return {"id": project_id, "deleted": True}
