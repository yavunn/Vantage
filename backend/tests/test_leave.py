"""Faz 5 — İzin / İK modülü testleri.

- Self-servis: çalışan izin girer, yalnız KENDİ taleplerini görür.
- Onay: admin ya da kişinin YÖNETİCİSİ; başka çalışan/başka takım onaylayamaz.
- Metrik entegrasyonu (asıl değer): onaylı izin günleri cycle time'dan düşülür.
- Takvim: izin sebebi/açıklaması sızmaz; anonim modda isim maskeli.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.conftest import NOW, days_ago, make_team
from tests.test_auth import login, make_user


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _headers(client, session, email, password="gizli123", developer=None, role="user"):
    make_user(session, email, password, developer=developer, role=role)
    token = login(client, email, password).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _leave_body(days_from=5, days_to=8, leave_type="yillik", description="tatil"):
    return {
        "start_date": (NOW + timedelta(days=days_from)).date().isoformat(),
        "end_date": (NOW + timedelta(days=days_to)).date().isoformat(),
        "leave_type": leave_type,
        "description": description,
    }


# --- kimlik / self-servis ------------------------------------------------------

def test_kimliksiz_401(client, session):
    assert client.get("/api/user/leave-requests").status_code == 401
    assert client.post("/api/user/leave-requests", json=_leave_body()).status_code == 401
    assert client.get("/api/admin/leave-requests").status_code == 401
    assert client.get("/api/leave/calendar").status_code == 401


def test_talep_olustur_ve_kendi_listesi(client, session):
    team, repo, devs, mgr = make_team(session)
    h = _headers(client, session, "dev1@corp.local", developer=devs[0])
    resp = client.post("/api/user/leave-requests", headers=h, json=_leave_body())
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending" and body["developer_id"] == devs[0].id
    mine = client.get("/api/user/leave-requests", headers=h).json()
    assert len(mine) == 1 and mine[0]["id"] == body["id"]


def test_gecersiz_tip_ve_tarih_422(client, session):
    team, repo, devs, mgr = make_team(session)
    h = _headers(client, session, "dev1@corp.local", developer=devs[0])
    assert client.post("/api/user/leave-requests", headers=h,
                       json=_leave_body(leave_type="uzun")).status_code == 422
    assert client.post("/api/user/leave-requests", headers=h,
                       json=_leave_body(days_from=8, days_to=5)).status_code == 422


def test_baskasinin_talebi_gorunmez(client, session):
    team, repo, devs, mgr = make_team(session)
    owner = _headers(client, session, "dev1@corp.local", developer=devs[0])
    client.post("/api/user/leave-requests", headers=owner, json=_leave_body())
    other = _headers(client, session, "dev2@corp.local", developer=devs[1])
    # Başka çalışanın kendi listesi boş; başkasının izni asla sızmaz
    assert client.get("/api/user/leave-requests", headers=other).json() == []


# --- onay yetkisi --------------------------------------------------------------

def test_normal_calisan_onay_ucuna_erisemez(client, session):
    team, repo, devs, mgr = make_team(session)
    emp = _headers(client, session, "dev2@corp.local", developer=devs[1])
    assert client.get("/api/admin/leave-requests", headers=emp).status_code == 403


def test_admin_onaylar_ve_reddeder(client, session):
    team, repo, devs, mgr = make_team(session)
    owner = _headers(client, session, "dev1@corp.local", developer=devs[0])
    leave_id = client.post("/api/user/leave-requests", headers=owner,
                           json=_leave_body()).json()["id"]
    admin = _headers(client, session, "admin@corp.local", role="admin")
    listed = client.get("/api/admin/leave-requests", headers=admin).json()
    assert any(x["id"] == leave_id for x in listed)
    resp = client.put(f"/api/admin/leave-requests/{leave_id}", headers=admin,
                      json={"decision": "approve"})
    assert resp.status_code == 200 and resp.json()["status"] == "approved"
    assert resp.json()["approved_by"] is not None


def test_yonetici_kendi_takimini_onaylar_baskasini_onaylayamaz(client, session):
    team_a, _, devs_a, mgr_a = make_team(session, name="A", devs=("a1",))
    team_b, _, devs_b, mgr_b = make_team(session, name="B", devs=("b1",))
    # A takımı yöneticisi (mgr_a) bir kullanıcı hesabına bağlı
    mgr_h = _headers(client, session, "mgra@corp.local", developer=mgr_a)
    # A'daki çalışan izin ister
    emp_a = _headers(client, session, "a1@corp.local", developer=devs_a[0])
    la = client.post("/api/user/leave-requests", headers=emp_a, json=_leave_body()).json()["id"]
    # B'deki çalışan izin ister
    emp_b = _headers(client, session, "b1@corp.local", developer=devs_b[0])
    lb = client.post("/api/user/leave-requests", headers=emp_b, json=_leave_body()).json()["id"]
    # A yöneticisi yalnız A'yı görür
    ids = {x["id"] for x in client.get("/api/admin/leave-requests", headers=mgr_h).json()}
    assert la in ids and lb not in ids
    # Kendi takımını onaylar
    assert client.put(f"/api/admin/leave-requests/{la}", headers=mgr_h,
                      json={"decision": "approve"}).status_code == 200
    # Başka takımı onaylayamaz — varlık sızmaz (404)
    assert client.put(f"/api/admin/leave-requests/{lb}", headers=mgr_h,
                      json={"decision": "approve"}).status_code == 404


# --- takvim mahremiyeti --------------------------------------------------------

def test_takvim_sebep_sizdirmaz(client, session):
    team, repo, devs, mgr = make_team(session)
    owner = _headers(client, session, "dev1@corp.local", developer=devs[0])
    leave_id = client.post("/api/user/leave-requests", headers=owner,
                           json=_leave_body(leave_type="hastalik",
                                            description="ameliyat")).json()["id"]
    admin = _headers(client, session, "admin@corp.local", role="admin")
    client.put(f"/api/admin/leave-requests/{leave_id}", headers=admin,
               json={"decision": "approve"})
    cal = client.get("/api/leave/calendar", headers=owner).json()
    assert len(cal) == 1
    entry = cal[0]
    # Operasyonel müsaitlik var; SEBEP/tür ve açıklama YOK
    assert "start_date" in entry and "end_date" in entry
    assert "leave_type" not in entry and "description" not in entry
    import json
    assert "ameliyat" not in json.dumps(cal) and "hastalik" not in json.dumps(cal)


def test_takvim_anonim_modda_isim_maskeli(client, session, app_env):
    from app.core.config import reset_config_cache

    team, repo, devs, mgr = make_team(session)
    owner = _headers(client, session, "dev1@corp.local", developer=devs[0])
    leave_id = client.post("/api/user/leave-requests", headers=owner,
                           json=_leave_body()).json()["id"]
    admin = _headers(client, session, "admin@corp.local", role="admin")
    client.put(f"/api/admin/leave-requests/{leave_id}", headers=admin,
               json={"decision": "approve"})
    text = app_env.read_text(encoding="utf-8").replace(
        "anonymize_individuals: false", "anonymize_individuals: true"
    )
    app_env.write_text(text, encoding="utf-8")
    reset_config_cache()
    cal = client.get("/api/leave/calendar", headers=owner).json()
    assert cal[0]["developer"].startswith("Geliştirici #")


# --- metrik entegrasyonu (asıl değer) ------------------------------------------

def test_approved_leave_dates_yalniz_onayli_ve_pencerede(client, session):
    from app.models import Leave
    from app.services.leave import approved_leave_dates

    team, repo, devs, mgr = make_team(session)
    dev = devs[0]
    # Onaylı izin: pencere içi 3 gün
    session.add(Leave(
        user_id=1, developer_id=dev.id,
        start_date=days_ago(5).date(), end_date=days_ago(3).date(),
        leave_type="yillik", status="approved",
    ))
    # Bekleyen izin: metriği ETKİLEMEMELİ
    session.add(Leave(
        user_id=1, developer_id=dev.id,
        start_date=days_ago(9).date(), end_date=days_ago(8).date(),
        leave_type="yillik", status="pending",
    ))
    session.commit()
    got = approved_leave_dates(session, dev.id, days_ago(30), NOW)
    assert len(got) == 3  # yalnız onaylı, yalnız pencere içi
    assert days_ago(8).date() not in got  # bekleyen sayılmaz


def test_cycle_time_izin_gununu_duser(client, session):
    """İzin ortada kalan bir işin cycle time'ı, izin günleri düşülerek küçülür.
    Boş izin kümesinde davranış birebir eski haliyle aynıdır."""
    from app.core.config import get_config
    from app.metrics.engine import TeamData, cycle_time
    from app.models import Task, TaskStatusTransition

    cfg = get_config()
    task = Task(source="fixture", external_id="T1", status="done")
    task.transitions = [
        TaskStatusTransition(from_status="todo", to_status="in progress",
                             changed_at=days_ago(10)),
        TaskStatusTransition(from_status="in progress", to_status="done",
                             changed_at=days_ago(2)),
    ]

    def data(leave_days):
        return TeamData(
            team=None, member_count=1, commits=[], prs=[], all_prs_count=0,
            tasks=[task], start=days_ago(30), end=NOW, leave_days=leave_days,
        )

    no_leave = cycle_time(data(set()), cfg).value       # ham süre = 8 gün
    leave_set = {days_ago(k).date() for k in (4, 5, 6, 7)}  # 4 gün, süre içinde
    with_leave = cycle_time(data(leave_set), cfg).value
    assert no_leave == pytest.approx(8.0, abs=0.1)
    assert with_leave == pytest.approx(4.0, abs=0.1)
    assert with_leave < no_leave
