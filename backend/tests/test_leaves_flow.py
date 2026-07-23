"""İzin akışı: istek → onay/red (gerekçeli) → takvim + çalışana bildirim.

- Çalışan create -> pending (kendi kendine onaylanmaz).
- Red note olmadan 422; note ile 200 + decision_note yazılır.
- Karar sonrası izin sahibine bildirim düşer (redde gerekçeyle).
- Takvim: rejected başkasına görünmez; başkasının decision_note'u sızmaz.
- /mine reddedileni gerekçesiyle döner.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, email, role="user", *, team_id=None, password="parola1"):
    from app.core.security import hash_password
    from app.models import Developer, TeamMembership, User

    dev = Developer(display_name=email.split("@")[0], external_ids={}, anonymizable=True)
    session.add(dev)
    session.flush()
    if team_id is not None:
        session.add(TeamMembership(team_id=team_id, developer_id=dev.id, role="member"))
    now = datetime.now(timezone.utc)
    u = User(email=email.lower(), password_hash=hash_password(password), role=role,
             developer_id=dev.id, is_active=True, must_change_password=False,
             created_at=now, updated_at=now)
    session.add(u)
    session.commit()
    return u


def _team(session, name="T1"):
    from app.models import Team

    t = Team(name=name)
    session.add(t)
    session.commit()
    return t


def _token(client, email, password="parola1"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _month():
    return date.today().strftime("%Y-%m")


def _mkleave(client, tok, **kw):
    body = {"start_date": date.today().isoformat(), "end_date": date.today().isoformat(),
            "leave_type": "annual", **kw}
    return client.post("/api/leaves", json=body, headers=_auth(tok))


def test_calisan_istegi_pending(client, session):
    _mk_user(session, "emp@x.com")
    t = _token(client, "emp@x.com")
    r = _mkleave(client, t, description="tatil")
    assert r.status_code == 201
    assert r.json()["status"] == "pending"


def test_red_gerekce_zorunlu(client, session):
    _mk_user(session, "emp@x.com")
    _mk_user(session, "admin@x.com", role="admin")
    et = _token(client, "emp@x.com")
    at = _token(client, "admin@x.com")
    lid = _mkleave(client, et).json()["id"]

    # Gerekçesiz red -> 422.
    r0 = client.post(f"/api/leaves/{lid}/decision", json={"decision": "rejected"}, headers=_auth(at))
    assert r0.status_code == 422
    # Boş gerekçe -> 422.
    r1 = client.post(f"/api/leaves/{lid}/decision", json={"decision": "rejected", "note": "   "}, headers=_auth(at))
    assert r1.status_code == 422
    # Gerekçeli red -> 200 + decision_note yazılır.
    r2 = client.post(f"/api/leaves/{lid}/decision",
                     json={"decision": "rejected", "note": "kapasite düşük"}, headers=_auth(at))
    assert r2.status_code == 200 and r2.json()["status"] == "rejected"

    from app.models import Leave
    assert session.get(Leave, lid).decision_note == "kapasite düşük"


def test_karar_bildirimi_calisana_duser(client, session):
    emp = _mk_user(session, "emp@x.com")
    _mk_user(session, "admin@x.com", role="admin")
    et = _token(client, "emp@x.com")
    at = _token(client, "admin@x.com")
    lid = _mkleave(client, et).json()["id"]
    client.post(f"/api/leaves/{lid}/decision",
                json={"decision": "rejected", "note": "başka hafta dene"}, headers=_auth(at))

    from sqlalchemy import select
    from app.models import Notification
    notifs = session.scalars(
        select(Notification).where(Notification.user_id == emp.id,
                                   Notification.kind == "leave_decision")
    ).all()
    assert len(notifs) == 1
    assert "başka hafta dene" in (notifs[0].body or "")


def test_mine_reddedileni_gerekceyle_doner(client, session):
    _mk_user(session, "emp@x.com")
    _mk_user(session, "admin@x.com", role="admin")
    et = _token(client, "emp@x.com")
    at = _token(client, "admin@x.com")
    lid = _mkleave(client, et).json()["id"]
    client.post(f"/api/leaves/{lid}/decision",
                json={"decision": "rejected", "note": "gerekçe X"}, headers=_auth(at))
    mine = client.get("/api/leaves/mine", headers=_auth(et)).json()
    row = next(m for m in mine if m["id"] == lid)
    assert row["status"] == "rejected" and row["decision_note"] == "gerekçe X"


def test_takvimde_reddedilen_ve_gerekce_baskasina_sizmaz(client, session):
    team = _team(session)
    a = _mk_user(session, "a@x.com", team_id=team.id)  # noqa: F841
    b = _mk_user(session, "b@x.com", team_id=team.id)  # aynı takım
    _mk_user(session, "admin@x.com", role="admin")
    at = _token(client, "admin@x.com")
    bt = _token(client, "b@x.com")

    # a bir izin ister, admin onaylar (not ile).
    aid = _mkleave(client, _token(client, "a@x.com")).json()["id"]
    client.post(f"/api/leaves/{aid}/decision",
                json={"decision": "approved", "note": "gizli not"}, headers=_auth(at))
    # a ikinci izin ister, admin reddeder.
    rid = _mkleave(client, _token(client, "a@x.com"),
                   start_date=date.today().isoformat()).json()["id"]
    client.post(f"/api/leaves/{rid}/decision",
                json={"decision": "rejected", "note": "gizli red"}, headers=_auth(at))

    # b (takım arkadaşı) takvimi görür: a'nın ONAYLI izni görünür ama karar
    # notu SIZMAZ; reddedilen izin hiç görünmez.
    rows = client.get(f"/api/leaves?month={_month()}", headers=_auth(bt)).json()
    ids = {r["id"] for r in rows}
    assert aid in ids and rid not in ids
    approved_row = next(r for r in rows if r["id"] == aid)
    assert approved_row["decision_note"] is None
