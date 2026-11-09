"""
🏆 Seasons: 8-week championships. No Streamlit imports.

Points come from real work first (every finish), then races and streaks. At the end of a season you get a
trophy and a title from your results, rival heat resets, and the top track switches to a new layout.
Cars, paint, parts and coins carry over: a season is a scoreboard, not a reset.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

SEASON_WEEKS = 8
EPOCH = date(2026, 11, 9)  # Monday: season 1 starts here

RACE_POINTS = {1: 10, 2: 6, 3: 4}
FINISH_POINTS = 2
STREAK_POINTS = 3          # per day of your best streak this season
TITLES = [  # (points needed, trophy, title)
    (400, "🏆", "Season Champion"),
    (250, "🥈", "Title Contender"),
    (120, "🥉", "Podium Regular"),
    (40, "🏁", "Full-Season Finisher"),
    (0, "🎖️", "Rookie Season"),
]


def season_of(d: date) -> tuple[int, date, date]:
    """(season number, first day, last day) for a date. Before the epoch counts as season 1."""
    n = max(0, (d - EPOCH).days) // (SEASON_WEEKS * 7) + 1
    start = EPOCH + timedelta(weeks=SEASON_WEEKS * (n - 1))
    return n, start, start + timedelta(weeks=SEASON_WEEKS) - timedelta(days=1)


def _in(ts: str | None, start: date, end: date) -> bool:
    return bool(ts) and start.isoformat() <= ts[:10] <= end.isoformat()


def results(state: dict, n: int) -> dict:
    """What you did in season n: finishes, races, wins, podiums, best streak, points."""
    start = EPOCH + timedelta(weeks=SEASON_WEEKS * (n - 1))
    end = start + timedelta(weeks=SEASON_WEEKS) - timedelta(days=1)
    finishes = sum(1 for t in state.get("tasks", []) if t.get("status") in ("done", "redeemed")
                   and _in(t.get("completed_at"), start, end))
    races = [r for r in state.get("races", []) if _in(r.get("ts"), start, end)]
    wins = sum(1 for r in races if r.get("pos") == 1)
    podiums = sum(1 for r in races if r.get("pos") in (1, 2, 3))
    race_pts = sum(RACE_POINTS.get(r.get("pos"), 0) for r in races)
    sea = state.get("season") or {}
    streak = int(sea.get("best_streak", 0)) if sea.get("n") == n else 0
    pts = finishes * FINISH_POINTS + race_pts + streak * STREAK_POINTS
    return {"n": n, "start": start.isoformat(), "end": end.isoformat(), "finishes": finishes, "races": len(races),
            "wins": wins, "podiums": podiums, "best_streak": streak, "points": pts}


def title_for(points: int) -> tuple[str, str]:
    for need, cup, name in TITLES:
        if points >= need:
            return cup, name
    return TITLES[-1][1], TITLES[-1][2]


def track_streak(state: dict, today: date) -> None:
    """Keep the season's best streak (the app's streak counter only knows 'now')."""
    n, _, _ = season_of(today)
    sea = state.setdefault("season", {"n": n, "best_streak": 0})
    if sea.get("n") == n:
        sea["best_streak"] = max(int(sea.get("best_streak", 0)), int(state.get("streak", 0)))


def rollover(state: dict, today: date) -> list[dict]:
    """Close any finished seasons: award trophies, reset rival heat. Returns the trophies just awarded."""
    n_now, _, _ = season_of(today)
    sea = state.setdefault("season", {"n": n_now, "best_streak": int(state.get("streak", 0))})
    awarded = []
    while int(sea.get("n", n_now)) < n_now:
        n = int(sea["n"])
        r = results(state, n)
        cup, name = title_for(r["points"])
        trophy = {**r, "cup": cup, "title": name, "awarded": today.isoformat()}
        cab = state.setdefault("trophies", [])
        if not any(t.get("n") == n for t in cab):
            cab.append(trophy)
            awarded.append(trophy)
        state["rival_heat"] = 0  # a fresh grid: your old misses don't follow you into the new season
        sea.clear()
        sea.update({"n": n + 1, "best_streak": int(state.get("streak", 0))})
    return awarded


def progress(state: dict, today: date) -> dict:
    """For the Today rail: where you are in the season and what title you're on course for."""
    n, start, end = season_of(today)
    r = results(state, n)
    day = (today - start).days + 1
    total = SEASON_WEEKS * 7
    cup, name = title_for(r["points"])
    nxt = next(((need, c, t) for need, c, t in reversed(TITLES) if need > r["points"]), None)
    return {**r, "day": day, "total": total, "week": (day - 1) // 7 + 1, "left": (end - today).days,
            "frac": day / total, "cup": cup, "title": name,
            "next": {"need": nxt[0] - r["points"], "cup": nxt[1], "title": nxt[2]} if nxt else None}
