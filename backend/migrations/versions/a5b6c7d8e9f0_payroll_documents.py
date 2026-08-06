"""payroll_documents (bordro / özlük evrakı kayıtları)

Revision ID: a5b6c7d8e9f0
Revises: e3f4a5b6c7d8
Create Date: 2026-08-06

DOSYA İÇERİĞİ BURADA DEĞİL: bu tablo yalnız meta + diskteki dosya adını tutar
(bkz. app/services/hr_documents.py). Kolon adları ve tipleri modeldeki
PayrollDocument ile birebir aynı olmalı — tests/test_migrations.py alembic
şeması ile modelleri karşılaştırıp ayrışmayı yakalıyor.

IDEMPOTENT: şema iki yoldan kurulabiliyor (alembic ve açılıştaki create_all);
tablo zaten varsa atlanır (bkz. migrations/idempotent.py).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotent import indeks_ekle, tablo_var

revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = (
    # Çalışan kendi belgelerini listeler; İK kişi bazında filtreler.
    ("ix_payroll_documents_user_id", ["user_id"]),
    # Dönem özeti (bordro kapatma) ve tür kırılımı bu iki kolondan sorgulanır.
    ("ix_payroll_documents_period", ["period"]),
    ("ix_payroll_documents_doc_type", ["doc_type"]),
)


def upgrade() -> None:
    if not tablo_var("payroll_documents"):
        op.create_table(
            "payroll_documents",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("uploaded_by", sa.Integer(), nullable=True),
            sa.Column("doc_type", sa.String(length=40), nullable=False),
            sa.Column("period", sa.String(length=7), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("leave_id", sa.Integer(), nullable=True),
            sa.Column("original_name", sa.String(length=255), nullable=False),
            sa.Column("stored_name", sa.String(length=80), nullable=False),
            sa.Column("content_type", sa.String(length=100), nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False,
                      server_default="pending"),
            sa.Column("reviewed_by", sa.Integer(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["leave_id"], ["leaves.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    for ad, kolonlar in _INDEXES:
        indeks_ekle(ad, "payroll_documents", kolonlar)


def downgrade() -> None:
    if tablo_var("payroll_documents"):
        for ad, _ in _INDEXES:
            op.drop_index(ad, table_name="payroll_documents")
        op.drop_table("payroll_documents")
