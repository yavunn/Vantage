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

# TR sözlükler geriye dönük uyum için burada duruyor (mevcut çağıranlar
# METRIC_META / STATUS_LABELS adıyla import ediyor). Dil seçimi gereken yerler
# app/core/i18n.py'deki metric_meta(lang) / status_labels(lang) kullanır —
# çeviriler TEK yerde yaşasın diye buradaki sözlükler oradan geliyor.
from app.core.i18n import METRIC_META_TR as _META_TR
from app.core.i18n import STATUS_LABELS_TR as _STATUS_TR

STATUS_LABELS = _STATUS_TR

# İnsan-okur metrik adları ve kısa açıklamaları (dashboard'da gösterilir).
# Çeviriler app/core/i18n.py'de; burada yalnız TR karşılığa takma ad verilir.
METRIC_META = _META_TR


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
