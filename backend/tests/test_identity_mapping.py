"""Kaynak kadrosu (Trello board üyeleri) + kimlik eşleme.

Buradaki asıl risk metriğin YANLIŞ İYİ görünmesidir: aynı insan git'te
e-postasıyla, Trello'da üye id'siyle gelir. İki ayrı kişi kaydı kalırsa takım
kadrosu şişer, WIP kişi başına bölündüğü için düşer ve pano "akıyor" der.
Bu yüzden birleştirme ayrı bir uç olarak test edilir.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select


class _FakeResp:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, routes: dict):
        self.routes = routes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        return self.routes.get(url, _FakeResp(404, {"message": "not found"}))


def _provider(monkeypatch, routes):
    from app.adapters.trello import TrelloProvider

    p = TrelloProvider("TRELLO_KEY", "TRELLO_TOKEN", ["b1"])
    p.key, p.token = "k", "t"
    monkeypatch.setattr(p, "_client", lambda: _FakeClient(routes))
    return p


# --- Adaptör: kadro ve atanan kişi adı ---------------------------------------

def test_board_uyeleri_takim_kadrosu_olarak_gelir(monkeypatch):
    p = _provider(monkeypatch, {
        "/boards/b1": _FakeResp(200, {"name": "Takım Panosu"}),
        "/boards/b1/members": _FakeResp(200, [
            {"id": "m1", "fullName": "Ayşe Yılmaz", "username": "ayse"},
            {"id": "m2", "fullName": "", "username": "mehmet"},
        ]),
    })

    members = p.fetch_team_members()

    assert [(m.team_name, m.member_key, m.member_name) for m in members] == [
        ("Takım Panosu", "m1", "Ayşe Yılmaz"),
        # fullName boşsa username'e düşer — ham id son çare
        ("Takım Panosu", "m2", "mehmet"),
    ]
    assert all(m.source == "trello" for m in members)


def test_kart_atamasi_uye_adiyla_gelir(monkeypatch):
    p = _provider(monkeypatch, {
        "/boards/b1": _FakeResp(200, {"name": "Takım Panosu"}),
        "/boards/b1/lists": _FakeResp(200, [{"id": "l1", "name": "DEVELOPMENT"}]),
        "/boards/b1/members": _FakeResp(200, [{"id": "m1", "fullName": "Ayşe Yılmaz"}]),
        "/boards/b1/cards": _FakeResp(200, [
            {"id": "c1", "name": "Kart", "idList": "l1", "idMembers": ["m1"], "labels": []},
            {"id": "c2", "name": "Sahipsiz", "idList": "l1", "idMembers": [], "labels": []},
        ]),
        "/cards/c1/actions": _FakeResp(200, []),
        "/cards/c2/actions": _FakeResp(200, []),
    })

    tasks = p.fetch_tasks()

    atanan = next(t for t in tasks if t.external_id == "c1")
    assert (atanan.assignee_key, atanan.assignee_name) == ("m1", "Ayşe Yılmaz")
    # Atanmamış kart kişiye bağlanmaz — sahte "bilinmeyen" üretilmez
    sahipsiz = next(t for t in tasks if t.external_id == "c2")
    assert sahipsiz.assignee_key is None and sahipsiz.assignee_name is None


def test_uye_listesi_okunamazsa_kartlar_yine_gelir(monkeypatch):
    """Üye listesi kart çekiminde yalnız görünen adı süsler. Sağlam board'u
    'bozuk' göstermemek için orada uyarı üretilmez; kadro çekiminde üretilir."""
    p = _provider(monkeypatch, {
        "/boards/b1": _FakeResp(200, {"name": "Takım Panosu"}),
        "/boards/b1/lists": _FakeResp(200, [{"id": "l1", "name": "DEVELOPMENT"}]),
        "/boards/b1/cards": _FakeResp(200, [
            {"id": "c1", "name": "Kart", "idList": "l1", "idMembers": ["m1"], "labels": []},
        ]),
        "/cards/c1/actions": _FakeResp(200, []),
        # "/boards/b1/members" YOK → 404
    })

    tasks = p.fetch_tasks()

    assert len(tasks) == 1
    assert tasks[0].assignee_key == "m1"     # kimlik korunur
    assert tasks[0].assignee_name is None    # ad uydurulmaz
    assert p.warnings == []                  # kart yolunda gürültü yok

    # Kadro yolunda aynı hata sessiz kalmaz: ürün zaten üye listesidir
    assert p.fetch_team_members() == []
    assert any("üye listesi okunamadı" in w for w in p.warnings)


# --- Ingest: kadro yalnızca EKLER --------------------------------------------

def test_kadro_ingest_uyelik_yazar_ve_tekrarlamaz(session):
    from app.adapters.base import NormalizedTeamMember
    from app.models import Developer, TeamMembership
    from app.services.ingest import Ingestor

    members = [NormalizedTeamMember("Takım A", "trello", "m1", "Ayşe Yılmaz")]

    assert Ingestor(session).ingest_team_members(members) == 1
    session.commit()
    # İkinci senkron aynı üyeliği çoğaltmaz
    assert Ingestor(session).ingest_team_members(members) == 0
    session.commit()

    assert len(session.scalars(select(TeamMembership)).all()) == 1
    dev = session.scalar(select(Developer))
    assert dev.display_name == "Ayşe Yılmaz"
    assert dev.external_ids["trello"] == "m1"


def test_kaynakta_olmayan_uyelik_silinmez(session):
    """Board üyeliği ile ölçüm kadrosu aynı şey değildir. Kaynağı tek gerçek
    saymak, panelden yapılmış bilinçli atamayı sessizce geri alırdı."""
    from app.adapters.base import NormalizedTeamMember
    from app.models import Developer, Team, TeamMembership
    from app.services.ingest import Ingestor

    team = Team(name="Takım A")
    dev = Developer(external_ids={"git": "elle@x.com"}, display_name="Elle Eklenen")
    session.add_all([team, dev])
    session.flush()
    session.add(TeamMembership(team_id=team.id, developer_id=dev.id, role="manager"))
    session.commit()

    Ingestor(session).ingest_team_members(
        [NormalizedTeamMember("Takım A", "trello", "m1", "Board Üyesi")]
    )
    session.commit()

    roller = {m.developer_id: m.role for m in session.scalars(select(TeamMembership))}
    assert len(roller) == 2
    assert roller[dev.id] == "manager"  # elle atanan üyelik ve rolü korunur


def test_esitlenmemis_kimlik_senkronda_uyari_uretir(session):
    from app.adapters.base import NormalizedTeamMember
    from app.services.ingest import run_ingest

    class _Tasks:
        warnings: list[str] = []

        def fetch_team_members(self):
            return [NormalizedTeamMember("Takım A", "trello", "m1", "Ayşe Yılmaz")]

        def fetch_tasks(self, since=None):
            return []

    stats = run_ingest(session, None, _Tasks())

    assert stats["team_members"] == 1
    assert any("git kimliği bağlı değil" in w for w in stats["warnings"])


# --- Kimlik eşleme ucu --------------------------------------------------------

@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


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


def test_kimlik_eslemesi_kopya_kaydi_birlestirir(client, session):
    """Asıl kazanç burada: kopya kayıt kadroyu şişirir, WIP kişi başına
    bölündüğü için metrik olduğundan iyi görünür. Birleştirme bunu kapatır."""
    from app.models import Developer, Task, Team, TeamMembership

    team = Team(name="Takım A")
    gercek = Developer(external_ids={"git": "ayse@x.com"}, display_name="Ayşe")
    kopya = Developer(external_ids={"trello": "m1"}, display_name="Ayşe Yılmaz")
    session.add_all([team, gercek, kopya])
    session.flush()
    session.add_all([
        TeamMembership(team_id=team.id, developer_id=gercek.id, role="member"),
        TeamMembership(team_id=team.id, developer_id=kopya.id, role="member"),
        Task(source="trello", external_id="c1", team_id=team.id,
             assignee_id=kopya.id, status="DEVELOPMENT"),
    ])
    session.commit()
    gercek_id, kopya_id = gercek.id, kopya.id
    token = _admin_token(client, session)

    r = client.patch(
        f"/api/admin/developers/{gercek_id}/task-identity",
        json={"source": "trello", "key": "m1"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["merged_developer_id"] == kopya_id
    session.expire_all()
    # Kopya silindi, kadro 2 kişiden 1'e indi (WIP paydası düzeldi)
    assert session.get(Developer, kopya_id) is None
    assert len(session.scalars(select(TeamMembership)).all()) == 1
    # Kopyanın işi kaybolmadı, gerçek kişiye taşındı
    assert session.scalar(select(Task)).assignee_id == gercek_id
    assert session.get(Developer, gercek_id).external_ids == {
        "git": "ayse@x.com", "trello": "m1",
    }


def test_kimlik_ucu_kopya_yoksa_sadece_bağlar(client, session):
    from app.models import Developer

    dev = Developer(external_ids={"git": "ayse@x.com"}, display_name="Ayşe")
    session.add(dev)
    session.commit()
    dev_id = dev.id
    token = _admin_token(client, session)

    r = client.patch(
        f"/api/admin/developers/{dev_id}/task-identity",
        json={"source": "trello", "key": "yeni"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert r.status_code == 200
    assert r.json()["merged_developer_id"] is None
    session.expire_all()
    assert session.get(Developer, dev_id).external_ids["trello"] == "yeni"


def test_kimlik_uclari_admin_disina_kapali(client, session):
    from app.core.security import hash_password
    from app.models import Developer, User

    now = datetime.now(timezone.utc)
    dev = Developer(external_ids={}, display_name="X")
    session.add_all([dev, User(
        email="calisan@x.com", password_hash=hash_password("parola1"), role="user",
        is_active=True, must_change_password=False, created_at=now, updated_at=now,
    )])
    session.commit()
    t = client.post(
        "/api/auth/login", json={"email": "calisan@x.com", "password": "parola1"}
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {t}"}

    assert client.get("/api/admin/identities", headers=h).status_code == 403
    assert client.patch(
        f"/api/admin/developers/{dev.id}/task-identity",
        json={"source": "trello", "key": "m1"}, headers=h,
    ).status_code == 403
