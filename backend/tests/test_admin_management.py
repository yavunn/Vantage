"""Servis edilen üründe YAML düzenlemeden yönetilebilmesi gereken şeyler.

Kurulu bir sistemde "yeni takım aç", "repo bağla", "eşiği değiştir" talepleri
sunucuya SSH + config.yaml düzenleme gerektirmemeli. Bu dosya o yüzeyleri
(takım CRUD, repo ekle/çıkar, statü eşlemesi, genel ayarlar) ve yetki
sınırlarını doğrular.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from tests.conftest import make_team

# Ortak yardımcılar tek yerde dursun (client fixture'ı da oradan gelir).
from tests.test_integration_sources import _admin_token, _set_git_repos, client  # noqa: F401


def _user_token(client, session, email="calisan@x.com"):
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    session.add(User(
        email=email, password_hash=hash_password("parola1"), role="user",
        is_active=True, must_change_password=False, created_at=now, updated_at=now,
    ))
    session.commit()
    r = client.post("/api/auth/login", json={"email": email, "password": "parola1"})
    return r.json()["access_token"]


# --- Takım yönetimi -----------------------------------------------------------

def test_takim_olustur_ve_listele(client, session):
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    r = client.post("/api/admin/teams", json={"name": "Platform"}, headers=auth)
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Platform"

    # Ad, ingest'te takım kimliğidir — çakışma sessizce birleştirilemez.
    assert client.post("/api/admin/teams", json={"name": "Platform"},
                       headers=auth).status_code == 409

    rows = client.get("/api/admin/teams", headers=auth).json()
    assert [t["name"] for t in rows] == ["Platform"]
    assert rows[0]["deletable"] is True


def test_uye_veya_repo_bagliysa_takim_silinmez(client, session):
    team, _repo, _devs, _mgr = make_team(session, name="Dolu")
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    row = next(t for t in client.get("/api/admin/teams", headers=auth).json()
               if t["name"] == "Dolu")
    assert row["deletable"] is False
    assert row["members"] == 3 and row["repos"] == 1

    r = client.delete(f"/api/admin/teams/{team.id}", headers=auth)
    assert r.status_code == 409
    assert "üye" in r.json()["detail"]


def test_takim_silinince_gorevler_korunur_takimsiz_kalir(client, session):
    from app.models import MetricResult, Task, Team

    team = Team(name="Kapanan")
    session.add(team)
    session.flush()
    session.add(Task(source="trello", external_id="T-9", team_id=team.id, status="DEVELOPMENT"))
    session.add(MetricResult(scope="team", scope_id=team.id, metric_key="wip",
                             period="p", value=1.0, data_completeness=1.0,
                             computed_at=datetime.now(timezone.utc)))
    session.commit()
    team_id = team.id

    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}
    r = client.delete(f"/api/admin/teams/{team_id}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["detached_tasks"] == 1

    session.expire_all()
    assert session.get(Team, team_id) is None
    # Gerçek iş kaydı SİLİNMEZ, yalnız takımsız kalır.
    task = session.scalar(select(Task).where(Task.external_id == "T-9"))
    assert task is not None and task.team_id is None
    # Artık var olmayan takımın metrik satırı temizlenir.
    assert session.scalars(
        select(MetricResult).where(MetricResult.scope_id == team_id)).all() == []


def test_takim_adi_degisince_repo_eslemesi_de_guncellenir(client, session):
    """Eşleme adla tutulur: config güncellenmezse sonraki senkron eski adla YENİ
    takım yaratır ve repo oraya kayardı (sessiz veri bölünmesi)."""
    from app.core.config import get_config, reset_config_cache
    from app.models import Team

    team = Team(name="Eski Ad")
    session.add(team)
    session.commit()
    _set_git_repos([{"name": "vantage", "path": "/repo", "team": "Eski Ad"}])
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    r = client.patch(f"/api/admin/teams/{team.id}", json={"name": "Yeni Ad"}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["config_updated"] is True
    reset_config_cache()
    assert get_config().sources.git.repos[0]["team"] == "Yeni Ad"


def test_takim_uclari_admin_disina_kapali(client, session):
    auth = {"Authorization": f"Bearer {_user_token(client, session)}"}
    assert client.get("/api/admin/teams", headers=auth).status_code == 403
    assert client.post("/api/admin/teams", json={"name": "X"}, headers=auth).status_code == 403
    assert client.delete("/api/admin/teams/1", headers=auth).status_code == 403


# --- Repo ekle/çıkar + statü eşlemesi ----------------------------------------

def test_repo_eklenip_cikarilabilir(client, session):
    from app.core.config import get_config, reset_config_cache

    _set_git_repos([{"name": "eski", "path": "/a"}])
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    r = client.put("/api/admin/sources", json={"repos": [
        {"name": "eski", "path": "/a", "team": "T1"},
        {"name": "yeni", "path": "/b", "team": ""},
    ]}, headers=auth)
    assert r.status_code == 200, r.text
    reset_config_cache()
    repos = get_config().sources.git.repos
    assert [x["name"] for x in repos] == ["eski", "yeni"]
    assert repos[0]["team"] == "T1"
    assert "team" not in repos[1]  # boş takım eşleme yazmaz

    # Listede olmayan repo config'ten düşer.
    client.put("/api/admin/sources", json={"repos": [{"name": "yeni", "path": "/b"}]},
               headers=auth)
    reset_config_cache()
    assert [x["name"] for x in get_config().sources.git.repos] == ["yeni"]


def test_ayni_adli_repo_iki_kez_yazilmaz(client, session):
    """Repo adı ingest'te kimlik anahtarı; çakışırsa commitler karışır."""
    from app.core.config import get_config, reset_config_cache

    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}
    client.put("/api/admin/sources", json={"repos": [
        {"name": "x", "path": "/1"},
        {"name": "x", "path": "/2"},
    ]}, headers=auth)
    reset_config_cache()
    repos = get_config().sources.git.repos
    assert len(repos) == 1 and repos[0]["path"] == "/1"


