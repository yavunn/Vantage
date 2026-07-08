"""Kimlik uçları (Faz 1): login + refresh.

- Parola bcrypt hash ile doğrulanır; hangi alanın hatalı olduğu söylenmez.
- Token'lar yalnızca response gövdesinde döner; URL/log'a yazılmaz.
- current_user: Bearer token'dan User çözer. routes.current_dev bunun
  üstünden Developer'a iner — kimlik TEK noktadan akar, paralel sistem yok.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models import User

router = APIRouter(prefix="/api/auth")


def current_user(
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> User | None:
    """Bearer token → User. Başlık yoksa None (açık takım uçları için);
    başlık var ama token geçersiz/expired ise 401."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    user_id = decode_token(token, expected_type="access")
    if user_id is None:
        raise HTTPException(401, "Geçersiz ya da süresi dolmuş token")
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Hesap bulunamadı ya da pasif")
    return user


@router.post("/login")
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    user = session.scalars(select(User).where(User.email == form.username)).first()
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, "E-posta ya da parola hatalı")
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
    }


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
def refresh(body: RefreshRequest, session: Session = Depends(get_session)):
    user_id = decode_token(body.refresh_token, expected_type="refresh")
    if user_id is None:
        raise HTTPException(401, "Geçersiz ya da süresi dolmuş refresh token")
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Hesap bulunamadı ya da pasif")
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}
