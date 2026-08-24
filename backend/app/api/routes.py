"""REST API.

Etik çerçevenin (spec Bölüm 1 + İlke E) uygulandığı yer:
- Varsayılan görünüm TAKIM/PROJE'dir; takım uçları her GİRİŞLİ kullanıcıya açıktır.
- Bireysel görünüm yalnızca kişinin KENDİSİ ya da YÖNETİCİSİ içindir.
- Kıyaslamalı leaderboard ucu YOKTUR ve eklenmez: hiçbir uç, birden çok
  kişinin metriklerini yan yana döndürmez.
- Anonimleştirme modunda bireysel uçlar kapanır, isimler maskelenir.
- Kimlik YALNIZ JWT'den gelir (router-level current_user). Tüm bu uçlar geçerli
  token ister; tokensiz istek 401. Eski, taklit edilebilen X-Dev-Id kaldırıldı.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, require_admin
from app.core.config import Config, get_config
from app.core.db import get_session
from app.core.i18n import (
    current_lang,
    lang_from_request,
    metric_meta,
    status_labels,
    tr_error,
    tr_text,
)
from app.metrics.engine import load_team_data
from app.models import (
    Commit,
    Developer,
    MetricResult,
    Recommendation,
    Task,
    Team,
    User,
)
from app.services.commit_alignment import alignment_summary
from app.services.health import METRIC_THRESHOLD_MAP, health_status
from app.services.scoring import overall_score

# Bu router'daki TÜM uçlar geçerli JWT ister (dashboard okuma dahil). Kimlik
# artık YALNIZ JWT'den gelir — eski, taklit edilebilen X-Dev-Id başlığı kaldırıldı.
# Login/kurulum ayrı auth_router'da (public); anket/anotasyon kendi router'larında.
# Frontend config/ui + teams + directory'yi zaten giriş sonrası (token'la) çeker.
router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


# --- kimlik ve yetki yardımcıları ---------------------------------------------

def _is_manager_of(session: Session, manager: Developer, dev: Developer) -> bool:
    dev_team_ids = {m.team_id for m in dev.memberships}
    return any(
        m.role == "manager" and m.team_id in dev_team_ids for m in manager.memberships
    )


def _individual_access(session: Session, user: User, dev_id: int, cfg: Config) -> Developer:
    """Bireysel görünüm kapısı — TEK yerde (İlke E).

    Kural: anonimleştirme modunda ya da özellik kapalıysa tamamen devre dışı;
    açıkken yalnızca kişinin KENDİSİ, yöneticisi ya da admin. Her yeni bireysel
    uç bu kapıdan geçer; kopyalanan bir yetki bloğu er ya da geç birinde eksik
    kalır ve kişi verisi sızar.
    """
    if not cfg.app.individual_view_enabled or cfg.app.anonymize_individuals:
        raise HTTPException(403, tr_error("Bireysel görünüm bu kurulumda kapalı (takım-agregat mod)"))
    dev = session.get(Developer, dev_id)
    if dev is None:
        raise HTTPException(404, tr_error("Kişi bulunamadı"))
    # Yetki YALNIZ JWT kimliğiyle: admin herkesi görebilir; aksi halde kişinin
    # KENDİSİ (user.developer_id) ya da yöneticisi. Yetki hatası 403 (401 DEĞİL:
    # istemcide oturumu düşürmesin). Kimliksiz istek router seviyesinde 401 olur.
    if user.role != "admin":
        requester = session.get(Developer, user.developer_id) if user.developer_id else None
        if requester is None or (requester.id != dev.id and not _is_manager_of(session, requester, dev)):
            raise HTTPException(403, tr_error("Bireysel görünümü yalnızca kişinin kendisi, yöneticisi ya da admin görebilir"))
    return dev


def _mask_name(dev: Developer, cfg: Config) -> str:
    """İlke E: kimlik bir katman arkasında. Anonim modda ya da kişi bazlı
    maskelemede gerçek isim hiçbir uçtan sızmaz."""
    if cfg.app.anonymize_individuals and dev.anonymizable:
        return f"Geliştirici #{dev.id}"
    return dev.display_name


# --- takım/proje uçları (varsayılan görünüm) -----------------------------------

@router.get("/teams")
def list_teams(session: Session = Depends(get_session)):
    return [{"id": t.id, "name": t.name} for t in session.scalars(select(Team))]


def _metric_payload(row: MetricResult, cfg: Config, lang: str = "tr") -> dict:
    """Metrik kartı gövdesi. `lang`: ad/açıklama/durum etiketi bu dilde döner —
    arayüz tek başına çevrilseydi pano yarı Türkçe kalırdı."""
    status = health_status(row.metric_key, row.value, row.data_completeness, cfg)
    name, description = metric_meta(lang).get(row.metric_key, (row.metric_key, ""))
    return {
        "key": row.metric_key,
        "name": name,
        "description": description,
        "value": row.value,
        "status": status,
        "status_label": status_labels(lang)[status],
        "data_completeness": row.data_completeness,
        "source_layer": row.source_layer,
        "sample_size": row.sample_size,
        "stats": row.stats,
        "period": row.period,
    }


@router.get("/teams/{team_id}/summary")
def team_summary(
    team_id: int,
    session: Session = Depends(get_session),
    lang: str = Depends(lang_from_request),
):
    cfg = get_config()
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    # En geniş period = pencere metriği (seri kovaları daha kısadır)
    rows = session.scalars(
        select(MetricResult).where(
            MetricResult.scope == "team", MetricResult.scope_id == team_id
        )
    ).all()
    window_days = cfg.app.window_days
    overall = {}
    for row in rows:
        try:
            p_start, p_end = row.period.split("/")
            span = (datetime.fromisoformat(p_end) - datetime.fromisoformat(p_start)).days
        except ValueError:
            span = 0
        if span >= window_days - 1:
            # Aynı metriğin birden çok pencere satırı olabilir (period anahtarı
            # her sync'te tarihle kayar, eski satırlar kalır). En güncel hesap
            # kazanır — yoksa stale satır gösterilip yeni alanlar kaybolur.
            prev = overall.get(row.metric_key)
            if prev is None or (row.computed_at and prev.computed_at and row.computed_at > prev.computed_at):
                overall[row.metric_key] = row
    from app.services.report import recommendation_payload

    recs = session.scalars(
        select(Recommendation).where(
            Recommendation.scope == "team", Recommendation.scope_id == team_id
        )
    ).all()
    member_count = sum(1 for m in team.memberships if m.role != "manager")
    return {
        "team": {"id": team.id, "name": team.name, "member_count": member_count},
        "metrics": [_metric_payload(r, cfg, lang) for r in overall.values()],
        "recommendations": [recommendation_payload(r) for r in recs],
        "anonymized": cfg.app.anonymize_individuals,
    }


@router.get("/teams/{team_id}/report")
def team_report(
    team_id: int,
    days: int = Query(default=30),
    session: Session = Depends(get_session),
    lang: str = Depends(lang_from_request),
):
    """Seçilen aralık (7/30/90) için anlık hesaplanan metrikler + delta +
    sağlık sinyalleri + trend. Precompute'a değil, canlı motora dayanır."""
    from app.services.report import VALID_DAYS, live_report

    if days not in VALID_DAYS:
        raise HTTPException(422, tr_error("days yalnızca {list} olabilir", list=sorted(VALID_DAYS)))
    cfg = get_config()
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    return live_report(session, team, days, cfg, lang)


