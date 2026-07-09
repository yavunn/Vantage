"""Kullanıcı projeleri (GitHub) + commit listesi + commit pratiği değerlendirme.

Erişim: kullanıcı kendi projelerini yönetir. Admin tüm projeleri/commit
skorlarını görebilir (proje sahibi kararı — bkz. memory commit-score-decision).
Skor kişiye değil commit PRATİĞİNE aittir; ceza dili yok.

İzolasyon: GitHub commitleri `project_commits` tablosuna gider, takım
metriklerini besleyen `commits` tablosuna KARIŞMAZ.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.config import get_config
from app.core.db import get_session
from app.models import CommitReview, Developer, ProjectCommit, User, UserProject
from app.services.commit_review import review_commits
from app.services.github import GitHubError, fetch_commits, parse_repo

router = APIRouter(prefix="/api/projects")


class CreateProjectBody(BaseModel):
    name: str = Field(min_length=1)
    github_url: str = Field(min_length=1)


def _owner_display(session: Session, project: UserProject) -> str:
    user = session.get(User, project.user_id)
    if user is None:
        return "?"
    if user.developer_id:
        dev = session.get(Developer, user.developer_id)
        if dev:
            return dev.display_name
    return user.email.split("@")[0]


def _project_out(session: Session, p: UserProject, with_owner: bool = False) -> dict:
    count = session.scalar(
        select(func.count()).select_from(ProjectCommit).where(ProjectCommit.user_project_id == p.id)
    ) or 0
    latest = session.scalar(
        select(CommitReview).where(CommitReview.user_project_id == p.id).order_by(CommitReview.id.desc())
    )
    out = {
        "id": p.id,
        "name": p.project_name,
        "url": p.source_url,
        "last_run_at": p.last_run_at.isoformat() if p.last_run_at else None,
        "last_status": p.last_status,
        "last_detail": p.last_detail,
        "commit_count": count,
        "latest_score": latest.score if latest else None,
    }
    if with_owner:
        out["owner"] = _owner_display(session, p)
    return out


def _get_project(session: Session, project_id: int, user: User) -> UserProject:
    p = session.get(UserProject, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Proje bulunamadı")
    if p.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu projeye erişim yetkiniz yok")
    return p


def _sync(session: Session, p: UserProject) -> int:
    """GitHub'dan commitleri çeker, upsert eder, durum yazar. Yeni sayı döner."""
    try:
        owner, repo = parse_repo(p.source_url or "")
        commits = fetch_commits(owner, repo, max_commits=100)
    except GitHubError as e:
        p.last_status = "error"
        p.last_detail = str(e)
        p.last_run_at = datetime.now(timezone.utc)
        session.commit()
        raise HTTPException(status_code=400, detail=str(e))

    existing = {
        c.sha for c in session.scalars(
            select(ProjectCommit).where(ProjectCommit.user_project_id == p.id)
        ).all()
    }
    now = datetime.now(timezone.utc)
    added = 0
    for c in commits:
        if not c["sha"] or c["sha"] in existing:
            continue
        session.add(ProjectCommit(
            user_project_id=p.id, sha=c["sha"], author_name=c["author_name"],
            author_email=c["author_email"], message=c["message"],
            committed_at=c["committed_at"], created_at=now,
        ))
        added += 1
    p.last_status = "ok"
    p.last_detail = f"{len(commits)} commit alındı, {added} yeni"
    p.last_run_at = now
    session.commit()
    return added


@router.post("", status_code=201)
def create_project(
    body: CreateProjectBody,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    try:
        parse_repo(body.github_url)  # erken doğrula
    except GitHubError as e:
        raise HTTPException(status_code=422, detail=str(e))
    now = datetime.now(timezone.utc)
    p = UserProject(
        user_id=user.id, project_name=body.name.strip(), source_type="github",
        source_url=body.github_url.strip(), created_at=now, updated_at=now,
    )
    session.add(p)
    session.commit()
    _sync(session, p)  # ilk senkron (hata olursa 400 + kayıt error durumunda kalır)
    return _project_out(session, p)


@router.get("")
def list_projects(
    all: bool = Query(default=False),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    if all and user.role == "admin":
        rows = session.scalars(select(UserProject).order_by(UserProject.id.desc())).all()
        return [_project_out(session, p, with_owner=True) for p in rows]
    rows = session.scalars(
        select(UserProject).where(UserProject.user_id == user.id).order_by(UserProject.id.desc())
    ).all()
    return [_project_out(session, p) for p in rows]


@router.post("/{project_id}/sync")
def sync_project(
    project_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    p = _get_project(session, project_id, user)
    added = _sync(session, p)
    return {"ok": True, "added": added, "project": _project_out(session, p)}


@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    p = _get_project(session, project_id, user)
    session.delete(p)  # cascade project_commits + commit_reviews
    session.commit()
    return {"ok": True}


@router.get("/{project_id}/commits")
def project_commits(
    project_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    p = _get_project(session, project_id, user)
    rows = session.scalars(
        select(ProjectCommit).where(ProjectCommit.user_project_id == p.id)
        .order_by(ProjectCommit.committed_at.desc().nullslast())
    ).all()
    return [{
        "sha": c.sha[:8],
        "message": (c.message or "").strip().splitlines()[0] if c.message else "",
        "author": c.author_name,
        "committed_at": c.committed_at.isoformat() if c.committed_at else None,
    } for c in rows]


@router.post("/{project_id}/review")
def review_project(
    project_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    p = _get_project(session, project_id, user)
    rows = session.scalars(
        select(ProjectCommit).where(ProjectCommit.user_project_id == p.id)
        .order_by(ProjectCommit.committed_at.desc().nullslast())
    ).all()
    if not rows:
        raise HTTPException(status_code=400, detail="Değerlendirilecek commit yok — önce senkronize edin")
    commits = [{"message": c.message, "committed_at": c.committed_at} for c in rows]
    result = review_commits(get_config(), commits)
    review = CommitReview(
        user_project_id=p.id, commit_count=len(rows), score=result["score"],
        summary=result["summary"], details=result.get("details"),
        provider=result["provider"], created_at=datetime.now(timezone.utc),
    )
    session.add(review)
    session.commit()
    return {
        "id": review.id, "score": review.score, "summary": review.summary,
        "details": review.details, "provider": review.provider,
        "commit_count": review.commit_count,
        "created_at": review.created_at.isoformat(),
    }


@router.get("/{project_id}/reviews")
def project_reviews(
    project_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    p = _get_project(session, project_id, user)
    rows = session.scalars(
        select(CommitReview).where(CommitReview.user_project_id == p.id)
        .order_by(CommitReview.id.desc())
    ).all()
    return [{
        "id": r.id, "score": r.score, "summary": r.summary, "details": r.details,
        "provider": r.provider, "commit_count": r.commit_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
