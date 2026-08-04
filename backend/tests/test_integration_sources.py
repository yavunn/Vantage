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
    def __init__(self, status_code: int, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        # GitLab sayfalaması x-next-page başlığına bakar; boş sözlük "son sayfa".
        self.headers = headers or {}

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
        # Kart hareketleri artık board seviyesinde TEK istekle çekiliyor
        # (kart başına istek oran sınırına takılıp veriyi sessizce kaybediyordu).
        "/boards/saglam/actions": _FakeResp(200, []),
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


def test_gitlab_hedefleri_ortak_repo_listesinden_okunur(monkeypatch):
    """Hedefler ayrı bir `gitlab.projects` listesinde yaşarsa repo→takım eşlemesi
    (repo ADIYLA yapılır) tutmaz ve commitler hiçbir metriğe giremez. Bu yüzden
    GitLab da github ile aynı `repos` girdilerini okur; normalize kayda giden ad
    config'teki `name`'dir, API'ye giden yol `slug`'tır."""
    from app.adapters.gitlab import GitLabProvider

    p = GitLabProvider("https://gitlab.local", "GL_TOKEN", [], repos=[
        {"name": "vantage", "slug": "platform/vantage", "team": "Takım A"},
        # Tam URL ve iç içe grup da kabul edilmeli
        {"name": "mobil", "slug": "https://gitlab.local/mobil/ios/uygulama.git"},
    ])
    p.token = "t"
    routes = {
        "/projects/platform%2Fvantage/repository/commits": _FakeResp(200, [
            {"id": "abc", "author_email": "a@x.com", "author_name": "A",
             "committed_date": "2026-01-01T10:00:00Z", "title": "iş",
             "stats": {"additions": 3, "deletions": 1}},
        ]),
        "/projects/mobil%2Fios%2Fuygulama/repository/commits": _FakeResp(200, []),
    }
    monkeypatch.setattr(p, "_client", lambda: _FakeClient(routes))

    commits = p.fetch_commits()
    assert [c.repo_name for c in commits] == ["vantage"]  # config'teki ad, yol değil
    assert p.warnings == []


def test_gitlab_okunamayan_proje_ve_bos_liste_sessiz_kalmaz(monkeypatch):
    from app.adapters.gitlab import GitLabProvider

    p = GitLabProvider("https://gitlab.local", "GL_TOKEN", [],
                       repos=[{"name": "yok", "slug": "grup/yok"}])
    p.token = "t"
    monkeypatch.setattr(p, "_client", lambda: _FakeClient({}))  # her yol 404
    assert p.fetch_commits() == []
    assert any("bulunamadı" in w and "yok" in w for w in p.warnings)

    # Adres tanımsızsa hiç istek atılmaz ama sebep söylenir
    p2 = GitLabProvider("", "GL_TOKEN", [], repos=[{"name": "x", "slug": "g/x"}])
    assert p2.fetch_commits() == []
    assert any("base_url" in w for w in p2.warnings)

    # Hedef yoksa: boş liste uyarısı
    p3 = GitLabProvider("https://gitlab.local", "GL_TOKEN", [], repos=[])
    p3.token = "t"
    assert p3.fetch_commits() == []
    assert any("liste" in w for w in p3.warnings)


def test_gitlab_eski_projects_listesine_dusulur():
    """Kurulu sistemlerde hedefler `gitlab.projects` içinde olabilir; repos boşsa
    o liste kullanılmaya devam eder (geriye dönük uyum)."""
    from app.adapters.gitlab import GitLabProvider

    p = GitLabProvider("https://gitlab.local", "GL_TOKEN", ["grup/eski"], repos=[])
    p.token = "t"
    assert p._hedefler() == [("grup/eski", "grup/eski")]


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
    _set_git_repos([{"name": "vantage", "path": "/tmp/yok"}])
    monkeypatch.setattr("app.services.pipeline.get_sessionmaker", lambda: lambda: session)
    from app.services.pipeline import run_pipeline

    stats = run_pipeline()
    assert any("hiçbir takıma bağlı değil" in w for w in stats["warnings"])

    # Takım atanınca uyarı kaybolur
    _set_git_repos([{"name": "vantage", "path": "/tmp/yok", "team": "Takım A"}])
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
    _set_git_repos([{"name": "vantage", "path": "/repo/vantage"}])
    token = _admin_token(client, session)

    body = client.get("/api/admin/sources", headers={"Authorization": f"Bearer {token}"}).json()

    # Panel "repo sayısı: 1" yerine hangi repo, nereye bağlı gösterebilmeli.
    # slug: github sağlayıcısının owner/repo alanı — git_log girdisinde boş.
    assert body["git"]["repos"] == [
        {"name": "vantage", "path": "/repo/vantage", "slug": None,
         "team": None, "commit_count": 0}
    ]
    # Takım seçimi için liste aynı yanıtta gelir (ikinci istek gerekmez)
    assert [t["name"] for t in body["teams"]] == ["Takım A"]


def test_repo_takim_eslemesi_config_e_yazilir(client, session):
    from app.core.config import get_config, reset_config_cache

    _set_git_repos([{"name": "vantage", "path": "/repo/vantage"}])
    token = _admin_token(client, session)
    auth = {"Authorization": f"Bearer {token}"}

    r = client.put("/api/admin/sources", json={"repo_teams": {"vantage": "Takım A"}}, headers=auth)
    assert r.status_code == 200, r.text
    reset_config_cache()
    assert get_config().sources.git.repos[0]["team"] == "Takım A"

    # Boş değer eşlemeyi kaldırır (takım yok'a dönüş)
    r = client.put("/api/admin/sources", json={"repo_teams": {"vantage": ""}}, headers=auth)
    assert r.status_code == 200, r.text
    reset_config_cache()
    assert "team" not in get_config().sources.git.repos[0]


def test_gitlab_ve_jira_panelden_uctan_uca_ayarlanir(client, session, monkeypatch):
    """Kaynak bağlamak için sunucuya girip YAML düzenlemek gerekmemeli.

    Sır (token) config'e yazılmaz, .secrets.env + ortama gider; env değişkeninin
    ADI config'ten okunur, sabit değil."""
    from app.core.config import active_config_path, get_config, reset_config_cache

    yazilan: dict[str, str] = {}
    monkeypatch.setattr("app.core.secrets.set_secret",
                        lambda ad, deger: yazilan.__setitem__(ad, deger))

    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}
    r = client.put("/api/admin/sources", json={
        "git_provider": "gitlab",
        "gitlab_base_url": "https://gitlab.sirket.local",
        "gitlab_token": "glpat-xyz",
        "repos": [{"name": "vantage", "path": "", "slug": "platform/vantage",
                   "team": "Takım A"}],
        "tasks_provider": "jira",
        "jira_base_url": "https://jira.sirket.local",
        "jira_projects": ["ENG", " OPS ", ""],
        "jira_token": "jira-pat",
    }, headers=auth)
    assert r.status_code == 200, r.text

    reset_config_cache()
    cfg = get_config()
    assert cfg.sources.git.provider == "gitlab"
    assert cfg.sources.git.gitlab.base_url == "https://gitlab.sirket.local"
    assert cfg.sources.git.repos[0]["slug"] == "platform/vantage"
    assert cfg.sources.tasks.jira.projects == ["ENG", "OPS"]  # boş/boşluk temizlenir

    # Token'lar config'e SIZMAZ, sır olarak yazılır (env adı config'ten).
    assert yazilan == {"GITLAB_TOKEN": "glpat-xyz", "JIRA_TOKEN": "jira-pat"}
    ham = yaml.safe_load(active_config_path().read_text(encoding="utf-8"))
    assert "glpat-xyz" not in yaml.safe_dump(ham)
    assert "jira-pat" not in yaml.safe_dump(ham)

    # GET, panelin doldurabilmesi için proje listelerini geri verir.
    body = client.get("/api/admin/sources", headers=auth).json()
    assert body["tasks"]["jira_projects"] == ["ENG", "OPS"]
    assert body["git"]["gitlab_projects"] == []


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


