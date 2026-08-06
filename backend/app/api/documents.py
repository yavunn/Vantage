"""Bordro / özlük evrakı uçları.

GİZLİLİK MODELİ (izin akışıyla aynı çizgi, bir kademe daha dar):
- Çalışan YALNIZ kendi belgelerini görür, yükler ve (İK bakmadan önce) siler.
- admin + İK herkesin belgesini görür, karar verir, başkası adına yükler.
- Takım yöneticisi başkasının belgesini GÖREMEZ. İzin takviminde yönetici
  kapasiteyi görmek için bir şeyler görüyordu; burada görülecek şey sağlık
  raporu ve icra yazısı — kapasite bağlamı bunu gerektirmez.

DENETİM: yükleme, indirme, karar ve silme audit_logs'a yazılır. Özel nitelikli
veriye erişimde "kim ne zaman baktı" sorusunun cevabı olmalı; indirmeyi de
kaydetmemiz bu yüzden (diğer uçlarda yalnız yazma işlemleri kaydediliyor).

BORDROYU HESAPLAMAZ: bu modül belgenin VARLIĞINI ve durumunu izler. Ücret
hesabı bilinçli olarak kapsam dışı — bkz. services/hr_doc_types.py.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, require_admin_or_hr
from app.core.db import get_session
from app.core.i18n import lang_from_request
from app.models import Developer, Leave, PayrollDocument, User
from app.services import hr_documents as storage
from app.services.hr_doc_types import (
    CATEGORIES,
    CATEGORY_LABELS_EN,
    CATEGORY_LABELS_TR,
    DOC_TYPE_MAP,
    LEAVE_TYPE_FOR_DOC,
    REQUIRED_KEYS,
    catalog,
    type_label,
)

router = APIRouter(prefix="/api/documents")

_STATUSES = ("pending", "approved", "rejected")
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _can_manage(user: User) -> bool:
    """Herkesin belgesini görebilen / karara bağlayabilen roller."""
    return user.role in ("admin", "hr")


def _person_name(session: Session, user_id: int) -> str:
    """İzin panosuyla AYNI isim kuralı: developer varsa görünen adı, yoksa
    e-postanın yerel kısmı. İki ekranda aynı kişi farklı görünmesin."""
    u = session.get(User, user_id)
    if u is None:
        return "?"
    if u.developer_id:
        dev = session.get(Developer, u.developer_id)
        if dev:
            return dev.display_name
    return u.email.split("@")[0]


def _parse_period(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not _PERIOD_RE.match(value):
        raise HTTPException(status_code=422, detail="Dönem biçimi YYYY-MM olmalı")
    return value


def _parse_date(value: str | None, field: str) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"{field} biçimi YYYY-AA-GG olmalı") from e


def _linked_leave_info(session: Session, leave_id: int | None) -> dict | None:
    """İzin ↔ evrak senkronu: belge bir Leave'e bağlıysa arayüz aynı tarihi
    ikinci kez ELLE İSTEMESİN diye o kaydın özetini döner."""
    if leave_id is None:
        return None
    lv = session.get(Leave, leave_id)
    if lv is None:
        return None
    return {
        "id": lv.id,
        "status": lv.status or "approved",
        "start_date": lv.start_date.isoformat(),
        "end_date": lv.end_date.isoformat(),
    }


def _serialize(session: Session, doc: PayrollDocument, viewer: User, lang: str) -> dict:
    meta = DOC_TYPE_MAP.get(doc.doc_type, {})
    own = doc.user_id == viewer.id
    manage = _can_manage(viewer)
    return {
        "id": doc.id,
        "user_id": doc.user_id,
        "person": _person_name(session, doc.user_id),
        "doc_type": doc.doc_type,
        "doc_label": type_label(doc.doc_type, lang),
        "category": meta.get("category", "other"),
        "affects_payroll": bool(meta.get("affects_payroll")),
        "period": doc.period,
        "start_date": doc.start_date.isoformat() if doc.start_date else None,
        "end_date": doc.end_date.isoformat() if doc.end_date else None,
        "note": doc.note,
        "leave_id": doc.leave_id,
        "linked_leave": _linked_leave_info(session, doc.leave_id),
        "file_name": doc.original_name,
        "size_bytes": doc.size_bytes,
        "status": doc.status or "pending",
        "review_note": doc.review_note,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "uploaded_by_me": doc.uploaded_by == viewer.id,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "own": own,
        # Çalışan kendi belgesini yalnız İK bakmadan ÖNCE silebilir: onaylanmış
        # bir belgenin sessizce kaybolması bordro kaydını delik bırakır.
        "can_delete": manage or (own and (doc.status or "pending") == "pending"),
        "can_decide": manage and (doc.status or "pending") == "pending",
    }


# --- katalog ------------------------------------------------------------------


@router.get("/types")
def document_types(request: Request, _: User = Depends(current_user)):
    """Yüklenebilecek belge türleri + bordroya etkileri.

    Arayüz bu listeyi SUNUCUDAN alır: katalog mevzuata bağlı ve tek kaynakta
    kalmalı. İki yerde tutulsaydı bir tür eklendiğinde arayüz ile sunucu
    ayrışır, çalışan seçtiği türü kaydedemezdi."""
    lang = lang_from_request(request)
    labels = CATEGORY_LABELS_EN if lang == "en" else CATEGORY_LABELS_TR
    return {
        "categories": [{"key": c, "label": labels[c]} for c in CATEGORIES],
        "types": catalog(lang),
    }


# --- listeleme ----------------------------------------------------------------


@router.get("")
def list_documents(
    request: Request,
    user_id: int | None = Query(default=None),
    period: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Belge listesi. Çalışan yalnız kendi kayıtlarını görür.

    `user_id` filtresi yalnız admin/İK için anlamlıdır; düz kullanıcıda sessizce
    yok sayılmaz, 403 döner — "başkasının belgelerini istedim, boş liste geldi"
    ile "yetkim yok" arasındaki fark kullanıcıya açık olmalı."""
    lang = lang_from_request(request)
    manage = _can_manage(user)
    stmt = select(PayrollDocument)
    if manage:
        if user_id is not None:
            stmt = stmt.where(PayrollDocument.user_id == user_id)
    else:
        if user_id is not None and user_id != user.id:
            raise HTTPException(status_code=403, detail="Başkasının belgelerini görme yetkiniz yok")
        stmt = stmt.where(PayrollDocument.user_id == user.id)
    if period:
        stmt = stmt.where(PayrollDocument.period == _parse_period(period))
    if doc_type:
        stmt = stmt.where(PayrollDocument.doc_type == doc_type)
    if status:
        if status not in _STATUSES:
            raise HTTPException(status_code=422, detail="status: pending | approved | rejected")
        stmt = stmt.where(PayrollDocument.status == status)
    rows = session.scalars(stmt.order_by(PayrollDocument.created_at.desc())).all()
    return [_serialize(session, d, user, lang) for d in rows]


