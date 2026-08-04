"""Task arşiv bayrağı (Trello 'closed')

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-04

Trello kart ucu varsayılan çağrıda YALNIZ açık kartları döndürür. Gerçek board
üzerinde ölçüldü: varsayılan 19 kart, `filter=all` 21 kart — 2 arşivli kart hiç
çekilmiyordu. Arşivlenen kart çoğu zaman BİTMİŞ iştir; yani takım kartlarını ne
kadar düzenli arşivlerse cycle time ve teslim sinyali o kadar çok kayboluyordu.

Artık arşivliler de çekiliyor ve bu kolonla işaretleniyor: WIP'e sayılmazlar
(akışta değiller) ama tamamlanmış işin izi kaybolmuyor.
"""
from __future__ import annotations

import sqlalchemy as sa

from migrations.idempotent import kolon_dusur, kolon_ekle

revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    kolon_ekle("tasks", sa.Column(
        "archived", sa.Boolean(), nullable=False, server_default=sa.false()
    ))


def downgrade() -> None:
    kolon_dusur("tasks", "archived")
