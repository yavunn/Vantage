"""Bordro / özlük evrakı akışı.

Odak noktaları:
- GİZLİLİK: çalışan başkasının belgesini ne listeler ne indirir (özel nitelikli
  veri — sağlık raporu, icra yazısı).
- DOSYA GÜVENLİĞİ: uzantı allowlist'i, boyut sınırı, yol geçişi denemesi.
- İŞ KURALI: türe göre zorunlu alanlar, karar akışı, eksik evrak listesi.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_team


@pytest.fixture()
def client(app_env, tmp_path, monkeypatch):
    """Evrak kökü test dizinine alınır — testler gerçek data/ klasörüne yazmasın."""
    text = app_env.read_text(encoding="utf-8")
    storage = (tmp_path / "hr-docs").as_posix()
    app_env.write_text(
        text + f"\nhr_documents:\n  storage_dir: '{storage}'\n  max_file_mb: 1\n",
        encoding="utf-8",
    )
    from app.core.config import reset_config_cache
    reset_config_cache()
    from app.main import app

    return TestClient(app)


def _mk_user(session, dev, email, role="user", password="parola1"):
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    u = User(
        email=email.lower(), password_hash=hash_password(password), role=role,
        developer_id=dev.id if dev else None, is_active=True,
        must_change_password=False, created_at=now, updated_at=now,
    )
    session.add(u)
    session.commit()
    return u


def _auth(client, email, password="parola1"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _pdf(name="rapor.pdf", size=64):
    return {"file": (name, io.BytesIO(b"%PDF-1.4\n" + b"x" * size), "application/pdf")}


def _upload(client, headers, doc_type="sick_report", **form):
    data = {"doc_type": doc_type}
    data.update({k: str(v) for k, v in form.items() if v is not None})
    return client.post("/api/documents", headers=headers, files=_pdf(), data=data)


# --- katalog ------------------------------------------------------------------


def test_katalog_bordroya_etkiyi_bildiriyor(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    h = _auth(client, "u0@x.com")
    body = client.get("/api/documents/types", headers=h).json()
    types = {t["key"]: t for t in body["types"]}
    # İstirahat raporu bordroyu etkiler ve tarih ister (gün hesabı).
    assert types["sick_report"]["affects_payroll"] is True
    assert types["sick_report"]["needs_dates"] is True
    # İcra kesintisi dönem ister (hangi bordrodan kesilecek).
    assert types["garnishment"]["needs_period"] is True
    # Özlük zorunluları işaretli.
    assert types["employment_contract"]["required"] is True
    assert {c["key"] for c in body["categories"]} >= {"leave", "payroll", "personnel"}


def test_katalog_ingilizce_donuyor(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    h = {**_auth(client, "u0@x.com"), "Accept-Language": "en-US,en;q=0.9"}
    types = {t["key"]: t for t in client.get("/api/documents/types", headers=h).json()["types"]}
    assert types["sick_report"]["label"] == "Medical leave report"


# --- yükleme + doğrulama ------------------------------------------------------


def test_calisan_kendi_belgesini_yukler(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    h = _auth(client, "u0@x.com")
    r = _upload(client, h, period="2026-08", start_date="2026-08-03", end_date="2026-08-05",
                note="Grip")
    assert r.status_code == 201, r.text
    rows = client.get("/api/documents", headers=h).json()
    assert len(rows) == 1
    assert rows[0]["doc_type"] == "sick_report"
    assert rows[0]["status"] == "pending"
    assert rows[0]["affects_payroll"] is True
    assert rows[0]["can_delete"] is True   # henüz incelenmedi
    assert rows[0]["can_decide"] is False  # çalışan kendi belgesine karar veremez


def test_zorunlu_alanlar_turden_geliyor(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    h = _auth(client, "u0@x.com")
    # Rapor tarihsiz kabul edilmez.
    assert _upload(client, h, "sick_report", period="2026-08").status_code == 422
    # İcra kesintisi dönemsiz kabul edilmez.
    assert _upload(client, h, "garnishment").status_code == 422
    # Sözleşme ikisini de istemez.
    assert _upload(client, h, "employment_contract").status_code == 201


def test_bilinmeyen_tur_reddedilir(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    h = _auth(client, "u0@x.com")
    assert _upload(client, h, "uydurma_tur").status_code == 422


def test_bitis_baslangictan_once_olamaz(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    h = _auth(client, "u0@x.com")
    r = _upload(client, h, period="2026-08", start_date="2026-08-09", end_date="2026-08-03")
    assert r.status_code == 422


# --- dosya güvenliği ----------------------------------------------------------


def test_izinsiz_uzanti_reddedilir(client, session):
    """Allowlist dışı biçim (ör. .svg / .html) yüklenemez: yüklenen dosya aynı
    origin'den servis ediliyor, tarayıcıda çalışan biçim depolanmış XSS olurdu."""
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    h = _auth(client, "u0@x.com")
    r = client.post(
        "/api/documents", headers=h,
        files={"file": ("kotucuk.svg", io.BytesIO(b"<svg onload=alert(1)>"), "image/svg+xml")},
        data={"doc_type": "employment_contract"},
    )
    assert r.status_code == 422
    assert "svg" in r.json()["detail"]


