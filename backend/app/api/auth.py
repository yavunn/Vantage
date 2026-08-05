"""Kimlik doğrulama ve hesap yönetimi uçları.

- POST /api/auth/login                 : email + parola -> JWT
- GET  /api/auth/me                    : token sahibinin bilgisi
- POST /api/auth/change-password       : çalışan kendi parolasını değiştirir
- POST /api/auth/forgot-password       : kimliksiz — hesabı bulur, yeni geçici
                                          parolayı DOĞRUDAN uygular ve döner
                                          (arayüz mailto ile e-postaya gönderir)
- GET  /api/auth/employees             : (admin) hesap listesi
- POST /api/auth/employees             : (admin) yeni çalışan + hesap oluştur
- POST /api/auth/employees/{id}/password : (admin) bir çalışanın parolasını sıfırla

Yetki modeli: role ∈ {user, admin, hr}. admin=tam yetki, hr=İK (rehber+izin+
kapasite; performans/entegrasyon/rol-değişimi KAPALI), user=çalışan. owner
(is_owner) = korunan admin. Admin uçları token'daki role ile korunur.
Dashboard uçları (routes.py) da geçerli JWT ister (router-level current_user);
kimlik yalnız JWT'den gelir — eski X-Dev-Id katmanı kaldırıldı.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_temp_password,
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

# Login brute-force koruması: ardışık N başarısız denemeden sonra hesap
# M dakika geçici kilitlenir. Kilit süresi dolunca sayaç sıfırlanır.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

# Parola taban uzunlugu. 6 karakter cevrimdisi hash saldirisina karsi
# anlamli bir direnc vermiyor; hesap kilidi yalniz CEVRIMICI denemeyi
# yavaslatir. Mevcut hesaplar etkilenmez — yalniz yeni/degisen parolalar.
MIN_PASSWORD_LENGTH = 10

# IP bazlı giriş sınırı. Hesap kilidi TEK hesabı korur; saldırgan hesap hesap
# dolaşarak (password spraying) ya da e-posta numaralandırarak kilidi hiç
# tetiklemeyebilir. Bu sayaç kaynağı sınırlar. Tek process + on-prem olduğu
# için bellek içi yeterli; birden çok worker'a geçilirse Redis'e taşınmalı.
LOGIN_RATE_MAX = 20          # pencere başına başarısız deneme
LOGIN_RATE_WINDOW_MIN = 5    # kayan pencere (dakika)
_login_attempts: dict[str, list[datetime]] = {}


def _client_ip(request: Request) -> str:
    """İstemci IP'si. Ters vekil arkasındaysa X-Forwarded-For'un İLK adresi.

    Not: X-Forwarded-For istemci tarafından uydurulabilir; on-prem kurulumda
    uygulamanın önünde güvenilen bir vekil olduğu varsayılır. Bu sınır ek bir
    katmandır, hesap kilidinin yerine geçmez."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "bilinmiyor"


def _rate_limited(ip: str, now: datetime) -> bool:
    """Kayan pencerede eşik aşıldı mı? Sayaç yalnız BAŞARISIZ denemede artar."""
    pencere = now - timedelta(minutes=LOGIN_RATE_WINDOW_MIN)
    denemeler = [t for t in _login_attempts.get(ip, []) if t > pencere]
    _login_attempts[ip] = denemeler
    return len(denemeler) >= LOGIN_RATE_MAX


def _record_failed_login(ip: str, now: datetime) -> None:
    _login_attempts.setdefault(ip, []).append(now)
    # Sözlük sınırsız büyümesin: boşalan IP kayıtlarını at.
    if len(_login_attempts) > 5000:
        pencere = now - timedelta(minutes=LOGIN_RATE_WINDOW_MIN)
        for k in [k for k, v in _login_attempts.items() if not any(t > pencere for t in v)]:
            _login_attempts.pop(k, None)


# --- şemalar ------------------------------------------------------------------

class LoginBody(BaseModel):
    email: str
    password: str


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class CreateEmployeeBody(BaseModel):
    display_name: str = Field(min_length=1)
    email: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)
    role: str = "user"  # user | admin | hr
    team_id: int | None = None
    team_role: str = "member"  # member | manager
    hire_date: date | None = None
    annual_allowance: int = 14


class SetPasswordBody(BaseModel):
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class UpdateEmployeeBody(BaseModel):
    role: str | None = None          # user | admin | hr
    is_active: bool | None = None


class EmploymentBody(BaseModel):
    hire_date: date | None = None
    annual_allowance: int | None = Field(default=None, ge=0, le=365)


