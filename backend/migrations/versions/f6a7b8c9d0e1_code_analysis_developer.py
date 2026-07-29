"""code_analyses.developer_id (kişi-bazlı analiz)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-20

Kod analizi git commit YAZARINA atfedilebilsin: admin herkesi tek tek, kullanıcı
kendi kodunu analiz eder. developer_id NULL = atfedilmemiş (repo/takım düzeyi).

SQLite: kolon FK ile birlikte tek ALTER'da eklenemez ("No support for ALTER of
constraints in SQLite dialect") — bu yüzden batch mode. Batch, SQLite'ta
kopyala-taşı yapar, PostgreSQL'de normal ALTER'a düşer. Önceki korumasız hâli
zincirin SQLite'ta hiç koşamaması demekti; migration testi de buna takılıyordu.
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
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "developer_id" in {c["name"] for c in insp.get_columns("code_analyses")}:
        return  # create_all ile zaten gelmiş
    with op.batch_alter_table("code_analyses") as batch:
        batch.add_column(sa.Column("developer_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_code_analyses_developer_id", "developers", ["developer_id"], ["id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "developer_id" not in {c["name"] for c in insp.get_columns("code_analyses")}:
        return
    with op.batch_alter_table("code_analyses") as batch:
        batch.drop_column("developer_id")