def test_boyut_siniri_uygulanir(client, session):
    """Sınır (testte 1 MB) aşılırsa 413 ve diske yarım dosya BIRAKILMAZ."""
    from app.services.hr_documents import storage_root

    team, repo, devs, mgr = make_team(session)
    u = _mk_user(session, devs[0], "u0@x.com")
    h = _auth(client, "u0@x.com")
    big = b"x" * (2 * 1024 * 1024)
    r = client.post(
        "/api/documents", headers=h,
        files={"file": ("buyuk.pdf", io.BytesIO(big), "application/pdf")},
        data={"doc_type": "employment_contract"},
    )
    assert r.status_code == 413
    user_dir = storage_root() / str(u.id)
    assert not user_dir.exists() or not any(user_dir.iterdir()), "yarım dosya diskte kaldı"


def test_dosya_adi_yol_gecisi_tasimaz(client, session):
    """Kullanıcının verdiği ad diske YAZILMAZ: disk adını sunucu üretir."""
    from app.services.hr_documents import storage_root

    team, repo, devs, mgr = make_team(session)
    u = _mk_user(session, devs[0], "u0@x.com")
    h = _auth(client, "u0@x.com")
    r = client.post(
        "/api/documents", headers=h,
        files={"file": ("../../../gizli.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        data={"doc_type": "employment_contract"},
    )
    assert r.status_code == 201, r.text
    files = list((storage_root() / str(u.id)).iterdir())
    assert len(files) == 1
    assert files[0].name.endswith(".pdf")
    assert ".." not in files[0].name and "/" not in files[0].name
    # Gösterim adı da temizlenmiş olmalı (dizin bileşenleri atılır).
    assert client.get("/api/documents", headers=h).json()[0]["file_name"] == "gizli.pdf"


def test_indirme_her_zaman_eklenti_olarak_doner(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    h = _auth(client, "u0@x.com")
    doc_id = _upload(client, h, "employment_contract").json()["id"]
    r = client.get(f"/api/documents/{doc_id}/download", headers=h)
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"


# --- gizlilik -----------------------------------------------------------------


def test_calisan_baskasinin_belgesini_goremez(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    u1 = _mk_user(session, devs[1], "u1@x.com")
    h0, h1 = _auth(client, "u0@x.com"), _auth(client, "u1@x.com")
    doc_id = _upload(client, h1, "employment_contract").json()["id"]

    # Liste: kendi kaydı yok, başkasınınki sızmıyor.
    assert client.get("/api/documents", headers=h0).json() == []
    # Açık filtre: sessiz boş liste değil, net 403.
    assert client.get(f"/api/documents?user_id={u1.id}", headers=h0).status_code == 403
    # İndirme ve silme de kapalı.
    assert client.get(f"/api/documents/{doc_id}/download", headers=h0).status_code == 403
    assert client.delete(f"/api/documents/{doc_id}", headers=h0).status_code == 403


def test_takim_yoneticisi_belge_goremez(client, session):
    """İzin takviminde yönetici kapasiteyi görüyor; burada görülecek şey sağlık
    raporu — yöneticilik bunu gerektirmez (yalnız admin/İK)."""
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, mgr, "mgr@x.com")
    h0, hm = _auth(client, "u0@x.com"), _auth(client, "mgr@x.com")
    doc_id = _upload(client, h0, "employment_contract").json()["id"]
    assert client.get(f"/api/documents/{doc_id}/download", headers=hm).status_code == 403
    assert client.get("/api/documents/pending", headers=hm).status_code == 403
    assert client.get("/api/documents/checklist", headers=hm).status_code == 403


def test_kimliksiz_erisim_reddedilir(client, session):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents/types").status_code == 401


def test_ik_herkesin_belgesini_gorur_ve_indirir(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")
    doc_id = _upload(client, h0, "employment_contract").json()["id"]
    rows = client.get("/api/documents", headers=hik).json()
    assert len(rows) == 1 and rows[0]["can_decide"] is True
    assert client.get(f"/api/documents/{doc_id}/download", headers=hik).status_code == 200


def test_baskasinin_belgesini_indirmek_denetime_yazilir(client, session):
    """Özel nitelikli veriye erişimde 'kim baktı' sorusunun cevabı olmalı."""
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "admin@x.com", role="admin")
    h0, ha = _auth(client, "u0@x.com"), _auth(client, "admin@x.com")
    doc_id = _upload(client, h0, "sick_report", period="2026-08",
                     start_date="2026-08-01", end_date="2026-08-02").json()["id"]
    client.get(f"/api/documents/{doc_id}/download", headers=ha)
    actions = [r["action"] for r in client.get("/api/admin/audit", headers=ha).json()]
    assert "document_download" in actions
    # Kendi belgesini indirmek denetime YAZILMAZ (gözetim değil, erişim izi).
    client.get(f"/api/documents/{doc_id}/download", headers=h0)
    downloads = [r for r in client.get("/api/admin/audit", headers=ha).json()
                 if r["action"] == "document_download"]
    assert len(downloads) == 1


# --- karar akışı --------------------------------------------------------------


def test_ik_karar_verir_ve_calisana_bildirim_duser(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")
    doc_id = _upload(client, h0, "employment_contract").json()["id"]

    r = client.post(f"/api/documents/{doc_id}/decision", headers=hik,
                    json={"decision": "approved"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    inbox = client.get("/api/me/notifications", headers=h0).json()
    assert "document_decision" in [n["kind"] for n in inbox["items"]]


def test_red_gerekce_ister(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")
    doc_id = _upload(client, h0, "employment_contract").json()["id"]
    assert client.post(f"/api/documents/{doc_id}/decision", headers=hik,
                       json={"decision": "rejected"}).status_code == 422
    ok = client.post(f"/api/documents/{doc_id}/decision", headers=hik,
                     json={"decision": "rejected", "note": "Okunmuyor, tekrar tarat"})
    assert ok.status_code == 200
    # Çalışan gerekçeyi görebilmeli — yoksa aynı belgeyi tekrar yükler.
    row = client.get("/api/documents", headers=h0).json()[0]
    assert row["review_note"] == "Okunmuyor, tekrar tarat"


def test_incelenmis_belge_calisan_tarafindan_silinemez(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")
    doc_id = _upload(client, h0, "employment_contract").json()["id"]
    client.post(f"/api/documents/{doc_id}/decision", headers=hik, json={"decision": "approved"})
    assert client.delete(f"/api/documents/{doc_id}", headers=h0).status_code == 403
    # İK silebilir.
    assert client.delete(f"/api/documents/{doc_id}", headers=hik).status_code == 200


def test_silme_diskteki_dosyayi_da_kaldirir(client, session):
    from app.services.hr_documents import storage_root

    team, repo, devs, mgr = make_team(session)
    u = _mk_user(session, devs[0], "u0@x.com")
    h0 = _auth(client, "u0@x.com")
    doc_id = _upload(client, h0, "employment_contract").json()["id"]
    assert len(list((storage_root() / str(u.id)).iterdir())) == 1
    assert client.delete(f"/api/documents/{doc_id}", headers=h0).status_code == 200
    assert list((storage_root() / str(u.id)).iterdir()) == []


# --- İK görünümleri -----------------------------------------------------------


def test_eksik_evrak_listesi(client, session):
    team, repo, devs, mgr = make_team(session)
    u0 = _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")

    body = client.get("/api/documents/checklist", headers=hik).json()
    row = next(r for r in body["rows"] if r["user_id"] == u0.id)
    assert row["approved_count"] == 0
    assert any(m["key"] == "employment_contract" for m in row["missing"])

    doc_id = _upload(client, h0, "employment_contract").json()["id"]
    # Bekleyen belge "eksik" sayılmaz ama ayrı gösterilir.
    row = next(r for r in client.get("/api/documents/checklist", headers=hik).json()["rows"]
               if r["user_id"] == u0.id)
    assert not any(m["key"] == "employment_contract" for m in row["missing"])
    assert any(p["key"] == "employment_contract" for p in row["pending"])

    # Reddedilen belge yeniden EKSİK sayılır (yüklenmiş ama geçerli değil).
    client.post(f"/api/documents/{doc_id}/decision", headers=hik,
                json={"decision": "rejected", "note": "Eksik sayfa"})
    row = next(r for r in client.get("/api/documents/checklist", headers=hik).json()["rows"]
               if r["user_id"] == u0.id)
    assert any(m["key"] == "employment_contract" for m in row["missing"])


def test_donem_ozeti_bordroyu_bekleten_belgeyi_sayar(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")
    _upload(client, h0, "sick_report", period="2026-08",
            start_date="2026-08-03", end_date="2026-08-05")
    _upload(client, h0, "garnishment", period="2026-08")
    # Başka dönem — bu özete girmemeli.
    _upload(client, h0, "garnishment", period="2026-07")

    body = client.get("/api/documents/summary?period=2026-08", headers=hik).json()
    assert body["total"] == 2
    assert body["blocking_payroll"] == 2  # ikisi de bordroyu etkiliyor ve bekliyor
    assert {r["doc_type"] for r in body["by_type"]} == {"sick_report", "garnishment"}


def test_gecersiz_donem_bicimi_reddedilir(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, None, "ik@x.com", role="hr")
    hik = _auth(client, "ik@x.com")
    assert client.get("/api/documents/summary?period=2026-13", headers=hik).status_code == 422
    assert client.get("/api/documents/summary?period=agustos", headers=hik).status_code == 422


def test_calisan_kendi_eksiklerini_gorur(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    h0 = _auth(client, "u0@x.com")
    body = client.get("/api/documents/mine/summary", headers=h0).json()
    assert body["required_total"] > 0
    assert body["approved_count"] == 0
    assert any(m["key"] == "id_copy" for m in body["missing"])


def test_ik_baskasi_adina_yukler_calisan_kendi_kaydinda_gorur(client, session):
    team, repo, devs, mgr = make_team(session)
    u0 = _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")
    r = _upload(client, hik, "sgk_entry", target_user_id=u0.id)
    assert r.status_code == 201, r.text
    rows = client.get("/api/documents", headers=h0).json()
    assert len(rows) == 1 and rows[0]["uploaded_by_me"] is False


def test_calisan_baskasi_adina_yukleyemez(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    u1 = _mk_user(session, devs[1], "u1@x.com")
    h0 = _auth(client, "u0@x.com")
    assert _upload(client, h0, "sgk_entry", target_user_id=u1.id).status_code == 403


def test_hesap_silinince_dosyalar_diskten_imha_edilir(client, session):
    """KVKK veri minimizasyonu: silinen çalışanın sağlık raporu diskte kalmamalı."""
    from app.services.hr_documents import storage_root

    team, repo, devs, mgr = make_team(session)
    u0 = _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "admin@x.com", role="admin")
    h0, ha = _auth(client, "u0@x.com"), _auth(client, "admin@x.com")
    _upload(client, h0, "sick_report", period="2026-08",
            start_date="2026-08-01", end_date="2026-08-02")
    assert (storage_root() / str(u0.id)).is_dir()

    assert client.delete(f"/api/auth/employees/{u0.id}", headers=ha).status_code == 200
    assert not (storage_root() / str(u0.id)).exists()


# --- izin (Leave) senkronu -----------------------------------------------------
# Amaç: İK aynı başlangıç/bitiş tarihini hem İzin panosuna hem Evrak formuna
# ELLE girmesin. İki yön test edilir: belge-önce (rapor yüklenir, onaylanınca
# izin OTOMATİK oluşur) ve izin-önce (izin isteği zaten var, belge ona
# BAĞLANIR, onay ikisini birden çözer).


def test_belge_onaylaninca_baglantisiz_izin_otomatik_olusur(client, session):
    """Belge-önce akış: hiçbir Leave yokken rapor yüklenir; onay bir tane
    OLUŞTURUR ve belgeyi ona bağlar."""
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")

    doc_id = _upload(client, h0, "sick_report", period="2026-08",
                     start_date="2026-08-03", end_date="2026-08-05").json()["id"]
    assert client.get("/api/leaves?month=2026-08", headers=h0).json() == []

    r = client.post(f"/api/documents/{doc_id}/decision", headers=hik, json={"decision": "approved"})
    assert r.status_code == 200
    assert r.json()["leave_sync"] == "created"

    leaves = client.get("/api/leaves?month=2026-08", headers=h0).json()
    assert len(leaves) == 1
    lv = leaves[0]
    assert lv["leave_type"] == "sick"
    assert lv["status"] == "approved"
    assert lv["start_date"] == "2026-08-03" and lv["end_date"] == "2026-08-05"
    assert lv["has_document"] is True

    doc = client.get("/api/documents", headers=h0).json()[0]
    assert doc["leave_id"] == lv["id"]
    assert doc["linked_leave"] == {
        "id": lv["id"], "status": "approved",
        "start_date": "2026-08-03", "end_date": "2026-08-05",
    }


def test_reddedilen_belge_izin_olusturmaz(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")
    doc_id = _upload(client, h0, "sick_report", period="2026-08",
                     start_date="2026-08-03", end_date="2026-08-05").json()["id"]

    r = client.post(f"/api/documents/{doc_id}/decision", headers=hik,
                    json={"decision": "rejected", "note": "Okunmuyor"})
    assert r.json()["leave_sync"] is None
    assert client.get("/api/leaves?month=2026-08", headers=h0).json() == []
    assert client.get("/api/documents", headers=h0).json()[0]["leave_id"] is None


def test_izin_isteğine_bağlı_belge_onaylaninca_izni_de_onaylar(client, session):
    """İzin-önce akış: çalışan önce Leaves panelinden izin isteği açar (pending),
    sonra kanıtı yükleyip o isteğe BAĞLAR. Belge onayı tarihi tekrar sormaz ve
    tek kararla ikisini de çözer — İK iki ayrı ekranda karar vermez."""
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")

    lv_id = client.post("/api/leaves", headers=h0, json={
        "start_date": "2026-08-10", "end_date": "2026-08-12", "leave_type": "sick",
    }).json()["id"]
    assert client.get("/api/leaves/mine", headers=h0).json()[0]["status"] == "pending"

    doc_id = _upload(client, h0, "sick_report", period="2026-08",
                     start_date="2026-08-10", end_date="2026-08-12",
                     leave_id=lv_id).json()["id"]

    r = client.post(f"/api/documents/{doc_id}/decision", headers=hik, json={"decision": "approved"})
    assert r.json()["leave_sync"] == "confirmed"

    mine = client.get("/api/leaves/mine", headers=h0).json()[0]
    assert mine["id"] == lv_id
    assert mine["status"] == "approved"
    assert mine["has_document"] is True
    # Onay bekleyen kuyrukta artık görünmemeli — belge kararı çözmüş olmalı.
    assert client.get("/api/leaves/pending", headers=hik).json() == []


def test_baskasinin_izin_kaydina_belge_baglayamaz(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, devs[1], "u1@x.com")
    h0, h1 = _auth(client, "u0@x.com"), _auth(client, "u1@x.com")
    lv_id = client.post("/api/leaves", headers=h1, json={
        "start_date": "2026-08-10", "end_date": "2026-08-10", "leave_type": "annual",
    }).json()["id"]
    r = _upload(client, h0, "sick_report", period="2026-08",
               start_date="2026-08-10", end_date="2026-08-10", leave_id=lv_id)
    assert r.status_code == 404


def test_bordroyu_etkilemeyen_belge_izin_olusturmaz(client, session):
    """"payroll"/"personnel" kategorisindeki belgeler (ör. iş sözleşmesi) izin
    değildir; onaylanmaları hiçbir Leave doğurmamalı."""
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")
    doc_id = _upload(client, h0, "employment_contract").json()["id"]
    r = client.post(f"/api/documents/{doc_id}/decision", headers=hik, json={"decision": "approved"})
    assert r.json()["leave_sync"] is None


def test_ik_baskasinin_izinlerini_by_user_ile_gorur(client, session):
    team, repo, devs, mgr = make_team(session)
    u0 = _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, None, "ik@x.com", role="hr")
    h0, hik = _auth(client, "u0@x.com"), _auth(client, "ik@x.com")
    client.post("/api/leaves", headers=h0, json={
        "start_date": "2026-08-01", "end_date": "2026-08-01", "leave_type": "annual",
    })
    rows = client.get(f"/api/leaves/by-user/{u0.id}", headers=hik).json()
    assert len(rows) == 1 and rows[0]["start_date"] == "2026-08-01"


def test_calisan_by_user_ile_baskasini_goremez(client, session):
    team, repo, devs, mgr = make_team(session)
    u0 = _mk_user(session, devs[0], "u0@x.com")
    _mk_user(session, devs[1], "u1@x.com")
    h1 = _auth(client, "u1@x.com")
    assert client.get(f"/api/leaves/by-user/{u0.id}", headers=h1).status_code == 403
