"""Tükenmişlik / sağlık sinyalleri.

Bunlar DORA metrikleri DEĞİL; takımın zorlanıp zorlanmadığına dair yumuşak
sinyallerdir. Felsefe aynı: kırmızı = "takım zorlanıyor, yardım gerekebilir",
asla kişi suçlama/kıyas aracı değil.

ÖNEMLI: dağılım/dengesizlik sinyalleri (WIP yığılması, review yükü) kişi
İSMİ göstermeden, yalnızca yoğunlaşma katsayısı olarak raporlanır. "Bir kişi
fazla yükleniyor" bilgisi yöneticinin yükü dengelemesi içindir, kişiyi
ifşa etmek için değil.

Veri yoksa sinyal 'insufficient_data' döner — asla uydurulmaz.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.metrics.engine import TeamData, as_utc, is_in_flow
from app.models import Leave, TeamMembership


def _gini(values: list[float]) -> float | None:
    """Gini katsayısı (0 = tam eşit dağılım, 1 = tümü tek kişide). Yük
    dengesizliğini kişi ismi olmadan tek sayıyla özetler."""
    xs = sorted(v for v in values if v is not None)
    n = len(xs)
    if n == 0:
        return None
    total = sum(xs)
    if total == 0:
        return 0.0
    cum = 0.0
    for i, x in enumerate(xs, start=1):
        cum += i * x
    return (2 * cum) / (n * total) - (n + 1) / n


def _status(value: float | None, green: float, red: float, higher_better: bool) -> str:
    if value is None:
        return "insufficient_data"
    if higher_better:
        if value >= green:
            return "green"
        if value <= red:
            return "red"
        return "yellow"
    if value <= green:
        return "green"
    if value >= red:
        return "red"
    return "yellow"


def off_hours_ratio(data: TeamData) -> dict:
    """Mesai dışı (08:00–20:00 dışı) veya hafta sonu yapılan commit oranı.
    Sürekli yüksekse tükenmişlik/aşırı yük sinyali."""
    dated = [c for c in data.commits if c.committed_at is not None]
    if not dated:
        return {"key": "off_hours_ratio", "value": None, "sample_size": 0,
                "status": "insufficient_data"}
    off = 0
    for c in dated:
        ts = as_utc(c.committed_at)
        if ts.weekday() >= 5 or ts.hour < 8 or ts.hour >= 20:
            off += 1
    ratio = off / len(dated)
    return {
        "key": "off_hours_ratio",
        "value": ratio,
        "sample_size": len(dated),
        "status": _status(ratio, green=0.15, red=0.35, higher_better=False),
    }


def wip_concentration(data: TeamData) -> dict:
    """Açık işlerin belirli kişilerde yığılıp yığılmadığı (Gini). İsim YOK;
    yalnızca dengesizlik. Yüksek = yük birkaç kişide, dağıtılmalı."""
    open_by_assignee: dict[int, int] = {}
    seen_any = False
    for t in data.tasks:
        if t.status is None:
            continue
        seen_any = True
        # Statü kategorileri config'ten çözümlenmiş eşlemeden gelir; burada
        # gömülü liste tutmak sinyalin WIP metriğiyle çelişmesine yol açıyordu.
        # Akış tanımı da WIP metriğiyle AYNI olmalı (is_in_flow): eşlenmemiş
        # kolon orada sayılmıyorsa burada da sayılmamalı.
        if not is_in_flow(t.status, data.statuses):
            continue
        if t.assignee_id is not None:
            open_by_assignee[t.assignee_id] = open_by_assignee.get(t.assignee_id, 0) + 1
    if not seen_any or not open_by_assignee:
        return {"key": "wip_concentration", "value": None,
                "sample_size": len(open_by_assignee), "status": "insufficient_data"}
    g = _gini([float(v) for v in open_by_assignee.values()])
    return {
        "key": "wip_concentration",
        "value": g,
        "sample_size": len(open_by_assignee),
        "status": _status(g, green=0.4, red=0.6, higher_better=False),
    }


def review_load_distribution(data: TeamData) -> dict:
    """Review yükü dağılımı / bus factor: review'ların tek kişiye yığılıp
    yığılmadığı. value = en çok review yapan kişinin payı (0..1). Yüksek =
    tek kişiye bağımlılık (düşük bus factor), riski dağıt."""
    counts: dict[int, int] = {}
    for pr in data.prs:
        for rv in pr.reviews:
            if rv.reviewer_id is not None:
                counts[rv.reviewer_id] = counts.get(rv.reviewer_id, 0) + 1
    total = sum(counts.values())
    if total == 0:
        return {"key": "review_load", "value": None, "sample_size": 0,
                "status": "insufficient_data", "reviewer_count": 0}
    top_share = max(counts.values()) / total
    return {
        "key": "review_load",
        "value": top_share,
        "sample_size": total,
        "reviewer_count": len(counts),
        "status": _status(top_share, green=0.5, red=0.75, higher_better=False),
    }


def leave_usage_signal(session: Session, data: TeamData) -> dict:
    """İzin sinyali: pencerede takımın ne kadarı izin kullandı. Kimse izin
    kullanmıyorsa (düşük) bu bir tükenmişlik riski sinyalidir — dinlenme
    kültürü zayıf. Yüksek kullanım sağlıklıdır (higher_better)."""
    member_dev_ids = {
        m.developer_id
        for m in session.scalars(
            select(TeamMembership).where(TeamMembership.team_id == data.team.id)
        )
        if m.role != "manager" and m.developer_id is not None
    }
    if not member_dev_ids:
        return {"key": "leave_usage", "value": None, "sample_size": 0,
                "status": "insufficient_data"}
    w_start: date = data.start.date()
    w_end: date = data.end.date()
    leaves = session.scalars(select(Leave)).all()
    took_leave = set()
    for lv in leaves:
        if lv.developer_id in member_dev_ids and lv.start_date <= w_end and lv.end_date >= w_start:
            took_leave.add(lv.developer_id)
    ratio = len(took_leave) / len(member_dev_ids)
    return {
        "key": "leave_usage",
        "value": ratio,
        "sample_size": len(member_dev_ids),
        "status": _status(ratio, green=0.30, red=0.05, higher_better=True),
    }


# Sinyal meta: başlık + açıklama + yön (frontend rengi/oku için)
SIGNAL_META = {
    "off_hours_ratio": (
        "Mesai Dışı Commit", "Hafta sonu ya da 08–20 dışı yapılan commit oranı; "
        "sürekli yüksekse aşırı yük sinyali", "lower"),
    "wip_concentration": (
        "WIP Yığılması", "Açık işlerin birkaç kişide toplanma dengesizliği "
        "(Gini, isim yok); yüksekse yük dağıtılmalı", "lower"),
    "review_load": (
        "Review Yükü / Bus Factor", "Review'ların tek kişiye yığılma payı; "
        "yüksekse tek kişiye bağımlılık riski", "lower"),
    "leave_usage": (
        "İzin Kullanımı", "Pencerede izin kullanan takım oranı; çok düşükse "
        "dinlenme kültürü zayıf (tükenmişlik riski)", "higher"),
}

SIGNAL_META_EN = {
    "off_hours_ratio": (
        "Off-Hours Commits", "Share of commits made on weekends or outside 08–20; "
        "consistently high is a signal of overload", "lower"),
    "wip_concentration": (
        "WIP Concentration", "Imbalance of open work piling up on a few people "
        "(Gini, no names); if high, load should be redistributed", "lower"),
    "review_load": (
        "Review Load / Bus Factor", "Share of reviews piling up on one person; "
        "if high, there's a single-person dependency risk", "lower"),
    "leave_usage": (
        "Leave Usage", "Share of the team taking leave in the window; if very low, "
        "rest culture is weak (burnout risk)", "higher"),
}

SIGNAL_LABELS = {
    "green": "Sağlıklı",
    "yellow": "İzlenmeli",
    "red": "Zorlanıyor — yardım gerekebilir",
    "insufficient_data": "Veri yetersiz",
}

SIGNAL_LABELS_EN = {
    "green": "Healthy",
    "yellow": "Worth watching",
    "red": "Struggling — support may help",
    "insufficient_data": "Not enough data",
}


def compute_signals(session: Session, data: TeamData, lang: str = "tr") -> list[dict]:
    """Tüm sinyalleri üretir, meta ile zenginleştirir."""
    raw = [
        off_hours_ratio(data),
        wip_concentration(data),
        review_load_distribution(data),
        leave_usage_signal(session, data),
    ]
    meta = SIGNAL_META_EN if lang == "en" else SIGNAL_META
    labels = SIGNAL_LABELS_EN if lang == "en" else SIGNAL_LABELS
    out = []
    for sig in raw:
        name, description, direction = meta.get(sig["key"], (sig["key"], "", "lower"))
        out.append({
            **sig,
            "name": name,
            "description": description,
            "direction": direction,
            "status_label": labels[sig["status"]],
        })
    return out