class UpdateProfileBody(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=60)
    bio: str | None = Field(default=None, max_length=2000)


class SetupBody(BaseModel):
    display_name: str = Field(min_length=1)
    email: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)


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
    if int(payload.get("tv", 0)) != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="Oturum geçersiz — parola değişti, tekrar giriş yapın")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem için yönetici yetkisi gerekli")
    return user


def require_admin_or_hr(user: User = Depends(current_user)) -> User:
    """Paylaşımlı İK uçları: çalışan rehberi, izin özeti/onayı, kapasite.
    admin (ve owner=admin) ile hr geçer; düz user geçemez."""
    if user.role not in ("admin", "hr"):
        raise HTTPException(status_code=403, detail="Bu işlem için yönetici veya İK yetkisi gerekli")
    return user


def require_owner(user: User = Depends(current_user)) -> User:
    """Yalnızca baş yönetici (owner). En üst yetki gerektiren işlemler için."""
    if not user.is_owner:
        raise HTTPException(status_code=403, detail="Bu işlem için baş yönetici yetkisi gerekli")
    return user


def _guard_owner_target(target: User, actor: User) -> None:
    """Baş yönetici hesabı korunur: sahibinden başkası ona dokunamaz (silme,
    rol/aktiflik değişimi, parola sıfırlama). Böylece en üst yetki ele geçirilemez."""
    if target.is_owner and target.id != actor.id:
        raise HTTPException(
            status_code=403,
            detail="Baş yönetici hesabı korunuyor; bu işlem yapılamaz",
        )


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
        "is_owner": bool(user.is_owner),
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "developer_id": user.developer_id,
        "display_name": dev.display_name if dev else user.email.split("@")[0],
        "title": user.title,
        "phone": user.phone,
        "timezone": user.timezone,
        "bio": user.bio,
        "hire_date": user.hire_date.isoformat() if user.hire_date else None,
        "annual_allowance": user.annual_allowance,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "teams": _memberships_out(session, user.developer_id),
    }


# Parola sıfırlama TALEBİ için ayrı, daha dar bir IP sınırı. Giriş sayacından
# ayrıdır: bu uç parola denemiyor, ama sınırsız bırakılırsa hem yöneticinin
# kuyruğu spam'lenir hem de e-posta numaralandırma denemesi ucuzlar.
RESET_RATE_MAX = 5
RESET_RATE_WINDOW_MIN = 15
_reset_attempts: dict[str, list[datetime]] = {}


# --- uçlar --------------------------------------------------------------------

@router.post("/login")
def login(body: LoginBody, request: Request, session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)

    # Önce kaynak sınırı: hesap kilidi tek hesabı korur, bu ise aynı IP'den
    # farklı hesapları taramayı (password spraying) yavaşlatır.
    ip = _client_ip(request)
    if _rate_limited(ip, now):
        raise HTTPException(
            status_code=429,
            detail=f"Çok fazla giriş denemesi. {LOGIN_RATE_WINDOW_MIN} dk sonra tekrar deneyin.",
        )

    user = session.scalar(select(User).where(User.email == body.email.lower()))

    # Hesap geçici kilitli mi? (brute-force koruması). Kilit süresi dolmuşsa
    # sayaç sıfırlanır ve girişe izin verilir.
    if user is not None and user.locked_until is not None:
        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            remaining = int((locked_until - now).total_seconds() // 60) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Çok fazla başarısız deneme. Hesap geçici kilitli — {remaining} dk sonra tekrar deneyin.",
            )
        # Kilit süresi doldu: temizle.
        user.failed_login_count = 0
        user.locked_until = None

    ok = user is not None and user.is_active and verify_password(body.password, user.password_hash)
    if not ok:
        # IP sayacı hesap VAR OLMASA da artar: numaralandırma da yavaşlasın.
        _record_failed_login(ip, now)
        # Başarısız deneme sayacını artır; eşiği aşarsa kilitle. (Var olan hesap
        # için; olmayan e-postada sayaç yok — kullanıcı sayımı sızdırılmaz,
        # mesaj aynıdır.)
        if user is not None:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_login_count = 0
            session.commit()
        raise HTTPException(status_code=401, detail="E-posta ya da parola hatalı")

    # Başarılı giriş: sayaç + kilit sıfırlanır.
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    session.commit()
    token = create_access_token(user.id, user.role, user.token_version or 0)
    return {"access_token": token, "token_type": "bearer", "user": _user_out(session, user)}


