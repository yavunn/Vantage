"""İŞ-10/İŞ-11: Jira adaptörü gerçek kurulumda çalışmalı ve sessiz kalmamalı.

ESKİ DAVRANIŞ (üç ayrı kusur):
 1. Yalnız `Authorization: Bearer` gönderiliyordu. Jira CLOUD e-posta + API
    token ile BASIC auth ister; Bearer sadece Server/DC PAT'ında geçerli →
    Cloud'da HER istek 401.
 2. `if resp.status_code != 200: break` — 401/403/404 sessizce yutuluyordu ve
    sınıfın `warnings` listesi HİÇ YOKTU. ingest `getattr(tasks, "warnings", [])`
    ile uyarı topladığı için kullanıcı yalnız "0 task" görüyordu.
 3. `/rest/api/2/search` Jira Cloud'da kaldırıldı (yerine /rest/api/3/search/jql).
 4. story_points alanı "customfield_10016" olarak koda gömülüydü; farklı
    kurulumda sessizce None üretiyordu.
"""
from __future__ import annotations


class _Resp:
    def __init__(self, kod, govde=None):
        self.status_code = kod
        self._g = govde if govde is not None else {}
        self.text = str(self._g)

    def json(self):
        return self._g


class _Client:
    """httpx.Client yerine geçer; (yol, params) yakalar, ağa çıkmaz."""

    def __init__(self, yanitlar: dict, base_url: str = ""):
        self.yanitlar = yanitlar
        self.base_url = base_url
        self.cagrilar: list[tuple[str, dict]] = []
        self.headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        self.cagrilar.append((url, params or {}))
        return self.yanitlar.get(url, _Resp(404))


def _issue(key="PROJ-1", **fields):
    temel = {
        "summary": "iş", "status": {"name": "Done"},
        "created": "2026-07-01T10:00:00.000+0300",
        "issuetype": {"name": "Story"},
        # Varsayılan story point alanı DOLU: "alan bulunamadı" uyarısı yalnız
        # gerçekten bulunamadığında çıksın (ayrı testi var).
        "customfield_10016": 3.0,
    }
    temel.update(fields)
    return {"key": key, "fields": temel, "changelog": {"histories": []}}


def _provider(**kw):
    from app.adapters.jira import JiraProvider

    varsayilan = dict(
        base_url="https://sirket.atlassian.net", token_env="X_JIRA",
        projects=["PROJ"], auth="basic", email="kisi@sirket.com",
    )
    varsayilan.update(kw)
    p = JiraProvider(**varsayilan)
    p.token = "tok"  # ortam değişkenine bağlı kalma
    return p


def test_cloud_basic_auth_basligi_gonderir():
    import base64

    p = _provider()
    h = p._headers()
    assert h["Authorization"].startswith("Basic ")
    coz = base64.b64decode(h["Authorization"].split(" ", 1)[1]).decode()
    assert coz == "kisi@sirket.com:tok"


def test_server_bearer_auth_korunur():
    p = _provider(base_url="https://jira.sirket.local", auth="bearer")
    assert p._headers()["Authorization"] == "Bearer tok"


def test_cloud_yeni_arama_ucunu_kullanir(monkeypatch):
    """Eski /rest/api/2/search Cloud'da kaldırıldı."""
    p = _provider()
    client = _Client({"/search/jql": _Resp(200, {"issues": [_issue()], "isLast": True})})
    monkeypatch.setattr(p, "_client", lambda: client)

    tasks = p.fetch_tasks()

    assert [c[0] for c in client.cagrilar] == ["/search/jql"]
    assert len(tasks) == 1 and tasks[0].external_id == "PROJ-1"
    assert p.warnings == []


def test_server_eski_ucu_kullanir(monkeypatch):
    p = _provider(base_url="https://jira.sirket.local", auth="bearer")
    client = _Client({"/search": _Resp(200, {"issues": [_issue()], "total": 1})})
    monkeypatch.setattr(p, "_client", lambda: client)

    assert len(p.fetch_tasks()) == 1
    assert [c[0] for c in client.cagrilar] == ["/search"]


