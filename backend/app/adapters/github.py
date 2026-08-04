"""GitHub API GitProvider'ı — takım metrikleri için commit + Pull Request.

NEDEN VAR: `git_log` adaptörü yerel klasörü okur ve orada PR diye bir şey
yoktur; pr_review_time / review_latency / change_failure_rate kalıcı olarak
"veri yetersiz" kalır. Repo GitHub'daysa bu veri MEVCUTTUR, yalnız çekilmesi
gerekir. Bu adaptör o boşluğu kapatır.

Kişisel "Projelerim" modülündeki app/services/github.py ile KARIŞTIRILMAMALI:
o, kullanıcının kendi reposunu takım metriklerinden İZOLE çeker. Bu dosya ise
takım seviyesindeki normalize hattına (ingest → metrik motoru) besleme yapar.

Tasarım kısıtları:
- Hiçbir hata senkronu düşürmez; sorunlar `warnings` listesinde toplanır ve
  ingest onları senkron sonucuna taşır (kullanıcı sebebini görür).
- Token config'e YAZILMAZ, ortam değişkeninden okunur (varsayılan GITHUB_TOKEN).
  Public repo tokensiz de çalışır ama oran sınırı 60/saat'e düşer.
- Commit listesi endpoint'i dosya listesi DÖNMEZ. `changed_files` rework
  metriği ve hotspot kuralı için gereklidir, bu yüzden en yeni N commit için
  ayrı detay isteği atılır (N = detail_limit). Sınırın ötesi None kalır:
  metrik "uydurmak" yerine tamlık oranını düşürür.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import httpx

from app.adapters.base import NormalizedCommit, NormalizedPR, NormalizedReview
from app.adapters.http_retry import get_with_backoff, oran_siniri_mi

GITHUB_API = "https://api.github.com"
_SLUG_RE = re.compile(r"(?:github\.com[/:])?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", re.IGNORECASE)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None  # bozuk tarih → None; metrik motoru bu kaydı düşer


def parse_slug(value: str) -> tuple[str, str] | None:
    """'owner/repo', 'https://github.com/owner/repo(.git)' → (owner, repo)."""
    m = _SLUG_RE.search((value or "").strip())
    return (m.group(1), m.group(2)) if m else None


class GitHubProvider:
    def __init__(
        self,
        repos: list[dict],
        token_env: str = "GITHUB_TOKEN",
        detail_limit: int = 150,
        max_prs: int = 200,
    ):
        """repos: [{name, slug|url, team}] — config'ten gelir.

        `name` normalize kayıtlarda kullanılan repo adıdır; repo→takım eşlemesi
        (pipeline) bu adla yapılır. `slug` GitHub'daki owner/repo yoludur.
        """
        self.repos = repos
        self.token = os.environ.get(token_env, "")
        self.token_env = token_env
        self.detail_limit = max(0, detail_limit)
        self.max_prs = max(0, max_prs)
        self.warnings: list[str] = []

    # --- altyapı --------------------------------------------------------------

    def _client(self) -> httpx.Client:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return httpx.Client(base_url=GITHUB_API, headers=headers, timeout=30.0)

    def _uyar(self, mesaj: str) -> None:
        """Aynı uyarı iki kez görünmesin: fetch_commits ve fetch_pull_requests
        aynı repo listesini çözer, ikisi de aynı sorunu bulur."""
        if mesaj not in self.warnings:
            self.warnings.append(mesaj)

    def _hedefler(self) -> list[tuple[str, str, str]]:
        """[(repo_adi, owner, repo)] — eşlenemeyenler uyarıya düşer."""
        out = []
        for r in self.repos:
            ad = r.get("name") or "(isimsiz repo)"
            ham = r.get("slug") or r.get("url") or r.get("github") or r.get("name") or ""
            parsed = parse_slug(str(ham))
            if not parsed:
                self._uyar(
                    f"Repo '{ad}': GitHub yolu çözülemedi ('{ham}'). "
                    "Beklenen biçim: owner/repo ya da https://github.com/owner/repo"
                )
                continue
            out.append((ad, parsed[0], parsed[1]))
        if not self.repos:
            self._uyar("Git repo listesi boş — çekilecek commit yok.")
        return out

    def _hata_uyarisi(self, ad: str, resp: httpx.Response) -> str:
        if resp.status_code == 404:
            return (f"Repo '{ad}': bulunamadı ya da özel (private). Özel repo için "
                    f"{self.token_env} tanımlı ve 'repo' yetkili olmalı.")
        if resp.status_code == 401:
            return f"Repo '{ad}': {self.token_env} geçersiz."
        if oran_siniri_mi(resp):
            # Yeniden denemedik: GitHub oran sınırı bir saate kadar sürebilir,
            # senkronu o kadar bekletmek doğru değil. Kullanıcı sebebi görsün.
            return (f"Repo '{ad}': GitHub oran sınırı aşıldı. "
                    f"{self.token_env} tanımlayın (60/saat → 5000/saat).")
        if resp.status_code == 403:
            return f"Repo '{ad}': erişim reddedildi (403)."
        return f"Repo '{ad}': GitHub API hatası ({resp.status_code})."

    def _paged(self, client: httpx.Client, url: str, params: dict, limit: int) -> list[dict]:
        """Link başlığını izleyerek sayfalar; limit'e ulaşınca durur.

        429/5xx'te geri çekilip yeniden dener (bkz. http_retry). GitHub'ın
        "403 + oran sınırı" durumu YENİDEN DENENMEZ — sıfırlanması bir saati
        bulabilir; yanıt olduğu gibi döner ve _hata_uyarisi net sebep yazar."""
        items: list[dict] = []
        page = 1
        while len(items) < limit:
            resp = get_with_backoff(
                client, url, {**params, "per_page": 100, "page": page}
            )
            if resp.status_code != 200:
                raise httpx.HTTPStatusError("api", request=resp.request, response=resp)
            batch = resp.json()
            if not batch:
                break
            items.extend(batch)
            if 'rel="next"' not in resp.headers.get("link", ""):
                break
            page += 1
        return items[:limit]

    # --- GitProvider arayüzü ---------------------------------------------------

    def fetch_commits(self, since: datetime | None = None) -> list[NormalizedCommit]:
        out: list[NormalizedCommit] = []
        self.warnings = []
        hedefler = self._hedefler()
        if not hedefler:
            return out

        params: dict = {}
        if since:
            params["since"] = since.astimezone(timezone.utc).isoformat()

        with self._client() as client:
            for ad, owner, repo in hedefler:
                try:
                    ham = self._paged(client, f"/repos/{owner}/{repo}/commits", params, 1000)
                except httpx.HTTPStatusError as e:
                    self._uyar(self._hata_uyarisi(ad, e.response))
                    continue
                except httpx.HTTPError as e:
                    self._uyar(f"Repo '{ad}': ağ hatası ({e}).")
                    continue

                # Dosya listesi yalnız detay isteğinde gelir; en yeniden başlayarak
                # sınırlı sayıda commit zenginleştirilir (oran sınırını korumak için).
                detayli = 0
                for item in ham:
                    c = item.get("commit") or {}
                    author = c.get("author") or {}
                    sha = item.get("sha", "")
                    degisen = eklenen = silinen = None
                    if detayli < self.detail_limit and sha:
                        detay = self._commit_detay(client, owner, repo, sha)
                        if detay is not None:
                            degisen, eklenen, silinen = detay
                            detayli += 1
                    out.append(NormalizedCommit(
                        repo_name=ad,
                        sha=sha,
                        # GitHub kimliği: e-posta kimlik eşlemesinde kullanılır;
                        # yoksa hesap adına düşülür.
                        author_key=author.get("email") or ((item.get("author") or {}).get("login")),
                        author_name=author.get("name"),
                        committed_at=_dt(author.get("date")),
                        message=c.get("message"),
                        changed_files=degisen,
                        additions=eklenen,
                        deletions=silinen,
                    ))
                if len(ham) > self.detail_limit:
                    self._uyar(
                        f"Repo '{ad}': {len(ham)} commit'in ilk {self.detail_limit} tanesi için "
                        "dosya listesi çekildi (oran sınırı). Rework metriği bu örneklem "
                        "üzerinden hesaplanır, tamlık oranı buna göre düşer."
                    )
        return out

    def _commit_detay(self, client: httpx.Client, owner: str, repo: str, sha: str):
        """(changed_files, additions, deletions) — hata olursa None (sessiz düşmez,
        yalnız o commit zenginleşmez)."""
        try:
            resp = client.get(f"/repos/{owner}/{repo}/commits/{sha}")
            if resp.status_code != 200:
                return None
            data = resp.json()
        except httpx.HTTPError:
            return None
        stats = data.get("stats") or {}
        dosyalar = [f.get("filename") for f in (data.get("files") or []) if f.get("filename")]
        return dosyalar or None, stats.get("additions"), stats.get("deletions")

    def fetch_pull_requests(self, since: datetime | None = None) -> list[NormalizedPR]:
        """PR'lar + review'lar. Asıl kazanç burada: pr_review_time, review_latency,
        deployment_frequency (merge edilmiş PR) ve change_failure_rate."""
        out: list[NormalizedPR] = []
        hedefler = self._hedefler()
        if not hedefler:
            return out

        # GitHub pulls ucunda 'since' YOKTUR; güncellenmeye göre sıralayıp
        # pencerenin dışına çıkınca duruyoruz.
        params = {"state": "all", "sort": "updated", "direction": "desc"}

        with self._client() as client:
            for ad, owner, repo in hedefler:
                try:
                    ham = self._paged(client, f"/repos/{owner}/{repo}/pulls", params, self.max_prs)
                except httpx.HTTPStatusError as e:
                    self._uyar(self._hata_uyarisi(ad, e.response))
                    continue
                except httpx.HTTPError as e:
                    self._uyar(f"Repo '{ad}': PR çekilemedi, ağ hatası ({e}).")
                    continue

                for pr in ham:
                    guncelleme = _dt(pr.get("updated_at"))
                    if since and guncelleme and guncelleme < since:
                        break  # sıralı liste: bundan sonrası daha da eski
                    yazar = (pr.get("user") or {}).get("login")
                    numara = pr.get("number")
                    reviews, ilk_review = self._reviewlar(client, owner, repo, numara, yazar)
                    out.append(NormalizedPR(
                        repo_name=ad,
                        external_id=str(numara),
                        author_key=yazar,
                        author_name=yazar,
                        title=pr.get("title"),
                        opened_at=_dt(pr.get("created_at")),
                        first_review_at=ilk_review,
                        merged_at=_dt(pr.get("merged_at")),
                        closed_at=_dt(pr.get("closed_at")),
                        reviews=reviews,
                    ))
        return out

    def _reviewlar(self, client, owner, repo, numara, yazar):
        """PR review'ları. Yazarın KENDİ review'ı sayılmaz (kendi kendini
        onaylamak review latency'sini yanlış iyileştirirdi)."""
        if numara is None:
            return [], None
        try:
            resp = client.get(f"/repos/{owner}/{repo}/pulls/{numara}/reviews",
                              params={"per_page": 100})
            if resp.status_code != 200:
                return [], None
            ham = resp.json()
        except httpx.HTTPError:
            return [], None

        reviews: list[NormalizedReview] = []
        for r in ham:
            login = (r.get("user") or {}).get("login")
            if login and yazar and login == yazar:
                continue
            ts = _dt(r.get("submitted_at"))
            if ts:
                reviews.append(NormalizedReview(reviewer_key=login, reviewed_at=ts))
        reviews.sort(key=lambda r: r.reviewed_at)
        return reviews, (reviews[0].reviewed_at if reviews else None)
