"""Sağlık durumu eşlemesi.

Metrik değeri → green / yellow / red / insufficient_data.
Dil destek dilidir: kırmızı "kötü performans" değil, "takım zorlanıyor,
yardım gerekebilir" demektir. Etiketler bu çerçeveyle yazılır.
"""
from __future__ import annotations

from app.core.config import Config

# metric_key → (threshold alanı, yön). "lower": düşük değer iyi.
METRIC_THRESHOLD_MAP: dict[str, tuple[str, str]] = {
    "cycle_time": ("cycle_time_days", "lower"),
    "pr_review_time": ("pr_review_time_days", "lower"),
    "review_latency": ("review_latency_days", "lower"),
    "deployment_frequency": ("deployment_frequency", "higher"),
    "change_failure_rate": ("change_failure_rate", "lower"),
    "mttr": ("mttr_hours", "lower"),
    "wip": ("wip_per_dev", "lower"),
    "rework": ("rework_rate", "lower"),
    "process_hygiene": ("process_hygiene", "higher"),
    # estimate_accuracy: 1.0 ideal; ayrı ele alınır
}

STATUS_LABELS = {
    "green": "Akıyor",
    "yellow": "İzlenmeli",
    "red": "Zorlanıyor — yardım gerekebilir",
    "insufficient_data": "Veri yetersiz",
}

# İnsan-okur metrik adları ve kısa açıklamaları (dashboard'da gösterilir)
METRIC_META = {
    "cycle_time": ("Cycle Time", "İş açıldıktan bitene kadar geçen ortalama süre (gün)"),
    "pr_review_time": ("PR Süresi", "PR açılıştan merge'e ortalama süre (gün)"),
    "review_latency": ("Review Gecikmesi", "PR açılıştan ilk review'a ortalama süre (gün)"),
    "deployment_frequency": ("Teslim Sıklığı", "Haftalık teslim (merge) sayısı"),
    "change_failure_rate": ("Geri Dönüş Oranı", "Deploy sonrası kısa sürede düzeltme gerektirme oranı"),
    "mttr": ("Toparlanma Süresi (MTTR)", "Incident başladıktan normale dönene kadar geçen süre (saat). Kaynak: Jira 'incident' iş tipi ya da git revert; incident kaydı yoksa 'veri yetersiz'"),
    "wip": ("Açık İş (WIP)", "Kişi başına aynı anda açık iş sayısı"),
    "rework": ("Rework Oranı", "Aynı dosyaya kısa aralıkla tekrar dokunma oranı (takım)"),
    "estimate_accuracy": ("Tahmin Tutarlılığı", "Gerçekleşen / tahmin edilen süre oranı (1.0 ideal)"),
    "process_hygiene": ("Süreç Hijyeni", "Sürecin veriyle izlenebilirlik oranı (estimate, status, review dolulukları)"),
}


def health_status(metric_key: str, value: float | None, completeness: float, cfg: Config) -> str:
    """Değer + tamlıktan durum üretir. Tamlık eşiğin altındaysa değer olsa
    bile 'veri yetersiz' denir — asla emin değilmiş gibi renk basılmaz."""
    if value is None or completeness < cfg.health_thresholds.data_completeness_min:
        return "insufficient_data"
    if metric_key == "estimate_accuracy":
        # 1.0'a yakın iyi: [0.7, 1.5] yeşil, [0.5, 2.5] sarı, ötesi kırmızı
        if 0.7 <= value <= 1.5:
            return "green"
        if 0.5 <= value <= 2.5:
            return "yellow"
        return "red"
    mapping = METRIC_THRESHOLD_MAP.get(metric_key)
    if mapping is None:
        return "insufficient_data"
    field, direction = mapping
    th = getattr(cfg.health_thresholds, field)
    if direction == "lower":
        if value <= th.green:
            return "green"
        if value >= th.red:
            return "red"
        return "yellow"
    if value >= th.green:
        return "green"
    if value <= th.red:
        return "red"
    return "yellow"
