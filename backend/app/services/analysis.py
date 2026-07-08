"""Kullanıcı projesi analizi (Faz 4).

Akış: credential decrypt → provider kur → MEVCUT ingest hattına yaz →
mevcut metrik/kural motorunu çalıştır → commit hijyen sinyalleri üret.
Paralel ikinci motor yoktur; veri normalize modele (Commit, PullRequest...)
akar.

Etik çerçeve:
- Hijyen sinyalleri TAKIM/PROJE hijyenidir (scope="project") — kişi bazlı
  skor/sıralama üretilmez.
- Eksik alan (mesajsız commit vb.) completeness'i düşürür; değer asla
  uydurulmaz, hiç veri yoksa value=None yazılır.
- Token yalnız bellek içinde decrypt edilir; last_detail/log'a yazılmaz.

Arka plan: mevcut APScheduler bağımlılığı (date job) — Celery yok.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.adapters.base import GitProvider
from app.adapters.github import GitHubProvider
from app.adapters.gitlab import GitLabProvider
from app.core.config import get_config
from app.core.crypto import decrypt_secret
from app.core.db import get_sessionmaker
from app.metrics.engine import compute_all
from app.models import Commit, MetricResult, Repo, UserProject
from app.rules.engine import run_rules
from app.services.ingest import Ingestor

logger = logging.getLogger(__name__)

# Konvansiyonel commit mesajı: "feat: ...", "fix(api): ...", "hotfix: ..."
CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|hotfix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]*\))?!?:",
    re.IGNORECASE,
)
LARGE_COMMIT_FILES = 10       # bu kadar+ dosyaya dokunan commit "geniş" sayılır
HYGIENE_METRICS = ("commit_message_convention", "large_commit_share")

_scheduler = None


def schedule_analysis(project_id: int) -> None:
    """Analizi arka planda (APScheduler date job) başlatır."""
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
    _scheduler.add_job(
        run_project_analysis,
        args=[project_id],
        id=f"analyze-{project_id}",
        replace_existing=True,
        misfire_grace_time=3600,
    )


def _build_provider(project: UserProject, token: str) -> GitProvider:
    """source_url + source_type'tan provider kurar. Token URL'ye girmez."""
    parsed = urlparse(project.source_url)
    path = parsed.path.strip("/").removesuffix(".git")
    if project.source_type == "github":
        api_base = (
            "https://api.github.com"
            if parsed.hostname in (None, "github.com", "www.github.com")
            else f"{parsed.scheme}://{parsed.netloc}/api/v3"
        )
        return GitHubProvider(api_base, path, token, repo_name=project.project_name)
    if project.source_type == "gitlab":
        return GitLabProvider(
            f"{parsed.scheme}://{parsed.netloc}", token_env="", projects=[path],
            token=token,
        )
    raise ValueError(f"'{project.source_type}' kaynağından analiz henüz desteklenmiyor")


def _commit_hygiene(session: Session, project: UserProject, repo: Repo) -> dict:
    """Commit kalite sinyalleri — PROJE hijyeni olarak MetricResult'a yazılır.
    Kişi bazlı hiçbir skor üretilmez. Eksik alan = düşük completeness."""
    commits = session.scalars(select(Commit).where(Commit.repo_id == repo.id)).all()
    now = datetime.now(timezone.utc)
    period = f"analysis/{project.id}"
    results = {}

    def upsert(key: str, value: float | None, completeness: float) -> None:
        session.execute(
            delete(MetricResult).where(
                MetricResult.scope == "project",
                MetricResult.scope_id == project.id,
                MetricResult.metric_key == key,
            )
        )
        session.add(
            MetricResult(
                scope="project", scope_id=project.id, metric_key=key,
                period=period, value=value, data_completeness=completeness,
                source_layer="git", computed_at=now,
            )
        )
        results[key] = {"value": value, "completeness": completeness}

    total = len(commits)
    with_msg = [c for c in commits if c.message]
    upsert(
        "commit_message_convention",
        (sum(1 for c in with_msg if CONVENTIONAL_RE.match(c.message)) / len(with_msg))
        if with_msg else None,  # hiç mesaj yoksa değer UYDURULMAZ
        (len(with_msg) / total) if total else 0.0,
    )
    with_files = [c for c in commits if c.changed_files is not None]
    upsert(
        "large_commit_share",
        (sum(1 for c in with_files if len(c.changed_files) >= LARGE_COMMIT_FILES)
         / len(with_files)) if with_files else None,
        (len(with_files) / total) if total else 0.0,
    )
    session.flush()
    return results


def run_project_analysis(project_id: int) -> None:
    """Arka plan işi: kendi session'ını açar; hata durumunda status=error,
    uygulama çökmez, token hiçbir çıktıya yazılmaz."""
    session = get_sessionmaker()()
    try:
        project = session.get(UserProject, project_id)
        if project is None:
            return
        project.last_status = "running"
        session.commit()
        try:
            detail = _analyze(session, project)
            project.last_status = "ok"
            project.last_detail = json.dumps(detail, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 — arka plan işi yutar, loglar
            session.rollback()
            project = session.get(UserProject, project_id)
            project.last_status = "error"
            project.last_detail = str(exc)[:500]
            logger.warning("Proje %s analizi başarısız: %s", project_id, exc)
        project.last_run_at = datetime.now(timezone.utc)
        session.commit()
    finally:
        session.close()


def _analyze(session: Session, project: UserProject) -> dict:
    if project.credential is None:
        raise ValueError("Projeye bağlı credential yok")
    token = decrypt_secret(project.credential.encrypted_value)
    if token is None:
        raise ValueError("Credential çözülemedi (ENCRYPTION_KEY değişmiş olabilir)")
    provider = _build_provider(project, token)

    cfg = get_config()
    ing = Ingestor(session)
    commit_count = ing.ingest_commits(provider.fetch_commits())
    pr_count = ing.ingest_pull_requests(provider.fetch_pull_requests())

    # Repo'yu projeye bağla (ingest oluşturdu/buldu) — veri adası yok
    repo = session.scalar(select(Repo).where(Repo.name == project.project_name))
    if repo is not None:
        project.repo_id = repo.id

    # Mevcut motorlar: takım metrikleri + kurallar (takıma bağlı repo'lar için)
    compute_all(session, cfg)
    run_rules(session, cfg)

    hygiene = _commit_hygiene(session, project, repo) if repo else {}
    session.commit()
    return {"new_commits": commit_count, "new_prs": pr_count, "hygiene": hygiene}
