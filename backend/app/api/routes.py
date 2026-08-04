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
from app.services.health import (
    METRIC_META,
    METRIC_THRESHOLD_MAP,
    STATUS_LABELS,
    health_status,
)
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


def _metric_payload(row: MetricResult, cfg: Config) -> dict:
    status = health_status(row.metric_key, row.value, row.data_completeness, cfg)
    name, description = METRIC_META.get(row.metric_key, (row.metric_key, ""))
    return {
        "key": row.metric_key,
        "name": name,
        "description": description,
        "value": row.value,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "data_completeness": row.data_completeness,
        "source_layer": row.source_layer,
        "sample_size": row.sample_size,
        "stats": row.stats,
        "period": row.period,
    }


@router.get("/teams/{team_id}/summary")
def team_summary(team_id: int, session: Session = Depends(get_session)):
    cfg = get_config()
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "Takım bulunamadı")
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
    recs = session.scalars(
        select(Recommendation).where(
            Recommendation.scope == "team", Recommendation.scope_id == team_id
        )
    ).all()
    member_count = sum(1 for m in team.memberships if m.role != "manager")
    return {
        "team": {"id": team.id, "name": team.name, "member_count": member_count},
        "metrics": [_metric_payload(r, cfg) for r in overall.values()],
        "recommendations": [
            {"rule": r.rule_key, "message": r.message, "severity": r.severity}
            for r in recs
        ],
        "anonymized": cfg.app.anonymize_individuals,
    }


@router.get("/teams/{team_id}/report")
def team_report(
    team_id: int,
    days: int = Query(default=30),
    session: Session = Depends(get_session),
):
    """Seçilen aralık (7/30/90) için anlık hesaplanan metrikler + delta +
    sağlık sinyalleri + trend. Precompute'a değil, canlı motora dayanır."""
    from app.services.report import VALID_DAYS, live_report

    if days not in VALID_DAYS:
        raise HTTPException(422, f"days yalnızca {sorted(VALID_DAYS)} olabilir")
    cfg = get_config()
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "Takım bulunamadı")
    return live_report(session, team, days, cfg)


@router.get("/teams/{team_id}/metric/{metric_key}/breakdown")
def team_metric_breakdown(
    team_id: int,
    metric_key: str,
    days: int = Query(default=30),
    session: Session = Depends(get_session),
):
    """Drill-down: bir metriğin altındaki ham kayıtlar (hangi iş/PR/commit bu
    sayıyı oluşturuyor). Şeffaflık için — sayı gökten inmiyor."""
    from app.services.report import VALID_DAYS, metric_breakdown

    if days not in VALID_DAYS:
        raise HTTPException(422, f"days yalnızca {sorted(VALID_DAYS)} olabilir")
    cfg = get_config()
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "Takım bulunamadı")
    return metric_breakdown(session, team, metric_key, days, cfg)


@router.get("/teams/{team_id}/series/{metric_key}")
def team_series(team_id: int, metric_key: str, session: Session = Depends(get_session)):
    cfg = get_config()
    if session.get(Team, team_id) is None:
        raise HTTPException(404, "Takım bulunamadı")
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
    name, description = METRIC_META.get(metric_key, (metric_key, ""))
    return {"metric": metric_key, "name": name, "description": description, "points": points}


# --- Kişi-bazlı kod sağlığı (kendi kodu / admin herkesi) ----------------------
# Kimlik JWT (current_user). Erişim: kişinin KENDİSİ ya da admin. Kıyaslamalı
# leaderboard YOK — her kişiye tekil, kendi kodunun geri bildirimi.

def _dev_access(dev_id: int, user):
    if user.role != "admin" and user.developer_id != dev_id:
        raise HTTPException(403, "Bu görünümü yalnızca kişinin kendisi ve admin görebilir")


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
        raise HTTPException(404, "Takım bulunamadı")
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
def my_code_health(session: Session = Depends(get_session), user=Depends(current_user)):
    from app.services.code_health import developer_code_health
    if user.developer_id is None:
        raise HTTPException(404, "Hesap bir geliştiriciye bağlı değil")
    return developer_code_health(session, user.developer_id, get_config())


