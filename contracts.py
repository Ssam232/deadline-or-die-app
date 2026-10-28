"""📜 Weekly contracts — three fresh challenges every Monday, so the game never gets stale."""
from __future__ import annotations

import random
from datetime import date, datetime

POOL = [
    {"id": "deep3", "title": "Finish 3 🧠 deep-work tasks", "goal": 3, "reward": 150},
    {"id": "focus300", "title": "Log 5 hours on the focus timer", "goal": 300, "reward": 150, "unit": "min"},
    {"id": "qualify5", "title": "Qualify on time 5 days", "goal": 5, "reward": 120},
    {"id": "early2", "title": "Finish 2 tasks 24h+ early", "goal": 2, "reward": 100},
    {"id": "noon3", "title": "Finish 3 tasks before noon", "goal": 3, "reward": 90},
    {"id": "done10", "title": "Finish 10 tasks", "goal": 10, "reward": 160},
    {"id": "streak5", "title": "Reach a 5-day streak", "goal": 5, "reward": 120},
    {"id": "sessions5", "title": "Complete 5 full focus sessions", "goal": 5, "reward": 100},
    {"id": "deepfocus", "title": "One 90-min focus session in a single sitting", "goal": 1, "reward": 80},
]


def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def this_week(now: datetime) -> list[dict]:
    return random.Random(week_key(now.date())).sample(POOL, 3)


def _in_week(iso: str | None, now: datetime) -> bool:
    return bool(iso) and week_key(datetime.fromisoformat(iso).date()) == week_key(now.date())


def progress(save: dict, c: dict, now: datetime) -> int:
    done = [t for t in save.get("tasks", []) if t.get("status") == "done" and _in_week(t.get("completed_at"), now)]
    log = [x for x in save.get("focus_log", []) if week_key(date.fromisoformat(x["date"])) == week_key(now.date())]
    cid = c["id"]
    if cid == "deep3":
        return sum(t.get("category") == "deep" for t in done)
    if cid == "focus300":
        return int(sum(x["min"] for x in log))
    if cid == "qualify5":
        wk = week_key(now.date())
        return sum(1 for k, v in save.get("days", {}).items()
                   if week_key(date.fromisoformat(k)) == wk and v.get("qualified") and not v.get("q_missed"))
    if cid == "early2":
        return sum((datetime.fromisoformat(t["deadline"]) - datetime.fromisoformat(t["completed_at"])).total_seconds()
                   >= 86400 for t in done)
    if cid == "noon3":
        return sum(datetime.fromisoformat(t["completed_at"]).hour < 12 for t in done)
    if cid == "done10":
        return len(done)
    if cid == "streak5":
        return save.get("day_streak", 0)
    if cid == "sessions5":
        return sum(bool(x.get("full")) for x in log)
    if cid == "deepfocus":
        return int(any(x["min"] >= 90 for x in log))
    return 0


def claim_key(c: dict, now: datetime) -> str:
    return f"{week_key(now.date())}:{c['id']}"
