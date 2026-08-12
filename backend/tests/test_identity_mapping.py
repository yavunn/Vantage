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
        "/boards/b1/actions": _FakeResp(200, []),
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
        "/boards/b1/actions": _FakeResp(200, []),
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


def _trello_kaynagini_ac(monkeypatch, kayitlar, warnings=None):
    """Görev kaynağını trello yapar ve üye dizinini sahteler (ağa çıkmaz)."""
    import yaml

    from app.adapters.trello import TrelloProvider
    from app.core.config import active_config_path, reset_config_cache

    path = active_config_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw.setdefault("sources", {})["tasks"] = {
        "provider": "trello", "trello": {"boards": ["b1"]},
    }
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    reset_config_cache()

    def sahte(self):
        self.warnings = list(warnings or [])
        return list(kayitlar)

    monkeypatch.setattr(TrelloProvider, "fetch_member_directory", sahte)


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


def test_iki_git_epostasiyla_bolunmus_kisi_elle_birlestirilir(client, session):
    """Otomatik eşleme bu vakayı YAKALAYAMAZ: aynı insan iki git e-postasıyla
    gelmişse (biri GitHub'ın …@users.noreply.github.com adresi) iki kayıt da
    'eşlenmiş' görünür. Commit'ler birine, görevler diğerine düşer ve hiçbir
    kişi bazlı görünüm doğru çıkmaz. Kararı insan verir, uç bunu uygular."""
    from app.models import Commit, Developer, Repo, Task, Team

    team = Team(name="Takım A")
    repo = Repo(name="r1")
    asil = Developer(external_ids={"git": "ayse@x.com"}, display_name="Ayşe")
    ikiz = Developer(external_ids={"git": "1+ayse@users.noreply.github.com",
                                   "trello": "m1"}, display_name="ayse")
    session.add_all([team, repo, asil, ikiz])
    session.flush()
    session.add_all([
        Commit(repo_id=repo.id, sha="a1", author_id=asil.id,
               committed_at=datetime.now(timezone.utc), message="iş"),
        # Commit kopyada da olabilir: birleştirme onu da taşımalı, yoksa
        # kopyayı silme adımı foreign key hatası verir.
        Commit(repo_id=repo.id, sha="b2", author_id=ikiz.id,
               committed_at=datetime.now(timezone.utc), message="iş 2"),
        Task(source="trello", external_id="c1", team_id=team.id,
             assignee_id=ikiz.id, status="DONE"),
    ])
    session.commit()
    asil_id, ikiz_id = asil.id, ikiz.id
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    r = client.post(f"/api/admin/developers/{asil_id}/merge",
                    json={"duplicate_id": ikiz_id}, headers=auth)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["merged_developer_id"] == ikiz_id
    assert body["moved"]["commits"] == 1 and body["moved"]["tasks"] == 1
    session.expire_all()
    assert session.get(Developer, ikiz_id) is None
    # Commit'ler ve görev asıl kayda taşındı — hiçbir kayıt kaybolmadı
    assert {c.sha for c in session.scalars(select(Commit))} == {"a1", "b2"}
    assert all(c.author_id == asil_id for c in session.scalars(select(Commit)))
    assert session.scalar(select(Task)).assignee_id == asil_id
    # Kopyanın Trello kimliği hedefe geçti: sonraki senkron kopyayı yeniden AÇMAZ
    assert session.get(Developer, asil_id).external_ids["trello"] == "m1"


def test_kendisiyle_birlestirme_reddedilir(client, session):
    from app.models import Developer

    dev = Developer(external_ids={"git": "a@x.com"}, display_name="A")
    session.add(dev)
    session.commit()
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    r = client.post(f"/api/admin/developers/{dev.id}/merge",
                    json={"duplicate_id": dev.id}, headers=auth)
    assert r.status_code == 400


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


# --- Adaptör: kart numarası (konvansiyonun ön şartı) --------------------------

