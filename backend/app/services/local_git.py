"""Yerel git deposundan commit okuma — "Projelerim" için yerel klasör kaynağı.

GitHub yolundan farkı: ağ yok, token yok, kod makineden ÇIKMAZ. Gizli ya da
henüz bitmemiş repolar için doğru kaynak budur — repoyu bir PAT'e açmak yerine
zaten diskte duran klonu okur.

GÜVENLİK: burada kullanıcı sunucuda bir YOL veriyor. Doğrulama olmadan bu,
panele girebilen herkesin sunucudaki herhangi bir dizinin (başka bir çalışanın
klasörü, /etc, C:\\Users\\...) commit mesajlarını okuyabilmesi demekti.
resolve_local_repo yalnızca config'teki `projects.local_roots` altındaki gerçek
git depolarına izin verir; liste boşsa özellik tamamen kapalıdır.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from app.adapters.git_log import FIELD_SEP, RECORD_SEP
from app.core.config import Config

# git log formatı: %B (tam gövde) yerine %s (konu) — commit_review konu satırıyla
# çalışıyor ve gövde ayraçları bozabilir.
LOG_FORMAT = f"{RECORD_SEP}%H{FIELD_SEP}%ae{FIELD_SEP}%an{FIELD_SEP}%aI{FIELD_SEP}%s"


class LocalRepoError(Exception):
    """Yol izinli köklerin dışında, mevcut değil ya da git deposu değil."""


def _norm(p: Path) -> str:
    """Karşılaştırma için normalize eder. Windows'ta yol karşılaştırması
    büyük/küçük harfe duyarsızdır; normcase olmadan 'c:\\users' ile
    'C:\\Users' farklı görünür ve izinli kök yanlışlıkla reddedilir."""
    return os.path.normcase(str(p))


def allowed_roots(cfg: Config) -> list[Path]:
    roots = []
    for raw in cfg.projects.local_roots:
        if not str(raw).strip():
            continue
        try:
            roots.append(Path(raw).expanduser().resolve(strict=False))
        except (OSError, RuntimeError):
            continue  # bozuk kök tüm özelliği düşürmesin
    return roots


def resolve_local_repo(raw_path: str, cfg: Config) -> Path:
    """Kullanıcının verdiği yolu doğrulanmış mutlak yola çevirir.

    Sırayla: boş mu → izinli kök tanımlı mı → yol çözülüyor mu → izinli kökün
    ALTINDA mı → var mı → git deposu mu. Hata mesajları kullanıcıya gösterilir,
    o yüzden sunucu dizin yapısını ifşa etmeyecek kadar genel tutuldu.
    """
    if not (raw_path or "").strip():
        raise LocalRepoError("Klasör yolu boş.")

    roots = allowed_roots(cfg)
    if not roots:
        raise LocalRepoError(
            "Yerel klasör kaynağı kapalı — yönetici izinli kök klasör tanımlamalı "
            "(config: projects.local_roots)."
        )

    try:
        # resolve(): '..' ve sembolik bağları çözer. Bu şart — aksi halde
        # '<izinli-kök>/../../gizli' ile kökün dışına çıkılabilirdi.
        path = Path(raw_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as e:
        raise LocalRepoError("Yol çözümlenemedi.") from e

    target = _norm(path)
    if not any(target == _norm(r) or target.startswith(_norm(r) + os.sep) for r in roots):
        raise LocalRepoError(
            "Bu klasör izinli kökler dışında — yöneticinin izin verdiği bir dizin altında olmalı."
        )
    if not path.is_dir():
        raise LocalRepoError("Klasör bulunamadı.")
    if not (path / ".git").exists():
        raise LocalRepoError("Burası bir git deposu değil (.git yok).")
    return path


def fetch_local_commits(path: Path, max_commits: int = 100) -> list[dict]:
    """Yerel depodan son commitleri okur (en yeni önce).

    Dönüş şekli services.github.fetch_commits ile AYNI — çağıran (_sync) iki
    kaynağı ayırt etmek zorunda kalmasın.
    """
    args = [
        "git", "-C", str(path), "log", f"--max-count={max(1, int(max_commits))}",
        f"--pretty=format:{LOG_FORMAT}",
    ]
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as e:
        raise LocalRepoError(f"git komutu çalıştırılamadı ({type(e).__name__}).") from e
    if proc.returncode != 0:
        # Boş depo (henüz commit yok) da buraya düşer — sebep kullanıcıya gösterilir.
        detay = (proc.stderr or "").strip().splitlines()
        raise LocalRepoError("git log başarısız: " + (detay[-1] if detay else "bilinmeyen hata"))

    out: list[dict] = []
    for record in (proc.stdout or "").split(RECORD_SEP):
        record = record.strip()
        if not record:
            continue
        parts = record.split(FIELD_SEP)
        if len(parts) < 5:
            continue
        sha, email, name, date_iso, subject = parts[:5]
        try:
            committed_at = datetime.fromisoformat(date_iso)
        except ValueError:
            committed_at = None  # bozuk tarih kaydı düşürmesin
        out.append({
            "sha": sha,
            "author_name": name or None,
            "author_email": email or None,
            "message": subject or None,
            "committed_at": committed_at,
        })
    return out