@router.get("/me/code-health/breakdown")
def my_code_health_breakdown(session: Session = Depends(get_session), user=Depends(current_user)):
    from app.services.code_health import developer_code_health_breakdown
    if user.developer_id is None:
        raise HTTPException(404, "Hesap bir geliştiriciye bağlı değil")
    return developer_code_health_breakdown(session, user.developer_id)


@router.post("/me/code-analysis/run")
def my_code_analysis_run(session: Session = Depends(get_session), user=Depends(current_user)):
    """Kullanıcı KENDİ kodunu analiz eder (git yazarı = kendisi)."""
    from app.services.code_analysis import run_code_analysis
    if user.developer_id is None:
        raise HTTPException(404, "Hesap bir geliştiriciye bağlı değil")
    return run_code_analysis(session, get_config(), only_developer_id=user.developer_id)


@router.get("/developers/{dev_id}/code-health")
def developer_code_health_endpoint(dev_id: int, session: Session = Depends(get_session),
                                   user=Depends(current_user)):
    from app.services.code_health import developer_code_health
    _dev_access(dev_id, user)
    return developer_code_health(session, dev_id, get_config())


@router.get("/developers/{dev_id}/code-health/breakdown")
def developer_code_health_breakdown_endpoint(dev_id: int, session: Session = Depends(get_session),
                                             user=Depends(current_user)):
    from app.services.code_health import developer_code_health_breakdown
    _dev_access(dev_id, user)
    return developer_code_health_breakdown(session, dev_id)


@router.get("/teams/{team_id}/code-health")
def team_code_health_endpoint(team_id: int, session: Session = Depends(get_session)):
    """AI kod sağlığı kartı: composite + modül kırılımı (kişi değil)."""
    from app.services.code_health import team_code_health

    if session.get(Team, team_id) is None:
        raise HTTPException(404, "Takım bulunamadı")
    return team_code_health(session, team_id, get_config())


@router.get("/teams/{team_id}/code-health/breakdown")
def team_code_health_breakdown_endpoint(team_id: int, session: Session = Depends(get_session)):
    """Drill-down: en çok dikkat isteyen dosyalar + AI önerileri."""
    from app.services.code_health import team_code_health_breakdown

    if session.get(Team, team_id) is None:
        raise HTTPException(404, "Takım bulunamadı")
    return team_code_health_breakdown(session, team_id)


@router.get("/teams/{team_id}/code-health/series")
def team_code_health_series_endpoint(team_id: int, session: Session = Depends(get_session)):
    """Haftalık kod sağlığı trendi."""
    from app.services.code_health import team_code_health_series

    if session.get(Team, team_id) is None:
        raise HTTPException(404, "Takım bulunamadı")
    return team_code_health_series(session, team_id, get_config())


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


