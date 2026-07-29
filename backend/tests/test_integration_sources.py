"""Entegrasyon paneli: kaynak eşlemesi + sessiz başarısızlığın görünür olması.

İki ilke burada zorlanır:
1. Okunamayan kaynak (ölü Trello board'u, bozuk repo yolu) SESSİZCE atlanmaz —
   senkron sonucu sebebi söyler. Aksi hâlde entegrasyon çalışıyor sanılır.
2. Repo→takım eşlemesi paneldan yönetilir ve DEĞİŞTİRİLEBİLİR. Takımsız repo'nun
   commitleri hiçbir takım metriğine giremez; bu yüzden hem uyarılır hem düzeltilir.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import days_ago

# --- Sahte HTTP katmanı (Trello ağa çıkmadan test edilir) ---------------------

class _FakeResp:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakeClient:
    """Tanımlı olmayan her yol 404 döner — 'board yok' senaryosu."""

    def __init__(self, routes: dict):
        self.routes = routes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        return self.routes.get(url, _FakeResp(404, {"message": "Board not found"}))


# --- Adaptör uyarıları --------------------------------------------------------

def test_trello_olu_board_sessizce_atlanmaz(monkeypatch):
    from app.adapters.trello import TrelloProvider

    p = TrelloProvider("TRELLO_KEY", "TRELLO_TOKEN", ["saglam", "olu"])
    p.key, p.token = "k", "t"  # ortam değişkenine bağlı kalmasın
    routes = {
        "/boards/saglam": _FakeResp(200, {"name": "Takım Panosu"}),
        "/boards/saglam/cards": _FakeResp(200, []),
        "/boards/saglam/lists": _FakeResp(200, []),
        # "/boards/olu" YOK → 404
    }
    monkeypatch.setattr(p, "_client", lambda: _FakeClient(routes))

    assert p.fetch_tasks() == []
    # Sağlam board sorun çıkarmaz; ölü board net sebeple raporlanır.
    assert len(p.warnings) == 1
    assert "olu" in p.warnings[0]
    assert "404" in p.warnings[0]


def test_trello_tokensiz_calisamadigini_soyler(monkeypatch):
    from app.adapters.trello import TrelloProvider

    p = TrelloProvider("YOK_KEY", "YOK_TOKEN", ["b1"])
    p.key, p.token = "", ""
    monkeypatch.setattr(p, "_client", lambda: _FakeClient({}))

    assert p.fetch_tasks() == []
    assert any("key/token" in w for w in p.warnings)


def test_git_log_bozuk_repo_yolu_uyari_uretir(tmp_path):
    from app.adapters.git_log import GitLogProvider

    p = GitLogProvider([{"name": "hayalet", "path": str(tmp_path / "olmayan-dizin")}])

    assert p.fetch_commits() == []
    assert len(p.warnings) == 1
    assert "hayalet" in p.warnings[0]


def test_run_ingest_saglayici_uyarilarini_tasir(session):
    from app.services.ingest import run_ingest

    class _Git:
        warnings = ["repo okunamadı"]

        def fetch_commits(self, since=None):
            return []

        def fetch_pull_requests(self, since=None):
            return []

    class _Tasks:
        warnings = ["board okunamadı"]

        def fetch_tasks(self, since=None):
            return []

    stats = run_ingest(session, _Git(), _Tasks())
    assert stats["warnings"] == ["repo okunamadı", "board okunamadı"]
    # Sayılar da korunur (yeni kayıt yok)
    assert stats["commits"] == 0 and stats["tasks"] == 0


# --- Repo → takım eşlemesi ----------------------------------------------------

def test_repo_takimi_degistirilince_db_guncellenir(session):
    """Panelden takım değiştirilebildiği için ingest yeniden atamayı UYGULAMALI.
    Yalnız None'ı doldurmak, değişikliği sessizce yutardı."""
    from app.adapters.base import NormalizedCommit
    from app.models import Repo, Team
    from app.services.ingest import Ingestor

    batch = [NormalizedCommit(repo_name="r1", sha="abc", committed_at=days_ago(1))]

    Ingestor(session, repo_team_map={"r1": "A takımı"}).ingest_commits(batch)
    session.commit()
    repo = session.scalar(select(Repo).where(Repo.name == "r1"))
    assert repo.team_id == session.scalar(select(Team).where(Team.name == "A takımı")).id

    # Yönetici panelden takımı değiştirdi → senkron DB'yi düzeltir
    Ingestor(session, repo_team_map={"r1": "B takımı"}).ingest_commits(batch)
    session.commit()
    session.refresh(repo)
    assert repo.team_id == session.scalar(select(Team).where(Team.name == "B takımı")).id


