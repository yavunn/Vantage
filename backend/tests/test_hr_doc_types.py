"""Belge kataloğu ↔ izin senkronu eşlemesinin tutarlılığı.

Katalog serbestçe büyüyebiliyor (yeni belge türleri eklenir); bu test yeni bir
"leave" kategorisi türü eklenip LEAVE_TYPE_FOR_DOC güncellemesi UNUTULURSA
patlar. Unutulsaydı o belge sessizce izin senkronunun dışında kalırdı —
onaylandığında hiçbir İzin kaydı oluşmaz/onaylanmazdı ve kimse fark etmezdi."""
from __future__ import annotations

from app.services.hr_doc_types import DOC_TYPE_MAP, DOC_TYPES, LEAVE_TYPE_FOR_DOC


def test_leave_esleme_tum_leave_kategorisini_kapsiyor():
    leave_keys = {d["key"] for d in DOC_TYPES if d["category"] == "leave"}
    assert set(LEAVE_TYPE_FOR_DOC) == leave_keys


def test_leave_esleme_yalniz_gecerli_leave_type_kullaniyor():
    assert set(LEAVE_TYPE_FOR_DOC.values()) <= {"annual", "sick", "other"}


def test_leave_esleme_disindaki_turler_tarih_gerektirmiyor_ya_da_leave_degil():
    """LEAVE_TYPE_FOR_DOC'ta olmayan "leave" kategorisi türü olmamalı (üstteki
    test zaten bunu zorluyor); burada ayrıca her eşlenen türün gerçekten
    needs_dates=True olduğunu doğruluyoruz — tarihsiz bir belgeden izin
    oluşturulamaz (decide_document tarih kontrolü yapar)."""
    for key in LEAVE_TYPE_FOR_DOC:
        assert DOC_TYPE_MAP[key]["needs_dates"] is True, key