@router.get("/pending")
def pending_documents(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_or_hr),
):
    """Admin/İK: inceleme bekleyen belgeler (onay kuyruğu)."""
    lang = lang_from_request(request)
    rows = session.scalars(
        select(PayrollDocument)
        .where(PayrollDocument.status == "pending")
        .order_by(PayrollDocument.created_at)
    ).all()
    return [_serialize(session, d, user, lang) for d in rows]


@router.get("/checklist")
def checklist(
    request: Request,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin_or_hr),
):
    """Admin/İK: kimin özlük dosyasında hangi ZORUNLU belge eksik.

    Bu ucun bütün değeri şurada: evrak yüklemek tek başına bir dosya deposu
    kurar, "kimde ne eksik" sorusunu cevaplamaz. Reddedilen belge EKSİK sayılır
    (yüklenmiş ama geçerli değil); bekleyen belge eksik SAYILMAZ ama ayrıca
    gösterilir — İK'nın önce neye bakması gerektiği görünsün."""
    lang = lang_from_request(request)
    users = session.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.id)
    ).all()
    docs = session.scalars(
        select(PayrollDocument).where(PayrollDocument.doc_type.in_(REQUIRED_KEYS))
    ).all()

    by_user: dict[int, dict[str, str]] = {}
    for d in docs:
        cur = by_user.setdefault(d.user_id, {})
        state = d.status or "pending"
        # Aynı tür birden çok kez yüklenmiş olabilir; en iyi durum kazanır:
        # onaylı > bekleyen > reddedilen.
        rank = {"approved": 3, "pending": 2, "rejected": 1}
        if rank.get(state, 0) > rank.get(cur.get(d.doc_type, ""), 0):
            cur[d.doc_type] = state

    out = []
    for u in users:
        states = by_user.get(u.id, {})
        missing = [k for k in REQUIRED_KEYS if states.get(k) != "approved"
                   and states.get(k) != "pending"]
        waiting = [k for k in REQUIRED_KEYS if states.get(k) == "pending"]
        out.append({
            "user_id": u.id,
            "person": _person_name(session, u.id),
            "required_total": len(REQUIRED_KEYS),
            "approved_count": sum(1 for k in REQUIRED_KEYS if states.get(k) == "approved"),
            "missing": [{"key": k, "label": type_label(k, lang)} for k in missing],
            "pending": [{"key": k, "label": type_label(k, lang)} for k in waiting],
        })
    # En eksik olan başta: İK'nın ilk bakacağı satır en üstte olsun.
    out.sort(key=lambda r: (-len(r["missing"]), r["person"]))
    return {"required_total": len(REQUIRED_KEYS), "rows": out}