def test_kart_numarasi_ve_adresi_cekilir(monkeypatch):
    """`idShort` çekilmezse task↔commit bağı TAHMİN olmak zorunda kalır: kartın
    `id` alanı opak bir hash'tir ve kimse onu commit mesajına yazmaz."""
    p = _provider(monkeypatch, {
        "/boards/b1": _FakeResp(200, {"name": "Takım Panosu"}),
        "/boards/b1/members": _FakeResp(200, []),
        "/boards/b1/lists": _FakeResp(200, [{"id": "l1", "name": "Bitti"}]),
        "/boards/b1/actions": _FakeResp(200, []),
        "/boards/b1/cards": _FakeResp(200, [{
            "id": "6a607d6760ba225667be389e", "name": "rapor ekrani",
            "idList": "l1", "idShort": 42, "shortLink": "aBcD1234",
            "shortUrl": "https://trello.com/c/aBcD1234", "labels": [],
        }]),
        "/cards/6a607d6760ba225667be389e/actions": _FakeResp(200, []),
    })

    task = p.fetch_tasks()[0]

    assert task.key == "42"
    assert task.url == "https://trello.com/c/aBcD1234"
    # external_id opak kalır: benzersizliği o sağlar, insan referansı `key`.
    assert task.external_id == "6a607d6760ba225667be389e"


def test_kart_numarasi_yoksa_uydurulmaz(monkeypatch):
    p = _provider(monkeypatch, {
        "/boards/b1": _FakeResp(200, {"name": "Takım Panosu"}),
        "/boards/b1/members": _FakeResp(200, []),
        "/boards/b1/lists": _FakeResp(200, []),
        "/boards/b1/actions": _FakeResp(200, []),
        "/boards/b1/cards": _FakeResp(200, [
            {"id": "c1", "name": "numarasiz kart", "idList": "l1", "labels": []},
        ]),
        "/cards/c1/actions": _FakeResp(200, []),
    })

    task = p.fetch_tasks()[0]

    assert task.key is None
    assert task.url is None


def test_board_adi_okunamazsa_kartlarin_takimsiz_kalacagi_soylenir(monkeypatch):
    """Takımsız kart indekste ölü kalır (asistan sorgusunda getirilemez).
    Sessiz atlama, entegrasyonu çalışıyor sanmaya yol açar."""
    p = _provider(monkeypatch, {
        "/boards/b1": _FakeResp(200, {}),          # ad YOK
        "/boards/b1/members": _FakeResp(200, []),
        "/boards/b1/lists": _FakeResp(200, []),
        "/boards/b1/actions": _FakeResp(200, []),
        "/boards/b1/cards": _FakeResp(200, [
            {"id": "c1", "name": "kart", "idList": "l1", "labels": []},
        ]),
        "/cards/c1/actions": _FakeResp(200, []),
    })

    tasks = p.fetch_tasks()

    assert tasks[0].team_name is None
    assert any("takıma bağlanamaz" in w for w in p.warnings)


# --- İŞ-19: aynı insanın iki geliştirici kaydı --------------------------------
# Canlı DB'de team 7'nin iki üyesi de aynı insandı (biri kişisel e-postayla, biri
# GitHub noreply adresiyle) → member_count 2, kişi başı WIP yarıya iniyor ve
# metrik olduğundan İYİ görünüyordu. Mevcut uyarı (_unlinked_identity_warnings)
# yalnız "git kimliği HİÇ olmayan" kişiyi yakalıyordu.
#
# OTOMATİK BİRLEŞTİRME YOK: burada yalnız ADAY üretilir, karar insanındır.

def _dev(session, ad, ids):
    from app.models import Developer

    d = Developer(display_name=ad, external_ids=ids)
    session.add(d)
    session.flush()
    return d


def test_github_noreply_ikizi_yakalanir(session):
    from app.services.ingest import duplicate_identity_pairs

    _dev(session, "Ayşe Yılmaz", {"git": "ayse@sirket.com"})
    _dev(session, "ayse", {"git": "12345+ayse@users.noreply.github.com"})
    session.commit()

    ciftler = duplicate_identity_pairs(session)

    assert len(ciftler) == 1
    assert "noreply" in ciftler[0][2]


def test_ayni_gorunen_ad_farkli_git_kimligi_yakalanir(session):
    from app.services.ingest import duplicate_identity_pairs

    _dev(session, "Mehmet Kaya", {"git": "mehmet@eski.com"})
    _dev(session, "Mehmet Kaya", {"git": "mehmet.kaya@yeni.com"})
    session.commit()

    ciftler = duplicate_identity_pairs(session)
    assert len(ciftler) == 1
    assert "görünen ad" in ciftler[0][2]


