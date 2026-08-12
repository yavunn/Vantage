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

from app.adapters.base import (
    NormalizedAssignee,
    NormalizedTask,
    NormalizedTeamMember,
    NormalizedTransition,
)
from app.adapters.http_retry import get_with_backoff

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
    def __init__(self, key_env: str, token_env: str, boards: list[str],
                 max_action_pages: int = 5):
        self.key = os.environ.get(key_env, "")
        self.token = os.environ.get(token_env, "")
        self.boards = boards
        # Board hareket geçmişi sayfa sınırı (sayfa başına 1000 hareket).
        # Sonsuz sayfalama, çok eski board'larda senkronu kilitlerdi.
        self.max_action_pages = max(1, max_action_pages)
        # Okunamayan board'lar burada birikir; ingest bunu senkron sonucuna taşır.
        self.warnings: list[str] = []

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url="https://api.trello.com/1",
            params={"key": self.key, "token": self.token},
            timeout=30,
        )

    def _member_records(
        self,
        client: httpx.Client,
        board_id: str,
        board_name: str | None,
        warn: bool = True,
    ) -> list[dict]:
        """Board üyelerinin HAM kayıtları (id, username, fullName).

        Ad ile kullanıcı adı ayrı ayrı gerekiyor: hesap eşleme ekranı adayı
        ikisinden de çıkarır ("ayse" kullanıcı adı ↔ ayse@sirket.com). Tek bir
        'görünen ad'a indirgemek o sinyali kaybettiriyordu.
        """
        try:
            resp = client.get(f"/boards/{board_id}/members", params={"fields": "fullName,username"})
        except httpx.HTTPError as e:
            if warn:
                self.warnings.append(
                    f"Trello board '{board_name or board_id}': üye listesi alınamadı "
                    f"({type(e).__name__}) — takım kadrosu güncellenemedi."
                )
            return []
        if resp.status_code != 200:
            if warn:
                self.warnings.append(
                    f"Trello board '{board_name or board_id}': üye listesi okunamadı "
                    f"(HTTP {resp.status_code}) — takım kadrosu güncellenemedi."
                )
            return []
        return [m for m in resp.json() if m.get("id")]

    def _members(
        self,
        client: httpx.Client,
        board_id: str,
        board_name: str | None,
        warn: bool = True,
    ) -> dict[str, str]:
        """Board üyeleri: kart üyesi id'si → görünen ad. Board başına TEK istek;
        kart başına üye adı sorulmaz. Okunamazsa boş sözlük döner — kartlar yine
        işlenir, yalnız atanan kişinin adı yerine ham id kalır.

        warn=False: kart çekerken üye listesi yalnızca görünen adı süsler; kartın
        kendisi eksiksiz gelir. Orada uyarı üretmek sağlam board'u bozukmuş gibi
        gösterirdi. Kadro çekerken (fetch_team_members) ürün ZATEN üye listesidir,
        orada sessiz kalmak gerçek bir kaybı gizler — bu yüzden warn=True.
        """
        return {
            m["id"]: (m.get("fullName") or m.get("username") or m["id"])
            for m in self._member_records(client, board_id, board_name, warn)
        }

    def fetch_member_directory(self) -> list[dict]:
        """Hesap eşleme ekranının kaynağı: her board'un üyeleri, ham alanlarıyla.

        `fetch_team_members`'tan farkı: orada ürün TAKIM KADROSUdur (tek görünen
        ad yeter), burada ürün KİMLİK EŞLEMESİdir — kullanıcı adı ile tam ad
        ayrı ayrı lazım. Okunamayan board `warnings`'e yazılır; sessiz atlama
        "board'da kimse yok" gibi görünürdü.
        """
        out: list[dict] = []
        self.warnings = []
        if not self.boards:
            self.warnings.append("Trello board listesi boş — okunacak üye yok.")
            return out
        if not self.key or not self.token:
            self.warnings.append("Trello API key/token tanımsız — üye listesi okunamaz.")
            return out
        with self._client() as client:
            for board_id in self.boards:
                try:
                    board_resp = client.get(f"/boards/{board_id}", params={"fields": "name"})
                except httpx.HTTPError as e:
                    self.warnings.append(
                        f"Trello board '{board_id}': bağlanılamadı ({type(e).__name__})."
                    )
                    continue
                if board_resp.status_code != 200:
                    self.warnings.append(_board_error(board_id, board_resp.status_code))
                    continue
                board_name = board_resp.json().get("name")
                for m in self._member_records(client, board_id, board_name):
                    out.append({
                        "board_id": board_id,
                        "board_name": board_name,
                        "member_id": m["id"],
                        "username": m.get("username") or None,
                        "full_name": m.get("fullName") or None,
                    })
        return out

    def fetch_team_members(self) -> list[NormalizedTeamMember]:
        """Board üyeleri = takım kadrosu. Board adı takım adıdır (fetch_tasks
        ile aynı kural), böylece kadro ve kartlar aynı takıma düşer."""
        out: list[NormalizedTeamMember] = []
        self.warnings = []
        if not self.boards or not self.key or not self.token:
            return out
        with self._client() as client:
            for board_id in self.boards:
                try:
                    board_resp = client.get(f"/boards/{board_id}", params={"fields": "name"})
                except httpx.HTTPError as e:
                    self.warnings.append(
                        f"Trello board '{board_id}': bağlanılamadı ({type(e).__name__})."
                    )
                    continue
                if board_resp.status_code != 200:
                    self.warnings.append(_board_error(board_id, board_resp.status_code))
                    continue
                board_name = board_resp.json().get("name")
                if not board_name:
                    # Takım adı yoksa kadro hiçbir takıma bağlanamaz — uydurmayız.
                    continue
                for member_id, name in self._members(client, board_id, board_name).items():
                    out.append(
                        NormalizedTeamMember(
                            team_name=board_name,
                            source="trello",
                            member_key=member_id,
                            member_name=name,
                        )
                    )
        return out

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

                if not board_name:
                    # Takım adı yoksa kartlar hiçbir takıma bağlanamaz: indekste
                    # ölü kayıt olur, takım bazlı sorguda hiç getirilemezler.
                    # Sessiz kalmak bu kaybı gizlerdi (bkz. rag/indexer.py uyarısı).
                    self.warnings.append(
                        f"Trello board '{board_id}': board adı okunamadı — bu board'un "
                        "kartları hiçbir takıma bağlanamaz ve asistan sorgularında "
                        "getirilemez."
                    )

                cards_resp = client.get(
                    f"/boards/{board_id}/cards",
                    # idShort/shortLink OLMADAN task↔commit bağı tahmin edilmek
                    # zorunda kalır: kartın `id` alanı opak bir hash'tir ve kimse
                    # onu commit mesajına yazmaz. idShort kartın üstünde görünen
                    # numaradır (#42) — insan yazabilir, bağ kesinleşir.
                    #
                    # filter=all: varsayılan çağrı yalnız AÇIK kartları getirir.
                    # Ölçüldü (gerçek board): varsayılan 19 kart, filter=all 21 —
                    # 2 arşivli kart hiç görünmüyordu. Arşivlenen kart genelde
                    # BİTMİŞ iştir; takım ne kadar düzenli arşivlerse cycle time
                    # ve teslim sinyali o kadar çok kayboluyordu.
                    params={"filter": "all",
                            "fields": "name,idList,dateLastActivity,due,labels,"
                                      "idMembers,idShort,shortLink,shortUrl,closed"},
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
                member_names = self._members(client, board_id, board_name, warn=False)
                kartlar = cards_resp.json()
                actions = self._board_actions(client, board_id, board_name)
                if actions is None:
                    # Sessiz atlama, cycle time'ı sebepsiz düşürüyordu.
                    self.warnings.append(
                        f"Trello board '{board_name or board_id}': kart hareketleri "
                        f"okunamadı — {len(kartlar)} kartın geçiş geçmişi (dolayısıyla "
                        "cycle time'ı) bu senkronda hesaplanamayacak."
                    )
                    actions = {}
                for card in kartlar:
                    out.append(
                        self._normalize(client, card, board_name, list_names,
                                        member_names, actions.get(card["id"]))
                    )
        return out

    def _board_actions(self, client: httpx.Client, board_id: str,
                       board_name: str | None) -> dict[str, list[dict]] | None:
        """Board'un TÜM kart hareketleri, kart id'sine göre gruplanmış.

        NEDEN BOARD SEVİYESİ: eskiden her kart için ayrı bir /cards/{id}/actions
        isteği atılıyordu. 300 kartlık bir board = 300 istek; Trello sınırı ise
        token başına ~100 istek/10 saniye. Sınıra takılınca yanıt 200 olmuyor ve
        o kartın TÜM geçişleri sessizce boş kalıyordu → cycle time düşüyor,
        sebebi hiçbir yerde görünmüyordu. Board ucu aynı veriyi tek istekte
        (gerekirse sayfalayarak) verir.

        None dönerse hareketler okunamadı — çağıran bunu uyarıya taşır.
        """
        gruplu: dict[str, list[dict]] = {}
        before: str | None = None
        for _ in range(self.max_action_pages):
            params = {"filter": "updateCard:idList,createCard", "limit": 1000}
            if before:
                params["before"] = before
            try:
                resp = get_with_backoff(client, f"/boards/{board_id}/actions", params)
            except httpx.HTTPError:
                return None
            if resp.status_code != 200:
                return None
            batch = resp.json() or []
            for action in batch:
                kart = ((action.get("data") or {}).get("card") or {}).get("id")
                if kart:
                    gruplu.setdefault(kart, []).append(action)
            if len(batch) < 1000:
                break
            before = batch[-1].get("id")
            if not before:
                break
        return gruplu

    def _normalize(
        self,
        client: httpx.Client,
        card: dict,
        board_name: str | None,
        list_names: dict,
        member_names: dict[str, str] | None = None,
        actions: list[dict] | None = None,
    ) -> NormalizedTask:
        # Kart hareketleri = status geçişleri (Katman 1). Board seviyesinde
        # önceden çekilir; kart başına istek atılmaz (oran sınırı).
        transitions: list[NormalizedTransition] = []
        for action in reversed(actions or []):  # eski → yeni
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
        # Kartın TÜM üyeleri. Eskiden yalnız `idMembers[0]` alınıyordu: iki
        # kişiye atanmış kartta ikinci kişi hiçbir yerde görünmüyordu — o kişinin
        # işi yokmuş gibi duruyor, kart↔commit eşleşmesinde kişi sinyali de
        # yanlış tarafa çalışıyordu. Sıra kaynaktaki sıradır; ilki BİRİNCİL.
        uyeler = [m for m in (card.get("idMembers") or []) if m]
        assignee_key = uyeler[0] if uyeler else None
        short = card.get("idShort")
        return NormalizedTask(
            source="trello",
            external_id=card["id"],
            # Kart numarası: board'da görünen, insanın commit mesajına
            # yazabileceği tek kısa referans. Yoksa None kalır — uydurmayız.
            key=str(short) if short is not None else None,
            url=card.get("shortUrl") or (
                f"https://trello.com/c/{card['shortLink']}"
                if card.get("shortLink") else None
            ),
            team_name=board_name,
            # Arşivli kart akışta değildir (WIP'e sayılmaz) ama kaydı tutulur:
            # arşivlenen kart çoğu zaman bitmiş iştir.
            archived=bool(card.get("closed")),
            assignee_key=assignee_key,
            # Ad board üye listesinden gelir (board başına tek istek). Bilinmiyorsa
            # None kalır: ingest o zaman ham id'yi görünen ad yapar, uydurmaz.
            assignee_name=(member_names or {}).get(assignee_key) if assignee_key else None,
            assignees=[
                NormalizedAssignee(key=m, name=(member_names or {}).get(m))
                for m in uyeler
            ],
            title=card.get("name"),
            type="bug" if is_bug else "task",
            status=list_names.get(card.get("idList", ""), None),
            created_at=created,
            estimate_hours=None,   # Trello'da yok → metrik otomatik gizlenir
            due_date=_dt(card.get("due")),
            story_points=None,
            transitions=transitions,
        )