# --- İŞ-12: arşivli kartlar ---------------------------------------------------
# Gerçek board üzerinde ölçüldü: varsayılan kart çağrısı 19, filter=all 21 kart
# döndürüyordu — 2 arşivli kart HİÇ çekilmiyordu. Arşivlenen kart çoğu zaman
# BİTMİŞ iştir; takım kartlarını ne kadar düzenli arşivlerse cycle time ve
# teslim sinyali o kadar çok kayboluyordu.

def test_trello_arsivli_kartlar_da_cekilir(monkeypatch):
    from app.adapters.trello import TrelloProvider

    p = TrelloProvider("K", "T", ["b1"])
    p.key, p.token = "k", "t"
    yakalanan: dict = {}

    class _Client(_FakeClient):
        def get(self, url, params=None):
            if url.endswith("/cards"):
                yakalanan["params"] = params
            return super().get(url, params)

    routes = {
        "/boards/b1": _FakeResp(200, {"name": "Pano"}),
        "/boards/b1/lists": _FakeResp(200, [{"id": "l1", "name": "DONE"}]),
        "/boards/b1/members": _FakeResp(200, []),
        "/boards/b1/actions": _FakeResp(200, []),
        "/boards/b1/cards": _FakeResp(200, [
            {"id": "c1", "name": "acik", "idList": "l1", "idShort": 1, "closed": False},
            {"id": "c2", "name": "arsivli", "idList": "l1", "idShort": 2, "closed": True},
        ]),
        "/cards/c1/actions": _FakeResp(200, []),
        "/cards/c2/actions": _FakeResp(200, []),
    }
    monkeypatch.setattr(p, "_client", lambda: _Client(routes))

    tasks = p.fetch_tasks()

    # filter=all gönderilmezse Trello arşivlileri hiç döndürmez.
    assert yakalanan["params"]["filter"] == "all"
    assert {t.external_id: t.archived for t in tasks} == {"c1": False, "c2": True}


