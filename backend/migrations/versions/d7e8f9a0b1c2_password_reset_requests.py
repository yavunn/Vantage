"""Parola sıfırlama talepleri ("şifremi unuttum")

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-08-04

Bu kurulum on-prem ve mail altyapısı YOK; token'lı sıfırlama linki göndermek
var olmayan bir SMTP'yi varmış gibi kurgulamak olurdu. Talep bir kuyruğa düşer,
yönetici/İK panelde görür ve zaten var olan sıfırlama akışını kullanır.

Tabloda SIR SAKLANMAZ: token yok, parola yok — yalnız "şu e-posta için talep
geldi" olgusu. `user_id` hesabın var olup olmadığını yöneticiye gösterir; uç
yanıtında asla dönmez (kullanıcı numaralandırma).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from migrations.idempotent import tablo_var

revision = "d7e8f9a0b1c2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if tablo_var("password_reset_requests"):
        return  # create_all zaten yaratmış olabilir (migration'sız kurulum)
    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_reset_requests_email", "password_reset_requests", ["email"])


def downgrade() -> None:
    if tablo_var("password_reset_requests"):
        op.drop_index("ix_password_reset_requests_email",
                      table_name="password_reset_requests")
        op.drop_table("password_reset_requests")
