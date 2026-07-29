"""add users.must_change_password

Revision ID: a1b2c3d4e5f6
Revises: e1f2a3b4c5d6
Create Date: 2026-07-09

Admin'in verdiği geçici parolayı ilk girişte zorunlu kılan bayrak.

IDEMPOTENT: kolon zaten varsa (create_all ya da e1f2a3b4c5d6 tabloyu tam
haliyle yarattıysa) atlar. Önceki hâli korumasız ALTER TABLE'dı ve users
hiçbir migration'da yaratılmadığı için temiz kurulumda burada çöküyordu.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("users"):
        cols = {c["name"] for c in insp.get_columns("users")}
        if "must_change_password" not in cols:
            op.add_column(
                "users",
                sa.Column(
                    "must_change_password",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("users"):
        cols = {c["name"] for c in insp.get_columns("users")}
        if "must_change_password" in cols:
            op.drop_column("users", "must_change_password")
