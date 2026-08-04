"""AI destekli kod içerik analizi.

FELSEFE (pazarlıksız): Bu bir KİŞİ puanlama/sıralama aracı DEĞİL. Skorlar
repo / dosya / modül düzeyinde toplanır; çıktı dili "kod tabanının şu bölümü
yardım istiyor", asla "şu kişi kötü kod yazıyor". Analiz kişiye atfedilmez.

MALİYET: Sadece değişen dosyalar analiz edilir, sonuçlar diff HASH'İNE göre
önbelleğe alınır (aynı diff tekrar analiz edilmez). LLM çağrısı başarısız/kapalı
olursa pano ÇÖKMEZ — 'analiz bekliyor' gösterilir (uydurma skor YOK).

BAĞLAM: Tüm proje ASLA okunmaz. Varsayılan bağlam dar — dosya yolu + commit
mesajı + o dosyanın diff'i. Model diff tek başına yetmediğini düşünürse
'read_file' aracıyla en fazla MAX_EXTRA_READS dosyayı, dosya başına
MAX_READ_LINES satır okuyabilir (yalnız Claude yolu). Üretilmiş / üçüncü taraf
dosyalar (BUILTIN_EXCLUDES) hiçbir yoldan analize giremez.

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


def diff_hash(diff_text: str, commit_message: str | None = None) -> str:
    """Önbellek anahtarı. Commit mesajı da prompt'a girdiği için hash'e DAHİLDİR:
    aynı diff farklı mesajla farklı analiz üretebilir. Bu değişiklikten önce
    yazılmış satırların hash'i mesajsız hesaplanmıştı — o satırlar bir kereliğine
    yeniden analiz edilir (kabul edilen tek seferlik maliyet)."""
    payload = diff_text if not commit_message else f"{commit_message.strip()}\n\x1f\n{diff_text}"
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


# Analize ASLA girmemesi gereken desenler. Bunlar admin tercihi değil modülün
# doğru davranışı: üretilmiş / üçüncü taraf / ikili dosyalar. Arayüzde gösterilmez,
# API'den değiştirilemez. config'teki exclude_globs bunun YERİNE geçmez, EKLENİR.
BUILTIN_EXCLUDES = [
    "generated/*", "vendor/*", "node_modules/*", "dist/*", "build/*",
    ".venv/*", "venv/*", "__pycache__/*",
    "*.min.js", "*.min.css", "*.lock", "*.map", "*.pyc",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.pdf",
    "*.woff", "*.woff2", "*.ttf",
]


def is_excluded(file_path: str, cfg: CodeAnalysisSettings | None = None) -> bool:
    """Dosya analiz dışı mı. Temel liste sabit (BUILTIN_EXCLUDES); config'te ek
    desen tanımlanmışsa üzerine eklenir."""
    p = file_path.replace("\\", "/")
    globs = [*BUILTIN_EXCLUDES, *(cfg.exclude_globs if cfg else [])]
    return any(fnmatch.fnmatch(p, g) or fnmatch.fnmatch(p, f"*/{g}") for g in globs)


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
# Commit mesajı bölümü — NİYETİ anlatır (mesaj yoksa hiç eklenmez).
_COMMIT_BLOCK = "Commit mesajı:\n{msg}\n\n"
_COMMIT_MSG_MAX_LINES = 20

# read_file aracı açıkken system'e eklenir: varsayılan dar bağlam, gerekirse
# ölçülü derinleşme.
_DEEP_READ_GUIDE = (
    "\n\nBAĞLAM KURALI: Varsayılan olarak yalnız diff ve commit mesajıyla "
    "değerlendir. Tüm projeyi okumaya çalışma. Sadece diff tek başına yanıltıcıysa "
    "(ör. çağrılan bir fonksiyonun sözleşmesi, testin varlığı, dosyanın diff dışı "
    "kısmı gerekiyorsa) read_file ile en fazla birkaç ilgili dosyayı iste. "
    "Gereksiz okuma maliyet demektir."
)

_READ_FILE_TOOL = {
    "name": "read_file",
    "description": (
        "Repo'dan bir dosyanın içeriğini okur. Yalnızca diff tek başına "
        "yetmediğinde kullan. Yol repo köküne GÖRELİ olmalı."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repo köküne göreli dosya yolu"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
    },
}

# Derin okuma sınırları (aşılırsa araç metin olarak 'limit doldu' döner)
MAX_EXTRA_READS = 3
MAX_READ_LINES = 300


class LocalOutputError(ValueError):
    """Yerel/OpenAI-uyumlu uç şemaya uymayan bir yanıt döndürdü. Claude'da
    structured output garantisi var, burada yok — bu yüzden ayrı hata tipi:
    çağıran 'AI çağrısı başarısız' yerine NET sebebi gösterebilsin."""


def extract_json_object(text: str) -> str:
    """Metinden ilk DENGELİ JSON nesnesini çıkarır; bulamazsa "" döner.

    Neden regex değil: `re.search(r"\\{.*\\}", ..., DOTALL)` açgözlüdür, nesneden
    sonra gelen metni (ikinci bir kod bloğu, açıklama) içine alır ve json.loads
    patlar. Ayrıca hiç `{` yoksa None döner — eski kod bunu kontrol etmediği için
    `None.group()` ile AttributeError'a düşüyordu.
    """
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    in_str = esc = False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ""  # açık kaldı (yanıt kesilmiş)


def parse_local_analysis(text: str) -> dict:
    """Yerel modelin serbest metnini analiz sözlüğüne çevirir.

    Küçük modeller JSON'u kod bloğu içinde, açıklama cümlesiyle sarılı ya da
    süslü parantezleri düşürerek döndürebiliyor (gözlendi: ```json "ping":
    "pong" ```). Ayrıştırma sırası: dengeli nesne → süssüz anahtar/değer
    gövdesini parantezle. Hiçbiri tutmazsa LocalOutputError.
    """
    body = extract_json_object(text)
    if not body:
        # Süslü parantezsiz gövde: kod bloğu içeriğini alıp kendimiz sarıyoruz.
        fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
        candidate = (fenced.group(1) if fenced else text).strip().strip(",")
        if re.match(r'^"[^"]+"\s*:', candidate):
            body = "{" + candidate + "}"
    if not body:
        raise LocalOutputError(
            "Yerel model JSON döndürmedi. Yanıtın başı: " + text.strip()[:200]
        )
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise LocalOutputError(f"Yerel modelin JSON'u bozuk ({e.msg}). Gövde: {body[:200]}") from e
    if not isinstance(data, dict):
        raise LocalOutputError(f"Yerel model nesne değil {type(data).__name__} döndürdü.")
    return data


def coerce_scores(data: dict) -> dict[str, int]:
    """Puanları 0-100 aralığında tam sayıya çevirir.

    `int(data[d])` üç yerde kırılıyordu: eksik boyut (KeyError), "85" yerine
    "85.5" gibi ondalık metin (ValueError) ve 0-100 dışı değer. Eksik boyutta
    puan UYDURMUYORUZ — hata veriyoruz ki dosya 'analiz bekliyor' kalsın.
    """
    missing = [d for d in DIMENSIONS if data.get(d) is None]
    if missing:
        raise LocalOutputError("Yerel modelin yanıtında eksik boyut: " + ", ".join(missing))
    scores = {}
    for d in DIMENSIONS:
        try:
            val = float(data[d])
        except (TypeError, ValueError) as e:
            raise LocalOutputError(f"'{d}' boyutu sayı değil: {data[d]!r}") from e
        scores[d] = int(round(min(100.0, max(0.0, val))))
    return scores


def coerce_suggestions(raw) -> list[str]:
    """Önerileri en fazla 3 düz metne indirger.

    Şema string listesi istiyor ama yerel modeller sık sık
    {"description": ..., "implementation": ...} nesneleri döndürüyor. Eski
    `str(s)` bunu Python repr'ine çeviriyordu, panoya `{'description': ...}`
    diye düşüyordu. Burada anlamlı alanı seçip birleştiriyoruz.
    """
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict):
            head = next((str(item[k]) for k in ("description", "suggestion", "text", "title")
                         if item.get(k)), "")
            tail = next((str(item[k]) for k in ("implementation", "example", "code")
                         if item.get(k)), "")
            text = f"{head} — {tail}" if head and tail else (head or tail)
            if not text:
                # Tanımadığımız şekil: repr yerine alanları okunur biçimde ser.
                text = "; ".join(f"{k}: {v}" for k, v in item.items())
        else:
            text = str(item)
        text = " ".join(text.split())
        if text:
            out.append(text)
    return out[:3]


def format_commit_message(msg: str | None) -> str | None:
    """Commit mesajını prompt'a uygun kırpar (konu + gövde, ~20 satır)."""
    if not msg or not msg.strip():
        return None
    lines = [ln.rstrip() for ln in msg.strip().splitlines()]
    if len(lines) > _COMMIT_MSG_MAX_LINES:
        lines = lines[:_COMMIT_MSG_MAX_LINES] + ["... (mesaj kırpıldı)"]
    return "\n".join(lines)


