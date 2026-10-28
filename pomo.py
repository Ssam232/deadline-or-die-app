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
