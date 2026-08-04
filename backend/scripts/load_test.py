"""Gerçekçi hacimde yük üretir ve ölçer (İŞ-26).

NEDEN: sistem bugün 51 commit / 26 task / 72 chunk ile çalışıyor. Ölçek
iddialarının hiçbiri gerçek hacimde ÖLÇÜLMEMİŞTİ (PROJE_DENETIM bölüm 5 de
"performans ölçülmedi" diyor). İŞ-22 (SQL pencere filtresi) ve İŞ-24 (RAG
indeks ölçeği) bu ölçüm olmadan doğrulanamaz.

ÜRETİM VERİTABANINA YAZMAZ: kendi geçici SQLite dosyasını kurar, ölçer, siler.
Komut:
    .venv\\Scripts\\python scripts\\load_test.py [commit_sayisi] [task_sayisi]

HEDEFLER (ölçümden ÖNCE yazıldı, sonuçlar bunlarla karşılaştırılır):
  - compute_all (2 takım, 30 gün + 5 haftalık kova): < 30 sn
  - takım özeti sorgusu (metric_results okuma):     < 1 sn
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HEDEF_COMPUTE_ALL_SN = 30.0
HEDEF_OZET_SN = 1.0

DOSYALAR = [f"app/modul_{i}/servis_{j}.py" for i in range(20) for j in range(10)]
MESAJLAR = [
    "feat: yeni akış", "fix: kenar durumu", "refactor: sadeleştirme",
    "Merge branch 'feature/x'", "hotfix: acil düzeltme", "docs: not",
]
STATULER = ["BACKLOG", "DEVELOPMENT", "TEST", "DONE"]


def veri_uret(session, commit_sayisi: int, task_sayisi: int, takim_sayisi: int = 2):
    from app.models import Commit, Developer, Repo, Task, TaskStatusTransition, Team, TeamMembership

    rnd = random.Random(42)  # tekrarlanabilir
    now = datetime.now(timezone.utc)
    takimlar, repolar = [], []
    for t in range(takim_sayisi):
        team = Team(name=f"Takım {t}")
        session.add(team)
        session.flush()
        repo = Repo(name=f"repo-{t}", team_id=team.id)
        session.add(repo)
        session.flush()
        takimlar.append(team)
        repolar.append(repo)
        for d in range(8):
            dev = Developer(external_ids={"git": f"dev{t}_{d}@sirket.com"},
                            display_name=f"Dev {t}.{d}")
            session.add(dev)
            session.flush()
            session.add(TeamMembership(team_id=team.id, developer_id=dev.id, role="member"))
    session.commit()

    devs = {r.id: [] for r in repolar}
    from sqlalchemy import select
    tum_devs = list(session.scalars(select(Developer)))
    for r in repolar:
        devs[r.id] = tum_devs

    # Commit'ler — kirli veri oranları seed_dirty_data desenine yakın:
    # %5 tarihsiz, %10 kimliksiz, %8 dosya listesi yok.
    toplu = []
    for i in range(commit_sayisi):
        repo = repolar[i % len(repolar)]
        tarih = None if rnd.random() < 0.05 else now - timedelta(
            days=rnd.uniform(0, 365), hours=rnd.uniform(0, 24)
        )
        yazar = None if rnd.random() < 0.10 else rnd.choice(devs[repo.id])
        dosyalar = None if rnd.random() < 0.08 else rnd.sample(DOSYALAR, rnd.randint(1, 6))
        toplu.append(Commit(
            repo_id=repo.id, sha=f"sha{i:08d}",
            author_id=yazar.id if yazar else None,
            committed_at=tarih, message=rnd.choice(MESAJLAR),
            changed_files=dosyalar,
            additions=rnd.randint(0, 400), deletions=rnd.randint(0, 200),
        ))
        if len(toplu) >= 5000:
            session.bulk_save_objects(toplu)
            session.commit()
            toplu = []
    if toplu:
        session.bulk_save_objects(toplu)
        session.commit()

    # Task'lar + geçişler
    for i in range(task_sayisi):
        team = takimlar[i % len(takimlar)]
        t = Task(source="trello", external_id=f"card-{i}", team_id=team.id,
                 title=f"İş {i}", status=rnd.choice(STATULER),
                 created_at=now - timedelta(days=rnd.uniform(0, 180)))
        session.add(t)
        session.flush()
        an = t.created_at
        for st in ("DEVELOPMENT", "DONE"):
            an = an + timedelta(days=rnd.uniform(0.5, 10))
            session.add(TaskStatusTransition(task_id=t.id, from_status=None,
                                             to_status=st, changed_at=an))
        if i % 1000 == 0:
            session.commit()
    session.commit()


def main() -> None:
    commit_sayisi = int(sys.argv[1]) if len(sys.argv) > 1 else 50_000
    task_sayisi = int(sys.argv[2]) if len(sys.argv) > 2 else 5_000

    db = Path(tempfile.mkdtemp(prefix="vantage-yuk-")) / "yuk.db"
    cfg = db.parent / "config.yaml"
    cfg.write_text(
        f"app: {{window_days: 30, bucket_days: 7}}\n"
        f'database: {{url: "sqlite:///{db.as_posix()}"}}\n'
        "sync: {interval_minutes: 0}\n"
        "llm: {enabled: false}\n"
        "rag: {enabled: false}\n"
        # Metrikler AÇIK olmalı: kapalıyken compute_all hiçbir şey hesaplamaz ve
        # ölçüm "0.13 sn" gibi anlamsız bir sonuç verir.
        "metrics:\n"
        "  cycle_time: {enabled: true, source: jira_status, fallback: pr_merge}\n"
        "  pr_review_time: {enabled: true}\n"
        "  review_latency: {enabled: true}\n"
        "  deployment_frequency: {enabled: true, deploy_signal: merge}\n"
        "  change_failure_rate: {enabled: true, hotfix_window_days: 3}\n"
        "  mttr: {enabled: true, source: jira_incident, fallback: git_revert}\n"
        "  wip: {enabled: true}\n"
        "  rework: {enabled: true, window_days: 21}\n"
        "  process_hygiene: {enabled: true}\n",
        encoding="utf-8",
    )
    # ÜRETİM VERİTABANINA DOKUNMA: config ve DATABASE_URL geçici dizine sabitlenir.
    os.environ["VANTAGE_CONFIG"] = str(cfg)
    os.environ["DATABASE_URL"] = f"sqlite:///{db.as_posix()}"

    from sqlalchemy import func, select

    import app.models  # noqa: F401
    from app.core.config import get_config, reset_config_cache
    from app.core.db import Base, get_engine, get_sessionmaker, reset_engine
    from app.metrics.engine import compute_all
    from app.models import Commit, MetricResult, Task

    reset_config_cache()
    reset_engine()
    Base.metadata.create_all(get_engine())
    session = get_sessionmaker()()

    print(f"Yük üretiliyor: {commit_sayisi} commit, {task_sayisi} task…")
    t0 = time.perf_counter()
    veri_uret(session, commit_sayisi, task_sayisi)
    print(f"  üretim süresi: {time.perf_counter() - t0:.1f} sn")
    print(f"  commits={session.scalar(select(func.count()).select_from(Commit))} "
          f"tasks={session.scalar(select(func.count()).select_from(Task))}")

    cfg_obj = get_config()
    print("\nÖLÇÜM")

    # Senkronun YAZMA yarısı: adaptörden gelen normalize kayıtların DB'ye
    # işlenmesi. Ağ süresi ölçülmez (dış API'ye bağlı ve bu makinede anlamsız);
    # ölçülen, hacim büyüdükçe bizim kontrolümüzde olan kısımdır.
    from app.adapters.base import NormalizedCommit
    from app.services.ingest import Ingestor

    ing = Ingestor(session)
    yeni = [
        NormalizedCommit(
            repo_name="repo-0", sha=f"yeni{i:07d}", author_key="dev0_0@sirket.com",
            author_name="Dev", committed_at=datetime.now(timezone.utc),
            message="feat: yük", changed_files=["a.py"], additions=1, deletions=0,
        )
        for i in range(2_000)
    ]
    t0 = time.perf_counter()
    ing.ingest_commits(yeni)
    session.commit()
    ingest_sn = time.perf_counter() - t0
    print(f"  ingest (2.000 commit)  : {ingest_sn:8.2f} sn "
          f"({2_000 / max(ingest_sn, 1e-9):,.0f} kayıt/sn)")
    t0 = time.perf_counter()
    yazilan = compute_all(session, cfg_obj)
    compute_sn = time.perf_counter() - t0
    print(f"  compute_all           : {compute_sn:8.2f} sn  ({yazilan} metrik satırı) "
          f"[hedef < {HEDEF_COMPUTE_ALL_SN} sn] {'OK' if compute_sn < HEDEF_COMPUTE_ALL_SN else 'HEDEF AŞILDI'}")

    # ÖNCE/SONRA: İŞ-22 öncesi load_team_data takımın TÜM commit'lerini belleğe
    # alıp Python'da filtreliyordu ve bunu iki kez yapıyordu (pencere + geriye/
    # ileriye bakış), compute_all da bunu takım başına 6 kez çağırıyordu.
    # Aşağıda o desenin ham maliyeti ölçülür (kod geri alınmadan, dürüst kıyas).
    from app.metrics.engine import as_utc
    from app.models import Repo

    repo_ids = [r.id for r in session.scalars(select(Repo))]
    now_ = datetime.now(timezone.utc)
    pencere_basi = now_ - timedelta(days=30)
    t0 = time.perf_counter()
    for _ in range(12):   # 2 takım × 6 pencere
        _ = [
            c for c in session.scalars(select(Commit).where(Commit.repo_id.in_(repo_ids)))
            if (ts := as_utc(c.committed_at)) is None or pencere_basi <= ts <= now_
        ]
    eski_sn = time.perf_counter() - t0
    print(f"  [kıyas] eski tam tarama : {eski_sn:8.2f} sn  (12 kez tüm commit tablosu)")

    t0 = time.perf_counter()
    rows = session.scalars(
        select(MetricResult).where(MetricResult.scope == "team", MetricResult.scope_id == 1)
    ).all()
    ozet_sn = time.perf_counter() - t0
    print(f"  takım özeti sorgusu   : {ozet_sn:8.4f} sn  ({len(rows)} satır) "
          f"[hedef < {HEDEF_OZET_SN} sn] {'OK' if ozet_sn < HEDEF_OZET_SN else 'HEDEF AŞILDI'}")

    session.close()
    reset_engine()
    # Geçici veritabanı silinir — üretim verisi hiç etkilenmedi.
    try:
        db.unlink(missing_ok=True)
        cfg.unlink(missing_ok=True)
        db.parent.rmdir()
        print(f"\nGeçici veritabanı silindi: {db}")
    except OSError as e:
        print(f"\nGeçici dosya silinemedi ({e}) — yol: {db.parent}")


if __name__ == "__main__":
    main()
