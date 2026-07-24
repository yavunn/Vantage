"""Sentetik KİRLİ veri üreteci (spec Bölüm 6 — kritik).

Amaç temiz demo verisi üretmek DEĞİL; gerçek dünyanın dağınıklığını üretmek:
- Billing takımı: görece sağlıklı süreç (kontrol grubu).
- Network Ops: estimate neredeyse hiç girilmiyor, status güncellenmiyor,
  kişi başı WIP yüksek → process hygiene ve WIP kuralları tetiklenir.
- CRM: PR'lar günlerce review beklemede, bazıları hiç review almıyor,
  aynı 3 dosya sürekli fix alıyor (hotspot), cuma akşamı deploy + hafta
  sonu fix örüntüsü var → review/hotspot/riskli-deploy kuralları tetiklenir.
Ayrıca: kimliksiz commit'ler, tarihi bozuk kayıtlar, boş alanlar.

Üretilen veri fixture JSON'larına yazılır ve NORMAL ingest hattından
geçirilir — dayanıklılık gerçek pipeline üzerinde kanıtlanır.
Deterministiktir (sabit random seed), tarihler bugüne görelidir.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.factory import FIXTURE_DIR  # noqa: E402
from app.core.db import Base, get_engine, get_sessionmaker  # noqa: E402
from app.models import Developer, Team, TeamMembership  # noqa: E402

rng = random.Random(42)
NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
DAYS = 90

TEAMS = {
    "Billing": {
        "repo": "billing-service",
        "devs": [("ayse@corp.local", "Ayşe K."), ("mehmet@corp.local", "Mehmet T."),
                 ("zeynep@corp.local", "Zeynep A."), ("can@corp.local", "Can Ö.")],
        "manager": ("selin@corp.local", "Selin Y."),
        "estimate_prob": 0.85, "status_prob": 0.9, "review_wait_h": (2, 24),
        "no_review_prob": 0.05, "wip_open": 6, "friday_deploys": False,
        "hotfix_prob": 0.02, "done_prob": 0.95,
    },
    "Network Ops": {
        "repo": "netops-tools",
        "devs": [("emre@corp.local", "Emre D."), ("fatma@corp.local", "Fatma S."),
                 ("burak@corp.local", "Burak G.")],
        "manager": ("hakan@corp.local", "Hakan B."),
        # Kirli örüntü: estimate yok denecek kadar az, status güncellenmiyor
        "estimate_prob": 0.1, "status_prob": 0.25, "review_wait_h": (12, 72),
        "no_review_prob": 0.2, "wip_open": 19, "friday_deploys": False,
        "hotfix_prob": 0.10, "done_prob": 0.8,
    },
    "CRM": {
        "repo": "crm-portal",
        "devs": [("deniz@corp.local", "Deniz Ç."), ("elif@corp.local", "Elif M."),
                 ("kerem@corp.local", "Kerem U."), ("melis@corp.local", "Melis P.")],
        "manager": ("umut@corp.local", "Umut E."),
        # Kirli örüntü: review darboğazı + hotspot dosyalar + cuma deploy'u
        "estimate_prob": 0.6, "status_prob": 0.7, "review_wait_h": (72, 160),
        "no_review_prob": 0.3, "wip_open": 24, "friday_deploys": True,
        "hotfix_prob": 0.15, "done_prob": 0.8,
    },
}

HOTSPOT_FILES = ["src/sync/order_sync.py", "src/legacy/customer_map.py", "src/api/quota.py"]


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def rand_time(days_ago_max: int = DAYS, days_ago_min: int = 0) -> datetime:
    delta = rng.uniform(days_ago_min * 24, days_ago_max * 24)
    return NOW - timedelta(hours=delta)


def make_files(repo: str, hotspot: bool) -> list[str]:
    if hotspot:
        return rng.sample(HOTSPOT_FILES, k=rng.randint(1, 2))
    return [f"src/{rng.choice(['api', 'core', 'ui', 'db'])}/file_{rng.randint(1, 40)}.py"]


def gen_commits() -> list[dict]:
    commits = []
    for team, spec in TEAMS.items():
        repo = spec["repo"]
        dev_keys = [d[0] for d in spec["devs"]]
        n = rng.randint(120, 200)
        for i in range(n):
            ts = rand_time()
            author = rng.choice(dev_keys)
            is_hotfix = rng.random() < spec["hotfix_prob"]
            is_fix = is_hotfix or rng.random() < 0.2
            hotspot = team == "CRM" and is_fix and rng.random() < 0.7
            prefix = "hotfix: " if is_hotfix else ("fix: " if is_fix else rng.choice(
                ["feat: ", "refactor: ", "chore: "]))
            msg = prefix + f"değişiklik {i}"
            commit = {
                "repo_name": repo,
                "sha": f"{team[:2].lower()}{i:05d}" + "".join(rng.choices("0123456789abcdef", k=8)),
                "author_key": author,
                "author_name": dict(spec["devs"]).get(author),
                "committed_at": iso(ts),
                "message": msg,
                "changed_files": make_files(repo, hotspot),
                "additions": rng.randint(2, 400),
                "deletions": rng.randint(0, 150),
            }
            # KİRLİLİK: %5 kimliksiz commit (CI botu, yanlış git config...)
            if rng.random() < 0.05:
                commit["author_key"] = None
                commit["author_name"] = None
            # KİRLİLİK: %3 tarih yok (bozuk import)
            if rng.random() < 0.03:
                commit["committed_at"] = None
            commits.append(commit)

        # CRM: cuma akşamı deploy (merge commit) + hafta sonu fix örüntüsü
        if spec["friday_deploys"]:
            for w in range(1, 12):
                friday = NOW - timedelta(days=NOW.weekday()) + timedelta(days=4) - timedelta(weeks=w)
                friday_evening = friday.replace(hour=17)
                if friday_evening > NOW:
                    continue
                commits.append({
                    "repo_name": repo,
                    "sha": f"deploy{w:04d}" + "".join(rng.choices("0123456789abcdef", k=8)),
                    "author_key": rng.choice(dev_keys),
                    "author_name": None,
                    "committed_at": iso(friday_evening),
                    "message": "Merge branch 'release' into main",
                    "changed_files": make_files(repo, False),
                    "additions": 10, "deletions": 2,
                })
                for _ in range(rng.randint(1, 3)):
                    weekend = friday_evening + timedelta(hours=rng.uniform(12, 48))
                    commits.append({
                        "repo_name": repo,
                        "sha": f"wfix{w:04d}" + "".join(rng.choices("0123456789abcdef", k=10)),
                        "author_key": rng.choice(dev_keys),
                        "author_name": None,
                        "committed_at": iso(weekend),
                        "message": "hotfix: canlıda hafta sonu düzeltmesi",
                        "changed_files": make_files(repo, True),
                        "additions": rng.randint(1, 30), "deletions": rng.randint(0, 10),
                    })
    return commits


def gen_prs() -> list[dict]:
    prs = []
    for team, spec in TEAMS.items():
        repo = spec["repo"]
        dev_keys = [d[0] for d in spec["devs"]]
        n = rng.randint(40, 70)
        for i in range(n):
            opened = rand_time(DAYS, 1)
            author = rng.choice(dev_keys)
            wait_lo, wait_hi = spec["review_wait_h"]
            never_reviewed = rng.random() < spec["no_review_prob"]
            first_review = None if never_reviewed else opened + timedelta(
                hours=rng.uniform(wait_lo, wait_hi))
            merged = None
            if rng.random() < 0.8:  # %20 hâlâ açık ya da kapanmış
                base = first_review or opened + timedelta(hours=rng.uniform(wait_lo, wait_hi))
                merged = base + timedelta(hours=rng.uniform(1, 48))
            reviews = []
            if first_review:
                reviewers = [k for k in dev_keys if k != author]
                reviews = [{"reviewer_key": rng.choice(reviewers),
                            "reviewed_at": iso(first_review)}]
            pr = {
                "repo_name": repo,
                "external_id": f"{repo}-{i+1}",
                "author_key": author,
                "author_name": dict(spec["devs"]).get(author),
                "title": f"PR {i+1}: {rng.choice(['özellik', 'düzeltme', 'refactor'])}",
                "opened_at": iso(opened),
                "first_review_at": iso(first_review),
                "merged_at": iso(merged) if merged and merged < NOW else None,
                "closed_at": None,
                "reviews": reviews,
            }
            # KİRLİLİK: %4 açılış tarihi bile yok (eski migrasyon artığı)
            if rng.random() < 0.04:
                pr["opened_at"] = None
                pr["first_review_at"] = None
            prs.append(pr)
    return prs


def gen_tasks() -> list[dict]:
    tasks = []
    statuses_flow = ["To Do", "In Progress", "In Review", "Done"]
    for team, spec in TEAMS.items():
        dev_keys = [d[0] for d in spec["devs"]]
        n = rng.randint(60, 90)
        open_target = spec["wip_open"]
        opened_so_far = 0
        for i in range(n):
            created = rand_time(DAYS, 0)
            assignee = rng.choice(dev_keys) if rng.random() < 0.85 else None  # %15 atanmamış
            has_status_updates = rng.random() < spec["status_prob"]
            keep_open = opened_so_far < open_target
            transitions = []
            status = "To Do"
            if has_status_updates:
                t = created
                last = 1 if keep_open else (3 if rng.random() < spec["done_prob"] else 2)
                for idx in range(1, last + 1):
                    t = t + timedelta(hours=rng.uniform(4, 96))
                    if t > NOW:
                        break
                    transitions.append({
                        "from_status": statuses_flow[idx - 1],
                        "to_status": statuses_flow[idx],
                        "changed_at": iso(t),
                    })
                    status = statuses_flow[idx]
            if status != "Done":
                opened_so_far += 1
            is_bug = rng.random() < 0.3
            task = {
                "source": "fixture",
                "external_id": f"{team[:3].upper()}-{i+1}",
                "team_name": team,
                "assignee_key": assignee,
                "assignee_name": dict(spec["devs"]).get(assignee) if assignee else None,
                "title": f"{'Bug' if is_bug else 'İş'} {i+1}",
                "type": "bug" if is_bug else rng.choice(["story", "task"]),
                "status": status,
                "created_at": iso(created),
                # Katman 2 — kirlilik burada: çoğu zaman BOŞ
                "estimate_hours": round(rng.uniform(2, 40), 1)
                if rng.random() < spec["estimate_prob"] else None,
                "due_date": iso(created + timedelta(days=rng.randint(3, 21)))
                if rng.random() < spec["estimate_prob"] * 0.7 else None,
                "story_points": float(rng.choice([1, 2, 3, 5, 8]))
                if rng.random() < spec["estimate_prob"] * 0.8 else None,
                "transitions": transitions,
            }
            tasks.append(task)
    return tasks


def seed_org(session) -> None:
    """Takımlar, geliştiriciler, üyelikler (yönetici dahil) ve repo eşlemesi."""
    from app.models import Repo

    for team_name, spec in TEAMS.items():
        team = Team(name=team_name)
        session.add(team)
        session.flush()
        session.add(Repo(name=spec["repo"], team_id=team.id))
        for key, name in spec["devs"]:
            dev = Developer(external_ids={"git": key, "fixture": key}, display_name=name)
            session.add(dev)
            session.flush()
            session.add(TeamMembership(team_id=team.id, developer_id=dev.id, role="member"))
        mkey, mname = spec["manager"]
        mgr = Developer(external_ids={"git": mkey, "fixture": mkey}, display_name=mname)
        session.add(mgr)
        session.flush()
        session.add(TeamMembership(team_id=team.id, developer_id=mgr.id, role="manager"))
    session.commit()


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    datasets = {
        "commits.json": gen_commits(),
        "pull_requests.json": gen_prs(),
        "tasks.json": gen_tasks(),
    }
    for fname, data in datasets.items():
        with open(FIXTURE_DIR / fname, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f"  {fname}: {len(data)} kayıt")

    Base.metadata.create_all(get_engine())
    session = get_sessionmaker()()
    try:
        if session.query(Team).count() == 0:
            seed_org(session)
            print("  organizasyon: 3 takım, 15 kişi (3 yönetici)")
        else:
            print("  organizasyon zaten mevcut, atlandı")
    finally:
        session.close()


if __name__ == "__main__":
    main()
