"""Task: kaynakta son görülme / kayıp damgası

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-08-04

Ingest yalnız upsert yapıyordu: kaynaktan silinen kayıt DB'de sonsuza kadar
kalıyordu. Canlı ölçüm — Trello board'unda 21 kart varken DB'de 26 task vardı;
aradaki 5'i artık çekilmeyen eski bir board'dan kalmıştı, her senkronda
"hiçbir takıma bağlı değil" uyarısı üretiyor ve metrik paydalarına giriyordu.

KALICI SİLME YOK: kayıt saklanır, yalnız metrik ve asistan indeksinden çıkar.
Damga da yalnızca çekimi EKSİKSİZ olan kaynaklar için vurulur — kaynak hata
verdiyse gelmeyen kayıt "silinmiş" değil "okunamamış"tır.
"""
from __future__ import annotations

import sqlalchemy as sa

from migrations.idempotent import kolon_dusur, kolon_ekle

revision = "a4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    kolon_ekle("tasks", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    kolon_ekle("tasks", sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    kolon_dusur("tasks", "missing_since")
    kolon_dusur("tasks", "last_seen_at")
