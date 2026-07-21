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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models import (
    Commit,
    Developer,
    PRReview,
    PullRequest,
    Task,
    Team,
    TeamMembership,
    User,
)

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


class UpdateEmployeeBody(BaseModel):
    role: str | None = None          # user | admin
    is_active: bool | None = None


class SetupBody(BaseModel):
    display_name: str = Field(min_length=1)
    email: str
    password: str = Field(min_length=6)


class MembershipBody(BaseModel):
    team_id: int
    role: str = "member"  # member | manager


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


def current_user_optional(
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> User | None:
    """current_user gibi ama token yoksa/geçersizse 401 atmaz, None döner.
    X-Dev-Id kimliğiyle çalışan uçların JWT'yi opsiyonel okuması için."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        return None
    user = session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        return None
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem için yönetici yetkisi gerekli")
    return user


def _active_admin_count(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(User).where(
            User.role == "admin", User.is_active.is_(True)
        )
    ) or 0


def _developer_has_history(session: Session, developer_id: int) -> bool:
    """Bu geliştiriciye bağlı metrik verisi (commit/PR/review/task) var mı?
    Varsa hesap silinse de geliştirici kaydı korunur (geçmiş bozulmasın)."""
    checks = (
        select(Commit.id).where(Commit.author_id == developer_id),
        select(PullRequest.id).where(PullRequest.author_id == developer_id),
        select(PRReview.id).where(PRReview.reviewer_id == developer_id),
        select(Task.id).where(Task.assignee_id == developer_id),
    )
    return any(session.scalar(q.limit(1)) is not None for q in checks)


def _memberships_out(session: Session, developer_id: int | None) -> list[dict]:
    if developer_id is None:
        return []
    rows = session.scalars(
        select(TeamMembership).where(TeamMembership.developer_id == developer_id)
    ).all()
    out = []
    for m in rows:
        team = session.get(Team, m.team_id)
        out.append({"team_id": m.team_id, "team_name": team.name if team else "?", "role": m.role})
    return out


def _user_out(session: Session, user: User) -> dict:
    dev = session.get(Developer, user.developer_id) if user.developer_id else None
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "developer_id": user.developer_id,
        "display_name": dev.display_name if dev else user.email.split("@")[0],
        "teams": _memberships_out(session, user.developer_id),
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
    user.must_change_password = False
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
        must_change_password=True,  # admin geçici parola verdi; ilk girişte değiştir
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.commit()
    return _user_out(session, user)


@router.patch("/employees/{user_id}")
def update_employee(
    user_id: int,
    body: UpdateEmployeeBody,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    # Kendini kilitleme koruması: admin kendi rolünü/aktifliğini bu uçtan bozamaz.
    if user.id == admin.id and (
        (body.role is not None and body.role != user.role)
        or (body.is_active is not None and body.is_active != user.is_active)
    ):
        raise HTTPException(
            status_code=400,
            detail="Kendi rolünü ya da aktiflik durumunu buradan değiştiremezsin",
        )
    # Son aktif yöneticiyi düşürme/pasifleştirme koruması (kilitlenme önleme).
    demoting = body.role is not None and body.role != "admin" and user.role == "admin"
    deactivating = body.is_active is False and user.is_active and user.role == "admin"
    if (demoting or deactivating) and _active_admin_count(session) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Sistemde en az bir aktif yönetici kalmalı",
        )
    if body.role is not None:
        if body.role not in ("user", "admin"):
            raise HTTPException(status_code=422, detail="role yalnızca 'user' veya 'admin' olabilir")
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    user.updated_at = datetime.now(timezone.utc)
    session.commit()
    return _user_out(session, user)


@router.delete("/employees/{user_id}")
def delete_employee(
    user_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Kendi hesabını silemezsin")
    if user.role == "admin" and _active_admin_count(session) <= 1:
        raise HTTPException(status_code=400, detail="Sistemde en az bir aktif yönetici kalmalı")

    dev_id = user.developer_id
    session.delete(user)
    # Geliştiricinin metrik geçmişi yoksa developer + üyelikleri de temizlenir;
    # geçmiş varsa developer korunur (commit/PR/task bağları bozulmasın).
    developer_removed = False
    if dev_id is not None and not _developer_has_history(session, dev_id):
        for m in session.scalars(
            select(TeamMembership).where(TeamMembership.developer_id == dev_id)
        ).all():
            session.delete(m)
        dev = session.get(Developer, dev_id)
        if dev is not None:
            session.delete(dev)
            developer_removed = True
    session.commit()
    return {"ok": True, "developer_removed": developer_removed}


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
    user.must_change_password = True  # sıfırlanan parola geçici; kullanıcı değiştirsin
    user.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {"ok": True}


# --- takım üyeliği yönetimi (admin) -------------------------------------------

@router.post("/employees/{user_id}/memberships", status_code=201)
def add_membership(
    user_id: int,
    body: MembershipBody,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if user is None or user.developer_id is None:
        raise HTTPException(status_code=404, detail="Hesap bir geliştiriciye bağlı değil")
    if session.get(Team, body.team_id) is None:
        raise HTTPException(status_code=404, detail="Takım bulunamadı")
    role = body.role if body.role in ("member", "manager") else "member"
    existing = session.scalar(
        select(TeamMembership).where(
            TeamMembership.developer_id == user.developer_id,
            TeamMembership.team_id == body.team_id,
        )
    )
    if existing:
        existing.role = role  # zaten üye: rolü güncelle
    else:
        session.add(
            TeamMembership(team_id=body.team_id, developer_id=user.developer_id, role=role)
        )
    session.commit()
    return _user_out(session, user)


@router.delete("/employees/{user_id}/memberships/{team_id}")
def remove_membership(
    user_id: int,
    team_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if user is None or user.developer_id is None:
        raise HTTPException(status_code=404, detail="Hesap bir geliştiriciye bağlı değil")
    m = session.scalar(
        select(TeamMembership).where(
            TeamMembership.developer_id == user.developer_id,
            TeamMembership.team_id == team_id,
        )
    )
    if m is None:
        raise HTTPException(status_code=404, detail="Üyelik bulunamadı")
    session.delete(m)
    session.commit()
    return _user_out(session, user)


# --- ilk kurulum sihirbazı (public — yalnızca hiç admin yokken) ---------------

@router.get("/setup-status")
def setup_status(session: Session = Depends(get_session)):
    """Sistemde hiç aktif yönetici yoksa kurulum gerekir. Public uç."""
    return {"needs_setup": _active_admin_count(session) == 0}


@router.post("/setup", status_code=201)
def setup(body: SetupBody, session: Session = Depends(get_session)):
    # Güvenlik: yalnızca sistemde hiç aktif admin yoksa çalışır (aksi halde
    # herkes admin oluşturabilirdi). İlk admin kurulduktan sonra bu uç kapanır.
    if _active_admin_count(session) > 0:
        raise HTTPException(status_code=403, detail="Kurulum zaten tamamlanmış")
    email = body.email.lower()
    if session.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Bu e-posta zaten kayıtlı")

    dev = Developer(display_name=body.display_name, external_ids={}, anonymizable=True)
    session.add(dev)
    session.flush()
    now = datetime.now(timezone.utc)
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role="admin",
        developer_id=dev.id,
        is_active=True,
        must_change_password=False,  # kendi parolasını kendi belirledi
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.commit()
    token = create_access_token(user.id, user.role)
    return {"access_token": token, "token_type": "bearer", "user": _user_out(session, user)}
