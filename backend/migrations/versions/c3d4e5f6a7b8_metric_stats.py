"""metric_results: sample_size + stats (medyan/p90 dağılımı)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-20

İstatistiksel dürüstlük: ortalama tek başına yanıltıcı. Süre metriklerinde
medyan ve p90 dağılımı (stats jsonb) + hesabın dayandığı örneklem büyüklüğü
(sample_size) saklanır. Değer yoksa alanlar NULL kalır — uydurma yok.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("metric_results", sa.Column("sample_size", sa.Integer(), nullable=True))
    op.add_column("metric_results", sa.Column("stats", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("metric_results", "stats")
    op.drop_column("metric_results", "sample_size")
