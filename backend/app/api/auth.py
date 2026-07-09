"""Kimlik doğrulama ve hesap yönetimi uçları.

- POST /api/auth/login                 : email + parola -> JWT
- GET  /api/auth/me                    : token sahibinin bilgisi
- POST /api/auth/change-password       : çalışan kendi parolasını değiştirir
- GET  /api/auth/employees             : (admin) hesap listesi
- POST /api/auth/employees             : (admin) yeni çalışan + hesap oluştur
- POST /api/auth/employees/{id}/password : (admin) bir çalışanın parolasını sıfırla

Yetki modeli sade: role ∈ {user, admin}. Admin uçları token'daki role ile korunur.
Dashboard uçları (routes.py) ayrı X-Dev-Id katmanını kullanmaya devam eder;
frontend giriş sonrası bu başlığı oturum sahibinin developer_id'siyle doldurur.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models import Developer, TeamMembership, User

router = APIRouter(prefix="/api/auth")


# --- şemalar ------------------------------------------------------------------

class LoginBody(BaseModel):
    email: str
    password: str


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


class CreateEmployeeBody(BaseModel):
    display_name: str = Field(min_length=1)
    email: str
    password: str = Field(min_length=6)
    role: str = "user"  # user | admin
    team_id: int | None = None
    team_role: str = "member"  # member | manager


class SetPasswordBody(BaseModel):
    new_password: str = Field(min_length=6)


# --- yardımcılar --------------------------------------------------------------

def current_user(
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Giriş gerekli")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Oturum geçersiz veya süresi doldu")
    user = session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Hesap bulunamadı veya pasif")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem için yönetici yetkisi gerekli")
    return user


def _user_out(session: Session, user: User) -> dict:
    dev = session.get(Developer, user.developer_id) if user.developer_id else None
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "developer_id": user.developer_id,
        "display_name": dev.display_name if dev else user.email.split("@")[0],
    }


# --- uçlar --------------------------------------------------------------------

@router.post("/login")
def login(body: LoginBody, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-posta ya da parola hatalı")
    token = create_access_token(user.id, user.role)
    return {"access_token": token, "token_type": "bearer", "user": _user_out(session, user)}


@router.get("/me")
def me(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return _user_out(session, user)


@router.post("/change-password")
def change_password(
    body: ChangePasswordBody,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Mevcut parola hatalı")
    user.password_hash = hash_password(body.new_password)
    user.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {"ok": True}


@router.get("/employees")
def list_employees(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    users = session.scalars(select(User).order_by(User.id)).all()
    return [_user_out(session, u) for u in users]


@router.post("/employees", status_code=201)
def create_employee(
    body: CreateEmployeeBody,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    email = body.email.lower()
    if body.role not in ("user", "admin"):
        raise HTTPException(status_code=422, detail="role yalnızca 'user' veya 'admin' olabilir")
    if session.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Bu e-posta zaten kayıtlı")

    dev = Developer(display_name=body.display_name, external_ids={}, anonymizable=True)
    session.add(dev)
    session.flush()  # dev.id

    if body.team_id is not None:
        role = body.team_role if body.team_role in ("member", "manager") else "member"
        session.add(TeamMembership(team_id=body.team_id, developer_id=dev.id, role=role))

    now = datetime.now(timezone.utc)
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=body.role,
        developer_id=dev.id,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.commit()
    return _user_out(session, user)


@router.post("/employees/{user_id}/password")
def set_employee_password(
    user_id: int,
    body: SetPasswordBody,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    user.password_hash = hash_password(body.new_password)
    user.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {"ok": True}
