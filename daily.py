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

import commitments as C
import shield as SH

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


def booked(save: dict, d: date) -> list[dict]:
    """Roadmap blocks booked for day d (open or done), in time order."""
    iso = d.isoformat()
    return sorted((t for t in save.get("tasks", []) if (t.get("block") or {}).get("date") == iso
                   and t.get("status") in ("open", "done", "redeemed")), key=lambda t: t["block"]["start"])


# ⏱️ Slices: "45 min on Thesis chapter". Time into a big task that counts toward qualifying without pulling the
# task's deadline to today. Done when the focus timer logs that much on it that day (or the task is finished).
# Locked once committed: you can add, never shrink or remove; an unfinished slice costs its missing share at midnight.
SLICE_LENGTHS = [15, 30, 45, 60, 90, 120]
SLICE_PEN_PER_HOUR = 40       # × level factor, for the minutes you didn't log
SLICE_PEN_CAP = 120           # per day
SLICE_COUNTS_MIN = 10         # a slice with at least this much logged keeps the day from being a zero day


def slices(save: dict, d: date) -> list[dict]:
    return peek_day(save, d).get("slices", [])


def slice_logged(save: dict, tid: str, d: date) -> float:
    key = d.isoformat()
    return sum(float(x.get("min", 0)) for x in save.get("focus_log", []) if x.get("task") == tid and x.get("date") == key)


def slice_done(save: dict, sl: dict, d: date) -> bool:
    t = next((t for t in save.get("tasks", []) if t["id"] == sl["tid"]), None)
    if t and t.get("status") in ("done", "redeemed") and (t.get("completed_at") or "")[:10] == d.isoformat():
        return True
    return slice_logged(save, sl["tid"], d) >= sl["min"]


def add_slice(save: dict, d: date, task: dict, mins: int) -> dict:
    """Commit (more) time to a task for day d. Adding to an existing slice grows it; nothing ever shrinks it."""
    e = day(save, d)
    sl = next((x for x in e.setdefault("slices", []) if x["tid"] == task["id"]), None)
    if sl:
        sl["min"] = int(sl["min"]) + int(mins)
    else:
        sl = {"tid": task["id"], "title": task["title"], "min": int(mins)}
        e["slices"].append(sl)
    return sl


def slice_worked(save: dict, d: date) -> bool:
    """Real time went into a slice today: counts as a working day for the streak."""
    return any(slice_done(save, sl, d) or slice_logged(save, sl["tid"], d) >= SLICE_COUNTS_MIN for sl in slices(save, d))


def slice_penalty(save: dict, d: date) -> tuple[int, list[str]]:
    """What day d's unfinished slices cost: the missing minutes at SLICE_PEN_PER_HOUR (× level), capped."""
    total, lines = 0, []
    for sl in slices(save, d):
        if slice_done(save, sl, d):
            continue
        miss = max(0.0, sl["min"] - slice_logged(save, sl["tid"], d))
        pen = round(SLICE_PEN_PER_HOUR * level_factor(save) * miss / 60)
        if pen:
            total += pen
            lines.append(f"{sl['title']}: {sl['min'] - miss:.0f}/{sl['min']} min → −{pen}")
    return min(total, SLICE_PEN_CAP), lines


def qualified(save: dict, d: date) -> bool:
    """Locked in a mission, or booked roadmap time that day (booked work IS a plan for the day)."""
    return bool(peek_day(save, d).get("qualified")) or bool(booked(save, d))


def release_moved(save: dict) -> list[dict]:
    """A roadmap block you moved to another day leaves the mission of the day it was in (it joins its new day's
    mission when that day comes). Returns the blocks that moved off."""
    out = []
    for t in save.get("tasks", []):
        md, bk = t.get("mission_day"), t.get("block") or {}
        if md and bk.get("date") and t.get("status") == "open" and bk["date"] != md:
            t.pop("mission_day", None)
            out.append(t)
    return out


