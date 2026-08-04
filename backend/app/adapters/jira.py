"""Jira REST API TaskProvider'ı.

Katman 1'in kalbi: changelog'dan status geçiş zaman damgalarını çıkarır —
kullanıcı tarih girmese bile cycle time hesaplanabilir. Katman 2 alanları
(estimate, due date, story points) VARSA alınır, yoksa None kalır.

GERÇEK KURULUMDA ÇALIŞMASI İÇİN ÜÇ ŞEY GEREKİYORDU (İŞ-10):

1. KİMLİK: Jira CLOUD, e-posta + API token ile BASIC auth ister. Adaptör yalnız
   `Authorization: Bearer` gönderiyordu; bu sadece Server/Data Center kişisel
   erişim token'ında geçerlidir. Yani Cloud'da HER istek 401 alıyordu.
2. UÇ: Cloud'da `GET /rest/api/2/search` kaldırıldı; yerine token tabanlı
   sayfalama kullanan `/rest/api/3/search/jql` geldi.
3. SESSİZLİK: hata durumunda `break` ediliyordu ve sınıfın `warnings` listesi
   HİÇ YOKTU. ingest.py `getattr(tasks, "warnings", [])` ile uyarı topladığı
   için bu adaptörden hiçbir zaman uyarı gelmiyordu: kullanıcı 401 alsa bile
   ekranda yalnız "0 task" görüyordu ve /api/sources/test "ok" diyordu.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime

import httpx

from app.adapters.base import NormalizedTask, NormalizedTeamMember, NormalizedTransition

# Jira issue type → normalize tip
TYPE_MAP = {"bug": "bug", "story": "story", "task": "task"}


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _jql_kacir(deger: str) -> str:
    """JQL değer kaçırma. Proje anahtarı tırnaksız yazıldığında boşluklu ya da
    özel karakterli anahtarlar sorguyu bozuyordu."""
    return '"' + (deger or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


class JiraProvider:
    def __init__(
        self,
        base_url: str,
        token_env: str,
        projects: list[str],
        auth: str = "basic",
        email: str = "",
        email_env: str = "JIRA_EMAIL",
        api_style: str = "auto",
        story_points_field: str = "customfield_10016",
    ):
        self.base_url = base_url.rstrip("/")
        self.token = os.environ.get(token_env, "")
        self.token_env = token_env
        self.projects = projects
        self.auth = (auth or "basic").lower()
        self.email = email or os.environ.get(email_env, "")
        self.email_env = email_env
        self.api_style = (api_style or "auto").lower()
        self.story_points_field = (story_points_field or "").strip()
        # Okunamayan projeler burada birikir; ingest bunu senkron sonucuna taşır.
        self.warnings: list[str] = []
        # story point alanı hiçbir kayıtta bulunamadıysa tek seferlik uyar.
        self._sp_gorulen = False
        self._sp_arandi = False

    # --- altyapı --------------------------------------------------------------

    def _cloud_mu(self) -> bool:
        if self.api_style == "cloud":
            return True
        if self.api_style == "server":
            return False
        return "atlassian.net" in self.base_url.lower()

    def _uyar(self, mesaj: str) -> None:
        if mesaj not in self.warnings:
            self.warnings.append(mesaj)

    def _headers(self) -> dict:
        if self.auth == "bearer":
            return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        # Basic: "e-posta:api_token" base64. Jira Cloud'un beklediği biçim.
        ham = f"{self.email}:{self.token}".encode()
        return {
            "Authorization": "Basic " + base64.b64encode(ham).decode(),
            "Accept": "application/json",
        }

    def _client(self) -> httpx.Client:
        surum = "3" if self._cloud_mu() else "2"
        return httpx.Client(
            base_url=f"{self.base_url}/rest/api/{surum}",
            headers=self._headers(),
            timeout=30,
        )

    def _hata_uyarisi(self, proje: str, kod: int, govde: str = "") -> str:
        if kod == 401:
            if self.auth == "bearer":
                return (f"Jira '{proje}': kimlik doğrulama başarısız (401). Jira CLOUD "
                        f"kullanıyorsanız auth 'basic' olmalı (e-posta + API token); "
                        f"'bearer' yalnız Server/Data Center içindir. {self.token_env} dolu mu?")
            return (f"Jira '{proje}': kimlik doğrulama başarısız (401) — "
                    f"e-posta ({self.email or 'tanımsız'}) ve {self.token_env} doğru mu?")
        if kod == 403:
            return f"Jira '{proje}': erişim reddedildi (403) — hesabın bu projeye yetkisi var mı?"
        if kod == 404:
            return (f"Jira '{proje}': uç bulunamadı (404) — proje anahtarı doğru mu, "
                    f"base_url ({self.base_url}) doğru mu?")
        if kod == 410:
            return (f"Jira '{proje}': bu uç kaldırılmış (410). Jira Cloud'da eski arama ucu "
                    "kapatıldı; sources.tasks.jira.api_style: cloud deneyin.")
        return f"Jira '{proje}': API hatası ({kod}){(' — ' + govde[:150]) if govde else ''}."

    def _hazir_mi(self) -> bool:
        if not self.base_url:
            self._uyar("Jira adresi (base_url) tanımsız — hiçbir proje okunamaz.")
            return False
        if not self.token:
            self._uyar(f"{self.token_env} tanımsız — Jira okunamaz.")
            return False
        if self.auth == "basic" and not self.email:
            self._uyar(
                "Jira 'basic' kimlik için e-posta gerekli (sources.tasks.jira.email ya da "
                f"{self.email_env}). Jira Cloud e-posta + API token ister."
            )
            return False
        if not self.projects:
            self._uyar("Jira proje listesi boş — çekilecek iş yok.")
            return False
        return True

    # --- TaskProvider arayüzü --------------------------------------------------

    def fetch_team_members(self) -> list[NormalizedTeamMember]:
        """Jira proje rolleri kurulumdan kuruluma değiştiği için kadro burada
        okunmaz: boş liste = 'kaynak bilmiyor', ingest elle atanmış üyeliğe
        dokunmaz. Uydurulmuş kadro WIP paydasını sessizce bozardı."""
        return []

    def fetch_tasks(self, since: datetime | None = None) -> list[NormalizedTask]:
        out: list[NormalizedTask] = []
        self.warnings = []
        self._sp_gorulen = False
        self._sp_arandi = False
        if not self._hazir_mi():
            return out
        with self._client() as client:
            for project in self.projects:
                jql = f"project = {_jql_kacir(project)}"
                if since:
                    jql += f" AND updated >= '{since.strftime('%Y-%m-%d')}'"
                if self._cloud_mu():
                    out.extend(self._cloud_ara(client, project, jql))
                else:
                    out.extend(self._server_ara(client, project, jql))
        if self._sp_arandi and not self._sp_gorulen and self.story_points_field:
            self._uyar(
                f"Story point alanı '{self.story_points_field}' hiçbir kayıtta bulunamadı — "
                "bu alan kurulumdan kuruluma değişir. sources.tasks.jira.story_points_field "
                "ayarını Jira'daki gerçek alan kimliğiyle güncelleyin."
            )
        return out

    def _alanlar(self) -> str:
        temel = ["summary", "status", "created", "duedate", "issuetype",
                 "assignee", "timeoriginalestimate"]
        if self.story_points_field:
            temel.append(self.story_points_field)
        return ",".join(temel)

    def _cloud_ara(self, client: httpx.Client, project: str, jql: str) -> list[NormalizedTask]:
        """Jira Cloud: /search/jql + nextPageToken sayfalaması."""
        out: list[NormalizedTask] = []
        token: str | None = None
        while True:
            params: dict = {
                "jql": jql,
                "maxResults": 100,
                "fields": self._alanlar(),
                "expand": "changelog",
            }
            if token:
                params["nextPageToken"] = token
            try:
                resp = client.get("/search/jql", params=params)
            except httpx.HTTPError as e:
                self._uyar(f"Jira '{project}': ağ hatası ({type(e).__name__}).")
                return out
            if resp.status_code != 200:
                self._uyar(self._hata_uyarisi(project, resp.status_code, resp.text))
                return out
            data = resp.json()
            for issue in data.get("issues", []):
                out.append(self._normalize(issue, project))
            token = data.get("nextPageToken")
            if not token or data.get("isLast"):
                break
        return out

    def _server_ara(self, client: httpx.Client, project: str, jql: str) -> list[NormalizedTask]:
        """Jira Server/DC: klasik startAt sayfalaması."""
        out: list[NormalizedTask] = []
        start = 0
        while True:
            try:
                resp = client.get(
                    "/search",
                    params={"jql": jql, "expand": "changelog", "maxResults": 100,
                            "startAt": start, "fields": self._alanlar()},
                )
            except httpx.HTTPError as e:
                self._uyar(f"Jira '{project}': ağ hatası ({type(e).__name__}).")
                return out
            if resp.status_code != 200:
                self._uyar(self._hata_uyarisi(project, resp.status_code, resp.text))
                return out
            data = resp.json()
            issues = data.get("issues", [])
            for issue in issues:
                out.append(self._normalize(issue, project))
            start += len(issues)
            if not issues or start >= data.get("total", 0):
                break
        return out

    def _normalize(self, issue: dict, project: str) -> NormalizedTask:
        f = issue.get("fields", {})
        assignee = f.get("assignee") or {}
        issue_type = ((f.get("issuetype") or {}).get("name") or "").lower()
        transitions = [
            NormalizedTransition(
                from_status=item.get("fromString"),
                to_status=item.get("toString") or "",
                changed_at=ts,
            )
            for history in (issue.get("changelog") or {}).get("histories", [])
            if (ts := _dt(history.get("created"))) is not None
            for item in history.get("items", [])
            if item.get("field") == "status"
        ]
        # Katman 2 alanları: varsa kullan, yoksa None — asla uydurma
        seconds = f.get("timeoriginalestimate")
        story_points = None
        if self.story_points_field:
            self._sp_arandi = True
            story_points = f.get(self.story_points_field)
            if story_points is not None:
                self._sp_gorulen = True
        return NormalizedTask(
            source="jira",
            external_id=issue.get("key", ""),
            # Jira'da external_id ZATEN insan tarafından yazılabilir bir anahtar
            # ("PROJ-123"); ayrı bir alan üretmeye gerek yok, aynı değeri taşır.
            key=issue.get("key") or None,
            team_name=project,
            assignee_key=assignee.get("name") or assignee.get("accountId"),
            assignee_name=assignee.get("displayName"),
            title=f.get("summary"),
            type=TYPE_MAP.get(issue_type, "task"),
            status=(f.get("status") or {}).get("name"),
            created_at=_dt(f.get("created")),
            estimate_hours=(seconds / 3600) if seconds else None,
            due_date=_dt(f.get("duedate")),
            story_points=story_points,
            transitions=transitions,
        )
