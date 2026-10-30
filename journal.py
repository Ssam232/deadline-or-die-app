"""
📓 Journal: a one-tap morning check-in, a short end-of-day questionnaire, and the weekly recap built from both.

state["journal"][YYYY-MM-DD] = {
    "am": {"mood": 1-5, "energy": 1-5, "at": iso},
    "pm": {"mood", "energy", "win", "blocker", "tomorrow", "note", "at", "paid"},
}
Pays a little (pity coins), once a day: +2 for the morning check-in, up to +9 for the evening one.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

MOODS = {1: "😫", 2: "😕", 3: "😐", 4: "🙂", 5: "😄"}
MOOD_WORDS = {1: "rough", 2: "meh", 3: "okay", 4: "good", 5: "great"}
ENERGY = {1: "🪫", 2: "🔋", 3: "🔋🔋", 4: "⚡", 5: "⚡⚡"}
QUESTIONS = [  # key, prompt, placeholder
    ("win", "Best thing you got done today?", "Even small counts: 'sent the ethics form'"),
    ("blocker", "What got in the way?", "Phone, a long meeting, tired, nothing…"),
    ("tomorrow", "The one thing for tomorrow?", "Becomes a suggestion in tomorrow's mission"),
    ("note", "Anything else on your mind?", "Optional"),
]
AM_COINS = 2
PM_BASE = 3          # mood + energy
PM_PER_ANSWER = 2    # per real answer (10+ characters), up to three
PM_MAX = PM_BASE + 3 * PM_PER_ANSWER
PM_OPENS = 17        # the evening journal opens at 5 PM
RECAP_DAY, RECAP_HOUR = 6, 19   # Sunday 7 PM


def day(save: dict, d: date) -> dict:
    return save.setdefault("journal", {}).setdefault(d.isoformat(), {})


def peek(save: dict, d: date) -> dict:
    return (save.get("journal") or {}).get(d.isoformat(), {})


def check_in(save: dict, d: date, mood: int, energy: int, at: datetime, bank) -> int:
    """Morning check-in. Pays once; changing it later just updates it."""
    e = day(save, d)
    first = "am" not in e
    e["am"] = {"mood": int(mood), "energy": int(energy), "at": at.isoformat()}
    if first:
        bank(save, AM_COINS, "☀️ Morning check-in")
        return AM_COINS
    return 0


def pm_value(answers: dict) -> int:
    real = sum(1 for k in ("win", "blocker", "tomorrow", "note") if len((answers.get(k) or "").strip()) >= 10)
    return PM_BASE + PM_PER_ANSWER * min(3, real)


def close_day(save: dict, d: date, entry: dict, at: datetime, bank) -> int:
    """Evening journal. Pays the difference if you add more later the same day, never more than PM_MAX."""
    e = day(save, d)
    paid = (e.get("pm") or {}).get("paid", 0)
    e["pm"] = {**{k: (entry.get(k) or "").strip() for k in ("win", "blocker", "tomorrow", "note")},
               "mood": int(entry["mood"]), "energy": int(entry["energy"]), "at": at.isoformat(), "paid": paid}
    owed = min(PM_MAX, pm_value(entry)) - paid
    if owed > 0 and d == at.date():
        bank(save, owed, "📓 Journal")
        e["pm"]["paid"] = paid + owed
        return owed
    return 0


def entries(save: dict) -> list[tuple[date, dict]]:
    return sorted(((date.fromisoformat(k), v) for k, v in (save.get("journal") or {}).items() if v),
                  key=lambda x: x[0], reverse=True)


def mood_of(e: dict) -> float | None:
    vals = [e[s]["mood"] for s in ("am", "pm") if e.get(s)]
    return sum(vals) / len(vals) if vals else None


def focus_on(save: dict, d: date) -> float:
    return sum(x.get("min", 0) for x in save.get("focus_log", []) if x.get("date") == d.isoformat())


def done_on(save: dict, d: date, tz) -> list[dict]:
    out = []
    for t in save.get("tasks", []):
        c = t.get("completed_at")
        if t.get("status") in ("done", "redeemed") and c:
            cd = datetime.fromisoformat(c)
            cd = cd.astimezone(tz) if cd.tzinfo else cd
            if cd.date() == d:
                out.append(t)
    return out


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def recap(save: dict, ws: date, tz, through: date | None = None) -> dict:
    """Mon–Sun summary: focus, finishes, mood, wins and blockers from the journal."""
    days_ = [ws + timedelta(days=i) for i in range(7)]
    if through:
        days_ = [x for x in days_ if x <= through]
    rows = []
    for d_ in days_:
        e = peek(save, d_)
        rows.append({"date": d_, "focus": focus_on(save, d_), "done": done_on(save, d_, tz), "mood": mood_of(e),
                     "am": (e.get("am") or {}).get("mood"), "pm": (e.get("pm") or {}).get("mood"),
                     "energy": ((e.get("pm") or e.get("am") or {}).get("energy")), "entry": e})
    moods = [r["mood"] for r in rows if r["mood"] is not None]
    focus = sum(r["focus"] for r in rows)
    best = max(rows, key=lambda r: r["focus"]) if rows else None
    good = [r["focus"] for r in rows if r["mood"] is not None and r["mood"] >= 4]
    low = [r["focus"] for r in rows if r["mood"] is not None and r["mood"] <= 2]
    return {"start": ws, "rows": rows, "focus_min": focus, "done": sum(len(r["done"]) for r in rows),
            "mood_avg": sum(moods) / len(moods) if moods else None, "journaled": sum(1 for r in rows if r["entry"].get("pm")),
            "best": best if best and best["focus"] > 0 else None,
            "wins": [(r["date"], r["entry"]["pm"]["win"]) for r in rows if (r["entry"].get("pm") or {}).get("win")],
            "blockers": [(r["date"], r["entry"]["pm"]["blocker"]) for r in rows
                         if (r["entry"].get("pm") or {}).get("blocker")],
            "bailouts": [(d_, ((save.get("days") or {}).get(d_.isoformat()) or {}).get("bailout", {}).get("reason", ""))
                         for d_ in days_ if ((save.get("days") or {}).get(d_.isoformat()) or {}).get("bailout")],
            "focus_good_mood": sum(good) / len(good) if good else None,
            "focus_low_mood": sum(low) / len(low) if low else None}


def mood_face(v: float | None) -> str:
    return MOODS[max(1, min(5, round(v)))] if v is not None else "—"


def recap_text(r: dict) -> str:
    end = r["start"] + timedelta(days=6)
    lines = [f"Week of {r['start']:%b} {r['start'].day}–{end:%b} {end.day}",
             f"⏱️ {r['focus_min'] / 60:.1f} h focused · ✅ {r['done']} done · mood {mood_face(r['mood_avg'])}"
             + (f" ({r['mood_avg']:.1f}/5)" if r["mood_avg"] is not None else "")
             + f" · 📓 {r['journaled']}/7 days journaled"]
    if r["best"]:
        lines.append(f"Best day: {r['best']['date']:%A} ({r['best']['focus'] / 60:.1f} h)")
    if r.get("bailouts"):
        lines.append("🪂 Bailed out: " + ", ".join(f"{d_:%a} ({why})" for d_, why in r["bailouts"]))
    if r["wins"]:
        lines.append("\nWins")
        lines += [f"• {d_:%a}: {w}" for d_, w in r["wins"]]
    if r["blockers"]:
        lines.append("\nWhat got in the way")
        lines += [f"• {d_:%a}: {b}" for d_, b in r["blockers"]]
    return "\n".join(lines)
