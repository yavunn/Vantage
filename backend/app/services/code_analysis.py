"""AI destekli kod içerik analizi.

FELSEFE (pazarlıksız): Bu bir KİŞİ puanlama/sıralama aracı DEĞİL. Skorlar
repo / dosya / modül düzeyinde toplanır; çıktı dili "kod tabanının şu bölümü
yardım istiyor", asla "şu kişi kötü kod yazıyor". Analiz kişiye atfedilmez.

MALİYET: Sadece değişen dosyalar analiz edilir, sonuçlar diff HASH'İNE göre
önbelleğe alınır (aynı diff tekrar analiz edilmez). LLM çağrısı başarısız/kapalı
olursa pano ÇÖKMEZ — 'analiz bekliyor' gösterilir (uydurma skor YOK).

GÜVENLİK: Diff LLM'e gitmeden önce secret/token kalıpları maskelenir. Hangi
verinin gittiği CodeAnalysisAudit'e loglanır (içerik değil, meta).

DETERMİNİZM: İstenen 'temperature 0' güncel Claude modellerinde 400 döner
(sampling parametreleri kaldırıldı). Onun yerine STRUCTURED OUTPUTS (JSON şema
+ strict) + effort=low kullanılır; tutarlı, şemaya uygun JSON bunu sağlar.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import CodeAnalysisSettings, Config
from app.models import CodeAnalysis, CodeAnalysisAudit

DIMENSIONS = [
    "readability", "complexity", "maintainability", "test_adequacy",
    "security", "code_smells", "conventions",
]

# Türkçe etiketler — prompt'taki ağırlık yönlendirmesinde kullanılır (UI'daki
# DIM_LABELS ile aynı anlam).
DIM_LABELS_TR = {
    "readability": "Okunabilirlik",
    "complexity": "Karmaşıklık",
    "maintainability": "Bakım kolaylığı",
    "test_adequacy": "Test yeterliliği",
    "security": "Güvenlik",
    "code_smells": "Kod kokuları / temizlik",
    "conventions": "Konvansiyonlar",
}

# --- Secret maskeleme ---------------------------------------------------------
# Diff'te açık secret varsa LLM'e GİTMEDEN maskele. Kalıplar geniş tutulur;
# yanlış-pozitif maskeleme, secret sızmasından iyidir.
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key)\b\s*[=:]\s*[\"']?[^\s\"';]{6,}"),
]
_MASK = "***MASKED_SECRET***"


def mask_secrets(text: str) -> tuple[str, int]:
    """Secret kalıplarını maskeler; (maskeli_metin, maskelenen_sayı) döner."""
    count = 0

    def _sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        # key=value kalıbında anahtar adını koru, değeri maskele
        g = m.group(0)
        if "=" in g or ":" in g:
            sep = "=" if "=" in g else ":"
            head = g.split(sep, 1)[0]
            return f"{head}{sep} {_MASK}"
        return _MASK

    for pat in _SECRET_PATTERNS:
        text, n = pat.subn(_sub, text)
    return text, count


def diff_hash(diff_text: str) -> str:
    return hashlib.sha256(diff_text.encode("utf-8", "replace")).hexdigest()


def is_excluded(file_path: str, cfg: CodeAnalysisSettings) -> bool:
    p = file_path.replace("\\", "/")
    return any(fnmatch.fnmatch(p, g) or fnmatch.fnmatch(p, f"*/{g}") for g in cfg.exclude_globs)


def _truncate(diff_text: str, max_lines: int) -> tuple[str, int]:
    lines = diff_text.splitlines()
    if len(lines) <= max_lines:
        return diff_text, len(lines)
    kept = lines[:max_lines]
    kept.append(f"... (diff {len(lines)} satır, ilk {max_lines} analiz edildi)")
    return "\n".join(kept), len(lines)


# --- Analiz çıktısı JSON şeması (structured outputs) ---------------------------
_DIM_PROP = {"type": "integer", "minimum": 0, "maximum": 100}
_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        **{d: _DIM_PROP for d in DIMENSIONS},
        "summary": {"type": "string"},
        "suggestions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": DIMENSIONS + ["summary", "suggestions"],
    "additionalProperties": False,
}

_SYSTEM = (
    "Sen yardımcı bir kıdemli yazılım mentörüsün. Sana bir kod değişikliğinin "
    "(git diff) verilir. Onu 7 boyutta 0-100 arası puanla — HER BOYUTTA 100 = EN "
    "İYİ (düşük karmaşıklık, az kod kokusu = yüksek puan). Puanlar kişiye değil, "
    "KODUN KENDİSİNE aittir; suçlayıcı değil yapıcı ol. Ayrıca 2-3 SOMUT, "
    "uygulanabilir iyileştirme önerisi ver (destek dilli, 'şu kişi' değil 'bu "
    "kod/bu bölüm' dili). Türkçe yaz. Yalnızca istenen JSON şemasına uygun yanıt ver."
)
_PROMPT = "Dosya: {path}\n\n```diff\n{diff}\n```"


def build_system(weights: dict[str, float] | None) -> str:
    """Statik yönergeye ekip RUBRİK AĞIRLIKLARINI ekler: AI puanlarken ve öneri
    verirken ağırlığı yüksek boyutlara daha çok dikkat etsin (ağırlık 0 = önemseme).
    Aynı ağırlıklar composite skorda da kullanılır (çift görev). Kod taraması
    dış araca (SonarQube vb.) bağlı DEĞİL — puanı bu prompt'la AI üretir."""
    weights = weights or {}
    ordered = sorted(DIMENSIONS, key=lambda d: weights.get(d, 1.0), reverse=True)
    lines = []
    for d in ordered:
        w = float(weights.get(d, 1.0))
        label = DIM_LABELS_TR.get(d, d)
        if w <= 0:
            lines.append(f"- {label}: ağırlık 0 — bu boyutu değerlendirme, önemseme.")
        else:
            pri = "YÜKSEK öncelik" if w >= 2 else ("düşük öncelik" if w < 1 else "normal")
            lines.append(f"- {label}: ağırlık {w:.1f} ({pri})")
    return (
        _SYSTEM
        + "\n\nBu ekip için boyut öncelik AĞIRLIKLARI (öneri verirken ve puanlarken "
        "bu boyutlara orantılı dikkat ver; ağırlığı yüksek boyutta zayıflığı daha "
        "belirgin vurgula):\n" + "\n".join(lines)
    )


