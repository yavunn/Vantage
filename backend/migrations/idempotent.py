"""Migration yardımcıları — var olanı yeniden yaratmaya çalışmaz.

NEDEN GEREKLİ: bu projede şema İKİ yoldan kurulabiliyor — alembic ve açılışta
çalışan `Base.metadata.create_all` + `ensure_schema_patches` (migration'sız
taşınabilir demo kurulumu için). İkisi birlikte çalıştığında bir kolon
migration'dan ÖNCE eklenmiş olabilir ve düz `add_column` "column already
exists" ile patlar. Aynı gerekçe daha önce `a1b2c3d4e5f6` migration'ında da
uygulanmıştı (bkz. PROJE_DENETIM madde 2).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def _inspector():
    return sa.inspect(op.get_bind())


def kolon_var(tablo: str, kolon: str) -> bool:
    insp = _inspector()
    if not insp.has_table(tablo):
        return False
    return kolon in {c["name"] for c in insp.get_columns(tablo)}


def kolon_ekle(tablo: str, kolon: sa.Column) -> None:
    if kolon_var(tablo, kolon.name):
        return
    with op.batch_alter_table(tablo) as batch:
        batch.add_column(kolon)


def kolon_dusur(tablo: str, kolon: str) -> None:
    if not kolon_var(tablo, kolon):
        return
    with op.batch_alter_table(tablo) as batch:
        batch.drop_column(kolon)


def tablo_var(tablo: str) -> bool:
    return _inspector().has_table(tablo)


def indeks_var(tablo: str, ad: str) -> bool:
    insp = _inspector()
    if not insp.has_table(tablo):
        return False
    return ad in {i["name"] for i in insp.get_indexes(tablo)}


def indeks_ekle(ad: str, tablo: str, kolonlar: list[str]) -> None:
    if indeks_var(tablo, ad):
        return
    op.create_index(ad, tablo, kolonlar)


def indeks_dusur(ad: str, tablo: str) -> None:
    if indeks_var(tablo, ad):
        op.drop_index(ad, table_name=tablo)
