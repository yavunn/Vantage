"""AI kod analizi: rubrik ağırlıkları PROMPT'a giriyor mu (kod taraması dış
araca değil kendi prompt'umuza bağlı)."""
from __future__ import annotations

from app.core.config import Config
from app.services.code_analysis import _SYSTEM, build_analyzer, build_system


def test_build_system_agirliklari_prompta_koyar():
    s = build_system({
        "readability": 2.0, "complexity": 1.5, "security": 0,
        "maintainability": 1.0, "test_adequacy": 1.0,
        "code_smells": 1.0, "conventions": 1.0,
    })
    assert _SYSTEM in s
    assert "Okunabilirlik: ağırlık 2.0 (YÜKSEK öncelik)" in s
    assert "Güvenlik: ağırlık 0" in s and "önemseme" in s
    # azalan ağırlık sırası: okunabilirlik (2.0) güvenlikten (0) önce
    assert s.index("Okunabilirlik") < s.index("Güvenlik")


def test_build_analyzer_system_agirlik_icerir():
    cfg = Config()
    cfg.llm.enabled = True
    cfg.llm.provider = "claude"
    cfg.code_analysis.enabled = True
    cfg.code_analysis.weights = {**cfg.code_analysis.weights, "readability": 3.0}
    az = build_analyzer(cfg)
    assert az is not None
    assert "Okunabilirlik: ağırlık 3.0" in az.system


def test_classify_error_kredi():
    from app.services.code_analysis import classify_error

    msg = classify_error(Exception("Error 400: Your credit balance is too low")).lower()
    assert "bakiye" in msg or "kredi" in msg


def test_analyze_diff_hata_sebebini_toplar(session):
    """LLM patlayınca sessiz None değil — sebep 'errors' listesine düşer."""
    from app.services.code_analysis import analyze_diff

    class Boom:
        provider = "claude"
        model = "x"

        def analyze(self, *a):
            raise RuntimeError("Your credit balance is too low")

    cfg = Config()
    errs: list[str] = []
    row = analyze_diff(session, cfg, Boom(), None, "foo.py", "sha", "@@ diff @@", errors=errs)
    assert row is None
    assert errs and ("kredi" in errs[0].lower() or "bakiye" in errs[0].lower())


def test_is_excluded_config_bos_olsa_da_uretilmis_dosyalari_atar():
    """Hariç klasörler ayar DEĞİL: config boş olsa bile node_modules/dist elenir."""
    from app.services.code_analysis import is_excluded

    cfg = Config().code_analysis
    assert cfg.exclude_globs == []  # varsayılan artık boş (temel liste kodda)
    assert is_excluded("node_modules/x.js", cfg)
    assert is_excluded("a/b/dist/app.js", cfg)
    assert is_excluded("frontend/package-lock.json", cfg)
    assert is_excluded("static/logo.svg", cfg)
    assert not is_excluded("src/app.py", cfg)
    assert not is_excluded("backend/app/services/code_analysis.py", cfg)


def test_is_excluded_config_deseni_ekler_yerine_gecmez():
    from app.services.code_analysis import is_excluded

    cfg = Config().code_analysis
    cfg.exclude_globs = ["migrations/*"]
    assert is_excluded("migrations/001.py", cfg)
    assert is_excluded("node_modules/x.js", cfg)  # temel liste hâlâ geçerli


def test_commit_mesaji_prompta_girer_ve_hashi_degistirir():
    """Analiz diff + commit mesajını görür; mesaj önbellek anahtarına dahildir."""
    from app.services.code_analysis import build_user_prompt, diff_hash

    p = build_user_prompt("foo.py", "@@ diff @@", "fix: null kontrolü ekle")
    assert "Commit mesajı:" in p and "fix: null kontrolü ekle" in p
    assert "@@ diff @@" in p
    # mesaj yoksa bölüm hiç yazılmaz
    assert "Commit mesajı" not in build_user_prompt("foo.py", "@@ diff @@", None)
    assert diff_hash("d", "mesaj A") != diff_hash("d", "mesaj B")
    assert diff_hash("d") == diff_hash("d", "")


def test_commit_mesaji_kirpilir():
    from app.services.code_analysis import format_commit_message

    out = format_commit_message("konu\n" + "\n".join(f"satır {i}" for i in range(50)))
    assert len(out.splitlines()) <= 21
    assert "kırpıldı" in out


