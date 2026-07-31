"""Embedding sağlayıcıları — SOHBET sağlayıcısından bağımsız.

Bu bağımsızlık zorunlu: Anthropic'in embedding ucu YOKTUR. `llm.provider: claude`
seçili olsa bile vektörler yerelden gelir. İkisini tek ayara bağlamak, Claude
seçildiğinde RAG'ı sessizce çalışmaz hâle getirirdi — en kötü hata türü.

`hash` sağlayıcısı ağsız ve deterministiktir: testler gerçek bir modele (ve
çalışan bir Ollama'ya) bağlı kalmasın diye vardır. Üretimde kullanılmaz.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

import httpx

from app.core.config import Config

_TOKEN = re.compile(r"[\wçğıöşüÇĞİÖŞÜ]+", re.UNICODE)


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def model(self) -> str: ...

    @property
    def dim(self) -> int: ...


def cosine(a: list[float], b: list[float]) -> float:
    """Kosinüs benzerliği. Boyut uyuşmazlığında 0 döner — farklı modellerin
    vektörleri aynı uzayda değildir; sessizce kıyaslamak saçma sonuç üretir."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class LocalEmbedding:
    """Self-hosted, OpenAI-uyumlu `/v1/embeddings` ucu (Ollama, vLLM).

    Veri dışarı çıkmaz. Uç erişilemezse çağıran tarafa istisna gider ve
    indeksleme NET sebeple atlanır — sessizce boş vektör üretilmez."""

    def __init__(self, base_url: str, model: str, dim: int = 768):
        self.base_url = base_url.rstrip("/")
        self._model = model
        self._dim = dim

    @property
    def model(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = httpx.post(
            f"{self.base_url}/v1/embeddings",
            json={"model": self._model, "input": texts},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
        if len(data) != len(texts):
            raise ValueError(
                f"Embedding ucu {len(texts)} metin için {len(data)} vektör döndürdü."
            )
        vectors = [list(item["embedding"]) for item in data]
        if vectors:
            self._dim = len(vectors[0])
        return vectors


class HashEmbedding:
    """Ağsız, deterministik hashing-vectorizer (yalnız test).

    Gerçek bir dil modeli değildir ama SÖZCÜK örtüşmesini yakalar: aynı
    kelimeleri paylaşan metinler yakın vektör üretir. Retrieval hattını
    uçtan uca, ağ olmadan test etmeye bu yeter."""

    def __init__(self, dim: int = 256):
        self._dim = dim

    @property
    def model(self) -> str:
        return f"hash-{self._dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self._dim
            for token in _TOKEN.findall(text.lower()):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                bucket = int.from_bytes(digest[:4], "big") % self._dim
                vec[bucket] += 1.0
            norm = math.sqrt(sum(v * v for v in vec))
            out.append([v / norm for v in vec] if norm else vec)
        return out


def build_embedding_provider(cfg: Config) -> EmbeddingProvider | None:
    """Config'ten sağlayıcı kurar. RAG kapalıysa None — çağıran taraf özelliği
    'devre dışı' olarak sunar, asla sessizce başka bir sağlayıcıya düşmez."""
    if not cfg.rag.enabled:
        return None
    emb = cfg.rag.embedding
    if emb.provider == "local":
        return LocalEmbedding(emb.base_url, emb.model)
    if emb.provider == "hash":
        return HashEmbedding()
    return None
