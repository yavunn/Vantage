"""Faz 4 — analiz motoru testleri.

- Analiz veriyi MEVCUT normalize modele (Commit) yazar, repo'yu projeye bağlar.
- Eksik alanlı commit'te skor uydurulmaz; completeness düşer.
- analyze ucu: kimliksiz 401, başkasının projesi 404, sahibi 202.
- Decrypt hatası: status=error, uygulama çökmez, token sızmaz.
- Etik: hijyen sinyalleri proje kapsamındadır, kişi bazlı skor yazılmaz.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tests.test_auth import login, make_user
from tests.test_projects import PLAIN_TOKEN, create_project, user_headers


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


class FakeGitProvider:
    """Sahte kaynak: 3 konvansiyonel + 1 mesajsız + 1 konvansiyonsuz commit."""

    def __init__(self, repo_name="repo-a"):
        from app.adapters.base import NormalizedCommit

        now = datetime.now(timezone.utc)
        self.commits = [
            NormalizedCommit(repo_name=repo_name, sha=f"aaa{i}", author_key="a@x",
                             author_name="A", committed_at=now - timedelta(days=i),
                             message=msg, changed_files=files)
            for i, (msg, files) in enumerate([
                ("feat: giriş", ["a.py"]),
                ("fix(api): düzeltme", ["b.py"]),
                ("chore: temizlik", ["c.py"]),
                (None, None),                      # KİRLİLİK: mesaj/dosya yok
                ("düzenleme yapıldı", [f"f{n}.py" for n in range(12)]),  # geniş
            ])
        ]

    def fetch_commits(self, since=None):
        return self.commits

    def fetch_pull_requests(self, since=None):
        return []


def setup_project(client, session, monkeypatch):
    from app.services import analysis

    headers = user_headers(client, session)
    project_id = create_project(client, headers).json()["id"]
    monkeypatch.setattr(analysis, "_build_provider", lambda p, t: FakeGitProvider())
    return headers, project_id


def test_analiz_mevcut_modele_yazar_ve_repo_baglar(client, session, monkeypatch):
    from sqlalchemy import select

    from app.models import Commit, UserProject
    from app.services.analysis import run_project_analysis

    headers, project_id = setup_project(client, session, monkeypatch)
    run_project_analysis(project_id)

    session.expire_all()
    project = session.get(UserProject, project_id)
    assert project.last_status == "ok"
    assert project.last_run_at is not None
    assert project.repo_id is not None  # veri adası yok: Repo'ya bağlandı
    commits = session.scalars(
        select(Commit).where(Commit.repo_id == project.repo_id)
    ).all()
    assert len(commits) == 5


def test_hijyen_proje_kapsaminda_eksik_veri_uydurulmaz(client, session, monkeypatch):
    from sqlalchemy import select

    from app.models import MetricResult
    from app.services.analysis import run_project_analysis

    headers, project_id = setup_project(client, session, monkeypatch)
    run_project_analysis(project_id)

    session.expire_all()
    rows = session.scalars(
        select(MetricResult).where(MetricResult.scope == "project")
    ).all()
    by_key = {r.metric_key: r for r in rows}
    # Konvansiyon: 4 mesajlı commit'in 3'ü uygun; 5 commit'in 4'ünde mesaj var
    conv = by_key["commit_message_convention"]
    assert conv.value == pytest.approx(0.75)
    assert conv.data_completeness == pytest.approx(0.8)  # eksik mesaj cezasız, dürüst
    # Geniş commit: dosyası bilinen 4 commit'in 1'i geniş
    large = by_key["large_commit_share"]
    assert large.value == pytest.approx(0.25)
    # Etik: kişi kapsamında hijyen skoru YAZILMAZ
    assert not session.scalars(
        select(MetricResult).where(
            MetricResult.scope == "developer",
            MetricResult.metric_key.in_(list(by_key)),
        )
    ).all()


def test_analysis_ucu_durum_ve_metrik_doner(client, session, monkeypatch):
    from app.services.analysis import run_project_analysis

    headers, project_id = setup_project(client, session, monkeypatch)
    run_project_analysis(project_id)
    body = client.get(f"/api/user/projects/{project_id}/analysis", headers=headers).json()
    assert body["status"] == "ok"
    assert {m["key"] for m in body["metrics"]} == {
        "commit_message_convention", "large_commit_share"
    }
    assert all("status_label" in m for m in body["metrics"])
    commits = client.get(f"/api/user/projects/{project_id}/commits", headers=headers).json()
    assert len(commits) == 5
    assert PLAIN_TOKEN not in str(commits)


def test_analyze_ucu_yetki(client, session, monkeypatch):
    headers, project_id = setup_project(client, session, monkeypatch)
    # Kimliksiz 401
    assert client.post(f"/api/user/projects/{project_id}/analyze").status_code == 401
    # Başkasının projesi 404
    other = user_headers(client, session, "other@corp.local")
    assert client.post(f"/api/user/projects/{project_id}/analyze",
                       headers=other).status_code == 404
    # Sahibi 202 + pending (arka plan işi ayrıca koşar)
    resp = client.post(f"/api/user/projects/{project_id}/analyze", headers=headers)
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"


def test_decrypt_hatasi_status_error_token_sizmaz(client, session, monkeypatch):
    from sqlalchemy import select

    from app.models import ProjectCredential, UserProject
    from app.services.analysis import run_project_analysis

    headers, project_id = setup_project(client, session, monkeypatch)
    cred = session.scalars(select(ProjectCredential)).first()
    cred.encrypted_value = "bozuk-veri"
    session.commit()

    run_project_analysis(project_id)  # exception fırlatmamalı
    session.expire_all()
    project = session.get(UserProject, project_id)
    assert project.last_status == "error"
    assert PLAIN_TOKEN not in (project.last_detail or "")
