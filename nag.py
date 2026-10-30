"""
📣 The phone nagger. GitHub Actions runs this every 10 minutes (when GitHub feels like it).

Exact-time alarms (prayers, deadline countdowns, qualifying, dailies/zero-day last calls) are queued on ntfy by
alarms.py; this script re-syncs them as a backup and handles everything else.

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

import daily
import dailies as DL
import alarms as AL
import events as EV
import insights as I
import locks as LK
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


def daily_nags(save: dict, mem: dict, now: datetime, quiet: bool) -> list[tuple]:
    """Hunt empty days: qualifying countdown, missed qualifying, lights-out at the promised start, zero-day ladder."""
    if not save or "tasks" not in save:
        return []
    stt, c = daily.status(save, now), daily.cfg(save)
    if stt["rest"]:
        return []
    dm = mem.setdefault("day", {})
    if dm.get("date") != now.date().isoformat():
        dm.clear()
        dm["date"] = now.date().isoformat()
    out = []
    if not stt["qualified"] and not stt["optional"]:
        left = (stt["deadline"] - now).total_seconds() / 60
        if 0 < left <= 60:
            pass  # the 60/30/10-min countdown is queued on ntfy (alarms.py)
        elif 0 < left <= 30 and not dm.get("q30"):
            dm["q30"] = dm["q60"] = True
            out.append((f"🚦 {int(left)} MIN TO QUALIFY",
                        f"No mission locked in. At {stt['deadline']:%I:%M %p} you lose {c['qualify_penalty']} coins "
                        "and the safety car picks your task for you. Takes 30 seconds — do it now.", 5, ["vertical_traffic_light"]))
        elif 30 < left <= 60 and not dm.get("q60"):
            dm["q60"] = True
            out.append(("🚦 1 hour to qualify",
                        f"What are you finishing today? Lock in 1–3 things before {stt['deadline']:%I:%M %p} "
                        f"for +{c['qualify_fuel']} fuel.", 4, ["vertical_traffic_light"]))
        elif left <= 0 and not dm.get("qmiss") and not quiet:
            dm["qmiss"] = dm["q30"] = dm["q60"] = True
            out.append(("🚨 Missed qualifying — safety car out",
                        f"−{c['qualify_penalty']} coins, rivals faster. Your task now: 30 min of focused work, proof by "
                        f"{int(c['safety_car_hour'])}:00. Open the app to see it.", 5, ["rotating_light"]))
    elif stt["start_at"] and not dm.get("lights") and not stt["done_today"]:
        h, m = (int(x) for x in stt["start_at"].split(":"))
        start = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if start <= now < start + timedelta(hours=3):
            dm["lights"] = True
            out.append(("🚦 LIGHTS OUT",
                        f"You said you'd start at {start:%I:%M %p}. It's {now:%I:%M %p}. "
                        "Open the first mission task and work 10 minutes. Go.", 5, ["checkered_flag"]))
    stake, lines = DL.at_stake(save, now.date())
    hour_f = now.hour + now.minute / 60
    for key, at_h, prio, title in (("h2230", 22.5, 5, "🔁 LAST CALL on dailies"), ("h20", 20, 4, "🔁 Dailies still open")):
        if stake and hour_f >= at_h and not dm.get(key):
            dm["h20"] = dm[key] = True
            out.append((title, f"{' · '.join(lines)}\n−{stake} coins at midnight if they're not done.", prio, ["repeat"]))
            break
    if not stt["done_today"] and not quiet:
        hour = now.hour + now.minute / 60
        ladder = [("z18", 18, 4, "⚠️ Zero finishes today",
                   f"6 PM and nothing done. Midnight = −{c['zero_day_penalty']} coins and your "
                   f"{stt['day_streak']}-day streak dies. Smallest task, now."),
                  ("z20", 20, 5, "🔴 ZERO-DAY WARNING",
                   f"Still nothing. 4 hours left. Tomorrow you'll wish you'd done one thing tonight."),
                  ("z2130", 21.5, 5, "☠️ LAST CALL",
                   f"2.5 hours to midnight. One proof-backed finish saves the day streak "
                   f"({stt['day_streak']}) and {c['zero_day_penalty']} coins. Tomorrow Tom is already celebrating.")]
        due = [x for x in ladder if hour >= x[1] and not dm.get(x[0])]
        if due:
            for x in due:
                dm[x[0]] = True
            key, _, prio, title, body = due[-1]
            out.append((title, body, prio, ["warning"]))
    return out


def ad_slots(d, prof: dict | None = None) -> list[datetime]:
    """Two suggestion pushes a day, aimed at your dead zones once the engine has enough history."""
    rng = random.Random(f"ads-{d.isoformat()}")
    opts = list(range(12 * 60, 19 * 60 + 31, 15))
    w = [I.hour_weight(prof, m // 60) for m in opts]
    mins = []
    for _ in range(2):
        k = rng.choices(range(len(opts)), weights=w)[0]
        mins.append(opts.pop(k))
        w.pop(k)
    mins.sort()
    return [datetime.combine(d, datetime.min.time(), TZ) + timedelta(minutes=m) for m in mins]


def suggestion_candidates(n: Notion, save: dict, now: datetime) -> list[tuple[str, str]]:
    """'Ads' for your own life: quick wins, today's board cards, unread papers."""
    out = []
    open_t = sorted((t for t in save.get("tasks", []) if t.get("status") == "open"),
                    key=lambda t: ((t.get("minutes") or 60) > 30, t["deadline"]))
    if open_t:
        t = open_t[0]
        out.append(("🎯 Quick win available",
                    f"{t['title']} — {t.get('minutes') or 60} min → +{t['reward']}. Knock it out and the lounge opens."))
    db = save.get("settings", {}).get("board_db")
    if db:
        try:
            import board as B
            items = [i for i in B.pull_day(n, B.detect(n, db), now.date())
                     if not B.already_have(i, save.get("tasks", []), now.date()) and not B.passed(i, now)]
            if items:
                i = random.choice(items)
                out.append(("📅 On your board today", f"{i['title']}{' · ' + i['when'] if i['when'] else ''} — "
                                                     "add it to today's mission so it counts."))
        except Exception as e:
            print(f"board suggestion skipped: {e}")
    zu, zk = os.getenv("ZOTERO_USER_ID"), os.getenv("ZOTERO_API_KEY")
    if zu and zk:
        try:
            import zotero as Z
            papers = Z.to_read(zu, zk, save.get("settings", {}).get("zotero_collection") or "To Read")
            if papers:
                p = random.choice(papers[:10])
                out.append(("📄 From your reading list", f"{Z.label(p)} — 45 min of deep work = +51. "
                                                        "Open the app and add it."))
        except Exception as e:
            print(f"zotero suggestion skipped: {e}")
    return out


