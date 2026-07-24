"""Yönetici operasyon uçları: kaynak/entegrasyon durumu, ayar, elle senkron.

Etik/güvenlik notu: token (sır) ASLA config'e yazılmaz; yalnızca ortam
değişkeninin adı ve "tanımlı mı" bilgisi gösterilir. Bu uçlar yönetici
yetkisi ister.
"""
from __future__ import annotations

import os

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import require_admin, require_owner
from app.core.config import active_config_path, get_config, reset_config_cache
from app.core.db import get_session
from app.models import MetricResult, User

router = APIRouter(prefix="/api/admin")


class SourcesUpdate(BaseModel):
    git_provider: str | None = None       # git_log | gitlab | fixture
    tasks_provider: str | None = None     # jira | trello | fixture | none
    gitlab_base_url: str | None = None
    jira_base_url: str | None = None
    sync_interval_minutes: int | None = None
    # Trello: board id'leri config'e yazılır (sır değil); key/token ise sır
    # olarak .secrets.env'e + ortama yazılır, config'e ASLA girmez.
    trello_boards: list[str] | None = None
    trello_key: str | None = None
    trello_token: str | None = None
    # GitHub PAT: "Projelerim" özel repoları için. Sır → .secrets.env, config'e değil.
    github_token: str | None = None


def _env_status(var: str) -> dict:
    return {"env_var": var, "configured": bool(os.environ.get(var))}


def _ai_ready(cfg) -> bool:
    """AI kod analizi kullanıma hazır mı? Sağlayıcıya göre değişir: claude API
    anahtarı ister; local (Ollama vb.) anahtarsız da çalışır (base_url yeter)."""
    if not (cfg.llm.enabled and cfg.code_analysis.enabled):
        return False
    if cfg.llm.provider == "claude":
        return bool(os.environ.get(cfg.llm.claude.api_key_env))
    if cfg.llm.provider == "local":
        return bool(cfg.llm.local.base_url)
    return False


