"""Kişi kayıtlarının birleştirilmesi ve kaynak kimliklerinin okunması.

NEDEN: Aynı insan kaynaklarda birden çok kimlikle görünür — git'te e-posta
(üstelik GitHub'ın `…@users.noreply.github.com` adresi ayrı bir e-postadır),
Trello'da üye id'si. İngest bunları eşleştiremez ve iki ayrı Developer açar.
Sonuç sessiz ve yanıltıcıdır: takım kadrosu şişer, WIP kişi başına bölündüğü
için metrik olduğundan İYİ görünür; commit'ler bir kayda, görevler diğerine
düşer ve hiçbir kişi bazlı görünüm doğru çıkmaz.

KRİTİK: kopyayı silmeden ÖNCE developers.id'ye bakan TÜM referanslar taşınmalı.
Eksik bırakılan tek tablo, PostgreSQL'de foreign key hatası (SQLite'ta sessiz
yetim kayıt) demektir. Bu yüzden liste tek yerde tutulur ve testi vardır.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CodeAnalysis,
    Commit,
    Developer,
    Leave,
    PRReview,
    PullRequest,
    Task,
    TaskAssignee,
    TeamMembership,
    User,
)

# (model, developers.id'ye bakan kolon) — models/__init__.py'deki
# ForeignKey("developers.id") geçen HER yer burada olmalı.
_REFERANSLAR = (
    (Commit, "author_id"),
    (PullRequest, "author_id"),
    (PRReview, "reviewer_id"),
    (Task, "assignee_id"),
    (Leave, "developer_id"),
    (CodeAnalysis, "developer_id"),
    (User, "developer_id"),
)

# Benzersizlik kısıtı taşıyan referanslar körü körüne TAŞINAMAZ: hedefte aynı
# satır zaten varsa taşımak IntegrityError verir (aynı karta iki kaydıyla da
# atanmış bir insan, aynı takımda iki kaydı olan bir insan). Bu tablolarda
# kopyanın satırı taşınmaz, SİLİNİR. (model, sahip kolonu, eşsizlik kolonu)
_TEKIL_REFERANSLAR = (
    (TaskAssignee, "developer_id", "task_id"),
    (TeamMembership, "developer_id", "team_id"),
)

# --- git kimliği: TEK e-posta değil, e-posta KÜMESİ --------------------------
#
# Aynı insan kişisel adresiyle ve GitHub'ın gizlilik adresiyle
# (`12345+kullanici@users.noreply.github.com`) commit atar; makinesini
# değiştirince üçüncüsü çıkar. Alan tek bir string olarak okunduğu sürece
# çözüm yalnızca "kopya kayıt aç, sonra birleştir"di — birleştirme de
# kopyanın e-postasını atıyordu, bu yüzden bir sonraki senkron aynı kopyayı
# YENİDEN açıyordu (sessiz döngü).
#
# Bu yüzden `external_ids["git"]` hem `"a@x.com"` hem `["a@x.com", "b@x.com"]`
# olabilir. Şekil bilgisi TEK YERDE, bu üç fonksiyonda kalır; okuyan hiçbir
# yer `.get("git")` yapmaz.

GIT_SOURCE = "git"


def git_emails(external_ids: dict | None) -> list[str]:
    """`external_ids['git']` → normalize e-posta listesi (küçük harf, tekil).

    Hem eski (str) hem yeni (list) biçimi okur; boş/None güvenle boş liste
    döner. Sıra korunur: ilk sıradaki 'birincil' e-postadır (arayüzde tek
    e-posta gösteren yerler onu gösterir)."""
    ham = (external_ids or {}).get(GIT_SOURCE)
    if not ham:
        return []
    adaylar = [ham] if isinstance(ham, str) else list(ham)
    out: list[str] = []
    for a in adaylar:
        e = (a or "").strip().lower()
        if e and e not in out:
            out.append(e)
    return out


def primary_git_email(external_ids: dict | None) -> str | None:
    """Tek e-posta bekleyen yerler (liste ekranları, eski API alanları) için."""
    liste = git_emails(external_ids)
    return liste[0] if liste else None


def with_git_emails(external_ids: dict | None, emails: list[str]) -> dict:
    """`external_ids`'in git alanı güncellenmiş KOPYASI.

    Tek e-posta kaldığında string olarak yazılır: kayıtların çoğunda öyle ve
    gereksiz yere liste yapmak hem eski veriyi hem eski istemcileri karşılıksız
    kırardı. Boş liste alanı tamamen kaldırır (bağ yok = anahtar yok)."""
    ext = dict(external_ids or {})
    temiz: list[str] = []
    for e in emails:
        n = (e or "").strip().lower()
        if n and n not in temiz:
            temiz.append(n)
    if not temiz:
        ext.pop(GIT_SOURCE, None)
    else:
        ext[GIT_SOURCE] = temiz[0] if len(temiz) == 1 else temiz
    return ext


# --- Kaynak üyesi ↔ giriş hesabı ADAYI ---------------------------------------
#
# OTOMATİK BAĞLAMA YOK. Burada üretilen tek şey "muhtemelen bu kişi" işaretidir;
# bağı admin kurar. Gerekçe duplicate_identity_pairs ile aynı: yanlış eşleme İK
# bağlamında gerçek zarardır (bir insanın işi başkasına atfedilir), ve o zarar
# sessizdir — kimse "acaba yanlış mı bağlandı" diye bakmaz.

_TR_KATLAMA = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
})


def fold_name(value: str | None) -> str:
    """Ad/kullanıcı adı karşılaştırma biçimi: küçük harf, Türkçe katlanmış,
    harf-rakam dışı atılmış. "Ayşe Yılmaz" → "ayseyilmaz", "ayse.yilmaz" → aynı.

    Katlama şart: Trello'da tam ad Türkçe yazılır ("Ayşe Yılmaz"), kurumsal
    e-posta ASCII olur (ayse.yilmaz@…). Katlamayan bir karşılaştırma bu çok
    yaygın çifti hiç yakalayamaz."""
    if not value:
        return ""
    katlanmis = value.translate(_TR_KATLAMA).lower()
    return "".join(ch for ch in katlanmis if ch.isalnum())


def suggest_account(member_name: str | None, member_username: str | None,
                    accounts: list[dict]) -> tuple[int, str] | None:
    """Trello üyesi için (developer_id, gerekçe) adayı — yoksa None.

    YALNIZ TAM eşleşme kabul edilir (katlama sonrası). Parça/benzerlik eşiği
    denendiğinde "Ali" ile "Ali Rıza"yı aynı kişi yapıyordu; kimlik eşlemesinde
    yanlış aday, adaysızlıktan kötüdür — admin onu onaylayıp geçer.

    accounts: [{"developer_id": int, "display_name": str, "user_email": str|None}]
    """
    ad = fold_name(member_name)
    kul = fold_name(member_username)
    if not ad and not kul:
        return None
    for acc in accounts:
        hesap_adi = fold_name(acc.get("display_name"))
        eposta = (acc.get("user_email") or "").strip().lower()
        yerel = fold_name(eposta.split("@", 1)[0]) if eposta else ""
        if ad and hesap_adi and ad == hesap_adi:
            return acc["developer_id"], "tam ad hesap adıyla aynı"
        if yerel and ad and ad == yerel:
            return acc["developer_id"], f"tam ad '{eposta}' ile eşleşiyor"
        if yerel and kul and kul == yerel:
            return acc["developer_id"], f"kullanıcı adı '{eposta}' ile eşleşiyor"
        if kul and hesap_adi and kul == hesap_adi:
            return acc["developer_id"], "kullanıcı adı hesap adıyla aynı"
    return None


class IdentityConflict(ValueError):
    """İstenen kimlik BAŞKA bir kayıtta. Çağıran (API) 409 döndürür.

    Sessizce el değiştirmek en pahalı hatadır: kimlik bir sonraki senkronda
    o commit'leri/kartları yanlış insana atfeder ve kimse fark etmez."""