def test_statu_eslemesi_arayuzden_YAZILMAZ(client, session):
    """Statü eşlemesi panelden kaldırıldı: ekip akışı Trello'da kartı doğru
    listeye taşıyarak belirliyor, ikinci bir eşleme ekranı aynı kararı iki
    yerde yönetmek demekti.

    KRİTİK: eşleme config'te YAŞAMAYA ve motor tarafından KULLANILMAYA devam
    eder (bkz. test_metrics: eşleme testleri). Bu test yalnız uç yüzeyinin
    kapandığını ve mevcut config'in bozulmadığını doğrular."""
    from app.core.config import get_config, reset_config_cache

    reset_config_cache()
    onceki = list(get_config().sources.tasks.status_mapping.backlog)

    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}
    # Bilinmeyen alan artık şemada yok → sessizce yok sayılır, 200 döner.
    r = client.put("/api/admin/sources",
                   json={"status_mapping": {"backlog": ["UYDURMA"]}}, headers=auth)
    assert r.status_code == 200, r.text

    reset_config_cache()
    assert get_config().sources.tasks.status_mapping.backlog == onceki

    # GET yanıtında da eşleme/görülen statü alanları yok.
    body = client.get("/api/admin/sources", headers=auth).json()
    assert "status_mapping" not in body["tasks"]
    assert "observed_statuses" not in body["tasks"]


# --- Genel ayarlar ------------------------------------------------------------

def test_gorunurluk_ve_anket_ayarlari_yazilir(client, session):
    from app.core.config import get_config, reset_config_cache

    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    body = client.get("/api/admin/settings", headers=auth).json()
    assert set(body) == {"app", "survey"}

    r = client.put("/api/admin/settings", json={
        "anonymize_individuals": True,
        "individual_view_enabled": False,
        "survey_min_responses": 5,
    }, headers=auth)
    assert r.status_code == 200, r.text

    reset_config_cache()
    cfg = get_config()
    assert cfg.app.anonymize_individuals is True
    assert cfg.app.individual_view_enabled is False
    assert cfg.survey.min_responses == 5


def test_esik_ve_kural_degerleri_api_den_yazilamaz(client, session):
    """Eşik/kural/metrik değerleri yöneticinin tahmin edeceği sayılar değil;
    bilerek API yüzeyinde YOK. Gönderilse bile config'e sızmamalı."""
    from app.core.config import get_config, reset_config_cache

    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}
    before = get_config().health_thresholds.wip_per_dev.green

    r = client.put("/api/admin/settings", json={
        "thresholds": {"wip_per_dev": {"green": 99, "red": 100}},
        "metrics_enabled": {"wip": False},
        "rules_enabled": {"review_bottleneck": False},
    }, headers=auth)
    assert r.status_code == 200, r.text  # bilinmeyen alanlar sessizce yok sayılır

    reset_config_cache()
    cfg = get_config()
    assert cfg.health_thresholds.wip_per_dev.green == before
    assert cfg.metric("wip").enabled is True
    assert cfg.rule("review_bottleneck").enabled is True


def test_gizlilik_esigi_bire_kadar_kisilir(client, session):
    """min_responses 1'in altına inerse tek yanıt ifşa olur — sunucu kısar."""
    from app.core.config import get_config, reset_config_cache

    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}
    client.put("/api/admin/settings", json={"survey_min_responses": 0}, headers=auth)
    reset_config_cache()
    assert get_config().survey.min_responses == 1


def test_ayar_uclari_admin_disina_kapali(client, session):
    auth = {"Authorization": f"Bearer {_user_token(client, session)}"}
    assert client.get("/api/admin/settings", headers=auth).status_code == 403
    assert client.put("/api/admin/settings", json={"anonymize_individuals": True},
                      headers=auth).status_code == 403
