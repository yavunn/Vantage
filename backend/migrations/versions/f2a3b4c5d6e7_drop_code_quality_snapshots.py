"""Artık kullanılmayan code_quality_snapshots tablosunu düşür

Revision ID: f2a3b4c5d6e7
Revises: d0e1f2a3b4c5
Create Date: 2026-07-29

Dış kod-kalitesi taraması (SonarQube/linter) e84c6b5'te kaldırıldı; kod taraması
artık kendi AI modülümüzle yapılıyor. Tabloyu yaratan initial_schema duruyor
(migration geçmişi geriye dönük değiştirilmez), ama hiçbir model ona eşlenmiyor
ve hiçbir kod okumuyor/yazmıyor — şemada "bu ne?" sorusu üreten ölü bir tablo.

VERİ KAYBI RİSKİ: tabloda satır varsa onlar da gider. Bilinçli: kayıtlar
kaldırılmış bir entegrasyonun çıktısı, hiçbir metrik onlara dayanmıyor.
Yine de tablo yoksa sessiz geçilir (has_table koruması).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("code_quality_snapshots"):
        op.drop_table("code_quality_snapshots")


def downgrade() -> None:
    """Geri alınırsa tablo BOŞ olarak geri gelir (veri geri getirilemez)."""
    bind = op.get_bind()
    if sa.inspect(bind).has_table("code_quality_snapshots"):
        return
    # Sütunlar initial_schema'daki (18731b1ad718) tanımın birebir aynısı.
    op.create_table(
        "code_quality_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("complexity", sa.Float(), nullable=True),
        sa.Column("duplication", sa.Float(), nullable=True),
        sa.Column("code_smells", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
