"""code_analysis_audit.extra_reads (derin okuma denetimi)

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-27

Analiz varsayılan olarak yalnız diff + commit mesajı görür. Model gerekirse
en fazla 3 ek dosya okuyabilir; kaç dosya okunduğu denetim kaydına yazılır
(hangi verinin LLM'e gittiği izlenebilir kalsın).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("code_analysis_audit", sa.Column(
        "extra_reads", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("code_analysis_audit", "extra_reads")
