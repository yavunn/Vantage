"""Oran sınırına (429) saygılı GET yardımcısı — tüm adaptörler için ortak.

NEDEN VAR: hiçbir adaptörde geri çekilme yoktu. Gerçek hacimde bunun sonucu
SESSİZ VERİ KAYBI oluyordu — örneğin Trello'da kart hareketleri isteği 429
alınca `if resp.status_code == 200` koşulu sağlanmıyor, o kartın TÜM geçişleri
boş kalıyor, cycle time düşüyor ve kullanıcı sebebini hiçbir yerde görmüyordu.

POLİTİKA:
- 429 ve geçici sunucu hataları (502/503/504) yeniden denenir. Bekleme süresi
  Retry-After başlığından okunur; yoksa üstel (1s, 2s, 4s). Üst sınır var:
  saatlerce beklemek senkronu kilitler.
- GitHub'ın "403 + oran sınırı" durumu YENİDEN DENENMEZ: sıfırlanması bir saati
  bulabilir. Yanıt olduğu gibi döner, çağıran net bir uyarı üretir.
"""
from __future__ import annotations

import time

import httpx

RETRY_STATUSES = (429, 502, 503, 504)
MAX_RETRIES = 3
MAX_SLEEP_SECONDS = 30.0


def _retry_after(resp: httpx.Response, deneme: int) -> float:
    ham = resp.headers.get("retry-after")
    if ham:
        try:
            return min(float(ham), MAX_SLEEP_SECONDS)
        except ValueError:
            pass
    return min(2.0 ** deneme, MAX_SLEEP_SECONDS)


def get_with_backoff(
    client: httpx.Client,
    url: str,
    params: dict | None = None,
    *,
    max_retries: int = MAX_RETRIES,
    sleep=time.sleep,
) -> httpx.Response:
    """Oran sınırına takılırsa bekleyip yeniden dener; son yanıtı döner.

    Yanıt YİNE başarısızsa istisna fırlatmaz — çağıran durum koduna bakıp
    kullanıcıya net sebep yazar (sessiz atlama yerine)."""
    resp = client.get(url, params=params)
    deneme = 0
    while resp.status_code in RETRY_STATUSES and deneme < max_retries:
        sleep(_retry_after(resp, deneme))
        deneme += 1
        resp = client.get(url, params=params)
    return resp


def oran_siniri_mi(resp: httpx.Response) -> bool:
    """Yanıt oran sınırı yüzünden mi başarısız? (GitHub 403'ü de kapsar.)"""
    if resp.status_code == 429:
        return True
    if resp.status_code == 403:
        if resp.headers.get("x-ratelimit-remaining") == "0":
            return True
        try:
            return "rate limit" in resp.text.lower()
        except Exception:  # noqa: BLE001 — gövde okunamıyorsa sınır bilgisi yok
            return False
    return False
