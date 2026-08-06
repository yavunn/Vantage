"""Bordro/özlük evrakı DOSYA katmanı — diske yazma, okuma, silme.

GÜVENLİK KARARLARI (hepsi bilinçli, hepsi test edilir):

1. DOSYA ADINI SUNUCU ÜRETİR. Kullanıcının verdiği ad yalnız `original_name`
   kolonunda gösterim için durur; diskteki ad `uuid4().hex + doğrulanmış uzantı`.
   Böylece "../../config/config.yaml" ya da "CON.pdf" gibi bir ad yol geçişine
   ya da Windows'ta ayrılmış aygıt adına dönüşemez.

2. UZANTI ALLOWLIST'İ. Yasaklama listesi değil izin listesi: yasaklama listesi
   her zaman eksiktir. svg/html bilerek dışarıda — yüklenen dosya aynı origin'den
   servis edildiği için tarayıcıda çalışan bir biçim depolanmış XSS demektir.

3. BOYUT SINIRI AKIŞ SIRASINDA UYGULANIR. `await file.read()` ile tamamını belleğe
   almak, 2 GB'lık bir yüklemede sunucuyu düşürürdü. Parça parça okunur ve sınır
   aşılınca yarım dosya diskten silinip 413 döner.

4. İÇERİK ASLA WEB KÖKÜNE YAZILMAZ. main.py `frontend/dist`'i StaticFiles ile
   servis ediyor; oraya yazılan bir istirahat raporu kimliksiz indirilebilirdi.

5. HASH SAKLANIR. sha256 hem bütünlük kanıtı (dosya sonradan değişti mi) hem de
   aynı belgenin ikinci kez yüklenmesini tespit için.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path

from app.core.config import PROJECT_ROOT, get_config

CHUNK = 1024 * 1024  # 1 MB

# İndirme yanıtında güvenle tekrarlanabilecek içerik tipleri. Listede olmayan
# her şey octet-stream olarak döner: tarayıcı onu render etmeye çalışmasın.
_SAFE_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
    "text/plain",
}


class UploadError(Exception):
    """İnsan-okur doğrulama hatası. API katmanı bunu 4xx'e çevirir."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def storage_root() -> Path:
    """Evrak kökü. Config boşsa PROJECT_ROOT/data/hr-docs.

    Dizin ilk yazmada oluşturulur; salt-okunur bir kurulumda uygulamanın
    AÇILIŞTA çökmemesi için burada mkdir yapılmaz."""
    raw = (get_config().hr_documents.storage_dir or "").strip()
    return Path(raw) if raw else PROJECT_ROOT / "data" / "hr-docs"


def _extension(filename: str) -> str:
    """Uzantıyı küçük harfle, noktasız döner. Uzantı yoksa boş string."""
    ext = Path(filename or "").suffix.lower().lstrip(".")
    # Uzantı da bir girdi: alfanümerik dışına izin verme (ör. "pdf/../sh").
    return ext if re.fullmatch(r"[a-z0-9]{1,10}", ext or "") else ""


def sanitize_filename(name: str) -> str:
    """Görüntülenecek dosya adını zararsızlaştırır (DİSK ADI DEĞİL).

    Yol ayırıcıları ve kontrol karakterleri atılır: bu ad indirme başlığına ve
    arayüze basılıyor; içine satır sonu koyulabilirse HTTP başlığı bölünebilir."""
    base = Path(name or "").name  # dizin bileşenlerini at
    base = re.sub(r"[\r\n\t\x00-\x1f\x7f]", "", base)
    base = base.replace('"', "'").strip()
    return base[:255] or "belge"


def validate_upload_name(filename: str) -> str:
    """Uzantıyı doğrular, izinli değilse UploadError. Doğrulanmış uzantıyı döner."""
    cfg = get_config().hr_documents
    ext = _extension(filename)
    allowed = [e.lower().lstrip(".") for e in cfg.allowed_extensions]
    if not ext:
        raise UploadError("Dosyanın uzantısı okunamadı; uzantılı bir dosya seçin")
    if ext not in allowed:
        raise UploadError(
            f"'{ext}' uzantısı kabul edilmiyor. İzinli türler: {', '.join(allowed)}"
        )
    return ext


async def save_upload(upload, *, user_id: int) -> dict:
    """Yüklenen dosyayı diske yazar; DB'ye yazılacak meta'yı döner.

    Boyut sınırı yazma SIRASINDA uygulanır (bkz. modül başlığı 3). Sınır aşılırsa
    yarım dosya silinir — diskte sahipsiz çöp bırakmaz."""
    cfg = get_config().hr_documents
    ext = validate_upload_name(upload.filename or "")
    limit = max(1, cfg.max_file_mb) * 1024 * 1024

    target_dir = storage_root() / str(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    path = target_dir / stored_name

    digest = hashlib.sha256()
    size = 0
    try:
        with open(path, "wb") as out:
            while True:
                chunk = await upload.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise UploadError(
                        f"Dosya çok büyük (en fazla {cfg.max_file_mb} MB)", status=413
                    )
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    if size == 0:
        path.unlink(missing_ok=True)
        raise UploadError("Boş dosya yüklenemez")

    return {
        "stored_name": stored_name,
        "original_name": sanitize_filename(upload.filename or f"belge.{ext}"),
        "content_type": (upload.content_type or "application/octet-stream")[:100],
        "size_bytes": size,
        "sha256": digest.hexdigest(),
    }


def file_path(user_id: int, stored_name: str) -> Path:
    """Kayıtlı dosyanın yolu.

    `stored_name` DB'den gelir ve sunucu üretmiştir; yine de doğrulanır: bir gün
    başka bir yol bu değeri dışarıdan doldurursa yol geçişi olmasın."""
    if not re.fullmatch(r"[a-f0-9]{32}\.[a-z0-9]{1,10}", stored_name or ""):
        raise UploadError("Geçersiz dosya kaydı", status=400)
    return storage_root() / str(user_id) / stored_name


def delete_file(user_id: int, stored_name: str) -> None:
    """Diskteki dosyayı siler. Dosya yoksa sessiz geçer — DB kaydının silinmesi
    diskteki bir tutarsızlık yüzünden engellenmemeli."""
    try:
        file_path(user_id, stored_name).unlink(missing_ok=True)
    except (UploadError, OSError):
        return


def purge_user_files(user_id: int) -> int:
    """Bir kullanıcının TÜM evrak dosyalarını diskten siler (hesap silinince).

    KVKK gerekçesi: hesap silindiğinde sağlık raporu diskte kalmamalı. Silinen
    dosya sayısını döner (denetim kaydına yazılır)."""
    directory = storage_root() / str(user_id)
    if not directory.is_dir():
        return 0
    count = 0
    for child in directory.iterdir():
        if child.is_file():
            try:
                child.unlink()
                count += 1
            except OSError:
                continue
    try:
        os.rmdir(directory)
    except OSError:
        pass  # boşalmadıysa (eş zamanlı yazma) bırak
    return count


def download_content_type(stored: str | None) -> str:
    """İndirmede kullanılacak içerik tipi. Allowlist dışındaki her şey
    octet-stream: tarayıcı yüklenen dosyayı render etmeye çalışmasın."""
    value = (stored or "").split(";")[0].strip().lower()
    return value if value in _SAFE_CONTENT_TYPES else "application/octet-stream"
