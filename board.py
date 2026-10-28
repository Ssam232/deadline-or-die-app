"""
🗓️ Bridge to your existing Notion board (e.g. the Assignments board in DECK 12) — no two islands.

  • Pull: today's cards on your board show up as one-tap suggestions when you set your mission.
  • Push: Deadline or Die tasks due in the next 7 days appear on your board as "🏁 …" cards,
          and get ticked/renamed "✅ …" when you finish them with proof.

The board's columns are auto-detected, so it works with whatever setup you already have:
  title · a Date column (if any) · a weekday Select/Status (Monday…Sunday) · a "Time" text · a done checkbox/status.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from notion_store import Notion, clean_id, plain, rt

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DONE_WORDS = {"done", "complete", "completed", "finished", "✅"}
MARK = "🏁 "
PUSH_WINDOW_DAYS = 7


def list_databases(n: Notion, exclude: set[str] = frozenset()) -> list[dict]:
    """Every database the integration can see (i.e. anything inside DECK 12)."""
    res, cur = [], None
    exclude = {clean_id(x) for x in exclude}
    while True:
        body = {"filter": {"value": "database", "property": "object"}, "page_size": 100}
        if cur:
            body["start_cursor"] = cur
        d = n.req("POST", "/search", json=body)
        for db in d.get("results", []):
            if clean_id(db["id"]) not in exclude:
                res.append({"id": db["id"], "title": plain(db.get("title")) or "(untitled)", "url": db.get("url")})
        if not d.get("has_more"):
            return res
        cur = d.get("next_cursor")


def detect(n: Notion, db_id: str) -> dict:
    db = n.req("GET", f"/databases/{clean_id(db_id)}")
    props = db.get("properties", {})
    m = {"db": db["id"], "name": plain(db.get("title")) or "(untitled)", "title": None, "date": None,
         "weekday": None, "weekday_type": None, "weekday_opts": {}, "time": None, "done": None, "done_type": None,
         "done_opt": None}
    for name, p in props.items():
        t = p.get("type")
        if t == "title":
            m["title"] = name
        elif t == "date" and not m["date"]:
            m["date"] = name
        elif t in ("select", "status", "multi_select"):
            opts = [o["name"] for o in (p.get(t) or {}).get("options", [])]
            wk = {o.strip().lower(): o for o in opts if o.strip().lower() in WEEKDAYS
                  or o.strip().lower()[:3] in [w[:3] for w in WEEKDAYS] and len(o.strip()) <= 4}
            if len(wk) >= 3 and not m["weekday"]:
                m.update(weekday=name, weekday_type=t,
                         weekday_opts={WEEKDAYS[[w[:3] for w in WEEKDAYS].index(k[:3])]: v for k, v in wk.items()})
            elif t in ("status", "select") and not m["done"]:
                done = next((o for o in opts if o.strip().lower() in DONE_WORDS), None)
                if done:
                    m.update(done=name, done_type=t, done_opt=done)
        elif t == "checkbox" and not m["done"]:
            m.update(done=name, done_type="checkbox")
        elif t == "rich_text" and not m["time"] and "time" in name.lower():
            m["time"] = name
    return m


def describe(m: dict) -> str:
    bits = [f"title → **{m['title']}**"]
    bits.append(f"date → **{m['date']}**" if m["date"] else "no date column")
    bits.append(f"weekday → **{m['weekday']}**" if m["weekday"] else "no weekday column")
    if m["time"]:
        bits.append(f"time → **{m['time']}**")
    bits.append(f"done → **{m['done']}**" if m["done"] else "done → renames to ✅")
    return " · ".join(bits)


def _day_filter(m: dict, d: date) -> dict | None:
    if m["date"]:
        return {"property": m["date"], "date": {"equals": d.isoformat()}}
    if m["weekday"]:
        opt = m["weekday_opts"].get(WEEKDAYS[d.weekday()])
        if not opt:
            return None
        key = "contains" if m["weekday_type"] == "multi_select" else "equals"
        return {"property": m["weekday"], m["weekday_type"]: {key: opt}}
    return None


def pull_day(n: Notion, m: dict, d: date, skip_ids: set[str] = frozenset()) -> list[dict]:
    flt = _day_filter(m, d)
    if not flt:
        return []
    out = []
    for p in n.query(m["db"], {"filter": flt}):
        pr = p.get("properties", {})
        title = plain((pr.get(m["title"]) or {}).get("title")).strip()
        if not title or title.startswith(MARK) or title.startswith("✅") or clean_id(p["id"]) in skip_ids:
            continue
        if m["done"]:
            dp = pr.get(m["done"]) or {}
            if m["done_type"] == "checkbox":
                if dp.get("checkbox"):
                    continue
            elif ((dp.get(m["done_type"]) or {}).get("name")) == m["done_opt"]:
                continue
        when = ""
        if m["date"]:
            start = ((pr.get(m["date"]) or {}).get("date") or {}).get("start") or ""
            if len(start) > 10:
                when = datetime.fromisoformat(start.replace("Z", "+00:00")).strftime("%I:%M %p").lstrip("0")
        if not when and m["time"]:
            when = plain((pr.get(m["time"]) or {}).get("rich_text")).strip()
        out.append({"id": p["id"], "title": title, "when": when})
    return out


def push(n: Notion, m: dict, t: dict, tz) -> str:
    dl = datetime.fromisoformat(t["deadline"]).astimezone(tz)
    props = {m["title"]: {"title": rt(MARK + t["title"])}}
    if m["date"]:
        props[m["date"]] = {"date": {"start": dl.isoformat()}}
    if m["weekday"]:
        opt = m["weekday_opts"].get(WEEKDAYS[dl.weekday()])
        if opt:
            props[m["weekday"]] = ({"multi_select": [{"name": opt}]} if m["weekday_type"] == "multi_select"
                                   else {m["weekday_type"]: {"name": opt}})
    if m["time"]:
        props[m["time"]] = {"rich_text": rt(f"Due {dl:%I:%M %p}".replace(" 0", " "))}
    return n.req("POST", "/pages", json={"parent": {"database_id": m["db"]}, "properties": props,
                                         "icon": {"type": "emoji", "emoji": "⏱️"}})["id"]


def mark_finished(n: Notion, m: dict, page_id: str, title: str, status: str) -> None:
    icon = {"done": "🏁", "redeemed": "🩹", "failed": "💀"}.get(status, "⏱️")
    prefix = "✅ " if status in ("done", "redeemed") else "💀 "
    props = {m["title"]: {"title": rt(prefix + title)}}
    if m["done"] and status in ("done", "redeemed"):
        props[m["done"]] = ({"checkbox": True} if m["done_type"] == "checkbox"
                            else {m["done_type"]: {"name": m["done_opt"]}})
    n.req("PATCH", f"/pages/{page_id}", json={"properties": props, "icon": {"type": "emoji", "emoji": icon}})


def sync_out(n: Notion, m: dict, tasks: list[dict], now: datetime) -> list[str]:
    """Push upcoming tasks to the board and close out finished ones. Returns errors (never raises)."""
    errs = []
    horizon = now + timedelta(days=PUSH_WINDOW_DAYS)
    for t in tasks:
        try:
            if t["status"] == "open" and not t.get("board_page") and now < datetime.fromisoformat(t["deadline"]) <= horizon:
                t["board_page"] = push(n, m, t, now.tzinfo)
                t["board_state"] = "open"
            elif t.get("board_page") and t["status"] != t.get("board_state"):
                mark_finished(n, m, t["board_page"], t["title"], t["status"])
                t["board_state"] = t["status"]
        except Exception as e:  # noqa: BLE001 — a board hiccup must never block the game
            errs.append(f"{t['title']}: {e}")
    return errs
