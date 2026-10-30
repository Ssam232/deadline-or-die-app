"""
📊 Analytics that feed the engine.

Reads your history and works out when you actually work. Hours come from ⏱️ focus sessions only (claiming
a task or ticking a daily isn't working); finished tasks feed the counts and categories.
The game uses it:
  • ⏱️ focus challenges + ⚡ live events land in your DEAD ZONES — hours you're up and about but not
    working (i.e. goofing off) — because that's where a nudge buys the most real work.
  • 💡 phone "ads" are timed into dead zones too; the morning briefing lands an hour before you usually start.
  • 🎲 "just tell me what to do" hands you deep work in your peak hours and quick wins outside them.

Everything is computed from history BEFORE today, so the app and the phone nagger always agree on today's
schedule, and today's work can't reshuffle today's surprises.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

MIN_ACTIVE_DAYS = 5   # the engine only starts steering after this much history
WINDOW_DAYS = 28


def _dt(s: str | None, tz) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s)
    return (d.replace(tzinfo=tz) if d.tzinfo is None else d).astimezone(tz)


def _spread(hour_min, wd_hour, start: datetime, minutes: float) -> None:
    """Add `minutes` of work starting at `start`, split across the clock hours it covers."""
    t, left = start, minutes
    while left > 0.01:
        chunk = min(left, 60 - t.minute - t.second / 60)
        hour_min[t.hour] += chunk
        wd_hour[t.weekday()][t.hour] += chunk
        t = (t + timedelta(minutes=chunk)).replace(second=0, microsecond=0)
        left -= chunk


def history(save: dict, as_of: date, tz, days: int = WINDOW_DAYS) -> dict:
    lo = as_of - timedelta(days=days)
    hour_min = [0.0] * 24
    wd_hour = [[0.0] * 24 for _ in range(7)]
    active, first_hour = set(), {}
    focused_tasks = set()
    focus_min = 0.0
    for x in save.get("focus_log", []):
        s = _dt(x.get("start"), tz)
        d = date.fromisoformat(x["date"])
        if not lo <= d < as_of:
            continue
        focus_min += x["min"]
        focused_tasks.add(x.get("task"))
        active.add(d)
        if s:
            _spread(hour_min, wd_hour, s, x["min"])
            first_hour[d] = min(first_hour.get(d, 24), s.hour)
    cat_min, done, on_time, failed = defaultdict(float), [], 0, 0
    for t in save.get("tasks", []):
        if t.get("status") in ("done", "redeemed"):
            c = _dt(t.get("completed_at"), tz)
            if not c or not lo <= c.date() < as_of:
                continue
            mins = max(t.get("minutes") or 30, t.get("focus_min") or 0)
            cat_min[t.get("category") or "deep"] += mins
            done.append(t)
            active.add(c.date())
            if t.get("status") == "done" and c <= _dt(t["deadline"], tz):
                on_time += 1
            # when you WORK comes from timer sessions only: claiming a task or ticking a daily isn't working
        elif t.get("status") == "failed":
            f = _dt(t.get("failed_at"), tz)
            if f and lo <= f.date() < as_of:
                failed += 1
    weeks = []
    for w in range(7, -1, -1):
        ws = as_of - timedelta(days=as_of.weekday() + 7 * w)
        n = 0
        for t in save.get("tasks", []):
            c = _dt(t.get("completed_at"), tz)
            if t.get("status") in ("done", "redeemed") and c and ws <= c.date() < ws + timedelta(days=7):
                n += 1
        weeks.append((ws, n))
    return {"hour_min": hour_min, "wd_hour": wd_hour, "active_days": len(active), "cat_min": dict(cat_min),
            "done": len(done), "on_time": on_time, "failed": failed, "focus_min": focus_min, "weeks": weeks,
            "first_hours": sorted(first_hour.values()), "days": days}


def profile(save: dict, as_of: date, tz) -> dict:
    h = history(save, as_of, tz)
    hm = h["hour_min"]
    total = sum(hm)
    ready = h["active_days"] >= MIN_ACTIVE_DAYS and total >= 120
    # your working day: the hours holding the middle 90% of your work, kept to a sane 8:00–22:00
    win = (9, 20)
    if total:
        cum, lo_h, hi_h = 0.0, None, None
        for hr in range(24):
            cum += hm[hr]
            if lo_h is None and cum >= 0.05 * total:
                lo_h = hr
            if hi_h is None and cum >= 0.95 * total:
                hi_h = hr
        win = (max(8, min(lo_h, 12)), min(22, max(hi_h + 1, 15)))
    inside = list(range(win[0], win[1]))
    peak = sorted(sorted(inside, key=lambda x: -hm[x])[:3]) if total else []
    top = max(hm[x] for x in inside) if total else 0
    dead = sorted(sorted((x for x in inside if x not in peak), key=lambda x: hm[x])[:3]) if total else []
    fh = h["first_hours"]
    usual_start = fh[len(fh) // 2] if fh else None
    # 30-min slot weights for challenges (9:00–19:00): low activity → high weight (1×–4×)
    slot_w = {}
    for m in range(9 * 60, 19 * 60 + 1, 30):
        hr = m // 60
        if not ready:
            slot_w[m] = 1.0
        elif win[0] <= hr < win[1]:
            slot_w[m] = 1.0 + 3.0 * (1 - (hm[hr] / top if top else 0))
        else:
            slot_w[m] = 0.5  # outside your day: rarely
    return {**h, "ready": ready, "window": win, "peak": peak, "dead": dead, "usual_start": usual_start,
            "slot_w": slot_w, "total_min": total}


def hour_weight(prof: dict | None, hour: int) -> float:
    """Weight for scheduling a nudge at `hour` (used by events + phone ads)."""
    if not prof or not prof.get("ready"):
        return 1.0
    return prof["slot_w"].get(hour * 60, prof["slot_w"].get(hour * 60 - 30, 1.0)) if 9 <= hour <= 19 else 0.5


def in_peak(prof: dict | None, hour: int) -> bool:
    return bool(prof and prof.get("ready") and hour in prof["peak"])


def brief_hour(prof: dict | None, default: int) -> int:
    if prof and prof.get("ready") and prof["usual_start"] is not None:
        return max(7, min(10, prof["usual_start"] - 1))
    return default


def fmt_hours(hours: list[int]) -> str:
    def f(h):
        return datetime(2000, 1, 1, h).strftime("%I %p").lstrip("0")
    return ", ".join(f"{f(h)}–{f((h + 1) % 24)}" for h in hours) or "—"
