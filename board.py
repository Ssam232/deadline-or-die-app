"""
🗓️ Bridge to your existing Notion board (e.g. the Assignments board in DECK 12) — no two islands.

  • Pull: today's cards on your board show up as one-tap suggestions when you set your mission.
  • Input board (e.g. Assignments): today + upcoming cards become one-tap suggestions; one-off cards you pick
          tick off when you finish them. Recurring weekday cards are never touched.
  • Output board (e.g. Fortuna, a daily schedule): WRITE-ONLY. Every task appears as a "🏁 …" card on the day/time
          it's set to happen (or when it was assigned), ticks ✅ when done, and is tidied away after its day.
          Nothing is ever read back from it, so whatever else you put there stays out of the game.

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


def _weekday_filter(m: dict, d: date) -> dict | None:
    opt = m["weekday_opts"].get(WEEKDAYS[d.weekday()]) if m["weekday"] else None
    if not opt:
        return None
    key = "contains" if m["weekday_type"] == "multi_select" else "equals"
    return {"property": m["weekday"], m["weekday_type"]: {key: opt}}


def _undated_weekday_filter(m: dict, d: date) -> dict | None:
    """Recurring cards: a weekday but no date (e.g. Group Meeting every Thursday)."""
    wk = _weekday_filter(m, d)
    if not wk:
        return None
    return {"and": [{"property": m["date"], "date": {"is_empty": True}}, wk]} if m["date"] else wk


def _day_filter(m: dict, d: date) -> dict | None:
    if m["date"]:
        on = {"property": m["date"], "date": {"equals": d.isoformat()}}
        rec = _undated_weekday_filter(m, d)
        return {"or": [on, rec]} if rec else on
    return _weekday_filter(m, d)


def _item(p: dict, m: dict, d: date | None, skip_ids, tz=None) -> dict | None:
    pr = p.get("properties", {})
    title = plain((pr.get(m["title"]) or {}).get("title")).strip()
    if not title or title.startswith(MARK) or title.startswith("✅") or clean_id(p["id"]) in skip_ids:
        return None
    if m["done"]:
        dp = pr.get(m["done"]) or {}
        if m["done_type"] == "checkbox":
            if dp.get("checkbox"):
                return None
        elif ((dp.get(m["done_type"]) or {}).get("name")) == m["done_opt"]:
            return None
    when = ""
    if m["date"]:
        start = ((pr.get(m["date"]) or {}).get("date") or {}).get("start") or ""
        if len(start) > 10:
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            dt = dt.astimezone(tz) if tz else dt
            when, d = dt.strftime("%I:%M %p").lstrip("0"), dt.date()
        elif start:
            d = date.fromisoformat(start[:10])
    if not when and m["time"]:
        when = plain((pr.get(m["time"]) or {}).get("rich_text")).strip()
    return {"id": p["id"], "title": title, "when": when, "date": d.isoformat() if d else ""}


def pull_day(n: Notion, m: dict, d: date, skip_ids: set[str] = frozenset()) -> list[dict]:
    flt = _day_filter(m, d)
    if not flt:
        return []
    skip_ids = {clean_id(x) for x in skip_ids}
    return [x for p in n.query(m["db"], {"filter": flt}) if (x := _item(p, m, d, skip_ids))]


def pull_range(n: Notion, m: dict, start: date, days: int, skip_ids: set[str] = frozenset(), tz=None) -> list[dict]:
    """Every open card from `start` through the next `days` days, soonest first."""
    skip_ids = {clean_id(x) for x in skip_ids}
    out = []
    if m["date"]:
        end = start + timedelta(days=days)
        flt = {"and": [{"property": m["date"], "date": {"on_or_after": start.isoformat()}},
                       {"property": m["date"], "date": {"before": end.isoformat()}}]}
        out = [x for p in n.query(m["db"], {"filter": flt, "sorts": [{"property": m["date"], "direction": "ascending"}]})
               if (x := _item(p, m, None, skip_ids, tz)) and x["date"]]
    if m["weekday"]:  # recurring weekday cards (no date): show each on its next occurrence
        seen = {x["id"] for x in out}
        for i in range(min(days, 7)):
            d = start + timedelta(days=i)
            flt = _undated_weekday_filter(m, d)
            for p in (n.query(m["db"], {"filter": flt}) if flt else []):
                x = _item(p, m, d, skip_ids)
                if x and x["id"] not in seen:
                    x["date"], x["recurring"] = d.isoformat(), True
                    seen.add(x["id"])
                    out.append(x)
    return sorted(out, key=lambda x: (x["date"], x["when"] or "99"))


def slot(t: dict, tz) -> tuple[datetime, bool, int]:
    """When the task is set to happen → (start, has_time, minutes). No schedule? Then when it was assigned."""
    mins = int(t.get("minutes") or 30)
    if t.get("scheduled"):
        return datetime.fromisoformat(t["scheduled"]).astimezone(tz), t.get("scheduled_time", True), mins
    return datetime.fromisoformat(t.get("created") or t["deadline"]).astimezone(tz), True, mins


def _hm(d: datetime) -> str:
    return d.strftime("%I:%M %p").lstrip("0")


def card_props(m: dict, t: dict, tz) -> dict:
    start, timed, mins = slot(t, tz)
    dl = datetime.fromisoformat(t["deadline"]).astimezone(tz)
    props = {m["title"]: {"title": rt(MARK + t["title"])}}
    if m["date"]:
        props[m["date"]] = {"date": ({"start": start.isoformat(), "end": (start + timedelta(minutes=mins)).isoformat()}
                                     if timed else {"start": start.date().isoformat()})}
    if m["weekday"]:
        opt = m["weekday_opts"].get(WEEKDAYS[start.weekday()])
        if opt:
            props[m["weekday"]] = ({"multi_select": [{"name": opt}]} if m["weekday_type"] == "multi_select"
                                   else {m["weekday_type"]: {"name": opt}})
    if m["time"]:
        txt = (f"{_hm(start)} - {_hm(start + timedelta(minutes=mins))}" if timed
               else f"{mins} min · due {_hm(dl)}")
        props[m["time"]] = {"rich_text": rt(txt)}
    return props


def push(n: Notion, m: dict, t: dict, tz) -> str:
    return n.req("POST", "/pages", json={"parent": {"database_id": m["db"]}, "properties": card_props(m, t, tz),
                                         "icon": {"type": "emoji", "emoji": "⏱️"}})["id"]


def mark_finished(n: Notion, m: dict, page_id: str, title: str, status: str, mark: str = "") -> None:
    icon = {"done": "🏁", "redeemed": "🩹", "failed": "💀"}.get(status, "⏱️")
    prefix = "✅ " if status in ("done", "redeemed") else "💀 "
    props = {m["title"]: {"title": rt(prefix + title)}}
    if m["done"] and status in ("done", "redeemed"):
        props[m["done"]] = ({"checkbox": True} if m["done_type"] == "checkbox"
                            else {m["done_type"]: {"name": m["done_opt"]}})
    n.req("PATCH", f"/pages/{page_id}", json={"properties": props, "icon": {"type": "emoji", "emoji": icon}})


def sync_out(n: Notion, m: dict, tasks: list[dict], now: datetime) -> list[str]:
    """OUTPUT board (e.g. Fortuna) — write-only. Every task lands on the day/time it's set to happen (or when it
    was assigned), moves if it's rescheduled, ticks ✅ when finished, and is tidied into Notion's trash once its day
    is over. Nothing is ever read back, and cards you add yourself are never touched."""
    errs = []
    tz = now.tzinfo
    horizon = (now + timedelta(days=PUSH_WINDOW_DAYS)).date()
    for t in tasks:
        try:
            start, timed, mins = slot(t, tz)
            sig = f"{t['title']}|{start.isoformat()}|{timed}|{mins}"
            if t["status"] == "open" and not t.get("out_page"):
                if start.date() <= horizon:
                    t["out_page"], t["out_state"], t["out_sig"] = push(n, m, t, tz), "open", sig
            elif t.get("out_page") and t["status"] == "open" and t.get("out_sig") != sig:
                n.req("PATCH", f"/pages/{t['out_page']}", json={"properties": card_props(m, t, tz)})
                t["out_sig"] = sig
            elif t.get("out_page") and t["status"] != t.get("out_state"):
                mark_finished(n, m, t["out_page"], t["title"], t["status"])
                t["out_state"] = t["status"]
            elif t.get("out_page") and t["status"] != "open" and not t.get("out_archived"):
                ended = max(start.date(), datetime.fromisoformat(
                    t.get("completed_at") or t.get("failed_at") or t["deadline"]).astimezone(tz).date())
                if ended < now.date():
                    n.req("PATCH", f"/pages/{t['out_page']}", json={"archived": True})
                    t["out_archived"] = True
        except Exception as e:  # noqa: BLE001 — a board hiccup must never block the game
            errs.append(f"{t['title']}: {e}")
    return errs


def sync_in(n: Notion, m: dict, tasks: list[dict]) -> list[str]:
    """INPUT board (e.g. Assignments): one-off cards you picked into a mission tick off when you finish them."""
    errs = []
    for t in tasks:
        try:
            if t.get("board_page") and t["status"] != t.get("board_state") and t["status"] != "open":
                mark_finished(n, m, t["board_page"], t["title"], t["status"])
                t["board_state"] = t["status"]
        except Exception as e:  # noqa: BLE001
            errs.append(f"{t['title']}: {e}")
    return errs