@dataclass
class AnalyzerResult:
    scores: dict[str, int]
    summary: str
    suggestions: list[str]
    provider: str
    model: str


class ClaudeAnalyzer:
    """Claude API (resmi SDK). Structured outputs + effort=low ile deterministik
    JSON. temperature GÖNDERİLMEZ (güncel modellerde 400)."""

    provider = "claude"

    def __init__(self, model: str, api_key_env: str, system: str = _SYSTEM):
        import anthropic

        self.model = model
        self.system = system
        self._client = anthropic.Anthropic(api_key=os.environ.get(api_key_env) or None)

    def analyze(self, file_path: str, diff_text: str) -> AnalyzerResult:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=self.system,
            thinking={"type": "disabled"},
            output_config={
                "format": {"type": "json_schema", "schema": _ANALYSIS_SCHEMA},
                "effort": "low",
            },
            messages=[{"role": "user", "content": _PROMPT.format(path=file_path, diff=diff_text)}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(text)
        return AnalyzerResult(
            scores={d: int(data[d]) for d in DIMENSIONS},
            summary=str(data.get("summary", "")).strip(),
            suggestions=[str(s) for s in data.get("suggestions", [])][:3],
            provider="claude",
            model=self.model,
        )


class LocalAnalyzer:
    """Self-hosted / OpenAI-uyumlu uç (Ollama, LM Studio, vLLM, OpenAI, OpenRouter…).
    Şema garantisi yok → JSON'u hoşgörülü ayrıştırır; başarısızsa hata verir
    (çağıran 'analiz bekliyor' der). api_key verilirse Authorization: Bearer
    başlığı gönderilir (anahtar isteyen uçlar için); Ollama gibi anahtarsız
    uçlarda boş bırakılır."""

    provider = "local"

    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 system: str = _SYSTEM):
        import httpx

        self._httpx = httpx
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key or None
        self.system = system

    def analyze(self, file_path: str, diff_text: str) -> AnalyzerResult:
        prompt = (
            self.system + "\n\nİstenen JSON alanları: " + ", ".join(DIMENSIONS)
            + ", summary, suggestions.\n\n" + _PROMPT.format(path=file_path, diff=diff_text)
        )
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        resp = self._httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json={"model": self.model, "messages": [{"role": "user", "content": prompt}]},
            headers=headers,
            timeout=180,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group(0))
        return AnalyzerResult(
            scores={d: int(data[d]) for d in DIMENSIONS},
            summary=str(data.get("summary", "")).strip(),
            suggestions=[str(s) for s in data.get("suggestions", [])][:3],
            provider="local",
            model=self.model,
        )


