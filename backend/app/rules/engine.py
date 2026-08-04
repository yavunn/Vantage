"""Kural motoru (İlke D): eşik aşılınca insan-dostu öneri üretir.

Ürünü "dashboard"dan "danışman"a çeviren katman. Dil her zaman destek
dilidir: sorun KİŞİ değil SÜREÇTİR; öneri yardım çerçevesindedir.
Eşikler config'ten gelir; her kural tek tek kapatılabilir.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Config
from app.metrics.engine import (
    FIX_HINTS,
    HOTFIX_HINTS,
    SOURCES_WITHOUT_ESTIMATE,
    TeamData,
    _deploy_events,
    as_utc,
    load_team_data,
    review_latency,
    wip,
)
from app.models import Recommendation, Team


@dataclass
class RuleFinding:
    rule_key: str
    message: str
    severity: str  # info | warning | attention


def rule_review_bottleneck(data: TeamData, cfg: Config) -> RuleFinding | None:
    """Tespit: PR'lar ortalama X günden uzun review bekliyor.
    Öneri: review WIP limiti / reviewer rotasyonu."""
    rc = cfg.rule("review_bottleneck")
    threshold = rc.extra_num("avg_review_wait_days", 4)
    outcome = review_latency(data, cfg)
    if outcome.value is not None and outcome.value >= threshold:
        return RuleFinding(
            "review_bottleneck",
            f"PR'lar ilk review için ortalama {outcome.value:.1f} gün bekliyor "
            f"(eşik: {threshold:g} gün). Takım review kapasitesinde sıkışıyor "
            "olabilir — bir review WIP limiti ya da reviewer rotasyonu denemek "
            "bekleme süresini kısaltabilir.",
            "attention",
        )
    return None


def rule_hotspot_files(data: TeamData, cfg: Config) -> RuleFinding | None:
    """Tespit: aynı dosyalar sürekli fix alıyor.
    Öneri: modül refactor / test coverage adayı."""
    rc = cfg.rule("hotspot_files")
    min_touches = int(rc.extra_num("min_fix_touches", 3))
    window = timedelta(days=rc.extra_num("window_days", 30))
    cutoff = data.end - window
    counter: Counter[str] = Counter()
    for c in data.commits:
        ts = as_utc(c.committed_at)
        if ts is None or ts < cutoff:
            continue
        if any(h in (c.message or "").lower() for h in FIX_HINTS):
            for f in c.changed_files or []:
                counter[f] += 1
    hotspots = [(f, n) for f, n in counter.most_common(5) if n >= min_touches]
    if hotspots:
        listing = ", ".join(f"{f} ({n} fix)" for f, n in hotspots[:3])
        return RuleFinding(
            "hotspot_files",
            f"Son {window.days} günde aynı dosyalar tekrar tekrar düzeltme aldı: "
            f"{listing}. Bu modüller refactor ve test coverage yatırımı için "
            "güçlü adaylar — buraya ayrılacak zaman, gelecekteki fix yükünü azaltır.",
            "warning",
        )
    return None


def rule_wip_overload(data: TeamData, cfg: Config) -> RuleFinding | None:
    """Tespit: kişi başı açık iş çok yüksek — çok iş başlatılıyor az bitiyor.
    Öneri: WIP limiti."""
    rc = cfg.rule("wip_overload")
    threshold = rc.extra_num("wip_per_dev", 5)
    outcome = wip(data, cfg)
    if outcome.value is not None and outcome.value >= threshold:
        return RuleFinding(
            "wip_overload",
            f"Kişi başına ortalama {outcome.value:.1f} açık iş görünüyor "
            f"(eşik: {threshold:g}). Çok iş başlatılıp az bitiriliyor olabilir — "
            "takımca bir WIP limiti belirlemek akışı hızlandırabilir.",
            "attention",
        )
    return None


def rule_low_process_hygiene(data: TeamData, cfg: Config) -> RuleFinding | None:
    """Tespit: task'ların büyük kısmında estimate yok.
    Öneri: süreç hijyeni düşük — planlama pratiğini iyileştir.
    (Eksik veri ceza değildir; görünürlük kaybı olarak raporlanır.)"""
    rc = cfg.rule("low_process_hygiene")
    threshold = rc.extra_num("missing_estimate_pct", 70)
    # Kaynağında estimate ALANI OLMAYAN task'lar paydaya girmez (Trello'da böyle
    # bir alan yoktur). Metrik motoru bunu zaten dışlıyordu (SOURCES_WITHOUT_ESTIMATE)
    # ama kural dışlamıyordu: Trello kullanan takım "%100'ünde estimate yok"
    # önerisini KAPATAMIYORDU — sistem çözümsüz bir iş öneriyordu.
    estimable = [
        t for t in data.tasks
        if (t.source or "").strip().lower() not in SOURCES_WITHOUT_ESTIMATE
    ]
    if not estimable:
        return None
    missing = sum(1 for t in estimable if t.estimate_hours is None)
    pct = 100 * missing / len(estimable)
    if pct >= threshold:
        return RuleFinding(
            "low_process_hygiene",
            f"Task'ların %{pct:.0f}'inde estimate girilmemiş. Bu bir kusur "
            "değil, görünürlük kaybı: planlama sinyalleri eksik kalıyor ve bazı "
            "metrikler hesaplanamıyor. Kısa bir planlama rutini (örn. haftalık "
            "estimate turu) süreci görünür kılabilir.",
            "info",
        )
    return None


def rule_risky_deploy_window(data: TeamData, cfg: Config) -> RuleFinding | None:
    """Tespit: cuma akşamı deploy + hafta sonu fix örüntüsü.
    Öneri: riskli deploy penceresi, freeze düşünülebilir."""
    # PR merge'lerine EK olarak merge commit'leri de deploy sayılır: cuma
    # akşamı doğrudan main'e atılan release merge'i PR listesinde görünmez.
    deploys = set(_deploy_events(data))
    deploys.update(
        ts for c in data.commits
        if (c.message or "").lower().startswith("merge")
        and (ts := as_utc(c.committed_at))
    )
    # Hafta sonu ACİL müdahale dili aranır (hotfix/revert): sıradan bir
    # "fix" commit'i hafta sonuna denk geldi diye pencere riskli sayılmaz.
    fix_times = [
        ts for c in data.commits
        if any(h in (c.message or "").lower() for h in HOTFIX_HINTS)
        and (ts := as_utc(c.committed_at))
    ]
    risky = 0
    for d in deploys:
        if d.weekday() == 4 and d.hour >= 15:  # cuma öğleden sonra/akşam
            weekend_fix = any(
                d < f <= d + timedelta(hours=60) and f.weekday() in (5, 6)
                for f in fix_times
            )
            if weekend_fix:
                risky += 1
    if risky >= 2:
        return RuleFinding(
            "risky_deploy_window",
            f"Son dönemde {risky} kez cuma akşamı deploy'unu hafta sonu "
            "düzeltmesi izledi. Cuma öğleden sonrası riskli bir deploy penceresi "
            "olabilir — hafta sonu öncesi kısa bir deploy freeze'i denemeye değer.",
            "warning",
        )
    return None


RULES = [
    ("review_bottleneck", rule_review_bottleneck),
    ("hotspot_files", rule_hotspot_files),
    ("wip_overload", rule_wip_overload),
    ("low_process_hygiene", rule_low_process_hygiene),
    ("risky_deploy_window", rule_risky_deploy_window),
]


def run_rules(session: Session, cfg: Config) -> int:
    """Tüm takımlar için kuralları koşar; önerileri tazeler."""
    now = datetime.now(timezone.utc)
    end = now
    start = end - timedelta(days=cfg.app.window_days)
    written = 0
    for team in session.scalars(select(Team)):
        data = load_team_data(session, team, start, end)
        # Önceki öneriler silinir — öneriler anlık durumun fotoğrafıdır
        for old in session.scalars(
            select(Recommendation).where(
                Recommendation.scope == "team", Recommendation.scope_id == team.id
            )
        ):
            session.delete(old)
        for key, func in RULES:
            if not cfg.rule(key).enabled:
                continue
            finding = func(data, cfg)
            if finding:
                session.add(
                    Recommendation(
                        scope="team",
                        scope_id=team.id,
                        rule_key=finding.rule_key,
                        message=finding.message,
                        severity=finding.severity,
                        created_at=now,
                    )
                )
                written += 1
    session.commit()
    return written
