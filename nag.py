"""
📣 The phone nagger. GitHub Actions runs this every 30 minutes.

It reads your save from Notion and pushes to your phone through ntfy:
  ≤24h  ⏱️ heads-up                         (normal)
  ≤6h   🟡 "start for 10 minutes"           (high)
  ≤2h   🔴 red zone — repeats every hour    (max)
  ≤30m  ☠️ final warning — repeats          (max, breaks quiet hours)
  miss  💀 DNF + rival taunt                 (max, breaks quiet hours)
plus a morning briefing, an evening "nothing finished today" check, and rust warnings.
It remembers what it already sent in the "📣 Deadline or Die — Nagger" Notion page.

Env: NOTION_TOKEN, NOTION_PARENT_PAGE, NTFY_TOPIC, [APP_URL, DOD_TZ, QUIET_HOURS=23-7, BRIEF_HOUR=8, EVENING_HOUR=20]
"""
from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from notify import push
from notion_store import Notion, NotionError, due_to_dt, ensure_workspace, load_json, pull_rows, save_json, update_dashboard

TZ = ZoneInfo(os.getenv("DOD_TZ", "America/Edmonton"))
QUIET_HOURS = os.getenv("QUIET_HOURS", "23-7")
BRIEF_HOUR = int(os.getenv("BRIEF_HOUR", "8"))
EVENING_HOUR = int(os.getenv("EVENING_HOUR", "20"))
DANGER_DAYS = {1, 2}  # Tue/Wed

STAGES = [(24 * 60, 1), (6 * 60, 2), (2 * 60, 3), (30, 4)]  # minutes left → stage
REPEAT_EVERY = {3: 55, 4: 25}                                # minutes between repeats in the red zone
STALE_MISS = timedelta(hours=12)                             # don't announce ancient misses

RIVALS = ["Tomorrow Tom", "Doomscroll Dan", "Snooze Button", "Night-Before Nate", "Just-One-Episode"]
TAUNTS = [
    "Tomorrow Tom: \"There's always tomorrow, right {name}?\"",
    "Doomscroll Dan just lapped you. He didn't even look up from his phone.",
    "Night-Before Nate is pocketing your coins. Thanks for the fuel.",
    "Just-One-Episode: \"Told you we had time.\"",
    "Snooze Button: \"Five more minutes. Then five more. Then the deadline.\"",
]
REPEATS = [
    "This will keep buzzing. You know exactly how to make it stop.",
    "Still not started? Doomscroll Dan is lapping you.",
    "Ten minutes. Start a timer. Go.",
    "Reading notifications instead of working. Bold strategy.",
    "Every buzz is Tomorrow Tom laughing.",
    "Future you is going to be so annoyed at present you.",
]


def stage_of(mins_left: float) -> int:
    if mins_left < 0:
        return 5
    s = 0
    for limit, stage in STAGES:
        if mins_left <= limit:
            s = stage
    return s


def in_quiet(hour: int) -> bool:
    a, b = (int(x) for x in QUIET_HOURS.split("-"))
    return (hour >= a or hour < b) if a > b else (a <= hour < b)


def fmt_left(mins: float) -> str:
    mins = int(mins)
    if mins >= 60:
        h, m = divmod(mins, 60)
        return f"{h}h {m:02d}m"
    return f"{mins} min"


