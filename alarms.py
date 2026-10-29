"""
⏰ Pre-scheduled phone alarms, delivered by ntfy's own server at exact times.

GitHub's cron drops most runs, so time-critical nags can't depend on it. Instead the app (and the nagger, as a backup)
works out every alarm for today and tomorrow, queues each on ntfy with a fixed sequence ID and a delivery time, and
cancels it the moment it stops applying (prayer logged, task finished, mission locked in, dailies done). Re-posting the
same sequence ID replaces the queued message, so the app and the nagger can both sync without double-buzzing.

  plan(save, now)            → every candidate alarm, each marked wanted or not
  sync(save, topic, now, M)  → posts/cancels the difference against M (seq → [ts, sig]); returns the updated M
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

import dailies as DL
import daily
import prayers as PR
from notify import SERVER

MIN_LEAD = 20          # seconds: ntfy needs ≥10 s of delay; anything sooner is sent by the live nagger instead
HORIZON = timedelta(hours=47)
TASK_STAGES = [  # minutes before the deadline, priority, quiet-hours ok, title
    (6 * 60, 4, False, "🟡 6 hours left"),
    (2 * 60, 5, False, "🔴 2 HOURS LEFT"),
    (60, 5, False, "🔴 1 HOUR LEFT"),
    (30, 5, True, "☠️ 30 min. FINAL WARNING."),
    (10, 5, True, "☠️ 10 MIN"),
]
PRAYER_STAGES = [  # minutes before the window ends (None = when it opens), priority, title
    (None, 3, "🕌 {n} time"),
    (45, 4, "🕌 {n} ends in 45 min"),
    (20, 5, "⏳ {n} ends in 20 min"),
    (10, 5, "⏳ {n} ends in 10 min"),
    (0, 4, "🕌 {n} window closed"),
]
QUIET = (23, 7)


def _quiet(dt: datetime) -> bool:
    a, b = QUIET
    return dt.hour >= a or dt.hour < b


def _seq(*parts) -> str:
    return "dod" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20]


def _hm(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _alarm(key, at, title, msg, prio, tags, wanted):
    return {"seq": _seq(*key), "at": at, "title": title, "message": msg, "priority": prio, "tags": tags,
            "wanted": bool(wanted)}


def _prayers(save: dict, d: date, now: datetime) -> list[dict]:
    hs = [h for h in DL.habits(save) if PR.is_prayer_daily(h) and DL.active_on(h, d)
          and (not h.get("end") or h["end"] > d.isoformat())]
    if not hs:
        return []
    h = hs[0]
    count = DL.count(save, h["id"], d)
    out = []
    for w in PR.windows(d, now.tzinfo, **PR.settings_of(save)):
        for mins, prio, title in PRAYER_STAGES:
            at = w["start"] if mins is None else w["end"] - timedelta(minutes=mins)
            if at < w["start"]:
                continue
            n = w["name"]
            if mins is None:
                msg = f"Window closes {_hm(w['end'])}. Prayer {w['i'] + 1} of {h['target']} today."
            elif mins == 0:
                msg = "It slipped. If you did pray, log it in the app so the streak math is right."
            else:
                msg = f"Not logged yet (prayer {w['i'] + 1} of {h['target']}). Pray now, then tap +1."
            out.append(_alarm(("pr", d, n, mins), at, title.format(n=n), msg, prio, ["mosque"], count <= w["i"]))
    return out


def _tasks(save: dict, now: datetime) -> list[dict]:
    out = []
    for t in save.get("tasks", []):
        try:
            dl = datetime.fromisoformat(t["deadline"])
        except (KeyError, TypeError, ValueError):
            continue
        dl = dl if dl.tzinfo else dl.replace(tzinfo=now.tzinfo)
        if not (now - timedelta(hours=1) < dl < now + HORIZON):
            continue
        for mins, prio, loud, title in TASK_STAGES:
            at = dl - timedelta(minutes=mins)
            if _quiet(at) and not loud:
                continue
            msg = (f"{t['title']}\n+{t.get('reward', 0)} if you finish · −{t.get('penalty', 0)} if you don't."
                   + (f"\nIf you miss: {t['consequence']}" if t.get("consequence") else "")
                   + ("\nOpen it. 10 minutes. Go." if mins >= 60 else "\nSubmit proof NOW."))
            out.append(_alarm(("task", t["id"], t["deadline"], mins), at, title, msg, prio, ["rotating_light"],
                              t.get("status") == "open"))
    return out


def _day(save: dict, d: date, now: datetime) -> list[dict]:
    if "tasks" not in save:
        return []
    out, rest = [], daily.is_rest(save, d)
    e = daily.peek_day(save, d)
    c = daily.cfg(save)
    qd = daily.qualify_deadline(save, d, now.tzinfo)
    for mins, prio, title, msg in (
            (60, 4, "🚦 1 hour to qualify", f"Lock in 1–3 things before {_hm(qd)} for +{c['qualify_fuel']} fuel."),
            (30, 5, "🚦 30 MIN TO QUALIFY", f"No mission locked in. At {_hm(qd)} you lose {c['qualify_penalty']} "
                                           "coins and the safety car picks your task. Takes 30 seconds."),
            (10, 5, "🚦 10 MIN TO QUALIFY", "Open the app and lock in today's mission. Now.")):
        out.append(_alarm(("q", d, mins), qd - timedelta(minutes=mins), title, msg, prio, ["vertical_traffic_light"],
                          not rest and not e.get("qualified")))
    zero = not rest and not daily.finished_on(save, d)
    for hh, mm, prio, title, msg in (
            (18, 0, 4, "⚠️ Zero finishes today", f"6 PM and nothing done. Midnight = −{c['zero_day_penalty']} coins "
                                                "and the day streak dies. Smallest task, now."),
            (20, 0, 5, "🔴 ZERO-DAY WARNING", "Still nothing. 4 hours left. One proof-backed finish saves the day."),
            (21, 30, 5, "☠️ LAST CALL", f"2.5 hours to midnight. One finish saves the streak and "
                                        f"{c['zero_day_penalty']} coins.")):
        out.append(_alarm(("z", d, hh), datetime.combine(d, datetime.min.time(), now.tzinfo).replace(hour=hh, minute=mm),
                          title, msg, prio, ["warning"], zero))
    stake, lines = DL.at_stake(save, d)
    for hh, mm, prio, title in ((20, 0, 4, "🔁 Dailies still open"), (22, 30, 5, "🔁 LAST CALL on dailies")):
        out.append(_alarm(("dl", d, hh), datetime.combine(d, datetime.min.time(), now.tzinfo).replace(hour=hh, minute=mm),
                          title, f"{' · '.join(lines)}\n−{stake} coins at midnight if they're not done.", prio,
                          ["repeat"], bool(stake) and not rest))
    return out


def plan(save: dict, now: datetime) -> list[dict]:
    """Every alarm that could fire in the next ~2 days, wanted or not (unwanted ones get cancelled)."""
    if not save:
        return []
    out = _tasks(save, now)
    for d in (now.date(), now.date() + timedelta(days=1)):
        out += _prayers(save, d, now) + _day(save, d, now)
    lo, hi = now + timedelta(seconds=MIN_LEAD), now + HORIZON
    return [a for a in out if lo <= a["at"] <= hi]


def _sig(a: dict) -> str:
    return hashlib.sha1(f"{a['at'].isoformat()}|{a['title']}|{a['message']}|{a['priority']}".encode()).hexdigest()[:12]


def diff(alarms: list[dict], posted: dict, now: datetime) -> tuple[list[dict], list[dict], dict]:
    """(to post, to cancel, the new posted-map). posted: seq → [unix ts, sig or 'x' for cancelled]."""
    cutoff = now.timestamp()
    m = {k: v for k, v in (posted or {}).items() if v[0] > cutoff}
    post, cancel = [], []
    for a in alarms:
        cur = m.get(a["seq"])
        if a["wanted"]:
            sig = _sig(a)
            if not cur or cur[1] != sig:
                post.append(a)
                m[a["seq"]] = [a["at"].timestamp(), sig]
        elif cur is None or cur[1] != "x":
            # cancel even if we never posted it: the other syncer (app ↔ nagger) might have
            cancel.append(a)
            m[a["seq"]] = [a["at"].timestamp(), "x"]
    return post, cancel, m


FAILED: set[str] = set()  # seqs whose last send failed (e.g. rate-limited) — the app drops them from its map to retry


def send(topic: str, post: list[dict], cancel: list[dict], click: str | None = None, server: str = SERVER) -> list[str]:
    """Fire the HTTP calls (in parallel). Returns the sequence IDs that failed (also added to FAILED)."""
    import requests
    from concurrent.futures import ThreadPoolExecutor
    base = server.rstrip("/")

    def do_post(a):
        body = {"topic": topic, "title": a["title"], "message": a["message"], "priority": a["priority"],
                "tags": a["tags"], "sequence_id": a["seq"], "delay": str(int(a["at"].timestamp()))}
        if click:
            body["click"] = click
            body["actions"] = [{"action": "view", "label": "Open Deadline or Die", "url": click, "clear": True}]
        return requests.post(base, json=body, timeout=10).status_code < 300

    def do_cancel(a):
        return requests.delete(f"{base}/{topic}/{a['seq']}", timeout=10).status_code < 500

    def safe(fn, a):
        try:
            return fn(a)
        except Exception:  # noqa: BLE001
            return False

    jobs = [(do_post, a) for a in post] + [(do_cancel, a) for a in cancel]
    if not jobs or not topic:
        return []
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda j: safe(*j), jobs))
    bad = [a["seq"] for (_, a), ok in zip(jobs, res) if not ok]
    FAILED.update(bad)
    return bad


def sync(save: dict, topic: str | None, now: datetime, posted: dict, click: str | None = None) -> tuple[dict, int, int]:
    """Plan → diff → send. Returns (new posted-map, posts+cancels made, failures). Failed posts are forgotten so the
    next sync retries them."""
    if not topic:
        return posted or {}, 0, 0
    post, cancel, m = diff(plan(save, now), posted, now)
    bad = send(topic, post, cancel, click)
    for q in bad:  # forget them so the next sync retries
        m.pop(q, None)
    return m, len(post) + len(cancel), len(bad)
