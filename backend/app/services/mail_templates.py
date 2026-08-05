"""Parola sıfırlama e-posta şablonları (HTML).

Sade ve tablosuz tutuldu: mail istemcileri CSS'in çoğunu (flex/grid, harici
stil, media query) yok sayar; bu yüzden düzen inline stil + tek sütundur ve
dar ekranda kendiliğinden akar. Karanlık tema varsayımı yapılmaz — arka plan
ve metin renkleri açıkça verilir, aksi hâlde koyu temalı istemcilerde siyah
üstüne siyah yazı çıkar.

Kod, kopyalanabilsin diye seçilebilir düz metindir (görsel DEĞİL) ve harf
aralığı açılarak okunaklı kılınmıştır.
"""
from __future__ import annotations

from html import escape

_WRAP_BASLIK = (
    'style="margin:0;padding:24px;background:#f4f5f7;'
    'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"'
)
_KART = (
    'style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:12px;'
    'padding:32px 28px;color:#1a1d21;"'
)
_MARKA = (
    'style="margin:0 0 24px;font-size:18px;font-weight:600;color:#1a1d21;"'
)
_METIN = 'style="margin:0 0 16px;font-size:15px;line-height:1.55;color:#3c4149;"'
_KUCUK = 'style="margin:24px 0 0;font-size:13px;line-height:1.5;color:#6b7280;"'


def reset_code_email(code: str, dakika: int) -> str:
    """6 haneli kodu içeren mail. `code` zaten üretilmiş bir rakam dizisidir."""
    return f"""\
<!doctype html>
<html lang="tr">
<body {_WRAP_BASLIK}>
  <div {_KART}>
    <p {_MARKA}>Vantage</p>
    <p {_METIN}>Parola sıfırlama isteğiniz için doğrulama kodunuz:</p>
    <p style="margin:0 0 20px;padding:16px;background:#f4f5f7;border-radius:10px;
              text-align:center;font-size:34px;font-weight:700;letter-spacing:10px;
              color:#1a1d21;font-family:Consolas,Menlo,monospace;">{escape(code)}</p>
    <p {_METIN}>Bu kod <strong>{dakika} dakika</strong> geçerlidir.</p>
    <p {_KUCUK}>
      Bu isteği siz yapmadıysanız dikkate almayın — parolanız değişmez.
      Kodu kimseyle paylaşmayın.
    </p>
  </div>
</body>
</html>"""


def password_changed_email() -> str:
    """Parola değiştikten sonra gönderilen bilgilendirme."""
    return f"""\
<!doctype html>
<html lang="tr">
<body {_WRAP_BASLIK}>
  <div {_KART}>
    <p {_MARKA}>Vantage</p>
    <p {_METIN}>Hesabınızın parolası az önce değiştirildi.</p>
    <p {_METIN}>
      Güvenlik gereği açık olan diğer tüm oturumlarınız kapatıldı; yeni
      parolanızla tekrar giriş yapmanız gerekir.
    </p>
    <p {_KUCUK}>
      Bu değişikliği siz yapmadıysanız <strong>hemen yöneticinize haber
      verin</strong> — hesabınıza başkası erişmiş olabilir.
    </p>
  </div>
</body>
</html>"""