@router.get("/teams/{team_id}/metric/{metric_key}/breakdown")
def team_metric_breakdown(
    team_id: int,
    metric_key: str,
    days: int = Query(default=30),
    session: Session = Depends(get_session),
    lang: str = Depends(lang_from_request),
):
    """Drill-down: bir metriğin altındaki ham kayıtlar (hangi iş/PR/commit bu
    sayıyı oluşturuyor). Şeffaflık için — sayı gökten inmiyor."""
    from app.services.report import VALID_DAYS, metric_breakdown

    if days not in VALID_DAYS:
        raise HTTPException(422, tr_error("days yalnızca {list} olabilir", list=sorted(VALID_DAYS)))
    cfg = get_config()
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    return metric_breakdown(session, team, metric_key, days, cfg, lang)


@router.get("/teams/{team_id}/series/{metric_key}")
def team_series(
    team_id: int,
    metric_key: str,
    session: Session = Depends(get_session),
    lang: str = Depends(lang_from_request),
):
    cfg = get_config()
    if session.get(Team, team_id) is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    rows = session.scalars(
        select(MetricResult).where(
            MetricResult.scope == "team",
            MetricResult.scope_id == team_id,
            MetricResult.metric_key == metric_key,
        )
    ).all()
    # period başına en güncel hesap (eski sync'lerden kalan stale kovaları ele)
    by_period: dict[str, MetricResult] = {}
    for row in rows:
        try:
            p_start, p_end = row.period.split("/")
            span = (datetime.fromisoformat(p_end) - datetime.fromisoformat(p_start)).days
        except ValueError:
            continue
        if span >= cfg.app.window_days - 1:  # pencere satırı seriye girmez
            continue
        prev = by_period.get(row.period)
        if prev is None or (row.computed_at and prev.computed_at and row.computed_at > prev.computed_at):
            by_period[row.period] = row
    points = [
        {
            "period_start": r.period.split("/")[0],
            "period_end": r.period.split("/")[1],
            "value": r.value,
            "data_completeness": r.data_completeness,
        }
        for r in by_period.values()
    ]
    points.sort(key=lambda p: p["period_start"])
    name, description = metric_meta(lang).get(metric_key, (metric_key, ""))
    return {"metric": metric_key, "name": name, "description": description, "points": points}


# --- Kişi-bazlı kod sağlığı (kendi kodu / admin herkesi) ----------------------
# Kimlik JWT (current_user). Erişim: kişinin KENDİSİ ya da admin. Kıyaslamalı
# leaderboard YOK — her kişiye tekil, kendi kodunun geri bildirimi.

def _dev_access(dev_id: int, user):
    if user.role != "admin" and user.developer_id != dev_id:
        raise HTTPException(403, tr_error("Bu görünümü yalnızca kişinin kendisi ve admin görebilir"))


# --- Bildirimler (giriş yapan kullanıcı) -------------------------------------

@router.get("/me/notifications")
def my_notifications(session: Session = Depends(get_session), user=Depends(current_user)):
    from app.services.notifications import list_for_user, unread_count
    return {
        "items": list_for_user(session, user.id),
        "unread": unread_count(session, user.id),
    }


@router.post("/me/notifications/{notif_id}/read")
def read_notification(notif_id: int, session: Session = Depends(get_session), user=Depends(current_user)):
    from app.services.notifications import mark_read
    n = mark_read(session, user.id, notif_id)
    session.commit()
    return {"marked": n}


