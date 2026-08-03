"""Task kısa anahtarı (konvansiyon) + bağın kaynağı

Revision ID: d1e2f3a4b5c6
Revises: c8d9e0f1a2b3
Create Date: 2026-08-03

Task↔commit bağı bugüne kadar TAHMİN edilmek zorundaydı: Trello'da
`tasks.external_id` opak bir hash (`6a607d67…`) ve kimse onu commit mesajına
yazmaz. `task_key` kartın board'da görünen numarasını (Trello `idShort`) ya da
Jira anahtarını ("PROJ-123") taşır — geliştirici commit'e `[#42]` yazdığında bağ
tahmin edilmez, kesinleşir.

`matched_by` ise bağın nereden geldiğini veri katmanında ayırır ('semantic' /
'convention'). Ayrılmasaydı arayüz "%73 benzer" ile "geliştirici numarayı
yazmış" arasındaki farkı gösteremez, ikisi aynı güvenle sunulurdu.

Üç kolon da nullable: geçmiş kayıtlarda karşılığı YOKTUR ve uydurulmaz.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table: SQLite ALTER'ı sınırlı; testler ve demo kurulumu
    # SQLite üzerinde koşuyor (bkz. f6a7b8c9d0e1'de aynı gerekçe).
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("task_key", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column("task_url", sa.Text(), nullable=True))
    with op.batch_alter_table("task_commit_links") as batch:
        batch.add_column(sa.Column("matched_by", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("task_commit_links") as batch:
        batch.drop_column("matched_by")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("task_url")
        batch.drop_column("task_key")
