"""Bildirim servisi + trend alarmı üretimi.

Etik çerçeve: bildirim de gözetim değil. Trend alarmı takım sağlığı sinyalidir
("metrik kırmızıya döndü, yardım gerekebilir"). Kişi kıyası, isim ifşası ya da
ceza dili YOK — takım seviyesinde, destek dilinde.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Notification, TeamMembership, User


def notify(
    session: Session,
    user_id: int,
    *,
    kind: str,
    title: str,
    body: str | None = None,
    severity: str = "info",
    dedup_key: str | None = None,
    link: str | None = None,
) -> Notification | None:
    """Bildirim ekler. dedup_key verilirse ve o kullanıcıda OKUNMAMIŞ aynı
    anahtarlı bildirim varsa yeniden eklemez (spam önleme). commit ÇAĞIRMAZ."""
    if dedup_key is not None:
        existing = session.scalar(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.dedup_key == dedup_key,
                Notification.is_read.is_(False),
            )
        )
        if existing is not None:
            return None
    n = Notification(
        user_id=user_id,
        kind=kind,
        severity=severity,
        title=title,
        body=body,
        dedup_key=dedup_key,
        link=link,
        is_read=False,
        created_at=datetime.now(timezone.utc),
    )
    session.add(n)
    return n


def _recipients_for_team(session: Session, team_id: int) -> set[int]:
    """Takım alarmının gideceği kullanıcılar: takım yöneticileri + tüm adminler.
    (Bireysel ifşa yok — alarm takım sağlığı hakkında.)"""
    recipients: set[int] = set()
    # Takım yöneticileri (developer_id üzerinden user'a bağlı)
    mgr_dev_ids = {
        m.developer_id
        for m in session.scalars(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.role == "manager",
            )
        )
        if m.developer_id is not None
    }
    if mgr_dev_ids:
        for u in session.scalars(
            select(User).where(User.developer_id.in_(mgr_dev_ids), User.is_active.is_(True))
        ):
            recipients.add(u.id)
    # Tüm aktif adminler
    for u in session.scalars(
        select(User).where(User.role == "admin", User.is_active.is_(True))
    ):
        recipients.add(u.id)
    return recipients


def emit_trend_alarm(
    session: Session,
    *,
    team_id: int,
    team_name: str,
    metric_key: str,
    metric_name: str,
    period: str,
) -> int:
    """Bir metrik kırmızıya döndüğünde ilgili kullanıcılara alarm üretir.
    dedup: aynı takım+metrik+period için tek alarm. Kaç bildirim üretildiğini döner."""
    dedup = f"trend:{team_id}:{metric_key}:{period}"
    recipients = _recipients_for_team(session, team_id)
    count = 0
    for uid in recipients:
        n = notify(
            session,
            uid,
            kind="trend_alarm",
            severity="warning",
            title=f"{team_name}: {metric_name} kırmızıya döndü",
            body="Takım bu metrikte zorlanıyor olabilir — destek gerekebilir. "
                 "Bu bir sağlık sinyalidir, kişi değerlendirmesi değildir.",
            dedup_key=dedup,
            link=f"/?team={team_id}",
        )
        if n is not None:
            count += 1
    return count


def scan_and_emit_trend_alarms(session: Session) -> int:
    """Pipeline sonrası: her takımın pencere metriklerini tarar, kırmızı olanlar
    için ilgili kullanıcılara alarm üretir (dedup ile tekrarsız). Üretilen
    toplam bildirim sayısını döner. Etik: yalnız takım-seviyesi, destek dili."""
    from datetime import datetime as _dt

    from app.core.config import get_config
    from app.models import MetricResult, Team
    from app.services.health import METRIC_META, health_status

    cfg = get_config()
    window_days = cfg.app.window_days
    total = 0
    for team in session.scalars(select(Team)):
        rows = session.scalars(
            select(MetricResult).where(
                MetricResult.scope == "team", MetricResult.scope_id == team.id
            )
        ).all()
        # En güncel pencere satırını metrik başına seç (team_summary ile aynı mantık).
        window_rows: dict[str, MetricResult] = {}
        for row in rows:
            try:
                p_start, p_end = row.period.split("/")
                span = (_dt.fromisoformat(p_end) - _dt.fromisoformat(p_start)).days
            except ValueError:
                span = 0
            if span < window_days - 1:
                continue
            prev = window_rows.get(row.metric_key)
            if prev is None or (
                row.computed_at and prev.computed_at and row.computed_at > prev.computed_at
            ):
                window_rows[row.metric_key] = row
        for key, row in window_rows.items():
            status = health_status(key, row.value, row.data_completeness, cfg)
            if status != "red":
                continue
            name, _ = METRIC_META.get(key, (key, ""))
            total += emit_trend_alarm(
                session,
                team_id=team.id,
                team_name=team.name,
                metric_key=key,
                metric_name=name,
                period=row.period,
            )
        # Sağlık sinyalleri de kırmızıysa alarm üret (burnout, bus factor,
        # WIP yığılması, izin kültürü). Etik: takım-seviyesi, kişi ifşası yok.
        total += _emit_signal_alarms(session, team)
    session.commit()
    return total


def _emit_signal_alarms(session: Session, team) -> int:
    from datetime import datetime as _dt, timedelta as _td

    from app.core.config import get_config
    from app.metrics.engine import load_team_data
    from app.services.signals import SIGNAL_META, compute_signals

    cfg = get_config()
    now = _dt.now(timezone.utc)
    start = now - _td(days=cfg.app.window_days)
    data = load_team_data(session, team, start, now)
    signals = compute_signals(session, data)
    period = f"{start.date().isoformat()}/{now.date().isoformat()}"
    count = 0
    for sig in signals:
        if sig.get("status") != "red":
            continue
        name = SIGNAL_META.get(sig["key"], (sig["key"],))[0]
        count += emit_trend_alarm(
            session,
            team_id=team.id,
            team_name=team.name,
            metric_key=f"signal:{sig['key']}",
            metric_name=name,
            period=period,
        )
    return count


def list_for_user(session: Session, user_id: int, limit: int = 50) -> list[dict]:
    rows = session.scalars(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "severity": r.severity,
            "title": r.title,
            "body": r.body,
            "link": r.link,
            "is_read": r.is_read,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def unread_count(session: Session, user_id: int) -> int:
    return session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
    ) or 0


def mark_read(session: Session, user_id: int, notif_id: int | None = None) -> int:
    """notif_id verilirse tek bildirimi, yoksa tümünü okundu yapar. Sayı döner."""
    q = select(Notification).where(
        Notification.user_id == user_id, Notification.is_read.is_(False)
    )
    if notif_id is not None:
        q = q.where(Notification.id == notif_id)
    rows = session.scalars(q).all()
    for r in rows:
        r.is_read = True
    return len(rows)
