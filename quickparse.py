"""
⚡ Quick add — type a task like a text message, no form.

    "email walter about surgery dates 15m by 3pm"
    "write discussion 1.5h tomorrow"
    "gym 60 min tonight"
    "read stroke paper 45m fri"
"""
from __future__ import annotations

import re
from datetime import datetime, time as dtime, timedelta

import valuation as V

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TEMPLATES = [
    ("📨 Clear inbox", 15, "admin"), ("🧠 Write 300 words", 45, "deep"), ("📄 Read a paper", 45, "deep"),
    ("📊 Analyze data", 60, "deep"), ("💪 Gym session", 60, "health"), ("🧺 Life admin errand", 30, "life"),
]


def parse(text: str, now: datetime) -> dict:
    t = " " + text.strip() + " "
    start_in = None
    m = re.search(r"\sin\s+(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minutes)\b", t, re.I)
    if m:
        start_in = round(float(m.group(1)) * (60 if m.group(2).lower().startswith("h") else 1))
        t = t.replace(m.group(0), " ")
    minutes = None
    m = re.search(r"\s(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours)\b", t, re.I)
    if m:
        minutes = round(float(m.group(1)) * 60)
        t = t.replace(m.group(0), " ")
    m = re.search(r"\s(\d+)\s*(m|min|mins|minute|minutes)\b", t, re.I)
    if m:
        minutes = (minutes or 0) + int(m.group(1))
        t = t.replace(m.group(0), " ")

    day = now.date()
    # a day word is a due date — unless it's possessive ("tomorrow's outfit") or what the task is *for*
    # ("prep for tomorrow", "notes about Monday"): then it's part of the title.
    keep = r"(?<!\bfor )(?<!\bof )(?<!\babout )(?<!\buntil )(?<!\bfrom )"
    not_poss = r"(?![''’]s\b)"
    day_given = False
    for word, delta in (("tomorrow", 1), ("tmrw", 1), ("today", 0), ("tonight", 0)):
        mm = re.search(rf"{keep}\b{word}\b{not_poss}", t, re.I)
        if mm:
            day, day_given = now.date() + timedelta(days=delta), True
            t = t[:mm.start()] + " " + t[mm.end():]
            if word == "tonight":
                t += " by 9pm "
            break
    else:
        mm = re.search(rf"{keep}\b(?:on\s+)?(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)"
                       rf"(?:day|sday|nesday|rsday|urday)?\b{not_poss}", t, re.I)
        if mm:
            target = WEEKDAYS.index(mm.group(1)[:3].lower())
            day, day_given = now.date() + timedelta(days=(target - now.weekday()) % 7 or 7), True
            t = t[:mm.start()] + " " + t[mm.end():]

    at = dtime(23, 59)
    at_time = False
    mm = re.search(r"(?:\b(by|at|before)|(@))\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t, re.I)
    if mm:
        at_time = (mm.group(1) or mm.group(2) or "").lower() in ("at", "@")  # "at 3pm" = it happens then
        h, mi, ap = int(mm.group(3)), int(mm.group(4) or 0), (mm.group(5) or "").lower()
        if ap == "pm" and h < 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
        elif not ap and h < 8:  # "by 3" means 3 PM
            h += 12
        at = dtime(min(h, 23), min(mi, 59))
        t = t.replace(mm.group(0), " ")
        day_given = True
    elif re.search(r"\beod\b", t, re.I):
        at = dtime(17, 0)
        t = re.sub(r"\beod\b", " ", t, flags=re.I)
        day_given = True
    when_given = day_given or "@" in t

    due = datetime.combine(day, at, now.tzinfo)
    if due <= now + timedelta(minutes=10):  # "by 3pm" when it's already 4pm → tomorrow
        due += timedelta(days=1)
    title = re.sub(r"\s+", " ", t).strip(" ,.-") or "Untitled task"
    title = title[0].upper() + title[1:]
    cat = V.guess_category(title)
    mins = minutes or {"show": 60, "life": 30, "health": 60, "admin": 30, "deep": 45}[cat]
    mins = min(V.MINUTES, key=lambda x: abs(x - mins))  # snap to the honest-time buckets
    out = {"title": title, "minutes": mins, "due": due, "category": cat, "at": None, "when_given": when_given}
    if at_time:  # happens at that time → due when it's over
        out["at"], out["due"] = due, due + timedelta(minutes=mins)
    elif start_in is not None:  # "in 1h" = I'll start in an hour
        out["at"] = now.replace(second=0, microsecond=0) + timedelta(minutes=start_in)
        if out["due"] < out["at"] + timedelta(minutes=mins):
            out["due"] = out["at"] + timedelta(minutes=mins)
    return out


def pick_next(tasks: list[dict], now: datetime, deep_hour: bool = False) -> dict | None:
    """🎲 'Just tell me what to do': today's mission first, then what's due soonest. In your peak hours it hands you
    the meaty task; outside them, the quick win."""
    today = now.date().isoformat()
    open_t = [t for t in tasks if t.get("status") == "open"]
    if not open_t:
        return None

    def score(t):
        due_h = (datetime.fromisoformat(t["deadline"]) - now).total_seconds() / 3600
        small = (t.get("minutes") or 60) <= 30
        return (t.get("mission_day") != today, due_h > 24, int(max(due_h, 0) // 6), small if deep_hour else not small,
                due_h)
    return min(open_t, key=score)


def session_length(task: dict) -> int:
    m = task.get("minutes") or 50
    return min([25, 50, 60, 90], key=lambda x: abs(x - m))
