"""Metrik motoru.

Her metrik şu üçlüyü üretir: (değer, data_completeness, source_layer).
- Değer HİÇBİR ZAMAN uydurulmaz: gerekli alanlar yoksa value=None döner,
  dashboard "veri yetersiz" gösterir.
- completeness: metriğin dayandığı aday kayıtların ne kadarında gerekli
  alanlar vardı (0..1). Eksik veri CEZALANDIRILMAZ, RAPORLANIR.
- source_layer: hangi veri katmanından üretildi (git | jira_status |
  pr_merge ...). Config'teki source/fallback zinciri burada işler.

Metrikler endüstri standardıdır (DORA + flow): cycle time, PR review time,
review latency, deployment frequency, change failure rate, WIP, rework.
Hepsi TAKIM seviyesinde sağlık göstergesidir; bireysel çıktı sayacı değildir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Config
from app.models import (
    Commit,
    MetricResult,
    PullRequest,
    Repo,
    Task,
    Team,
    TeamMembership,
)

DONE_STATUSES = {"done", "closed", "resolved", "bitti", "tamamlandı"}
IN_PROGRESS_STATUSES = {"in progress", "doing", "yapılıyor", "in review", "review"}
# WIP'e sayılmayan bekleme statüleri: backlog'daki iş "devam eden" değildir
BACKLOG_STATUSES = {"to do", "todo", "backlog", "open", "yapılacak"}
FIX_HINTS = ("fix", "hotfix", "bugfix", "düzeltme")
# CFR için daha dar sinyal: her "fix" commit'i deploy hatası değildir;
# acil müdahale dilini arıyoruz (hotfix/revert)
HOTFIX_HINTS = ("hotfix", "revert")


def as_utc(dt: datetime | None) -> datetime | None:
    """Naive tarihleri UTC varsayar — SQLite/Postgres farkını tek yerde çözer."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _is_done(status: str | None) -> bool:
    return (status or "").strip().lower() in DONE_STATUSES


def leave_overlap_days(start_ts: datetime, end_ts: datetime, leave_days: set[date]) -> int:
    """[start_ts, end_ts] aralığına düşen onaylı izin takvim günü sayısı.
    Boş küme = 0 (eski davranış). Faz 5 metrik entegrasyonunun çekirdeği."""
    if not leave_days:
        return 0
    d, last = start_ts.date(), end_ts.date()
    count = 0
    while d <= last:
        if d in leave_days:
            count += 1
        d += timedelta(days=1)
    return count


def _duration_days(start_ts: datetime, end_ts: datetime, leave_days: set[date]) -> float:
    """Süre (gün), onaylı izin günleri düşülerek. İzin ortada kalan bir işin
    cycle time'ını şişirmez — izin bağlamdır, gecikme değildir (spec Faz 5)."""
    raw = (end_ts - start_ts).total_seconds() / 86400
    return max(0.0, raw - leave_overlap_days(start_ts, end_ts, leave_days))


@dataclass
class MetricOutcome:
    value: float | None
    completeness: float
    source_layer: str | None
    sample: int  # değerin dayandığı kayıt sayısı (şeffaflık için)


ZERO = MetricOutcome(value=None, completeness=0.0, source_layer=None, sample=0)


@dataclass
class TeamData:
    """Bir takımın penceresi içindeki ham verisi — metrik fonksiyonlarına girdi."""

    team: Team
    member_count: int
    commits: list[Commit]        # pencere içi
    prs: list[PullRequest]       # pencereye dokunan (açılış ya da merge içeride)
    all_prs_count: int           # completeness paydası için tüm PR sayısı
    tasks: list[Task]            # takımın tüm task'ları (WIP için hepsi gerekir)
    start: datetime
    end: datetime
    # Faz 5: bu kapsamdaki ONAYLI izin takvim günleri. Takım kapsamında boş
    # bırakılır (izin bireysel bağlamdır); bireysel görünümde doldurulur ve
    # cycle time'dan düşülür. Boşken tüm hesaplar birebir eski davranışta kalır.
    leave_days: set[date] = field(default_factory=set)