def check_git_emails_free(session: Session, emails: list[str], dev_id: int | None) -> None:
    """E-postalardan biri başka bir kişideyse IdentityConflict atar."""
    istenen = {e.strip().lower() for e in emails if e and e.strip()}
    if not istenen:
        return
    stmt = select(Developer)
    if dev_id is not None:
        stmt = stmt.where(Developer.id != dev_id)
    for other in session.scalars(stmt):
        cakisan = istenen & set(git_emails(other.external_ids))
        if cakisan:
            raise IdentityConflict(
                f"'{sorted(cakisan)[0]}' e-postası zaten {other.display_name} kaydına bağlı. "
                "Aynı insansa iki kaydı birleştirin, değilse başka e-posta girin."
            )


def task_identity_owner(session: Session, source: str, key: str,
                        dev_id: int | None) -> Developer | None:
    """`source:key` kimliğini taşıyan DİĞER kaydı döner (yoksa None).

    Giriş hesabı olan bir kayda çarparsa IdentityConflict atar: o bir "kopya"
    değil, BAŞKA BİR İNSANDIR ve birleştirme iki çalışanın verisini tek kişide
    toplardı (merge, User satırını da taşır).
    """
    stmt = select(Developer)
    if dev_id is not None:
        stmt = stmt.where(Developer.id != dev_id)
    for other in session.scalars(stmt):
        if (other.external_ids or {}).get(source) != key:
            continue
        sahip = session.scalar(select(User).where(User.developer_id == other.id))
        if sahip is not None:
            raise IdentityConflict(
                f"'{key}' kimliği zaten {other.display_name} ({sahip.email}) hesabına bağlı. "
                "Önce oradaki bağı kaldırın; iki kayıt aynı insansa elle birleştirme kullanın."
            )
        return other
    return None