@router.get("/summary")
def summary(
    request: Request,
    period: str = Query(...),
    session: Session = Depends(get_session),
    _: User = Depends(require_admin_or_hr),
):
    """Admin/İK: bir bordro döneminde gelen belgeler — tür kırılımı + bordroyu
    etkileyen kaç belge hâlâ karara bağlanmamış."""
    lang = lang_from_request(request)
    p = _parse_period(period)
    rows = session.scalars(
        select(PayrollDocument).where(PayrollDocument.period == p)
    ).all()
    by_type: dict[str, dict] = {}
    blocking = 0
    for d in rows:
        meta = DOC_TYPE_MAP.get(d.doc_type, {})
        rec = by_type.setdefault(d.doc_type, {
            "doc_type": d.doc_type,
            "label": type_label(d.doc_type, lang),
            "affects_payroll": bool(meta.get("affects_payroll")),
            "total": 0, "approved": 0, "pending": 0, "rejected": 0,
        })
        rec["total"] += 1
        rec[d.status or "pending"] += 1
        if meta.get("affects_payroll") and (d.status or "pending") == "pending":
            blocking += 1
    return {
        "period": p,
        "total": len(rows),
        # Bordro kapatılmadan önce karara bağlanması gereken belge sayısı.
        "blocking_payroll": blocking,
        "by_type": sorted(by_type.values(), key=lambda r: -r["total"]),
    }


# --- yükleme ------------------------------------------------------------------