def test_read_repo_file_sinirlari(tmp_path):
    """Derin okuma aracı: repo dışı / hariç dosya okunamaz, satır limiti uygulanır,
    secret maskelenir."""
    from app.services.code_analysis import MAX_READ_LINES, read_repo_file

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        "\n".join(f"line {i}" for i in range(1000)), encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("var a=1", encoding="utf-8")
    (tmp_path / "s.py").write_text('api_key = "abcdef123456"', encoding="utf-8")
    outside = tmp_path.parent / "gizli.txt"
    outside.write_text("sır", encoding="utf-8")

    repo = str(tmp_path)
    body, _ = read_repo_file(repo, "src/a.py")
    assert len(body.splitlines()) <= MAX_READ_LINES + 2

    assert read_repo_file(repo, "../gizli.txt")[0].startswith("HATA")
    assert read_repo_file(repo, "/etc/passwd")[0].startswith("HATA")
    assert read_repo_file(repo, "node_modules/x.js")[0].startswith("HATA")
    assert read_repo_file(repo, "yok.py")[0].startswith("HATA")

    masked, n = read_repo_file(repo, "s.py")
    assert n == 1 and "abcdef123456" not in masked


class _Blk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


def _final_json():
    import json

    from app.services.code_analysis import DIMENSIONS

    data = {d: 70 for d in DIMENSIONS}
    data["summary"] = "iyi"
    data["suggestions"] = ["a"]
    return _Resp("end_turn", [_Blk(type="text", text=json.dumps(data))])


def test_claude_derin_okuma_limiti(tmp_path):
    """Model sürekli dosya isterse: en fazla 3 okuma, sonrası 'limit doldu'."""
    from app.services.code_analysis import MAX_EXTRA_READS, ClaudeAnalyzer

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    az = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
    az.model = "m"
    az.system = "S"
    calls: list[dict] = []

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                # model hep dosya istiyor; sınırı analizör koymalı. Araçsız
                # (zorlama) çağrıda cevap ver.
                if kw.get("tools"):
                    return _Resp("tool_use", [_Blk(type="tool_use", id=f"t{len(calls)}",
                                                   name="read_file", input={"path": "a.py"})])
                return _final_json()

    az._client = FakeClient()
    res = az.analyze("a.py", "@@ diff @@", commit_message="fix: x", repo_path=str(tmp_path))
    assert res.extra_reads == MAX_EXTRA_READS
    assert res.scores["readability"] == 70
    # araç yalnız repo_path varken tanımlanır ve system'e bağlam kuralı eklenir
    assert calls[0]["tools"][0]["name"] == "read_file"
    assert "BAĞLAM KURALI" in calls[0]["system"]
    assert "fix: x" in calls[0]["messages"][0]["content"]


def test_claude_repo_path_yoksa_arac_yok(tmp_path):
    from app.services.code_analysis import ClaudeAnalyzer

    az = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
    az.model = "m"
    az.system = "S"
    calls: list[dict] = []

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                return _final_json()

    az._client = FakeClient()
    res = az.analyze("a.py", "@@ diff @@")
    assert res.extra_reads == 0
    assert "tools" not in calls[0]
    assert "BAĞLAM KURALI" not in calls[0]["system"]


# --- Yerel/OpenAI-uyumlu uç: şema garantisi olmayan çıktıyı ayrıştırma --------
# Claude'da structured output var, yerel uçta YOK. Gözlenen bozukluklar:
# kod bloğuna sarma, nesneden sonra açıklama metni, süslü parantez düşürme,
# ondalık puanı metin olarak verme ve suggestions'ı string yerine nesne yapma.

def _tam_json(**degisiklik) -> str:
    from app.services.code_analysis import DIMENSIONS

    alanlar = {d: 80 for d in DIMENSIONS}
    alanlar.update(summary="özet", suggestions=["a"])
    alanlar.update(degisiklik)
    import json

    return json.dumps(alanlar, ensure_ascii=False)


def test_extract_json_object_dengeli_kapanista_durur():
    """Eski regex açgözlüydü: nesneden sonraki metni de yutup json.loads'u
    patlatıyordu. İç içe süslü parantez ve string içindeki '}' de yanıltmamalı."""
    from app.services.code_analysis import extract_json_object

    metin = '{"a": {"b": "}"}, "c": 1} BU METIN DISARIDA {bozuk}'
    assert extract_json_object(metin) == '{"a": {"b": "}"}, "c": 1}'
    assert extract_json_object("hic suslu parantez yok") == ""
    assert extract_json_object('{"kesilmis": ') == ""  # açık kaldı


