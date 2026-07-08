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

from fastapi import APIRouter, Depends, Header, HTTPException
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
    User,
)
from app.services.health import METRIC_META, STATUS_LABELS, health_status

router = APIRouter(prefix="/api")


# --- kimlik ve yetki yardımcıları ---------------------------------------------

def current_dev(
    session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
    x_dev_id: int | None = Header(default=None),
) -> Developer | None:
    """TEK kimlik noktası (Faz 1). Öncelik JWT'dedir: Bearer → User →
    Developer. Demo modunda (app.demo_auth_enabled) X-Dev-Id başlığı da
    kabul edilir; prod'da bayrak kapatılır, yalnız JWT kalır."""
    if user is not None:
        if user.developer_id is None:
            return None
        return session.get(Developer, user.developer_id)
    if get_config().app.demo_auth_enabled and x_dev_id is not None:
        return session.get(Developer, x_dev_id)
    return None


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
    points = []
    for row in rows:
        try:
            p_start, p_end = row.period.split("/")
            span = (datetime.fromisoformat(p_end) - datetime.fromisoformat(p_start)).days
        except ValueError:
            continue
        if span < cfg.app.window_days - 1:  # yalnızca kovalar
            points.append(
                {
                    "period_start": p_start,
                    "period_end": p_end,
                    "value": row.value,
                    "data_completeness": row.data_completeness,
                }
            )
    points.sort(key=lambda p: p["period_start"])
    name, description = METRIC_META.get(metric_key, (metric_key, ""))
    return {"metric": metric_key, "name": name, "description": description, "points": points}


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
    user: User | None = Depends(current_user),
):
    """Kimim: hesap (JWT'liyse email/rol) + geliştirici profili (varsa).
    Admin hesabı developer'a bağlı olmayabilir — yine authenticated'dır."""
    cfg = get_config()
    if dev is None and user is None:
        return {"authenticated": False}
    out = {"authenticated": True}
    if user is not None:
        out["account"] = {"email": user.email, "role": user.role}
    if dev is not None:
        out.update(
            {
                "id": dev.id,
                "display_name": _mask_name(dev, cfg),
                "teams": [
                    {"team_id": m.team_id, "role": m.role} for m in dev.memberships
                ],
            }
        )
    return out


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
    return {
        "enabled_metrics": [k for k, m in cfg.metrics.items() if m.enabled],
        "individual_view_enabled": cfg.app.individual_view_enabled
        and not cfg.app.anonymize_individuals,
        "anonymize_individuals": cfg.app.anonymize_individuals,
        "window_days": cfg.app.window_days,
        "llm_enabled": cfg.llm.enabled,
    }
