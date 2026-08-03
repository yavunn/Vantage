"""GitLab API GitProvider'ı (şirket GitLab'ı — on-prem).

Commit + Merge Request (PR) verisini çeker. Token config'e yazılmaz,
ortam değişkeninden okunur. API hatası tüm senkronu düşürmez.

HEDEF LİSTESİ: GitHub sağlayıcısıyla AYNI `repos` girdilerinden okunur
([{name, slug, team}]). Sebep repo→takım eşlemesi: pipeline eşlemeyi repo
ADIYLA yapar (services/pipeline.py:repo_team_map), yani hedefler ayrı bir
`gitlab.projects` listesinde yaşarsa takımsız kalır ve commitleri hiçbir
metriğe giremez — sessiz bir "veri yetersiz". Eski kurulumlar bozulmasın diye
`repos` boşsa `gitlab.projects` listesine düşülür.

SESSİZ BAŞARISIZLIK YOK: okunamayan proje, eksik adres/token ve HTTP hataları
`warnings` listesine düşer; panel ve senkron bunları gösterir.
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx

from app.adapters.base import NormalizedCommit, NormalizedPR, NormalizedReview


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_project_path(value: str) -> str | None:
    """'grup/proje', 'grup/alt/proje', tam URL → GitLab proje yolu.

    GitLab iç içe grupları destekler, o yüzden GitHub'daki gibi iki parçaya
    sabitlenmez: adres kısmı atılır, kalan yol olduğu gibi kullanılır.
    Sayısal proje id'si de geçerli bir hedeftir (GitLab API ikisini de kabul eder).
    """
    v = (value or "").strip()
    if not v:
        return None
    if "://" in v:
        _, _, rest = v.partition("://")
        v = rest.partition("/")[2]  # adres kısmını at, yolu bırak
    v = v.strip("/")
    if v.endswith(".git"):
        v = v[: -len(".git")]
    return v or None


class GitLabProvider:
    def __init__(self, base_url: str, token_env: str, projects: list[str],
                 repos: list[dict] | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = os.environ.get(token_env, "")
        self.token_env = token_env
        self.projects = projects  # eski biçim: düz "grup/proje" listesi
        self.repos = repos or []  # yeni biçim: [{name, slug, team}]
        self.warnings: list[str] = []

    def _uyar(self, mesaj: str) -> None:
        """Aynı uyarı iki kez görünmesin: fetch_commits ve fetch_pull_requests
        aynı listeyi çözer, ikisi de aynı sorunu bulur."""
        if mesaj not in self.warnings:
            self.warnings.append(mesaj)

    def _hedefler(self) -> list[tuple[str, str]]:
        """[(repo_adi, proje_yolu)] — çözülemeyenler uyarıya düşer.

        repo_adi normalize kayıtlara yazılır ve repo→takım eşlemesinin
        anahtarıdır; proje_yolu GitLab API'ye gider."""
        if not self.base_url:
            self._uyar("GitLab adresi (base_url) tanımsız — hiçbir proje okunamaz.")
            return []
        if not self.token:
            self._uyar(
                f"{self.token_env} tanımsız — özel projeler okunamaz "
                "(GitLab çoğu kurulumda anonim erişime kapalıdır)."
            )
        out: list[tuple[str, str]] = []
        if self.repos:
            for r in self.repos:
                ad = r.get("name") or "(isimsiz repo)"
                ham = r.get("slug") or r.get("url") or r.get("name") or ""
                yol = parse_project_path(str(ham))
                if not yol:
                    self._uyar(
                        f"Repo '{ad}': GitLab proje yolu çözülemedi ('{ham}'). "
                        "Beklenen biçim: grup/proje ya da https://gitlab.../grup/proje"
                    )
                    continue
                out.append((ad, yol))
        else:
            for proj in self.projects:
                yol = parse_project_path(str(proj))
                if yol:
                    out.append((yol, yol))
        if not out:
            self._uyar("GitLab proje listesi boş — çekilecek commit yok.")
        return out

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=f"{self.base_url}/api/v4",
            headers={"PRIVATE-TOKEN": self.token},
            timeout=30,
        )

    def _hata_uyarisi(self, ad: str, resp: httpx.Response) -> str:
        if resp.status_code == 404:
            return (f"Proje '{ad}': bulunamadı ya da erişim yok. Yol 'grup/proje' "
                    f"biçiminde mi, {self.token_env} bu projeyi görüyor mu?")
        if resp.status_code == 401:
            return f"Proje '{ad}': {self.token_env} geçersiz ya da süresi dolmuş (401)."
        if resp.status_code == 403:
            return (f"Proje '{ad}': erişim reddedildi (403) — token'ın 'read_api' "
                    "kapsamı ve proje yetkisi olmalı.")
        return f"Proje '{ad}': GitLab API hatası ({resp.status_code})."

    def _paged(self, client: httpx.Client, url: str, params: dict,
               ad: str = "") -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            resp = client.get(url, params={**params, "per_page": 100, "page": page})
            if resp.status_code != 200:
                # Tek proje hatası senkronu durdurmaz ama SESSİZ de kalmaz.
                self._uyar(self._hata_uyarisi(ad or url, resp))
                break
            batch = resp.json()
            if not batch:
                break
            items.extend(batch)
            if resp.headers.get("x-next-page") in (None, ""):
                break
            page += 1
        return items

    def fetch_commits(self, since: datetime | None = None) -> list[NormalizedCommit]:
        out: list[NormalizedCommit] = []
        params: dict = {"with_stats": "true"}
        if since:
            params["since"] = since.isoformat()
        hedefler = self._hedefler()
        if not hedefler:
            return out
        with self._client() as client:
            for ad, proj in hedefler:
                pid = str(proj).replace("/", "%2F")
                for c in self._paged(client, f"/projects/{pid}/repository/commits",
                                     params, ad):
                    stats = c.get("stats") or {}
                    out.append(
                        NormalizedCommit(
                            repo_name=ad,
                            sha=c.get("id", ""),
                            author_key=c.get("author_email"),
                            author_name=c.get("author_name"),
                            committed_at=_dt(c.get("committed_date")),
                            message=c.get("title"),
                            changed_files=None,  # ayrı istek gerekir; opsiyonel bırakıldı
                            additions=stats.get("additions"),
                            deletions=stats.get("deletions"),
                        )
                    )
        return out

    def fetch_pull_requests(self, since: datetime | None = None) -> list[NormalizedPR]:
        out: list[NormalizedPR] = []
        params: dict = {"state": "all"}
        if since:
            params["updated_after"] = since.isoformat()
        hedefler = self._hedefler()
        if not hedefler:
            return out
        with self._client() as client:
            for ad, proj in hedefler:
                pid = str(proj).replace("/", "%2F")
                for mr in self._paged(client, f"/projects/{pid}/merge_requests",
                                      params, ad):
                    author = mr.get("author") or {}
                    # İlk review yaklaşımı: notes API'sinden ilk insan yorumu
                    first_review_at = None
                    reviews: list[NormalizedReview] = []
                    notes = self._paged(
                        client,
                        f"/projects/{pid}/merge_requests/{mr.get('iid')}/notes",
                        {"sort": "asc"},
                        ad,
                    )
                    for note in notes:
                        if note.get("system"):
                            continue
                        note_author = (note.get("author") or {}).get("username")
                        if note_author == author.get("username"):
                            continue  # yazarın kendi yorumu review sayılmaz
                        ts = _dt(note.get("created_at"))
                        if ts:
                            reviews.append(NormalizedReview(reviewer_key=note_author, reviewed_at=ts))
                            if first_review_at is None:
                                first_review_at = ts
                    out.append(
                        NormalizedPR(
                            repo_name=ad,
                            external_id=str(mr.get("iid")),
                            author_key=author.get("username"),
                            author_name=author.get("name"),
                            title=mr.get("title"),
                            opened_at=_dt(mr.get("created_at")),
                            first_review_at=first_review_at,
                            merged_at=_dt(mr.get("merged_at")),
                            closed_at=_dt(mr.get("closed_at")),
                            reviews=reviews,
                        )
                    )
        return out