@router.get("/me")
def me(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return _user_out(session, user)


@router.patch("/me/profile")
def update_my_profile(
    body: UpdateProfileBody,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Kullanıcı kendi profilini düzenler. display_name Developer'a, diğer
    alanlar User'a yazılır. Hiçbir alan metrik/performans hesabına karışmaz."""
    if body.display_name is not None:
        dev = session.get(Developer, user.developer_id) if user.developer_id else None
        if dev is not None:
            dev.display_name = body.display_name.strip()
    if body.title is not None:
        user.title = body.title.strip() or None
    if body.phone is not None:
        user.phone = body.phone.strip() or None
    if body.timezone is not None:
        user.timezone = body.timezone.strip() or None
    if body.bio is not None:
        user.bio = body.bio.strip() or None
    user.updated_at = datetime.now(timezone.utc)
    session.commit()
    return _user_out(session, user)


class ForgotPasswordBody(BaseModel):
    email: str


@router.post("/forgot-password")
def forgot_password(
    body: ForgotPasswordBody,
    request: Request,
    session: Session = Depends(get_session),
):
    """Kendi kendine parola sıfırlama (kimlik doğrulaması gerektirmez).

    Sunucuda mail gönderimi YOK — kurulum bilerek sunucu/SMTP gerektirmez.
    Hesap e-postayla bulunur ve yeni bir geçici parola DOĞRUDAN uygulanır;
    kullanıcı ilk girişte kendi parolasını belirler (must_change_password).
    Yeni parola yanıtla birlikte döner; arayüz bunu ekranda gösterir ve
    kullanıcının kendi e-postasına göndermesi için bir mailto bağlantısı
    sunar (istemci tarafında, kendi mail programını açar — sunucu göndermez).

    BİLİNÇLİ GÜVENLİK ÖDÜNÜ: e-posta adresini bilen HERKES o hesabın
    parolasını sıfırlayıp yeni değeri görebilir — ikinci bir kimlik doğrulama
    adımı (gerçekten o kutuya erişildiğinin doğrulanması) yoktur. Kapalı, tek
    kuruluşluk, on-prem bir araç için bilinçli olarak kabul edilen risktir;
    internete açık bir sistemde KULLANILMAMALIDIR. IP bazlı hız sınırı
    yalnızca toplu e-posta taramasını yavaşlatır, bu ödünü ortadan kaldırmaz.
    """
    now = datetime.now(timezone.utc)
    ip = _client_ip(request)
    pencere = now - timedelta(minutes=RESET_RATE_WINDOW_MIN)
    denemeler = [t for t in _reset_attempts.get(ip, []) if t > pencere]
    _reset_attempts[ip] = denemeler
    if len(denemeler) >= RESET_RATE_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"Çok fazla talep. {RESET_RATE_WINDOW_MIN} dk sonra tekrar deneyin.",
        )
    _reset_attempts[ip].append(now)

    email = (body.email or "").strip().lower()
    user = session.scalar(select(User).where(User.email == email)) if email else None
    if user is None or not user.is_active:
        return {"ok": True, "account_exists": False, "email": email, "new_password": None}

    new_password = generate_temp_password()
    user.password_hash = hash_password(new_password)
    user.must_change_password = True  # geçici; kullanıcı ilk girişte değiştirir
    user.token_version = (user.token_version or 0) + 1  # eski oturumları düşür
    user.updated_at = now
    from app.services.audit import record_audit
    # Parolanın KENDİSİ asla kaydedilmez — yalnız "kendi kendine sıfırladı"
    # olgusu. actor=None: oturum açmış bir yönetici değil, hesabın kendisi.
    record_audit(session, None, "self_reset_password", target_user_id=user.id,
                 target_email=user.email)
    session.commit()
    return {"ok": True, "account_exists": True, "email": email, "new_password": new_password}


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
    user.token_version = (user.token_version or 0) + 1  # eski/diğer oturumları düşür
    user.updated_at = datetime.now(timezone.utc)
    session.commit()
    # Bu oturum devam etsin diye YENİ token ver (aksi halde kendi kendini düşürür).
    return {"ok": True, "access_token": create_access_token(user.id, user.role, user.token_version)}


@router.get("/employees")
def list_employees(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin_or_hr),
):
    users = session.scalars(select(User).order_by(User.id)).all()
    return [_user_out(session, u) for u in users]


