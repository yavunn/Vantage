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
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Config, get_config
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
# Yalnızca VARSAYILAN. Gerçek eşleme config'ten gelir (sources.tasks.status_mapping)
# ve resolve_statuses() ile birleştirilir — kaynak kolon adları serbest metindir.
DEFAULT_STATUSES = {
    "done": DONE_STATUSES,
    "in_progress": IN_PROGRESS_STATUSES,
    "backlog": BACKLOG_STATUSES,
}

# Kaynak yeteneği: alan KAYNAKTA YOKSA doldurulmaması süreç hijyeni eksikliği
# değildir. Bu bir ayar değil, aracın gerçeği (Trello'da estimate alanı yoktur).
SOURCES_WITHOUT_ESTIMATE = {"trello"}

FIX_HINTS = ("fix", "hotfix", "bugfix", "düzeltme")
# CFR için daha dar sinyal: her "fix" commit'i deploy hatası değildir;
# acil müdahale dilini arıyoruz (hotfix/revert)
HOTFIX_HINTS = ("hotfix", "revert")


def as_utc(dt: datetime | None) -> datetime | None:
    """Naive tarihleri UTC varsayar — SQLite/Postgres farkını tek yerde çözer."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def resolve_statuses(cfg: Config | None = None) -> dict[str, set[str]]:
    """Varsayılan statü sözlüğü + config beyanı → kategori→adlar eşlemesi.

    Config'te beyan edilen ad ÖNCE tüm kategorilerden düşülür, sonra beyan
    edildiği kategoriye eklenir: böylece varsayılanla çakışan bir ad (ör.
    'open') sessizce iki kategoride birden kalmaz, beyan kazanır."""
    out = {k: set(v) for k, v in DEFAULT_STATUSES.items()}
    mapping = getattr(getattr(cfg, "sources", None), "tasks", None)
    mapping = getattr(mapping, "status_mapping", None)
    if mapping is None:
        return out
    declared: dict[str, str] = {}
    for category in out:
        for name in getattr(mapping, category, None) or []:
            if name and name.strip():
                declared[name.strip().lower()] = category
    for name, category in declared.items():
        for names in out.values():
            names.discard(name)
        out[category].add(name)
    return out


def _in(status: str | None, names: set[str]) -> bool:
    return (status or "").strip().lower() in names


def _is_done(status: str | None, statuses: dict[str, set[str]] | None = None) -> bool:
    return _in(status, (statuses or DEFAULT_STATUSES)["done"])


@dataclass
class MetricOutcome:
    value: float | None
    completeness: float
    source_layer: str | None
    sample: int  # değerin dayandığı kayıt sayısı (şeffaflık için)
    stats: dict | None = None  # süre metriklerinde {median, p90, min, max}


ZERO = MetricOutcome(value=None, completeness=0.0, source_layer=None, sample=0)


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Doğrusal enterpolasyonlu yüzdelik (q: 0..1). Küçük örneklemde de tutarlı."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _distribution(values: list[float]) -> dict | None:
    """Ortalama yanıltıcı olabilir: medyan + p90 + uç değerleri birlikte döndür.
    Ortalama ATILMAZ, çağıran ayrıca value olarak taşır; bu yalnızca yanına eklenir."""
    if not values:
        return None
    s = sorted(values)
    return {
        "median": _percentile(s, 0.5),
        "p90": _percentile(s, 0.9),
        "min": s[0],
        "max": s[-1],
    }


def _duration_outcome(
    durations: list[float], denom: int, source_layer: str
) -> MetricOutcome:
    """Süre metrikleri için ortak çıktı: ortalama + medyan/p90 dağılımı + örneklem.
    denom: completeness paydası (aday kayıt sayısı). Boşsa 'veri yetersiz'."""
    if not durations:
        return MetricOutcome(None, 0.0, source_layer, 0)
    return MetricOutcome(
        value=sum(durations) / len(durations),
        completeness=len(durations) / max(1, denom),
        source_layer=source_layer,
        sample=len(durations),
        stats=_distribution(durations),
    )


@dataclass
class TeamData:
    """Bir takımın penceresi içindeki ham verisi — metrik fonksiyonlarına girdi."""

    team: Team
    member_count: int            # GERÇEK üye sayısı; 0 olabilir → kişi-başı metrik yok
    commits: list[Commit]        # pencere içi
    prs: list[PullRequest]       # pencereye dokunan (açılış ya da merge içeride)
    all_prs_count: int           # completeness paydası için tüm PR sayısı
    tasks: list[Task]            # takımın tüm task'ları (WIP için hepsi gerekir)
    start: datetime
    end: datetime
    # Config'ten çözümlenmiş statü eşlemesi (kategori → adlar). Metrik
    # fonksiyonları gömülü sabit yerine bunu kullanır.
    statuses: dict[str, set[str]] = field(default_factory=lambda: {
        k: set(v) for k, v in DEFAULT_STATUSES.items()
    })


def load_team_data(session: Session, team: Team, start: datetime, end: datetime,
                   cfg: Config | None = None) -> TeamData:
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
        # GERÇEK sayı: 0 üyeli takımda "kişi başı" metrik uydurmak yerine
        # metrik "veri yetersiz" olmalı (bkz. wip).
        member_count=sum(1 for m in members if m.role != "manager"),
        commits=commits,
        prs=prs,
        all_prs_count=len(all_prs),
        tasks=tasks,
        start=start,
        end=end,
        statuses=resolve_statuses(cfg if cfg is not None else get_config()),
    )


# --- Tekil metrik fonksiyonları ------------------------------------------------

def _task_done_at(task: Task, statuses: dict[str, set[str]] | None = None) -> datetime | None:
    for tr in sorted(task.transitions, key=lambda t: as_utc(t.changed_at) or datetime.min.replace(tzinfo=timezone.utc)):
        if _is_done(tr.to_status, statuses):
            return as_utc(tr.changed_at)
    return None


def _task_started_at(task: Task, statuses: dict[str, set[str]] | None = None) -> datetime | None:
    names = (statuses or DEFAULT_STATUSES)["in_progress"]
    for tr in sorted(task.transitions, key=lambda t: as_utc(t.changed_at) or datetime.min.replace(tzinfo=timezone.utc)):
        if _in(tr.to_status, names):
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
                if (d := _task_done_at(t, data.statuses)) is not None and data.start <= d <= data.end
            ]
            if not done_in_window:
                continue  # bu katmanda veri yok → fallback'e düş
            durations = []
            for t in done_in_window:
                start_ts = _task_started_at(t, data.statuses) if layer == "jira_status" else as_utc(t.created_at)
                end_ts = _task_done_at(t, data.statuses)
                if start_ts and end_ts and end_ts >= start_ts:
                    durations.append((end_ts - start_ts).total_seconds() / 86400)
            if durations:
                return _duration_outcome(durations, len(done_in_window), layer)
        elif layer == "pr_merge":
            merged = [
                p for p in data.prs
                if (m := as_utc(p.merged_at)) and data.start <= m <= data.end
            ]
            durations = [
                (as_utc(p.merged_at) - as_utc(p.opened_at)).total_seconds() / 86400
                for p in merged
                if p.opened_at and as_utc(p.merged_at) >= as_utc(p.opened_at)
            ]
            if durations:
                return _duration_outcome(durations, len(merged), "pr_merge")
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
    return _duration_outcome(durations, len(merged), "git")


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
        stats=_distribution(latencies),
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
    fallback: açık PR sayısı (Katman 0).

    Takımın üyesi yoksa KİŞİ BAŞI bir sayı üretilemez: paydayı 1'e yuvarlamak
    "10 iş / hayali 1 kişi" gibi yanlış bir kırmızı üretirdi. Değer uydurmak
    yerine 'veri yetersiz' döner (İlke A)."""
    if data.member_count <= 0:
        return ZERO
    with_status = [t for t in data.tasks if t.status is not None]
    if with_status:
        # Backlog VE done dışındakiler akıştaki iştir. Kategoriler config'ten
        # gelir; kaynak kolon adları ("Araştırma Konuları") gömülü listede yok.
        open_tasks = [
            t for t in with_status
            if not _is_done(t.status, data.statuses)
            and not _in(t.status, data.statuses["backlog"])
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
        if (d := _task_done_at(t, data.statuses)) is not None and data.start <= d <= data.end
    ]
    if not done:
        return ZERO
    ratios = []
    for t in done:
        if t.estimate_hours is None or t.estimate_hours <= 0:
            continue
        start_ts, end_ts = _task_started_at(t, data.statuses), _task_done_at(t, data.statuses)
        if start_ts and end_ts and end_ts > start_ts:
            actual_h = (end_ts - start_ts).total_seconds() / 3600
            ratios.append(min(actual_h / t.estimate_hours, 10.0))  # uç değer kırp
    completeness = len(ratios) / len(done)
    if not ratios:
        return MetricOutcome(None, completeness, "manual", 0)
    return MetricOutcome(sum(ratios) / len(ratios), completeness, "manual", len(ratios))