def build_analyzer(cfg: Config):
    """Config'ten analizör kurar. Kapalıysa None — özellik 'analiz bekliyor'
    gösterir, asla sessizce dış servise düşmez."""
    if not (cfg.llm.enabled and cfg.code_analysis.enabled):
        return None
    # Rubrik ağırlıklarını system prompt'a göm (analiz dış araca değil bu prompt'a bağlı).
    system = build_system(cfg.code_analysis.weights)
    if cfg.llm.provider == "claude":
        return ClaudeAnalyzer(cfg.llm.claude.model, cfg.llm.claude.api_key_env, system)
    if cfg.llm.provider == "local":
        return LocalAnalyzer(
            cfg.llm.local.base_url,
            cfg.llm.local.model,
            os.environ.get(cfg.llm.local.api_key_env),
            system,
        )
    return None


def _composite(scores: dict[str, int], weights: dict[str, float]) -> float:
    total_w = sum(weights.get(d, 1.0) for d in DIMENSIONS)
    if total_w == 0:
        total_w = len(DIMENSIONS)
    return sum(scores[d] * weights.get(d, 1.0) for d in DIMENSIONS) / total_w


def classify_error(e: Exception) -> str:
    """LLM çağrısı hatasını kullanıcıya gösterilecek NET Türkçe sebebe çevirir.
    'analiz 0 yeni' gibi sessiz başarısızlık yerine gerçek neden görünsün."""
    msg = str(e).lower()
    if "credit balance" in msg or "billing" in msg or "insufficient" in msg:
        return ("AI sağlayıcı bakiyesi yetersiz — Anthropic Plans & Billing'den "
                "kredi ekle ya da yerel LLM'e (Ollama) geç.")
    if "authentication" in msg or "x-api-key" in msg or "unauthorized" in msg or " 401" in msg:
        return "AI API anahtarı geçersiz/eksik (owner AI Sağlayıcı bölümünden kontrol et)."
    if "rate limit" in msg or "429" in msg or "overloaded" in msg or "529" in msg:
        return "AI hız limiti/aşırı yük — biraz sonra tekrar dene."
    if "connect" in msg or "connection" in msg or "timeout" in msg or "refused" in msg:
        return "AI sunucusuna bağlanılamadı (yerel LLM kapalı olabilir — base_url'i kontrol et)."
    if "not_found" in msg or "404" in msg or "model" in msg:
        return "AI modeli bulunamadı — model adını kontrol et."
    return f"AI çağrısı başarısız: {type(e).__name__}."