def test_arsivli_kart_wipe_sayilmaz(session):
    """Arşivli kart akışta değildir; paydaya da girmez (eksik veri değildir)."""
    from app.metrics.engine import load_team_data, wip
    from app.models import Task
    from tests.conftest import NOW, make_team

    team, repo, devs, _ = make_team(session)  # 2 üye
    session.add(Task(source="trello", external_id="acik", team_id=team.id,
                     status="DEVELOPMENT", archived=False))
    session.add(Task(source="trello", external_id="arsiv", team_id=team.id,
                     status="DEVELOPMENT", archived=True))
    session.commit()

    from datetime import timedelta

    from app.core.config import get_config
    cfg = get_config()
    cfg.sources.tasks.status_mapping.in_progress = ["DEVELOPMENT"]
    data = load_team_data(session, team, NOW - timedelta(days=30), NOW, cfg)
    out = wip(data, cfg)

    assert out.sample == 1          # yalnız açık kart akışta
    assert out.value == 0.5         # 1 iş / 2 üye
    assert out.completeness == 1.0  # arşivli kart tamlığı düşürmez


# --- İŞ-21: /api/sources/test "ok" yalanı -------------------------------------
# Uç, ok'u yalnızca warnings listesinin boşluğuna bakarak veriyordu. Uyarı
# sözleşmesini uygulamayan bir sağlayıcı (eskiden JiraProvider) 401 alsa bile
# ok:true, count:0 diyordu → kullanıcı "bağlantı çalışıyor, henüz kayıt yok"
# sanıyordu. Oysa bu uç tam da yanlış ayarı yüzeye çıkarmak için yazılmıştı.

