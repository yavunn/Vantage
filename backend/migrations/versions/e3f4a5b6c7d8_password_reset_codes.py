"""password_reset_codes ("şifremi unuttum" 6 haneli kod akışı)

Revision ID: e3f4a5b6c7d8
Revises: c6d7e8f9a0b1
Create Date: 2026-08-05

Tabloda SIR SAKLANMAZ: ne kodun kendisi ne de reset jetonu düz metin tutulur —
ikisi de sha256 hash'iyle saklanır. Kolon adları ve tipleri modeldeki
PasswordResetCode ile birebir aynı olmalı (tests/test_migrations.py bunu
alembic şeması ↔ model karşılaştırmasıyla zorluyor).

IDEMPOTENT: şema bu projede iki yoldan kurulabiliyor (alembic ve açılıştaki
create_all); tablo zaten varsa atlar (bkz. migrations/idempotent.py).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotent import indeks_ekle, tablo_var

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not tablo_var("password_reset_codes"):
        op.create_table(
            "password_reset_codes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reset_token_hash", sa.String(length=64), nullable=True),
            sa.Column("reset_token_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    # Kod doğrulaması her istekte kullanıcının açık kodlarını arar — indekssiz
    # tam tarama olurdu.
    indeks_ekle("ix_password_reset_codes_user_id", "password_reset_codes", ["user_id"])


def downgrade() -> None:
    if tablo_var("password_reset_codes"):
        op.drop_index("ix_password_reset_codes_user_id",
                      table_name="password_reset_codes")
        op.drop_table("password_reset_codes")
