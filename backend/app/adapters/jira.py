"""Jira REST API TaskProvider'ı.

Katman 1'in kalbi: changelog'dan status geçiş zaman damgalarını çıkarır —
kullanıcı tarih girmese bile cycle time hesaplanabilir. Katman 2 alanları
(estimate, due date, story points) VARSA alınır, yoksa None kalır.
"""
from __future__ import annotations

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


class JiraProvider:
    def __init__(self, base_url: str, token_env: str, projects: list[str]):
        self.base_url = base_url.rstrip("/")
        self.token = os.environ.get(token_env, "")
        self.projects = projects

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=f"{self.base_url}/rest/api/2",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30,
        )

    def fetch_team_members(self) -> list[NormalizedTeamMember]:
        """Jira proje rolleri kurulumdan kuruluma değiştiği için kadro burada
        okunmaz: boş liste = 'kaynak bilmiyor', ingest elle atanmış üyeliğe
        dokunmaz. Uydurulmuş kadro WIP paydasını sessizce bozardı."""
        return []

    def fetch_tasks(self, since: datetime | None = None) -> list[NormalizedTask]:
        out: list[NormalizedTask] = []
        with self._client() as client:
            for project in self.projects:
                jql = f"project = {project}"
                if since:
                    jql += f" AND updated >= '{since.strftime('%Y-%m-%d')}'"
                start = 0
                while True:
                    resp = client.get(
                        "/search",
                        params={
                            "jql": jql,
                            "expand": "changelog",
                            "maxResults": 100,
                            "startAt": start,
                        },
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    issues = data.get("issues", [])
                    for issue in issues:
                        out.append(self._normalize(issue, project))
                    start += len(issues)
                    if start >= data.get("total", 0) or not issues:
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
        return NormalizedTask(
            source="jira",
            external_id=issue.get("key", ""),
            team_name=project,
            assignee_key=assignee.get("name") or assignee.get("accountId"),
            assignee_name=assignee.get("displayName"),
            title=f.get("summary"),
            type=TYPE_MAP.get(issue_type, "task"),
            status=(f.get("status") or {}).get("name"),
            created_at=_dt(f.get("created")),
            estimate_hours=(seconds / 3600) if seconds else None,
            due_date=_dt(f.get("duedate")),
            story_points=f.get("customfield_10016"),  # yaygın SP alanı; config'e taşınabilir
            transitions=transitions,
        )
