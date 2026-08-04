"""Canlı takım raporu — seçilen tarih aralığına göre ANLIK hesap.

Precompute (metric_results) sabit 30 günlük penceredir; kullanıcı 7/30/90
seçince metrikler, trend ve sinyaller bu pencereye göre yeniden hesaplanır.
Aynı motor (METRIC_FUNCS) kullanılır — ikinci bir hesap yolu yoktur.

Ek olarak:
- delta: her metriğin bir önceki eş pencereye göre değişimi (İlke E: kıyas
  yalnızca kendi geçmişiyle, başka takımla değil).
- breakdown: bir metriğin altındaki ham kayıtlar (drill-down) — sayı nereden
  geliyor şeffaf görünsün.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Config
from app.metrics.engine import (
    HOTFIX_HINTS,
    METRIC_FUNCS,
    TeamData,
    _deploy_events,
    _revert_target_sha,
    _task_done_at,
    _task_started_at,
    as_utc,
    is_in_flow,
    load_team_data,
)
from app.models import Recommendation, Team
from app.services.health import METRIC_META, METRIC_THRESHOLD_MAP, STATUS_LABELS, health_status
from app.services.signals import compute_signals

VALID_DAYS = {7, 30, 90}
BUCKET_FOR_DAYS = {7: 1, 30: 7, 90: 14}  # gün: kova boyu (gün)


def _direction(metric_key: str) -> str:
    """Frontend delta rengi için: 'lower' = değer düşerse iyi."""
    mapping = METRIC_THRESHOLD_MAP.get(metric_key)
    return mapping[1] if mapping else "lower"


def _metric_dict(key: str, outcome, cfg: Config, previous_value: float | None) -> dict:
    status = health_status(key, outcome.value, outcome.completeness, cfg)
    name, description = METRIC_META.get(key, (key, ""))
    return {
        "key": key,
        "name": name,
        "description": description,
        "value": outcome.value,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "data_completeness": outcome.completeness,
        "source_layer": outcome.source_layer,
        "sample_size": outcome.sample,
        "stats": outcome.stats,
        "previous_value": previous_value,
        "direction": _direction(key),
    }


def _compute_window(session: Session, team: Team, start: datetime, end: datetime,
                    cfg: Config) -> dict[str, object]:
    data = load_team_data(session, team, start, end)
    out = {}
    for key, func in METRIC_FUNCS.items():
        if not cfg.metric(key).enabled:
            continue
        out[key] = func(data, cfg)
    return out


def live_report(session: Session, team: Team, days: int, cfg: Config) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    current = _compute_window(session, team, start, now, cfg)
    previous = _compute_window(session, team, prev_start, start, cfg)

    metrics = [
        _metric_dict(key, oc, cfg, previous.get(key).value if previous.get(key) else None)
        for key, oc in current.items()
    ]

    data = load_team_data(session, team, start, now)
    signals = compute_signals(session, data)

    recs = session.scalars(
        select(Recommendation).where(
            Recommendation.scope == "team", Recommendation.scope_id == team.id
        )
    ).all()

    member_count = sum(1 for m in team.memberships if m.role != "manager")
    return {
        "team": {"id": team.id, "name": team.name, "member_count": member_count},
        "window_days": days,
        "metrics": metrics,
        "signals": signals,
        "series": _live_series(session, team, days, cfg),
        "recommendations": [
            {"rule": r.rule_key, "message": r.message, "severity": r.severity}
            for r in recs
        ],
    }


def _live_series(session: Session, team: Team, days: int, cfg: Config) -> list[dict]:
    """Seçilen aralık için haftalık/kova bazlı trend — anlık hesap."""
    from app.metrics.engine import SERIES_METRICS

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    bucket = timedelta(days=BUCKET_FOR_DAYS.get(days, 7))

    series_points: dict[str, list[dict]] = {k: [] for k in SERIES_METRICS if cfg.metric(k).enabled}
    b_start = start
    while b_start < now:
        b_end = min(b_start + bucket, now)
        data = load_team_data(session, team, b_start, b_end)
        for key in series_points:
            oc = METRIC_FUNCS[key](data, cfg)
            series_points[key].append({
                "period_start": f"{b_start:%Y-%m-%d}",
                "period_end": f"{b_end:%Y-%m-%d}",
                "value": oc.value,
                "data_completeness": oc.completeness,
            })
        b_start = b_end

    out = []
    for key, points in series_points.items():
        name, description = METRIC_META.get(key, (key, ""))
        # direction: frontend'in trend özetini doğru yönde okuması için
        # ('higher' metrikte artış İYİ, 'lower' metrikte azalış iyi).
        out.append({
            "metric": key, "name": name, "description": description,
            "direction": _direction(key), "points": points,
        })
    return out


# --- Drill-down: bir metriğin altındaki ham kayıtlar ---------------------------

def metric_breakdown(session: Session, team: Team, key: str, days: int, cfg: Config) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    data = load_team_data(session, team, start, now)
    rows = _BREAKDOWN.get(key, _breakdown_unsupported)(data)
    name, _ = METRIC_META.get(key, (key, ""))
    return {"metric": key, "name": name, "window_days": days, "rows": rows,
            "count": len(rows)}


def _fmt_days(seconds: float) -> float:
    return round(seconds / 86400, 2)


def _breakdown_cycle_time(data: TeamData) -> list[dict]:
    rows = []
    for t in data.tasks:
        done = _task_done_at(t, data.statuses)
        if done is None or not (data.start <= done <= data.end):
            continue
        started = _task_started_at(t, data.statuses)
        if started and done >= started:
            rows.append({
                "label": t.title or f"Task #{t.external_id}",
                "detail": f"{t.status or ''}",
                "value": _fmt_days((done - started).total_seconds()),
                "unit": "gün",
                "date": f"{done:%Y-%m-%d}",
            })
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows


def _breakdown_pr_duration(field: str):
    def fn(data: TeamData) -> list[dict]:
        rows = []
        for p in data.prs:
            merged = as_utc(p.merged_at)
            opened = as_utc(p.opened_at)
            if field == "merge":
                if merged and opened and data.start <= merged <= data.end and merged >= opened:
                    rows.append({
                        "label": p.title or f"PR #{p.external_id}",
                        "detail": "açılış→merge",
                        "value": _fmt_days((merged - opened).total_seconds()),
                        "unit": "gün", "date": f"{merged:%Y-%m-%d}",
                    })
            else:  # review latency
                first = as_utc(p.first_review_at)
                if opened and data.start <= opened <= data.end:
                    if first and first >= opened:
                        rows.append({
                            "label": p.title or f"PR #{p.external_id}",
                            "detail": "açılış→ilk review",
                            "value": _fmt_days((first - opened).total_seconds()),
                            "unit": "gün", "date": f"{opened:%Y-%m-%d}",
                        })
                    else:
                        rows.append({
                            "label": p.title or f"PR #{p.external_id}",
                            "detail": "henüz review almadı",
                            "value": None, "unit": "gün", "date": f"{opened:%Y-%m-%d}",
                        })
        rows.sort(key=lambda r: (r["value"] is not None, r["value"] or 0), reverse=True)
        return rows
    return fn


def _breakdown_deploys(data: TeamData) -> list[dict]:
    return [
        {"label": "Teslim (merge)", "detail": "main'e merge proxy'si",
         "value": None, "unit": "", "date": f"{d:%Y-%m-%d %H:%M}"}
        for d in _deploy_events(data)
    ]


def _breakdown_wip(data: TeamData) -> list[dict]:
    rows = []
    for t in data.tasks:
        # Statü kategorileri data.statuses'tan (config + varsayılan) gelir —
        # burada ikinci bir gömülü liste tutmak drilldown'ın metrikle
        # çelişmesine yol açıyordu. Akış tanımı da metrikle AYNI (is_in_flow):
        # eşlenmemiş kolon WIP'e girmiyorsa drilldown'da da görünmemeli.
        if t.status is None or not is_in_flow(t.status, data.statuses):
            continue
        rows.append({
            "label": t.title or f"Task #{t.external_id}",
            "detail": t.status or "", "value": None, "unit": "", "date": "",
        })
    return rows


def _breakdown_change_failure(data: TeamData) -> list[dict]:
    rows = []
    for c in data.commits:
        low = (c.message or "").lower()
        if any(h in low for h in HOTFIX_HINTS):
            ts = as_utc(c.committed_at)
            rows.append({
                "label": (c.message or "").splitlines()[0][:80] if c.message else c.sha[:10],
                "detail": "hotfix/revert sinyali", "value": None, "unit": "",
                "date": f"{ts:%Y-%m-%d}" if ts else "",
            })
    return rows


def _breakdown_rework(data: TeamData) -> list[dict]:
    from collections import Counter
    counter: Counter = Counter()
    for c in data.commits:
        for f in c.changed_files or []:
            counter[f] += 1
    rows = [
        {"label": f, "detail": "dosyaya dokunma sayısı", "value": n, "unit": "×", "date": ""}
        for f, n in counter.most_common() if n > 1
    ]
    return rows


def _breakdown_mttr(data: TeamData) -> list[dict]:
    # incident/revert verisi yoksa boş döner — drill-down da dürüst
    rows = []
    by_sha = {c.sha[:12]: c for c in data.commits if c.sha}
    for c in data.commits:
        target = _revert_target_sha(c.message)
        if target is None:
            continue
        orig = by_sha.get(target[:12])
        rev_ts = as_utc(c.committed_at)
        orig_ts = as_utc(orig.committed_at) if orig else None
        rows.append({
            "label": (c.message or "")[:80] or c.sha[:10],
            "detail": "revert eşleşmesi" if orig_ts else "orijinal commit penceresde yok",
            "value": round((rev_ts - orig_ts).total_seconds() / 3600, 1) if (orig_ts and rev_ts and rev_ts >= orig_ts) else None,
            "unit": "saat",
            "date": f"{rev_ts:%Y-%m-%d}" if rev_ts else "",
        })
    return rows


def _breakdown_unsupported(data: TeamData) -> list[dict]:
    return []


_BREAKDOWN = {
    "cycle_time": _breakdown_cycle_time,
    "pr_review_time": _breakdown_pr_duration("merge"),
    "review_latency": _breakdown_pr_duration("review"),
    "deployment_frequency": _breakdown_deploys,
    "wip": _breakdown_wip,
    "change_failure_rate": _breakdown_change_failure,
    "rework": _breakdown_rework,
    "mttr": _breakdown_mttr,
}