def test_ayni_trello_kimligi_yakalanir(session):
    from app.services.ingest import duplicate_identity_pairs

    _dev(session, "A", {"git": "a@x.com", "trello": "m1"})
    _dev(session, "B", {"git": "b@x.com", "trello": "m1"})
    session.commit()

    ciftler = duplicate_identity_pairs(session)
    assert len(ciftler) == 1
    assert "trello" in ciftler[0][2]


def test_farkli_kisiler_ikiz_sayilmaz(session):
    """Yanlış pozitif, İK bağlamında gerçek bir zarardır: iki ayrı insanı
    birleştirmeye davet etmemeli."""
    from app.services.ingest import duplicate_identity_pairs

    _dev(session, "Ali", {"git": "ali@x.com", "trello": "m1"})
    _dev(session, "Veli", {"git": "veli@x.com", "trello": "m2"})
    session.commit()

    assert duplicate_identity_pairs(session) == []


# --- Çoklu git e-postası ------------------------------------------------------
#
# Aynı insan kişisel adresiyle ve GitHub'ın gizlilik adresiyle commit atar.
# Alan tek string kaldığı sürece tek çare "kopya aç, sonra birleştir"di — ve
# birleştirme kopyanın e-postasını ATIYORDU, bu yüzden bir sonraki senkron aynı
# kopyayı yeniden açıyordu. Sessiz bir döngü.

def test_git_alani_hem_metin_hem_liste_okunur():
    from app.services.identity import git_emails, primary_git_email, with_git_emails

    assert git_emails({"git": "A@X.com"}) == ["a@x.com"]
    assert git_emails({"git": ["a@x.com", "B@x.com", "a@x.com"]}) == ["a@x.com", "b@x.com"]
    assert git_emails({}) == [] and git_emails(None) == []
    assert primary_git_email({"git": ["ilk@x.com", "ikinci@x.com"]}) == "ilk@x.com"
    # Tek e-posta metin olarak yazılır: veriyi ve eski istemcileri karşılıksız kırma.
    assert with_git_emails({}, ["a@x.com"]) == {"git": "a@x.com"}
    assert with_git_emails({}, ["a@x.com", "b@x.com"]) == {"git": ["a@x.com", "b@x.com"]}
    assert with_git_emails({"git": "a@x.com", "trello": "m1"}, []) == {"trello": "m1"}


def test_ikinci_git_epostasi_ayni_kisiye_cozulur(session):
    """Asıl kazanç: ikinci adres artık YENİ bir kişi kaydı açmıyor."""
    from app.adapters.base import NormalizedCommit
    from app.models import Commit, Developer
    from app.services.ingest import Ingestor

    dev = Developer(display_name="Ayşe",
                    external_ids={"git": ["ayse@sirket.com",
                                          "1+ayse@users.noreply.github.com"]})
    session.add(dev)
    session.commit()

    Ingestor(session).ingest_commits([
        NormalizedCommit(repo_name="r1", sha="a1", author_key="ayse@sirket.com"),
        NormalizedCommit(repo_name="r1", sha="b2",
                         author_key="1+AYSE@users.noreply.github.com"),
    ])
    session.commit()

    assert len(session.scalars(select(Developer)).all()) == 1
    assert {c.author_id for c in session.scalars(select(Commit))} == {dev.id}


def test_birlestirme_iki_git_epostasini_da_saklar(session):
    """Kopyanın e-postası atılırsa bir sonraki senkron kopyayı YENİDEN açar."""
    from app.models import Developer
    from app.services.identity import git_emails, merge_developers

    asil = _dev(session, "Ayşe", {"git": "ayse@sirket.com"})
    ikiz = _dev(session, "ayse", {"git": "1+ayse@users.noreply.github.com"})
    session.commit()
    asil_id = asil.id

    merge_developers(session, asil.id, ikiz.id)

    kalan = session.get(Developer, asil_id)
    assert set(git_emails(kalan.external_ids)) == {
        "ayse@sirket.com", "1+ayse@users.noreply.github.com",
    }