INCIDENT_TYPES = {"incident", "outage", "olay", "kesinti"}
INCIDENT_HINTS = ("incident", "outage", "sev1", "sev2", "p1", "p2", "olay", "kesinti")


def _revert_target_sha(message: str | None) -> str | None:
    """'Revert "..." This reverts commit <sha>.' örüntüsünden hedef sha'yı çıkarır.
    Git'in standart revert mesaj biçimidir; bulunamazsa None."""
    if not message:
        return None
    low = message.lower()
    if "reverts commit" in low:
        after = low.split("reverts commit", 1)[1].strip()
        token = after.split()[0].strip(".") if after.split() else ""
        if len(token) >= 7 and all(c in "0123456789abcdef" for c in token):
            return token
    return None


def mttr(data: TeamData, cfg: Config) -> MetricOutcome:
    """4. DORA metriği — Toparlanma Süresi (MTTR): incident başladıktan normale
    dönene kadar (saat). TAKIM sağlık göstergesi; asla kişi sinyali değildir.

    İki aday veri katmanı (config: source):
      - jira_incident: type/başlık 'incident' olan task'ın açılış→bitiş süresi.
      - git_revert: bir revert commit'i ile geri aldığı orijinal commit
        arasındaki süre (Git standart 'This reverts commit <sha>' mesajından).

    Hiçbir katmanda veri yoksa value=None döner ('veri yetersiz'). Uydurma YOK.
    Gerçek incident yönetimi için önerilen kaynak: PagerDuty/Opsgenie olay
    başlangıç+çözüm damgaları ya da Jira 'incident' iş tipi (created→resolved).
    """
    mc = cfg.metric("mttr")
    chain = [mc.source or "jira_incident"]
    if mc.fallback and mc.fallback not in chain:
        chain.append(mc.fallback)

    for layer in chain:
        if layer == "jira_incident":
            incidents = [
                t for t in data.tasks
                if ((t.type or "").strip().lower() in INCIDENT_TYPES
                    or any(h in (t.title or "").lower() for h in INCIDENT_HINTS))
                and (d := _task_done_at(t, data.statuses)) is not None and data.start <= d <= data.end
            ]
            hours = []
            for t in incidents:
                start_ts = as_utc(t.created_at)
                end_ts = _task_done_at(t, data.statuses)
                if start_ts and end_ts and end_ts >= start_ts:
                    hours.append((end_ts - start_ts).total_seconds() / 3600)
            if hours:
                out = _duration_outcome(hours, len(incidents), "jira_incident")
                return out
        elif layer == "git_revert":
            by_sha = {c.sha[:12]: c for c in data.commits if c.sha}
            hours = []
            considered = 0
            for c in data.commits:
                target = _revert_target_sha(c.message)
                if target is None:
                    continue
                considered += 1
                orig = by_sha.get(target[:12])
                rev_ts, orig_ts = as_utc(c.committed_at), as_utc(orig.committed_at) if orig else None
                if orig_ts and rev_ts and rev_ts >= orig_ts:
                    hours.append((rev_ts - orig_ts).total_seconds() / 3600)
            if hours:
                return _duration_outcome(hours, max(considered, len(hours)), "git_revert")
    return ZERO


