"""
🚦 Daily qualifying — no empty days.

Every day needs a mission (1–3 things you'll finish today), locked in before the cutoff.
  • Lock it in on time → fuel coins.
  • Miss the cutoff → penalty, rivals get faster, and the SAFETY CAR assigns you a task.
  • Finish nothing by midnight → ZERO DAY: penalty, car damage, day streak dies.
  • One pit stop per week (sick / rest) exempts a day.

Pure functions on the save dict (no Streamlit) so the app and the nagger agree on the rules.
Only the app ever *applies* penalties; the nagger just reads and warns.
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta

DAILY_DEFAULTS = {
    "qualify_by": 11,          # hour (local) the mission must be locked in by
    "qualify_penalty": 20,
    "qualify_fuel": 15,
    "zero_day_penalty": 40,
    "zero_day_damage": 10,
    "safety_car_hour": 18,     # safety-car task due by this hour (or +3h if later)
    "pit_stops_per_week": 1,
    "rest_days": [],           # weekday numbers, 0 = Monday
}
WEEKEND = (5, 6)            # Sat/Sun: qualifying is optional (still pays fuel, never costs)
BAILOUTS_PER_WEEK = 1
BAIL_REASONS = ["🤒 Sick", "😵 Exhausted / burnt out", "🧠 Mental health", "🚨 Emergency", "🧳 Life got in the way",
                "✏️ Something else"]
SAFETY_CAR_TITLE = "🚨 Safety car: 30 min of focused work on anything real"
SETTLE_LOOKBACK_DAYS = 7
MAX_CHARGED_ZERO_DAYS = 3   # comeback rule: returning after a long absence shouldn't bury you


def level(save: dict) -> int:
    import math
    return int(math.sqrt(max(save.get("xp", 0), 0) / 50)) + 1


def level_factor(save: dict) -> float:
    """The game gets harder as you get better: penalties grow 10% per level, up to 2×."""
    return min(2.0, 1 + 0.1 * (level(save) - 1))


def min_mission_minutes(save: dict) -> int:
    return 30 if level(save) < 3 else 60


def cfg(save: dict) -> dict:
    s = save.get("settings", {})
    c = {k: s.get(k, v) for k, v in DAILY_DEFAULTS.items()}
    f = level_factor(save)
    c["qualify_penalty"] = round(c["qualify_penalty"] * f)
    c["zero_day_penalty"] = round(c["zero_day_penalty"] * f)
    return c


def day(save: dict, d: date) -> dict:
    return save.setdefault("days", {}).setdefault(d.isoformat(), {})


def peek_day(save: dict, d: date) -> dict:
    return save.get("days", {}).get(d.isoformat(), {})


def finished_on(save: dict, d: date) -> list[dict]:
    key = d.isoformat()
    return [t for t in save.get("tasks", []) if t.get("status") in ("done", "redeemed")
            and (t.get("completed_at") or "")[:10] == key]


def mission(save: dict, d: date) -> list[dict]:
    key = d.isoformat()
    return [t for t in save.get("tasks", []) if t.get("mission_day") == key]


def pit_stops_used(save: dict, d: date) -> int:
    y, w, _ = d.isocalendar()
    return sum(1 for k, v in save.get("days", {}).items()
               if v.get("pit_stop") and date.fromisoformat(k).isocalendar()[:2] == (y, w))


def is_rest(save: dict, d: date) -> bool:
    e = peek_day(save, d)
    return d.weekday() in cfg(save)["rest_days"] or bool(e.get("pit_stop")) or bool(e.get("bailout"))


def qualify_optional(d: date) -> bool:
    """Weekends: sleep in. Locking in still pays fuel; not locking in costs nothing."""
    return d.weekday() in WEEKEND


def bailouts_used(save: dict, d: date) -> int:
    y, w, _ = d.isocalendar()
    return sum(1 for k, v in save.get("days", {}).items()
               if v.get("bailout") and date.fromisoformat(k).isocalendar()[:2] == (y, w))


def bailouts_left(save: dict, d: date) -> int:
    return max(0, BAILOUTS_PER_WEEK - bailouts_used(save, d))


def bail_preview(save: dict, now: datetime) -> list[dict]:
    """Open tasks due today that a bailout would push to tomorrow (the safety car is simply cancelled)."""
    out = []
    for t in save.get("tasks", []):
        if t.get("status") != "open":
            continue
        dl = datetime.fromisoformat(t["deadline"])
        dl = dl if dl.tzinfo else dl.replace(tzinfo=now.tzinfo)
        if dl.astimezone(now.tzinfo).date() <= now.date():
            out.append(t)
    return out


def bail_out(save: dict, now: datetime, reason: str, why: str) -> dict | None:
    """🪂 Pull the cord on today, any time of day. Today stops counting: no zero-day, dailies aren't charged, the
    day streak is frozen (not broken, not grown), today's open work moves to tomorrow at the same time (the
    safety car is cancelled). Once a week. Penalties already taken today stay taken."""
    today = now.date()
    if bailouts_left(save, today) <= 0 or peek_day(save, today).get("bailout"):
        return None
    moved, cancelled = [], []
    for t in bail_preview(save, now):
        if t.get("title", "").startswith("🚨 Safety car"):
            t.update(status="cancelled", cancelled_at=now.isoformat())
            cancelled.append(t["title"])
            continue
        dl = datetime.fromisoformat(t["deadline"])
        dl = dl if dl.tzinfo else dl.replace(tzinfo=now.tzinfo)
        new = max(dl + timedelta(days=1), datetime.combine(today + timedelta(days=1), dtime(12, 0), now.tzinfo))
        t["deadline"] = min(new, datetime.combine(today + timedelta(days=1), dtime(23, 59), now.tzinfo)).isoformat()
        t["bailed_from"] = today.isoformat()
        if t.get("mission_day") == today.isoformat():
            t.pop("mission_day", None)
        moved.append(t["title"])
    e = day(save, today)
    e["bailout"] = {"reason": reason, "why": why.strip(), "at": now.isoformat(), "moved": moved}
    return {"moved": moved, "cancelled": cancelled}


def qualify_deadline(save: dict, d: date, tz) -> datetime:
    return datetime.combine(d, dtime(int(cfg(save)["qualify_by"]), 0), tz)


def status(save: dict, now: datetime) -> dict:
    """Read-only view of today, shared by the app, the nagger and the Notion Pit Wall."""
    today = now.date()
    e = peek_day(save, today)
    done_today = finished_on(save, today)
    m = mission(save, today)
    return {
        "rest": is_rest(save, today),
        "bailout": e.get("bailout"),
        "optional": qualify_optional(today),
        "bailouts_left": bailouts_left(save, today),
        "qualified": bool(e.get("qualified")),
        "missed": bool(e.get("q_missed")) or (not e.get("qualified") and not qualify_optional(today)
                                               and now >= qualify_deadline(save, today, now.tzinfo)),
        "deadline": qualify_deadline(save, today, now.tzinfo),
        "start_at": e.get("start_at"),
        "mission": m,
        "mission_done": [t for t in m if t.get("status") in ("done", "redeemed")],
        "done_today": len(done_today),
        "day_streak": save.get("day_streak", 0),
        "pit_stops_left": max(0, cfg(save)["pit_stops_per_week"] - pit_stops_used(save, today)),
    }


def settle(save: dict, now: datetime, bank, make_safety_car) -> list[str]:
    """Apply zero-day and missed-qualifying consequences. Idempotent: safe to call on every load.

    bank(state, delta, reason) and make_safety_car(due: datetime) -> task are supplied by the app.
    """
    c, msgs = cfg(save), []
    today = now.date()
    since = date.fromisoformat(save.setdefault("daily_since", today.isoformat()))
    d = max(since, today - timedelta(days=SETTLE_LOOKBACK_DAYS))
    charged, forgiven = 0, 0
    while d < today:
        e = day(save, d)
        if not e.get("settled"):
            if is_rest(save, d):
                e["settled"] = "rest"
            elif finished_on(save, d):
                save["day_streak"] = save.get("day_streak", 0) + 1
                save["best_day_streak"] = max(save.get("best_day_streak", 0), save["day_streak"])
                e["settled"] = "ok"
            elif charged >= MAX_CHARGED_ZERO_DAYS:
                e["settled"] = "forgiven"
                forgiven += 1
            else:
                charged += 1
                lost = save.get("day_streak", 0)
                save["day_streak"] = 0
                bank(save, -c["zero_day_penalty"], f"💀 Zero day: {d:%a %b %d}")
                save["car"]["condition"] = max(0, save["car"]["condition"] - c["zero_day_damage"])
                save["rival_heat"] = save.get("rival_heat", 0) + 1
                e["settled"] = "zero"
                msgs.append(f"### 💀 ZERO DAY — {d:%A %b %d}\nNothing finished. −{c['zero_day_penalty']} coins, "
                            f"−{c['zero_day_damage']}% car, rivals faster."
                            + (f" Your **{lost}-day streak is dead.**" if lost else ""))
        d += timedelta(days=1)
    if forgiven:
        msgs.append(f"👋 Welcome back. {forgiven} more empty day(s) were forgiven — the comeback starts with "
                    "one small mission today.")

    e = day(save, today)
    if (not is_rest(save, today) and not qualify_optional(today) and not e.get("qualified") and not e.get("q_missed")
            and now >= qualify_deadline(save, today, now.tzinfo)):
        e["q_missed"] = True
        bank(save, -c["qualify_penalty"], "🚦 Missed qualifying")
        save["rival_heat"] = save.get("rival_heat", 0) + 1
        due = max(datetime.combine(today, dtime(int(c["safety_car_hour"]), 0), now.tzinfo),
                  now + timedelta(hours=3))
        due = min(due, datetime.combine(today, dtime(23, 59), now.tzinfo))
        t = make_safety_car(due)
        t["mission_day"] = today.isoformat()
        save["tasks"].append(t)
        e["safety_car"] = t["id"]
        msgs.append(f"### 🚦 MISSED QUALIFYING\nNo mission by {c['qualify_by']}:00. −{c['qualify_penalty']} coins, "
                    f"rivals faster.\n\n🚨 **Safety car deployed:** 30 min of focused work, proof due "
                    f"{due:%I:%M %p}. You can still add your own mission below.")
    return msgs


OUTAGE_DAYS = {"2026-10-28"}  # days the APP was down at the qualifying deadline — the player isn't charged for those


def excuse_outages(save: dict, bank) -> list[str]:
    """Undo a missed-qualifying charge on a day the app itself was unreachable. One-shot per day."""
    msgs = []
    for iso in OUTAGE_DAYS:
        e = save.get("days", {}).get(iso)
        if not e or not e.get("q_missed") or e.get("excused"):
            continue
        e["excused"] = True
        bank(save, cfg(save)["qualify_penalty"], "🛠️ Refund: app was down at qualifying")
        save["rival_heat"] = max(0, save.get("rival_heat", 0) - 1)
        sc = e.get("safety_car")
        save["tasks"] = [t for t in save["tasks"] if not (t["id"] == sc and t["status"] == "open")]
        msgs.append("🛠️ The app was down at the qualifying deadline. That's on the app, not you: the −"
                    f"{cfg(save)['qualify_penalty']} is refunded, the safety car is gone, and locking in still pays "
                    f"+{cfg(save)['qualify_fuel']}.")
    return msgs


def lock_in(save: dict, now: datetime, task_ids: list[str], start_at: str | None, bank) -> str:
    c, today = cfg(save), now.date()
    e = day(save, today)
    first = not e.get("qualified")
    e.update({"qualified": True, "set_at": now.isoformat(), "start_at": start_at or e.get("start_at")})
    for t in save["tasks"]:
        if t["id"] in task_ids:
            t["mission_day"] = today.isoformat()
    if first and (not e.get("q_missed") or e.get("excused")):
        bank(save, c["qualify_fuel"], "⛽ Qualified on time")
        return f"🚦 **Qualified.** +{c['qualify_fuel']} fuel coins. Now go finish it."
    return "🚦 Mission locked in."


def pit_stop(save: dict, now: datetime) -> bool:
    today = now.date()
    if is_rest(save, today) or pit_stops_used(save, today) >= cfg(save)["pit_stops_per_week"]:
        return False
    day(save, today)["pit_stop"] = True
    return True
