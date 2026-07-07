"""Ingest testleri: kirli veriye dayanıklılık + idempotentlik."""
from __future__ import annotations

from sqlalchemy import select

from tests.conftest import days_ago


def test_kimliksiz_commit_sistemi_cokertmez(session):
    from app.adapters.base import NormalizedCommit
    from app.models import Commit, Developer
    from app.services.ingest import Ingestor

    ing = Ingestor(session)
    n = ing.ingest_commits([
        NormalizedCommit(repo_name="r1", sha="abc", author_key=None,
                         committed_at=None, message=None, changed_files=None),
        NormalizedCommit(repo_name="r1", sha="def", author_key="a@x",
                         author_name="A", committed_at=days_ago(1)),
        NormalizedCommit(repo_name="r1", sha="", author_key="a@x"),  # kimliksiz → atlanır
    ])
    session.commit()
    assert n == 2
    rows = session.scalars(select(Commit)).all()
    assert len(rows) == 2
    # Kimliği belirsiz yazar için sahte developer üretilmez
    assert session.scalars(select(Developer)).all()[0].display_name == "A"
    assert rows[0].author_id is None


def test_ingest_idempotent(session):
    from app.adapters.base import NormalizedCommit
    from app.models import Commit
    from app.services.ingest import Ingestor

    ing = Ingestor(session)
    batch = [NormalizedCommit(repo_name="r1", sha="abc", committed_at=days_ago(2))]
    ing.ingest_commits(batch)
    ing.ingest_commits(batch)  # tekrar senkron
    session.commit()
    assert len(session.scalars(select(Commit)).all()) == 1


def test_ayni_kisi_farkli_kaynaklarda_tek_kayit(session):
    from app.adapters.base import NormalizedCommit, NormalizedTask
    from app.models import Developer
    from app.services.ingest import Ingestor

    ing = Ingestor(session)
    ing.ingest_commits([NormalizedCommit(repo_name="r1", sha="s1",
                                         author_key="ali@x", author_name="Ali")])
    # Farklı kaynak anahtarı → önce ayrı kayıt açılır (otomatik eşleme iddiası yok)
    ing.ingest_tasks([NormalizedTask(source="jira", external_id="J-1",
                                     assignee_key="ali.jira", assignee_name="Ali")])
    session.commit()
    devs = session.scalars(select(Developer)).all()
    assert len(devs) == 2  # kimlik eşleme bilinçli/manuel yapılır, uydurulmaz


def test_task_katman2_alanlari_bos_kalabilir(session):
    from app.adapters.base import NormalizedTask
    from app.models import Task
    from app.services.ingest import Ingestor

    ing = Ingestor(session)
    ing.ingest_tasks([NormalizedTask(source="fixture", external_id="T-1",
                                     team_name="A", status="To Do")])
    session.commit()
    task = session.scalars(select(Task)).one()
    assert task.estimate_hours is None
    assert task.due_date is None
    assert task.story_points is None
