"""Kimlik doğrulama ve hesap yönetimi uçları.

- POST /api/auth/login                 : email + parola -> JWT
- GET  /api/auth/me                    : token sahibinin bilgisi
- POST /api/auth/change-password       : çalışan kendi parolasını değiştirir
- POST /api/auth/forgot-password       : kimliksiz — 6 haneli kodu maille yollar
- POST /api/auth/verify-reset-code     : kimliksiz — kodu doğrular, jeton döner
- POST /api/auth/reset-password        : kimliksiz — jetonla parolayı günceller
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

import hashlib
import logging
import secrets as _secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
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
    PasswordResetCode,
    PRReview,
    PullRequest,
    Task,
    Team,
    TeamMembership,
    User,
)

router = APIRouter(prefix="/api/auth")

# Mail gönderim hatası kullanıcıya GENEL mesajla döner (hangi adımın patladığı
# sızmasın); sebebin kendisi yöneticinin görebilmesi için loga yazılır.
logger = logging.getLogger(__name__)

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


# --- "şifremi unuttum" akışı sabitleri ---------------------------------------

RESET_CODE_TTL_MINUTES = 10      # 6 haneli kodun ömrü
RESET_TOKEN_TTL_MINUTES = 15     # kod doğrulanınca verilen jetonun ömrü
RESET_MAX_ATTEMPTS = 5           # bu kadar hatalı denemede kod tamamen iptal

# Sıfırlama uçları için ayrı, daha dar sınır. Giriş sayacından AYRIDIR: bu uçlar
# parola denemiyor ama sınırsız bırakılırsa mail bombardımanı ve kod tahmini
# ucuzlar. Hem IP hem E-POSTA başına sayılır — tek IP'den çok hesabı denemek de,
# çok IP'den tek hesabı denemek de sınırlansın.
RESET_RATE_WINDOW_MIN = 15
# forgot-password: her istek BİR MAİL gönderttiği için pahalı → sıkı sınır.
RESET_RATE_MAX = 5
# verify-reset-code: ucuz bir uç, burada asıl koruma RESET_MAX_ATTEMPTS'tir
# (5 hatalı kodda kod tamamen yakılır). Bu sayaç yalnızca "hamur gibi dövmeyi"
# engelleyen emniyet frenidir ve BİLEREK daha gevşektir:
#   - forgot ile AYNI kovayı paylaşsaydı, 1 kod isteği + 5 deneme = 6 istek
#     olur, sınır 5'te dolar ve deneme sayacı hiç 5'e ULAŞAMAZDI (ölü kod).
#   - Kodu iki kez yanlış yazan meşru kullanıcı 15 dk kilitlenirdi.
VERIFY_RATE_MAX = 15
_reset_attempts: dict[str, list[datetime]] = {}


def _reset_rate_limited(anahtarlar: list[str], now: datetime, ust_sinir: int) -> bool:
    """Verilen anahtarlardan (ip / email) herhangi biri eşiği aştı mı?

    Sayaç, sonucundan bağımsız olarak HER istekte artar: başarılı istek de
    maliyetlidir. Anahtarlar uç adıyla ön eklendiği için forgot ve verify
    kovaları birbirini tüketmez."""
    asildi = False
    pencere = now - timedelta(minutes=RESET_RATE_WINDOW_MIN)
    for k in anahtarlar:
        denemeler = [t for t in _reset_attempts.get(k, []) if t > pencere]
        if len(denemeler) >= ust_sinir:
            asildi = True
        denemeler.append(now)
        _reset_attempts[k] = denemeler
    if len(_reset_attempts) > 5000:
        for k in [k for k, v in _reset_attempts.items() if not any(t > pencere for t in v)]:
            _reset_attempts.pop(k, None)
    return asildi


def _hash_secret(deger: str) -> str:
    """Kod/jeton için sha256. Parolalar için DEĞİL — onlar bcrypt (yavaş hash)
    ister. Buradakiler yüksek entropili, kısa ömürlü sırlar; sha256 yeterli ve
    sabit zamanlı karşılaştırmayı ucuzlatır."""
    return hashlib.sha256(deger.encode("utf-8")).hexdigest()


def _as_utc(dt: datetime) -> datetime:
    """Naive datetime'ı UTC kabul eder. SQLite (testler + taşınabilir demo)
    saat dilimini saklamaz; aware `now` ile karşılaştırma yoksa TypeError olur.
    Aynı düzeltme login'deki kilit kontrolünde de satır içi yapılıyor."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


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


# --- "şifremi unuttum": 3 adım (kod iste → kodu doğrula → parolayı belirle) ---
#
# GİZLİLİK: üç uç da hangi adımın patladığını SIZDIRMAZ. forgot-password,
# e-posta kayıtlı olsun ya da olmasın aynı yanıtı döner (kullanıcı
# numaralandırma); verify/reset ise "kod yanlış / süresi dolmuş / zaten
# kullanılmış / hiç kod yok" ayrımını yapmadan tek bir genel mesaj verir.

