"""Kullanıcının kendi dış servis anahtarları (şu an: GitHub PAT).

Sınır: herkes YALNIZ kendi anahtarını yönetir. Admin bile başkasının anahtarını
okuyamaz/yazamaz — kişisel bir kimlik bilgisi, yönetilecek bir ayar değil.
Anahtarın düz metni hiçbir yanıtta dönmez; yalnız "tanımlı mı" ve son 4 karakter.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.db import get_session
from app.models import User
from app.services.credentials import GITHUB, set_token, status
from app.services.github import GitHubError, check_repo_access

router = APIRouter(prefix="/api/me/credentials")


class GithubTokenBody(BaseModel):
    # Boş dize = bağlantıyı kaldır (anahtarı sil).
    token: str = ""


@router.get("/github")
def get_github_credential(
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    return status(session, user.id, GITHUB)


@router.put("/github")
def put_github_credential(
    body: GithubTokenBody,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Anahtarı kaydeder. Kaydetmeden ÖNCE GitHub'a doğrular: geçersiz bir
    anahtarı sessizce saklayıp kullanıcıyı ilk senkronda şaşırtmak yerine
    hatayı burada gösterir."""
    token = (body.token or "").strip()
    if token:
        try:
            # Kimlik doğrulaması yeter; erişilebilir bir repo aramıyoruz.
            check_repo_access("github", "docs", token=token)
        except GitHubError as e:
            # 404 = anahtar GEÇERLİ ama bu repoyu göremiyor; sorun değil.
            # 401 = anahtar geçersiz → kullanıcıya söyle.
            if "geçersiz" in str(e).lower() or "süresi dolmuş" in str(e).lower():
                raise HTTPException(status_code=422, detail=str(e)) from e
    return set_token(session, user.id, token, GITHUB)