def build_user_prompt(file_path: str, diff_text: str, commit_message: str | None) -> str:
    msg = format_commit_message(commit_message)
    head = _COMMIT_BLOCK.format(msg=msg) if msg else ""
    return head + _PROMPT.format(path=file_path, diff=diff_text)


def read_repo_file(repo_path: str, rel_path: str, cfg: CodeAnalysisSettings | None = None,
                   start_line: int | None = None,
                   end_line: int | None = None) -> tuple[str, int]:
    """read_file aracının gövdesi. Güvenlik sınırları burada zorlanır:
    yol repo altında kalmalı, hariç dosyalar okunamaz, en fazla MAX_READ_LINES
    satır döner, içerik maskelemeden geçer. (metin, maskelenen_secret) döner."""
    from pathlib import Path

    rel = (rel_path or "").replace("\\", "/").strip()
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return "HATA: geçersiz yol (repo köküne göreli olmalı).", 0
    root = Path(repo_path).resolve()
    try:
        target = (root / rel).resolve()
        target.relative_to(root)
    except (ValueError, OSError):
        return "HATA: yol repo dışında.", 0
    if is_excluded(rel, cfg):
        return "HATA: bu dosya analiz kapsamı dışı (üretilmiş/üçüncü taraf).", 0
    if not target.is_file():
        return "HATA: dosya bulunamadı.", 0
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "HATA: dosya okunamadı.", 0

    start = max(1, start_line or 1)
    end = end_line or (start + MAX_READ_LINES - 1)
    end = min(end, start + MAX_READ_LINES - 1, len(lines))
    if start > len(lines):
        return f"HATA: dosyada {len(lines)} satır var, {start}. satır yok.", 0
    body = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
    masked, n = mask_secrets(body)
    note = "" if end >= len(lines) else f"\n... ({len(lines)} satırın {start}-{end} arası)"
    return f"{rel} ({start}-{end}):\n{masked}{note}", n


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
    # Derin okuma denetimi: kaç ek dosya okundu, kaç karakter daha gönderildi
    extra_reads: int = 0
    extra_chars: int = 0
    masked_secrets: int = 0
    # Prompt bağlam bütçesine sığmadığı için kırpıldı mı. Sessiz kırpma,
    # "analiz yapıldı" görünüp eksik girdiye dayanan bir sonuç üretiyordu.
    truncated: bool = False


