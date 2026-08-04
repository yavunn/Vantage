"""Kaynak bazında son başarılı senkron damgası (artımlı çekim)

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-08-04

Adaptörlerin hepsi `fetch_*(since=...)` destekliyordu ama ingest hepsini
PARAMETRESİZ çağırıyordu — kod tabanında `since` üreten tek satır yoktu.
Sonuç her saat TAM çekim: GitHub'da repo başına ~350 istek (10 sayfa commit +
150 commit detayı + 200 PR + review istekleri). 5000/saat sınırında bu ~13
repo tavanı demek; token'sız kurulumda (60/saat) ilk repoda biter.

Damga yalnız UYARISIZ çekimden sonra ilerletilir: kısmi başarıda ilerletmek,
alınamayan veriyi kalıcı olarak atlamak olurdu.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from migrations.idempotent import tablo_var

revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if tablo_var("sync_state"):
        return  # create_all zaten yaratmış olabilir (migration'sız kurulum)
    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_kind"),
    )


def downgrade() -> None:
    if tablo_var("sync_state"):
        op.drop_table("sync_state")
