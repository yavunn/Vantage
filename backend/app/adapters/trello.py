"""Trello REST API TaskProvider'ı.

Trello'da "status" = liste (kolon). Kart hareketleri (updateCard actions)
Katman 1 geçiş damgaları olarak normalize edilir. Trello'da estimate/story
point doğal alanı yoktur → Katman 2 alanları None kalır ve ilgili metrikler
otomatik gizlenir (İlke B).
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx

from app.adapters.base import NormalizedTask, NormalizedTransition

DONE_LIST_HINTS = ("done", "bitti", "tamamlan")
BUG_LABEL_HINTS = ("bug", "hata", "fix")


def _board_error(board_id: str, status: int) -> str:
    """Board okunamadığında kullanıcıya NET sebep. Sessiz atlama, entegrasyonu
    çalışıyor sanmaya yol açar — eksiklik görünür olmalı."""
    if status == 404:
        return (f"Trello board '{board_id}' bulunamadı (404) — id yanlış olabilir ya da "
                "token bu board'u görmüyor. Doğru id board URL'inde: trello.com/b/<ID>/isim")
    if status in (401, 403):
        return (f"Trello board '{board_id}': erişim reddedildi ({status}) — API key/token "
                "bu board'u okuyamıyor.")
    return f"Trello board '{board_id}': okunamadı (HTTP {status})."


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class TrelloProvider:
    def __init__(self, key_env: str, token_env: str, boards: list[str]):
        self.key = os.environ.get(key_env, "")
        self.token = os.environ.get(token_env, "")
        self.boards = boards
        # Okunamayan board'lar burada birikir; ingest bunu senkron sonucuna taşır.
        self.warnings: list[str] = []

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url="https://api.trello.com/1",
            params={"key": self.key, "token": self.token},
            timeout=30,
        )

    def fetch_tasks(self, since: datetime | None = None) -> list[NormalizedTask]:
        out: list[NormalizedTask] = []
        self.warnings = []
        if not self.boards:
            self.warnings.append("Trello board listesi boş — çekilecek kart yok.")
            return out
        if not self.key or not self.token:
            self.warnings.append("Trello API key/token tanımsız — hiçbir board okunamaz.")
            return out
        with self._client() as client:
            for board_id in self.boards:
                try:
                    board_resp = client.get(f"/boards/{board_id}", params={"fields": "name"})
                except httpx.HTTPError as e:
                    self.warnings.append(f"Trello board '{board_id}': bağlanılamadı ({type(e).__name__}).")
                    continue
                if board_resp.status_code != 200:
                    # Ölü/erişilemeyen board sessizce atlanmaz — senkron bunu raporlar.
                    self.warnings.append(_board_error(board_id, board_resp.status_code))
                    continue
                board_name = board_resp.json().get("name")

                cards_resp = client.get(
                    f"/boards/{board_id}/cards",
                    params={"fields": "name,idList,dateLastActivity,due,labels,idMembers"},
                )
                if cards_resp.status_code != 200:
                    self.warnings.append(
                        f"Trello board '{board_name or board_id}': kartlar okunamadı "
                        f"(HTTP {cards_resp.status_code})."
                    )
                    continue
                lists_resp = client.get(f"/boards/{board_id}/lists", params={"fields": "name"})
                list_names = {
                    lst["id"]: lst["name"]
                    for lst in (lists_resp.json() if lists_resp.status_code == 200 else [])
                }
                for card in cards_resp.json():
                    out.append(self._normalize(client, card, board_name, list_names))
        return out

    def _normalize(
        self, client: httpx.Client, card: dict, board_name: str | None, list_names: dict
    ) -> NormalizedTask:
        # Kart hareketleri = status geçişleri (Katman 1)
        transitions: list[NormalizedTransition] = []
        actions_resp = client.get(
            f"/cards/{card['id']}/actions", params={"filter": "updateCard:idList,createCard"}
        )
        if actions_resp.status_code == 200:
            for action in reversed(actions_resp.json()):  # eski → yeni
                ts = _dt(action.get("date"))
                data = action.get("data", {})
                if ts is None:
                    continue
                if action.get("type") == "createCard":
                    to_list = (data.get("list") or {}).get("name")
                    if to_list:
                        transitions.append(NormalizedTransition(None, to_list, ts))
                else:
                    before = (data.get("listBefore") or {}).get("name")
                    after = (data.get("listAfter") or {}).get("name")
                    if after:
                        transitions.append(NormalizedTransition(before, after, ts))

        labels = [(lbl.get("name") or "").lower() for lbl in card.get("labels", [])]
        is_bug = any(h in lbl for lbl in labels for h in BUG_LABEL_HINTS)
        created = transitions[0].changed_at if transitions else None
        return NormalizedTask(
            source="trello",
            external_id=card["id"],
            team_name=board_name,
            assignee_key=(card.get("idMembers") or [None])[0],
            assignee_name=None,  # üye adı ayrı istek; kimlik eşleme ingest'te
            title=card.get("name"),
            type="bug" if is_bug else "task",
            status=list_names.get(card.get("idList", ""), None),
            created_at=created,
            estimate_hours=None,   # Trello'da yok → metrik otomatik gizlenir
            due_date=_dt(card.get("due")),
            story_points=None,
            transitions=transitions,
        )
