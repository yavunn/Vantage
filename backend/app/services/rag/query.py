"""Soru → retrieval → prompt → cevap.

İki kural bu dosyanın varlık sebebi:

1. Retrieval boşsa ya da tüm isabetler eşiğin altındaysa LLM'e HİÇ GİDİLMEZ.
   Zayıf bağlamla konuşmak, bilmemekten kötüdür: model boşluğu kendi genel
   bilgisiyle doldurur ve sistem kaynağı olmayan bir cevabı kaynaklıymış gibi
   sunar. 'insufficient_context' dürüst boşluktur.
2. Cevap her zaman kaynak listesiyle döner. Kaynak gösteremeyen cevap dönmez.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import Config
from app.models import RagQueryAudit
from app.services.code_analysis import mask_secrets
from app.services.rag.embedding import EmbeddingProvider
from app.services.rag.index import Hit, build_index

SYSTEM_PROMPT = """Sen bir yazılım süreç danışmanısın. Aşağıdaki BAĞLAM bir takımın \
mühendislik sürecinden alınmış gerçek kayıtlardır (commit, PR, task, statü geçişi).

Kurallar:
- Yalnızca BAĞLAM'daki bilgilere dayanarak cevap ver. Bağlamda olmayan bir şeyi \
ASLA uydurma, tahmin etme, genel bilgiden tamamlama.
- Bağlam soruyu cevaplamaya yetmiyorsa tek bir cümleyle "Bu soruyu cevaplamak için \
elimde yeterli kayıt yok" de ve neyin eksik olduğunu söyle.
- Kişilerden değil SÜREÇTEN bahset. Kimin ne yaptığını yazma; nerede tıkanma, \
nerede gecikme olduğunu yaz.
- Suçlayıcı değil destekleyici dil kullan. Kırmızı bir gösterge "takım zorlanıyor, \
yardım gerekebilir" demektir, "kusur" demek değildir.
- Her iddianı hangi kayda dayandığını [1], [2] biçiminde işaretle.
- Türkçe yanıtla. Kısa ve somut ol."""

# Bağlam bloğu SONA gelir: sistem talimatı sabit kaldığı sürece prompt cache
# öneki korunur. Bağlamı sistem promptuna koymak, her soruda öneki geçersiz kılardı.
USER_TEMPLATE = "Soru: {question}\n\nBAĞLAM:\n{context_block}"

_KIND_LABEL = {"commit": "commit", "pr": "PR", "task": "task"}


@dataclass(frozen=True)
class Source:
    n: int
    chunk_id: int
    source_kind: str
    source_id: int
    score: float


@dataclass
class RagAnswer:
    status: Literal["ok", "insufficient_context", "disabled", "error"]
    answer: str | None = None
    sources: list[Source] = field(default_factory=list)
    reason: str | None = None


def _question_hash(question: str) -> str:
    return hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()


def build_context_block(hits: list[Hit]) -> tuple[str, int]:
    """Numaralı bağlam bloğu + maskelenen secret sayısı.

    Maskeleme LLM'e gitmeden ÖNCE: commit mesajına yapıştırılmış bir token
    indekste durabilir, ama dışarı çıkmaz."""
    lines: list[str] = []
    masked_total = 0
    for i, hit in enumerate(hits, start=1):
        safe, n = mask_secrets(hit.content)
        masked_total += n
        label = _KIND_LABEL.get(hit.source_kind, hit.source_kind)
        lines.append(f"[{i}] ({label}) {safe}")
    return "\n".join(lines), masked_total


def answer(
    session: Session,
    cfg: Config,
    question: str,
    team_id: int | None,
    provider: EmbeddingProvider | None = None,
    advisor=None,
    k: int | None = None,
) -> RagAnswer:
    """RAG cevabı üretir. provider/advisor verilmezse config'ten kurulur."""
    now = datetime.now(timezone.utc)
    q_hash = _question_hash(question)

    def _audit(outcome: str, chunks: int = 0, chars: int = 0, masked: int = 0,
               model: str | None = None) -> None:
        session.add(RagQueryAudit(
            team_id=team_id, question_hash=q_hash, chunks_sent=chunks,
            chars_sent=chars, masked_secrets=masked,
            provider=cfg.llm.provider, model=model, outcome=outcome, asked_at=now,
        ))
        session.commit()

    if not cfg.rag.enabled:
        return RagAnswer(status="disabled", reason="RAG katmanı kapalı (config: rag.enabled).")

    if provider is None:
        from app.services.rag.embedding import build_embedding_provider
        provider = build_embedding_provider(cfg)
    if provider is None:
        _audit("error")
        return RagAnswer(
            status="error",
            reason=f"Embedding sağlayıcısı kurulamadı (rag.embedding.provider: "
                   f"{cfg.rag.embedding.provider}).",
        )

    if advisor is None:
        from app.llm.advisor import build_advisor
        advisor = build_advisor(cfg)
    if advisor is None:
        _audit("error")
        return RagAnswer(
            status="error",
            reason="LLM katmanı kapalı (config: llm.enabled) — cevap üretilemez.",
        )

    try:
        query_vec = provider.embed([question])[0]
    except Exception as e:  # noqa: BLE001 — uç 500 vermesin, sebep dönsün
        _audit("error", model=provider.model)
        return RagAnswer(
            status="error",
            reason=f"Soru vektöre çevrilemedi ({type(e).__name__}) — "
                   "embedding sağlayıcısı erişilebilir mi?",
        )

    index, _impl = build_index(session, cfg, provider.model)
    top_k = k or cfg.rag.retrieval.top_k
    hits = [
        h for h in index.search(query_vec, top_k, team_id)
        if h.score >= cfg.rag.retrieval.min_score
    ]

    if not hits:
        # LLM'e GİTMİYORUZ. Bu dalın testi var (advisor.call_count == 0).
        _audit("insufficient_context", model=provider.model)
        return RagAnswer(
            status="insufficient_context",
            reason="Bu soruyla yeterince ilgili kayıt bulunamadı. Senkron çalıştı mı, "
                   "ilgili takımda commit/task var mı kontrol edin.",
        )

    context_block, masked = build_context_block(hits)
    user_msg = USER_TEMPLATE.format(question=question.strip(), context_block=context_block)

    try:
        text = advisor.chat(SYSTEM_PROMPT, user_msg)
    except Exception as e:  # noqa: BLE001
        _audit("error", len(hits), len(context_block), masked, provider.model)
        return RagAnswer(
            status="error", reason=f"LLM çağrısı başarısız ({type(e).__name__}).",
        )

    _audit("ok", len(hits), len(context_block), masked, provider.model)
    return RagAnswer(
        status="ok",
        answer=text.strip() if isinstance(text, str) else str(text),
        sources=[
            Source(n=i, chunk_id=h.chunk_id, source_kind=h.source_kind,
                   source_id=h.source_id, score=round(h.score, 4))
            for i, h in enumerate(hits, start=1)
        ],
    )
