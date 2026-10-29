"""
🚦 Focus nudges: pushes during your work hours that get you onto the timer.

Queued on ntfy at exact times (alarms.py) and cancelled the moment they'd be pointless:
  • a timer is running (or just ended),     • today's focus goal is hit,
  • it's a rest / pit-stop day,              • nudges are off, or it's the weekend (unless turned on).
Every nudge names one concrete task and a short stint, and carries a ▶️ button that opens the app with the timer
already running (?go=<task>&m=<minutes>) — the whole "decide + start" cost becomes one tap. Ignore them and they get
louder through the day. The tone rotates (progress, rivals, loss, peak hours) so they don't fade into wallpaper.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import daily
import insights as I
import pomo as PM
import quickparse as Q

DEFAULTS = {"nudge_every": 90, "nudge_start": 9, "nudge_end": 18, "nudge_weekends": False, "focus_goal": 180}
EVERY_OPTS = {0: "Off", 120: "Every 2 h", 90: "Every 90 min", 60: "Every hour"}
GRACE_AFTER = timedelta(minutes=40)   # no nudge this soon after a session ends
RIVALS = ["Tomorrow Tom", "Doomscroll Dan", "Snooze Button", "Night-Before Nate", "Just-One-Episode"]


def cfg(save: dict) -> dict:
    s = save.get("settings", {})
    return {k: s.get(k, v) for k, v in DEFAULTS.items()}


def _parse(s: str, tz) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=tz)


def focus_on(save: dict, d: date) -> float:
    return sum(x.get("min", 0) for x in save.get("focus_log", []) if x.get("date") == d.isoformat())


def _last_end(save: dict, d: date, tz) -> datetime | None:
    ends = []
    for x in save.get("focus_log", []):
        if x.get("date") == d.isoformat() and x.get("start"):
            try:
                ends.append(_parse(x["start"], tz) + timedelta(minutes=x.get("min", 0)))
            except ValueError:
                pass
    return max(ends) if ends else None


def timer_busy_until(save: dict, now: datetime) -> datetime | None:
    """When the running timer (if any) should be over, plus grace — nudges before then are pointless."""
    tm = save.get("timer")
    if not tm:
        return None
    try:
        start = _parse(tm["start"], now.tzinfo)
    except (KeyError, ValueError):
        return None
    wall = PM.wall_minutes(tm.get("planned", 25), tm.get("work"), tm.get("brk"))
    paused = tm.get("paused_total", 0.0)
    if tm.get("paused_at"):
        paused += max(0.0, (now - _parse(tm["paused_at"], now.tzinfo)).total_seconds())
    return start + timedelta(minutes=wall, seconds=paused - tm.get("skipped", 0.0)) + GRACE_AFTER


def slots(save: dict, d: date, tz) -> list[datetime]:
    c = cfg(save)
    every = int(c["nudge_every"] or 0)
    if not every:
        return []
    a, b = int(c["nudge_start"]), int(c["nudge_end"])
    rng = random.Random(f"nudge-{d.isoformat()}")
    out, m = [], a * 60 + 20
    while m <= b * 60 - 20:
        jm = min(b * 60 - 15, max(a * 60 + 5, m + rng.randint(-12, 12)))  # irregular = harder to tune out
        out.append(datetime.combine(d, datetime.min.time(), tz) + timedelta(minutes=jm))
        m += every
    return out


def _fmt_min(m: float) -> str:
    m = int(round(m))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def build(save: dict, now: datetime, prof: dict | None, mk) -> list[dict]:
    """Nudge alarms for today and tomorrow. mk(key, at, title, msg, prio, tags, wanted, go) builds one alarm."""
    out, tz = [], now.tzinfo
    if "tasks" not in save:
        return out
    c = cfg(save)
    busy = timer_busy_until(save, now)
    for d in (now.date(), now.date() + timedelta(days=1)):
        e = daily.peek_day(save, d)
        off_day = daily.is_rest(save, d) or (d.weekday() >= 5 and not c["nudge_weekends"])
        done = focus_on(save, d) if d == now.date() else 0.0
        goal_hit = done >= c["focus_goal"]
        last = _last_end(save, d, tz) if d == now.date() else None
        zero = not daily.finished_on(save, d)
        pen = daily.cfg(save)["zero_day_penalty"]

        def wanted(at):
            return (not off_day and not goal_hit and not (busy and at < busy)
                    and not (last and at < last + GRACE_AFTER))

        # 🚦 lights out at the start time you promised when you locked in
        if e.get("start_at"):
            hh, mm = (int(x) for x in e["start_at"].split(":"))
            at = datetime.combine(d, datetime.min.time(), tz).replace(hour=hh, minute=mm)
            pick = Q.pick_next(save.get("tasks", []), at, deep_hour=I.in_peak(prof, at.hour))
            L = Q.session_length(pick) if pick else 25
            out.append(mk(("lights", d, e["start_at"]), at, "🚦 LIGHTS OUT",
                          f"You said you'd start at {at:%I:%M %p}".replace(" 0", " ") +
                          (f". First up: {pick['title']} — {L} min." if pick else ". Tap ▶️ and go."),
                          5, ["checkered_flag"], wanted(at) and done == 0, (pick["id"] if pick else "new", L)))
        for i, at in enumerate(slots(save, d, tz)):
            pick = Q.pick_next(save.get("tasks", []), at, deep_hour=I.in_peak(prof, at.hour))
            L = Q.session_length(pick) if pick else 25
            task = pick["title"] if pick else "a focus session"
            idle = (f"Nothing on the timer since {last:%I:%M %p}".replace(" 0", " ") if last
                    else "No focus yet today")
            rng = random.Random(f"{d}-{i}")
            kind = (i + d.toordinal()) % 5
            if kind == 0:
                title, msg = f"▶️ {L} min: {task}", f"{idle}. Tap ▶️ Start — the clock is your proof."
            elif kind == 1:
                title = f"⏱️ {_fmt_min(done)} of {_fmt_min(c['focus_goal'])} today"
                msg = f"One {L}-min stint on {task} → {_fmt_min(done + L)}. Start it."
            elif kind == 2:
                peak = I.in_peak(prof, at.hour)
                title = "🧠 Your peak hour" if peak else "🚦 Green light"
                msg = f"{task}. Phone face-down, {L} minutes, go." + (
                    " This is when you do your best work — don't spend it scrolling." if peak else "")
            elif kind == 3:
                title = f"🏎️ {rng.choice(RIVALS)} is pulling away"
                msg = f"{idle}. {task} — {L} min closes the gap."
            else:
                title = "⚠️ Zero finishes today" if zero and d == now.date() else "🔥 Keep the car moving"
                msg = (f"Midnight costs {pen} coins if nothing gets done. {task} is {L} min." if zero
                       else f"Momentum is the whole game. {task}, {L} min.")
            ignored = sum(1 for p in slots(save, d, tz)[:i] if p < at and wanted(p))
            prio = 3 if ignored == 0 else 4 if ignored < 3 or done > 0 else 5
            out.append(mk(("nudge", d, i), at, title, msg, prio, ["racing_car"], wanted(at),
                          (pick["id"] if pick else "new", L)))
    return out
