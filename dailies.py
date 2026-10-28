"""
🔁 Dailies — small things that have to happen every day (water, prayers, brushing…). You set them up yourself.

Low gain, high penalty: hitting the day's count pays a little (and grows the daily's streak); missing it at midnight
costs a lot. Tap +1 each time. Honour system — no proof — which is exactly why the penalty is big.

Values are set by the game, not by you, from how many times a day it has to happen:
  once a day = smallest reward, biggest penalty (it's one thing — no excuse);
  many times a day = a bit more reward, smaller penalty (harder to land every single one).
  1×: +5 / −45 · 2×: +5 / −40 · 3×: +6 / −35 · 5×: +5 / −25 · 8×: +6 / −20
  Break-even sits at a ~90% hit rate (easing to ~76% for 8×-a-day): consistent = slowly richer, sloppy = poorer.
  Every 7 days in a row on one daily: +15 bonus. Missed dailies cost at most 60 in one day (no death spirals).
  The day you add a daily is free: it can pay you, but it can't charge you.

Dailies never touch your Notion boards.

Anti-dodge rules: removing or pausing a daily only takes effect tomorrow (today still counts), and you can't
lower today's target after the fact. Pit-stop days skip dailies. After a long absence at most
MAX_CHARGED_DAYS missed days are charged.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

PRESETS = [  # (name, times per day)
    ("💧 Drink water (glasses)", 8), ("🕌 Prayers", 5), ("🦷 Brush teeth", 2), ("🚶 10k steps", 1),
    ("📖 Read 10 pages", 1), ("🧘 Stretch", 1), ("🛏️ In bed by midnight", 1),
]


MAX_CHARGED_DAYS = 3
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
STREAK_BONUS_EVERY, STREAK_BONUS = 7, 15   # every 7 days in a row on one daily: +15
DAILY_PENALTY_CAP = 60                      # most the dailies can cost you in one day, however many you miss


def _n(h_or_target) -> int:
    return h_or_target["target"] if isinstance(h_or_target, dict) else int(h_or_target)


def penalty(h_or_target) -> int:
    """Once a day = biggest hit; many times a day = smaller (harder to land every single one)."""
    return max(20, 50 - 5 * _n(h_or_target))


def breakeven(h_or_target) -> float:
    """Hit rate at which a daily pays for itself: 90% for once-a-day, easing to 76% for 8×."""
    return max(0.76, 0.90 - 0.02 * (_n(h_or_target) - 1))


def reward(h_or_target) -> int:
    """Small — but set so that hitting it ~90% of the time comes out ahead, not behind."""
    be = breakeven(h_or_target)
    return max(2, round(penalty(h_or_target) * (1 - be) / be))


def habits(save: dict) -> list[dict]:
    return save.setdefault("habits", [])


def add(save: dict, name: str, target: int, days: list[int], today: date) -> dict:
    h = {"id": uuid.uuid4().hex[:8], "name": name.strip(), "target": max(1, int(target)),
         "days": sorted(days) or list(range(7)), "start": today.isoformat(), "end": None, "streak": 0, "best": 0}
    habits(save).append(h)
    return h


def remove(save: dict, hid: str, today: date) -> None:
    """Takes effect tomorrow: today still counts (no dodging tonight's penalty)."""
    for h in habits(save):
        if h["id"] == hid:
            if h["start"] > today.isoformat():
                save["habits"] = [x for x in habits(save) if x["id"] != hid]
            else:
                h["end"] = today.isoformat()


def active_on(h: dict, d: date) -> bool:
    iso = d.isoformat()
    return h["start"] <= iso and (not h.get("end") or iso <= h["end"]) and d.weekday() in h["days"]


def log(save: dict, d: date) -> dict:
    return save.setdefault("habit_log", {}).setdefault(d.isoformat(), {})


def count(save: dict, hid: str, d: date) -> int:
    return int(save.get("habit_log", {}).get(d.isoformat(), {}).get(hid, 0))


def tap(save: dict, hid: str, d: date, delta: int = 1) -> int:
    lg = log(save, d)
    h = next(x for x in habits(save) if x["id"] == hid)
    lg[hid] = max(0, min(h["target"] * 3, int(lg.get(hid, 0)) + delta))
    return lg[hid]


def claimed(save: dict, hid: str, d: date) -> bool:
    return f"{d.isoformat()}#{hid}" in save.get("habit_claims", [])


def claim(save: dict, hid: str, d: date, bank, why: str = "") -> int:
    """Pay the day's (small) reward once the count is hit. Returns coins paid (0 if not eligible)."""
    h = next(x for x in habits(save) if x["id"] == hid)
    if claimed(save, hid, d) or count(save, hid, d) < h["target"]:
        return 0
    save.setdefault("habit_claims", []).append(f"{d.isoformat()}#{hid}")
    del save["habit_claims"][:-400]
    h["streak"] = h.get("streak", 0) + 1
    h["best"] = max(h.get("best", 0), h["streak"])
    paid = reward(h)
    bank(save, paid, f"🔁 {h['name']}{why}")
    if h["streak"] % STREAK_BONUS_EVERY == 0:
        bank(save, STREAK_BONUS, f"🔥 {h['streak']}-day streak: {h['name']}")
        paid += STREAK_BONUS
    save["xp"] = save.get("xp", 0) + 2
    return paid


def today_status(save: dict, d: date) -> list[dict]:
    out = []
    for h in habits(save):
        if active_on(h, d):
            c = count(save, h["id"], d)
            out.append({"h": h, "count": c, "done": c >= h["target"], "claimed": claimed(save, h["id"], d)})
    return out


def settle(save: dict, today: date, bank, is_rest) -> list[str]:
    """Close out past days: auto-claim days you hit, charge the penalty for days you missed. Idempotent."""
    msgs = []
    last = save.get("habits_settled")
    starts = [date.fromisoformat(h["start"]) for h in habits(save)]
    if not starts:
        return msgs
    d = date.fromisoformat(last) + timedelta(days=1) if last else min(starts)
    d = max(d, today - timedelta(days=7))
    charged = 0
    while d < today:
        if not is_rest(save, d):
            missed, day_total = [], 0
            for h in habits(save):
                if not active_on(h, d):
                    continue
                if count(save, h["id"], d) >= h["target"]:
                    claim(save, h["id"], d, bank, " (auto-claimed)")
                elif h["start"] == d.isoformat():
                    pass  # the day you added it is free
                elif charged < MAX_CHARGED_DAYS:
                    lost = h.get("streak", 0)
                    h["streak"] = 0
                    hit = min(penalty(h), DAILY_PENALTY_CAP - day_total)
                    if hit > 0:
                        day_total += hit
                        bank(save, -hit, f"🔁 Missed daily: {h['name']} ({d:%a})")
                    missed.append(f"{h['name']} {count(save, h['id'], d)}/{h['target']} → **−{max(hit, 0)}**"
                                  + (f" (streak {lost} lost)" if lost else "")
                                  + (" (capped)" if hit < penalty(h) else ""))
                else:
                    h["streak"] = 0
            if missed:
                charged += 1
                msgs.append(f"### 🔁 Dailies missed — {d:%A %b %d}\n" + "\n".join(f"- {m}" for m in missed))
        save["habits_settled"] = d.isoformat()
        d += timedelta(days=1)
    # prune old logs
    cutoff = (today - timedelta(days=60)).isoformat()
    save["habit_log"] = {k: v for k, v in save.get("habit_log", {}).items() if k >= cutoff}
    return msgs


def at_stake(save: dict, d: date) -> tuple[int, list[str]]:
    """Coins on the line at midnight + 'Water 3/8' style lines, for nags (first day free, daily cap applied)."""
    total, lines = 0, []
    for s in today_status(save, d):
        if not s["done"]:
            lines.append(f"{s['h']['name']} {s['count']}/{s['h']['target']}")
            if s["h"]["start"] != d.isoformat():
                total += penalty(s["h"])
    return min(total, DAILY_PENALTY_CAP), lines


def hit_rate(save: dict, today: date, days: int = 28) -> float | None:
    hit = tot = 0
    for k in range(1, days + 1):
        d = today - timedelta(days=k)
        for h in habits(save):
            if active_on(h, d):
                tot += 1
                hit += count(save, h["id"], d) >= h["target"]
    return hit / tot if tot else None