def test_takimsiz_repo_senkronda_uyari_uretir(session, monkeypatch):
    """Bu uyarı olmadan pano 'veri yetersiz' gösterir ve sebebi görünmez."""
    _set_git_repos([{"name": "nabiz", "path": "/tmp/yok"}])
    monkeypatch.setattr("app.services.pipeline.get_sessionmaker", lambda: lambda: session)
    from app.services.pipeline import run_pipeline

    stats = run_pipeline()
    assert any("hiçbir takıma bağlı değil" in w for w in stats["warnings"])

    # Takım atanınca uyarı kaybolur
    _set_git_repos([{"name": "nabiz", "path": "/tmp/yok", "team": "Takım A"}])
    stats = run_pipeline()
    assert not any("hiçbir takıma bağlı değil" in w for w in stats["warnings"])


# --- API uçları ---------------------------------------------------------------

@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _set_git_repos(repos: list[dict]) -> None:
    """Test config'ine repo listesi yazar (PUT repo eklemez, yalnız eşler)."""
    from app.core.config import active_config_path, reset_config_cache

    path = active_config_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw.setdefault("sources", {})["git"] = {"provider": "git_log", "repos": repos}
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    reset_config_cache()


def _admin_token(client, session) -> str:
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    session.add(User(
        email="admin@x.com", password_hash=hash_password("parola1"), role="admin",
        is_active=True, must_change_password=False, created_at=now, updated_at=now,
    ))
    session.commit()
    r = client.post("/api/auth/login", json={"email": "admin@x.com", "password": "parola1"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_sources_ucu_repolari_takimlariyla_dondurur(client, session):
    from app.models import Team

    session.add(Team(name="Takım A"))
    session.commit()
    _set_git_repos([{"name": "nabiz", "path": "/repo/nabiz"}])
    token = _admin_token(client, session)

    body = client.get("/api/admin/sources", headers={"Authorization": f"Bearer {token}"}).json()

    # Panel "repo sayısı: 1" yerine hangi repo, nereye bağlı gösterebilmeli
    assert body["git"]["repos"] == [
        {"name": "nabiz", "path": "/repo/nabiz", "team": None, "commit_count": 0}
    ]
    # Takım seçimi için liste aynı yanıtta gelir (ikinci istek gerekmez)
    assert [t["name"] for t in body["teams"]] == ["Takım A"]


def test_repo_takim_eslemesi_config_e_yazilir(client, session):
    from app.core.config import get_config, reset_config_cache

    _set_git_repos([{"name": "nabiz", "path": "/repo/nabiz"}])
    token = _admin_token(client, session)
    auth = {"Authorization": f"Bearer {token}"}

    r = client.put("/api/admin/sources", json={"repo_teams": {"nabiz": "Takım A"}}, headers=auth)
    assert r.status_code == 200, r.text
    reset_config_cache()
    assert get_config().sources.git.repos[0]["team"] == "Takım A"

    # Boş değer eşlemeyi kaldırır (takım yok'a dönüş)
    r = client.put("/api/admin/sources", json={"repo_teams": {"nabiz": ""}}, headers=auth)
    assert r.status_code == 200, r.text
    reset_config_cache()
    assert "team" not in get_config().sources.git.repos[0]


def test_sources_test_ucu_okunamayan_kaynagi_raporlar(client, session):
    """Kuru çalıştırma: senkron beklemeden bozuk ayarı yüzeye çıkarır, DB'ye yazmaz."""
    from app.models import Commit

    _set_git_repos([{"name": "hayalet", "path": "/kesinlikle/olmayan/yol"}])
    token = _admin_token(client, session)

    r = client.post("/api/admin/sources/test", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["ok"] is False
    assert any("hayalet" in w for w in body["git"]["warnings"])
    assert body["unmapped_repos"] == ["hayalet"]
    # Kuru çalıştırma DB'ye dokunmaz
    assert session.scalars(select(Commit)).all() == []


def test_sources_test_ucu_admin_disina_kapali(client, session):
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    session.add(User(
        email="calisan@x.com", password_hash=hash_password("parola1"), role="user",
        is_active=True, must_change_password=False, created_at=now, updated_at=now,
    ))
    session.commit()
    t = client.post(
        "/api/auth/login", json={"email": "calisan@x.com", "password": "parola1"}
    ).json()["access_token"]

    r = client.post("/api/admin/sources/test", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 403
