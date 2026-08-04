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
from app.adapters.http_retry import get_with_backoff


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
    # CI/kalite botları MR'lara `system: false` yorum bırakır. Bunlar review
    # sayılırsa review_latency olduğundan İYİ görünür — bot yorumu insan
    # incelemesi değildir. Kullanıcı adı bu parçaları içeren hesaplar elenir.
    BOT_ISARETLERI = ("bot", "ci-", "-ci", "sonar", "danger", "renovate", "dependabot")

    def __init__(self, base_url: str, token_env: str, projects: list[str],
                 repos: list[dict] | None = None, detail_limit: int = 150,
                 max_notes_pages: int = 3, bot_users: list[str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = os.environ.get(token_env, "")
        self.token_env = token_env
        self.projects = projects  # eski biçim: düz "grup/proje" listesi
        self.repos = repos or []  # yeni biçim: [{name, slug, team}]
        self.detail_limit = max(0, detail_limit)
        self.max_notes_pages = max(1, max_notes_pages)
        self.bot_users = {b.strip().lower() for b in (bot_users or []) if b and b.strip()}
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
               ad: str = "", max_pages: int | None = None) -> list[dict]:
        items: list[dict] = []
        page = 1
        while max_pages is None or page <= max_pages:
            resp = get_with_backoff(client, url, {**params, "per_page": 100, "page": page})
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
                ham = self._paged(client, f"/projects/{pid}/repository/commits", params, ad)
                # Dosya listesi commit LİSTESİ ucunda gelmez, ayrı istek ister.
                # None bırakmak üç özelliği sessizce öldürüyordu: rework metriği
                # kalıcı "veri yetersiz", hotspot kuralı hiç tetiklenmiyor,
                # mesaj-kod uyum analizi her commit için "kontrol edilemedi".
                # Oran sınırını korumak için yalnız en yeni detail_limit commit
                # zenginleştirilir (GitHub adaptöründeki desenin aynısı).
                detayli = 0
                for c in ham:
                    stats = c.get("stats") or {}
                    sha = c.get("id", "")
                    dosyalar = None
                    if detayli < self.detail_limit and sha:
                        dosyalar = self._commit_dosyalari(client, pid, sha)
                        if dosyalar is not None:
                            detayli += 1
                    out.append(
                        NormalizedCommit(
                            repo_name=ad,
                            sha=sha,
                            author_key=c.get("author_email"),
                            author_name=c.get("author_name"),
                            committed_at=_dt(c.get("committed_date")),
                            message=c.get("title"),
                            changed_files=dosyalar,
                            additions=stats.get("additions"),
                            deletions=stats.get("deletions"),
                        )
                    )
                if len(ham) > self.detail_limit:
                    self._uyar(
                        f"Proje '{ad}': {len(ham)} commit'in ilk {self.detail_limit} tanesi "
                        "için dosya listesi çekildi (oran sınırı). Rework metriği bu "
                        "örneklem üzerinden hesaplanır, tamlık oranı buna göre düşer."
                    )
        return out

    def _commit_dosyalari(self, client: httpx.Client, pid: str, sha: str) -> list[str] | None:
        """Commit'in değiştirdiği dosya yolları. Hata olursa None (o commit
        zenginleşmez, koşu sürer)."""
        try:
            resp = client.get(f"/projects/{pid}/repository/commits/{sha}/diff")
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        yollar = [
            (f.get("new_path") or f.get("old_path"))
            for f in (resp.json() or [])
            if f.get("new_path") or f.get("old_path")
        ]
        return yollar or None

    def _bot_mu(self, kullanici: str | None) -> bool:
        ad = (kullanici or "").lower()
        if not ad:
            return False
        if ad in self.bot_users:
            return True
        return any(isaret in ad for isaret in self.BOT_ISARETLERI)

    def _onaylar(self, client, pid, iid, ad, author) -> list[NormalizedReview]:
        """MR onayları — GERÇEK review sinyali. Onay verisi yoksa boş liste."""
        if iid is None:
            return []
        try:
            resp = client.get(f"/projects/{pid}/merge_requests/{iid}/approvals")
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            # 404 = onay özelliği kapalı/erişilemez; bu bir hata değil, yorum
            # yoluna düşülür. Uyarı üretmek sağlam projeyi bozukmuş gibi gösterirdi.
            return []
        data = resp.json() or {}
        out: list[NormalizedReview] = []
        for a in data.get("approved_by") or []:
            kullanici = ((a.get("user") or {}).get("username")) or a.get("username")
            if not kullanici or kullanici == author.get("username") or self._bot_mu(kullanici):
                continue
            # Onay zamanı bu uçta yoktur; MR'ın onaylanma damgası varsa kullanılır.
            ts = _dt(data.get("updated_at") or data.get("created_at"))
            if ts:
                out.append(NormalizedReview(reviewer_key=kullanici, reviewed_at=ts))
        out.sort(key=lambda r: r.reviewed_at)
        return out

    def _yorum_reviewlari(self, client, pid, iid, ad, author) -> list[NormalizedReview]:
        """FALLBACK: onay verisi yoksa insan yorumları zayıf review sinyalidir.

        Sayfa sayısı sınırlı: aranan İLK review'dır, tüm tartışma değil —
        yüzlerce MR'lı projede tüm notları çekmek gereksiz ağır."""
        if iid is None:
            return []
        notes = self._paged(
            client, f"/projects/{pid}/merge_requests/{iid}/notes",
            {"sort": "asc"}, ad, max_pages=self.max_notes_pages,
        )
        out: list[NormalizedReview] = []
        for note in notes:
            if note.get("system"):
                continue
            kullanici = (note.get("author") or {}).get("username")
            if not kullanici or kullanici == author.get("username") or self._bot_mu(kullanici):
                continue
            ts = _dt(note.get("created_at"))
            if ts:
                out.append(NormalizedReview(reviewer_key=kullanici, reviewed_at=ts))
        out.sort(key=lambda r: r.reviewed_at)
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
                    iid = mr.get("iid")
                    # Review sinyali ÖNCE gerçek onay verisinden alınır. Eskiden
                    # yalnız "ilk system olmayan yorum" review sayılıyordu; CI ve
                    # kalite botları da yorum bıraktığı için review_latency
                    # olduğundan iyi görünüyor ve "review yapıldı" sinyali sahte
                    # oluyordu. Yorum yolu artık yalnızca FALLBACK.
                    reviews = self._onaylar(client, pid, iid, ad, author)
                    layer = "approval"
                    if not reviews:
                        reviews = self._yorum_reviewlari(client, pid, iid, ad, author)
                        layer = "comment"
                    first_review_at = reviews[0].reviewed_at if reviews else None
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
                            review_source=layer if reviews else None,
                        )
                    )
        return out