def load_team_data(session: Session, team: Team, start: datetime, end: datetime) -> TeamData:
    repo_ids = [r.id for r in session.scalars(select(Repo).where(Repo.team_id == team.id))]
    commits = [
        c for c in session.scalars(select(Commit).where(Commit.repo_id.in_(repo_ids)))
        if (ts := as_utc(c.committed_at)) is None or start <= ts <= end
    ] if repo_ids else []
    all_prs = list(
        session.scalars(
            select(PullRequest)
            .where(PullRequest.repo_id.in_(repo_ids))
            .options(selectinload(PullRequest.reviews))
        )
    ) if repo_ids else []
    prs = [
        p for p in all_prs
        if ((o := as_utc(p.opened_at)) and start <= o <= end)
        or ((m := as_utc(p.merged_at)) and start <= m <= end)
        or (p.opened_at is None)  # tarihi eksik PR'lar da completeness'e sayılır
    ]
    tasks = list(
        session.scalars(
            select(Task).where(Task.team_id == team.id).options(selectinload(Task.transitions))
        )
    )
    members = session.scalars(
        select(TeamMembership).where(TeamMembership.team_id == team.id)
    ).all()
    return TeamData(
        team=team,
        member_count=max(1, sum(1 for m in members if m.role != "manager")),
        commits=commits,
        prs=prs,
        all_prs_count=len(all_prs),
        tasks=tasks,
        start=start,
        end=end,
    )


# --- Tekil metrik fonksiyonları ------------------------------------------------

def _task_done_at(task: Task) -> datetime | None:
    for tr in sorted(task.transitions, key=lambda t: as_utc(t.changed_at) or datetime.min.replace(tzinfo=timezone.utc)):
        if _is_done(tr.to_status):
            return as_utc(tr.changed_at)
    return None


def _task_started_at(task: Task) -> datetime | None:
    for tr in sorted(task.transitions, key=lambda t: as_utc(t.changed_at) or datetime.min.replace(tzinfo=timezone.utc)):
        if (tr.to_status or "").strip().lower() in IN_PROGRESS_STATUSES:
            return as_utc(tr.changed_at)
    return as_utc(task.created_at)


def cycle_time(data: TeamData, cfg: Config) -> MetricOutcome:
    """Task açıldı → bitti (gün). source: jira_status (Katman 1 damgaları),
    fallback: pr_merge (Katman 0). Zincirde veri bulunamazsa 'veri yetersiz'."""
    mc = cfg.metric("cycle_time")
    chain = [mc.source or "jira_status"]
    if mc.fallback and mc.fallback not in chain:
        chain.append(mc.fallback)

    for layer in chain:
        if layer in ("jira_status", "jira_dates"):
            done_in_window = [
                t for t in data.tasks
                if (d := _task_done_at(t)) is not None and data.start <= d <= data.end
            ]
            if not done_in_window:
                continue  # bu katmanda veri yok → fallback'e düş
            durations = []
            for t in done_in_window:
                start_ts = _task_started_at(t) if layer == "jira_status" else as_utc(t.created_at)
                end_ts = _task_done_at(t)
                if start_ts and end_ts and end_ts >= start_ts:
                    durations.append(_duration_days(start_ts, end_ts, data.leave_days))
            if durations:
                return MetricOutcome(
                    value=sum(durations) / len(durations),
                    completeness=len(durations) / len(done_in_window),
                    source_layer=layer,
                    sample=len(durations),
                )
        elif layer == "pr_merge":
            merged = [
                p for p in data.prs
                if (m := as_utc(p.merged_at)) and data.start <= m <= data.end
            ]
            durations = [
                _duration_days(as_utc(p.opened_at), as_utc(p.merged_at), data.leave_days)
                for p in merged
                if p.opened_at and as_utc(p.merged_at) >= as_utc(p.opened_at)
            ]
            if durations:
                return MetricOutcome(
                    value=sum(durations) / len(durations),
                    completeness=len(durations) / max(1, len(merged)),
                    source_layer="pr_merge",
                    sample=len(durations),
                )
    return ZERO


def pr_review_time(data: TeamData, cfg: Config) -> MetricOutcome:
    """PR açılış → merge (gün). Katman 0 — elle veri gerekmez."""
    merged = [p for p in data.prs if (m := as_utc(p.merged_at)) and data.start <= m <= data.end]
    if not merged:
        return ZERO
    durations = [
        (as_utc(p.merged_at) - as_utc(p.opened_at)).total_seconds() / 86400
        for p in merged
        if p.opened_at and as_utc(p.merged_at) >= as_utc(p.opened_at)
    ]
    if not durations:
        return MetricOutcome(None, 0.0, "git", 0)
    return MetricOutcome(
        value=sum(durations) / len(durations),
        completeness=len(durations) / len(merged),
        source_layer="git",
        sample=len(durations),
    )


def review_latency(data: TeamData, cfg: Config) -> MetricOutcome:
    """PR açıldı → ilk review (gün). Hiç review almayan PR'lar burada değil,
    process hygiene'de raporlanır (yokluk sinyaldir, gecikme değildir)."""
    opened = [p for p in data.prs if (o := as_utc(p.opened_at)) and data.start <= o <= data.end]
    dated = len(opened)
    total = len([p for p in data.prs])
    if not opened:
        return ZERO
    latencies = [
        (as_utc(p.first_review_at) - as_utc(p.opened_at)).total_seconds() / 86400
        for p in opened
        if p.first_review_at and as_utc(p.first_review_at) >= as_utc(p.opened_at)
    ]
    if not latencies:
        return MetricOutcome(None, dated / max(1, total), "git", 0)
    return MetricOutcome(
        value=sum(latencies) / len(latencies),
        completeness=dated / max(1, total),
        source_layer="git",
        sample=len(latencies),
    )


