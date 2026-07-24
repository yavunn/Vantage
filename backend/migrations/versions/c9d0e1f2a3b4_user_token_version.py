"""users.token_version (oturum geçersiz kılma)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-24

Parola değişince artırılır; eski JWT'lerin 'tv' claim'i eşleşmez → 401.
IDEMPOTENT: kolon zaten varsa (create_all/_COLUMN_PATCHES) atlar.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("users"):
        cols = {c["name"] for c in insp.get_columns("users")}
        if "token_version" not in cols:
            op.add_column("users", sa.Column(
                "token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("users"):
        cols = {c["name"] for c in insp.get_columns("users")}
        if "token_version" in cols:
            op.drop_column("users", "token_version")