@router.get("/developers/{dev_id}/summary")
def developer_summary(
    dev_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Bireysel sağlık görünümü. Kurallar:
    - anonimleştirme modunda ya da özellik kapalıysa tamamen devre dışı;
    - yalnızca kişinin kendisi, yöneticisi ya da admin erişebilir;
    - kıyas yalnızca kişinin KENDİ geçmişiyle yapılır, asla başkasıyla."""
    cfg = get_config()
    if not cfg.app.individual_view_enabled or cfg.app.anonymize_individuals:
        raise HTTPException(403, "Bireysel görünüm bu kurulumda kapalı (takım-agregat mod)")
    dev = session.get(Developer, dev_id)
    if dev is None:
        raise HTTPException(404, "Kişi bulunamadı")
    # Yetki YALNIZ JWT kimliğiyle: admin herkesi görebilir; aksi halde kişinin
    # KENDİSİ (user.developer_id) ya da yöneticisi. Yetki hatası 403 (401 DEĞİL:
    # istemcide oturumu düşürmesin). Kimliksiz istek router seviyesinde 401 olur.
    if user.role != "admin":
        requester = session.get(Developer, user.developer_id) if user.developer_id else None
        if requester is None or (requester.id != dev.id and not _is_manager_of(session, requester, dev)):
            raise HTTPException(403, "Bireysel görünümü yalnızca kişinin kendisi, yöneticisi ya da admin görebilir")

    now = datetime.now(timezone.utc)
    window = timedelta(days=cfg.app.window_days)
    current = _dev_metrics(session, dev, now - window, now, cfg)
    previous = _dev_metrics(session, dev, now - 2 * window, now - window, cfg)
    metrics = []
    for key, cur in current.items():
        prev_val = previous.get(key, {}).get("value")
        status = health_status(key, cur["value"], cur["completeness"], cfg)
        name, description = METRIC_META.get(key, (key, ""))
        metrics.append(
            {
                "key": key,
                "name": name,
                "description": description,
                "value": cur["value"],
                "status": status,
                "status_label": STATUS_LABELS[status],
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
        "note": "Bu görünüm yalnızca sizin (ve yöneticinizin) erişimine açıktır; "
                "kıyas yalnızca kendi geçmişinizle yapılır.",
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
            wins.append(f"{name}: sağlıklı seyrediyor — takdir et.")
        elif st == "red":
            focus.append(f"{name}: zorlanma işareti. Ne engel oluyor, nasıl "
                         f"destek olabilirim diye birlikte bak.")
        elif st == "yellow":
            focus.append(f"{name}: izlenmeli. Erken konuşmak sorunu büyümeden çözer.")
        if improved:
            wins.append(f"{name}: geçen döneme göre iyileşmiş — ilerlemeyi görünür kıl.")
    if not wins:
        wins.append("Bu dönemde öne çıkan pozitif ve zorlanma yeterli veriyle "
                    "ölçülemedi — genel gidişatı ve moralı konuş.")
    return [
        {"section": "Kutlanacaklar", "tone": "positive", "items": wins},
        {"section": "Birlikte bakılacaklar", "tone": "support", "items": focus},
        {"section": "Hatırlatma", "tone": "neutral", "items": [
            "Bu notlar performans puanı değil; süreç sağlığı ve destek içindir.",
            "Kıyas yalnızca kişinin kendi geçmişiyledir, başka kişiyle değil.",
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
    summary = developer_summary(dev_id, session, user)
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
        raise HTTPException(
            503, "LLM öneri katmanı kapalı (config: llm.enabled). On-prem kısıtı "
                 "gereği varsayılan olarak hiçbir veri dış servise gönderilmez."
        )
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "Takım bulunamadı")
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
        raise HTTPException(
            503, "RAG asistanı kapalı (config: rag.enabled). On-prem kısıtı gereği "
                 "varsayılan olarak kapalıdır."
        )
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "Takım bulunamadı")
    if not _can_access_team(session, user, team_id):
        raise HTTPException(403, "Bu takımın kayıtlarına erişim yetkiniz yok")

    from app.services.rag.query import answer as rag_answer

    result = rag_answer(session, cfg, body.question, team_id)
    if result.status == "error":
        raise HTTPException(503, result.reason or "RAG cevabı üretilemedi")
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
        raise HTTPException(404, "Takım bulunamadı")
    if not _can_access_team(session, user, team_id):
        raise HTTPException(403, "Bu takımın kayıtlarına erişim yetkiniz yok")
    task = session.get(Task, task_id)
    if task is None or task.team_id != team_id:
        raise HTTPException(404, "İş bulunamadı")
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
        raise HTTPException(404, "Takım bulunamadı")
    if not _can_access_team(session, user, team_id):
        raise HTTPException(403, "Bu takımın kayıtlarına erişim yetkiniz yok")

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
        raise HTTPException(404, "Commit bulunamadı")
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
        raise HTTPException(503, result.reason or "Analiz üretilemedi")
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