def deployment_frequency(data: TeamData, cfg: Config) -> MetricOutcome:
    """Haftalık teslim sayısı. deploy_signal=merge: main'e merge proxy'si
    (merge commit ya da merge edilmiş PR)."""
    deploys = _deploy_events(data)
    weeks = max(1.0, (data.end - data.start).total_seconds() / (7 * 86400))
    if not deploys:
        # Hiç deploy görünmüyorsa bu "0 teslim"dir, eksik veri değildir —
        # ama commit verisi de hiç yoksa veri yetersizdir.
        if not data.commits and not data.prs:
            return ZERO
        return MetricOutcome(0.0, 1.0, "git", 0)
    return MetricOutcome(len(deploys) / weeks, 1.0, "git", len(deploys))


def _deploy_events(data: TeamData) -> list[datetime]:
    events = [
        m for p in data.prs if (m := as_utc(p.merged_at)) and data.start <= m <= data.end
    ]
    if not events:
        events = [
            ts for c in data.commits
            if (c.message or "").lower().startswith("merge")
            and (ts := as_utc(c.committed_at)) and data.start <= ts <= data.end
        ]
    return sorted(events)


def change_failure_rate(data: TeamData, cfg: Config) -> MetricOutcome:
    """Deploy sonrası N gün içinde hotfix gelme oranı (DORA, TAKIM seviyesi).
    Fix commit'i asla kişi sinyali değildir — burada yalnızca deploy
    kalitesinin takım göstergesi olarak kullanılır."""
    mc = cfg.metric("change_failure_rate")
    window = timedelta(days=mc.extra_int("hotfix_window_days", 3))
    deploys = _deploy_events(data)
    if not deploys:
        return ZERO
    fix_times = [
        ts for c in data.commits
        if any(h in (c.message or "").lower() for h in HOTFIX_HINTS)
        and (ts := as_utc(c.committed_at))
    ]
    failures = sum(1 for d in deploys if any(d < f <= d + window for f in fix_times))
    return MetricOutcome(failures / len(deploys), 1.0, "git", len(deploys))


def wip(data: TeamData, cfg: Config) -> MetricOutcome:
    """Kişi başı açık iş — tıkanma göstergesi. source: task status;
    fallback: açık PR sayısı (Katman 0)."""
    with_status = [t for t in data.tasks if t.status is not None]
    if with_status:
        open_tasks = [
            t for t in with_status
            if not _is_done(t.status)
            and (t.status or "").strip().lower() not in BACKLOG_STATUSES
        ]
        return MetricOutcome(
            value=len(open_tasks) / data.member_count,
            completeness=len(with_status) / max(1, len(data.tasks)),
            source_layer="task_status",
            sample=len(open_tasks),
        )
    open_prs = [p for p in data.prs if p.merged_at is None and p.closed_at is None]
    if data.all_prs_count:
        return MetricOutcome(
            value=len(open_prs) / data.member_count,
            completeness=1.0,
            source_layer="pr_open",
            sample=len(open_prs),
        )
    return ZERO


def rework_rate(data: TeamData, cfg: Config) -> MetricOutcome:
    """Aynı dosyaya X gün içinde tekrar dokunma oranı — TAKIM seviyesinde
    kalite sinyali (Katman 0, otomatik)."""
    mc = cfg.metric("rework")
    window = timedelta(days=mc.extra_int("window_days", 21))
    dated = [
        c for c in data.commits
        if c.committed_at is not None and c.changed_files
    ]
    if not dated:
        return MetricOutcome(None, 0.0, "git", 0) if data.commits else ZERO
    dated.sort(key=lambda c: as_utc(c.committed_at))
    last_touch: dict[str, datetime] = {}
    touches = reworks = 0
    for c in dated:
        ts = as_utc(c.committed_at)
        for f in c.changed_files or []:
            touches += 1
            prev = last_touch.get(f)
            if prev is not None and ts - prev <= window:
                reworks += 1
            last_touch[f] = ts
    if touches == 0:
        return MetricOutcome(None, 0.0, "git", 0)
    return MetricOutcome(
        value=reworks / touches,
        completeness=len(dated) / max(1, len(data.commits)),
        source_layer="git",
        sample=touches,
    )