@router.post("/me/notifications/read-all")
def read_all_notifications(session: Session = Depends(get_session), user=Depends(current_user)):
    from app.services.notifications import mark_read
    n = mark_read(session, user.id)
    session.commit()
    return {"marked": n}


# --- Denetim kaydı (yalnız admin) --------------------------------------------

@router.get("/admin/audit")
def admin_audit(session: Session = Depends(get_session), _=Depends(require_admin)):
    from app.services.audit import list_audit
    return list_audit(session)


def _csv_response(header: list[str], rows: list[list], filename: str) -> Response:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    # BOM: Excel'in Türkçe karakterleri UTF-8 okuması için.
    data = "﻿" + buf.getvalue()
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/audit.csv")
def admin_audit_csv(session: Session = Depends(get_session), _=Depends(require_admin)):
    from app.services.audit import list_audit
    rows = list_audit(session, limit=1000)
    body = [
        [r["created_at"], r["actor_email"], r["action"], r["target_email"],
         "; ".join(f"{k}={v}" for k, v in (r["detail"] or {}).items())]
        for r in rows
    ]
    return _csv_response(
        ["zaman", "aktor", "eylem", "hedef", "ayrinti"], body, "denetim-kaydi.csv"
    )


@router.get("/teams/{team_id}/report.csv")
def team_report_csv(team_id: int, session: Session = Depends(get_session)):
    """Takım metrik özetini CSV indirir. Etik: takım-agregat, kişi satırı yok."""
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    summary = team_summary(team_id, session)
    body = [
        [m["name"], m["key"], m["value"], m["status_label"],
         m.get("data_completeness"), m.get("sample_size"), m.get("source_layer")]
        for m in summary["metrics"]
    ]
    return _csv_response(
        ["metrik", "anahtar", "deger", "durum", "veri_tamligi", "ornek_boyut", "kaynak_katman"],
        body, f"{team.name}-rapor.csv",
    )


@router.get("/me/code-health")
def my_code_health(session: Session = Depends(get_session), user=Depends(current_user),
                    lang: str = Depends(lang_from_request)):
    from app.services.code_health import developer_code_health
    if user.developer_id is None:
        raise HTTPException(404, tr_error("Hesap bir geliştiriciye bağlı değil"))
    return developer_code_health(session, user.developer_id, get_config(), lang)


@router.get("/me/code-health/breakdown")
def my_code_health_breakdown(session: Session = Depends(get_session), user=Depends(current_user),
                              lang: str = Depends(lang_from_request)):
    from app.services.code_health import developer_code_health_breakdown
    if user.developer_id is None:
        raise HTTPException(404, tr_error("Hesap bir geliştiriciye bağlı değil"))
    return developer_code_health_breakdown(session, user.developer_id, lang)


@router.post("/me/code-analysis/run")
def my_code_analysis_run(session: Session = Depends(get_session), user=Depends(current_user)):
    """Kullanıcı KENDİ kodunu analiz eder (git yazarı = kendisi)."""
    from app.services.code_analysis import run_code_analysis
    if user.developer_id is None:
        raise HTTPException(404, tr_error("Hesap bir geliştiriciye bağlı değil"))
    return run_code_analysis(session, get_config(), only_developer_id=user.developer_id)


@router.get("/developers/{dev_id}/code-health")
def developer_code_health_endpoint(dev_id: int, session: Session = Depends(get_session),
                                   user=Depends(current_user),
                                   lang: str = Depends(lang_from_request)):
    from app.services.code_health import developer_code_health
    _dev_access(dev_id, user)
    return developer_code_health(session, dev_id, get_config(), lang)


@router.get("/developers/{dev_id}/code-health/breakdown")
def developer_code_health_breakdown_endpoint(dev_id: int, session: Session = Depends(get_session),
                                             user=Depends(current_user),
                                             lang: str = Depends(lang_from_request)):
    from app.services.code_health import developer_code_health_breakdown
    _dev_access(dev_id, user)
    return developer_code_health_breakdown(session, dev_id, lang)


@router.get("/teams/{team_id}/code-health")
def team_code_health_endpoint(team_id: int, session: Session = Depends(get_session),
                               lang: str = Depends(lang_from_request)):
    """AI kod sağlığı kartı: composite + modül kırılımı (kişi değil)."""
    from app.services.code_health import team_code_health

    if session.get(Team, team_id) is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    return team_code_health(session, team_id, get_config(), lang)


@router.get("/teams/{team_id}/code-health/breakdown")
def team_code_health_breakdown_endpoint(team_id: int, session: Session = Depends(get_session),
                                         lang: str = Depends(lang_from_request)):
    """Drill-down: en çok dikkat isteyen dosyalar + AI önerileri."""
    from app.services.code_health import team_code_health_breakdown

    if session.get(Team, team_id) is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    return team_code_health_breakdown(session, team_id, lang)


@router.get("/teams/{team_id}/code-health/series")
def team_code_health_series_endpoint(team_id: int, session: Session = Depends(get_session),
                                      lang: str = Depends(lang_from_request)):
    """Haftalık kod sağlığı trendi."""
    from app.services.code_health import team_code_health_series

    if session.get(Team, team_id) is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    return team_code_health_series(session, team_id, get_config(), lang)


# --- bireysel görünüm (Faz 4: yetkili, leaderboard YOK) -------------------------

