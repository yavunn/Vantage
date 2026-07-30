"""Kullanıcı başına dış servis erişim anahtarı (user_credentials)

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-30

Sunucu geneli tek GITHUB_TOKEN iki sorun üretiyordu: (1) çalışanın özel
reposuna erişmek yöneticinin o repoya erişmesini gerektiriyordu, (2) token'ın
ulaşabildiği HER repo, panele girebilen HERKESE açıktı. Artık her kullanıcı
kendi anahtarını saklıyor; değer at-rest şifreli (Fernet, CREDENTIALS_ENC_KEY).

Öksüz `project_credentials` tablosuna DOKUNULMADI: proje başına tasarlanmıştı
(unique project_id), bu tablo kullanıcı başına. Ayrı bir temizlik konusu.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("user_credentials"):
        return
    op.create_table(
        "user_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("hint", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        # Kullanıcı başına sağlayıcı başına TEK anahtar — upsert bu kısıta dayanır.
        sa.UniqueConstraint("user_id", "provider"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("user_credentials"):
        op.drop_table("user_credentials")
