"""Commit pratiği değerlendirmesi.

ÖNEMLİ: Skor kişiye değil COMMIT PRATİĞİNE aittir (mesaj kalitesi, atomiklik
işareti, tutarlılık, düzen). Ceza dili yok — yapıcı, destek dilli.

İki mod:
- AI (config llm.enabled + provider): commit mesajlarını LLM'e verir.
- Kural tabanlı fallback: AI kapalı/başarısızsa çalışır — özellik ÇÖKMEZ.
"""
from __future__ import annotations

import json
import os
import re

import httpx

from app.core.config import Config

_CONVENTIONAL = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(.+\))?!?:\s", re.IGNORECASE
)
_GENERIC = {"update", "fix", "wip", "changes", "commit", "test", ".", "..", "...", "asdf", "stuff", "misc", "temp"}


def _first_line(msg: str | None) -> str:
    return (msg or "").strip().splitlines()[0].strip() if (msg or "").strip() else ""


def rule_based_review(commits: list[dict]) -> dict:
    """commits: [{message, committed_at, ...}] — en yeni önce olabilir."""
    n = len(commits)
    if n == 0:
        return {"score": None, "summary": "Değerlendirilecek commit yok.", "details": {}, "provider": "rule"}

    good_len = 0
    non_generic = 0
    conventional = 0
    with_body = 0
    for c in commits:
        first = _first_line(c.get("message"))
        low = first.lower().rstrip(".")
        if 10 <= len(first) <= 72:
            good_len += 1
        if low and low not in _GENERIC and len(low) >= 8:
            non_generic += 1
        if _CONVENTIONAL.match(first):
            conventional += 1
        body = (c.get("message") or "").strip().splitlines()
        if len(body) > 1 and any(l.strip() for l in body[1:]):
            with_body += 1

    len_score = good_len / n
    clarity_score = non_generic / n
    convention_score = conventional / n
    body_score = with_body / n

    # Düzen: commitler zamana yayılmış mı (tek güne yığılma zayıf sinyal).
    dates = [c["committed_at"].date() for c in commits if c.get("committed_at")]
    distinct_days = len(set(dates)) if dates else 1
    regularity_score = min(1.0, distinct_days / max(1, min(n, 10)))

    # Ağırlıklar: mesaj netliği ve uzunluğu en önemli; konvansiyon bonus.
    score = round(
        100 * (0.30 * clarity_score + 0.25 * len_score + 0.20 * body_score
               + 0.15 * convention_score + 0.10 * regularity_score)
    )

    strengths, improvements = [], []
    (strengths if clarity_score >= 0.7 else improvements).append(
        "Mesajlar açıklayıcı" if clarity_score >= 0.7 else "Bazı mesajlar fazla genel (ör. 'update', 'fix') — ne/neden yazılabilir")
    (strengths if len_score >= 0.7 else improvements).append(
        "Başlık uzunlukları uygun" if len_score >= 0.7 else "Başlıklar çok kısa/uzun — 10-72 karakter hedefle")
    (strengths if body_score >= 0.4 else improvements).append(
        "Gövde açıklamaları var" if body_score >= 0.4 else "Karmaşık commitlerde gövde açıklaması ekleyin")
    (strengths if convention_score >= 0.5 else improvements).append(
        "Konvansiyonel commit kullanımı iyi" if convention_score >= 0.5 else "İsteğe bağlı: 'feat:'/'fix:' gibi önekler tutarlılık katar")

    summary = "Güçlü yönler: " + "; ".join(strengths) + ". İyileştirme: " + "; ".join(improvements) + "."
    details = {
        "clarity": round(clarity_score * 100),
        "length": round(len_score * 100),
        "body": round(body_score * 100),
        "convention": round(convention_score * 100),
        "regularity": round(regularity_score * 100),
        "commit_count": n,
    }
    return {"score": score, "summary": summary, "details": details, "provider": "rule"}


_AI_PROMPT = """Sen yardımcı bir yazılım mentörüsün. Aşağıda bir geliştiricinin
KENDİ deposundaki commit mesajları var. Commit YAZMA PRATİĞİNİ değerlendir
(mesaj netliği, atomiklik, tutarlılık, düzen). Kişiyi yargılama, yapıcı ve
destek dilli ol. Türkçe yanıtla.

Yanıtı SADECE şu JSON formatında ver:
{{"score": <0-100 tam sayı>, "summary": "<2-3 cümle yapıcı geri bildirim>"}}

Commit mesajları:
{commits_block}
"""


def _ai_call(cfg: Config, commits_block: str) -> dict | None:
    """LLM'den skor+özet dener; başarısızsa None (çağıran kurala düşer)."""
    if not cfg.llm.enabled or cfg.llm.provider not in ("local", "claude"):
        return None
    prompt = _AI_PROMPT.format(commits_block=commits_block)
    try:
        if cfg.llm.provider == "local":
            resp = httpx.post(
                f"{cfg.llm.local.base_url.rstrip('/')}/v1/chat/completions",
                json={"model": cfg.llm.local.model, "messages": [{"role": "user", "content": prompt}]},
                timeout=120,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
        else:  # claude
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": os.environ.get(cfg.llm.claude.api_key_env, ""),
                         "anthropic-version": "2023-06-01"},
                json={"model": cfg.llm.claude.model, "max_tokens": 512,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=120,
            )
            resp.raise_for_status()
            text = resp.json()["content"][0]["text"]
    except (httpx.HTTPError, KeyError, IndexError):
        return None

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    score = data.get("score")
    if not isinstance(score, (int, float)):
        return None
    return {
        "score": max(0, min(100, round(score))),
        "summary": str(data.get("summary", "")).strip() or "AI değerlendirmesi.",
        "provider": cfg.llm.provider,
    }


def review_commits(cfg: Config, commits: list[dict]) -> dict:
    """AI açıksa dener, değilse/başarısızsa kural tabanlı. Her zaman sonuç döner."""
    rule = rule_based_review(commits)
    if not commits:
        return rule
    block = "\n".join(f"- {_first_line(c.get('message'))}" for c in commits[:50])
    ai = _ai_call(cfg, block)
    if ai is None:
        return rule
    # AI özet + skor; kural kırılımını details olarak koru (şeffaflık).
    return {"score": ai["score"], "summary": ai["summary"], "details": rule["details"], "provider": ai["provider"]}
