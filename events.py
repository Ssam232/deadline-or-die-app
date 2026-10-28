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


# ── 🌅 Golden hour + focus-session drops ──
DROPS_PER_DAY = 3
DROP_TABLE = [  # (weight, kind)
    (40, "xp"), (25, "crate"), (15, "double_token"), (12, "coins"), (8, "upgrade_token"),
]
GOLDEN_TABLE = [(55, "crate"), (30, "double_token"), (15, "upgrade_token")]


def golden_hour(d: date, tz) -> tuple[datetime, datetime]:
    """A 2-hour window each day (between 8 AM and 6 PM). Start a focus session inside it → guaranteed good drop."""
    rng = random.Random(f"golden-{d.isoformat()}")
    start_min = rng.randrange(8 * 60, 16 * 60 + 1, 30)
    start = datetime.combine(d, dtime(start_min // 60, start_min % 60), tz)
    return start, start + timedelta(hours=2)


def roll_drop(golden: bool, rng: random.Random | None = None) -> str:
    table = GOLDEN_TABLE if golden else DROP_TABLE
    r = rng or random
    return r.choices([k for _, k in table], weights=[w for w, _ in table])[0]
