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