def estimate_accuracy(data: TeamData, cfg: Config) -> MetricOutcome:
    """Katman 2 — yalnızca estimate GİRİLMİŞSE hesaplanır. Yoksa metrik
    gizlenir; asla varsayılan uydurulmaz (İlke B kuralı)."""
    done = [
        t for t in data.tasks
        if (d := _task_done_at(t)) is not None and data.start <= d <= data.end
    ]
    if not done:
        return ZERO
    ratios = []
    for t in done:
        if t.estimate_hours is None or t.estimate_hours <= 0:
            continue
        start_ts, end_ts = _task_started_at(t), _task_done_at(t)
        if start_ts and end_ts and end_ts > start_ts:
            actual_h = (end_ts - start_ts).total_seconds() / 3600
            ratios.append(min(actual_h / t.estimate_hours, 10.0))  # uç değer kırp
    completeness = len(ratios) / len(done)
    if not ratios:
        return MetricOutcome(None, completeness, "manual", 0)
    return MetricOutcome(sum(ratios) / len(ratios), completeness, "manual", len(ratios))


def process_hygiene(data: TeamData, cfg: Config) -> MetricOutcome:
    """Eksik verinin kendisi metriktir (İlke A). Bileşenler:
    estimate doluluk, status güncelleme, PR review'lanma, commit kimliği.
    Yüksek = süreç izlenebilir; düşük = süreç körlüğü var, planlama iyileştir."""
    components: list[float] = []
    if data.tasks:
        components.append(
            sum(1 for t in data.tasks if t.estimate_hours is not None) / len(data.tasks)
        )
        components.append(
            sum(1 for t in data.tasks if t.transitions) / len(data.tasks)
        )
    if data.prs:
        components.append(
            sum(1 for p in data.prs if p.first_review_at is not None or p.reviews) / len(data.prs)
        )
    if data.commits:
        components.append(
            sum(1 for c in data.commits if c.author_id is not None) / len(data.commits)
        )
    if not components:
        return ZERO
    return MetricOutcome(
        value=sum(components) / len(components),
        completeness=1.0,  # meta-metrik: kendisi zaten eksikliği ölçer
        source_layer="composite",
        sample=len(components),
    )


# Metrik kayıt tablosu: config anahtarı → fonksiyon
METRIC_FUNCS = {
    "cycle_time": cycle_time,
    "pr_review_time": pr_review_time,
    "review_latency": review_latency,
    "deployment_frequency": deployment_frequency,
    "change_failure_rate": change_failure_rate,
    "wip": wip,
    "rework": rework_rate,
    "estimate_accuracy": estimate_accuracy,
    "process_hygiene": process_hygiene,
}

# Zaman serisi üretilen metrikler (WIP anlık olduğundan seriye girmez)
SERIES_METRICS = ["cycle_time", "pr_review_time", "review_latency",
                  "deployment_frequency", "rework"]


def _period_key(start: datetime, end: datetime) -> str:
    return f"{start:%Y-%m-%d}/{end:%Y-%m-%d}"


def _upsert(session: Session, scope: str, scope_id: int, metric_key: str,
            period: str, outcome: MetricOutcome, now: datetime) -> None:
    row = session.scalar(
        select(MetricResult).where(
            MetricResult.scope == scope,
            MetricResult.scope_id == scope_id,
            MetricResult.metric_key == metric_key,
            MetricResult.period == period,
        )
    )
    if row is None:
        row = MetricResult(scope=scope, scope_id=scope_id, metric_key=metric_key, period=period)
        session.add(row)
    row.value = outcome.value
    row.data_completeness = outcome.completeness
    row.source_layer = outcome.source_layer
    row.computed_at = now


def compute_all(session: Session, cfg: Config) -> int:
    """Tüm takımlar için pencere metriği + haftalık seriyi hesaplar ve saklar."""
    now = datetime.now(timezone.utc)
    end = now
    start = end - timedelta(days=cfg.app.window_days)
    written = 0

    for team in session.scalars(select(Team)):
        data = load_team_data(session, team, start, end)
        for key, func in METRIC_FUNCS.items():
            if not cfg.metric(key).enabled:
                continue  # config kapattıysa hesaplanmaz, saklanmaz
            outcome = func(data, cfg)
            _upsert(session, "team", team.id, key, _period_key(start, end), outcome, now)
            written += 1

        # Haftalık kovalar (trend grafikleri için)
        bucket = timedelta(days=cfg.app.bucket_days)
        b_start = start
        while b_start < end:
            b_end = min(b_start + bucket, end)
            b_data = load_team_data(session, team, b_start, b_end)
            for key in SERIES_METRICS:
                if not cfg.metric(key).enabled:
                    continue
                outcome = METRIC_FUNCS[key](b_data, cfg)
                _upsert(session, "team", team.id, key, _period_key(b_start, b_end), outcome, now)
                written += 1
            b_start = b_end

    session.commit()
    return written
