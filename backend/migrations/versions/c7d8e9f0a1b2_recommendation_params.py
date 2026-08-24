"""Öneri metni: şablon + parametre (çeviri okuma anında yapılabilsin)

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-08-24

Kural motorunun önerileri veritabanına HAZIR CÜMLE olarak yazılıyordu; sonuç,
arayüzü İngilizceye alan kullanıcının "Süreç önerileri" bloğunda Türkçe metin
görmesiydi. Sayı içeren cümleler sabit sözlükle çevrilemez ("PR'lar ortalama
4.2 gün bekliyor").

Artık `message` yer tutuculu şablon, sayısal değerler bu kolonda: çeviri okuma
anında yapılıyor (bkz. app/core/texts_en.py). Öneriler her senkronda baştan
üretildiği için eski satırlar kendiliğinden yenilenir; yenilenene kadar
params NULL kalır ve metin olduğu gibi gösterilir.
"""
from __future__ import annotations

import sqlalchemy as sa

from migrations.idempotent import kolon_dusur, kolon_ekle

revision = "c7d8e9f0a1b2"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    kolon_ekle("recommendations", sa.Column("params", sa.JSON(), nullable=True))


def downgrade() -> None:
    kolon_dusur("recommendations", "params")