def test_sifir_kayit_basari_sayilmaz(client, session, monkeypatch):
    """Hata yok + kayıt da yok: bu bir başarı değil, kontrol edilecek bir durum."""
    import app.adapters.factory as factory_mod

    class _BosSaglayici:
        """Uyarı sözleşmesini uygular ama hiç kayıt döndürmez."""

        def __init__(self):
            self.warnings: list[str] = []

        def fetch_commits(self, since=None):
            return []

        def fetch_pull_requests(self, since=None):
            return []

        def fetch_tasks(self, since=None):
            return []

        def fetch_team_members(self):
            return []

    _set_git_repos([{"name": "r", "path": ".", "team": "T"}])
    # Uç sağlayıcıları fabrikadan fonksiyon içinde import ediyor → yama hedefi fabrika.
    monkeypatch.setattr(factory_mod, "build_git_provider", lambda cfg: _BosSaglayici())
    monkeypatch.setattr(factory_mod, "build_task_provider", lambda cfg: _BosSaglayici())
    token = _admin_token(client, session)

    body = client.post("/api/admin/sources/test",
                       headers={"Authorization": f"Bearer {token}"}).json()

    assert body["git"]["ok"] is False
    assert body["tasks"]["ok"] is False
    assert "kayıt gelmedi" in body["tasks"]["detail"]


def test_uyari_desteklemeyen_saglayici_ok_demez(client, session, monkeypatch):
    """Sözleşmesiz sağlayıcıda 'uyarı yok' bilgi değil SESSİZLİKTİR."""
    import app.adapters.factory as factory_mod

    class _Sozlesmesiz:
        def fetch_tasks(self, since=None):
            return [object()]      # kayıt döndürüyor ama hata bildirimi yok

        def fetch_team_members(self):
            return []

    _set_git_repos([{"name": "r", "path": ".", "team": "T"}])
    monkeypatch.setattr(factory_mod, "build_task_provider", lambda cfg: _Sozlesmesiz())
    token = _admin_token(client, session)

    body = client.post("/api/admin/sources/test",
                       headers={"Authorization": f"Bearer {token}"}).json()

    assert body["tasks"]["ok"] is False
    assert "hata bildirimi" in body["tasks"]["detail"]


# --- İŞ-14/İŞ-15: GitLab review sinyali ve dosya listesi ----------------------
# İŞ-14: "system olmayan ilk yorum" review sayılıyordu. CI/kalite botları da
#        yorum bıraktığı için review_latency olduğundan İYİ görünüyordu.
# İŞ-15: changed_files SABİT None'dı → rework metriği, hotspot kuralı ve
#        mesaj-kod uyum analizi GitLab kurulumunda kalıcı olarak ölüydü.

def _gitlab(routes, **kw):
    from app.adapters.gitlab import GitLabProvider

    p = GitLabProvider("https://gl.local", "GL_TOKEN", [], [{"name": "r", "slug": "g/p"}], **kw)
    p.token = "t"
    return p


def test_gitlab_commit_dosyalari_cekilir(monkeypatch):
    p = _gitlab({})
    routes = {
        "/projects/g%2Fp/repository/commits": _FakeResp(
            200, [{"id": "s1", "author_email": "a@b.c", "title": "feat: x",
                   "committed_date": "2026-08-01T10:00:00+03:00",
                   "stats": {"additions": 3, "deletions": 1}}]),
        "/projects/g%2Fp/repository/commits/s1/diff": _FakeResp(
            200, [{"new_path": "app/a.py"}, {"new_path": "app/b.py"}]),
    }
    monkeypatch.setattr(p, "_client", lambda: _FakeClient(routes))

    commits = p.fetch_commits()

    assert commits[0].changed_files == ["app/a.py", "app/b.py"]
    assert commits[0].additions == 3