def auto_qualify(save: dict, now: datetime, bank) -> str | None:
    """Today's booked roadmap blocks become today's mission and count as qualifying (+fuel, once). Qualifying
    stays open: you can still lock in more. Blocks booked later in the day join the mission too."""
    today = now.date()
    if is_rest(save, today):
        return None
    bl = [t for t in booked(save, today) if t.get("mission_day") != today.isoformat()]
    if not bl:
        return None
    e = day(save, today)
    if e.get("qualified"):
        for t in bl:
            t["mission_day"] = today.isoformat()
        return None
    lock_in(save, now, [t["id"] for t in bl], bl[0]["block"]["start"], bank)
    e["auto"] = "roadmap"
    c = cfg(save)
    return (f"🗺️ Your booked roadmap time is today's qualifying: {len(bl)} block{'s' * (len(bl) != 1)} locked in, "
            f"first at {datetime.strptime(bl[0]['block']['start'], '%H:%M'):%I:%M %p}".replace(" 0", " ")
            + f" · +{c['qualify_fuel']} fuel. You can still add more to today's mission.")


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
        "qualified": qualified(save, today),
        "booked": booked(save, today),
        "missed": bool(e.get("q_missed")) or (not qualified(save, today) and not qualify_optional(today)
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
            if not is_rest(save, d) and not e.get("slices_settled") and slices(save, d):
                pen, lines = slice_penalty(save, d)
                e["slices_settled"] = True
                if pen:
                    bank(save, -pen, f"⏱️ Unfinished slices: {d:%a %b %d}")
                    msgs.append(f"### ⏱️ Slices not finished — {d:%A %b %d}\n" + "\n".join(f"- {x}" for x in lines)
                                + (f"\n\nTotal −{pen} (capped)" if pen == SLICE_PEN_CAP else ""))
            if is_rest(save, d):
                e["settled"] = "rest"
            elif finished_on(save, d) or slice_worked(save, d) or C.attended_on(save, d):  # 📍 showing up counts
                save["day_streak"] = save.get("day_streak", 0) + 1
                save["best_day_streak"] = max(save.get("best_day_streak", 0), save["day_streak"])
                e["settled"] = "ok"
                if SH.earn_shield(save):
                    msgs.append(f"🛡️ {save['day_streak']}-day streak → you earned a **streak shield** "
                                f"({save['shields']}/{SH.SHIELD_MAX}). It saves the streak from one zero day.")
            elif d.weekday() in WEEKEND:  # weekends are optional: an empty one costs nothing, the streak holds
                e["settled"] = "weekend"
            elif charged >= MAX_CHARGED_ZERO_DAYS:
                e["settled"] = "forgiven"
                forgiven += 1
            else:
                charged += 1
                shielded = SH.use_shield(save)
                lost = 0 if shielded else save.get("day_streak", 0)
                if not shielded:
                    save["day_streak"] = 0
                bank(save, -c["zero_day_penalty"], f"💀 Zero day: {d:%a %b %d}")
                save["car"]["condition"] = max(0, save["car"]["condition"] - c["zero_day_damage"])
                save["rival_heat"] = save.get("rival_heat", 0) + 1
                e["settled"] = "zero"
                msgs.append(f"### 💀 ZERO DAY — {d:%A %b %d}\nNothing finished. −{c['zero_day_penalty']} coins, "
                            f"−{c['zero_day_damage']}% car, rivals faster."
                            + (f" Your **{lost}-day streak is dead.**" if lost else "")
                            + (f" 🛡️ A **streak shield** saved your {save.get('day_streak', 0)}-day streak "
                               f"({save.get('shields', 0)} left)." if shielded else ""))
        d += timedelta(days=1)
    if forgiven:
        msgs.append(f"👋 Welcome back. {forgiven} more empty day(s) were forgiven — the comeback starts with "
                    "one small mission today.")

    e = day(save, today)
    if (not is_rest(save, today) and not qualify_optional(today) and not qualified(save, today) and not e.get("q_missed")
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


SYNC_LOSS_DAYS = {"2026-10-31"}  # days a sync bug threw away your ticks: undone once, see make_good()


def make_good(save: dict, bank, DL) -> list[str]:
    """One-shot repair for a day whose ticks/journal were lost by a sync bug (the app showed an older copy of
    your save and settled the day from it). Refunds that day's penalties, restores the streaks and car, marks
    the dailies done (paid as normal) and lets you re-write that evening's journal for full coins."""
    msgs = []
    done = save.setdefault("made_good", [])
    for iso in SYNC_LOSS_DAYS:
        if iso in done:
            continue
        d = date.fromisoformat(iso)
        e = save.get("days", {}).get(iso)
        if not e or not e.get("settled"):
            continue  # not settled yet: nothing to undo (and today's fixes keep it from happening)
        done.append(iso)
        back, notes = 0, []
        tag_zero, tag_daily = f"💀 Zero day: {d:%a %b %d}", f"({d:%a})"
        for x in save.get("ledger", []):
            r = x.get("reason", "")
            if x.get("delta", 0) < 0 and (r == tag_zero or (r.startswith("🔁 Missed daily") and r.endswith(tag_daily))):
                back -= x["delta"]
                x["refunded"] = True  # no longer counts toward today's damage cap
        save["held"] = [h for h in save.get("held", []) if not (h.get("reason") == tag_zero or (
            h.get("reason", "").startswith("🔁 Missed daily") and h.get("reason", "").endswith(tag_daily)))]
        if e.get("settled") == "zero":
            save["car"]["condition"] = min(100, save["car"]["condition"] + cfg(save)["zero_day_damage"])
            save["rival_heat"] = max(0, save.get("rival_heat", 0) - 1)
            if not save.get("day_streak"):
                save["day_streak"] = save.get("best_day_streak", 0)
            notes += ["car repaired", f"day streak back to {save['day_streak']}"]
        e["settled"] = "weekend" if d.weekday() in WEEKEND else "ok"
        if back:
            bank(save, back, f"🛠️ Refund: sync bug lost {d:%a %b %d}")
        fixed = []
        for h in DL.habits(save):
            if DL.active_on(h, d) and DL.count(save, h["id"], d) < h["target"]:
                prior, k = 0, d - timedelta(days=1)  # the streak it had going in (from the days you claimed)
                while DL.claimed(save, h["id"], k) or (not DL.active_on(h, k) and k >= date.fromisoformat(h["start"])):
                    prior += DL.claimed(save, h["id"], k)
                    k -= timedelta(days=1)
                h["streak"] = max(h.get("streak", 0), prior)
                DL.log(save, d)[h["id"]] = h["target"]
                DL.claim(save, h["id"], d, bank, " (restored)")
                fixed.append(h["name"])
        save.setdefault("late_journal_ok", []).append(iso)
        msgs.append(f"🛠️ Sorry: a sync bug lost your {d:%A} ticks and then charged you for them. "
                    + ", ".join([f"+{back} refunded"] * bool(back) + notes + ([f"{', '.join(fixed)} marked done"]
                                                                              if fixed else []))
                    + f". Your {d:%A} journal didn't survive: write it again in Log → Journal (it pays in full).")
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


# ↩️ Sending a task back off today's mission. Plans change; procrastination shouldn't get a free exit:
#  - the mission can never drop under the qualifying hour (swap something in, or add a slice, first)
#  - free for SEND_BACK_GRACE min after you lock in (fixing a plan you just made), then it costs half the task's
#    penalty and you get SEND_BACK_MAX a day
#  - nothing you've already logged timer time on today, and nothing after SEND_BACK_CUTOFF (the evening is for finishing)
SEND_BACK_GRACE, SEND_BACK_MAX, SEND_BACK_CUTOFF = 30, 2, 18


def mission_minutes(save: dict, d: date, without: str | None = None) -> int:
    tasks = sum(int(t.get("minutes") or 30) for t in mission(save, d) if t["id"] != without
                and t.get("status") in ("open", "done", "redeemed"))
    return tasks + sum(int(s_["min"]) for s_ in slices(save, d))


def send_back_check(save: dict, t: dict, now: datetime) -> tuple[bool, str, int]:
    """(allowed, why not / what it'll cost, cost)."""
    d = now.date()
    e = peek_day(save, d)
    if t.get("mission_day") != d.isoformat() or t.get("status") != "open":
        return False, "Not in today's open mission.", 0
    if any(x.get("task") == t["id"] and x.get("date") == d.isoformat() for x in save.get("focus_log", [])):
        return False, "You've already put timer time into it today: finish it.", 0
    need = min_mission_minutes(save)
    if e.get("qualified") and mission_minutes(save, d, without=t["id"]) < need:
        return False, f"Without it the mission drops under {need} min. Add something (or a ⏱️ slice) first.", 0
    set_at = datetime.fromisoformat(e["set_at"]) if e.get("set_at") else now
    if (now - set_at).total_seconds() <= SEND_BACK_GRACE * 60:
        return True, f"Free: you locked in under {SEND_BACK_GRACE} min ago.", 0
    if now.hour >= SEND_BACK_CUTOFF:
        return False, f"After {SEND_BACK_CUTOFF % 12 or 12} PM the mission is locked: finish it or let it ride.", 0
    used = int(e.get("sent_back", 0))
    if used >= SEND_BACK_MAX:
        return False, f"You've already sent {SEND_BACK_MAX} back today.", 0
    cost = max(5, round(int(t.get("penalty") or 20) * 0.5))
    return True, f"Costs {cost} (half its penalty) · {SEND_BACK_MAX - used - 1} more allowed today.", cost


def send_back(save: dict, t: dict, now: datetime, reason: str, bank) -> tuple[bool, str]:
    ok, why, cost = send_back_check(save, t, now)
    if not ok:
        return False, why
    if not reason.strip():
        return False, "Say why (one line)."
    e = day(save, now.date())
    if cost:
        bank(save, -cost, f"↩️ Sent back: {t['title']}")
        e["sent_back"] = int(e.get("sent_back", 0)) + 1
    e.setdefault("sent_back_log", []).append({"title": t["title"][:80], "why": reason.strip()[:120], "cost": cost,
                                             "at": now.isoformat()})
    t.pop("mission_day", None)
    return True, f"↩️ **{t['title']}** is off today's mission" + (f" (−{cost})." if cost else " (free).")


def pit_stop(save: dict, now: datetime) -> bool:
    today = now.date()
    if is_rest(save, today) or pit_stops_used(save, today) >= cfg(save)["pit_stops_per_week"]:
        return False
    day(save, today)["pit_stop"] = True
    return True