def parse_dt(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def collect(save: dict, rows: list[dict]) -> list[dict]:
    out = []
    for t in save.get("tasks", []):
        if t.get("status") == "open":
            out.append({"key": t["id"], "title": t["title"], "deadline": parse_dt(t["deadline"]),
                        "reward": t["reward"], "penalty": t["penalty"], "consequence": t.get("consequence", ""),
                        "unsynced": False})
    known = {t.get("sync_page") for t in save.get("tasks", [])}
    for r in rows:  # rows added in Notion that the app hasn't pulled in yet still count
        if not r["app_id"] and r["page_id"] not in known and r["due"] and r["status"] in (None, "Open"):
            out.append({"key": r["page_id"], "title": r["title"] or "(untitled)", "deadline": due_to_dt(r["due"], TZ),
                        "reward": 45, "penalty": 35, "consequence": r["consequence"], "unsynced": True})
    return out


def message(stage: int, t: dict, mins: float, ctx: dict, repeat: bool) -> tuple[str, str, int, list[str]]:
    name, streak = ctx["name"], ctx["streak"]
    cons = f"\nIf you miss: {t['consequence']}" if t["consequence"] else ""
    lock = "\n(Added in Notion — open the app to lock it in.)" if t["unsynced"] else ""
    if stage == 1:
        return (f"⏱️ Due in {fmt_left(mins)}",
                f"{t['title']}\n+{t['reward']} coins on the table. Finish 6h+ early for a bonus.{lock}",
                3, ["stopwatch"])
    if stage == 2:
        return ("🟡 6 hours left",
                f"{t['title']}\nOpen it. Work 10 minutes. That's all. Your {streak}-streak is riding on it.{lock}",
                4, ["warning"])
    if stage == 3:
        extra = f"\n{random.choice(REPEATS)}" if repeat else ""
        return (f"🔴 {fmt_left(mins)} LEFT",
                f"{t['title']}\n−{t['penalty']} coins · −15% car · streak {streak} gone.{cons}{extra}{lock}",
                5, ["rotating_light"])
    if stage == 4:
        extra = f"\n{random.choice(REPEATS)}" if repeat else ""
        return (f"☠️ {fmt_left(mins)}. FINAL WARNING.",
                f"{t['title']}\nSubmit proof NOW or {random.choice(RIVALS)} takes your coins.{cons}{extra}",
                5, ["skull"])
    return (f"💀 DNF: {t['title']}",
            f"−{t['penalty']} coins. −15% car. Streak reset.\n{random.choice(TAUNTS).format(name=name)}{cons}\n"
            f"Finish it within 72h to claw back half.",
            5, ["skull"])


def run(n: Notion, parent: str, topic: str, app_url: str | None, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(TZ)
    ids = ensure_workspace(n, parent)
    save = load_json(n, ids["save_page"]) or {}
    mem = load_json(n, ids["nag_page"]) or {}
    mem.setdefault("tasks", {})
    rows = pull_rows(n, ids["tasks_db"])
    ctx = {"name": save.get("settings", {}).get("player_name") or "driver", "streak": save.get("streak", 0)}
    quiet, today, sent = in_quiet(now.hour), now.date().isoformat(), []

    def send(title, msg, prio, tags):
        push(topic, title, msg, prio, tags, click=app_url)
        sent.append(title)

    tasks = collect(save, rows)
    for t in tasks:
        mins = (t["deadline"] - now).total_seconds() / 60
        stg = stage_of(mins)
        m = mem["tasks"].get(t["key"], {"stage": 0, "last": None})
        if stg == 0 or (stg == 5 and m["stage"] >= 5):
            continue
        if stg == 5 and now - t["deadline"] > STALE_MISS:
            mem["tasks"][t["key"]] = {"stage": 5, "last": now.isoformat()}
            continue
        last = parse_dt(m["last"]) if m.get("last") else None
        new_stage = stg > m["stage"]
        repeat = (not new_stage and stg in REPEAT_EVERY and last is not None
                  and (now - last).total_seconds() / 60 >= REPEAT_EVERY[stg])
        if not (new_stage or repeat) or (quiet and stg < 4):
            continue
        send(*message(stg, t, mins, ctx, repeat))
        mem["tasks"][t["key"]] = {"stage": stg, "last": now.isoformat()}

    open_keys = {t["key"] for t in tasks}
    mem["tasks"] = {k: v for k, v in mem["tasks"].items() if k in open_keys}

    if not quiet and now.hour >= BRIEF_HOUR and mem.get("brief") != today:
        mem["brief"] = today
        upcoming = sorted((t for t in tasks if timedelta(0) < t["deadline"] - now < timedelta(hours=48)),
                          key=lambda t: t["deadline"])
        lines = [f"• {t['deadline']:%a %I:%M %p} — {t['title']}" for t in upcoming[:6]]
        body = ("Next 48h:\n" + "\n".join(lines)) if lines else (
            "Nothing on the board. Add one deadline — the car needs fuel." if not tasks
            else "Nothing due in the next 48h. Get ahead: early finishes pay +25%.")
        body += (f"\n\n🪙 {save.get('coins', 0)} · 🔥 streak {ctx['streak']} · "
                 f"🔧 car {save.get('car', {}).get('condition', 100)}%")
        if now.weekday() in DANGER_DAYS:
            body += "\n\n⚠️ Danger day. No one's watching you today — that's exactly why it counts. +20% on everything."
        send(f"🏁 Morning, {ctx['name']}", body, 3, ["checkered_flag"])

    if not quiet and now.hour >= EVENING_HOUR and mem.get("evening") != today:
        mem["evening"] = today
        done_today = any((t.get("completed_at") or "")[:10] == today for t in save.get("tasks", []))
        if tasks and not done_today:
            send("🌙 Nothing finished today",
                 f"{len(tasks)} open. One small one before bed keeps the streak alive and the rust off. "
                 f"Tomorrow Tom is already smiling.", 4, ["crescent_moon"])

    last_done = save.get("last_done_date")
    if last_done and not quiet and mem.get("rust") != today:
        idle = (now.date() - date.fromisoformat(last_done)).days
        if idle >= 2:
            mem["rust"] = today
            send("🟫 Your car is rusting",
                 f"{idle} days without finishing anything. −4% condition a day until you do. "
                 f"Rival heat: {save.get('rival_heat', 0)}.", 4, ["wrench"])

    save_json(n, ids["nag_page"], mem)
    if ids.get("dashboard") and save:
        try:  # keeps the Notion countdowns fresh even when the app isn't opened
            update_dashboard(n, ids["dashboard"], save, TZ, app_url)
        except NotionError as e:
            print(f"Dashboard update failed: {e}")
    return sent


def main() -> int:
    missing = [k for k in ("NOTION_TOKEN", "NOTION_PARENT_PAGE", "NTFY_TOPIC") if not os.getenv(k)]
    if missing:
        print(f"Missing secrets: {', '.join(missing)}")
        return 1
    sent = run(Notion(os.environ["NOTION_TOKEN"]), os.environ["NOTION_PARENT_PAGE"], os.environ["NTFY_TOPIC"],
               os.getenv("APP_URL") or None)
    print(f"Sent {len(sent)} push(es): {sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