def run(n: Notion, parent: str, topic: str, app_url: str | None, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(TZ)
    ids = ensure_workspace(n, parent)
    save = load_json(n, ids["save_page"]) or {}
    app_url = app_url or save.get("settings", {}).get("app_url")  # tap a push → open the app
    prof = I.profile(save, now.date(), TZ) if save else None  # same history-before-today profile as the app
    EV.set_profile(prof)
    brief_at = I.brief_hour(prof, BRIEF_HOUR)
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
        if 2 <= stg <= 4 and not t["unsynced"]:  # queued on ntfy as exact-time alarms (see alarms.py)
            mem["tasks"][t["key"]] = {"stage": stg, "last": now.isoformat()}
            continue
        send(*message(stg, t, mins, ctx, repeat))
        mem["tasks"][t["key"]] = {"stage": stg, "last": now.isoformat()}

    covered = {"🔁 LAST CALL on dailies", "🔁 Dailies still open", "⚠️ Zero finishes today", "🔴 ZERO-DAY WARNING",
               "☠️ LAST CALL", "🚦 LIGHTS OUT"}  # these are queued on ntfy at their exact times (alarms.py)
    for msg in daily_nags(save, mem, now, quiet):
        if msg[0] not in covered:
            send(*msg)

    if save:  # backup sync of the exact-time alarms (the app does this on every change)
        mem["alarms"], made, fails = AL.sync(save, topic, now, mem.get("alarms", {}), click=app_url, prof=prof)
        print(f"::notice title=alarms::{made} queued/cancelled, {fails} failed")

    day_mem = mem.setdefault("day", {})
    if save and not quiet and not (save.get("tasks") is not None and daily.status(save, now)["rest"]):
        for i, slot in enumerate(ad_slots(now.date(), prof)):
            key = f"ad{i}"
            if slot <= now < slot + timedelta(hours=2) and not day_mem.get(key):
                day_mem[key] = True
                cands = suggestion_candidates(n, save, now)
                if cands:
                    title, body = cands[(i + now.day) % len(cands)]
                    send(title, body, 3, ["bulb"])

    sent_ch = mem.setdefault("challenges", [])
    claimed = set((save or {}).get("challenge_claims", []))
    for ch in EV.focus_challenges(now.date(), TZ):  # ping when a challenge window opens
        if ch["start"] <= now < ch["end"] and ch["id"] not in sent_ch and ch["id"] not in claimed and not quiet:
            sent_ch.append(ch["id"])
            send("⏱️ FOCUS CHALLENGE — window open",
                 f"Start a {ch['minutes']}-min session before {ch['end']:%I:%M %p} → {EV.prize_label(ch['kind'], ch['val'])}. "
                 "Open the app, pick a task, hit Start.", 4, ["stopwatch"])
    del sent_ch[:-30]

    sent_ev = mem.setdefault("events", [])
    for e in EV.active(now):  # random live events — the reason to open the app right now
        if e["id"] not in sent_ev and not quiet:
            sent_ev.append(e["id"])
            send(f"🎉 {e['title']}", f"{e['push']}\nEnds {e['end']:%I:%M %p}.", 4, ["tada"])
    del sent_ev[:-30]

    open_keys = {t["key"] for t in tasks}
    mem["tasks"] = {k: v for k, v in mem["tasks"].items() if k in open_keys}

    if not quiet and now.hour >= brief_at and mem.get("brief") != today:
        mem["brief"] = today
        upcoming = sorted((t for t in tasks if timedelta(0) < t["deadline"] - now < timedelta(hours=48)),
                          key=lambda t: t["deadline"])
        lines = [f"• {t['deadline']:%a %I:%M %p} — {t['title']}" for t in upcoming[:6]]
        body = ("Next 48h:\n" + "\n".join(lines)) if lines else (
            "Nothing on the board. Add one deadline — the car needs fuel." if not tasks
            else "Nothing due in the next 48h. Get ahead: early finishes pay +25%.")
        body += (f"\n\n🪙 {save.get('coins', 0)} · 🔥 streak {ctx['streak']} · "
                 f"🔧 car {save.get('car', {}).get('condition', 100)}%")
        if save.get("tasks") is not None:
            stt = daily.status(save, now)
            if stt["rest"]:
                body += ("\n\n🪂 Bailed out today. Rest, reset." if stt.get("bailout") else "\n\n🛌 Pit stop day. Rest.")
            elif not stt["qualified"] and stt["optional"]:
                body += "\n\n🚦 Weekend: qualifying is optional. Lock in any time today for +15 fuel."
            elif not stt["qualified"]:
                body += f"\n\n🚦 Qualifying closes {stt['deadline']:%I:%M %p} — lock in today's mission."
            body += f"\n📅 Day streak: {stt['day_streak']}"
            body += "\n⏱️ Focus challenges can drop any time today. Keep your phone close."
            for g in save.get("goals", []):
                if not g.get("event_kind") or g.get("claimed"):
                    continue
                left = (date.fromisoformat(g["target"]) - now.date()).days
                if 0 <= left <= 21:
                    gt = [t for t in save["tasks"] if t.get("goal_id") == g["id"]]
                    done = sum(t.get("status") in ("done", "redeemed") for t in gt)
                    body += (f"\n🗓️ {g['title']}: {'TODAY' if left == 0 else f'{left} days'} · prep {done}/{len(gt)}"
                             + (" — behind!" if gt and done / len(gt) < 1 - left / 21 else ""))
        if now.weekday() in DANGER_DAYS:
            body += "\n\n⚠️ Danger day. No one's watching you today — that's exactly why it counts. +20% on everything."
        send(f"🏁 Morning, {ctx['name']}", body, 3, ["checkered_flag"])

    last_done = save.get("last_done_date")
    if last_done and not quiet and mem.get("rust") != today:
        idle = (now.date() - date.fromisoformat(last_done)).days
        if idle >= 2:
            mem["rust"] = today
            send("🟫 Your car is rusting",
                 f"{idle} days without finishing anything. −4% condition a day until you do. "
                 f"Rival heat: {save.get('rival_heat', 0)}.", 4, ["wrench"])

    if save:  # keep-alive so the PC enforcer / iPhone Shortcut always have a fresh lock state
        LK.publish(topic, LK.status(save, now))
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
               os.getenv("APP_URL") or None)  # (run() falls back to the address the app saved)
    print(f"Sent {len(sent)} push(es): {sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
