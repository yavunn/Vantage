"""Yönetici operasyon uçları: kaynak/entegrasyon durumu, ayar, elle senkron.

Etik/güvenlik notu: token (sır) ASLA config'e yazılmaz; yalnızca ortam
değişkeninin adı ve "tanımlı mı" bilgisi gösterilir. Bu uçlar yönetici
yetkisi ister.
"""
from __future__ import annotations

import os

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import require_admin, require_owner
from app.core.config import active_config_path, get_config, reset_config_cache
from app.core.db import get_session
from app.core.i18n import lang_from_request, tr_error
from app.models import MetricResult, User

router = APIRouter(prefix="/api/admin")


class RepoEntry(BaseModel):
    """config.yaml'daki bir git repo girdisi. team boşsa eşleme yok demektir.

    path : git_log sağlayıcısı için yerel klasör yolu.
    slug : github sağlayıcısı için 'owner/repo' (ya da tam GitHub URL'i).
    İkisi bir arada durabilir; hangisinin okunacağını sağlayıcı belirler."""

    name: str = Field(min_length=1, max_length=200)
    path: str = ""
    slug: str = ""
    team: str = ""


class SourcesUpdate(BaseModel):
    git_provider: str | None = None       # git_log | github | gitlab | fixture
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
    # GitLab/Jira: adres + token panelden girilebilsin diye. Token'lar sır →
    # .secrets.env; env değişkeninin ADI config'ten okunur (token_env), sabit değil.
    gitlab_token: str | None = None
    jira_token: str | None = None
    # Jira proje anahtarları (ör. ["ENG", "OPS"]). Sır değil → config'e yazılır.
    jira_projects: list[str] | None = None
    # Jira kimlik/uç ayarları. Panelden girilebilmeleri ŞART: Jira CLOUD
    # e-posta + API token ile BASIC auth ister ve eski arama ucu Cloud'da
    # kaldırıldı. Bunlar yalnız YAML'dan ayarlanabilir kalsaydı, "gerçek
    # kurulumda çalışsın" düzeltmesi pratikte kullanılamazdı.
    jira_auth: str | None = None            # basic | bearer
    jira_email: str | None = None           # basic auth kullanıcı adı
    jira_api_style: str | None = None       # auto | cloud | server
    jira_story_points_field: str | None = None
    # GitLab hedefleri artık ORTAK `repos` listesinden okunur (repo→takım eşlemesi
    # oradan geliyor). Bu alan eski kurulumların listesini düzenleyebilmek için
    # duruyor; panel kullanmaz.
    gitlab_projects: list[str] | None = None
    # repo adı → takım adı. Boş değer eşlemeyi kaldırır. Takımsız repo'nun
    # commitleri hiçbir takım metriğine giremez, o yüzden bu panelden yönetilir.
    repo_teams: dict[str, str] | None = None
    # Repo listesinin TAMAMI (ekleme/çıkarma). Verilirse config'teki liste bununla
    # değiştirilir; verilmezse dokunulmaz. Kurulu sistemde yeni repo bağlamak
    # sunucuya girip YAML düzenlemeyi gerektirmemeli.
    repos: list[RepoEntry] | None = None


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
    from app.models import Commit, Repo, Team

    cfg = get_config()
    last_sync = session.scalar(select(func.max(MetricResult.computed_at)))

    # Config'teki repolar + DB'deki karşılığı (takım bağlı mı, kaç commit geldi).
    # Panel "repo sayısı: 1" demek yerine hangi reponun nereye bağlı olduğunu gösterir.
    db_repos = {r.name: r for r in session.scalars(select(Repo))}
    repos = []
    for r in cfg.sources.git.repos:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        row = db_repos.get(r["name"])
        repos.append({
            "name": r["name"],
            "path": r.get("path"),
            "slug": r.get("slug"),
            "team": r.get("team"),
            "commit_count": (session.scalar(
                select(func.count()).select_from(Commit).where(Commit.repo_id == row.id)
            ) or 0) if row else 0,
        })

    return {
        "last_sync": last_sync.isoformat() if last_sync else None,
        "sync_interval_minutes": cfg.sync.interval_minutes,
        # Repo→takım açılır listesi için; takımsız repo metrik üretmez.
        "teams": [{"id": t.id, "name": t.name} for t in session.scalars(select(Team))],
        "git": {
            "provider": cfg.sources.git.provider,
            "gitlab_base_url": cfg.sources.git.gitlab.base_url,
            # Eski biçimdeki hedef listesi: panelde repo satırları boşken hâlâ
            # buradan çekiliyor olabilir — görünmezse "neden hâlâ veri geliyor"
            # sorusu doğar.
            "gitlab_projects": list(cfg.sources.git.gitlab.projects),
            "token": _env_status(cfg.sources.git.gitlab.token_env),
            # Hem "Projelerim" özel repoları hem de github sağlayıcısı bu PAT'i
            # kullanır. Public repo tokensiz çalışır ama oran sınırı 60/saat.
            "github_token": _env_status(cfg.sources.git.github.token_env),
            "repo_count": len(cfg.sources.git.repos),
            "repos": repos,
        },
        "tasks": {
            "provider": cfg.sources.tasks.provider,
            "jira_base_url": cfg.sources.tasks.jira.base_url,
            "jira_projects": list(cfg.sources.tasks.jira.projects),
            "jira_auth": cfg.sources.tasks.jira.auth,
            "jira_email": cfg.sources.tasks.jira.email,
            "jira_api_style": cfg.sources.tasks.jira.api_style,
            "jira_story_points_field": cfg.sources.tasks.jira.story_points_field,
            "token": _env_status(cfg.sources.tasks.jira.token_env),
            "trello": {
                "boards": cfg.sources.tasks.trello.boards,
                "key": _env_status(cfg.sources.tasks.trello.key_env),
                "token": _env_status(cfg.sources.tasks.trello.token_env),
            },
            # NOT: statü eşlemesi (kolon adı → backlog/in_progress/done) BU UÇTA
            # DÖNMEZ ve panelden düzenlenmez. Ekip zaten kartı Trello'da doğru
            # listeye taşıyarak akışı belirliyor; ikinci bir eşleme ekranı aynı
            # kararı iki yerde yönetmek demekti. Eşleme config.yaml'da yaşamaya
            # ve metrik motoru tarafından KULLANILMAYA devam eder
            # (sources.tasks.status_mapping → app/metrics/engine.py:resolve_statuses).
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
    if body.jira_auth is not None:
        secim = body.jira_auth.strip().lower()
        if secim not in ("basic", "bearer"):
            raise HTTPException(422, tr_error("jira_auth 'basic' ya da 'bearer' olmalı."))
        raw["sources"]["tasks"]["jira"]["auth"] = secim
    if body.jira_email is not None:
        # E-posta sır DEĞİLDİR (token sırdır) → config'e yazılabilir.
        raw["sources"]["tasks"]["jira"]["email"] = body.jira_email.strip()
    if body.jira_api_style is not None:
        secim = body.jira_api_style.strip().lower()
        if secim not in ("auto", "cloud", "server"):
            raise HTTPException(422, tr_error("jira_api_style 'auto', 'cloud' ya da 'server' olmalı."))
        raw["sources"]["tasks"]["jira"]["api_style"] = secim
    if body.jira_story_points_field is not None:
        # Boş bırakmak bilinçli tercihtir: alan hiç okunmaz, uyarı da üretilmez.
        raw["sources"]["tasks"]["jira"]["story_points_field"] = \
            body.jira_story_points_field.strip()
    if body.sync_interval_minutes is not None:
        raw["sync"]["interval_minutes"] = max(0, body.sync_interval_minutes)
    if body.trello_boards is not None:
        # Board id'leri temizle (boşları at). Sır DEĞİL → config'e yazılır.
        raw["sources"]["tasks"]["trello"]["boards"] = [
            b.strip() for b in body.trello_boards if b and b.strip()
        ]
    if body.jira_projects is not None:
        raw["sources"]["tasks"]["jira"]["projects"] = [
            p.strip() for p in body.jira_projects if p and p.strip()
        ]
    if body.gitlab_projects is not None:
        raw["sources"]["git"]["gitlab"]["projects"] = [
            p.strip() for p in body.gitlab_projects if p and p.strip()
        ]
    if body.repos is not None:
        # Listenin TAMAMI değişir (ekleme/çıkarma). Aynı ad iki kez verilemez:
        # repo adı ingest'te kimlik anahtarıdır, çakışırsa commitler karışır.
        seen: set[str] = set()
        entries = []
        for r in body.repos:
            name = r.name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            entry = {"name": name, "path": r.path.strip()}
            if r.slug.strip():
                entry["slug"] = r.slug.strip()
            if r.team.strip():
                entry["team"] = r.team.strip()
            entries.append(entry)
        raw["sources"]["git"]["repos"] = entries
    if body.repo_teams is not None:
        # Repo→takım eşlemesi config'te repo girdisinin 'team' alanında yaşar;
        # pipeline bunu repo_team_map'e çevirip ingest'e verir.
        for entry in raw["sources"]["git"].setdefault("repos", []):
            if not isinstance(entry, dict) or entry.get("name") not in body.repo_teams:
                continue
            team = (body.repo_teams[entry["name"]] or "").strip()
            if team:
                entry["team"] = team
            else:
                entry.pop("team", None)
    # status_mapping bu uçtan YAZILMAZ (panelden kaldırıldı). config.yaml'daki
    # mevcut blok olduğu gibi korunur: raw yeniden yazılırken dokunulmadığı için
    # motor onu okumaya devam eder.

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
    # Env değişkeninin adı config'ten okunur: kurulum GITLAB_TOKEN yerine başka
    # bir ad kullanıyorsa panel onu yazsın, sabit ada yazıp sessizce kaybolmasın.
    if body.gitlab_token is not None:
        from app.core.secrets import set_secret
        set_secret(cfg.sources.git.gitlab.token_env, body.gitlab_token.strip())
    if body.jira_token is not None:
        from app.core.secrets import set_secret
        set_secret(cfg.sources.tasks.jira.token_env, body.jira_token.strip())

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
    # NOT: hariç tutulan klasörler (node_modules, dist, vendor…) ayar DEĞİL —
    # code_analysis.BUILTIN_EXCLUDES'ta sabit, API'den değiştirilemez.
    max_files_per_run: int | None = None
    max_diff_lines: int | None = None


@router.get("/code-analysis")
def get_code_analysis(_: User = Depends(require_admin)):
    """AI kod analizi ayarları (rubrik ağırlıkları, analiz limitleri).
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
        raise HTTPException(422, detail=tr_error(
            "provider yalnızca {list} olabilir", list=", ".join(LLM_PROVIDERS)
        ))

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
def code_analysis_overview(session: Session = Depends(get_session), _: User = Depends(require_admin),
                            lang: str = Depends(lang_from_request)):
    """Tüm şirketin genel AI kod sağlığı (admin)."""
    from app.services.code_health import company_code_health

    return company_code_health(session, get_config(), lang)


@router.get("/code-analysis/overview/breakdown")
def code_analysis_overview_breakdown(session: Session = Depends(get_session), _: User = Depends(require_admin),
                                      lang: str = Depends(lang_from_request)):
    from app.services.code_health import company_code_health_breakdown

    return company_code_health_breakdown(session, lang)


class GitEmailUpdate(BaseModel):
    """Tek e-posta (eski istemciler) ya da liste (çoklu adres).

    `git_emails` verildiyse o kazanır; ikisi de boşsa bağ kaldırılır."""

    git_email: str | None = None
    git_emails: list[str] | None = None


@router.patch("/developers/{dev_id}/git-email")
def set_developer_git_email(
    dev_id: int,
    body: GitEmailUpdate,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Kişinin git commit e-posta(ları)nı bağlar (kişi-bazlı kod analizi için).
    Elle SQL yerine panelden. Boş verilirse bağ kaldırılır.

    Aynı e-posta başkasındaysa 409: kimliği sessizce el değiştirmek, o kişinin
    commit'lerini bir sonraki senkronda başka birine atfederdi."""
    from app.models import Developer
    from app.services.identity import (
        IdentityConflict,
        check_git_emails_free,
        git_emails,
        with_git_emails,
    )

    dev = session.get(Developer, dev_id)
    if dev is None:
        raise HTTPException(404, tr_error("Kişi bulunamadı"))
    yeni = body.git_emails if body.git_emails is not None else (
        [body.git_email] if body.git_email else []
    )
    ext = with_git_emails(dev.external_ids, [e for e in yeni if e])
    try:
        check_git_emails_free(session, git_emails(ext), dev_id)
    except IdentityConflict as e:
        raise HTTPException(409, tr_error(str(e))) from e
    dev.external_ids = ext
    session.commit()
    return {"ok": True, "git_email": git_emails(ext)[0] if git_emails(ext) else None,
            "git_emails": git_emails(ext)}


@router.get("/identities")
def identities(session: Session = Depends(get_session), _: User = Depends(require_admin)):
    """Kimlik eşleme tablosu: her kişi hangi kaynakta hangi anahtarla görünüyor.

    Aynı insan git'te e-posta, Trello'da üye id'siyle gelir; ingest bunları
    eşleştiremez. Bu uç, eşlenmemiş kayıtları görünür kılar ki admin birleştirsin.
    """
    from app.models import Commit, Developer, Task, TeamMembership
    from app.services.identity import git_emails

    out = []
    for dev in session.scalars(select(Developer).order_by(Developer.display_name)):
        ids = dict(dev.external_ids or {})
        task_sources = {k: v for k, v in ids.items() if k != "git"}
        gitler = git_emails(ids)
        out.append({
            "id": dev.id,
            "display_name": dev.display_name,
            # git_email = birincil (tek e-posta gösteren eski ekranlar için),
            # git_emails = tamamı. İkincisi olmadan çoklu adres görünmezdi.
            "git_email": gitler[0] if gitler else None,
            "git_emails": gitler,
            "task_identities": task_sources,
            # Hangi kaydın "asıl" olduğunu ayırt etmek için: commit'ler bir
            # kayda, görevler diğerine düşmüş olabilir — birleştirmede hedef,
            # ağırlığı taşıyan kayıt olmalı.
            "commit_count": session.scalar(
                select(func.count()).select_from(Commit).where(Commit.author_id == dev.id)
            ) or 0,
            "team_count": session.scalar(
                select(func.count()).select_from(TeamMembership)
                .where(TeamMembership.developer_id == dev.id)
            ) or 0,
            "task_count": session.scalar(
                select(func.count()).select_from(Task).where(Task.assignee_id == dev.id)
            ) or 0,
            # Bağlı giriş hesabı: eşleme yaparken hangi kaydın "gerçek" kişi
            # olduğunu ayırt etmeyi sağlar (hesabı olan taraf hedef seçilmeli).
            "user_email": session.scalar(
                select(User.email).where(User.developer_id == dev.id)
            ),
            # Ne git ne hesap: büyük olasılıkla bir kaynak kaydının kopyası
            "unlinked": not gitler and bool(task_sources),
        })
    return out


def _hesap_listesi(session: Session) -> list[dict]:
    """Kimlik bağlanabilecek kişiler: giriş HESABI olan Developer kayıtları.

    Hesabı olmayan kayıt hedef olamaz — o zaten çoğu zaman kaynağın açtığı
    kopyanın kendisidir; ona bağlamak kopyayı kalıcılaştırırdı."""
    from app.models import Developer

    out = []
    for u in session.scalars(select(User).where(User.developer_id.isnot(None))):
        dev = session.get(Developer, u.developer_id)
        if dev is None:
            continue
        out.append({
            "developer_id": dev.id,
            "display_name": dev.display_name,
            "user_email": u.email,
            "external_ids": dict(dev.external_ids or {}),
        })
    out.sort(key=lambda a: (a["display_name"] or "").lower())
    return out


@router.get("/trello/members")
def trello_members(session: Session = Depends(get_session), _: User = Depends(require_admin)):
    """Board üyeleri + her birinin bağlı olduğu giriş hesabı (ya da 'bağsız').

    Bu ekran olmadan Trello kimliği yalnız ham üye id'si (opak hash) elle
    yazılarak bağlanabiliyordu; pratikte kimse yapmıyordu ve kart↔commit
    eşleşmesi kişiyi hiç tanımıyordu.

    Trello okunamazsa uyarı GÖVDEDE döner (hata değil): board erişimi bozukken
    de bağlı üyeler listelenebilmeli, aksi hâlde ekran tamamen kararırdı.
    """
    from app.models import Developer
    from app.services.identity import suggest_account

    cfg = get_config()
    saglayici = (cfg.sources.tasks.provider or "none").lower()
    if saglayici != "trello":
        raise HTTPException(400, tr_error(
            f"Görev kaynağı 'trello' değil (şu an: {saglayici}). Kaynaklar bölümünden değiştirin."
        ))

    from app.adapters.trello import TrelloProvider

    t = cfg.sources.tasks.trello
    provider = TrelloProvider(t.key_env, t.token_env, t.boards)
    kayitlar = provider.fetch_member_directory()

    hesaplar = _hesap_listesi(session)
    # Trello üye id'si → o kimliği taşıyan Developer (hesabı olmayanlar dahil:
    # kaynağın açtığı kopya kayıtları da göstermek gerekir, "bağsız" damgası
    # yanlış olurdu).
    kimlige_gore: dict[str, Developer] = {}
    for dev in session.scalars(select(Developer)):
        anahtar = (dev.external_ids or {}).get("trello")
        if anahtar:
            kimlige_gore[str(anahtar)] = dev
    hesabi_olan = {a["developer_id"]: a for a in hesaplar}

    # Aynı üye birden çok board'da olabilir: tek satır, board listesiyle.
    birlesik: dict[str, dict] = {}
    for k in kayitlar:
        satir = birlesik.setdefault(k["member_id"], {
            "member_id": k["member_id"],
            "username": k["username"],
            "full_name": k["full_name"],
            "boards": [],
        })
        ad = k["board_name"] or k["board_id"]
        if ad not in satir["boards"]:
            satir["boards"].append(ad)

    uyeler = []
    for satir in birlesik.values():
        dev = kimlige_gore.get(satir["member_id"])
        hesap = hesabi_olan.get(dev.id) if dev else None
        oneri = None
        if dev is None:
            aday = suggest_account(satir["full_name"], satir["username"], hesaplar)
            if aday:
                oneri = {"developer_id": aday[0], "reason": aday[1],
                         "display_name": hesabi_olan[aday[0]]["display_name"]}
        uyeler.append({
            **satir,
            "linked": dev is not None,
            "developer_id": dev.id if dev else None,
            "developer_name": dev.display_name if dev else None,
            # Bağlı ama giriş hesabı yok = kaynağın açtığı kopya kayıt. Ayrı
            # gösterilmeli: "bağlı" demek burada işin bittiği anlamına gelmez.
            "user_email": hesap["user_email"] if hesap else None,
            "suggestion": oneri,
        })
    uyeler.sort(key=lambda m: (m["linked"], (m["full_name"] or m["username"] or "").lower()))

    return {
        "provider": saglayici,
        "boards": list(t.boards),
        "members": uyeler,
        "accounts": [
            {"developer_id": a["developer_id"], "display_name": a["display_name"],
             "user_email": a["user_email"],
             "trello": (a["external_ids"] or {}).get("trello")}
            for a in hesaplar
        ],
        "warnings": list(provider.warnings),
    }


class TaskIdentityUpdate(BaseModel):
    source: str = Field(min_length=1, max_length=50)   # trello | jira | ...
    key: str | None = None                             # boş → bağ kaldırılır


@router.patch("/developers/{dev_id}/task-identity")
def set_developer_task_identity(
    dev_id: int,
    body: TaskIdentityUpdate,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Kişiye görev kaynağı kimliği bağlar (Trello üye id'si vb.) ve varsa aynı
    kimliği taşıyan KOPYA kişi kaydını hedefe birleştirir.

    Birleştirme şart: kopya kaydı öylece bırakmak takım kadrosunu şişirir, WIP
    kişi başına bölündüğü için metrik olduğundan iyi görünür. Kopyanın task'ları
    ve takım üyelikleri hedefe taşınır, sonra kopya silinir.
    """
    from app.models import Developer

    dev = session.get(Developer, dev_id)
    if dev is None:
        raise HTTPException(404, tr_error("Kişi bulunamadı"))
    source = body.source.strip().lower()
    key = (body.key or "").strip()
    ext = dict(dev.external_ids or {})

    if not key:
        ext.pop(source, None)
        dev.external_ids = ext
        session.commit()
        return {"ok": True, "task_identities": {k: v for k, v in ext.items() if k != "git"},
                "merged_developer_id": None}

    from app.services.identity import IdentityConflict, task_identity_owner

    merged_id = None
    # Kimliği taşıyan başka kayıt varsa: giriş hesabı olan bir kayda çarparsak
    # o bir "kopya" değil BAŞKA BİR İNSANDIR ve birleştirme iki çalışanın
    # verisini tek kişide toplardı — servis bunu 409'a çevirir.
    try:
        duplicate = task_identity_owner(session, source, key, dev.id)
    except IdentityConflict as e:
        raise HTTPException(409, tr_error(str(e))) from e
    if duplicate is not None:
        # Birleştirme tek yerde: developers.id'ye bakan TÜM tablolar taşınmalı
        # (commit/PR/review/izin/analiz dahil), yoksa silme adımı FK hatası verir.
        from app.services.identity import merge_developers

        merged_id = duplicate.id
        merge_developers(session, dev.id, duplicate.id)
        session.refresh(dev)
        ext = dict(dev.external_ids or {})

    ext[source] = key
    dev.external_ids = ext
    session.commit()
    return {
        "ok": True,
        "task_identities": {k: v for k, v in ext.items() if k != "git"},
        "merged_developer_id": merged_id,
    }


@router.get("/developers/duplicate-candidates")
def duplicate_candidates(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Aynı insan olma ihtimali yüksek kişi çiftleri + gerekçeleri.

    OTOMATİK BİRLEŞTİRME YOK — burada yalnız ADAY listelenir, kararı insan
    verir (POST /developers/{id}/merge). Bu bir gözetim özelliği değil, VERİ
    KALİTESİ uyarısıdır: ikiz kayıtlar takım kadrosunu şişirir ve kişi başı
    metrikler (WIP) olduğundan İYİ görünür.

    Uyarı senkron sonucunda da çıkar ama orada kaybolur; eşleme ekranının
    listeyi doğrudan gösterebilmesi gerekiyordu.
    """
    from app.services.ingest import duplicate_identity_pairs

    out = []
    for a, b, sebep in duplicate_identity_pairs(session):
        out.append({
            "reason": sebep,
            "a": {"id": a.id, "name": a.display_name,
                  "external_ids": {k: v for k, v in (a.external_ids or {}).items()}},
            "b": {"id": b.id, "name": b.display_name,
                  "external_ids": {k: v for k, v in (b.external_ids or {}).items()}},
        })
    return {"candidates": out, "count": len(out)}


class DeveloperMerge(BaseModel):
    duplicate_id: int


@router.post("/developers/{dev_id}/merge")
def merge_developer(
    dev_id: int,
    body: DeveloperMerge,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """İki kişi kaydını birleştirir (hedef = dev_id, silinen = duplicate_id).

    Görev kimliği üzerinden otomatik birleştirme yetmediği durum için: aynı
    insan İKİ git e-postasıyla gelmiş olabilir (ör. biri GitHub'ın
    `…@users.noreply.github.com` adresi). O zaman iki kayıt da "eşlenmiş"
    görünür, hiçbir otomatik ipucu yoktur ve kararı yalnız insan verebilir.
    """
    from app.services.identity import MergeError, merge_developers

    try:
        return merge_developers(session, dev_id, body.duplicate_id)
    except MergeError as e:
        raise HTTPException(400, str(e)) from e


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
            "extra_reads": a.extra_reads,
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
    from app.services.identity import git_emails

    cfg = get_config()
    real_source = cfg.sources.git.provider != "fixture"
    has_commits = session.scalar(select(func.count()).select_from(Commit)) or 0
    has_metrics = session.scalar(select(func.count()).select_from(MetricResult)) or 0
    # kimlik eşleme: bir user'a bağlı developer'lardan kaçının git e-postası var
    linked = unlinked = 0
    for u in session.scalars(select(User).where(User.developer_id.isnot(None))):
        dev = session.get(Developer, u.developer_id)
        if dev and git_emails(dev.external_ids):
            linked += 1
        else:
            unlinked += 1
    employees = session.scalar(select(func.count()).select_from(User)) or 0
    # Görev kaynağı kimliği: kaç Developer'ın Trello/Jira üye anahtarı var.
    # git bağı tek başına yetmez — kart↔commit eşleşmesinde kişi sinyali ve
    # "görevlerim" görünümü bu bağ olmadan hiç çalışmaz, ama eksikliği hiçbir
    # ekranda görünmüyordu.
    task_source = (cfg.sources.tasks.provider or "none").lower()
    task_linked = task_unlinked = 0
    if task_source in ("trello", "jira"):
        for u in session.scalars(select(User).where(User.developer_id.isnot(None))):
            dev = session.get(Developer, u.developer_id)
            if dev and (dev.external_ids or {}).get(task_source):
                task_linked += 1
            else:
                task_unlinked += 1

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
    if task_source in ("trello", "jira"):
        # git adımının HEMEN ARDINA: ikisi aynı işin iki yarısıdır (commit
        # tarafı + görev tarafı). Biri eksikken kart↔commit eşleşmesi kişiyi
        # tanımaz ve "görevlerim" ekranı boş kalır.
        steps.insert(4, {
            "key": "task_identity",
            "done": task_unlinked == 0 and task_linked > 0,
            "label": f"Giriş hesaplarını {task_source.capitalize()} üyeliğine bağla",
            "hint": (
                f"{task_unlinked} hesabın {task_source} üye kimliği yok — Entegrasyon → "
                f"{task_source.capitalize()} üyeleri bölümünden bağla."
                if task_unlinked else f"{task_linked} hesap bağlı."
            ),
        })
    return {"steps": steps, "linked": linked, "unlinked": unlinked,
            "task_source": task_source,
            "task_linked": task_linked, "task_unlinked": task_unlinked,
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

    from app.services.identity import primary_git_email

    out = []
    for dev in session.scalars(select(Developer)):
        git_email = primary_git_email(dev.external_ids)
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
def trigger_sync(full: bool = False, user: User = Depends(require_admin)):
    """Elle senkron BAŞLATIR ve hemen döner (arka planda çalışır).

    Eskiden pipeline istek içinde koşuyordu: gerçek kaynakla dakikalar sürüyor,
    tarayıcı/proxy zaman aşımına düşüyor ve ilerleme görünmüyordu. Durum
    GET /api/admin/sync/{job_id} (ya da /sync/status) ile izlenir.

    full=true: son senkron damgasını yok sayıp tam çekim yapar."""
    from app.services import sync_job

    job, sebep = sync_job.baslat(triggered_by=user.email, incremental=not full)
    if job is None:
        # 409: istek geçerli ama şu an çalıştırılamaz — kullanıcı tekrar dener.
        raise HTTPException(409, sebep or "Senkron başlatılamadı.")
    return {"ok": True, "job": job.payload()}


@router.get("/sync/status")
def sync_status(_: User = Depends(require_admin)):
    """Son senkronun durumu (çalışıyor / bitti / hata + uyarılar)."""
    from app.services import sync_job

    job = sync_job.son_is()
    return {"job": job.payload() if job else None}


@router.get("/sync/{job_id}")
def sync_job_durumu(job_id: str, _: User = Depends(require_admin)):
    from app.services import sync_job

    job = sync_job.is_getir(job_id)
    if job is None:
        raise HTTPException(404, tr_error("Senkron işi bulunamadı."))
    return {"job": job.payload()}


@router.post("/sources/test")
def test_sources(_: User = Depends(require_admin)):
    """Kaynakları KURU çalıştırır: neyin okunabildiğini söyler, DB'ye YAZMAZ.

    Senkronu beklemeden 'board id yanlış' / 'repo yolu bozuk' gibi hataları
    yüzeye çıkarır — yanlış ayarla saatlerce boş pano izlenmesin."""
    from app.adapters.factory import build_git_provider, build_task_provider
    from app.core.secrets import load_secrets

    load_secrets()  # arayüzden yeni girilen token bu testte de geçerli olsun
    cfg = get_config()

    def _probe(provider, label: str, fetch) -> dict:
        if provider is None:
            return {"ok": False, "provider": None,
                    "detail": f"{label} sağlayıcısı yok (provider: none/tanımsız)."}
        # Sağlayıcı uyarı sözleşmesini uyguluyor mu? Uygulamıyorsa "uyarı yok"
        # bilgi DEĞİL, sessizliktir: eskiden böyle bir sağlayıcı (Jira) 401 alsa
        # bile bu uç ok:true, count:0 diyor ve kullanıcı "bağlantı çalışıyor,
        # henüz kayıt yok" sanıyordu. Tam da bunu engellemek için yazılmış bir uç.
        uyari_destegi = hasattr(provider, "warnings")
        try:
            items = fetch(provider)
        except Exception as e:  # noqa: BLE001 — test ucu asla 500 vermemeli
            return {"ok": False, "provider": type(provider).__name__,
                    "detail": f"{label} okunamadı: {type(e).__name__}.",
                    "warnings": list(getattr(provider, "warnings", []))}
        warnings = list(getattr(provider, "warnings", []))
        out = {"provider": type(provider).__name__, "count": len(items),
               "warnings": warnings}
        if not uyari_destegi:
            out["ok"] = False
            out["detail"] = (
                f"{label} sağlayıcısı ({type(provider).__name__}) hata bildirimi "
                "desteklemiyor — sonucun doğruluğu doğrulanamıyor."
            )
            return out
        if warnings:
            out["ok"] = False
            return out
        if not items:
            # "0 kayıt + uyarı yok" bir başarı değildir: filtre/proje/board ayarı
            # yanlış olabilir ve bunu ancak kullanıcı bilir.
            out["ok"] = False
            out["detail"] = (
                f"{label} bağlantısı kuruldu ama hiç kayıt gelmedi — proje/board "
                "listesi ve filtre ayarlarını kontrol edin."
            )
            return out
        out["ok"] = True
        return out

    git = build_git_provider(cfg)
    git_res = _probe(git, "Git", lambda p: p.fetch_commits())
    if git is not None and "count" in git_res:
        git_res["pull_requests"] = len(git.fetch_pull_requests())

    tasks_res = _probe(build_task_provider(cfg), "Görev", lambda p: p.fetch_tasks())

    # Takımsız repo senkronda metrik üretmez — testte de söylensin.
    unmapped = [
        r["name"] for r in cfg.sources.git.repos
        if isinstance(r, dict) and r.get("name") and not r.get("team")
    ]
    return {
        "git": git_res,
        "tasks": tasks_res,
        "unmapped_repos": unmapped,
        "ok": git_res.get("ok", False) and tasks_res.get("ok", False) and not unmapped,
    }


# --- Takım yönetimi (servis edilen üründe config dosyasına dokunmadan) ---------
# Takımlar şimdiye dek YALNIZCA ingest sırasında (Trello board adı / repo eşlemesi)
# örtük olarak doğuyordu; oluşturma, yeniden adlandırma ve silme yolu yoktu.
# Kurulu bir sistemde bu, "yeni takım için sunucuya gir ve YAML düzenle" demekti.

class TeamBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _team_usage(session: Session, team_id: int) -> dict:
    """Takıma ne bağlı? Silme kararını yönetici bilerek versin diye gösterilir."""
    from app.models import Repo, Task, TeamMembership

    return {
        "members": session.scalar(select(func.count()).select_from(TeamMembership)
                                  .where(TeamMembership.team_id == team_id)) or 0,
        "repos": session.scalar(select(func.count()).select_from(Repo)
                                .where(Repo.team_id == team_id)) or 0,
        "tasks": session.scalar(select(func.count()).select_from(Task)
                                .where(Task.team_id == team_id)) or 0,
    }


@router.get("/teams")
def list_teams_admin(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    from app.models import Team

    out = []
    for t in session.scalars(select(Team).order_by(Team.name)):
        usage = _team_usage(session, t.id)
        out.append({
            "id": t.id, "name": t.name, **usage,
            # Silinebilir mi: yönetici önce üyeyi/repoyu bilinçli olarak ayırmalı.
            "deletable": usage["members"] == 0 and usage["repos"] == 0,
        })
    return out


@router.post("/teams", status_code=201)
def create_team(
    body: TeamBody,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    from app.models import Team

    name = body.name.strip()
    if session.scalar(select(Team).where(Team.name == name)) is not None:
        raise HTTPException(status_code=409, detail=tr_error("'{name}' adlı takım zaten var.", name=name))
    team = Team(name=name)
    session.add(team)
    session.commit()
    return {"id": team.id, "name": team.name, "members": 0, "repos": 0, "tasks": 0,
            "deletable": True}


@router.patch("/teams/{team_id}")
def rename_team(
    team_id: int,
    body: TeamBody,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Takımı yeniden adlandırır ve config'teki repo eşlemesini BİRLİKTE günceller.

    Eşleme adla tutulduğu için config güncellenmezse bir sonraki senkron eski
    adla YENİ bir takım yaratır ve repo oraya kayardı (sessiz veri bölünmesi)."""
    from app.models import Team

    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail=tr_error("Takım bulunamadı"))
    new_name = body.name.strip()
    if new_name == team.name:
        return {"ok": True, "id": team.id, "name": team.name, "config_updated": False}
    if session.scalar(select(Team).where(Team.name == new_name)) is not None:
        raise HTTPException(status_code=409, detail=tr_error("'{name}' adlı takım zaten var.", name=new_name))

    old_name = team.name
    team.name = new_name
    session.commit()

    config_updated = _rewrite_repo_team_name(old_name, new_name)
    return {"ok": True, "id": team.id, "name": team.name, "config_updated": config_updated}


def _rewrite_repo_team_name(old_name: str, new_name: str | None) -> bool:
    """config.yaml'daki repo→takım eşlemelerinde adı günceller (None = kaldırır)."""
    path = active_config_path()
    if not path.exists():
        return False
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    repos = (raw.get("sources", {}).get("git", {}) or {}).get("repos") or []
    changed = False
    for entry in repos:
        if isinstance(entry, dict) and entry.get("team") == old_name:
            if new_name:
                entry["team"] = new_name
            else:
                entry.pop("team", None)
            changed = True
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
        reset_config_cache()
    return changed


@router.delete("/teams/{team_id}")
def delete_team(
    team_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Takımı siler. Üye ya da repo bağlıysa REDDEDER — yönetici önce bilinçli
    olarak ayırsın (kazara veri kopması olmasın). Task'lar silinmez, takımsız
    kalır; metrik/öneri satırları temizlenir (o takım artık yok)."""
    from app.models import Recommendation, Task, Team, TrendAnnotation

    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail=tr_error("Takım bulunamadı"))
    usage = _team_usage(session, team_id)
    blockers = []
    if usage["members"]:
        blockers.append(f"{usage['members']} üye")
    if usage["repos"]:
        blockers.append(f"{usage['repos']} repo")
    if blockers:
        raise HTTPException(
            status_code=409,
            detail=("Takım silinemedi — önce şunları ayırın: " + ", ".join(blockers)
                    + ". (Repo için Entegrasyon → Repo'lar, üye için Hesaplar sekmesi.)"),
        )

    # Task'lar KORUNUR, yalnızca takımsız kalır: gerçek iş kaydı silinmemeli.
    for t in session.scalars(select(Task).where(Task.team_id == team_id)):
        t.team_id = None
    for a in session.scalars(select(TrendAnnotation).where(TrendAnnotation.team_id == team_id)):
        a.team_id = None
    for m in session.scalars(select(MetricResult).where(
            MetricResult.scope == "team", MetricResult.scope_id == team_id)):
        session.delete(m)
    for r in session.scalars(select(Recommendation).where(
            Recommendation.scope == "team", Recommendation.scope_id == team_id)):
        session.delete(r)
    session.delete(team)
    session.commit()
    # Config'te bu takıma işaret eden repo eşlemesi varsa temizle (kalırsa
    # sonraki senkron takımı sessizce geri yaratırdı).
    _rewrite_repo_team_name(team.name, None)
    return {"ok": True, "detached_tasks": usage["tasks"]}


# --- Görünürlük + anket ayarları ---------------------------------------------
# Kapsam BİLİNÇLİ olarak dar: yalnızca yöneticinin gerçekten bilebileceği
# kararlar. Eşik/kural/metrik değerleri buraya AİT DEĞİL — onlar yöneticinin
# tahmin edeceği sayılar değil, sistemin veriden çıkarması gereken şeyler.
# (Bir form koymak, sorumluluğu bilmeyen tarafa atıyordu.)

class SettingsUpdate(BaseModel):
    # app.* — kimlik görünürlüğü; İK talebiyle değişir, kod değişmemeli.
    individual_view_enabled: bool | None = None
    anonymize_individuals: bool | None = None
    # survey.*
    survey_enabled: bool | None = None
    survey_interval_days: int | None = None
    survey_min_responses: int | None = None


@router.get("/settings")
def get_settings(_: User = Depends(require_admin)):
    cfg = get_config()
    return {
        "app": {
            "individual_view_enabled": cfg.app.individual_view_enabled,
            "anonymize_individuals": cfg.app.anonymize_individuals,
        },
        "survey": {
            "enabled": cfg.survey.enabled,
            "interval_days": cfg.survey.interval_days,
            "min_responses": cfg.survey.min_responses,
        },
    }


@router.put("/settings")
def update_settings(body: SettingsUpdate, _: User = Depends(require_admin)):
    raw: dict = {}
    if active_config_path().exists():
        with open(active_config_path(), encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    raw.setdefault("app", {})
    raw.setdefault("survey", {})

    if body.individual_view_enabled is not None:
        raw["app"]["individual_view_enabled"] = body.individual_view_enabled
    if body.anonymize_individuals is not None:
        raw["app"]["anonymize_individuals"] = body.anonymize_individuals
    if body.survey_enabled is not None:
        raw["survey"]["enabled"] = body.survey_enabled
    if body.survey_interval_days is not None:
        raw["survey"]["interval_days"] = max(1, body.survey_interval_days)
    if body.survey_min_responses is not None:
        # Gizlilik eşiği: 1'in altına inerse tek yanıt ifşa olur.
        raw["survey"]["min_responses"] = max(1, body.survey_min_responses)

    active_config_path().parent.mkdir(parents=True, exist_ok=True)
    with open(active_config_path(), "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    reset_config_cache()
    return {"ok": True}
