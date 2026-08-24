"""Sunucu tarafı dil desteği (Accept-Language).

Arayüzü tek başına çevirmek panoyu yarı Türkçe bırakırdı: metrik adları,
açıklamaları ve durum etiketleri API'den geliyor.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, email, role="user", password="parola12345"):
    from datetime import datetime, timezone

    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    u = User(email=email.lower(), password_hash=hash_password(password), role=role,
             is_active=True, must_change_password=False, created_at=now, updated_at=now)
    session.add(u)
    session.commit()
    return u


def _token(client, email, password="parola12345"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_dil_basligi_metrik_adlarini_cevirir(client, session):
    """Arayüzü tek başına çevirmek panoyu yarı Türkçe bırakırdı: metrik adları,
    açıklamaları ve durum etiketleri API'den geliyor."""
    from app.core.config import get_config
    from app.metrics.engine import compute_all
    from tests.conftest import make_team

    team, repo, devs, _ = make_team(session)
    compute_all(session, get_config())
    _mk_user(session, "admin@x.com", role="admin")
    auth = _token(client, "admin@x.com")

    tr = client.get(f"/api/teams/{team.id}/summary",
                    headers={**auth, "Accept-Language": "tr"}).json()
    en = client.get(f"/api/teams/{team.id}/summary",
                    headers={**auth, "Accept-Language": "en-US,en;q=0.9"}).json()

    tr_adlar = {m["key"]: m["name"] for m in tr["metrics"]}
    en_adlar = {m["key"]: m["name"] for m in en["metrics"]}
    assert tr_adlar["deployment_frequency"] == "Teslim Sıklığı"
    assert en_adlar["deployment_frequency"] == "Delivery Frequency"

    tr_etiket = {m["key"]: m["status_label"] for m in tr["metrics"]}
    en_etiket = {m["key"]: m["status_label"] for m in en["metrics"]}
    assert "Veri yetersiz" in tr_etiket.values()
    assert "Not enough data" in en_etiket.values()


def test_desteklenmeyen_dil_turkceye_duser(client, session):
    from app.core.i18n import normalize_lang

    assert normalize_lang("de-DE,de;q=0.9") == "tr"
    assert normalize_lang(None) == "tr"
    assert normalize_lang("en-GB") == "en"


def test_ingilizce_durum_etiketi_ceza_dili_kullanmaz(client, session):
    """Etik çerçeve çeviride de korunmalı: kırmızı bir ceza değil, destek
    çağrısıdır. 'bad' / 'fail' gibi bir performans dili kullanılmaz."""
    from app.core.i18n import status_labels

    en = status_labels("en")
    assert "support" in en["red"].lower()
    for kotu in ("bad", "fail", "poor"):
        assert kotu not in " ".join(en.values()).lower()


# --- API'nin İÇERİK olarak döndürdüğü metinler (tr_text / texts_en.py) --------
# Metrik adları çevriliyordu ama bireysel görünümün yarısı (genel skor etiketi,
# notlar, commit-kod eşleşmesi, 1:1 hazırlık) ve takım panosunun süreç önerileri
# İngilizce arayüzde Türkçe kalıyordu. Aşağıdakiler o yolu kilitler.

TR_HARF = set("çğışöüÇĞİŞÖÜ")


def _turkce_iz(deger, yol=""):
    """JSON gövdesinde Türkçe'ye özgü harf taşıyan dizeleri bulur."""
    out = []
    if isinstance(deger, dict):
        for k, v in deger.items():
            out += _turkce_iz(v, f"{yol}.{k}")
    elif isinstance(deger, list):
        for i, v in enumerate(deger):
            out += _turkce_iz(v, f"{yol}[{i}]")
    elif isinstance(deger, str) and any(c in TR_HARF for c in deger):
        out.append((yol, deger))
    return out


def _bireysel_veri(session):
    """Bireysel görünümü dolduran asgari veri: PR + commit (mesaj-kod
    eşleşmesi için changed_files şart)."""
    from app.models import Commit, PullRequest
    from tests.conftest import days_ago, make_team

    team, repo, devs, _ = make_team(session)
    for i in range(4):
        session.add(PullRequest(
            repo_id=repo.id, external_id=f"pr{i}", author_id=devs[0].id,
            opened_at=days_ago(10 + i), first_review_at=days_ago(5 + i),
            merged_at=days_ago(3 + i)))
        session.add(Commit(
            repo_id=repo.id, sha=f"sha{i}", author_id=devs[0].id,
            message="update", committed_at=days_ago(4 + i),
            additions=30, deletions=5, changed_files=[f"src/modul_{i}.py"]))
    session.commit()
    return team, devs[0]