def analyze_diff(
    session: Session,
    cfg: Config,
    analyzer,
    repo_id: int | None,
    file_path: str,
    commit_sha: str | None,
    diff_text: str,
    developer_id: int | None = None,
    now: datetime | None = None,
    errors: list[str] | None = None,
) -> CodeAnalysis | None:
    """Tek bir dosya diff'ini analiz eder (cache + maskeleme + audit).
    analyzer None ise 'analiz bekliyor' (audit=skipped). Hata olursa None
    döner ve audit=error yazılır — pano çökmez. errors verilirse hata SEBEBİ
    o listeye eklenir (çağıran kullanıcıya net mesaj gösterebilsin)."""
    ca_cfg = cfg.code_analysis
    now = now or datetime.now(timezone.utc)

    if is_excluded(file_path, ca_cfg):
        return None

    h = diff_hash(diff_text)
    # Cache: aynı diff daha önce analiz edildiyse tekrar LLM çağırma
    existing = session.scalar(
        select(CodeAnalysis).where(
            CodeAnalysis.repo_id == repo_id, CodeAnalysis.diff_hash == h
        )
    )
    if existing is not None:
        # Kişi-bazlı koşuda daha önce atfedilmemiş satırı yazarına bağla
        if developer_id is not None and existing.developer_id is None:
            existing.developer_id = developer_id
        return existing

    masked, n_secrets = mask_secrets(diff_text)
    truncated, total_lines = _truncate(masked, ca_cfg.max_diff_lines)

    if analyzer is None:
        session.add(CodeAnalysisAudit(
            repo_id=repo_id, file_path=file_path, diff_hash=h,
            chars_sent=0, masked_secrets=n_secrets, provider=None, model=None,
            outcome="skipped", sent_at=now,
        ))
        return None

    try:
        result = analyzer.analyze(file_path, truncated)
    except Exception as e:  # noqa: BLE001 — pano çökmesin; sebep 'errors'a taşınır
        session.add(CodeAnalysisAudit(
            repo_id=repo_id, file_path=file_path, diff_hash=h,
            chars_sent=len(truncated), masked_secrets=n_secrets,
            provider=getattr(analyzer, "provider", None), model=getattr(analyzer, "model", None),
            outcome="error", sent_at=now,
        ))
        if errors is not None:
            errors.append(classify_error(e))
        return None

    row = CodeAnalysis(
        repo_id=repo_id, developer_id=developer_id,
        commit_sha=commit_sha, file_path=file_path,
        diff_hash=h, diff_lines=total_lines,
        **{d: result.scores[d] for d in DIMENSIONS},
        composite=_composite(result.scores, ca_cfg.weights),
        suggestions=[{"text": s} for s in result.suggestions],
        summary=result.summary, provider=result.provider, model=result.model,
        analyzed_at=now,
    )
    session.add(row)
    session.add(CodeAnalysisAudit(
        repo_id=repo_id, file_path=file_path, diff_hash=h,
        chars_sent=len(truncated), masked_secrets=n_secrets,
        provider=result.provider, model=result.model, outcome="ok", sent_at=now,
    ))
    session.flush()
    return row


# --- Diff kaynağı: yerel git repo (git_log yolu) ------------------------------
# GERÇEK diff burada üretilir. GitLab/GitHub için diff API'leri ayrı sağlayıcı
# gerektirir (VERİ KAYNAĞI GEREKLİ — iskele: fetch_gitlab_diff/fetch_github_diff).

def _run_git(args: list[str]) -> str:
    import subprocess
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        ).stdout
    except Exception:  # noqa: BLE001 — repo/git erişilemezse tüm koşuyu düşürme
        return ""


def iter_git_file_diffs(repo_path: str, max_commits: int = 40):
    """Son commit'lerin dosya-bazlı diff'lerini üretir: (sha, author_email, file, diff).
    author_email: commit'in git yazarı — analizi KİŞİYE atfetmek için (yardımcı
    veri, kimlik ingest'teki gibi e-posta ile developer'a eşlenir)."""
    from pathlib import Path

    p = Path(repo_path)
    if not (p / ".git").exists():
        return
    # sha ve yazar e-postasını tek log çağrısında al
    raw = _run_git(["-C", str(p), "log", "-n", str(max_commits), "--pretty=format:%H%x1f%ae"])
    commits = []
    for line in raw.splitlines():
        if "\x1f" in line:
            sha, email = line.split("\x1f", 1)
            commits.append((sha.strip(), email.strip().lower()))
    for sha, email in commits:
        files = [f for f in _run_git(["-C", str(p), "show", "--name-only",
                                      "--pretty=format:", sha]).splitlines() if f.strip()]
        for f in files:
            diff = _run_git(["-C", str(p), "show", "--format=", sha, "--", f])
            if diff.strip():
                yield sha, email, f, diff