@router.get("/sources")
def get_sources(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    cfg = get_config()
    last_sync = session.scalar(select(func.max(MetricResult.computed_at)))
    return {
        "last_sync": last_sync.isoformat() if last_sync else None,
        "sync_interval_minutes": cfg.sync.interval_minutes,
        "git": {
            "provider": cfg.sources.git.provider,
            "gitlab_base_url": cfg.sources.git.gitlab.base_url,
            "token": _env_status(cfg.sources.git.gitlab.token_env),
            # "Projelerim" özel GitHub repoları için PAT durumu.
            "github_token": _env_status("GITHUB_TOKEN"),
            "repo_count": len(cfg.sources.git.repos),
        },
        "tasks": {
            "provider": cfg.sources.tasks.provider,
            "jira_base_url": cfg.sources.tasks.jira.base_url,
            "token": _env_status(cfg.sources.tasks.jira.token_env),
            "trello": {
                "boards": cfg.sources.tasks.trello.boards,
                "key": _env_status(cfg.sources.tasks.trello.key_env),
                "token": _env_status(cfg.sources.tasks.trello.token_env),
            },
        },
    }


@router.put("/sources")
def update_sources(
    body: SourcesUpdate,
    _: User = Depends(require_admin),
):
    # Mevcut config.yaml'ı ham oku, yalnızca verilen alanları güncelle, geri yaz.
    # (Yorumlar kaybolur — on-prem tek dosya, kabul edilebilir.) Sır YAZILMAZ.
    raw = {}
    if active_config_path().exists():
        with open(active_config_path(), encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    raw.setdefault("sources", {})
    raw["sources"].setdefault("git", {}).setdefault("gitlab", {})
    raw["sources"].setdefault("tasks", {}).setdefault("jira", {})
    raw["sources"]["tasks"].setdefault("trello", {})
    raw.setdefault("sync", {})

    if body.git_provider is not None:
        raw["sources"]["git"]["provider"] = body.git_provider
    if body.tasks_provider is not None:
        raw["sources"]["tasks"]["provider"] = body.tasks_provider
    if body.gitlab_base_url is not None:
        raw["sources"]["git"]["gitlab"]["base_url"] = body.gitlab_base_url
    if body.jira_base_url is not None:
        raw["sources"]["tasks"]["jira"]["base_url"] = body.jira_base_url
    if body.sync_interval_minutes is not None:
        raw["sync"]["interval_minutes"] = max(0, body.sync_interval_minutes)
    if body.trello_boards is not None:
        # Board id'leri temizle (boşları at). Sır DEĞİL → config'e yazılır.
        raw["sources"]["tasks"]["trello"]["boards"] = [
            b.strip() for b in body.trello_boards if b and b.strip()
        ]

    # Sırlar (Trello key/token): config'e YAZILMAZ — .secrets.env + ortama.
    cfg = get_config()
    if body.trello_key is not None:
        from app.core.secrets import set_secret
        set_secret(cfg.sources.tasks.trello.key_env, body.trello_key.strip())
    if body.trello_token is not None:
        from app.core.secrets import set_secret
        set_secret(cfg.sources.tasks.trello.token_env, body.trello_token.strip())
    if body.github_token is not None:
        from app.core.secrets import set_secret
        set_secret("GITHUB_TOKEN", body.github_token.strip())

    active_config_path().parent.mkdir(parents=True, exist_ok=True)
    with open(active_config_path(), "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    reset_config_cache()
    return {"ok": True}


class CodeAnalysisUpdate(BaseModel):
    enabled: bool | None = None
    llm_enabled: bool | None = None
    # NOT: sağlayıcı seçimi + kimlik bilgileri buradan DEĞİL, yalnız baş yönetici
    # (owner) /api/admin/llm-provider ucundan yönetir (bkz. llm_provider uçları).
    weights: dict[str, float] | None = None
    exclude_globs: list[str] | None = None
    max_files_per_run: int | None = None
    max_diff_lines: int | None = None


@router.get("/code-analysis")
def get_code_analysis(_: User = Depends(require_admin)):
    """AI kod analizi ayarları (rubrik ağırlıkları, hariç klasörler, sıklık).
    API anahtarı config'e yazılmaz; yalnızca env durumu gösterilir."""
    cfg = get_config()
    ca = cfg.code_analysis
    # Aktif sağlayıcıya göre gösterilecek model + anahtar durumu.
    if cfg.llm.provider == "local":
        active_model = cfg.llm.local.model
        active_key = _env_status(cfg.llm.local.api_key_env)
    else:
        active_model = cfg.llm.claude.model
        active_key = _env_status(cfg.llm.claude.api_key_env)
    return {
        "enabled": ca.enabled,
        "llm_enabled": cfg.llm.enabled,
        "llm_provider": cfg.llm.provider,
        "model": active_model,
        "api_key": active_key,
        "weights": ca.weights,
        "exclude_globs": ca.exclude_globs,
        "max_files_per_run": ca.max_files_per_run,
        "max_diff_lines": ca.max_diff_lines,
    }


@router.put("/code-analysis")
def update_code_analysis(body: CodeAnalysisUpdate, _: User = Depends(require_admin)):
    raw = {}
    if active_config_path().exists():
        with open(active_config_path(), encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    raw.setdefault("code_analysis", {})
    raw.setdefault("llm", {})

    if body.enabled is not None:
        raw["code_analysis"]["enabled"] = body.enabled
    if body.llm_enabled is not None:
        raw["llm"]["enabled"] = body.llm_enabled
    if body.weights is not None:
        # yalnızca bilinen boyutları kabul et, negatifleri kırp
        from app.services.code_analysis import DIMENSIONS
        raw["code_analysis"]["weights"] = {
            d: max(0.0, float(body.weights.get(d, 1.0))) for d in DIMENSIONS
        }
    if body.exclude_globs is not None:
        raw["code_analysis"]["exclude_globs"] = [g for g in body.exclude_globs if g.strip()]
    if body.max_files_per_run is not None:
        raw["code_analysis"]["max_files_per_run"] = max(1, body.max_files_per_run)
    if body.max_diff_lines is not None:
        raw["code_analysis"]["max_diff_lines"] = max(20, body.max_diff_lines)

    active_config_path().parent.mkdir(parents=True, exist_ok=True)
    with open(active_config_path(), "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    reset_config_cache()
    return {"ok": True}


# --- AI sağlayıcı yönetimi (YALNIZ baş yönetici / owner) ----------------------
# Etik/güvenlik: hangi AI kullanılacağı ve API anahtarları en üst yetkiye aittir.
# Anahtar config.yaml'a ASLA yazılmaz — .secrets.env + ortama yazılır (set_secret).
# provider=local, OpenAI-uyumlu HERHANGİ bir uca (Ollama, LM Studio, vLLM, OpenAI,
# OpenRouter…) base_url ile yönlendirilir; böylece Claude zorunlu değildir.

LLM_PROVIDERS = ["none", "claude", "local"]


class LlmProviderUpdate(BaseModel):
    provider: str | None = None              # none | claude | local
    claude_model: str | None = None
    claude_api_key: str | None = None        # sır → .secrets.env (config'e YAZILMAZ)
    local_base_url: str | None = None
    local_model: str | None = None
    local_api_key: str | None = None         # opsiyonel sır (anahtarsız uçlarda boş)


@router.get("/llm-provider")
def get_llm_provider(_: User = Depends(require_owner)):
    """Aktif AI sağlayıcı yapılandırması (yalnız baş yönetici). Anahtarların
    KENDİSİ dönülmez — yalnız 'tanımlı mı' durumu (env_status)."""
    cfg = get_config()
    return {
        "enabled": cfg.llm.enabled,
        "provider": cfg.llm.provider,
        "providers": LLM_PROVIDERS,
        "claude": {
            "model": cfg.llm.claude.model,
            "api_key": _env_status(cfg.llm.claude.api_key_env),
        },
        "local": {
            "base_url": cfg.llm.local.base_url,
            "model": cfg.llm.local.model,
            "api_key": _env_status(cfg.llm.local.api_key_env),
        },
    }


@router.put("/llm-provider")
def update_llm_provider(body: LlmProviderUpdate, _: User = Depends(require_owner)):
    """Baş yönetici AI sağlayıcıyı ve kendi kimlik bilgilerini ayarlar.
    Model/base_url config.yaml'a; API anahtarları .secrets.env'e (+ canlı ortama)
    yazılır. Boş anahtar gönderilirse o anahtar TEMİZLENİR."""
    from app.core.secrets import set_secret

    if body.provider is not None and body.provider not in LLM_PROVIDERS:
        raise HTTPException(422, detail=f"provider yalnızca {', '.join(LLM_PROVIDERS)} olabilir")

    raw = {}
    if active_config_path().exists():
        with open(active_config_path(), encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    raw.setdefault("llm", {})
    raw["llm"].setdefault("claude", {})
    raw["llm"].setdefault("local", {})

    if body.provider is not None:
        raw["llm"]["provider"] = body.provider
        # Provider = tek açma/kapama düğmesi: 'none' modülü kapatır, gerçek bir
        # sağlayıcı seçmek llm + kod analizini açar. Ayrı 'enabled' kutucuğu yok.
        on = body.provider != "none"
        raw["llm"]["enabled"] = on
        raw.setdefault("code_analysis", {})["enabled"] = on
    if body.claude_model is not None and body.claude_model.strip():
        raw["llm"]["claude"]["model"] = body.claude_model.strip()
    if body.local_base_url is not None and body.local_base_url.strip():
        raw["llm"]["local"]["base_url"] = body.local_base_url.strip()
    if body.local_model is not None and body.local_model.strip():
        raw["llm"]["local"]["model"] = body.local_model.strip()

    cfg = get_config()
    # Sırlar config'e YAZILMAZ. None = dokunma; "" = temizle; değer = ayarla.
    if body.claude_api_key is not None:
        set_secret(cfg.llm.claude.api_key_env, body.claude_api_key.strip())
    if body.local_api_key is not None:
        set_secret(cfg.llm.local.api_key_env, body.local_api_key.strip())

    active_config_path().parent.mkdir(parents=True, exist_ok=True)
    with open(active_config_path(), "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    reset_config_cache()
    return {"ok": True}


@router.post("/code-analysis/run")
def run_code_analysis_now(_: User = Depends(require_admin)):
    """Elle AI kod analizi çalıştır (git_log repoları, tüm yazarlar)."""
    from app.core.db import get_sessionmaker
    from app.services.code_analysis import run_code_analysis

    session = get_sessionmaker()()
    try:
        return run_code_analysis(session, get_config())
    finally:
        session.close()


@router.get("/code-analysis/overview")
def code_analysis_overview(session: Session = Depends(get_session), _: User = Depends(require_admin)):
    """Tüm şirketin genel AI kod sağlığı (admin)."""
    from app.services.code_health import company_code_health

    return company_code_health(session, get_config())


@router.get("/code-analysis/overview/breakdown")
def code_analysis_overview_breakdown(session: Session = Depends(get_session), _: User = Depends(require_admin)):
    from app.services.code_health import company_code_health_breakdown

    return company_code_health_breakdown(session)


class GitEmailUpdate(BaseModel):
    git_email: str | None = None


@router.patch("/developers/{dev_id}/git-email")
def set_developer_git_email(
    dev_id: int,
    body: GitEmailUpdate,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Kişinin git commit e-postasını bağlar (kişi-bazlı kod analizi için).
    Elle SQL yerine panelden. Boş verilirse bağ kaldırılır."""
    from app.models import Developer

    dev = session.get(Developer, dev_id)
    if dev is None:
        raise HTTPException(404, "Kişi bulunamadı")
    ext = dict(dev.external_ids or {})
    email = (body.git_email or "").strip().lower()
    if email:
        ext["git"] = email
    else:
        ext.pop("git", None)
    dev.external_ids = ext
    session.commit()
    return {"ok": True, "git_email": ext.get("git")}


@router.get("/code-analysis/audit")
def code_analysis_audit(
    limit: int = 100,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """LLM'e ne gitti denetim kaydı (gizlilik şeffaflığı). İçerik saklanmaz —
    yalnızca meta: dosya, kaç karakter, kaç secret maskelendi, sonuç."""
    from app.models import CodeAnalysisAudit

    rows = session.scalars(
        select(CodeAnalysisAudit).order_by(CodeAnalysisAudit.sent_at.desc()).limit(min(limit, 500))
    ).all()
    return [
        {
            "id": a.id, "file_path": a.file_path, "diff_hash": a.diff_hash[:12],
            "chars_sent": a.chars_sent, "masked_secrets": a.masked_secrets,
            "provider": a.provider, "model": a.model, "outcome": a.outcome,
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
        }
        for a in rows
    ]


@router.get("/onboarding")
def onboarding_status(session: Session = Depends(get_session), _: User = Depends(require_admin)):
    """Kurulum kontrol listesi: admin ne yapacağını görsün (yeni kurulumda
    kaybolmasın). Her adım tamam/eksik + kısa ipucu."""
    from app.models import Commit, Developer, MetricResult

    cfg = get_config()
    real_source = cfg.sources.git.provider != "fixture"
    has_commits = session.scalar(select(func.count()).select_from(Commit)) or 0
    has_metrics = session.scalar(select(func.count()).select_from(MetricResult)) or 0
    # kimlik eşleme: bir user'a bağlı developer'lardan kaçının git e-postası var
    linked = unlinked = 0
    for u in session.scalars(select(User).where(User.developer_id.isnot(None))):
        dev = session.get(Developer, u.developer_id)
        if dev and (dev.external_ids or {}).get("git"):
            linked += 1
        else:
            unlinked += 1
    employees = session.scalar(select(func.count()).select_from(User)) or 0

    steps = [
        {"key": "source", "done": real_source,
         "label": "Gerçek veri kaynağı bağla",
         "hint": "config.yaml sources.git.provider: git_log/gitlab (şu an fixture)." if not real_source else "Bağlı."},
        {"key": "sync", "done": bool(has_commits or has_metrics),
         "label": "Senkron çalıştır",
         "hint": "Yönetici paneli → Entegrasyon → Senkronla (veya CLI sync)." if not (has_commits or has_metrics) else f"{has_commits} commit çekildi."},
        {"key": "employees", "done": employees > 1,
         "label": "Çalışan hesapları oluştur",
         "hint": "Hesaplar sekmesinden çalışan ekle." if employees <= 1 else f"{employees} hesap."},
        {"key": "identity", "done": unlinked == 0 and linked > 0,
         "label": "Giriş hesaplarını git kimliğine bağla",
         "hint": f"{unlinked} hesabın git e-postası yok — kişi-bazlı analiz için AI Kod Analizi sekmesinden bağla." if unlinked else "Hepsi bağlı."},
        {"key": "ai", "done": _ai_ready(cfg),
         "label": "AI kod analizini aç",
         "hint": "AI Kod Analizi sekmesi → Baş Yönetici sağlayıcıyı ve API anahtarını girer." if not _ai_ready(cfg) else "Açık."},
    ]
    return {"steps": steps, "linked": linked, "unlinked": unlinked,
            "complete": all(s["done"] for s in steps)}


@router.get("/code-analysis/developers")
def code_analysis_developers(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Kişi listesi: admin herkesi tek tek analiz edip sonucunu görsün.
    git_email tanımsızsa atıf yapılamaz (analiz edilebilir=false)."""
    from app.models import CodeAnalysis, Developer
    from app.services.code_health import _latest_per_file

    out = []
    for dev in session.scalars(select(Developer)):
        git_email = (dev.external_ids or {}).get("git")
        files = _latest_per_file(list(session.scalars(
            select(CodeAnalysis).where(CodeAnalysis.developer_id == dev.id))))
        composite = round(sum(f.composite for f in files) / len(files), 1) if files else None
        out.append({
            "id": dev.id, "display_name": dev.display_name,
            "git_email": git_email, "analyzable": bool(git_email),
            "analyzed_files": len(files), "composite": composite,
        })
    out.sort(key=lambda d: d["display_name"].lower())
    return out


@router.post("/code-analysis/run-developer/{dev_id}")
def run_code_analysis_developer(dev_id: int, _: User = Depends(require_admin)):
    """Admin, tek bir kişinin kodunu (git yazarı) isteğe bağlı analiz eder."""
    from app.core.db import get_sessionmaker
    from app.services.code_analysis import run_code_analysis

    session = get_sessionmaker()()
    try:
        return run_code_analysis(session, get_config(), only_developer_id=dev_id)
    finally:
        session.close()


@router.post("/sync")
def trigger_sync(_: User = Depends(require_admin)):
    """Elle senkron: kaynaklardan çek + metrik hesapla + öneri üret."""
    from app.services.pipeline import run_pipeline

    stats = run_pipeline()
    return {"ok": True, "stats": stats}