def test_parse_local_analysis_kod_blogunu_ve_arti_metni_tolere_eder():
    from app.services.code_analysis import parse_local_analysis

    icerik = _tam_json()
    assert parse_local_analysis(f"Analiz:\n```json\n{icerik}\n```\nUmarım yardımcı olur.")
    assert parse_local_analysis(icerik + "\n\nAyrıca: {bozuk}")


def test_parse_local_analysis_json_yoksa_net_hata_verir():
    """Eski kod burada `None.group()` ile AttributeError atıyordu; kullanıcıya
    'AI çağrısı başarısız: AttributeError' diye anlamsız bir sebep düşüyordu."""
    import pytest

    from app.services.code_analysis import LocalOutputError, classify_error, parse_local_analysis

    with pytest.raises(LocalOutputError) as ei:
        parse_local_analysis("Bu diff iyi görünüyor, puan vermeye gerek yok.")
    mesaj = classify_error(ei.value)
    assert "json" in mesaj.lower()
    # 'model' kelimesi geçiyor diye "AI modeli bulunamadı" dalına DÜŞMEMELİ
    assert "bulunamadı" not in mesaj


def test_coerce_scores_ondalik_metni_ve_tasan_degeri_toparlar():
    from app.services.code_analysis import DIMENSIONS, coerce_scores

    ham = {d: 80 for d in DIMENSIONS}
    ham["readability"] = "85.6"
    ham["security"] = 140      # 0-100 dışı
    ham["complexity"] = -5
    puan = coerce_scores(ham)
    assert puan["readability"] == 86
    assert puan["security"] == 100
    assert puan["complexity"] == 0


def test_coerce_scores_eksik_boyutta_puan_uydurmaz():
    import pytest

    from app.services.code_analysis import DIMENSIONS, LocalOutputError, coerce_scores

    ham = {d: 80 for d in DIMENSIONS if d != "conventions"}
    with pytest.raises(LocalOutputError, match="conventions"):
        coerce_scores(ham)


def test_coerce_suggestions_nesneyi_python_repr_olarak_yazmaz():
    """Yerel modeller {'description':..., 'implementation':...} döndürüyor;
    eski str(s) bunu panoya "{'description': ...}" diye basıyordu."""
    from app.services.code_analysis import coerce_suggestions

    out = coerce_suggestions([
        {"description": "sum kullan", "implementation": "return sum(...)"},
        {"description": "adlandırmayı netleştir"},
        "düz string öneri",
        {"tanimsiz": "şekil"},
    ])
    assert out[0] == "sum kullan — return sum(...)"
    assert out[1] == "adlandırmayı netleştir"
    assert out[2] == "düz string öneri"
    assert len(out) == 3  # en fazla 3
    assert not any("{" in s or "'description'" in s for s in out)
    assert coerce_suggestions(None) == []
    assert coerce_suggestions("tek öneri") == ["tek öneri"]


def test_local_analyzer_bozuk_yaniti_net_hataya_cevirir(monkeypatch):
    """LocalAnalyzer.analyze uçtan uca: HTTP 200 ama içerik şemaya uymuyor.

    İstek artık app/llm/local_client.py'de kurulduğu için (bağlam sınırı TEK
    yerde ayarlansın diye) yama hedefi orasıdır."""
    import pytest

    from app.core.config import LLMLocal
    from app.llm import local_client
    from app.services.code_analysis import LocalAnalyzer, LocalOutputError

    class FakeResp:
        def __init__(self, icerik):
            self._i = icerik

        def raise_for_status(self):
            return None

        def json(self):
            # Ollama /api/chat gövdesi (varsayılan api_style).
            return {"message": {"content": self._i}, "prompt_eval_count": 10_000}

    def _fake_post(icerik):
        return lambda url, **kw: FakeResp(icerik)

    az = LocalAnalyzer(LLMLocal(base_url="http://localhost:11434", model="m"), None, "S")

    monkeypatch.setattr(local_client.httpx, "post",
                        _fake_post('```json\n"ping": "pong"\n```'))
    with pytest.raises(LocalOutputError):
        az.analyze("a.py", "@@ diff @@")

    monkeypatch.setattr(local_client.httpx, "post", _fake_post(
        f"Iste sonuc:\n```json\n{_tam_json(suggestions=[{'description': 'x', 'implementation': 'y'}])}\n```"))
    res = az.analyze("a.py", "@@ diff @@")
    assert res.provider == "local"
    assert res.scores["readability"] == 80
    assert res.suggestions == ["x — y"]
    assert res.truncated is False