@router.post("", status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    period: str | None = Form(default=None),
    start_date: str | None = Form(default=None),
    end_date: str | None = Form(default=None),
    note: str | None = Form(default=None),
    leave_id: int | None = Form(default=None),
    target_user_id: int | None = Form(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Belge yükle. Çalışan kendine, admin/İK herkes adına.

    Multipart FORM alanları kullanılır (JSON değil): dosya ile meta tek istekte
    gelmeli — önce meta kaydedip sonra dosya yüklemek, yarıda kalan yüklemelerde
    dosyasız kayıtlar bırakırdı."""
    meta = DOC_TYPE_MAP.get(doc_type)
    if meta is None:
        raise HTTPException(status_code=422, detail="Bilinmeyen belge türü")

    target = user
    if target_user_id is not None and target_user_id != user.id:
        if not _can_manage(user):
            raise HTTPException(status_code=403, detail="Başkası adına belge yükleme yetkiniz yok")
        target = session.get(User, target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Hedef kullanıcı yok")

    p = _parse_period(period)
    s_date = _parse_date(start_date, "Başlangıç tarihi")
    e_date = _parse_date(end_date, "Bitiş tarihi")

    if meta["needs_period"] and not p:
        raise HTTPException(status_code=422, detail="Bu belge için bordro dönemi (YYYY-MM) zorunlu")
    if meta["needs_dates"] and not (s_date and e_date):
        raise HTTPException(status_code=422, detail="Bu belge için başlangıç ve bitiş tarihi zorunlu")
    if s_date and e_date and e_date < s_date:
        raise HTTPException(status_code=422, detail="Bitiş tarihi başlangıçtan önce olamaz")

    if leave_id is not None:
        lv = session.get(Leave, leave_id)
        if lv is None or lv.user_id != target.id:
            raise HTTPException(status_code=404, detail="İlgili izin kaydı bulunamadı")

    # Dosya diske SON adımda yazılır: doğrulama hatalarında disk kirlenmesin.
    try:
        saved = await storage.save_upload(file, user_id=target.id)
    except storage.UploadError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from e

    now = datetime.now(timezone.utc)
    doc = PayrollDocument(
        user_id=target.id,
        uploaded_by=user.id,
        doc_type=doc_type,
        period=p,
        start_date=s_date,
        end_date=e_date,
        note=(note or "").strip() or None,
        leave_id=leave_id,
        status="pending",
        created_at=now,
        **saved,
    )
    session.add(doc)
    session.flush()

    # Onay bekleyen belge → admin + İK'ya bildirim (izin akışıyla aynı desen).
    from app.services.notifications import notify
    person = _person_name(session, target.id)
    label = type_label(doc_type, "tr")
    for approver in session.scalars(
        select(User).where(User.role.in_(("admin", "hr")), User.is_active.is_(True))
    ).all():
        if approver.id == user.id:
            continue  # kendi yüklediğini kendine haber verme
        notify(
            session, approver.id, kind="document_pending", severity="info",
            title="Yeni evrak inceleme bekliyor",
            body=f"{person} · {label}" + (f" · {p}" if p else ""),
            dedup_key=f"document_pending:{doc.id}", link="documents",
        )

    from app.services.audit import record_audit
    record_audit(session, user, "document_upload", target_user_id=target.id,
                 target_email=target.email,
                 detail={"document_id": doc.id, "type": doc_type,
                         "period": p, "size": saved["size_bytes"]})
    session.commit()
    return {"id": doc.id, "ok": True, "status": doc.status}


# --- indirme ------------------------------------------------------------------


@router.get("/{doc_id}/download")
def download_document(
    doc_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Belge içeriğini indirir. Sahibi + admin/İK.

    Yanıt her zaman `attachment`: içerik tarayıcıda AÇILMAZ. PDF'i satır içinde
    açmak kolaylık gibi görünür ama yüklenen dosya aynı origin'den servis
    ediliyor — tarayıcının render ettiği her biçim saldırı yüzeyidir."""
    doc = session.get(PayrollDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Belge bulunamadı")
    if doc.user_id != user.id and not _can_manage(user):
        raise HTTPException(status_code=403, detail="Bu belgeyi görme yetkiniz yok")

    try:
        path = storage.file_path(doc.user_id, doc.stored_name)
    except storage.UploadError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from e
    if not path.is_file():
        # DB kaydı var, dosya yok: sessiz 500 yerine anlaşılır bir hata.
        raise HTTPException(status_code=410, detail="Belgenin dosyası sunucuda bulunamadı")

    # Başkasının özel nitelikli belgesini KİM açtı — kaydedilir.
    if doc.user_id != user.id:
        from app.services.audit import record_audit
        target = session.get(User, doc.user_id)
        record_audit(session, user, "document_download", target_user_id=doc.user_id,
                     target_email=target.email if target else None,
                     detail={"document_id": doc.id, "type": doc.doc_type})
        session.commit()

    return FileResponse(
        path,
        media_type=storage.download_content_type(doc.content_type),
        filename=doc.original_name,
        headers={
            # Yüklenen dosyanın içeriği tarayıcıya "tahmin ettirilmesin".
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


# --- karar / silme ------------------------------------------------------------


class DocumentDecisionBody(BaseModel):
    decision: str  # approved | rejected
    note: str | None = None  # redde ZORUNLU


@router.post("/{doc_id}/decision")
def decide_document(
    doc_id: int,
    body: DocumentDecisionBody,
    session: Session = Depends(get_session),
    actor: User = Depends(require_admin_or_hr),
):
    """Admin/İK belgeyi onaylar ya da reddeder. Redde gerekçe ZORUNLU — çalışan
    hangi belgeyi neden yeniden yüklemesi gerektiğini bilsin."""
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=422, detail="decision: approved | rejected")
    note = (body.note or "").strip()
    if body.decision == "rejected" and not note:
        raise HTTPException(status_code=422, detail="Red için gerekçe gerekli")
    doc = session.get(PayrollDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Belge bulunamadı")

    doc.status = body.decision
    doc.review_note = note or None
    doc.reviewed_by = actor.id
    doc.reviewed_at = datetime.now(timezone.utc)

    # İZİN SENKRONU: "leave" kategorisindeki bir belge kabul edilince, aynı
    # tarihi bir de İzin panosuna ELLE GİRMEK gerekmesin. İki durum:
    #   - Belge hiçbir izne bağlı değilse: onaylı bir Leave OTOMATİK oluşur
    #     (yükleme sırasında zaten tarih/tür doğrulanmıştı).
    #   - Belge ZATEN bir izne bağlıysa (yükleyen kişi seçmişti) ve o izin hâlâ
    #     "pending" ise: belge kabulü aynı zamanda o izni de onaylar — İK'nın
    #     aynı kararı iki ayrı ekranda vermesi gerekmez.
    # Reddedilen belgede bu bağ KURULMAZ: rapor onaylanmadıysa henüz oluşmuş
    # bir izin kaydı yoktur (auto-create yalnız onayda çalışır); önceden elle
    # bağlanmış bir izin varsa o başka bir kararın konusu, belge reddi onu
    # otomatik geçersiz kılmaz — geri alınamaz bir yan etki olurdu.
    leave_sync = None
    if body.decision == "approved":
        leave_type = LEAVE_TYPE_FOR_DOC.get(doc.doc_type)
        if leave_type and doc.start_date and doc.end_date:
            if doc.leave_id is None:
                owner = session.get(User, doc.user_id)
                new_leave = Leave(
                    user_id=doc.user_id,
                    developer_id=owner.developer_id if owner else None,
                    start_date=doc.start_date, end_date=doc.end_date,
                    leave_type=leave_type,
                    description=f"“{type_label(doc.doc_type, 'tr')}” belgesinden otomatik oluşturuldu",
                    status="approved", approved_by=actor.id, approved_at=doc.reviewed_at,
                    created_at=doc.reviewed_at,
                )
                session.add(new_leave)
                session.flush()
                doc.leave_id = new_leave.id
                leave_sync = "created"
            else:
                linked = session.get(Leave, doc.leave_id)
                if linked is not None and (linked.status or "approved") == "pending":
                    linked.status = "approved"
                    linked.approved_by = actor.id
                    linked.approved_at = doc.reviewed_at
                    if not linked.decision_note:
                        linked.decision_note = f"“{type_label(doc.doc_type, 'tr')}” belgesiyle onaylandı"
                    leave_sync = "confirmed"

    from app.services.notifications import notify
    label = type_label(doc.doc_type, "tr")
    if body.decision == "approved":
        extra = ""
        if leave_sync == "created":
            extra = " İzin takvimine işlendi."
        elif leave_sync == "confirmed":
            extra = " Bağlı izin kaydın da onaylandı."
        notify(session, doc.user_id, kind="document_decision", severity="info",
               title="Evrakın kabul edildi",
               body=f"{label} belgesi kabul edildi ve özlük dosyana işlendi.{extra}",
               dedup_key=f"document_decision:{doc.id}:approved", link="documents")
    else:
        notify(session, doc.user_id, kind="document_decision", severity="info",
               title="Evrakın kabul edilmedi",
               body=f"{label} belgesi kabul edilmedi. Gerekçe: {note}",
               dedup_key=f"document_decision:{doc.id}:rejected", link="documents")

    from app.services.audit import record_audit
    target = session.get(User, doc.user_id)
    record_audit(session, actor, f"document_{body.decision}", target_user_id=doc.user_id,
                 target_email=target.email if target else None,
                 detail={"document_id": doc.id, "type": doc.doc_type,
                         **({"note": note[:120]} if note else {}),
                         **({"leave_sync": leave_sync} if leave_sync else {})})
    session.commit()
    return {"ok": True, "status": doc.status, "leave_sync": leave_sync}


@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Belgeyi siler (DB kaydı + diskteki dosya).

    Çalışan yalnız İK bakmadan önce silebilir; karara bağlanmış belgeyi ancak
    admin/İK siler. Kayıt gerçekten silinir — reddedilen izin isteğinin aksine
    burada saklanacak bir KARAR yok, saklanacak olan kişisel bir DOSYA var ve
    gereksiz tutmak KVKK'nın veri minimizasyonuna aykırı."""
    doc = session.get(PayrollDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Belge bulunamadı")
    manage = _can_manage(user)
    own = doc.user_id == user.id
    if not manage:
        if not own:
            raise HTTPException(status_code=403, detail="Bu belgeyi silme yetkiniz yok")
        if (doc.status or "pending") != "pending":
            raise HTTPException(
                status_code=403,
                detail="İncelenmiş belge silinemez; kaldırılması için İK ile görüşün",
            )

    stored_name, owner_id = doc.stored_name, doc.user_id
    from app.services.audit import record_audit
    target = session.get(User, doc.user_id)
    record_audit(session, user, "document_delete", target_user_id=doc.user_id,
                 target_email=target.email if target else None,
                 detail={"document_id": doc.id, "type": doc.doc_type})
    session.delete(doc)
    session.commit()
    # Dosya DB commit'inden SONRA silinir: commit başarısız olursa kaydı duran
    # ama dosyası yok olmuş bir belge kalmasın.
    storage.delete_file(owner_id, stored_name)
    return {"ok": True}


# --- çalışan özeti ------------------------------------------------------------


@router.get("/mine/summary")
def my_summary(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Çalışanın kendi eksik ZORUNLU belgeleri — "benden ne isteniyor" ekranı."""
    lang = lang_from_request(request)
    rows = session.scalars(
        select(PayrollDocument).where(
            PayrollDocument.user_id == user.id,
            PayrollDocument.doc_type.in_(REQUIRED_KEYS),
        )
    ).all()
    best: dict[str, str] = {}
    rank = {"approved": 3, "pending": 2, "rejected": 1}
    for d in rows:
        state = d.status or "pending"
        if rank.get(state, 0) > rank.get(best.get(d.doc_type, ""), 0):
            best[d.doc_type] = state
    missing = [k for k in REQUIRED_KEYS if best.get(k) not in ("approved", "pending")]
    return {
        "required_total": len(REQUIRED_KEYS),
        "approved_count": sum(1 for k in REQUIRED_KEYS if best.get(k) == "approved"),
        "missing": [{"key": k, "label": type_label(k, lang)} for k in missing],
    }