class MergeError(ValueError):
    """Birleştirme yapılamaz (aynı kayıt, eksik kayıt vb.)."""


def merge_developers(session: Session, target_id: int, duplicate_id: int) -> dict:
    """`duplicate_id`'yi `target_id` içine birleştirir ve kopyayı siler.

    Geri alınamaz: çağıran taraf onay almalı. Döner: neyin taşındığı (sayılarla),
    ki arayüz "5 commit ve 2 görev taşındı" diyebilsin — sessiz başarı yok.
    """
    if target_id == duplicate_id:
        raise MergeError("Bir kayıt kendisiyle birleştirilemez.")
    target = session.get(Developer, target_id)
    duplicate = session.get(Developer, duplicate_id)
    if target is None or duplicate is None:
        raise MergeError("Kişi bulunamadı.")

    moved: dict[str, int] = {}
    for model, column in _REFERANSLAR:
        col = getattr(model, column)
        rows = session.scalars(select(model).where(col == duplicate.id)).all()
        for row in rows:
            setattr(row, column, target.id)
        if rows:
            moved[model.__tablename__] = len(rows)

    # Benzersizlik kısıtlı tablolar: hedefte AYNI satır zaten varsa kopyanınki
    # taşınmaz, silinir. Taşımak IntegrityError verirdi — aynı karta iki
    # kaydıyla atanmış (ya da aynı takımda iki kaydı olan) bir insan, kimlik
    # eşlemesi yapılmamış kurulumlarda tam olarak beklenen durumdur.
    for model, sahip_kolonu, tekil_kolon in _TEKIL_REFERANSLAR:
        sahip = getattr(model, sahip_kolonu)
        hedefteki = {
            getattr(r, tekil_kolon)
            for r in session.scalars(select(model).where(sahip == target.id))
        }
        tasinan = 0
        for row in session.scalars(select(model).where(sahip == duplicate.id)):
            if getattr(row, tekil_kolon) in hedefteki:
                session.delete(row)
            else:
                setattr(row, sahip_kolonu, target.id)
                tasinan += 1
        if tasinan:
            moved[model.__tablename__] = tasinan

    # Kopyanın kimlikleri hedefe geçsin ki bir sonraki senkron aynı kopyayı
    # yeniden AÇMASIN. Hedefte zaten varsa hedefinki korunur.
    ext = dict(target.external_ids or {})
    for k, v in (duplicate.external_ids or {}).items():
        ext.setdefault(k, v)
    # git ALANI İSTİSNA: burada setdefault yetmez, BİRLEŞİM gerekir. Kopyanın
    # e-postası atıldığında bir sonraki senkron o e-postayı tanımayıp kopyayı
    # yeniden açıyordu — birleştirme her seferinde geri alınıyor, kullanıcı
    # aynı ikizi tekrar tekrar birleştiriyordu.
    ext = with_git_emails(
        ext, git_emails(target.external_ids) + git_emails(duplicate.external_ids)
    )
    target.external_ids = ext

    session.flush()
    session.delete(duplicate)
    session.commit()
    return {
        "ok": True,
        "target_id": target.id,
        "merged_developer_id": duplicate_id,
        "moved": moved,
        "task_identities": {k: v for k, v in ext.items() if k != "git"},
    }
