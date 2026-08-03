"""Chunk üretimi + gömme + DB'ye yazma.

Maliyet freni `content_hash`: kayıt değişmediyse embedding çağrısı YAPILMAZ.
Model değişirse hash aynı olsa bile yeniden gömülür — farklı modellerin
vektörleri aynı uzayda değildir.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Config
from app.models import DocChunk
from app.services.rag.chunker import build_chunks
from app.services.rag.embedding import EmbeddingProvider

# Embedding ucuna tek seferde gönderilecek metin sayısı.
BATCH = 32


def reindex(session: Session, cfg: Config,
            provider: EmbeddingProvider | None) -> dict:
    """Normalize kayıtları indeksler. Dönen sayılar YENİ/GÜNCELLENEN kayıttır.

    RAG kapalıysa ya da sağlayıcı yoksa hiçbir şey yapmaz — ve bunu 'warnings'
    ile SÖYLER. Sessiz atlama, entegrasyonu çalışıyor sanmaya yol açar."""
    stats: dict = {"chunks": 0, "embedded": 0, "skipped": 0, "warnings": []}
    if not cfg.rag.enabled:
        return stats
    if provider is None:
        stats["warnings"].append(
            "RAG açık ama embedding sağlayıcısı kurulamadı "
            f"(rag.embedding.provider: {cfg.rag.embedding.provider}) — indeksleme atlandı."
        )
        return stats

    # Takımsız kayıt İNDEKSLENMEZ. Arama takım filtresini SQL'de uygular
    # (`DocChunk.team_id == team_id`, bkz. rag/index.py) ve tek sorgu ucu olan
    # /api/teams/{id}/ask her zaman gerçek bir takım id'si geçirir — yani
    # team_id'si NULL olan bir chunk hiçbir sorguda GETİRİLEMEZ. Gömmek onu
    # erişilebilir yapmaz, yalnızca embedding maliyeti ödetir ve indeks
    # sayacını şişirerek "kayıtlar indekste var" yanılgısı üretir.
    #
    # Filtreyi gevşetip takımsızları her takıma göstermek YANLIŞ olurdu: o
    # kayıtlar "herkesin" değil, "hiç kimsenin" — ve takım sızıntısını tip
    # düzeyinde engelleyen kuralı deler.
    all_chunks = build_chunks(session, cfg)
    chunks = [ch for ch in all_chunks if ch.team_id is not None]
    orphan = len(all_chunks) - len(chunks)
    if orphan:
        stats["warnings"].append(
            f"{orphan} kayıt hiçbir takıma bağlı olmadığı için indekslenmedi — "
            "takım bazlı asistan sorgularında getirilemezler. Sebep genellikle "
            "takımı belirlenemeyen bir Trello board'u ya da takımsız repo'dur; "
            "Entegrasyon ekranından takım atayın."
        )
    stats["orphan_chunks"] = orphan
    stats["chunks"] = len(chunks)
    existing = {
        (row.source_kind, row.source_id, row.chunk_index): row
        for row in session.scalars(select(DocChunk))
    }

    pending: list[tuple[DocChunk, str]] = []
    seen: set[tuple[str, int, int]] = set()
    for ch in chunks:
        key = (ch.source_kind, ch.source_id, ch.chunk_index)
        seen.add(key)
        row = existing.get(key)
        digest = ch.content_hash
        if row is None:
            row = DocChunk(
                source_kind=ch.source_kind, source_id=ch.source_id,
                chunk_index=ch.chunk_index,
            )
            session.add(row)
        elif (row.content_hash == digest and row.model == provider.model
                and row.embedding):
            # İçerik de model de aynı → yeniden gömmeye gerek yok.
            row.team_id = ch.team_id
            stats["skipped"] += 1
            continue
        row.team_id = ch.team_id
        row.content = ch.content
        row.content_hash = digest
        pending.append((row, ch.content))

    session.flush()

    now = datetime.now(timezone.utc)
    for start in range(0, len(pending), BATCH):
        batch = pending[start:start + BATCH]
        try:
            vectors = provider.embed([content for _, content in batch])
        except Exception as e:  # noqa: BLE001 — senkron çökmesin, sebep raporlansın
            stats["warnings"].append(
                f"Embedding sağlayıcısına ulaşılamadı ({type(e).__name__}) — "
                f"{len(pending) - stats['embedded']} chunk gömülmeden kaldı. "
                "Yerel model çalışıyor mu kontrol edin."
            )
            break
        # strict: sağlayıcı eksik vektör döndürürse sessizce yanlış chunk'a
        # yazmak yerine patlasın (embed() zaten sayıyı doğruluyor).
        for (row, _), vec in zip(batch, vectors, strict=True):
            row.embedding = vec
            row.model = provider.model
            row.embedded_at = now
            stats["embedded"] += 1

    # Kaynakta artık olmayan chunk indekste kalmasın: silinmiş bir task'ın
    # metni cevaba kaynak olarak gösterilirse sistem yalan söylemiş olur.
    stale = [row for key, row in existing.items() if key not in seen]
    for row in stale:
        session.delete(row)
    stats["removed"] = len(stale)

    session.commit()
    return stats
