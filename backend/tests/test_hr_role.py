"""İnsan Kaynakları (hr) rolü — yetki sınırı testleri.

HR: çalışan rehberi + izin özeti/onayı + kapasite = 200.
HR ERİŞMEZ: entegrasyon/AI kod/denetim/rol değiştirme/bireysel performans = 403.
HR yalnız role=user oluşturur/sıfırlar; admin/hr/owner hedefi 403.
Owner korumaları HR ile de bozulmaz.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, email, role, *, is_owner=False, password="parola1"):
    from app.core.security import hash_password
    from app.models import Developer, User

    dev = Developer(display_name=email.split("@")[0], external_ids={}, anonymizable=True)
    session.add(dev)
    session.flush()
    now = datetime.now(timezone.utc)
    u = User(
        email=email.lower(), password_hash=hash_password(password), role=role,
        is_owner=is_owner, developer_id=dev.id, is_active=True,
        must_change_password=False, created_at=now, updated_at=now,
    )
    session.add(u)
    session.commit()
    return u


def _token(client, email, password="parola1"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def actors(client, session):
    owner = _mk_user(session, "owner@x.com", "admin", is_owner=True)
    admin = _mk_user(session, "admin@x.com", "admin")
    hr = _mk_user(session, "hr@x.com", "hr")
    emp = _mk_user(session, "emp@x.com", "user")
    return {
        "owner": owner, "admin": admin, "hr": hr, "emp": emp,
        "owner_t": _token(client, "owner@x.com"),
        "admin_t": _token(client, "admin@x.com"),
        "hr_t": _token(client, "hr@x.com"),
        "emp_t": _token(client, "emp@x.com"),
    }


# --- HR erişir: rehber + izin özeti + kapasite = 200 -------------------------

def test_hr_calisan_listesi_200(client, actors):
    r = client.get("/api/auth/employees", headers=_auth(actors["hr_t"]))
    assert r.status_code == 200
    assert len(r.json()) == 4


def test_hr_izin_ozeti_200(client, actors):
    r = client.get("/api/leaves/summary?month=2026-07", headers=_auth(actors["hr_t"]))
    assert r.status_code == 200


def test_hr_izinleri_hepsini_gorur(client, actors):
    r = client.get("/api/leaves?month=2026-07", headers=_auth(actors["hr_t"]))
    assert r.status_code == 200


# --- HR erişmez: admin-özel = 403 -------------------------------------------

def test_hr_entegrasyon_ayarlari_403(client, actors):
    r = client.get("/api/admin/sources", headers=_auth(actors["hr_t"]))
    assert r.status_code == 403


def test_hr_denetim_logu_403(client, actors):
    r = client.get("/api/admin/audit", headers=_auth(actors["hr_t"]))
    assert r.status_code == 403


def test_hr_rol_degistiremez_403(client, actors):
    uid = actors["emp"].id
    r = client.patch(f"/api/auth/employees/{uid}", json={"role": "admin"},
                     headers=_auth(actors["hr_t"]))
    assert r.status_code == 403


def test_hr_hesap_silemez_403(client, actors):
    uid = actors["emp"].id
    r = client.delete(f"/api/auth/employees/{uid}", headers=_auth(actors["hr_t"]))
    assert r.status_code == 403


def test_hr_bireysel_performans_403(client, actors, session):
    # code-analysis kişisel çalıştırma admin-özel
    r = client.post(f"/api/admin/code-analysis/run-developer/{actors['emp'].developer_id}",
                    headers=_auth(actors["hr_t"]))
    assert r.status_code == 403


# --- HR yalnız user oluşturur/sıfırlar --------------------------------------

def test_hr_user_olusturur_201(client, actors):
    r = client.post("/api/auth/employees", headers=_auth(actors["hr_t"]),
                    json={"display_name": "Yeni", "email": "yeni@x.com",
                          "password": "parola123456", "role": "user"})
    assert r.status_code == 201
    assert r.json()["role"] == "user"


def test_hr_admin_olusturamaz_403(client, actors):
    r = client.post("/api/auth/employees", headers=_auth(actors["hr_t"]),
                    json={"display_name": "X", "email": "x@x.com",
                          "password": "parola123456", "role": "admin"})
    assert r.status_code == 403


def test_hr_hr_olusturamaz_403(client, actors):
    r = client.post("/api/auth/employees", headers=_auth(actors["hr_t"]),
                    json={"display_name": "X", "email": "x2@x.com",
                          "password": "parola123456", "role": "hr"})
    assert r.status_code == 403


def test_hr_user_parolasi_sifirlar_200(client, actors):
    uid = actors["emp"].id
    r = client.post(f"/api/auth/employees/{uid}/password", headers=_auth(actors["hr_t"]),
                    json={"new_password": "yeniparola"})
    assert r.status_code == 200


def test_hr_admin_parolasi_sifirlayamaz_403(client, actors):
    uid = actors["admin"].id
    r = client.post(f"/api/auth/employees/{uid}/password", headers=_auth(actors["hr_t"]),
                    json={"new_password": "yeniparola"})
    assert r.status_code == 403


def test_hr_owner_parolasi_sifirlayamaz_403(client, actors):
    uid = actors["owner"].id
    r = client.post(f"/api/auth/employees/{uid}/password", headers=_auth(actors["hr_t"]),
                    json={"new_password": "yeniparola"})
    assert r.status_code == 403


# --- İzin onay akışı ---------------------------------------------------------

def test_izin_istegi_pending_sonra_hr_onaylar(client, actors):
    # Çalışan kendi izin isteğini açar → pending
    r = client.post("/api/leaves", headers=_auth(actors["emp_t"]),
                    json={"start_date": "2026-07-10", "end_date": "2026-07-12",
                          "leave_type": "annual"})
    assert r.status_code == 201
    assert r.json()["status"] == "pending"
    lid = r.json()["id"]

    # HR onay kuyruğunda görür
    q = client.get("/api/leaves/pending", headers=_auth(actors["hr_t"]))
    assert q.status_code == 200
    assert any(x["id"] == lid for x in q.json())

    # HR onaylar
    d = client.post(f"/api/leaves/{lid}/decision", headers=_auth(actors["hr_t"]),
                    json={"decision": "approved"})
    assert d.status_code == 200
    assert d.json()["status"] == "approved"


def test_hr_ekledigi_izin_dogrudan_approved(client, actors):
    r = client.post("/api/leaves", headers=_auth(actors["hr_t"]),
                    json={"start_date": "2026-07-15", "end_date": "2026-07-16",
                          "leave_type": "annual", "target_user_id": actors["emp"].id})
    assert r.status_code == 201
    assert r.json()["status"] == "approved"


def test_user_izin_karar_veremez_403(client, actors):
    r = client.post("/api/leaves", headers=_auth(actors["emp_t"]),
                    json={"start_date": "2026-07-10", "end_date": "2026-07-12",
                          "leave_type": "annual"})
    lid = r.json()["id"]
    d = client.post(f"/api/leaves/{lid}/decision", headers=_auth(actors["emp_t"]),
                    json={"decision": "approved"})
    assert d.status_code == 403


def test_directory_hesaplarla_tutarli(client, actors):
    # Bireysel görünüm kişi listesi = hesaba bağlı aktif çalışanların developer'ları.
    dir_ids = {p["id"] for p in client.get("/api/directory", headers=_auth(actors["admin_t"])).json()}
    emps = client.get("/api/auth/employees", headers=_auth(actors["admin_t"])).json()
    acct_dev_ids = {u["developer_id"] for u in emps if u["developer_id"] and u["is_active"]}
    assert dir_ids == acct_dev_ids
    assert len(dir_ids) > 0


def test_bekleyen_izin_hr_bildirimi(client, actors):
    # Çalışan pending istek açar → admin + hr bildirim alır.
    client.post("/api/leaves", headers=_auth(actors["emp_t"]),
                json={"start_date": "2026-07-10", "end_date": "2026-07-11",
                      "leave_type": "annual"})
    n = client.get("/api/me/notifications", headers=_auth(actors["hr_t"]))
    assert n.status_code == 200
    kinds = [x["kind"] for x in n.json()["items"]]
    assert "leave_pending" in kinds


# --- İK istihdam alanları (işe giriş + izin hakkı) --------------------------

def test_hr_istihdam_alani_gunceller(client, actors):
    uid = actors["emp"].id
    r = client.patch(f"/api/auth/employees/{uid}/employment", headers=_auth(actors["hr_t"]),
                     json={"hire_date": "2024-03-01", "annual_allowance": 20})
    assert r.status_code == 200
    assert r.json()["hire_date"] == "2024-03-01"
    assert r.json()["annual_allowance"] == 20


def test_user_istihdam_alani_guncelleyemez_403(client, actors):
    uid = actors["emp"].id
    r = client.patch(f"/api/auth/employees/{uid}/employment", headers=_auth(actors["emp_t"]),
                     json={"annual_allowance": 99})
    assert r.status_code == 403


# --- İzin bakiyesi -----------------------------------------------------------

def test_izin_bakiyesi_hesabi(client, actors):
    uid = actors["emp"].id
    # Hak = 20 gün ver.
    client.patch(f"/api/auth/employees/{uid}/employment", headers=_auth(actors["hr_t"]),
                 json={"annual_allowance": 20})
    # HR 5 günlük onaylı annual izin ekler (2026-07-06 → 07-10 = 5 gün).
    client.post("/api/leaves", headers=_auth(actors["hr_t"]),
                json={"start_date": "2026-07-06", "end_date": "2026-07-10",
                      "leave_type": "annual", "target_user_id": uid})
    b = client.get("/api/leaves/balances?year=2026", headers=_auth(actors["hr_t"]))
    assert b.status_code == 200
    rec = next(x for x in b.json()["balances"] if x["user_id"] == uid)
    assert rec["allowance"] == 20
    assert rec["used"] == 5
    assert rec["remaining"] == 15


def test_user_bakiye_goremez_403(client, actors):
    r = client.get("/api/leaves/balances", headers=_auth(actors["emp_t"]))
    assert r.status_code == 403


# --- Login brute-force koruması ----------------------------------------------

def test_login_brute_force_kilit(client, session):
    _mk_user(session, "kilit@x.com", "user", password="dogruparola")
    # 5 yanlış deneme.
    for _ in range(5):
        r = client.post("/api/auth/login", json={"email": "kilit@x.com", "password": "yanlis"})
        assert r.status_code == 401
    # 6. deneme (doğru parola bile) kilit nedeniyle 429.
    r = client.post("/api/auth/login", json={"email": "kilit@x.com", "password": "dogruparola"})
    assert r.status_code == 429


def test_login_basarili_sayaci_sifirlar(client, session):
    _mk_user(session, "sayac@x.com", "user", password="dogruparola")
    for _ in range(3):
        client.post("/api/auth/login", json={"email": "sayac@x.com", "password": "yanlis"})
    # Doğru giriş sayacı sıfırlar → sonraki yanlışlar tekrar baştan sayılır.
    ok = client.post("/api/auth/login", json={"email": "sayac@x.com", "password": "dogruparola"})
    assert ok.status_code == 200
    # Tek yanlış deneme kilitlemez (sayaç sıfırlandı).
    r = client.post("/api/auth/login", json={"email": "sayac@x.com", "password": "yanlis"})
    assert r.status_code == 401
    ok2 = client.post("/api/auth/login", json={"email": "sayac@x.com", "password": "dogruparola"})
    assert ok2.status_code == 200