def _resolve_developer_id(session: Session, dev_cache: dict, email: str | None) -> int | None:
    """git e-postasından developer çözer (ingest ile aynı mantık: external_ids['git']).
    Eşleşme yoksa None — sahte 'unknown' kişi üretilmez."""
    from app.models import Developer

    if not email:
        return None
    if email in dev_cache:
        return dev_cache[email]
    for dev in session.scalars(select(Developer)):
        if (dev.external_ids or {}).get("git", "").lower() == email:
            dev_cache[email] = dev.id
            return dev.id
    dev_cache[email] = None
    return None


def _developer_git_emails(session: Session, developer_id: int) -> set[str]:
    from app.models import Developer

    dev = session.get(Developer, developer_id)
    if dev is None:
        return set()
    g = (dev.external_ids or {}).get("git")
    return {g.lower()} if g else set()


def run_code_analysis(session: Session, cfg: Config,
                      only_developer_id: int | None = None) -> dict:
    """git_log repolarındaki değişen dosyaları analiz eder (cache'li, maliyet
    frenli, git YAZARINA atfeder). only_developer_id verilirse yalnızca o kişinin
    yazdığı commit'ler analiz edilir (admin tek kişi / kullanıcı kendi kodu).
    analyzer kapalıysa hiçbir şey yapmaz — 'analiz bekliyor'."""
    from app.models import Repo

    analyzer = build_analyzer(cfg)
    if analyzer is None:
        return {"status": "disabled", "analyzed": 0,
                "note": "llm.enabled + code_analysis.enabled açık değil (analiz bekliyor)"}

    target_emails = _developer_git_emails(session, only_developer_id) if only_developer_id else None
    if only_developer_id and not target_emails:
        return {"status": "no_identity", "analyzed": 0,
                "note": "Bu kişinin git e-postası tanımlı değil (developer.external_ids['git']). "
                        "Atıf yapılamaz — veri kaynağı gerekli."}

    ca = cfg.code_analysis
    budget = ca.max_files_per_run
    dev_cache: dict = {}
    analyzed = cached = skipped = other_author = 0
    errors: list[str] = []

    for repo_cfg in cfg.sources.git.repos:
        if budget <= 0:
            break
        if not isinstance(repo_cfg, dict) or not repo_cfg.get("path"):
            continue
        repo_row = session.scalar(select(Repo).where(Repo.name == repo_cfg.get("name")))
        repo_id = repo_row.id if repo_row else None
        for sha, email, file_path, diff in iter_git_file_diffs(repo_cfg["path"]):
            if budget <= 0:
                break
            if target_emails is not None and email not in target_emails:
                other_author += 1
                continue
            if is_excluded(file_path, ca):
                skipped += 1
                continue
            dev_id = only_developer_id if target_emails else _resolve_developer_id(session, dev_cache, email)
            h = diff_hash(diff)
            pre = session.scalar(select(CodeAnalysis).where(
                CodeAnalysis.repo_id == repo_id, CodeAnalysis.diff_hash == h))
            if pre is not None:
                if dev_id is not None and pre.developer_id is None:
                    pre.developer_id = dev_id
                cached += 1
                continue
            row = analyze_diff(session, cfg, analyzer, repo_id, file_path, sha, diff,
                               developer_id=dev_id, errors=errors)
            budget -= 1
            if row is not None:
                analyzed += 1
    session.commit()
    out = {"status": "ok", "analyzed": analyzed, "cached": cached, "excluded": skipped}
    if target_emails is not None:
        out["other_author_skipped"] = other_author
    # Hiç yeni analiz olmadı ama LLM çağrıları hata verdiyse: sessiz "0 yeni"
    # yerine NET sebep göster (ör. kredi yetersiz).
    if analyzed == 0 and errors:
        out["status"] = "error"
        out["error_count"] = len(errors)
        out["note"] = errors[-1]
    return out