def test_gitlab_onay_verisi_yorumdan_once_gelir(monkeypatch):
    p = _gitlab({})
    routes = {
        "/projects/g%2Fp/merge_requests": _FakeResp(200, [{
            "iid": 7, "author": {"username": "yazar", "name": "Yazar"},
            "title": "MR", "created_at": "2026-08-01T09:00:00+03:00",
            "merged_at": "2026-08-02T09:00:00+03:00",
        }]),
        "/projects/g%2Fp/merge_requests/7/approvals": _FakeResp(200, {
            "updated_at": "2026-08-01T15:00:00+03:00",
            "approved_by": [{"user": {"username": "inceleyen"}}],
        }),
    }
    monkeypatch.setattr(p, "_client", lambda: _FakeClient(routes))

    prs = p.fetch_pull_requests()

    assert prs[0].review_source == "approval"
    assert [r.reviewer_key for r in prs[0].reviews] == ["inceleyen"]


def test_gitlab_bot_yorumu_review_sayilmaz(monkeypatch):
    """Onay verisi yoksa yorumlara düşülür ama bot yorumu review DEĞİLDİR."""
    p = _gitlab({})
    routes = {
        "/projects/g%2Fp/merge_requests": _FakeResp(200, [{
            "iid": 7, "author": {"username": "yazar"},
            "created_at": "2026-08-01T09:00:00+03:00",
        }]),
        # approvals 404 → onay özelliği kapalı; yorum yoluna düşülür
        "/projects/g%2Fp/merge_requests/7/notes": _FakeResp(200, [
            {"author": {"username": "sonarqube-bot"}, "system": False,
             "created_at": "2026-08-01T09:05:00+03:00"},
            {"author": {"username": "yazar"}, "system": False,
             "created_at": "2026-08-01T09:10:00+03:00"},
            {"author": {"username": "insan"}, "system": False,
             "created_at": "2026-08-01T12:00:00+03:00"},
        ]),
    }
    monkeypatch.setattr(p, "_client", lambda: _FakeClient(routes))

    prs = p.fetch_pull_requests()

    assert prs[0].review_source == "comment"
    # Bot ve yazarın kendi yorumu elendi: ilk review 12:00'deki insan yorumu.
    assert [r.reviewer_key for r in prs[0].reviews] == ["insan"]
    assert prs[0].first_review_at.hour == 12


# --- İŞ-13: oran sınırı (429) ve geri çekilme ---------------------------------
# Hiçbir adaptörde backoff yoktu. Trello'da kart hareketleri isteği 429 alınca
# `status_code == 200` sağlanmıyor ve o kartın TÜM geçişleri sessizce boş
# kalıyordu: cycle time düşüyor, sebebi hiçbir yerde görünmüyordu.

def test_429_sonrasi_yeniden_denenir():
    from app.adapters.http_retry import get_with_backoff

    class _Client:
        def __init__(self):
            self.n = 0

        def get(self, url, params=None):
            self.n += 1
            return _FakeResp(429 if self.n < 3 else 200, [], {"retry-after": "0"})

    c = _Client()
    uykular: list[float] = []
    resp = get_with_backoff(c, "/x", sleep=uykular.append)

    assert resp.status_code == 200
    assert c.n == 3
    assert uykular == [0.0, 0.0]   # Retry-After'a saygı duyuldu


def test_backoff_sonsuza_kadar_denemez():
    from app.adapters.http_retry import get_with_backoff

    class _Client:
        def __init__(self):
            self.n = 0

        def get(self, url, params=None):
            self.n += 1
            return _FakeResp(429, [], {"retry-after": "0"})

    c = _Client()
    resp = get_with_backoff(c, "/x", max_retries=2, sleep=lambda s: None)

    assert resp.status_code == 429   # çağıran net uyarı üretir
    assert c.n == 3                  # ilk istek + 2 deneme


def test_github_oran_siniri_403_olarak_taninir():
    from app.adapters.http_retry import oran_siniri_mi

    assert oran_siniri_mi(_FakeResp(403, {}, {"x-ratelimit-remaining": "0"})) is True
    assert oran_siniri_mi(_FakeResp(429, {}, {})) is True
    assert oran_siniri_mi(_FakeResp(404, {}, {})) is False