def test_git_eposta_ucu_liste_kabul_eder_ve_cakismayi_reddeder(client, session):
    from app.models import Developer

    a = _dev(session, "A", {})
    b = _dev(session, "B", {"git": "b@x.com"})
    session.commit()
    a_id, b_id = a.id, b.id
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    r = client.patch(f"/api/admin/developers/{a_id}/git-email",
                     json={"git_emails": ["a@x.com", "1+a@users.noreply.github.com"]},
                     headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["git_emails"] == ["a@x.com", "1+a@users.noreply.github.com"]

    # Başkasının e-postasını almak SESSİZCE olmaz: o commit'ler bir sonraki
    # senkronda yanlış insana atfedilirdi.
    r = client.patch(f"/api/admin/developers/{a_id}/git-email",
                     json={"git_emails": ["b@x.com"]}, headers=auth)
    assert r.status_code == 409
    session.expire_all()
    assert session.get(Developer, b_id).external_ids["git"] == "b@x.com"


# --- Trello üyeleri ↔ giriş hesapları -----------------------------------------

def test_aday_eslesmesi_turkce_katlar_ve_tam_eslesme_ister():
    """Trello'da tam ad Türkçe, kurumsal e-posta ASCII olur. Katlamayan bir
    karşılaştırma bu çok yaygın çifti hiç yakalayamaz. Ama PARÇA eşleşme de
    kabul edilmez: yanlış aday, adaysızlıktan kötüdür."""
    from app.services.identity import suggest_account

    hesaplar = [{"developer_id": 7, "display_name": "Ayşe Yılmaz",
                 "user_email": "ayse.yilmaz@sirket.com"}]

    assert suggest_account("Ayşe Yılmaz", None, hesaplar)[0] == 7
    assert suggest_account("AYSE YILMAZ", None, hesaplar)[0] == 7
    assert suggest_account(None, "ayse.yilmaz", hesaplar)[0] == 7
    # "Ayşe" tek başına eşleşmez — "Ayşe Yılmaz" ile "Ayşe Demir" ayrı insanlar.
    assert suggest_account("Ayşe", None, hesaplar) is None
    assert suggest_account(None, None, hesaplar) is None


def test_trello_uyeleri_ucu_bagli_ve_bagsizi_ayirir(client, session, monkeypatch):
    from app.core.security import hash_password
    from app.models import Developer, User

    dev = _dev(session, "Ayşe Yılmaz", {"git": "ayse@x.com"})
    bagli = _dev(session, "Mehmet", {"git": "m@x.com", "trello": "m2"})
    session.flush()
    now = datetime.now(timezone.utc)
    session.add_all([
        User(email="ayse@sirket.com", password_hash=hash_password("parola1"),
             role="user", developer_id=dev.id, is_active=True,
             must_change_password=False, created_at=now, updated_at=now),
        User(email="mehmet@sirket.com", password_hash=hash_password("parola1"),
             role="user", developer_id=bagli.id, is_active=True,
             must_change_password=False, created_at=now, updated_at=now),
    ])
    session.commit()
    dev_id = dev.id

    _trello_kaynagini_ac(monkeypatch, [
        {"board_id": "b1", "board_name": "Pano", "member_id": "m1",
         "username": "ayse", "full_name": "Ayşe Yılmaz"},
        {"board_id": "b1", "board_name": "Pano", "member_id": "m2",
         "username": "mehmet", "full_name": "Mehmet"},
    ])
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    body = client.get("/api/admin/trello/members", headers=auth).json()

    uyeler = {m["member_id"]: m for m in body["members"]}
    assert uyeler["m2"]["linked"] is True
    assert uyeler["m2"]["user_email"] == "mehmet@sirket.com"
    # Bağsız üye için ADAY üretilir ama otomatik bağlanmaz — karar insanın.
    assert uyeler["m1"]["linked"] is False
    assert uyeler["m1"]["suggestion"]["developer_id"] == dev_id
    assert session.get(Developer, dev_id).external_ids.get("trello") is None


def test_trello_okunamazsa_uyari_govdede_doner(client, session, monkeypatch):
    """Board erişimi bozukken ekran tamamen kararmamalı: bağlı üyeler yine
    listelenebilmeli, sebep görünür olmalı."""
    _trello_kaynagini_ac(monkeypatch, [], warnings=["Trello board 'b1': erişim reddedildi (401)."])
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    r = client.get("/api/admin/trello/members", headers=auth)

    assert r.status_code == 200
    assert any("401" in w for w in r.json()["warnings"])


def test_giris_hesabi_olan_kimlik_devralinamaz(client, session):
    """Aynı Trello kimliğini taşıyan kayıt bir KULLANICIYA aitse o bir 'kopya'
    değil BAŞKA BİR İNSANDIR: birleştirme iki çalışanın commit'lerini,
    görevlerini ve izinlerini tek kişide toplardı."""
    from app.core.security import hash_password
    from app.models import User

    a = _dev(session, "A", {"git": "a@x.com"})
    b = _dev(session, "B", {"git": "b@x.com", "trello": "m1"})
    session.flush()
    now = datetime.now(timezone.utc)
    session.add(User(email="b@sirket.com", password_hash=hash_password("parola1"),
                     role="user", developer_id=b.id, is_active=True,
                     must_change_password=False, created_at=now, updated_at=now))
    session.commit()
    a_id, b_id = a.id, b.id
    auth = {"Authorization": f"Bearer {_admin_token(client, session)}"}

    r = client.patch(f"/api/admin/developers/{a_id}/task-identity",
                     json={"source": "trello", "key": "m1"}, headers=auth)

    assert r.status_code == 409
    session.expire_all()
    from app.models import Developer
    assert session.get(Developer, b_id) is not None          # kayıt silinmedi
    assert session.get(Developer, a_id).external_ids.get("trello") is None


# --- Self-service: kendi kimliğim ---------------------------------------------

def _kullanici(session, client, dev, email="calisan@x.com"):
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    session.add(User(
        email=email, password_hash=hash_password("parola1"), role="user",
        developer_id=dev.id if dev else None, is_active=True,
        must_change_password=False, created_at=now, updated_at=now,
    ))
    session.commit()
    r = client.post("/api/auth/login", json={"email": email, "password": "parola1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_kullanici_kendi_git_epostasini_baglar(client, session):
    from app.models import Developer

    dev = _dev(session, "Ayşe", {})
    session.commit()
    dev_id = dev.id
    auth = _kullanici(session, client, dev)

    r = client.patch("/api/me/identities",
                     json={"git_emails": ["Ayse@Sirket.com"]}, headers=auth)

    assert r.status_code == 200, r.text
    assert r.json()["git_emails"] == ["ayse@sirket.com"]
    session.expire_all()
    assert session.get(Developer, dev_id).external_ids["git"] == "ayse@sirket.com"


def test_kullanici_baskasinin_kimligini_alamaz(client, session):
    dev = _dev(session, "Ayşe", {})
    _dev(session, "Mehmet", {"git": "mehmet@sirket.com"})
    session.commit()
    auth = _kullanici(session, client, dev)

    r = client.patch("/api/me/identities",
                     json={"git_emails": ["mehmet@sirket.com"]}, headers=auth)

    assert r.status_code == 409
    assert "Mehmet" in r.json()["detail"]


def test_kullanici_kendi_trello_kaydini_ustlenir(client, session, monkeypatch):
    """Kaynağın açtığı kopya kayıt (hesabı yok) kullanıcıya birleştirilir —
    kartları taşınır. Bırakılsaydı kadro şişer ve kişi başı WIP olduğundan
    iyi görünürdü."""
    from app.models import Developer, Task

    dev = _dev(session, "Ayşe Yılmaz", {"git": "ayse@sirket.com"})
    kopya = _dev(session, "Ayşe Yılmaz", {"trello": "m1"})
    session.flush()
    session.add(Task(source="trello", external_id="c1", title="kart",
                     assignee_id=kopya.id))
    session.commit()
    dev_id, kopya_id = dev.id, kopya.id
    _trello_kaynagini_ac(monkeypatch, [])
    auth = _kullanici(session, client, dev, email="ayse@sirket.com")

    r = client.patch("/api/me/identities",
                     json={"task_identity": "m1"}, headers=auth)

    assert r.status_code == 200, r.text
    assert r.json()["merged_developer_id"] == kopya_id
    session.expire_all()
    assert session.get(Developer, kopya_id) is None
    assert session.scalar(select(Task)).assignee_id == dev_id


def test_baskasina_benzeyen_kaydi_kullanici_ustlenemez(client, session, monkeypatch):
    """Aksi hâlde bir çalışan meslektaşının kaynak kaydını üstlenip onun
    kartlarını kendine taşıyabilirdi. Böyle bir bağı yönetici kurar."""
    from app.models import Developer

    ben = _dev(session, "Ayşe", {"git": "ayse@sirket.com"})
    _dev(session, "Mehmet Kaya", {"trello": "m1"})   # hesabı yok ama başkası
    session.flush()
    session.commit()
    ben_id = ben.id
    # "Mehmet Kaya" adlı bir giriş hesabı var: kopya ona benziyor.
    _kullanici(session, client, _dev(session, "Mehmet Kaya", {"git": "mk@sirket.com"}),
               email="mehmet.kaya@sirket.com")
    _trello_kaynagini_ac(monkeypatch, [])
    auth = _kullanici(session, client, ben, email="ayse@sirket.com")

    r = client.patch("/api/me/identities",
                     json={"task_identity": "m1"}, headers=auth)

    assert r.status_code == 409
    session.expire_all()
    assert session.get(Developer, ben_id).external_ids.get("trello") is None


def test_kisi_kaydi_olmayan_hesap_net_hata_alir(client, session):
    """Sessiz 500 yerine ne yapması gerektiğini söyleyen 400."""
    auth = _kullanici(session, client, None, email="admin2@x.com")

    r = client.get("/api/me/identities", headers=auth)

    assert r.status_code == 400
    assert "yöneticinize" in r.json()["detail"]


def test_ikiz_uyarisi_metrik_etkisini_soyler(session):
    from app.services.ingest import _duplicate_identity_warnings

    _dev(session, "Ayşe Yılmaz", {"git": "ayse@sirket.com"})
    _dev(session, "ayse", {"git": "12345+ayse@users.noreply.github.com"})
    session.commit()

    uyarilar = _duplicate_identity_warnings(session)
    assert uyarilar and "WIP" in uyarilar[0]
    assert "otomatik birleştirme yapılmaz" in uyarilar[0].lower()


def test_ayni_karta_atanmis_iki_kayit_birlestirilebilir(session):
    """Kimlik eşlemesi yapılmamış kurulumda aynı insan bir karta İKİ kaydıyla
    atanmış olabilir. Benzersizlik kısıtı (task_id + developer_id) yüzünden
    kopyanın satırını körü körüne taşımak IntegrityError verirdi — taşınmaz,
    silinir. Aynı gerekçe takım üyeliğinde de geçerli."""
    from app.models import Task, TaskAssignee, Team, TeamMembership
    from app.services.identity import merge_developers

    team = Team(name="Takım A")
    asil = _dev(session, "Ayşe", {"git": "ayse@x.com"})
    ikiz = _dev(session, "ayse", {"trello": "m1"})
    session.add(team)
    session.flush()
    task = Task(source="trello", external_id="c1", title="iş")
    session.add(task)
    session.flush()
    session.add_all([
        TaskAssignee(task_id=task.id, developer_id=asil.id, is_primary=True),
        TaskAssignee(task_id=task.id, developer_id=ikiz.id),
        TeamMembership(team_id=team.id, developer_id=asil.id, role="member"),
        TeamMembership(team_id=team.id, developer_id=ikiz.id, role="member"),
    ])
    session.commit()
    asil_id, task_id = asil.id, task.id

    merge_developers(session, asil.id, ikiz.id)

    session.expire_all()
    atananlar = list(session.scalars(
        select(TaskAssignee).where(TaskAssignee.task_id == task_id)))
    assert len(atananlar) == 1 and atananlar[0].developer_id == asil_id
    uyelikler = list(session.scalars(select(TeamMembership)))
    assert len(uyelikler) == 1 and uyelikler[0].developer_id == asil_id