# Adım ayrımı yapmayan tek mesaj — kaynağı tek yerde tut ki ileride biri
# yanlışlıkla ayrıntılı bir varyant yazmasın.
_GENERIC_CODE_ERROR = "Kod geçersiz ya da süresi dolmuş. Lütfen yeni bir kod isteyin."


class ForgotPasswordBody(BaseModel):
    email: str


class VerifyResetCodeBody(BaseModel):
    email: str
    code: str


class ResetPasswordBody(BaseModel):
    reset_token: str
    # Parola kuralı, hesap oluşturma ve parola değiştirme ile AYNI kaynaktan
    # gelir (MIN_PASSWORD_LENGTH) — üç yerde ayrı kural olmasın.
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


def _aktif_kodlari_iptal_et(session: Session, user_id: int, now: datetime) -> None:
    """Kullanıcının açık tüm kodlarını kapatır. Yeni kod isteyince çağrılır:
    aynı anda birden çok geçerli kod dolaşması, saldırganın deneme yüzeyini
    büyütürdü."""
    acik = session.scalars(
        select(PasswordResetCode).where(
            PasswordResetCode.user_id == user_id,
            PasswordResetCode.used_at.is_(None),
        )
    ).all()
    for k in acik:
        k.used_at = now


@router.post("/forgot-password")
def forgot_password(
    body: ForgotPasswordBody,
    request: Request,
    session: Session = Depends(get_session),
):
    """1/3 — 6 haneli kod üretir ve kullanıcının kendi adresine MAİLLER.

    Kod yanıtta ASLA dönmez: postayı alabilmek, isteği gerçekten hesap
    sahibinin yaptığını doğrulayan tek adımdır.

    SIRA ÖNEMLİ: önce mail gönderilir, ancak gönderim başarılıysa kod
    kaydedilir. Tersi sırada kullanıcı asla eline geçmeyecek bir kodu beklerdi.
    """
    from app.services.mail_templates import reset_code_email
    from app.services.mailer import MailError, is_configured, send_email

    now = datetime.now(timezone.utc)
    email = (body.email or "").strip().lower()
    if _reset_rate_limited(
        [f"forgot:ip:{_client_ip(request)}", f"forgot:mail:{email}"], now, RESET_RATE_MAX
    ):
        raise HTTPException(
            status_code=429,
            detail=f"Çok fazla istek. {RESET_RATE_WINDOW_MIN} dk sonra tekrar deneyin.",
        )

    # Mail hiç yapılandırılmamışsa akış çalışamaz. Bu, hesabın varlığından
    # BAĞIMSIZ bir kurulum hatasıdır — numaralandırma sızdırmaz.
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail="E-posta gönderimi yapılandırılmamış. Lütfen yöneticinize başvurun.",
        )

    user = session.scalar(select(User).where(User.email == email)) if email else None
    if user is not None and user.is_active:
        # crypto-secure, baştaki sıfırlar korunacak şekilde 6 hane.
        code = f"{_secrets.randbelow(1_000_000):06d}"
        try:
            send_email(
                user.email,
                "Vantage — parola sıfırlama kodunuz",
                reset_code_email(code, RESET_CODE_TTL_MINUTES),
            )
        except MailError as e:
            logger.error("Parola sıfırlama kodu gönderilemedi: %s", e)
            raise HTTPException(
                status_code=502,
                detail="E-posta gönderilemedi. Lütfen yöneticinize başvurun.",
            ) from e
        # Mail gitti — kodu ancak şimdi kalıcılaştır.
        _aktif_kodlari_iptal_et(session, user.id, now)
        session.add(PasswordResetCode(
            user_id=user.id,
            code_hash=_hash_secret(code),   # düz metin ASLA saklanmaz
            expires_at=now + timedelta(minutes=RESET_CODE_TTL_MINUTES),
            attempts=0,
            created_at=now,
        ))
        session.commit()

    # Yanıt her koşulda aynı — hesabın var olup olmadığı sızmaz. TTL sabit bir
    # yapılandırma değeridir, hesabın varlığına göre değişmez; arayüz geri
    # sayımı buradan kurar (istemcide ikinci bir sabit tutmayalım).
    return {
        "ok": True,
        "expires_in_minutes": RESET_CODE_TTL_MINUTES,
        "message": (
            "Hesabınız varsa doğrulama kodu e-posta adresinize gönderildi. "
            "Gelen kutunuzu (ve spam klasörünü) kontrol edin."
        ),
    }