def test_hareketler_okunamazsa_kayip_bildirilir(monkeypatch):
    """Sessiz atlama cycle time'ı sebepsiz düşürüyordu."""
    from app.adapters.trello import TrelloProvider

    p = TrelloProvider("K", "T", ["b1"])
    p.key, p.token = "k", "t"
    routes = {
        "/boards/b1": _FakeResp(200, {"name": "Pano"}),
        "/boards/b1/lists": _FakeResp(200, [{"id": "l1", "name": "DONE"}]),
        "/boards/b1/members": _FakeResp(200, []),
        "/boards/b1/cards": _FakeResp(200, [
            {"id": "c1", "name": "kart", "idList": "l1", "idShort": 1},
        ]),
        # /boards/b1/actions YOK → 404
    }
    monkeypatch.setattr(p, "_client", lambda: _FakeClient(routes))

    tasks = p.fetch_tasks()

    assert len(tasks) == 1 and tasks[0].transitions == []
    assert any("cycle time" in w for w in p.warnings)


# --- Panelden ayarlanabilirlik: düzeltmenin YAML'da kalmaması --------------
# İŞ-10 Jira'yı gerçek Cloud kurulumunda çalışır hale getirdi ama yeni ayarlar
# (auth stili, e-posta, uç sürümü, story point alanı) panelde YOKTU: kullanıcı
# ancak sunucuya girip config.yaml düzenleyerek kullanabilirdi.

def test_jira_kimlik_ayarlari_panelden_girilebilir(client, session):
    token = _admin_token(client, session)
    auth = {"Authorization": f"Bearer {token}"}

    r = client.put("/api/admin/sources", headers=auth, json={
        "jira_base_url": "https://sirket.atlassian.net",
        "jira_auth": "basic",
        "jira_email": "kisi@sirket.com",
        "jira_api_style": "cloud",
        "jira_story_points_field": "customfield_99",
    })
    assert r.status_code == 200, r.text

    body = client.get("/api/admin/sources", headers=auth).json()["tasks"]
    assert body["jira_auth"] == "basic"
    assert body["jira_email"] == "kisi@sirket.com"
    assert body["jira_api_style"] == "cloud"
    assert body["jira_story_points_field"] == "customfield_99"


def test_gecersiz_jira_auth_reddedilir(client, session):
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}
    r = client.put("/api/admin/sources", headers=auth, json={"jira_auth": "oauth"})
    assert r.status_code == 422


def test_story_point_alani_bosaltilabilir(client, session):
    """Boş bırakmak bilinçli tercihtir: alan okunmaz, uyarı da üretilmez."""
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}
    client.put("/api/admin/sources", headers=auth,
               json={"jira_story_points_field": ""})
    body = client.get("/api/admin/sources", headers=auth).json()["tasks"]
    assert body["jira_story_points_field"] == ""


def test_ikiz_adaylari_ucu_listeler(client, session):
    """İŞ-19: uyarı senkron çıktısında kayboluyordu; eşleme ekranı listeyi
    doğrudan görebilmeli. Karar yine insanın (otomatik birleştirme yok)."""
    from app.models import Developer

    session.add(Developer(display_name="Ayşe Yılmaz", external_ids={"git": "ayse@sirket.com"}))
    session.add(Developer(display_name="ayse",
                          external_ids={"git": "12345+ayse@users.noreply.github.com"}))
    session.commit()

    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}
    body = client.get("/api/admin/developers/duplicate-candidates", headers=auth).json()

    assert body["count"] == 1
    aday = body["candidates"][0]
    assert "noreply" in aday["reason"]
    assert {aday["a"]["name"], aday["b"]["name"]} == {"Ayşe Yılmaz", "ayse"}


def test_ikiz_adaylari_admin_disina_kapali(client, session):
    from datetime import datetime, timezone

    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    session.add(User(email="calisan2@x.com", password_hash=hash_password("parola1"),
                     role="user", is_active=True, must_change_password=False,
                     created_at=now, updated_at=now))
    session.commit()
    t = client.post("/api/auth/login",
                    json={"email": "calisan2@x.com", "password": "parola1"}).json()["access_token"]

    r = client.get("/api/admin/developers/duplicate-candidates",
                   headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 403
