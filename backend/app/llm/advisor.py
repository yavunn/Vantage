"""Opsiyonel LLM öneri katmanı (Faz 5 / stretch).

On-prem kısıtı gereği:
- Varsayılan KAPALI (config: llm.enabled=false).
- Dışarı veri gönderen sağlayıcı (claude) bilinçli olarak seçilmedikçe
  hiçbir veri şirket dışına çıkmaz.
- Arayüz soyut: yerel/self-hosted bir modele (Ollama, vLLM — OpenAI-uyumlu
  uç) aynı arayüzle bağlanılır. Sağlayıcı eklemek çekirdeği değiştirmez.

LLM'e KİŞİSEL veri gönderilmez: yalnızca takım seviyesi metrik özetleri
context olarak verilir.
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

import httpx

from app.core.config import Config

PROMPT_TEMPLATE = """Sen bir yazılım süreç danışmanısın. Aşağıda bir takımın
mühendislik sağlığı metrikleri var. Suçlayıcı olmayan, destek dilli, somut
3 öneri yaz. Kişilerden değil süreçten bahset. Türkçe yanıtla.

Takım: {team_name}
Metrikler:
{metrics_block}
"""


@runtime_checkable
class LLMAdvisor(Protocol):
    def advise(self, team_name: str, metrics_block: str) -> str: ...

    # Serbest sistem+kullanıcı mesajı — RAG gibi kendi prompt'unu kuran
    # katmanlar için. Sağlayıcı seçimi (yerel/claude) tek yerde kalsın diye
    # ayrı bir istemci yazmak yerine arayüz buradan genişletildi.
    def chat(self, system: str, user: str) -> str: ...


class LocalAdvisor:
    """Self-hosted, OpenAI-uyumlu uca (Ollama/vLLM) bağlanır — veri dışarı çıkmaz."""

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def advise(self, team_name: str, metrics_block: str) -> str:
        prompt = PROMPT_TEMPLATE.format(team_name=team_name, metrics_block=metrics_block)
        return self.chat("", prompt)

    def chat(self, system: str, user: str) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        resp = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json={"model": self.model, "messages": messages},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class ClaudeAdvisor:
    """Claude API — dışarı veri gönderir; yalnızca bilinçli config ile açılır."""

    def __init__(self, model: str, api_key_env: str):
        self.model = model
        self.api_key = os.environ.get(api_key_env, "")

    def advise(self, team_name: str, metrics_block: str) -> str:
        prompt = PROMPT_TEMPLATE.format(team_name=team_name, metrics_block=metrics_block)
        return self.chat("", prompt)

    def chat(self, system: str, user: str) -> str:
        payload: dict = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            # Sistem talimatı ayrı alanda: sabit kaldığı sürece prompt cache
            # önekini korur. Bağlam kullanıcı mesajının sonunda taşınır.
            payload["system"] = system
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


def build_advisor(cfg: Config) -> LLMAdvisor | None:
    """Config'ten danışman kurar. Kapalıysa None — çağıran taraf özelliği
    'devre dışı' olarak sunar, asla sessizce dış servise düşmez."""
    if not cfg.llm.enabled:
        return None
    if cfg.llm.provider == "local":
        return LocalAdvisor(cfg.llm.local.base_url, cfg.llm.local.model)
    if cfg.llm.provider == "claude":
        return ClaudeAdvisor(cfg.llm.claude.model, cfg.llm.claude.api_key_env)
    return None