def test_401_sessiz_kalmaz_ve_sebebi_soyler(monkeypatch):
    """EN KRİTİK REGRESYON: kullanıcı eskiden yalnız '0 task' görüyordu."""
    p = _provider(auth="bearer")
    monkeypatch.setattr(p, "_client", lambda: _Client({"/search/jql": _Resp(401)}))

    assert p.fetch_tasks() == []
    assert p.warnings, "401 sessizce yutuldu"
    assert "401" in p.warnings[0]
    # Cloud'da bearer kullanmak tam olarak bu hatayı verir; mesaj çözümü söylemeli.
    assert "basic" in p.warnings[0].lower()


def test_eksik_eposta_calismadan_once_yakalanir(monkeypatch):
    p = _provider(email="")
    monkeypatch.setattr(p, "_client", lambda: _Client({}))
    assert p.fetch_tasks() == []
    assert any("e-posta" in w.lower() for w in p.warnings)


def test_jql_proje_anahtari_kacirilir(monkeypatch):
    """Boşluklu/özel karakterli proje anahtarı sorguyu bozmamalı."""
    p = _provider(projects=['ACME "X"'])
    client = _Client({"/search/jql": _Resp(200, {"issues": [], "isLast": True})})
    monkeypatch.setattr(p, "_client", lambda: client)

    p.fetch_tasks()

    jql = client.cagrilar[0][1]["jql"]
    assert jql == 'project = "ACME \\"X\\""'


def test_story_point_alani_config_ten_okunur(monkeypatch):
    """İŞ-11: alan kimliği kurulumdan kuruluma değişir."""
    p = _provider(story_points_field="customfield_99")
    client = _Client({"/search/jql": _Resp(
        200, {"issues": [_issue(customfield_99=5.0)], "isLast": True})})
    monkeypatch.setattr(p, "_client", lambda: client)

    tasks = p.fetch_tasks()

    assert tasks[0].story_points == 5.0
    assert "customfield_99" in client.cagrilar[0][1]["fields"]
    assert p.warnings == []


def test_bulunamayan_story_point_alani_bildirilir(monkeypatch):
    """Yanlış alan kimliği sessizce None üretiyordu — kullanıcı sebebini bilemez."""
    p = _provider(story_points_field="customfield_yanlis")
    client = _Client({"/search/jql": _Resp(200, {"issues": [_issue()], "isLast": True})})
    monkeypatch.setattr(p, "_client", lambda: client)

    tasks = p.fetch_tasks()

    assert tasks[0].story_points is None
    assert any("story point" in w.lower() for w in p.warnings)


def test_story_point_kapatilabilir(monkeypatch):
    """Boş bırakmak bilinçli tercihtir: uyarı da üretilmemeli."""
    p = _provider(story_points_field="")
    client = _Client({"/search/jql": _Resp(200, {"issues": [_issue()], "isLast": True})})
    monkeypatch.setattr(p, "_client", lambda: client)

    p.fetch_tasks()
    assert p.warnings == []


def test_cloud_sayfalamasi_token_ile_ilerler(monkeypatch):
    from app.adapters.jira import JiraProvider

    p = _provider()
    sayfalar = [
        _Resp(200, {"issues": [_issue("P-1")], "nextPageToken": "t2"}),
        _Resp(200, {"issues": [_issue("P-2")], "isLast": True}),
    ]

    class _Sayfali(_Client):
        def get(self, url, params=None):
            self.cagrilar.append((url, params or {}))
            return sayfalar[len(self.cagrilar) - 1]

    client = _Sayfali({})
    monkeypatch.setattr(p, "_client", lambda: client)

    tasks = p.fetch_tasks()

    assert [t.external_id for t in tasks] == ["P-1", "P-2"]
    assert client.cagrilar[1][1]["nextPageToken"] == "t2"
    assert isinstance(p, JiraProvider)