@router.post("/verify-reset-code")
def verify_reset_code(
    body: VerifyResetCodeBody,
    request: Request,
    session: Session = Depends(get_session),
):
    """2/3 — kodu doğrular, tek kullanımlık `reset_token` döner.

    Jeton sayesinde son adımda kod tekrar sorulmaz. Yanlış denemeler sayılır;
    RESET_MAX_ATTEMPTS'e ulaşınca kod tamamen iptal edilir (kaba kuvvet).
    """
    now = datetime.now(timezone.utc)
    email = (body.email or "").strip().lower()
    if _reset_rate_limited(
        [f"verify:ip:{_client_ip(request)}", f"verify:mail:{email}"], now, VERIFY_RATE_MAX
    ):
        raise HTTPException(
            status_code=429,
            detail=f"Çok fazla istek. {RESET_RATE_WINDOW_MIN} dk sonra tekrar deneyin.",
        )

    user = session.scalar(select(User).where(User.email == email)) if email else None
    kayit = None
    if user is not None:
        kayit = session.scalar(
            select(PasswordResetCode)
            .where(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.used_at.is_(None),
            )
            .order_by(PasswordResetCode.id.desc())
        )
    # Hesap yok / kod yok / süresi dolmuş — hepsi AYNI yanıt.
    if kayit is None or _as_utc(kayit.expires_at) <= now:
        raise HTTPException(status_code=400, detail=_GENERIC_CODE_ERROR)

    girilen = (body.code or "").strip()
    # Sabit zamanlı karşılaştırma: yanıt süresinden kod tahmin edilemesin.
    if not _secrets.compare_digest(_hash_secret(girilen), kayit.code_hash):
        kayit.attempts = (kayit.attempts or 0) + 1
        if kayit.attempts >= RESET_MAX_ATTEMPTS:
            kayit.used_at = now  # kod yakıldı; kullanıcı yenisini istemeli
        session.commit()
        raise HTTPException(status_code=400, detail=_GENERIC_CODE_ERROR)

    # Doğru kod: tek kullanımlık jeton üret. Jeton da HASH'li saklanır — o da
    # parolayı değiştirmeye yeten bir sırdır.
    reset_token = _secrets.token_urlsafe(32)
    kayit.reset_token_hash = _hash_secret(reset_token)
    kayit.reset_token_expires_at = now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
    session.commit()
    return {
        "ok": True,
        "reset_token": reset_token,
        "expires_in_minutes": RESET_TOKEN_TTL_MINUTES,
    }


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordBody,
    session: Session = Depends(get_session),
):
    """3/3 — jetonu doğrular, parolayı günceller, tüm oturumları sonlandırır."""
    from app.services.mail_templates import password_changed_email
    from app.services.mailer import MailError, send_email

    now = datetime.now(timezone.utc)
    token = (body.reset_token or "").strip()
    kayit = session.scalar(
        select(PasswordResetCode).where(
            PasswordResetCode.reset_token_hash == _hash_secret(token),
            PasswordResetCode.used_at.is_(None),
        )
    ) if token else None
    if (
        kayit is None
        or kayit.reset_token_expires_at is None
        or _as_utc(kayit.reset_token_expires_at) <= now
    ):
        raise HTTPException(status_code=400, detail=_GENERIC_CODE_ERROR)

    user = session.get(User, kayit.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail=_GENERIC_CODE_ERROR)

    user.password_hash = hash_password(body.new_password)
    # Kullanıcı parolayı KENDİ seçti — admin'in verdiği geçici parola değil,
    # dolayısıyla ilk girişte tekrar değiştirmesi istenmez.
    user.must_change_password = False
    # Diğer tüm oturumları/JWT'leri düşür: parola sızmış olabilir.
    user.token_version = (user.token_version or 0) + 1
    user.updated_at = now
    # Kod + jeton tek seferliktir: ikisini birden yak.
    kayit.used_at = now
    from app.services.audit import record_audit
    # Parolanın KENDİSİ asla kaydedilmez — yalnız "kendi sıfırladı" olgusu.
    # actor=None: oturum açmış bir yönetici değil, hesabın sahibi.
    record_audit(session, None, "self_reset_password", target_user_id=user.id,
                 target_email=user.email)
    session.commit()

    # Bilgilendirme maili BEST-EFFORT: parola çoktan değişti, mail gitmedi diye
    # işlemi geri almak kullanıcıyı kilitler. Hata yalnız loglanır.
    try:
        send_email(user.email, "Vantage — parolanız değiştirildi", password_changed_email())
    except MailError as e:
        logger.error("Parola değişikliği bildirimi gönderilemedi: %s", e)

    return {"ok": True}


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
    # Özlük/bordro evrakı: DB satırları FK cascade ile gider ama DOSYALAR diskte
    # kalırdı. Silinen bir çalışanın istirahat raporunun sunucuda durması KVKK
    # veri minimizasyonuna aykırı — hesap silinirken dosyalar da imha edilir.
    from app.models import PayrollDocument
    from app.services.hr_documents import purge_user_files
    for doc in session.scalars(
        select(PayrollDocument).where(PayrollDocument.user_id == user_id)
    ).all():
        session.delete(doc)
    purged_files = purge_user_files(user_id)
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
                 target_email=user.email,
                 detail={"developer_removed": developer_removed,
                         "documents_purged": purged_files})
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
