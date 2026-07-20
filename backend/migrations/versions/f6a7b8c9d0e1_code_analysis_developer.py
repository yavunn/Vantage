"""code_analyses.developer_id (kişi-bazlı analiz)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-20

Kod analizi git commit YAZARINA atfedilebilsin: admin herkesi tek tek, kullanıcı
kendi kodunu analiz eder. developer_id NULL = atfedilmemiş (repo/takım düzeyi).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("code_analyses", sa.Column("developer_id", sa.Integer(),
                  sa.ForeignKey("developers.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("code_analyses", "developer_id")