@router.get("/me")
def me(
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Kimim, hangi takımdayım (JWT kimliğiyle). developer'a bağlı değilse boş."""
    cfg = get_config()
    dev = session.get(Developer, user.developer_id) if user.developer_id else None
    if dev is None:
        return {"authenticated": True, "id": None,
                "display_name": user.email.split("@")[0], "teams": []}
    return {
        "authenticated": True,
        "id": dev.id,
        "display_name": _mask_name(dev, cfg),
        "teams": [
            {"team_id": m.team_id, "role": m.role} for m in dev.memberships
        ],
    }


@router.get("/directory")
def directory(session: Session = Depends(get_session)):
    """Kişi listesi (bireysel görünüm kimlik seçici). Metrik İÇERMEZ — sadece
    isim/rol; liste + metrik birleşimi leaderboard doğurur, o uç bilerek yoktur.

    Kaynak = giriş HESABI olan ve bir geliştiriciye bağlı aktif çalışanlar.
    Böylece bu liste yönetici panelindeki "Hesaplar" ile tutarlıdır: ingest'ten
    gelen ama hesabı olmayan (orphan) geliştiriciler burada görünmez. Hesabı
    developer'a bağlı olmayan saf admin'ler zaten bireysel eng görünümü
    üretemez (developer_id yok), o yüzden dışarıda kalır."""
    cfg = get_config()
    out = []
    seen: set[int] = set()
    users = session.scalars(
        select(User)
        .where(User.is_active.is_(True), User.developer_id.is_not(None))
        .order_by(User.id)
    ).all()
    for u in users:
        if u.developer_id in seen:
            continue
        dev = session.get(Developer, u.developer_id)
        if dev is None:
            continue
        seen.add(u.developer_id)
        out.append(
            {
                "id": dev.id,
                "display_name": _mask_name(dev, cfg),
                "roles": [{"team_id": m.team_id, "role": m.role} for m in dev.memberships],
            }
        )
    return out


# --- kendi kimliklerim (self-service) ----------------------------------------
#
# NEDEN KULLANICIYA AÇIK: git e-postasını ve Trello üyeliğini yalnız admin
# bağlayabiliyordu ve pratikte kimse bağlamıyordu. Sonuç sessizdi — kişinin
# commit'leri kimseye atfedilmiyor, kartları "görevlerim"de görünmüyor, kart↔commit
# eşleşmesinde kişi sinyali hiç oluşmuyordu. Kendi kimliğini bilen tek kişi zaten
# sahibidir.
#
# SINIR: kullanıcı YALNIZ kendi Developer kaydını değiştirir ve BAŞKASINDA olan
# bir kimliği alamaz (409). Değişiklik denetim kaydına yazılır.

def _my_developer(session: Session, user: User) -> Developer:
    dev = session.get(Developer, user.developer_id) if user.developer_id else None
    if dev is None:
        raise HTTPException(400, tr_error(
            "Hesabınız bir kişi kaydına bağlı değil — kimlik bağlamak için yöneticinize başvurun."
        ))
    return dev


def _task_source(cfg: Config) -> str:
    return (cfg.sources.tasks.provider or "none").lower()


@router.get("/me/identities")
def my_identities(
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Kendi kaynak kimliklerim + bağlanabilecek görev kaynağı üyeleri.

    Üye listesi board'un kadrosudur (kişi zaten board'da görüyor); KİMİN hangi
    hesaba bağlı olduğu burada DÖNMEZ — o yönetici bilgisidir. Yalnız "boşta mı"
    denir, ki kullanıcı zaten alınmış bir kimliği seçip 409 yemesin."""
    from app.services.identity import git_emails

    cfg = get_config()
    dev = _my_developer(session, user)
    kaynak = _task_source(cfg)
    ext = dict(dev.external_ids or {})

    uyeler: list[dict] = []
    warnings: list[str] = []
    if kaynak == "trello":
        from app.adapters.trello import TrelloProvider

        t = cfg.sources.tasks.trello
        provider = TrelloProvider(t.key_env, t.token_env, t.boards)
        kayitlar = provider.fetch_member_directory()
        warnings = list(provider.warnings)
        alinmis = {
            str((d.external_ids or {}).get(kaynak))
            for d in session.scalars(select(Developer))
            if (d.external_ids or {}).get(kaynak) and d.id != dev.id
        }
        gorulen: set[str] = set()
        for k in kayitlar:
            if k["member_id"] in gorulen:
                continue
            gorulen.add(k["member_id"])
            uyeler.append({
                "member_id": k["member_id"],
                "full_name": k["full_name"],
                "username": k["username"],
                "board_name": k["board_name"],
                "available": k["member_id"] not in alinmis,
            })

    return {
        "developer_id": dev.id,
        "display_name": dev.display_name,
        "git_emails": git_emails(ext),
        "task_source": kaynak,
        "task_identity": ext.get(kaynak) if kaynak in ("trello", "jira") else None,
        "members": uyeler,
        "warnings": warnings,
    }


class MyIdentitiesUpdate(BaseModel):
    """Verilmeyen alan DEĞİŞMEZ. `task_identity: ""` bağı kaldırır."""

    git_emails: list[str] | None = None
    task_identity: str | None = None


@router.patch("/me/identities")
def update_my_identities(
    body: MyIdentitiesUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Kendi git e-postalarımı / görev kaynağı üyeliğimi bağlar.

    Kimlik başkasındaysa 409 — sessizce el değiştirmesi, o kişinin commit'lerini
    ve kartlarını bir sonraki senkronda başkasına atfederdi."""
    from app.services.audit import record_audit
    from app.services.identity import (
        IdentityConflict,
        check_git_emails_free,
        git_emails,
        merge_developers,
        suggest_account,
        with_git_emails,
    )

    cfg = get_config()
    dev = _my_developer(session, user)
    kaynak = _task_source(cfg)
    degisiklik: dict = {}

    if body.git_emails is not None:
        ext = with_git_emails(dev.external_ids, body.git_emails)
        try:
            check_git_emails_free(session, git_emails(ext), dev.id)
        except IdentityConflict as e:
            raise HTTPException(409, tr_error(str(e))) from e
        dev.external_ids = ext
        degisiklik["git_emails"] = git_emails(ext)

    merged_id = None
    if body.task_identity is not None:
        if kaynak not in ("trello", "jira"):
            raise HTTPException(400, tr_error("Bu kurulumda bağlanacak bir görev kaynağı yok."))
        key = body.task_identity.strip()
        ext = dict(dev.external_ids or {})
        if not key:
            ext.pop(kaynak, None)
            dev.external_ids = ext
            degisiklik["task_identity"] = None
        else:
            from app.services.identity import task_identity_owner

            try:
                kopya = task_identity_owner(session, kaynak, key, dev.id)
            except IdentityConflict as e:
                raise HTTPException(409, tr_error(str(e))) from e
            # Kimlik boşta ama BAŞKASINA benziyorsa kendi kendine bağlanmaz.
            # Aksi hâlde bir çalışan meslektaşının kaynak kaydını üstlenip
            # (birleştirme yoluyla) onun kartlarını kendine taşıyabilirdi.
            hesaplar = [
                {"developer_id": u.developer_id, "display_name": d.display_name,
                 "user_email": u.email}
                for u in session.scalars(select(User).where(User.developer_id.isnot(None)))
                if (d := session.get(Developer, u.developer_id)) is not None
            ]
            kaynak_adi = kopya.display_name if kopya else None
            aday = suggest_account(kaynak_adi, None, hesaplar)
            if aday and aday[0] != dev.id:
                raise HTTPException(409, tr_error(
                    f"'{kaynak_adi}' kaydı başka bir hesapla eşleşiyor gibi görünüyor — "
                    "bu bağı yönetici kurmalı."
                ))
            if kopya is not None:
                # Kopyanın kartları/commit'leri hedefe taşınır, kopya silinir:
                # bırakılırsa kadro şişer ve kişi başı WIP olduğundan iyi görünür.
                merged_id = kopya.id
                merge_developers(session, dev.id, kopya.id)
                session.refresh(dev)
                ext = dict(dev.external_ids or {})
            ext[kaynak] = key
            dev.external_ids = ext
            degisiklik["task_identity"] = key

    if not degisiklik:
        raise HTTPException(400, tr_error("Değiştirilecek alan verilmedi."))

    record_audit(session, user, "self_identity_update",
                 target_user_id=user.id, target_email=user.email,
                 detail={**degisiklik, "merged_developer_id": merged_id})
    session.commit()
    return {
        "ok": True,
        "git_emails": git_emails(dev.external_ids),
        "task_identity": (dev.external_ids or {}).get(kaynak) if kaynak in ("trello", "jira") else None,
        "merged_developer_id": merged_id,
    }


@router.get("/developers/{dev_id}/summary")
def developer_summary(
    dev_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
    lang: str = Depends(lang_from_request),
):
    """Bireysel sağlık görünümü. Kurallar:
    - anonimleştirme modunda ya da özellik kapalıysa tamamen devre dışı;
    - yalnızca kişinin kendisi, yöneticisi ya da admin erişebilir;
    - kıyas yalnızca kişinin KENDİ geçmişiyle yapılır, asla başkasıyla."""
    cfg = get_config()
    dev = _individual_access(session, user, dev_id, cfg)

    now = datetime.now(timezone.utc)
    window = timedelta(days=cfg.app.window_days)
    current = _dev_metrics(session, dev, now - window, now, cfg)
    previous = _dev_metrics(session, dev, now - 2 * window, now - window, cfg)
    metrics = []
    for key, cur in current.items():
        prev_val = previous.get(key, {}).get("value")
        status = health_status(key, cur["value"], cur["completeness"], cfg)
        name, description = metric_meta(lang).get(key, (key, ""))
        metrics.append(
            {
                "key": key,
                "name": name,
                "description": description,
                "value": cur["value"],
                "status": status,
                "status_label": status_labels(lang)[status],
                "data_completeness": cur["completeness"],
                # Kıyas SADECE kişinin kendi geçmişi: "geçen aya göre" (İlke E)
                "previous_value": prev_val,
            }
        )
    overall = overall_score(metrics, cfg)
    commit_rows = (
        session.query(Commit)
        .filter(Commit.author_id == dev.id, Commit.committed_at >= now - window, Commit.committed_at <= now)
        .all()
    )
    alignment = alignment_summary(
        [
            {
                "sha": c.sha, "message": c.message, "changed_files": c.changed_files,
                "additions": c.additions, "deletions": c.deletions,
            }
            for c in commit_rows
        ]
    )
    return {
        "developer": {"id": dev.id, "display_name": dev.display_name},
        "window_days": cfg.app.window_days,
        "overall": overall,
        "commit_alignment": alignment,
        "metrics": metrics,
        "note": tr_text("Bu görünüm yalnızca sizin (ve yöneticinizin) erişimine açıktır; "
                        "kıyas yalnızca kendi geçmişinizle yapılır."),
    }


@router.get("/developers/{dev_id}/task-links")
def developer_task_links(
    dev_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Kişinin görevleri + o görevlere bağlanmış commit'ler.

    NE DEĞİLDİR: üretkenlik ölçümü. Burada hiçbir sayaç, skor toplamı ya da
    sıralama YOKTUR ve tek çağrıda tek kişi döner — birden çok kişiyi yan yana
    döndüren bir uç leaderboard'un ta kendisi olurdu (bkz. test_api_ethics).
    Ekranın işi tek: "hangi kartım hangi commit'e bağlanmış" sorusunu
    cevaplamak, ki kişi yanlış bağı görüp düzeltebilsin.

    Yetki bireysel özetle AYNI kapıdan geçer (_individual_access).
    """
    from app.models import TaskAssignee
    from app.services.task_link import list_links

    cfg = get_config()
    dev = _individual_access(session, user, dev_id, cfg)

    # Kartın atananı iki yerde olabilir: birincil alan ve çoklu atama tablosu.
    # Yalnız birincisine bakmak, iki kişiye atanmış kartı ikinci kişiye hiç
    # göstermezdi (Trello'da bu yaygın).
    task_ids = {
        t.id for t in session.scalars(select(Task).where(Task.assignee_id == dev.id))
    } | set(session.scalars(
        select(TaskAssignee.task_id).where(TaskAssignee.developer_id == dev.id)
    ))

    gorevler = []
    for task in session.scalars(select(Task).where(Task.id.in_(task_ids))) if task_ids else []:
        if task.missing_since is not None:
            continue  # kaynakta yok: metriklerden düşmüş kayıt, ekranı kirletmesin
        gorevler.append({
            "task_id": task.id,
            "title": task.title,
            "status": task.status,
            # Kart numarası görünmeli: konvansiyonu kullanabilmek için kişinin
            # commit'e YAZACAĞI değeri bilmesi gerekir ([#42]).
            "task_key": task.task_key,
            "task_url": task.task_url,
            "archived": bool(task.archived),
            "links": list_links(session, task.id),
        })
    # Bağı olan işler üstte: ekranda karar verilecek/incelenecek olan onlar.
    gorevler.sort(key=lambda g: (not g["links"], (g["title"] or "").lower()))
    return {
        "developer": {"id": dev.id, "display_name": dev.display_name},
        "task_source": _task_source(cfg),
        "tasks": gorevler,
        "note": tr_text("Bağlar tahmindir; 'kesin' olanlar commit mesajında kart numarası "
                        "geçtiği için kuruldu. Bu görünüm yalnızca sizin (ve yöneticinizin) "
                        "erişimine açıktır."),
    }


def _one_on_one_points(summary: dict) -> list[dict]:
    """Bireysel özetten 1:1 konuşma noktaları üretir. Destek dili: kutlama +
    birlikte bakılacak yerler. ASLA ceza/kıyas dili — yön hep 'nasıl yardımcı
    olabilirim'. Kişi başkasıyla kıyaslanmaz, yalnız kendi trendiyle."""
    wins, focus = [], []
    for m in summary["metrics"]:
        name = m["name"]
        st = m["status"]
        prev = m.get("previous_value")
        cur = m.get("value")
        improved = (
            prev is not None and cur is not None and m.get("direction") != "higher"
            and cur < prev
        )
        if st == "green":
            wins.append(tr_text("{name}: sağlıklı seyrediyor — takdir et.", name=name))
        elif st == "red":
            focus.append(tr_text("{name}: zorlanma işareti. Ne engel oluyor, nasıl destek "
                                 "olabilirim diye birlikte bak.", name=name))
        elif st == "yellow":
            focus.append(tr_text("{name}: izlenmeli. Erken konuşmak sorunu büyümeden çözer.",
                                 name=name))
        if improved:
            wins.append(tr_text("{name}: geçen döneme göre iyileşmiş — ilerlemeyi görünür kıl.",
                                name=name))
    if not wins:
        wins.append(tr_text("Bu dönemde öne çıkan pozitif ve zorlanma yeterli veriyle "
                            "ölçülemedi — genel gidişatı ve moralı konuş."))
    return [
        {"section": tr_text("Kutlanacaklar"), "tone": "positive", "items": wins},
        {"section": tr_text("Birlikte bakılacaklar"), "tone": "support", "items": focus},
        {"section": tr_text("Hatırlatma"), "tone": "neutral", "items": [
            tr_text("Bu notlar performans puanı değil; süreç sağlığı ve destek içindir."),
            tr_text("Kıyas yalnızca kişinin kendi geçmişiyledir, başka kişiyle değil."),
        ]},
    ]


@router.get("/developers/{dev_id}/one-on-one")
def developer_one_on_one(
    dev_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """1:1 görüşme hazırlık özeti — bireysel görünümle AYNI yetki kurallarına
    tabidir (kişinin kendisi, yöneticisi ya da admin)."""
    # Dil AÇIKÇA geçilmeli: developer_summary'nin `lang` parametresi FastAPI
    # bağımlılığıdır ve doğrudan çağrıda devreye girmez — varsayılana düşünce
    # İngilizce arayüzde 1:1 özetindeki metrik adları Türkçe kalıyordu.
    summary = developer_summary(dev_id, session, user, current_lang())
    return {
        "developer": summary["developer"],
        "window_days": summary["window_days"],
        "talking_points": _one_on_one_points(summary),
    }


def _dev_metrics(
    session: Session, dev: Developer, start: datetime, end: datetime, cfg: Config
) -> dict[str, dict]:
    """Kişinin kendi işleri üzerinden takım metriklerinin bireysel izdüşümü.
    Takım verisi yüklenir, kişiye filtrelenir; ayrı bir 'çıktı sayacı' yoktur."""
    from app.metrics.engine import TeamData, cycle_time, pr_review_time, review_latency, wip

    team_ids = [m.team_id for m in dev.memberships]
    if not team_ids:
        return {}
    team = session.get(Team, team_ids[0])
    data = load_team_data(session, team, start, end)
    filtered = TeamData(
        team=data.team,
        member_count=1,  # bireysel izdüşüm: payda kişinin kendisidir
        commits=[c for c in data.commits if c.author_id == dev.id],
        prs=[p for p in data.prs if p.author_id == dev.id],
        all_prs_count=len([p for p in data.prs if p.author_id == dev.id]),
        tasks=[t for t in data.tasks if t.assignee_id == dev.id],
        start=start,
        end=end,
        statuses=data.statuses,  # takımla aynı statü eşlemesi
    )
    out = {}
    for key, func in (
        ("cycle_time", cycle_time),
        ("pr_review_time", pr_review_time),
        ("review_latency", review_latency),
        ("wip", wip),
    ):
        if not cfg.metric(key).enabled:
            continue
        o = func(filtered, cfg)
        out[key] = {"value": o.value, "completeness": o.completeness}
    return out


# --- opsiyonel LLM önerisi (Faz 5) ---------------------------------------------

@router.get("/teams/{team_id}/ai-advice")
def ai_advice(team_id: int, session: Session = Depends(get_session)):
    cfg = get_config()
    from app.llm.advisor import build_advisor

    advisor = build_advisor(cfg)
    if advisor is None:
        raise HTTPException(503, tr_error(
            "LLM öneri katmanı kapalı (config: llm.enabled). On-prem kısıtı "
            "gereği varsayılan olarak hiçbir veri dış servise gönderilmez."
        ))
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    summary = team_summary(team_id, session)
    block = "\n".join(
        f"- {m['name']}: {m['value']:.2f} ({m['status_label']}, tamlık %{m['data_completeness']*100:.0f})"
        for m in summary["metrics"]
        if m["value"] is not None
    )
    return {"team": team.name, "advice": advisor.advise(team.name, block)}


# --- RAG asistanı --------------------------------------------------------------

class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


def _can_access_team(session: Session, user: User, team_id: int) -> bool:
    """Takım verisi takım üyesine ve admin'e açıktır. Başka takımın kaydını
    sormak 403'tür — RAG bağlamı ham kayıt taşıdığı için bu sınır özet
    uçlarından daha katı tutulur."""
    if user.role in ("admin", "hr") or user.is_owner:
        return True
    if user.developer_id is None:
        return False
    dev = session.get(Developer, user.developer_id)
    return dev is not None and any(m.team_id == team_id for m in dev.memberships)


@router.post("/teams/{team_id}/ask")
def ask_team(
    team_id: int,
    body: AskBody,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Takımın kendi kayıtlarına dayanan soru-cevap (RAG).

    Cevap YALNIZCA getirilen kayıtlardan çıkar; ilgili kayıt yoksa cevap
    üretilmez (hata değil, dürüst boşluk)."""
    cfg = get_config()
    if not cfg.rag.enabled:
        raise HTTPException(503, tr_error(
            "RAG asistanı kapalı (config: rag.enabled). On-prem kısıtı gereği "
            "varsayılan olarak kapalıdır."
        ))
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    if not _can_access_team(session, user, team_id):
        raise HTTPException(403, tr_error("Bu takımın kayıtlarına erişim yetkiniz yok"))

    from app.services.rag.query import answer as rag_answer

    result = rag_answer(session, cfg, body.question, team_id)
    if result.status == "error":
        raise HTTPException(503, result.reason or tr_error("RAG cevabı üretilemedi"))
    return {
        "team": team.name,
        "status": result.status,
        "answer": result.answer,
        "reason": result.reason,
        # İndeks ölçek sınırı gibi uyarılar kullanıcıya ULAŞMALI: cevap üretilir
        # ama sistemin yavaşlama sebebini bilmek kullanıcının hakkı (sessiz
        # bozulma, sebebi görünmeyen bozulmadır).
        "warnings": result.warnings,
        "sources": [
            {"n": s.n, "kind": s.source_kind, "id": s.source_id, "score": s.score}
            for s in result.sources
        ],
    }


class LinkDecisionBody(BaseModel):
    status: str = Field(pattern="^(confirmed|rejected)$")


def _task_of_team(session: Session, user: User, team_id: int, task_id: int) -> Task:
    """Takım erişimi + task'ın gerçekten O TAKIMA ait olduğu doğrulanır.

    İkinci kontrol şart: yalnız takım erişimine bakılsaydı, erişimi olan bir
    kullanıcı URL'deki task_id'yi değiştirerek BAŞKA takımın işini okuyabilirdi."""
    if session.get(Team, team_id) is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    if not _can_access_team(session, user, team_id):
        raise HTTPException(403, tr_error("Bu takımın kayıtlarına erişim yetkiniz yok"))
    task = session.get(Task, task_id)
    if task is None or task.team_id != team_id:
        raise HTTPException(404, tr_error("İş bulunamadı"))
    return task


@router.get("/teams/{team_id}/task-links")
def team_task_links(team_id: int,
                    session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
    """Takımın bağı olan tüm işleri, bağlarıyla birlikte döner (onay ekranı için).

    Bağı hiç olmayan iş listeye GİRMEZ: onay ekranı, karar verilecek şeyleri
    gösterir; motorun hiçbir aday bulamadığı iş için verilecek karar yoktur."""
    from app.services.task_link import list_links

    if session.get(Team, team_id) is None:
        raise HTTPException(404, tr_error("Takım bulunamadı"))
    if not _can_access_team(session, user, team_id):
        raise HTTPException(403, tr_error("Bu takımın kayıtlarına erişim yetkiniz yok"))

    out = []
    for task in session.scalars(select(Task).where(Task.team_id == team_id)):
        links = list_links(session, task.id)
        if not links:
            continue
        out.append({
            "task_id": task.id, "title": task.title, "status": task.status,
            # Kart numarası ekranda görünmeli: konvansiyonu kullanabilmek için
            # kişinin commit'e YAZACAĞI değeri bilmesi gerekir.
            "task_key": task.task_key, "task_url": task.task_url,
            "pending": sum(1 for x in links if x["status"] == "suggested"),
            "confirmed": sum(1 for x in links if x["status"] == "confirmed"),
            "links": links,
        })
    # Karar bekleyenler üstte: ekranın işi, bekleyen işi bitirtmek.
    out.sort(key=lambda x: (-x["pending"], -x["confirmed"]))
    return {"team_id": team_id, "tasks": out}


@router.get("/teams/{team_id}/tasks/{task_id}/links")
def task_links(team_id: int, task_id: int,
               session: Session = Depends(get_session),
               user: User = Depends(current_user)):
    """Bir işin commit bağları: motorun önerileri + insan kararları.

    KAYITLI veriyi okur, eşleştirmeyi yeniden hesaplamaz (bkz. task_link.list_links)."""
    from app.services.task_link import list_links

    task = _task_of_team(session, user, team_id, task_id)
    return {"task_id": task.id, "title": task.title,
            "task_key": task.task_key, "task_url": task.task_url,
            "links": list_links(session, task_id)}


@router.post("/teams/{team_id}/tasks/{task_id}/links/{commit_id}")
def decide_task_link(team_id: int, task_id: int, commit_id: int,
                     body: LinkDecisionBody,
                     session: Session = Depends(get_session),
                     user: User = Depends(require_admin)):
    """Bir bağı onaylar/reddeder. Karar kalıcıdır; senkron bunu EZMEZ."""
    from app.services.task_link import decide

    _task_of_team(session, user, team_id, task_id)
    if session.get(Commit, commit_id) is None:
        raise HTTPException(404, tr_error("Commit bulunamadı"))
    row = decide(session, task_id, commit_id, body.status, user_id=user.id)
    return {"task_id": task_id, "commit_id": commit_id, "status": row.status}


@router.post("/teams/{team_id}/tasks/{task_id}/analysis")
def task_analysis(team_id: int, task_id: int,
                  session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    """İşin süreç analizi — YALNIZ onaylanmış commit bağlarına dayanır.

    Onaylı bağ yoksa LLM çağrılmaz; 200 ile 'no_confirmed_links' döner
    (hata değil: analiz edilecek doğrulanmış veri yok)."""
    from app.services.task_analysis import analyze_task

    _task_of_team(session, user, team_id, task_id)
    result = analyze_task(session, get_config(), task_id)
    if result.status == "error":
        raise HTTPException(503, result.reason or tr_error("Analiz üretilemedi"))
    return {
        "task_id": result.task_id, "status": result.status,
        "analysis": result.text, "reason": result.reason,
        "commits_used": result.commits_used,
        # Kartta tarif edilen iş ile onaylı commit'lerin anlattığı iş örtüşüyor mu.
        # Model biçimi tutturamazsa None — uydurulmuş bir yargı dönmez.
        "alignment": result.alignment,
        "alignment_label": result.alignment_label,
    }


@router.get("/config/ui")
def ui_config():
    """Frontend'in neyi gösterip gizleyeceği: kapalı metrik kart bile olmaz."""
    cfg = get_config()
    # Trend grafiklerine hedef/eşik çizgisi için: metrik → {green, red, direction}
    thresholds = {}
    for metric_key, (field, direction) in METRIC_THRESHOLD_MAP.items():
        th = getattr(cfg.health_thresholds, field, None)
        if th is not None:
            thresholds[metric_key] = {"green": th.green, "red": th.red, "direction": direction}
    return {
        "enabled_metrics": [k for k, m in cfg.metrics.items() if m.enabled],
        "individual_view_enabled": cfg.app.individual_view_enabled
        and not cfg.app.anonymize_individuals,
        "anonymize_individuals": cfg.app.anonymize_individuals,
        "window_days": cfg.app.window_days,
        "llm_enabled": cfg.llm.enabled,
        "metric_thresholds": thresholds,
        # "Projelerim"de yerel klasör kaynağı seçilebilir mi. İzinli kök YOLLARI
        # gönderilmez (sunucu dizin yapısı sızmasın), yalnız açık/kapalı bilgisi.
        "projects_local_enabled": bool(cfg.projects.local_roots),
    }
