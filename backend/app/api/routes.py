"""REST API.

Etik çerçevenin (spec Bölüm 1 + İlke E) uygulandığı yer:
- Varsayılan görünüm TAKIM/PROJE'dir; takım uçları herkese açıktır.
- Bireysel görünüm yalnızca kişinin KENDİSİ ya da YÖNETİCİSİ içindir.
- Kıyaslamalı leaderboard ucu YOKTUR ve eklenmez: hiçbir uç, birden çok
  kişinin metriklerini yan yana döndürmez.
- Anonimleştirme modunda bireysel uçlar kapanır, isimler maskelenir.
- Kimlik, demo amaçlı X-Dev-Id başlığından okunur; şirket ortamında bu
  katman SSO/reverse-proxy başlığıyla değiştirilir (tek nokta).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.config import Config, get_config
from app.core.db import get_session
from app.metrics.engine import METRIC_FUNCS, load_team_data
from app.models import (
    CodeQualitySnapshot,
    Developer,
    MetricResult,
    Recommendation,
    Repo,
    Team,
    TeamMembership,
)
from app.services.health import (
    METRIC_META,
    METRIC_THRESHOLD_MAP,
    STATUS_LABELS,
    health_status,
)

router = APIRouter(prefix="/api")


# --- kimlik ve yetki yardımcıları ---------------------------------------------

def current_dev(
    session: Session = Depends(get_session),
    x_dev_id: int | None = Header(default=None),
) -> Developer | None:
    if x_dev_id is None:
        return None
    return session.get(Developer, x_dev_id)


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


@router.get("/teams/{team_id}/quality")
def team_quality(team_id: int, session: Session = Depends(get_session)):
    if session.get(Team, team_id) is None:
        raise HTTPException(404, "Takım bulunamadı")
    repos = session.scalars(select(Repo).where(Repo.team_id == team_id)).all()
    out = []
    for repo in repos:
        snap = session.scalars(
            select(CodeQualitySnapshot)
            .where(CodeQualitySnapshot.repo_id == repo.id)
            .order_by(CodeQualitySnapshot.taken_at.desc())
            .limit(1)
        ).first()
        out.append(
            {
                "repo": repo.name,
                "snapshot": None
                if snap is None
                else {
                    "taken_at": snap.taken_at.isoformat() if snap.taken_at else None,
                    "coverage": snap.coverage,
                    "complexity": snap.complexity,
                    "duplication": snap.duplication,
                    "code_smells": snap.code_smells,
                },
            }
        )
    return out


# --- bireysel görünüm (Faz 4: yetkili, leaderboard YOK) -------------------------

@router.get("/me")
def me(
    session: Session = Depends(get_session),
    dev: Developer | None = Depends(current_dev),
):
    """Demo kullanıcı değiştirici için: kimim, hangi takımdayım, yönetici miyim."""
    cfg = get_config()
    if dev is None:
        return {"authenticated": False}
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
    """Kişi listesi (demo kimlik seçici). Metrik İÇERMEZ — sadece isim/rol;
    liste + metrik birleşimi leaderboard doğurur, o uç bilerek yoktur."""
    cfg = get_config()
    out = []
    for dev in session.scalars(select(Developer)):
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
    requester: Developer | None = Depends(current_dev),
):
    """Bireysel sağlık görünümü. Kurallar:
    - anonimleştirme modunda ya da özellik kapalıysa tamamen devre dışı;
    - yalnızca kişinin kendisi ya da yöneticisi erişebilir;
    - kıyas yalnızca kişinin KENDİ geçmişiyle yapılır, asla başkasıyla."""
    cfg = get_config()
    if not cfg.app.individual_view_enabled or cfg.app.anonymize_individuals:
        raise HTTPException(403, "Bireysel görünüm bu kurulumda kapalı (takım-agregat mod)")
    dev = session.get(Developer, dev_id)
    if dev is None:
        raise HTTPException(404, "Kişi bulunamadı")
    if requester is None:
        raise HTTPException(401, "Kimlik gerekli (X-Dev-Id başlığı)")
    if requester.id != dev.id and not _is_manager_of(session, requester, dev):
        raise HTTPException(403, "Bireysel görünümü yalnızca kişinin kendisi ve yöneticisi görebilir")

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
    return {
        "developer": {"id": dev.id, "display_name": dev.display_name},
        "window_days": cfg.app.window_days,
        "metrics": metrics,
        "note": "Bu görünüm yalnızca sizin (ve yöneticinizin) erişimine açıktır; "
                "kıyas yalnızca kendi geçmişinizle yapılır.",
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
        member_count=1,
        commits=[c for c in data.commits if c.author_id == dev.id],
        prs=[p for p in data.prs if p.author_id == dev.id],
        all_prs_count=len([p for p in data.prs if p.author_id == dev.id]),
        tasks=[t for t in data.tasks if t.assignee_id == dev.id],
        start=start,
        end=end,
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
    }
