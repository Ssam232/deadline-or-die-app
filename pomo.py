"""
🍅 Pomodoro / break-at intervals for the focus timer.

A session is a target of WORK minutes. With breaks on, the wall clock runs work → break → work …,
with no break after the last block. Only work minutes are logged, so breaks never inflate the receipt.
"""
from __future__ import annotations

PRESETS = {
    "off": ("No breaks", None),
    "25/5": ("🍅 25 / 5 pomodoro", (25, 5)),
    "50/10": ("50 / 10", (50, 10)),
    "custom": ("Custom break-at…", None),
}


def wall_minutes(target: int, work: int | None, brk: int | None) -> int:
    """Wall-clock length of a session with `target` work minutes."""
    if not work or not brk or target <= work:
        return target
    full_blocks = -(-target // work) - 1  # breaks happen between blocks, not after the last
    return target + full_blocks * brk


def work_done(elapsed: float, work: int | None, brk: int | None) -> float:
    """Work minutes inside `elapsed` wall minutes."""
    if not work or not brk:
        return elapsed
    cycle = work + brk
    full, rest = divmod(elapsed, cycle)
    return full * work + min(rest, work)


def phase(elapsed: float, work: int | None, brk: int | None, target: int) -> tuple[str, float]:
    """('work'|'break'|'done', minutes left in this phase)."""
    if work_done(elapsed, work, brk) >= target:
        return "done", 0.0
    if not work or not brk:
        return "work", target - elapsed
    rest = elapsed % (work + brk)
    if rest < work:
        return "work", min(work - rest, target - work_done(elapsed, work, brk))
    return "break", work + brk - rest


# ── pit in / pit out: breaks start and end when you confirm, not on their own ──
PIT_OVER_MAX = 10  # minutes past a stint that still count as work while you finish a thought (then: walked away?)


def gate(tm: dict, elapsed: float) -> tuple[str, float]:
    """('pit_in'|'pit_out'|'', minutes over), from the pit ins/outs you've actually confirmed.
    pit_in: the stint is up and the break waits for you (that extra time is work, up to PIT_OVER_MAX).
    pit_out: the break is up and work waits for you (that extra time is break)."""
    work, brk, target = tm.get("work"), tm.get("brk"), tm["planned"]
    if not work or not brk or tm.get("flow") or "pins" not in tm:  # (timers started before gates existed: none)
        return "", 0.0
    c, n, m = work + brk, int(tm.get("pins", 0)), int(tm.get("pouts", 0))
    if n > m:  # in the pit: the break ends at n·c on the clock
        return ("pit_out", elapsed - n * c) if elapsed >= n * c else ("", 0.0)
    end = n * c + work  # on track: this stint ends here
    if elapsed >= end and (n + 1) * work < target:
        return "pit_in", elapsed - end
    return "", 0.0


def credited(tm: dict, elapsed: float) -> float:
    """Work minutes to log: the clock's work, plus overruns you kept working before confirming a pit in (capped),
    minus any time sitting in the pit past the break (that isn't work)."""
    work, brk = tm.get("work"), tm.get("brk")
    g, over = gate(tm, elapsed)
    if g == "pit_out":
        return work_done(elapsed - over, work, brk) + tm.get("over_total", 0.0)
    if g == "pit_in":
        return work_done(elapsed - over, work, brk) + tm.get("over_total", 0.0) + min(over, PIT_OVER_MAX)
    return work_done(elapsed, work, brk) + tm.get("over_total", 0.0)


def confirm(tm: dict, elapsed: float) -> str:
    """Tap 'Pit in' / 'Pit out': pull the clock back to the moment that phase should start, so the break (or the
    next stint) runs its full length from now. Returns which one it was."""
    g, over = gate(tm, elapsed)
    if g == "pit_in":
        tm["skipped"] = tm.get("skipped", 0.0) - over * 60
        tm["over_total"] = tm.get("over_total", 0.0) + min(over, PIT_OVER_MAX)
        tm["pins"] = int(tm.get("pins", 0)) + 1
    elif g == "pit_out":
        tm["skipped"] = tm.get("skipped", 0.0) - over * 60
        tm["pouts"] = int(tm.get("pins", 0))
    return g


def label(work: int | None, brk: int | None) -> str:
    return f"break every {work} min ({brk} min)" if work and brk else "no breaks"


# ── pause / skip ──
PAUSE_COST = 2          # coins × pause number: 2, 4, 6, …
PAUSE_LIMIT_MIN = 20    # a pause longer than this ends the session (and logs what you did)


def effective_elapsed(tm: dict, now_ts: float) -> float:
    """Session minutes that count as 'on the clock': wall time minus pauses, plus any skipped break time."""
    from datetime import datetime
    start = datetime.fromisoformat(tm["start"]).timestamp()
    paused = tm.get("paused_total", 0.0)
    if tm.get("paused_at"):
        paused += now_ts - datetime.fromisoformat(tm["paused_at"]).timestamp()
    return max(0.0, (now_ts - start - paused + tm.get("skipped", 0.0)) / 60)


def paused_for(tm: dict, now_ts: float) -> float:
    from datetime import datetime
    return (now_ts - datetime.fromisoformat(tm["paused_at"]).timestamp()) / 60 if tm.get("paused_at") else 0.0


def pause_cost(tm: dict) -> int:
    return PAUSE_COST * (tm.get("pauses", 0) + 1)
