"""
🎉 Live events — random, time-limited reasons to come back.

Seeded by date, so the app and the phone nagger agree on the schedule without sharing state.
0–2 events a day between 10:00 and 20:00. You only find out when your phone buzzes.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time as dtime, timedelta

TYPES = {
    "double": {"title": "⚡ DOUBLE COINS & XP", "minutes": 180, "weight": 3,
               "push": "Everything you finish in the next 3 hours pays double. Go.",
               "banner": "Every finish pays **double coins & XP**."},
    "supply": {"title": "🎁 SUPPLY DROP", "minutes": 120, "weight": 3,
               "push": "A free pit crate just landed. It's gone in 2 hours — open the app to grab it.",
               "banner": "A **free pit crate** is waiting. Claim it before it's gone."},
    "bounty": {"title": "🎯 BOUNTY", "minutes": 240, "weight": 2,
               "push": "Tomorrow Tom bet you 75 coins you won't finish a 🧠 deep-work task in the next 4 hours.",
               "banner": "Finish a **🧠 deep-work** task before it ends: **+75** bounty."},
    "pitcrew": {"title": "🔧 PIT CREW ON SITE", "minutes": 120, "weight": 1,
                "push": "Free repairs for the next 2 hours. Come get your car fixed.",
                "banner": "**Free +30% repair** for your car. Claim it while they're here."},
}
BOUNTY = 75


def todays(d: date, tz) -> list[dict]:
    rng = random.Random(f"events-{d.isoformat()}")
    n = rng.choice([0, 1, 1, 1, 2, 2])
    keys = list(TYPES)
    out, used = [], set()
    for i in range(n):
        k = rng.choices(keys, weights=[TYPES[x]["weight"] for x in keys])[0]
        if k in used:
            continue
        used.add(k)
        start_min = rng.randrange(10 * 60, 20 * 60, 15)
        start = datetime.combine(d, dtime(start_min // 60, start_min % 60), tz)
        out.append({"id": f"{d.isoformat()}#{i}", "type": k, "start": start,
                    "end": start + timedelta(minutes=TYPES[k]["minutes"]), **TYPES[k]})
    return sorted(out, key=lambda e: e["start"])


def active(now: datetime) -> list[dict]:
    return [e for e in todays(now.date(), now.tzinfo) if e["start"] <= now < e["end"]]


def is_double(now: datetime) -> bool:
    return any(e["type"] == "double" for e in active(now))


# ── ⏱️ Focus challenges + per-session drops ──
DROPS_PER_DAY = 3
DROP_TABLE = [  # (weight, kind)
    (40, "xp"), (25, "crate"), (15, "double_token"), (12, "coins"), (8, "upgrade_token"),
]


CHALLENGE_PRIZES = {  # by session length: what a challenge can pay out
    25: [("coins", 25), ("crate", None)],
    50: [("crate", None), ("double", 120)],
    60: [("crate", None), ("double", 120)],
    90: [("double", 180), ("upgrade_token", None)],
}


def prize_label(kind: str, val) -> str:
    if kind == "coins":
        return f"+{val} coins"
    if kind == "double":
        return f"⚡ double coins & XP for {val // 60}h"
    return "🎁 a pit crate" if kind == "crate" else "🔧 a free-upgrade token"


def focus_challenges(d: date, tz) -> list[dict]:
    """1–3 timed challenges a day: start a session of N minutes inside the window, win the prize."""
    rng = random.Random(f"challenges-{d.isoformat()}")
    n = rng.choice([1, 2, 2, 3])
    starts = sorted(rng.sample(range(9 * 60, 19 * 60 + 1, 30), n))
    out = []
    for i, s in enumerate(starts):
        minutes = rng.choices([25, 50, 60, 90], weights=[3, 3, 3, 2])[0]
        kind, val = rng.choice(CHALLENGE_PRIZES[minutes])
        start = datetime.combine(d, dtime(s // 60, s % 60), tz)
        end = start + timedelta(hours=2)
        out.append({"id": f"{d.isoformat()}#c{i}", "start": start, "end": end, "minutes": minutes, "kind": kind,
                    "val": val, "label": f"Start a {minutes}-min focus session between {start:%I:%M}–{end:%I:%M %p} "
                                         f"→ {prize_label(kind, val)}"})
    return out


def roll_drop(rng: random.Random | None = None) -> str:
    table = DROP_TABLE
    r = rng or random
    return r.choices([k for _, k in table], weights=[w for w, _ in table])[0]