@router.post("/employees", status_code=201)
def create_employee(
    body: CreateEmployeeBody,
    session: Session = Depends(get_session),
    actor: User = Depends(require_admin_or_hr),
):
    email = body.email.lower()
    if body.role not in ("user", "admin", "hr"):
        raise HTTPException(status_code=422, detail="role yalnızca 'user', 'admin' veya 'hr' olabilir")
    # İK işe alım yapar ama rol veremez: HR yalnız role=user hesap açabilir,
    # admin/hr yükseltmesi yapamaz (yetki tırmanması önleme).
    if actor.role == "hr" and body.role != "user":
        raise HTTPException(status_code=403, detail="İK yalnızca çalışan (user) hesabı oluşturabilir")
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
        # İşe giriş verilmediyse bugüne varsay (hesap açılış günü = işe giriş).
        hire_date=body.hire_date or date.today(),
        annual_allowance=body.annual_allowance,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.flush()
    from app.services.audit import record_audit
    record_audit(session, actor, "create_employee", target_user_id=user.id,
                 target_email=user.email, detail={"role": body.role})
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
    # Baş yönetici korunur: rolü ve aktifliği bu uçtan HİÇ değiştirilemez
    # (başka admin tarafından da, kaza ile kendi tarafından da). En üst yetki sabit.
    if user.is_owner and (
        (body.role is not None and body.role != user.role)
        or (body.is_active is not None and body.is_active != user.is_active)
    ):
        raise HTTPException(
            status_code=403,
            detail="Baş yönetici hesabının rolü veya aktifliği değiştirilemez",
        )
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
    changes: dict = {}
    if body.role is not None:
        if body.role not in ("user", "admin", "hr"):
            raise HTTPException(status_code=422, detail="role yalnızca 'user', 'admin' veya 'hr' olabilir")
        if body.role != user.role:
            changes["role"] = f"{user.role}->{body.role}"
        user.role = body.role
    if body.is_active is not None:
        if body.is_active != user.is_active:
            changes["is_active"] = f"{user.is_active}->{body.is_active}"
        user.is_active = body.is_active
    user.updated_at = datetime.now(timezone.utc)
    if changes:
        from app.services.audit import record_audit
        record_audit(session, admin, "update_employee", target_user_id=user.id,
                     target_email=user.email, detail=changes)
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
    if user.is_owner:
        raise HTTPException(status_code=403, detail="Baş yönetici hesabı silinemez")
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
    from app.services.audit import record_audit
    record_audit(session, admin, "delete_employee", target_user_id=user_id,
                 target_email=user.email, detail={"developer_removed": developer_removed})
    session.commit()
    return {"ok": True, "developer_removed": developer_removed}


@router.post("/employees/{user_id}/password")
def set_employee_password(
    user_id: int,
    body: SetPasswordBody,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin_or_hr),
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    # İK yalnızca düz çalışan (user) parolası sıfırlayabilir; admin/hr/owner hedefi red.
    if admin.role == "hr" and user.role != "user":
        raise HTTPException(status_code=403, detail="İK yalnızca çalışan (user) parolasını sıfırlayabilir")
    # Baş yöneticinin parolasını yalnızca kendisi değiştirebilir (ele geçirme önleme).
    _guard_owner_target(user, admin)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = True  # sıfırlanan parola geçici; kullanıcı değiştirsin
    user.token_version = (user.token_version or 0) + 1  # hedefin eski oturumlarını düşür
    user.updated_at = datetime.now(timezone.utc)
    from app.services.audit import record_audit
    # Parolanın KENDİSİ asla kaydedilmez — yalnız "sıfırlandı" olgusu.
    record_audit(session, admin, "reset_password", target_user_id=user.id,
                 target_email=user.email)
    session.commit()
    return {"ok": True}


@router.patch("/employees/{user_id}/employment")
def set_employment(
    user_id: int,
    body: EmploymentBody,
    session: Session = Depends(get_session),
    actor: User = Depends(require_admin_or_hr),
):
    """İşe giriş tarihi + yıllık izin hakkı (İK kaydı). admin + hr düzenler.
    Bu alanlar performans metriğine KARIŞMAZ — yalnız İK/kapasite bağlamı."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    changes: dict = {}
    if body.hire_date is not None and body.hire_date != user.hire_date:
        changes["hire_date"] = body.hire_date.isoformat()
        user.hire_date = body.hire_date
    if body.annual_allowance is not None and body.annual_allowance != user.annual_allowance:
        changes["annual_allowance"] = f"{user.annual_allowance}->{body.annual_allowance}"
        user.annual_allowance = body.annual_allowance
    user.updated_at = datetime.now(timezone.utc)
    if changes:
        from app.services.audit import record_audit
        record_audit(session, actor, "update_employment", target_user_id=user.id,
                     target_email=user.email, detail=changes)
    session.commit()
    return _user_out(session, user)


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
    token = create_access_token(user.id, user.role, user.token_version or 0)
    return {"access_token": token, "token_type": "bearer", "user": _user_out(session, user)}
