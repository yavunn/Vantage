"""Yerel / OpenAI-uyumlu LLM uçlarına TEK giriş noktası.

NEDEN TEK DOSYA: aynı `llm.local` ayarını okuyan birden çok çağrı yolu vardı ve
biri API anahtarını göndermiyordu — kullanıcı için açıklanamaz bir "kod analizi
çalışıyor ama commit değerlendirmesi hep kural tabanlı" durumu doğuyordu (bkz.
PROJE_DENETIM madde 22). Bağlam sınırı da tam olarak aynı hataya açık: bir
çağrıda ayarlanıp diğerinde unutulursa prompt SESSİZCE kesilir.

BAĞLAM SINIRI — ölçülmüş sorun:
Ollama'nın OpenAI-uyumlu ucu (/v1/chat/completions) `options` kabul etmez, yani
num_ctx oradan ayarlanamaz ve sunucu varsayılan 4096 token'a düşer. Ölçüm
(qwen2.5:14b): config'in kendi sınırıyla (max_diff_lines=400) üretilen gerçek
bir analiz prompt'u 30.768 karakter (~7.700 token) iken Ollama prompt_tokens
olarak 2050 saydı — diff'in dörtte üçü modele HİÇ ulaşmadı ama model yine de
7 boyutta puanlı JSON üretti. Kesme sessiz olduğu için sonuç "çalışıyor" görünüp
yanlış oluyordu.

Bu modül üç şeyi garanti eder:
1. num_ctx gerçekten gönderilir (ollama stilinde /api/chat kullanılarak),
2. prompt bütçeyi aşıyorsa GÖNDERMEDEN ÖNCE kırpılır ve kırpıldığı BEYAN edilir,
3. uç yine de beklenenden az token gördüyse bu hata olarak yüzeye çıkar.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import LLMLocal

# Türkçe metin + kod için karakter/token oranı — ÖLÇÜLDÜ, tahmin edilmedi.
# qwen2.5:14b, gerçek bir 400 satırlık analiz prompt'u: 30.766 karakter →
# uç 15.296 token saydı, yani 2,01 karakter/token. İlk yazılan 3.0 değeri
# token sayısını EKSİK tahmin ediyordu; eksik tahmin, bütçeye sığdığını sanıp
# uca fazla veri göndermek ve sessiz kesilmeye geri dönmek demektir.
# Oran düşük tutulur: fazla tahmin güvenli tarafta hata yapar (biraz bağlam
# boşta kalır), az tahmin ise düzeltilen hatayı geri getirir.
CHARS_PER_TOKEN = 2.0

# Uç, tahminin bu oranından azını gördüyse prompt kesilmiş demektir.
TRUNCATION_ALARM_RATIO = 0.8


class ContextOverflowError(RuntimeError):
    """Uç, gönderilen prompt'un belirgin bir kısmını görmemiş.

    Sessiz kalmak yerine hata: analiz sonucu üretilse bile eksik girdiye
    dayandığı için güvenilir değildir."""


@dataclass
class LocalChatResult:
    text: str
    prompt_tokens: int | None   # uç bildirdiyse gerçek, yoksa None
    sent_chars: int
    truncated: bool             # bütçe için prompt kırpıldı mı


def estimate_tokens(text: str) -> int:
    return int(len(text or "") / CHARS_PER_TOKEN) + 1


def prompt_budget(local: LLMLocal) -> int:
    """Prompt'a ayrılan token bütçesi (yanıt payı düşülmüş)."""
    return max(256, int(local.context_tokens) - int(local.reserve_output_tokens))


def fit_to_budget(text: str, budget_tokens: int) -> tuple[str, bool]:
    """Metni bütçeye sığdırır. Döner: (metin, kırpıldı_mı).

    Kırpma SONDAN yapılır ve yerine görünür bir işaret bırakılır: modelin
    "burada devamı vardı" bilgisini görmesi, hiç bilmemesinden iyidir."""
    limit_chars = int(budget_tokens * CHARS_PER_TOKEN)
    if len(text or "") <= limit_chars:
        return text, False
    isaret = "\n\n[... bağlam sınırı nedeniyle kısaltıldı ...]"
    kesim = max(0, limit_chars - len(isaret))
    return text[:kesim] + isaret, True


def local_chat(
    local: LLMLocal,
    system: str,
    user: str,
    api_key: str | None = None,
    timeout: float = 120.0,
    max_output_tokens: int | None = None,
) -> LocalChatResult:
    """Yerel uca sohbet isteği. Bağlam bütçesi burada zorlanır."""
    budget = prompt_budget(local)
    system_tokens = estimate_tokens(system)
    user, truncated = fit_to_budget(user, max(128, budget - system_tokens))
    gonderilen = estimate_tokens(system) + estimate_tokens(user)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    base = local.base_url.rstrip("/")

    if (local.api_style or "ollama").lower() == "ollama":
        payload: dict = {
            "model": local.model,
            "messages": messages,
            "stream": False,
            # ASIL DÜZELTME: bağlam uzunluğu burada bildiriliyor.
            "options": {"num_ctx": int(local.context_tokens)},
        }
        if max_output_tokens:
            payload["options"]["num_predict"] = int(max_output_tokens)
        resp = httpx.post(f"{base}/api/chat", json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        text = (data.get("message") or {}).get("content", "")
        prompt_tokens = data.get("prompt_eval_count")
    else:
        payload = {"model": local.model, "messages": messages}
        if max_output_tokens:
            payload["max_tokens"] = int(max_output_tokens)
        resp = httpx.post(
            f"{base}/v1/chat/completions", json=payload, headers=headers, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        prompt_tokens = (data.get("usage") or {}).get("prompt_tokens")

    # Uç bildirdiği token sayısı tahminin belirgin altındaysa prompt kesilmiştir.
    if prompt_tokens is not None and gonderilen > 0:
        if prompt_tokens < gonderilen * TRUNCATION_ALARM_RATIO:
            raise ContextOverflowError(
                f"uç prompt'un yalnız {prompt_tokens} token'ını gördü "
                f"(gönderilen ~{gonderilen}); bağlam penceresi küçük olabilir — "
                f"llm.local.context_tokens ({local.context_tokens}) ve sunucunun "
                "kendi sınırını (Ollama: OLLAMA_CONTEXT_LENGTH) kontrol edin"
            )

    return LocalChatResult(
        text=text,
        prompt_tokens=prompt_tokens,
        sent_chars=len(system or "") + len(user or ""),
        truncated=truncated,
    )
