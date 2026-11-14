"""
🏷️ Priority, difficulty and the order you see your tasks in. No Streamlit imports.

Two tags, picked by tapping (no numbers):
  priority    🔥 Must  ·  📌 Should  ·  🌱 Could
  difficulty  🪶 Easy  ·  🧱 Medium  ·  🏔️ Hard      (how hard it feels to start, not how long it takes)

Orders:
  start  ✨ Start here   built for getting going: anything due within 3 h first, then by priority, and inside each
                         priority the lowest-friction task (quick + easy) first, so the first move is a small win
  quick  ⏱️ Quickest     shortest first
  easy   🪶 Easiest      easiest first, then shortest
  prio   🔥 Priority     most important first, then soonest due
  due    ⏰ Due          soonest deadline first
  mine   ✋ My order     the order you arranged yourself
"""
from __future__ import annotations

from datetime import datetime, timedelta

PRIO = {"must": "🔥 Must", "should": "📌 Should", "could": "🌱 Could"}
DIFF = {"easy": "🪶 Easy", "medium": "🧱 Medium", "hard": "🏔️ Hard"}
PRIO_HELP = {"must": "has to happen", "should": "matters, but could slip a day", "could": "nice if it happens"}
DIFF_HELP = {"easy": "no thinking needed", "medium": "takes some focus", "hard": "you've been putting it off"}
MODES = {"start": "✨ Start here", "quick": "⏱️ Quickest", "easy": "🪶 Easiest", "prio": "🔥 Priority",
         "due": "⏰ Due", "mine": "✋ My order"}
_PR = {"must": 0, "should": 1, "could": 2}
_DR = {"easy": 0, "medium": 1, "hard": 2}


def prio(t: dict) -> str:
    return t.get("prio") if t.get("prio") in PRIO else "should"


def diff(t: dict) -> str:
    return t.get("diff") if t.get("diff") in DIFF else "medium"


def chips(t: dict) -> str:
    """The row prefix: only what you've set (an untagged task stays clean)."""
    out = []
    if t.get("prio") in PRIO:
        out.append(PRIO[t["prio"]].split()[0])
    if t.get("diff") in DIFF:
        out.append(DIFF[t["diff"]].split()[0])
    return "".join(out)


def _mins(t: dict) -> int:
    return int(t.get("minutes") or 30)


def _due(t: dict) -> datetime:
    return datetime.fromisoformat(t["deadline"])


def friction(t: dict) -> float:
    """How hard it is to begin: difficulty counts most, length a bit."""
    m = _mins(t)
    size = 0 if m <= 15 else 1 if m <= 30 else 2 if m <= 60 else 3
    return _DR[diff(t)] * 2 + size


def urgent(t: dict, now: datetime) -> bool:
    return _due(t) - now <= timedelta(hours=3)


def rank(tasks: list[dict], mode: str, now: datetime) -> list[dict]:
    if mode == "quick":
        key = lambda t: (_mins(t), _due(t))  # noqa: E731
    elif mode == "easy":
        key = lambda t: (_DR[diff(t)], _mins(t), _due(t))  # noqa: E731
    elif mode == "prio":
        key = lambda t: (_PR[prio(t)], _due(t), friction(t))  # noqa: E731
    elif mode == "due":
        key = lambda t: (_due(t), _PR[prio(t)])  # noqa: E731
    else:  # start
        key = lambda t: (0 if urgent(t, now) else 1, _PR[prio(t)], friction(t), _due(t))  # noqa: E731
    return sorted(tasks, key=key)


def why_first(t: dict, now: datetime) -> str:
    """One line on why this one's on top: it's the nudge to start."""
    m = _mins(t)
    if urgent(t, now):
        left = _due(t) - now
        h, mm = divmod(max(0, int(left.total_seconds() // 60)), 60)
        return f"Due in {f'{h} h ' if h else ''}{mm} min. Do it first, then everything else is calmer."
    if diff(t) == "easy" and m <= 20:
        return f"A {m}-minute easy one: a quick win to get rolling."
    if diff(t) == "hard" and prio(t) == "must":
        return "The hard one that matters. Do it while you're fresh; the rest will feel light after."
    if m <= 15:
        return f"Only {m} minutes. Start it and you're already moving."
    if prio(t) == "must":
        return "It has to happen today. Starting is the hard part: give it 10 minutes."
    return "Lowest friction on the list. Start here and build momentum."


_ROLL = ["🔥 <b>Keep it going:</b>", "💪 <b>Tuff. Next up:</b>", "🚀 <b>On a roll. Next:</b>",
         "⚡ <b>Don't let it cool down:</b>", "😤 <b>Locked in. Next:</b>"]


def lead(done: int, left: int) -> str:
    """The banner's opener: 'Start here' before your first finish, momentum after it."""
    if done <= 0:
        return "👉 <b>Start here:</b>"
    if left == 1:
        return "🏁 <b>Last one:</b>"
    return _ROLL[(done - 1) % len(_ROLL)]


def why_next(t: dict, now: datetime, done: int, left: int) -> str:
    """Why this one's on top, told as a continuation once you're already moving."""
    if done <= 0:
        return why_first(t, now)
    m = _mins(t)
    head = f"{done} down" + (", one to go. Close the day out." if left == 1 else ". ")
    if left == 1:
        return head
    if urgent(t, now):
        return head + why_first(t, now)
    if m <= 15:
        return head + f"Only {m} minutes: bank it while you're warm."
    if diff(t) == "hard":
        return head + "You're warmed up now, which is the best time for the hard one."
    if diff(t) == "easy":
        return head + "An easy one keeps the streak of wins going."
    return head + "Same energy. Start the timer before the momentum fades."