def process_hygiene(data: TeamData, cfg: Config) -> MetricOutcome:
    """Eksik verinin kendisi metriktir (İlke A). Bileşenler:
    estimate doluluk, status güncelleme, PR review'lanma, commit kimliği.
    Yüksek = süreç izlenebilir; düşük = süreç körlüğü var, planlama iyileştir."""
    components: list[float] = []
    if data.tasks:
        # Estimate bileşeni YALNIZCA alanı olan kaynaklar için sayılır. Trello'da
        # estimate alanı yoktur; onu "doldurulmamış" saymak takımı var olmayan bir
        # eksiklikten cezalandırır ve metriği yapısal tavana çakar (İlke B:
        # alan yoksa metrik gizlenir, varsayılan uydurulmaz).
        estimable = [
            t for t in data.tasks
            if (t.source or "").strip().lower() not in SOURCES_WITHOUT_ESTIMATE
        ]
        if estimable:
            components.append(
                sum(1 for t in estimable if t.estimate_hours is not None) / len(estimable)
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
    "mttr": mttr,
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
    row.sample_size = outcome.sample
    row.stats = outcome.stats
    row.computed_at = now


def compute_all(session: Session, cfg: Config) -> int:
    """Tüm takımlar için pencere metriği + haftalık seriyi hesaplar ve saklar."""
    now = datetime.now(timezone.utc)
    end = now
    start = end - timedelta(days=cfg.app.window_days)
    written = 0

    # Team-scope metrikler her çalıştırmada tümüyle yeniden üretilir. Period
    # anahtarı tarihle kaydığından eski satırlar upsert'e uğramaz, birikir ve
    # trendi/özeti kirletir. Bu yüzden önce temizlenir (developer/project scope
    # bu fonksiyonda üretilmediğinden dokunulmaz).
    from app.models import MetricResult as _MR
    session.query(_MR).filter(_MR.scope == "team").delete(synchronize_session=False)

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
