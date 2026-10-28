"""
🎉 Live events — random, time-limited reasons to come back.

Seeded by date, so the app and the phone nagger agree on the schedule without sharing state.
0–2 events a day between 10:00 and 20:00. You only find out when your phone buzzes.
"""
from __future__ import annotations

import os
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


_PROFILE: dict | None = None  # set by app/nagger from insights.profile(): steers WHEN surprises land


def set_profile(p: dict | None) -> None:
    global _PROFILE
    _PROFILE = p


def _hour_w(hour: int) -> float:
    import insights
    return insights.hour_weight(_PROFILE, hour)


def _seed(kind: str, d: date) -> str:
    """Salted with your private ntfy topic, so the public code can't be used to predict the schedule."""
    return f"{kind}-{d.isoformat()}-{os.getenv('NTFY_TOPIC', '')}"


def todays(d: date, tz) -> list[dict]:
    rng = random.Random(_seed("events", d))
    n = rng.choice([0, 1, 1, 1, 2, 2])
    keys = list(TYPES)
    out, used = [], set()
    for i in range(n):
        k = rng.choices(keys, weights=[TYPES[x]["weight"] for x in keys])[0]
        if k in used:
            continue
        used.add(k)
        opts = list(range(10 * 60, 20 * 60, 15))
        start_min = rng.choices(opts, weights=[_hour_w(m // 60) for m in opts])[0]
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


def prize_label(kind: str, val=None) -> str:
    return "this session counts ⚡ double" + (" + 🎁 a pit crate" if kind == "double_crate" else "")


def focus_challenges(d: date, tz) -> list[dict]:
    """1–3 timed challenges a day: start a session of N minutes inside the window, win the prize."""
    rng = random.Random(_seed("challenges", d))
    n = rng.choice([1, 2, 2, 3])
    slots = list(range(9 * 60, 19 * 60 + 1, 30))
    w = [_hour_w(m // 60) for m in slots]  # dead zones (up but not working) get up to 4× the odds
    starts = []
    for _ in range(n):
        k = rng.choices(range(len(slots)), weights=w)[0]
        starts.append(slots.pop(k))
        w.pop(k)
    starts.sort()
    out = []
    for i, s in enumerate(starts):
        minutes = rng.choices([25, 50, 60, 90], weights=[3, 3, 3, 2])[0]
        kind = "double_crate" if minutes >= 90 else "double"
        start = datetime.combine(d, dtime(s // 60, s % 60), tz)
        end = start + timedelta(hours=2)
        out.append({"id": f"{d.isoformat()}#c{i}", "start": start, "end": end, "minutes": minutes, "kind": kind,
                    "val": None, "label": f"Start a {minutes}-min focus session before {end:%I:%M %p} → "
                                          f"{prize_label(kind)}"})
    return out


def roll_drop(rng: random.Random | None = None) -> str:
    table = DROP_TABLE
    r = rng or random
    return r.choices([k for _, k in table], weights=[w for w, _ in table])[0]
