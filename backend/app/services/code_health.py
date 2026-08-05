"""Kod sağlığı toplama (AI analiz sonuçlarından).

Skorlar KİŞİ DEĞİL repo/modül/dosya düzeyinde toplanır. "Kod tabanının şu
bölümü yardım istiyor" dili. Dosya yolu gösterilir, kişi asla.

Bir dosyanın birden çok diff analizi olabilir; güncel sağlık için dosya başına
EN SON analiz alınır. Trend için analyzed_at haftalık kovalanır.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Config
from app.models import CodeAnalysis, Repo
from app.services.code_analysis import DIMENSIONS

DIM_LABELS = {
    "readability": "Okunabilirlik",
    "complexity": "Karmaşıklık",
    "maintainability": "Bakım Yapılabilirlik",
    "test_adequacy": "Test Yeterliliği",
    "security": "Güvenlik",
    "code_smells": "Kod Kokuları",
    "conventions": "Konvansiyon Uyumu",
}

DIM_LABELS_EN = {
    "readability": "Readability",
    "complexity": "Complexity",
    "maintainability": "Maintainability",
    "test_adequacy": "Test Adequacy",
    "security": "Security",
    "code_smells": "Code Smells",
    "conventions": "Convention Compliance",
}


def _status(composite: float | None) -> str:
    if composite is None:
        return "insufficient_data"
    if composite >= 75:
        return "green"
    if composite <= 50:
        return "red"
    return "yellow"


STATUS_LABELS = {
    "green": "Sağlıklı",
    "yellow": "İzlenmeli",
    "red": "Zorlanıyor — yardım gerekebilir",
    "insufficient_data": "Analiz bekliyor",
}

STATUS_LABELS_EN = {
    "green": "Healthy",
    "yellow": "Worth watching",
    "red": "Struggling — support may help",
    "insufficient_data": "Awaiting analysis",
}

NAME_EN = {
    "Kod Sağlığı (şirket geneli)": "Code Health (company-wide)",
    "Kod Sağlığı (kişi)": "Code Health (individual)",
    "Kod Sağlığı": "Code Health",
}

_DESC_EN = {
    "AI kod analizi composite skoru (repo/modül düzeyi)":
        "AI code analysis composite score (repo/module level)",
    "AI kod analizi composite skoru (repo/modül düzeyi, kişi değil)":
        "AI code analysis composite score (repo/module level, not per person)",
    "Haftalık AI kod analizi composite trendi": "Weekly AI code analysis composite trend",
}

_NOTE_EN = "AI code analysis is off (llm.enabled + code_analysis.enabled)."


def _dim_labels(lang: str) -> dict:
    return DIM_LABELS_EN if lang == "en" else DIM_LABELS

def _status_labels(lang: str) -> dict:
    return STATUS_LABELS_EN if lang == "en" else STATUS_LABELS

def _tr(text: str, lang: str) -> str:
    return NAME_EN.get(text, text) if lang == "en" else text

def _desc(text: str, lang: str) -> str:
    return _DESC_EN.get(text, text) if lang == "en" else text


def _module_of(file_path: str) -> str:
    """Dosya yolundan modül (ilk 2 dizin) çıkarır; kök dosyalar '(kök)'."""
    parts = file_path.replace("\\", "/").strip("/").split("/")
    if len(parts) <= 1:
        return "(kök)"
    return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def _latest_per_file(rows: list[CodeAnalysis]) -> list[CodeAnalysis]:
    """Dosya başına en son analizi tutar (güncel sağlık)."""
    latest: dict[str, CodeAnalysis] = {}
    for r in rows:
        cur = latest.get(r.file_path)
        if cur is None or (r.analyzed_at and cur.analyzed_at and r.analyzed_at > cur.analyzed_at):
            latest[r.file_path] = r
    return [r for r in latest.values() if r.composite is not None]


def _team_analyses(session: Session, team_id: int) -> list[CodeAnalysis]:
    repo_ids = [r.id for r in session.scalars(select(Repo).where(Repo.team_id == team_id))]
    if not repo_ids:
        return []
    return list(session.scalars(
        select(CodeAnalysis).where(CodeAnalysis.repo_id.in_(repo_ids))
    ))


def _dev_analyses(session: Session, developer_id: int) -> list[CodeAnalysis]:
    return list(session.scalars(
        select(CodeAnalysis).where(CodeAnalysis.developer_id == developer_id)
    ))


def _latest_per_repo_file(rows: list[CodeAnalysis]) -> list[CodeAnalysis]:
    """Şirket geneli: (repo, dosya) başına en son analiz (farklı repolarda aynı
    dosya adı çakışmasın)."""
    latest: dict[tuple, CodeAnalysis] = {}
    for r in rows:
        k = (r.repo_id, r.file_path)
        cur = latest.get(k)
        if cur is None or (r.analyzed_at and cur.analyzed_at and r.analyzed_at > cur.analyzed_at):
            latest[k] = r
    return [r for r in latest.values() if r.composite is not None]


def company_code_health(session: Session, cfg: Config, lang: str = "tr") -> dict:
    """Tüm şirketin genel AI kod sağlığı (tüm repo/dosya). Admin görünümü."""
    enabled = cfg.llm.enabled and cfg.code_analysis.enabled
    files = _latest_per_repo_file(list(session.scalars(select(CodeAnalysis))))
    return _health_payload(files, enabled, _tr("Kod Sağlığı (şirket geneli)", lang), lang)


def company_code_health_breakdown(session: Session, lang: str = "tr") -> dict:
    return _breakdown_payload(_latest_per_repo_file(list(session.scalars(select(CodeAnalysis)))), lang)


def _health_payload(files: list[CodeAnalysis], enabled: bool, name: str, lang: str = "tr") -> dict:
    """Ortak composite + modül kırılımı üretici (takım ve kişi paylaşır)."""
    dim_labels = _dim_labels(lang)
    status_labels = _status_labels(lang)
    if not files:
        return {
            "key": "code_health", "name": name,
            "description": _desc("AI kod analizi composite skoru (repo/modül düzeyi)", lang),
            "value": None, "status": "insufficient_data",
            "status_label": status_labels["insufficient_data"],
            "sample_size": 0, "data_completeness": 0.0, "enabled": enabled,
            "note": None if enabled else _NOTE_EN if lang == "en" else "AI kod analizi kapalı (llm.enabled + code_analysis.enabled).",
            "modules": [],
        }
    composite = sum(f.composite for f in files) / len(files)
    dim_avgs = {
        d: round(sum(getattr(f, d) for f in files if getattr(f, d) is not None)
                 / max(1, sum(1 for f in files if getattr(f, d) is not None)))
        for d in DIMENSIONS
    }
    by_mod: dict[str, list[CodeAnalysis]] = {}
    for f in files:
        by_mod.setdefault(_module_of(f.file_path), []).append(f)
    modules = []
    for mod, mfiles in by_mod.items():
        mcomp = sum(x.composite for x in mfiles) / len(mfiles)
        worst_dim = min(DIMENSIONS, key=lambda d: sum(getattr(x, d) for x in mfiles) / len(mfiles))
        modules.append({
            "module": mod, "composite": round(mcomp, 1), "files": len(mfiles),
            "status": _status(mcomp), "worst_dimension": dim_labels[worst_dim],
        })
    modules.sort(key=lambda m: m["composite"])
    status = _status(composite)
    return {
        "key": "code_health", "name": name,
        "description": _desc("AI kod analizi composite skoru (repo/modül düzeyi)", lang),
        "value": round(composite, 1), "status": status,
        "status_label": status_labels[status],
        "sample_size": len(files), "data_completeness": 1.0, "enabled": enabled, "note": None,
        "dimension_averages": {dim_labels[d]: dim_avgs[d] for d in DIMENSIONS},
        "modules": modules,
    }


def developer_code_health(session: Session, developer_id: int, cfg: Config, lang: str = "tr") -> dict:
    """Kişinin KENDİ kodunun AI sağlığı (git yazarı atfı). Kıyas yok, kendi
    kodunun geri bildirimi. Kapalı/veri yoksa 'analiz bekliyor'."""
    enabled = cfg.llm.enabled and cfg.code_analysis.enabled
    files = _latest_per_file(_dev_analyses(session, developer_id))
    return _health_payload(files, enabled, _tr("Kod Sağlığı (kişi)", lang), lang)


def developer_code_health_breakdown(session: Session, developer_id: int, lang: str = "tr") -> dict:
    return _breakdown_payload(_latest_per_file(_dev_analyses(session, developer_id)), lang)


def team_code_health(session: Session, team_id: int, cfg: Config, lang: str = "tr") -> dict:
    """Takımın composite kod sağlığı + modül kırılımı. AI kapalı ya da veri
    yoksa 'analiz bekliyor' (uydurma skor yok)."""
    enabled = cfg.llm.enabled and cfg.code_analysis.enabled
    files = _latest_per_file(_team_analyses(session, team_id))
    dim_labels = _dim_labels(lang)
    status_labels = _status_labels(lang)

    if not files:
        return {
            "key": "code_health", "name": _tr("Kod Sağlığı", lang),
            "description": _desc("AI kod analizi composite skoru (repo/modül düzeyi, kişi değil)", lang),
            "value": None, "status": "insufficient_data",
            "status_label": status_labels["insufficient_data"],
            "sample_size": 0, "data_completeness": 0.0,
            "enabled": enabled,
            "note": None if enabled else _NOTE_EN if lang == "en" else "AI kod analizi kapalı (llm.enabled + code_analysis.enabled).",
            "modules": [],
        }

    composite = sum(f.composite for f in files) / len(files)
    # boyut ortalamaları (kartta radar/özet için)
    dim_avgs = {
        d: round(sum(getattr(f, d) for f in files if getattr(f, d) is not None)
                 / max(1, sum(1 for f in files if getattr(f, d) is not None)))
        for d in DIMENSIONS
    }

    # modül kırılımı
    by_mod: dict[str, list[CodeAnalysis]] = {}
    for f in files:
        by_mod.setdefault(_module_of(f.file_path), []).append(f)
    modules = []
    for mod, mfiles in by_mod.items():
        mcomp = sum(x.composite for x in mfiles) / len(mfiles)
        # en zayıf boyut (yardım isteyen alan)
        worst_dim = min(
            DIMENSIONS,
            key=lambda d: sum(getattr(x, d) for x in mfiles) / len(mfiles),
        )
        modules.append({
            "module": mod, "composite": round(mcomp, 1), "files": len(mfiles),
            "status": _status(mcomp),
            "worst_dimension": dim_labels[worst_dim],
        })
    modules.sort(key=lambda m: m["composite"])  # en çok yardım isteyen üstte

    status = _status(composite)
    return {
        "key": "code_health", "name": _tr("Kod Sağlığı", lang),
        "description": _desc("AI kod analizi composite skoru (repo/modül düzeyi, kişi değil)", lang),
        "value": round(composite, 1), "status": status,
        "status_label": status_labels[status],
        "sample_size": len(files), "data_completeness": 1.0,
        "enabled": enabled, "note": None,
        "dimension_averages": {dim_labels[d]: dim_avgs[d] for d in DIMENSIONS},
        "modules": modules,
    }


def _breakdown_payload(files: list[CodeAnalysis], lang: str = "tr") -> dict:
    """Dosya bazlı drill-down (takım ve kişi paylaşır). En düşük composite üstte."""
    dim_labels = _dim_labels(lang)
    files = sorted(files, key=lambda f: f.composite)
    rows = []
    for f in files:
        rows.append({
            "file_path": f.file_path,
            "module": _module_of(f.file_path),
            "composite": round(f.composite, 1),
            "status": _status(f.composite),
            "dimensions": {dim_labels[d]: getattr(f, d) for d in DIMENSIONS},
            "summary": f.summary,
            "suggestions": [s.get("text") for s in (f.suggestions or [])],
            "analyzed_at": f.analyzed_at.isoformat() if f.analyzed_at else None,
        })
    return {"count": len(rows), "rows": rows}


def team_code_health_breakdown(session: Session, team_id: int, lang: str = "tr") -> dict:
    """Drill-down: en çok dikkat isteyen dosyalar + AI önerileri (kişi yok)."""
    return _breakdown_payload(_latest_per_file(_team_analyses(session, team_id)), lang)


def team_code_health_series(session: Session, team_id: int, cfg: Config, lang: str = "tr") -> dict:
    """Haftalık kod sağlığı trendi (analyzed_at kovaları). Kova composite'i o
    hafta analiz edilen dosyaların ortalaması."""
    rows = [r for r in _team_analyses(session, team_id) if r.composite is not None and r.analyzed_at]
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=cfg.app.window_days)
    bucket = timedelta(days=cfg.app.bucket_days)
    points = []
    b_start = start
    while b_start < now:
        b_end = min(b_start + bucket, now)
        vals = [
            r.composite for r in rows
            if b_start <= r.analyzed_at.astimezone(timezone.utc) <= b_end
        ]
        points.append({
            "period_start": f"{b_start:%Y-%m-%d}",
            "period_end": f"{b_end:%Y-%m-%d}",
            "value": round(sum(vals) / len(vals), 1) if vals else None,
            "data_completeness": 1.0 if vals else 0.0,
        })
        b_start = b_end
    return {
        "metric": "code_health", "name": _tr("Kod Sağlığı", lang),
        "description": _desc("Haftalık AI kod analizi composite trendi", lang), "points": points,
    }
