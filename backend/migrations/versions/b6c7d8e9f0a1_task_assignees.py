"""task_assignees (kartın TÜM atananları)

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-08-12

NEDEN: Trello kartı birden çok üyeye atanabilir, adaptör ise yalnız
`idMembers[0]`'ı okuyordu. Kaybedilen şey "eksik alan" değil YANLIŞ bilgiydi:
iki kişilik kartın ikinci kişisi hiçbir yerde görünmüyor, o kişinin işi yok
gibi duruyordu. `tasks.assignee_id` BİRİNCİL atanan olarak KALIR (WIP ve kişi
bazlı metrikler onun üzerine kurulu); bu tablo ek katmandır.

IDEMPOTENT: şema iki yoldan kurulabiliyor (alembic ve açılıştaki create_all);
tablo zaten varsa atlanır (bkz. migrations/idempotent.py).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotent import indeks_ekle, tablo_var

revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not tablo_var("task_assignees"):
        op.create_table(
            "task_assignees",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("developer_id", sa.Integer(), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False,
                      server_default="false"),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.ForeignKeyConstraint(["developer_id"], ["developers.id"]),
            sa.PrimaryKeyConstraint("id"),
            # Aynı kişi bir karta iki kez atanmış görünemez: kaynak listeyi
            # tekrarlarsa tek satır kalır (ingest de tekilleştirir).
            sa.UniqueConstraint("task_id", "developer_id"),
        )
    # "Bu kişinin kartları" ve "bu kartın kişileri" iki yönde de sorgulanıyor
    # (kişi bazlı görev↔commit görünümü + eşleştirmedeki kişi sinyali).
    indeks_ekle("ix_task_assignees_task_id", "task_assignees", ["task_id"])
    indeks_ekle("ix_task_assignees_developer_id", "task_assignees", ["developer_id"])


def downgrade() -> None:
    op.drop_table("task_assignees")
