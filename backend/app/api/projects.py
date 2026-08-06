"""Kullanıcı projeleri (GitHub) + commit listesi + commit pratiği değerlendirme.

Erişim: kullanıcı kendi projelerini ekler/yönetir. Admin proje EKLEMEZ ama
TÜM kullanıcıların projelerini/commit skorlarını doğrudan görür (proje sahibi
kararı — bkz. memory commit-score-decision). Skor kişiye değil commit
PRATİĞİNE aittir; ceza dili yok.

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
from app.core.i18n import tr_error
from app.models import CommitReview, Developer, ProjectCommit, User, UserProject
from app.services.commit_review import review_commits
from app.services.credentials import get_token
from app.services.github import GitHubError, check_repo_access, fetch_commits, parse_repo
from app.services.local_git import LocalRepoError, fetch_local_commits, resolve_local_repo

router = APIRouter(prefix="/api/projects")

SOURCE_TYPES = ("github", "local")


class CreateProjectBody(BaseModel):
    name: str = Field(min_length=1)
    # github | local. Varsayılan "github": eski istemciler yalnız github_url
    # gönderiyordu, onlar bozulmasın.
    source_type: str = "github"
    github_url: str | None = None
    # Yerel kaynak: sunucudaki klasör yolu. İzinli kökler config'te
    # (projects.local_roots) — bkz. services/local_git.resolve_local_repo.
    local_path: str | None = None


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
        "source_type": p.source_type or "github",
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
        raise HTTPException(status_code=404, detail=tr_error("Proje bulunamadı"))
    if p.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail=tr_error("Bu projeye erişim yetkiniz yok"))
    return p


def _fetch_commits_for(session: Session, p: UserProject) -> list[dict]:
    """Projenin kaynağına göre commitleri getirir. İki kaynak da AYNI şekilde
    (sha/author_name/author_email/message/committed_at) döner, böylece _sync
    kaynak ayrımı yapmak zorunda kalmaz.

    GitHub'da projenin SAHİBİNİN anahtarı kullanılır — senkronu tetikleyenin
    değil. Admin başkasının projesini senkronlarken kendi yetkisini ödünç
    vermemeli; proje hangi erişimle eklendiyse onunla tazelenir.
    """
    cfg = get_config()
    if (p.source_type or "github") == "local":
        path = resolve_local_repo(p.source_url or "", cfg)
        return fetch_local_commits(path, cfg.projects.max_local_commits)
    owner, repo = parse_repo(p.source_url or "")
    return fetch_commits(owner, repo, max_commits=100,
                         token=get_token(session, p.user_id))


def _sync(session: Session, p: UserProject) -> int:
    """Kaynaktan commitleri çeker, upsert eder, durum yazar. Yeni sayı döner."""
    try:
        commits = _fetch_commits_for(session, p)
    except (GitHubError, LocalRepoError) as e:
        p.last_status = "error"
        p.last_detail = str(e)
        p.last_run_at = datetime.now(timezone.utc)
        session.commit()
        raise HTTPException(status_code=400, detail=str(e)) from e

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
    # Yönetici proje EKLEMEZ — projeleri yalnız görüntüler (herkesinkini görür).
    if user.role == "admin":
        raise HTTPException(status_code=403,
                            detail=tr_error("Yöneticiler proje eklemez — projeleri yalnız görüntüler."))
    kaynak = (body.source_type or "github").strip().lower()
    if kaynak not in SOURCE_TYPES:
        raise HTTPException(status_code=422,
                            detail=tr_error("source_type yalnızca {list} olabilir",
                                            list=", ".join(SOURCE_TYPES)))

    # Kaynağa göre doğrula ve saklanacak referansı belirle. Yerel yol doğrulaması
    # EKLEMEDE yapılır ki kullanıcı hatayı anında görsün; _sync her koşuda
    # yeniden doğrular (izinli kökler sonradan daraltılmış olabilir).
    if kaynak == "local":
        try:
            referans = str(resolve_local_repo(body.local_path or "", get_config()))
        except LocalRepoError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    else:
        try:
            owner, repo = parse_repo(body.github_url or "")  # biçim doğrula
        except GitHubError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        # YETKİ DOĞRULAMASI: repo, EKLEYENİN kendi anahtarıyla görülebiliyor mu?
        # Bu kontrol olmadan kullanıcı, sunucu token'ının eriştiği herhangi bir
        # özel repoyu (başka bir çalışanınkini) kendi projesi diye ekleyip
        # commit mesajlarını okuyabiliyordu.
        try:
            check_repo_access(owner, repo, token=get_token(session, user.id))
        except GitHubError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        referans = (body.github_url or "").strip()

    now = datetime.now(timezone.utc)
    p = UserProject(
        user_id=user.id, project_name=body.name.strip(), source_type=kaynak,
        source_url=referans, created_at=now, updated_at=now,
    )
    session.add(p)
    session.commit()
    _sync(session, p)  # ilk senkron (hata olursa 400 + kayıt error durumunda kalır)
    return _project_out(session, p)


@router.get("")
def list_projects(
    all: bool = Query(default=False),  # geriye uyum; admin her hâlükârda hepsini görür
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    # Admin TÜM projeleri doğrudan görür (sahip adıyla). Kullanıcı yalnız kendininki.
    if user.role == "admin":
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
        raise HTTPException(status_code=400, detail=tr_error("Değerlendirilecek commit yok — önce senkronize edin"))
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