class ClaudeAnalyzer:
    """Claude API (resmi SDK). Structured outputs + effort=low ile deterministik
    JSON. temperature GÖNDERİLMEZ (güncel modellerde 400).

    repo_path verilirse 'read_file' aracı açılır: model diff tek başına yetmezse
    en fazla MAX_EXTRA_READS dosyayı, dosya başına MAX_READ_LINES satır okuyabilir.
    Varsayılan davranış hâlâ dar bağlam — tüm proje ASLA okunmaz."""

    provider = "claude"

    def __init__(self, model: str, api_key_env: str, system: str = _SYSTEM):
        import anthropic

        self.model = model
        self.system = system
        self._client = anthropic.Anthropic(api_key=os.environ.get(api_key_env) or None)

    def _create(self, messages, system, tools):
        kwargs = dict(
            model=self.model,
            max_tokens=2048,
            system=system,
            thinking={"type": "disabled"},
            output_config={
                "format": {"type": "json_schema", "schema": _ANALYSIS_SCHEMA},
                "effort": "low",
            },
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools
        return self._client.messages.create(**kwargs)

    def analyze(self, file_path: str, diff_text: str, commit_message: str | None = None,
                repo_path: str | None = None,
                ca_cfg: CodeAnalysisSettings | None = None) -> AnalyzerResult:
        base_prompt = build_user_prompt(file_path, diff_text, commit_message)
        messages = [{"role": "user", "content": base_prompt}]
        tools = [_READ_FILE_TOOL] if repo_path else None
        system = self.system + (_DEEP_READ_GUIDE if tools else "")

        reads = 0
        extra_chars = 0
        masked = 0
        try:
            resp = self._create(messages, system, tools)
        except Exception as e:  # noqa: BLE001
            # Araçlı çağrıyı reddeden uç/model olursa dar bağlamla devam et
            # (analiz kaybolmasın); kredi/kimlik hataları yeniden denenmez.
            if not tools or "tool" not in str(e).lower():
                raise
            tools = None
            resp = self._create(messages, self.system, None)

        # Araç döngüsü: model dosya isterse oku, sonucu geri ver, tekrar sor.
        for _ in range(MAX_EXTRA_READS + 1):
            if resp.stop_reason != "tool_use":
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if reads >= MAX_EXTRA_READS:
                    body = "HATA: okuma limiti doldu (en fazla 3 dosya). Eldeki bilgiyle karar ver."
                else:
                    inp = block.input or {}
                    body, n = read_repo_file(
                        repo_path, str(inp.get("path", "")), ca_cfg,
                        inp.get("start_line"), inp.get("end_line"),
                    )
                    reads += 1
                    extra_chars += len(body)
                    masked += n
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": body})
            messages.append({"role": "user", "content": results})
            resp = self._create(messages, system, tools)

        text = next((b.text for b in resp.content if b.type == "text"), "")
        if not text:
            # Döngü araç isteğiyle bitti (model cevap vermedi): araç geçmişi
            # olmadan tek seferlik dar bağlamla sonuca zorla.
            resp = self._create(
                [{"role": "user", "content": base_prompt
                  + "\n\n(Ek dosya okuma limiti doldu; yalnız yukarıdaki bilgiyle değerlendir.)"}],
                self.system, None,
            )
            text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(text)
        return AnalyzerResult(
            scores={d: int(data[d]) for d in DIMENSIONS},
            summary=str(data.get("summary", "")).strip(),
            suggestions=[str(s) for s in data.get("suggestions", [])][:3],
            provider="claude",
            model=self.model,
            extra_reads=reads,
            extra_chars=extra_chars,
            masked_secrets=masked,
        )


class LocalAnalyzer:
    """Self-hosted / OpenAI-uyumlu uç (Ollama, LM Studio, vLLM, OpenAI, OpenRouter…).
    Şema garantisi yok → JSON'u hoşgörülü ayrıştırır; başarısızsa hata verir
    (çağıran 'analiz bekliyor' der). api_key verilirse Authorization: Bearer
    başlığı gönderilir (anahtar isteyen uçlar için); Ollama gibi anahtarsız
    uçlarda boş bırakılır."""

    provider = "local"

    def __init__(self, local, api_key: str | None = None, system: str = _SYSTEM):
        self.local = local
        self.base_url = local.base_url.rstrip("/")
        self.model = local.model
        self._api_key = api_key or None
        self.system = system

    def analyze(self, file_path: str, diff_text: str, commit_message: str | None = None,
                repo_path: str | None = None,
                ca_cfg: CodeAnalysisSettings | None = None) -> AnalyzerResult:
        # Yerel uçta araç çağrısı garantisi yok: commit mesajı metin olarak girer,
        # ek dosya okuma YAPILMAZ (repo_path yok sayılır).
        #
        # İstek app/llm/local_client.py üzerinden kurulur: bağlam uzunluğu
        # (num_ctx) orada gönderilir ve prompt bütçeyi aşarsa GÖNDERMEDEN ÖNCE
        # kırpılıp kırpıldığı beyan edilir. Eskiden burada kurulan doğrudan
        # httpx çağrısı num_ctx göndermediği için Ollama 4096'ya düşüyor ve
        # prompt'un başını sessizce atıyordu (ölçüm: 7.700 token gönderildi,
        # 2050 görüldü) — model diff'in dörtte birini görüp puan veriyordu.
        from app.llm.local_client import local_chat

        system = self.system + "\n\nİstenen JSON alanları: " + ", ".join(DIMENSIONS) \
            + ", summary, suggestions."
        sonuc = local_chat(
            self.local,
            system,
            build_user_prompt(file_path, diff_text, commit_message),
            api_key=self._api_key,
            timeout=180,
        )
        data = parse_local_analysis(sonuc.text)
        return AnalyzerResult(
            scores=coerce_scores(data),
            summary=" ".join(str(data.get("summary", "")).split()),
            suggestions=coerce_suggestions(data.get("suggestions")),
            provider="local",
            model=self.model,
            truncated=sonuc.truncated,
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
            cfg.llm.local,
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
    from app.llm.local_client import ContextOverflowError

    # Bağlam taşması: uç prompt'un bir kısmını görmemiş. Bu, "analiz üretildi ama
    # eksik girdiye dayanıyor" durumudur ve SESSİZ kalmamalı — sonuç üretilse
    # bile güvenilir değildir.
    if isinstance(e, ContextOverflowError):
        return (f"Yerel uç prompt'un tamamını görmedi ({e}). llm.local.context_tokens "
                "değerini ya da sunucunun bağlam sınırını büyütün.")
    # Yerel uçta şema garantisi yok: modelin biçim hatası, "model bulunamadı"
    # gibi bir altyapı hatasıyla karışmasın diye EN BAŞTA ve tipe göre eşlenir
    # (metin eşleşmesi 'model' kelimesine takılıyordu).
    if isinstance(e, LocalOutputError):
        return (f"Yerel model istenen JSON biçimini vermedi ({e}). Daha büyük ya da "
                "talimat uyumu iyi bir model dene (ör. qwen2.5-coder:14b).")
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
    commit_message: str | None = None,
    repo_path: str | None = None,
) -> CodeAnalysis | None:
    """Tek bir dosya diff'ini analiz eder (cache + maskeleme + audit).
    analyzer None ise 'analiz bekliyor' (audit=skipped). Hata olursa None
    döner ve audit=error yazılır — pano çökmez. errors verilirse hata SEBEBİ
    o listeye eklenir (çağıran kullanıcıya net mesaj gösterebilsin)."""
    ca_cfg = cfg.code_analysis
    now = now or datetime.now(timezone.utc)

    if is_excluded(file_path, ca_cfg):
        return None

    h = diff_hash(diff_text, commit_message)
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
        try:
            result = analyzer.analyze(file_path, truncated, commit_message=commit_message,
                                      repo_path=repo_path, ca_cfg=ca_cfg)
        except TypeError:
            # Eski/dar imzalı analizör — bağlamsız çağrıya düş.
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
        truncated=result.truncated,
        analyzed_at=now,
    )
    session.add(row)
    session.add(CodeAnalysisAudit(
        repo_id=repo_id, file_path=file_path, diff_hash=h,
        # chars_sent derin okumada gönderilen ek içeriği de kapsar
        chars_sent=len(truncated) + result.extra_chars,
        masked_secrets=n_secrets + result.masked_secrets,
        extra_reads=result.extra_reads,
        provider=result.provider, model=result.model, outcome="ok",
        truncated=result.truncated, sent_at=now,
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
    """Son commit'lerin dosya-bazlı diff'lerini üretir:
    (sha, author_email, commit_message, file, diff).
    author_email: commit'in git yazarı — analizi KİŞİYE atfetmek için (yardımcı
    veri, kimlik ingest'teki gibi e-posta ile developer'a eşlenir).
    commit_message: konu + gövde — analize NİYET bağlamı verir."""
    from pathlib import Path

    p = Path(repo_path)
    if not (p / ".git").exists():
        return
    # sha, yazar e-postası ve mesajı tek log çağrısında al. Commit'ler \x1e ile,
    # alanlar \x1f ile ayrılır (mesaj çok satırlı olabilir).
    raw = _run_git(["-C", str(p), "log", "-n", str(max_commits),
                    "--pretty=format:%H%x1f%ae%x1f%s%x1f%b%x1e"])
    commits = []
    for chunk in raw.split("\x1e"):
        parts = chunk.strip("\n").split("\x1f")
        if len(parts) < 4:
            continue
        sha, email, subject, body = parts[0], parts[1], parts[2], parts[3]
        msg = subject.strip() + ("\n\n" + body.strip() if body.strip() else "")
        commits.append((sha.strip(), email.strip().lower(), msg))
    for sha, email, msg in commits:
        files = [f for f in _run_git(["-C", str(p), "show", "--name-only",
                                      "--pretty=format:", sha]).splitlines() if f.strip()]
        for f in files:
            diff = _run_git(["-C", str(p), "show", "--format=", sha, "--", f])
            if diff.strip():
                yield sha, email, msg, f, diff


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


def _diff_iterator(cfg: Config, repo_cfg: dict, warnings: list[str]):
    """Repo yapılandırmasına göre doğru diff kaynağını seçer.

    None dönerse o repodan diff ÜRETİLEMEZ ve sebebi `warnings`'e yazılmıştır —
    sessizce atlamak, özelliği çalışıyor sanmaya yol açıyordu."""
    import os

    from app.services.diff_sources import iter_github_file_diffs, iter_gitlab_file_diffs

    ad = repo_cfg.get("name") or "(isimsiz repo)"
    saglayici = (cfg.sources.git.provider or "").lower()
    max_commits = 40

    # Yerel klasör her sağlayıcıda önceliklidir: varsa ağ trafiği hiç doğmaz.
    if repo_cfg.get("path"):
        return iter_git_file_diffs(repo_cfg["path"], max_commits)

    if saglayici == "github":
        from app.adapters.github import parse_slug

        ham = repo_cfg.get("slug") or repo_cfg.get("url") or ""
        slug = parse_slug(str(ham))
        if not slug:
            warnings.append(
                f"Repo '{ad}': GitHub yolu çözülemedi ('{ham}') — kod analizi bu repo "
                "için çalışamaz. Beklenen biçim: owner/repo"
            )
            return None
        token_env = cfg.sources.git.github.token_env
        return iter_github_file_diffs(
            slug, os.environ.get(token_env), max_commits, warnings, token_env
        )

    if saglayici == "gitlab":
        from app.adapters.gitlab import parse_project_path

        ham = repo_cfg.get("slug") or repo_cfg.get("url") or ""
        yol = parse_project_path(str(ham))
        if not yol:
            warnings.append(
                f"Repo '{ad}': GitLab proje yolu çözülemedi ('{ham}') — kod analizi bu "
                "repo için çalışamaz. Beklenen biçim: grup/proje"
            )
            return None
        gl = cfg.sources.git.gitlab
        return iter_gitlab_file_diffs(
            gl.base_url, yol, os.environ.get(gl.token_env), max_commits,
            warnings, gl.token_env,
        )

    warnings.append(
        f"Repo '{ad}': yerel 'path' tanımlı değil ve kaynak sağlayıcısı "
        f"('{saglayici or 'tanımsız'}') diff üretemiyor — kod analizi bu repo için atlandı."
    )
    return None


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
    source_warnings: list[str] = []
    # Diff üretilebilen repo sayısı: 0 ise sonuç "ok/0" DEĞİL, sebebi olan bir
    # durumdur (aşağıda). Eskiden github/gitlab kaynağında döngü hiç dönmüyor
    # ve özellik "çalışıyor ama yeni analiz yok" gibi görünüyordu.
    usable_repos = 0

    for repo_cfg in cfg.sources.git.repos:
        if budget <= 0:
            break
        if not isinstance(repo_cfg, dict):
            continue
        diffs = _diff_iterator(cfg, repo_cfg, source_warnings)
        if diffs is None:
            continue
        usable_repos += 1
        repo_row = session.scalar(select(Repo).where(Repo.name == repo_cfg.get("name")))
        repo_id = repo_row.id if repo_row else None
        for sha, email, commit_msg, file_path, diff in diffs:
            if budget <= 0:
                break
            if target_emails is not None and email not in target_emails:
                other_author += 1
                continue
            if is_excluded(file_path, ca):
                skipped += 1
                continue
            dev_id = only_developer_id if target_emails else _resolve_developer_id(session, dev_cache, email)
            h = diff_hash(diff, commit_msg)
            pre = session.scalar(select(CodeAnalysis).where(
                CodeAnalysis.repo_id == repo_id, CodeAnalysis.diff_hash == h))
            if pre is not None:
                if dev_id is not None and pre.developer_id is None:
                    pre.developer_id = dev_id
                cached += 1
                continue
            row = analyze_diff(session, cfg, analyzer, repo_id, file_path, sha, diff,
                               developer_id=dev_id, errors=errors,
                               commit_message=commit_msg,
                               # Derin okuma (repo'dan ek dosya) yalnız YEREL
                               # klasör varsa mümkün; uzak kaynakta None.
                               repo_path=repo_cfg.get("path"))
            budget -= 1
            if row is not None:
                analyzed += 1
    session.commit()
    out = {"status": "ok", "analyzed": analyzed, "cached": cached, "excluded": skipped}
    if target_emails is not None:
        out["other_author_skipped"] = other_author
    if source_warnings:
        out["warnings"] = source_warnings
    # Hiçbir repodan diff ÜRETİLEMEDİYSE bu "0 yeni analiz" değildir: kaynak
    # yapılandırması analizi imkânsız kılıyordur. "ok" demek, özelliği çalışıyor
    # sanmaya yol açıyordu — sebebi söyle.
    if usable_repos == 0:
        out["status"] = "no_source"
        out["note"] = source_warnings[-1] if source_warnings else (
            "Kod analizi için diff üretilebilecek repo yok — sources.git.repos "
            "altında yerel 'path' ya da uzak 'slug' tanımlı olmalı."
        )
        return out
    # Hiç yeni analiz olmadı ama LLM çağrıları hata verdiyse: sessiz "0 yeni"
    # yerine NET sebep göster (ör. kredi yetersiz).
    if analyzed == 0 and errors:
        out["status"] = "error"
        out["error_count"] = len(errors)
        out["note"] = errors[-1]
    return out
