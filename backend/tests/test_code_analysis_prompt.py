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
