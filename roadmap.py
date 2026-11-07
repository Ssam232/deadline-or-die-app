"""
🗺️ Roadmaps: a long-term goal broken into stages (which can nest) and scheduled work blocks.

goal["nodes"] = [{"id", "title", "parent": None | stage id, "paid": bool}]   ← stages (multi-level)
A work block is an ordinary task (so proof, timer, alarms and the board all just work) with:
    task["goal_id"] = goal id, task["node"] = stage id or None (straight under the goal),
    task["block"] = {"date": "YYYY-MM-DD", "start": "HH:MM", "minutes": int}, task["scheduled"] = start time.
Old-style milestones (goal tasks without "node") hang straight off the goal.

Rewards: every block pays like any task (small) · a cleared stage pays a bonus · the whole goal pays big.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

STAGE_BASE, STAGE_PER_BLOCK, STAGE_MAX = 10, 5, 60
GOAL_BASE, GOAL_PER_BLOCK, GOAL_MAX = 150, 15, 450
DONE = ("done", "redeemed")


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def stages(g: dict) -> list[dict]:
    return g.setdefault("nodes", [])


def add_stage(g: dict, title: str, parent: str | None) -> dict:
    n = {"id": new_id(), "title": title.strip(), "parent": parent or None, "paid": False}
    stages(g).append(n)
    return n


def children(g: dict, parent: str | None) -> list[dict]:
    return [n for n in stages(g) if n.get("parent") == parent]


def descendants(g: dict, sid: str) -> set[str]:
    out, todo = {sid}, [sid]
    while todo:
        cur = todo.pop()
        for n in children(g, cur):
            if n["id"] not in out:
                out.add(n["id"])
                todo.append(n["id"])
    return out


def depth(g: dict, sid: str | None) -> int:
    d, seen = 0, set()
    by = {n["id"]: n for n in stages(g)}
    while sid and sid in by and sid not in seen:
        seen.add(sid)
        sid = by[sid].get("parent")
        d += 1
    return d


def goal_tasks(g: dict, tasks: list[dict]) -> list[dict]:
    return [t for t in tasks if t.get("goal_id") == g["id"] and not t.get("abandoned") and t["status"] != "cancelled"]


def stage_tasks(g: dict, tasks: list[dict], sid: str) -> list[dict]:
    ids = descendants(g, sid)
    return [t for t in goal_tasks(g, tasks) if t.get("node") in ids]


def progress(ts: list[dict]) -> tuple[int, int]:
    return sum(t["status"] in DONE for t in ts), len(ts)


def stage_bonus(n_blocks: int) -> int:
    return min(STAGE_MAX, STAGE_BASE + STAGE_PER_BLOCK * n_blocks)


def goal_bonus(g: dict, tasks: list[dict]) -> int:
    n = len(goal_tasks(g, tasks))
    return min(GOAL_MAX, GOAL_BASE + (GOAL_PER_BLOCK * max(0, n - 3) if stages(g) else 0))


def cleared(g: dict, tasks: list[dict], sid: str) -> bool:
    d, n = progress(stage_tasks(g, tasks, sid))
    return n > 0 and d == n


def settle(goals: list[dict], tasks: list[dict]) -> list[tuple[dict, dict, int]]:
    """Stages that just got cleared (every block under them done) and haven't paid yet → (goal, stage, bonus).
    Marks them paid; the caller banks the coins."""
    out = []
    for g in goals:
        for n in stages(g):
            if not n.get("paid") and cleared(g, tasks, n["id"]):
                n["paid"] = True
                out.append((g, n, stage_bonus(len(stage_tasks(g, tasks, n["id"])))))
    return out


def remove_stage(g: dict, tasks: list[dict], sid: str) -> bool:
    """Only empty stages (no blocks, no sub-stages) can go."""
    if children(g, sid) or any(t.get("node") == sid for t in goal_tasks(g, tasks)):
        return False
    g["nodes"] = [n for n in stages(g) if n["id"] != sid]
    return True


def move_options(g: dict, sid: str) -> list[dict]:
    """Stages this one could feed into without making a loop."""
    bad = descendants(g, sid)
    return [n for n in stages(g) if n["id"] not in bad]


def update_stage(g: dict, sid: str, title: str | None = None, parent: str | None | bool = False) -> bool:
    n = next((x for x in stages(g) if x["id"] == sid), None)
    if not n:
        return False
    if title:
        n["title"] = title.strip()
    if parent is not False:
        if parent and parent in descendants(g, sid):
            return False  # would loop back into itself
        n["parent"] = parent or None
    return True


def delete_stage(g: dict, tasks: list[dict], sid: str) -> int:
    """Remove a stage; its blocks and sub-stages move up to where it fed into. Returns how many things moved."""
    n = next((x for x in stages(g) if x["id"] == sid), None)
    if not n:
        return 0
    up, moved = n.get("parent"), 0
    for c in children(g, sid):
        c["parent"] = up
        moved += 1
    for t in goal_tasks(g, tasks):
        if t.get("node") == sid:
            t["node"] = up
            moved += 1
    g["nodes"] = [x for x in stages(g) if x["id"] != sid]
    return moved


def block_days(first: date, days: int, skip_weekends: bool) -> list[date]:
    out, d = [], first
    while len(out) < days:
        if not (skip_weekends and d.weekday() >= 5):
            out.append(d)
        d += timedelta(days=1)
    return out


def block_fields(day: date, start: str, minutes: int, tz) -> dict:
    """What turns a task into a scheduled block: starts at `start` on `day`, due by the end of that day."""
    hh, mm = (int(x) for x in start.split(":"))
    at = datetime.combine(day, datetime.min.time(), tz).replace(hour=hh, minute=mm)
    end_of_day = datetime.combine(day, datetime.min.time(), tz).replace(hour=23, minute=59)
    return {"block": {"date": day.isoformat(), "start": f"{hh:02d}:{mm:02d}", "minutes": int(minutes)},
            "scheduled": at.isoformat(), "scheduled_time": True, "deadline": end_of_day.isoformat()}


def block_at(t: dict, tz) -> datetime | None:
    s = t.get("scheduled") if t.get("block") else None
    if not s:
        return None
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=tz)


# ── the flow chart ──
C = {"done": "#2ec4b6", "open": "#3a3f4b", "today": "#f5c518", "failed": "#e10600", "text": "#ece8df",
     "muted": "#8b909c", "edge": "#4a505c", "stage": "#1b1f27", "goal": "#141821"}


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _fmt_block(t: dict, tz) -> str:
    at = block_at(t, tz)
    if at:
        out = f"{at:%a %b} {at.day} · {at:%I:%M %p}".replace(" 0", " ") + f" · {t['block']['minutes']}m"
        if t.get("own_deadline"):
            dl = datetime.fromisoformat(t["own_deadline"])
            out += f" · due {dl:%a %b} {dl.day}"
        return out
    dl = datetime.fromisoformat(t["deadline"])
    return f"due {dl:%a %b} {dl.day}"


def dot(g: dict, tasks: list[dict], now: datetime, accent: str = "#f5c518") -> str:
    """Left → right: blocks flow into stages, stages into bigger stages, everything into the goal (🏁)."""
    tz = now.tzinfo
    gts = goal_tasks(g, tasks)
    d_all, n_all = progress(gts)
    lines = ["digraph G {", 'rankdir=LR; bgcolor="transparent"; nodesep=0.25; ranksep=0.55; pad=0.15;',
             f'node [fontname="Helvetica" fontsize=11 fontcolor="{C["text"]}" shape=box style="rounded,filled" '
             f'penwidth=1.4 margin="0.14,0.07"];',
             f'edge [color="{C["edge"]}" arrowsize=0.6 penwidth=1.2];']
    pct = int(100 * d_all / n_all) if n_all else 0
    lines.append(f'goal [label={_q("🏁 " + g["title"] + chr(10) + f"{d_all}/{n_all} · {pct}%")} '
                 f'fillcolor="{C["goal"]}" color="{C["done"] if n_all and d_all == n_all else accent}" '
                 f'penwidth=2.4 fontsize=13];')
    for n in stages(g):
        d, tot = progress(stage_tasks(g, tasks, n["id"]))
        full = tot and d == tot
        col = C["done"] if full else accent if d else C["edge"]
        label = ("✅ " if full else "") + n["title"] + "\n" + (f"{d}/{tot} done" if tot else "no blocks yet")
        lines.append(f's_{n["id"]} [label={_q(label)} fillcolor="{C["stage"]}" color="{col}"];')
        lines.append(f's_{n["id"]} -> {"s_" + n["parent"] if n.get("parent") else "goal"} '
                     f'[color="{C["done"] if full else C["edge"]}"];')
    for t in sorted(gts, key=lambda t: t.get("scheduled") or t["deadline"]):
        st_ = t["status"]
        when = block_at(t, tz) or datetime.fromisoformat(t["deadline"])
        today = st_ == "open" and when.date() == now.date()
        fill = {"done": "#12312f", "redeemed": "#12312f", "failed": "#3a1214"}.get(st_, "#1b1f27")
        col = C["done"] if st_ in DONE else C["failed"] if st_ == "failed" else C["today"] if today else C["open"]
        icon = "✅ " if st_ in DONE else "💀 " if st_ == "failed" else "▶ " if today else ""
        label = icon + t["title"] + "\n" + _fmt_block(t, tz)
        lines.append(f't_{t["id"]} [label={_q(label)} fillcolor="{fill}" color="{col}" fontsize=10 '
                     f'fontcolor="{C["text"] if st_ == "open" else C["muted"]}"];')
        parent = f's_{t["node"]}' if t.get("node") and any(n["id"] == t["node"] for n in stages(g)) else "goal"
        lines.append(f't_{t["id"]} -> {parent} [color="{C["done"] if st_ in DONE else C["edge"]}"];')
    lines.append("}")
    return "\n".join(lines)