def test_bireysel_gorunum_ingilizcede_turkce_metin_birakmaz(client, session):
    """Genel skor etiketi/notu, commit-kod eşleşmesi özeti ve uç notu sunucudan
    geliyor; çevrilmezse İngilizce panoda Türkçe cümleler kalırdı."""
    from app.core.config import get_config
    from app.models import User

    _team, dev = _bireysel_veri(session)
    _mk_user(session, "kisi@x.com")
    u = session.query(User).filter_by(email="kisi@x.com").one()
    u.developer_id = dev.id
    session.commit()
    get_config()
    auth = _token(client, "kisi@x.com")

    r = client.get(f"/api/developers/{dev.id}/summary",
                   headers={**auth, "Accept-Language": "en"})
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["overall"] is not None
    assert _turkce_iz(govde) == []


def test_bir_bir_hazirlik_ozeti_ingilizce_doner(client, session):
    """1:1 özeti bireysel özeti YENİDEN çağırır; dil açıkça geçilmezse
    başlıklar İngilizce, metrik adları Türkçe çıkıyordu."""
    from app.models import User

    _team, dev = _bireysel_veri(session)
    _mk_user(session, "kisi@x.com")
    u = session.query(User).filter_by(email="kisi@x.com").one()
    u.developer_id = dev.id
    session.commit()
    auth = _token(client, "kisi@x.com")

    r = client.get(f"/api/developers/{dev.id}/one-on-one",
                   headers={**auth, "Accept-Language": "en"})
    assert r.status_code == 200, r.text
    govde = r.json()
    basliklar = [b["section"] for b in govde["talking_points"]]
    assert basliklar == ["Worth celebrating", "To look at together", "A reminder"]
    assert _turkce_iz(govde["talking_points"]) == []


def test_surec_onerisi_okuma_aninda_cevrilir(client, session):
    """Öneri metni veritabanına ŞABLON olarak yazılır, parametreler ayrı durur:
    aynı satır TR isteğinde Türkçe, EN isteğinde İngilizce okunur."""
    from app.core.config import get_config
    from app.models import PullRequest
    from app.rules.engine import run_rules
    from tests.conftest import days_ago, make_team

    team, repo, devs, _ = make_team(session)
    for i in range(3):
        # İlk review 6 gün sonra: review_bottleneck eşiği (4 gün) aşılır.
        session.add(PullRequest(
            repo_id=repo.id, external_id=f"pr{i}", author_id=devs[0].id,
            opened_at=days_ago(12 + i), first_review_at=days_ago(6 + i),
            merged_at=days_ago(5 + i)))
    session.commit()
    assert run_rules(session, get_config()) > 0

    _mk_user(session, "admin@x.com", role="admin")
    auth = _token(client, "admin@x.com")

    tr = client.get(f"/api/teams/{team.id}/report?days=30",
                    headers={**auth, "Accept-Language": "tr"}).json()
    en = client.get(f"/api/teams/{team.id}/report?days=30",
                    headers={**auth, "Accept-Language": "en"}).json()

    tr_mesaj = {r["rule"]: r["message"] for r in tr["recommendations"]}
    en_mesaj = {r["rule"]: r["message"] for r in en["recommendations"]}
    assert "review_bottleneck" in tr_mesaj
    assert "gün bekliyor" in tr_mesaj["review_bottleneck"]
    assert "days on average for a first review" in en_mesaj["review_bottleneck"]
    # Sayı hem TR hem EN metinde yerine oturmalı — yer tutucu sızmamalı.
    assert "{gun}" not in en_mesaj["review_bottleneck"]
    assert "{esik}" not in tr_mesaj["review_bottleneck"]


def test_kural_sablonlari_ceviri_sozlugunde_var():
    """Kural metni değişip sözlük güncellenmezse çeviri SESSİZCE düşer ve
    İngilizce panoda Türkçe bir öneri belirir. Bu testin işi o sessizliği
    bozmak."""
    from app.core.texts_en import TEXTS_EN
    from app.rules import engine

    kaynak = __import__("inspect").getsource(engine)
    eksik = []
    for anahtar in ("PR'lar ilk review", "Son {gun} günde aynı dosyalar",
                    "Kişi başına ortalama {wip}", "Task'ların %{yuzde}",
                    "Son dönemde {sayi} kez"):
        assert anahtar in kaynak, f"kural metni değişmiş: {anahtar}"
        if not any(k.startswith(anahtar) for k in TEXTS_EN):
            eksik.append(anahtar)
    assert eksik == [], f"texts_en.py'de karşılığı yok: {eksik}"
