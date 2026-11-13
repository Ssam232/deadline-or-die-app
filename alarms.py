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
import commitments as C
import daily
import journal as J
import pomo as PM
import nudges as NU
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
# 📓 Evening journal reminders, minutes after midnight of the day it's for (it locks at 4 AM the next morning):
# hourly from 8 PM, every 30 min from 10 PM, then a last call at 3:45. Priority stays ≤ 4 so a sleep Focus still
# silences the late ones.
JOURNAL_LADDER = ([(h * 60, 3) for h in (20, 21)] + [(m, 3) for m in range(22 * 60, 24 * 60, 30)]
                  + [(m, 4) for m in range(24 * 60, 28 * 60, 30)] + [(27 * 60 + 45, 4)])


def _quiet(dt: datetime) -> bool:
    a, b = QUIET
    return dt.hour >= a or dt.hour < b


def _seq(*parts) -> str:
    return "dod" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20]


def _hmin(minutes) -> str:
    """45 min · 1 h · 1 h 30 min (no decimal hours)."""
    m = int(round(minutes or 0))
    h, r = divmod(m, 60)
    return f"{r} min" if not h else f"{h} h" + (f" {r} min" if r else "")


def _hm(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


# Tapping a notification opens the app on the section it's about (?to=…; see JUMPS in app.py)
TO = {"q": "mission", "qb": "mission", "qw": "mission", "z": "mission", "sl": "mission", "block": "mission",
      "task": "mission", "dl": "dailies", "pr": "dailies", "cm": "commit", "journal": "journal", "recap": "journal",
      "timer": "timer", "ch": "timer"}


def _alarm(key, at, title, msg, prio, tags, wanted, go=None):
    """go=(task id or 'new', minutes) adds a ▶️ Start button that opens the app with that timer running."""
    return {"seq": _seq(*key), "at": at, "title": title, "message": msg, "priority": prio, "tags": tags,
            "wanted": bool(wanted), "go": go, "to": TO.get(key[0])}


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


def _daily_reminders(save: dict, d: date, now: datetime) -> list[dict]:
    """🔔 per-daily reminders. The i-th fires only if you've logged fewer than i+1 by then; +1 cancels it."""
    out, rest = [], "tasks" in save and daily.is_rest(save, d)
    for h in DL.habits(save):
        if PR.is_prayer_daily(h) or not DL.active_on(h, d) or (h.get("end") and h["end"] < d.isoformat()):
            continue
        times = DL.remind_times(h)
        if not times:
            continue
        count, n = DL.count(save, h["id"], d), int(h["target"])
        for i, hm in enumerate(times):
            hh, mm = (int(x) for x in hm.split(":"))
            at = datetime.combine(d, datetime.min.time(), now.tzinfo).replace(hour=hh, minute=mm)
            k = min(i + 1, n)
            last = i == len(times) - 1
            msg = (("Last one for today — " if last else "") + f"#{k} of {n} should be done by now. Tap +1 when it is."
                   if n > 1 else "Not done yet today. Tap +1 when it is.")
            out.append(_alarm(("rem", h["id"], d, hm), at, h["name"], msg, 4 if last else 3, ["bell"],
                              not rest and count < k))
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
    return out + _blocks(save, now)


def _blocks(save: dict, now: datetime) -> list[dict]:
    """🗺️ Booked roadmap time: a heads-up 10 min before, then 'it's time' with a ▶️ Start button."""
    out = []
    goals = {g["id"]: g.get("title", "") for g in save.get("goals", [])}
    for t in save.get("tasks", []):
        b = t.get("block") or ({"minutes": t.get("minutes") or 30} if t.get("start_set") else None)
        if not b or not t.get("scheduled"):  # booked roadmap time, or a start time you set in ↕ Arrange
            continue
        at = datetime.fromisoformat(t["scheduled"])
        at = at if at.tzinfo else at.replace(tzinfo=now.tzinfo)
        if not (now - timedelta(minutes=15) < at < now + HORIZON):
            continue
        g = goals.get(t.get("goal_id"), "")
        live = t.get("status") == "open" and not t.get("focus_min")
        for lead, prio, title, msg in (
                (10, 3, f"{'🗺️' if t.get('block') else '⏰'} In 10 min: {t['title']}", f"{b['minutes']} min booked at {_hm(at)}" + (f" for {g}." if g else ".")),
                (0, 4, f"▶️ Now: {t['title']}", f"Your {b['minutes']}-min block" + (f" for {g}" if g else "") + " starts now. "
                                                 f"Tap ▶️ and the timer runs.")):
            out.append(_alarm(("block", t["id"], t["scheduled"], lead), at - timedelta(minutes=lead), title, msg,
                              prio, ["world_map"], live, (t["id"], b["minutes"])))
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
                          not rest and not daily.qualified(save, d) and not daily.qualify_optional(d)))
    # 🗺️ booked roadmap time already qualifies you; still nudge to add the rest of the day (cancelled once you do)
    bk = daily.booked(save, d)
    extra = [t for t in daily.mission(save, d) if not t.get("block")]
    if bk:
        first = datetime.strptime(bk[0]["block"]["start"], "%H:%M").strftime("%I:%M %p").lstrip("0")
        for mins, title, msg in (
                (60, f"🚦 Booked: {len(bk)} block{'s' * (len(bk) != 1)} today", f"First at {first}. You're qualified, but "
                 f"is that the whole day? Add anything else to today's mission before {_hm(qd)}."),
                (15, "🚦 Anything else today?", "Your roadmap blocks are locked in. 30 seconds to add the rest of "
                                                "today's mission (emails, errands, the small stuff).")):
            out.append(_alarm(("qb", d, mins), qd - timedelta(minutes=mins), title, msg, 3, ["vertical_traffic_light"],
                              not rest and not extra))
    if daily.qualify_optional(d):  # weekends: no countdown, just two friendly offers (cancelled once you lock in)
        for hh, mm, title, msg in (
                (11, 30, "🚦 Weekend mission?", f"Optional today: lock in 1–3 things any time for +{c['qualify_fuel']} fuel. "
                                                "No deadline, no penalty."),
                (14, 30, "🚦 Still time for a weekend mission", f"Lock in something small and the +{c['qualify_fuel']} "
                                                                "fuel is yours. Skip it and nothing happens.")):
            out.append(_alarm(("qw", d, hh), datetime.combine(d, datetime.min.time(), now.tzinfo).replace(hour=hh, minute=mm),
                              title, msg, 3, ["vertical_traffic_light"], not rest and not daily.qualified(save, d)))
    zero = (not rest and d.weekday() not in daily.WEEKEND and not daily.finished_on(save, d)
            and not daily.slice_worked(save, d) and not C.attended_on(save, d))  # weekends optional; slices/showing up count
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
    # ⏱️ committed slices still short: 8 PM and 10:30 PM, cancelled as soon as the timer covers them
    pen, lines = daily.slice_penalty(save, d)
    for hh, mm, prio, title in ((20, 0, 4, "⏱️ Slices still open"), (22, 30, 5, "⏱️ LAST CALL on slices")):
        out.append(_alarm(("sl", d, hh), datetime.combine(d, datetime.min.time(), now.tzinfo).replace(hour=hh, minute=mm),
                          title, "\n".join(lines[:3]) + f"\n−{pen} coins at midnight for the minutes you don't log.",
                          prio, ["stopwatch"], bool(pen) and not rest))
    # 🗓️ Sunday-evening weekly recap
    if d.weekday() == J.RECAP_DAY:
        r = J.recap(save, J.week_start(d), now.tzinfo, through=now.date())
        rat = datetime.combine(d, datetime.min.time(), now.tzinfo).replace(hour=J.RECAP_HOUR)
        out.append(_alarm(("recap", d), rat, "🗓️ Your week",
                          f"{_hmin(r['focus_min'])} focused · {r['done']} done · mood {J.mood_face(r['mood_avg'])}. "
                          "Log → Journal for the full recap.", 3, ["calendar"], True))
    return out


TIMER_SLOTS = 6  # pomodoro transitions queued ahead (break / back to work)


def _timer(save: dict, now: datetime) -> list[dict]:
    """⏱️ Buzz the phone when a running focus session ends, and at each pomodoro break / back-to-work, so you
    notice without looking at the screen or wearing headphones. Fixed slots: re-posting moves them; no running timer
    (or a pause) cancels them."""
    tm = save.get("timer")
    task = next((t for t in save.get("tasks", []) if tm and t.get("id") == tm.get("task_id")), None)
    title = (task or {}).get("title", "your session")
    park = now + timedelta(hours=40)  # where idle slots "live" so they stay inside the planning window
    end_a = _alarm(("timer", "end"), park, "🏁 Session done", "", 4, ["checkered_flag"], False)
    slots = [_alarm(("timer", "t", i), park, "☕ Break", "", 3, ["coffee"], False) for i in range(TIMER_SLOTS)]
    if not tm or tm.get("paused_at"):
        return [end_a] + slots
    work, brk = tm.get("work"), tm.get("brk")
    eff = PM.effective_elapsed(tm, now.timestamp())  # minutes on the clock so far
    if tm.get("flow"):  # 🌊 no finish line: one buzz at the check-in
        chk = now + timedelta(minutes=tm.get("check", 90) - eff)
        if chk > now:
            end_a.update(at=chk, wanted=True, title="🌊 Still flowing?",
                         message=f"{title}: {int(tm.get('check', 90))} min in. Tap 'keep going' in the app, or it logs up to here.")
        return [end_a] + slots
    wall = PM.wall_minutes(tm["planned"], work, brk)
    end = now + timedelta(minutes=wall - eff)
    if end > now:
        end_a.update(at=end, wanted=True, message=f"{title}: {tm['planned']} min done. Stop & log it — that's proof.")
    if work and brk:
        c, i, k = work + brk, 0, 0
        while i < TIMER_SLOTS and k < 40:
            gated = "pins" in tm  # breaks wait for a Pit in / Pit out tap in the app
            for off, ttl, msg in ((k * c + work, "🔧 Box, box" if gated else "☕ Break time",
                                   f"{work} min in. Tap Pit in when you're ready." if gated
                                   else f"{work} min in. Stand up, water, no phone."),
                                  ((k + 1) * c, "🟢 Pit out?" if gated else "🟢 Back to work",
                                   "Break's up. Tap Pit out to rejoin." if gated else "Break's over. Phone face-down, back to it.")):
                at = now + timedelta(minutes=off - eff)
                if now < at < end - timedelta(minutes=1) and i < TIMER_SLOTS:
                    slots[i].update(at=at, wanted=True, title=ttl, message=f"{title}: {msg}",
                                    tags=["coffee" if ("Break" in ttl or "Box" in ttl) else "green_circle"])
                    i += 1
            k += 1
    return [end_a] + slots


def _live(save: dict, now: datetime, prof: dict | None) -> list[dict]:
    """🎉 Live events and ⏱️ focus challenges, pushed the minute they start (not whenever the cron wakes up)."""
    import events as EV
    EV.set_profile(prof)  # same profile as the app and the nagger → the same schedule
    out, tz = [], now.tzinfo
    ev_claims, ch_claims = set(save.get("event_claims", [])), set(save.get("challenge_claims", []))
    for d in (now.date(), now.date() + timedelta(days=1)):
        for e in EV.todays(d, tz):
            out.append(_alarm(("ev", e["id"]), e["start"], f"🎉 {e['title']}", EV.push_text(e, e["start"]), 4,
                              ["tada"], e["id"] not in ev_claims))
        for ch in EV.focus_challenges(d, tz):
            out.append(_alarm(("ch", ch["id"]), ch["start"], "⏱️ FOCUS CHALLENGE — window open",
                              f"Start a {ch['minutes']}-min session before {_hm(ch['end'])} → "
                              f"{EV.prize_label(ch['kind'], ch['val'])}. Open the app, pick a task, hit Start.", 4,
                              ["stopwatch"], ch["id"] not in ch_claims, ("new", ch["minutes"])))
    return out


def _commitments(save: dict, now: datetime) -> list[dict]:
    """📍 Pack your bag 2 h before, leave on time, check in once it starts; quota pace in the morning."""
    out = []
    for d in (now.date(), now.date() + timedelta(days=1)):
        rest = daily.is_rest(save, d)
        for c in C.items(save):
            st_ = C.start_on(c, d, now.tzinfo)
            if st_:
                r = C.rec(save, c["id"], d) or {}
                open_ = not r.get("status")
                t12 = f"{st_:%I:%M %p}".lstrip("0")
                stakes = c["stakes"]
                lose = ("" if stakes == "green" or C.warming_up(c, d) else
                        f" No check-in, no notice = flake (−{round(C.STAKES[stakes]['flake'] * daily.level_factor(save))}).")
                out.append(_alarm(("cm", c["id"], d, "pack"), st_ - timedelta(hours=2), f"🎒 {c['name']} at {t12}",
                                  f"Two hours out. Get your stuff together.{lose}", 3, ["round_pushpin"], open_))
                lv = st_ - timedelta(minutes=int(c.get("travel") or 0))
                if c.get("travel"):
                    out.append(_alarm(("cm", c["id"], d, "leave"), lv, f"🚗 Leave now: {c['name']}",
                                      f"It starts at {t12}. {c['travel']} min to get there.", 4, ["red_car"], open_))
                out.append(_alarm(("cm", c["id"], d, "in"), st_ + timedelta(minutes=5), f"📍 Check in: {c['name']}",
                                  f"Tap “I'm here” in the app. On time until {st_ + timedelta(minutes=C.ON_TIME_MIN):%I:%M %p}."
                                  .replace(" 0", " "), 5 if stakes == "red" else 4, ["round_pushpin"], open_))
            elif c["kind"] == "quota" and not rest and (not c.get("days") or d.weekday() in c["days"]):
                need, left = C.quota_pace(save, c, d)
                behind = need > 0 and need >= left
                out.append(_alarm(("cm", c["id"], d, "pace"), datetime.combine(d, datetime.min.time(), now.tzinfo)
                                  .replace(hour=8, minute=30), f"🎯 {c['name']}: {need} left this week",
                                  f"{left} day{'s' * (left != 1)} left to do it. Today's a good one.", 4, ["dart"],
                                  behind and (C.rec(save, c["id"], d) or {}).get("status") not in ("in", "visit")))
    return out


def _journal(save: dict, d: date, now: datetime) -> list[dict]:
    """📓 The evening journal for day d keeps nudging until it locks at 4 AM the next morning; every one is
    cancelled once you've closed the day (yesterday's night is planned too, so a 1 AM entry cancels the rest)."""
    out = []
    # 📓 evening journal: keeps nudging until it closes at 4 AM; all of it cancelled once you've closed the day
    open_ = not J.peek(save, d).get("pm")
    base = datetime.combine(d, datetime.min.time(), now.tzinfo)
    close = base + timedelta(days=1, hours=J.PM_CLOSES)
    for off, prio in JOURNAL_LADDER:
        jat = base + timedelta(minutes=off)
        left = close - jat
        if off < 23 * 60:
            title, msg = "📓 Close the day", (f"Two taps, what you're grateful for, the win, tomorrow's one thing. "
                                              f"Up to +{J.PM_MAX}.")
        elif left > timedelta(minutes=30):
            title, msg = "📓 Journal still open", f"Closes at {J.PM_CLOSES} AM ({_hmin(left.total_seconds() / 60)} left). " \
                                                  f"Two minutes before bed, up to +{J.PM_MAX}."
        else:
            title, msg = "⏳ Journal closes soon", f"{_hmin(left.total_seconds() / 60)} until it locks for the day."
        key = ("journal", d) if off == 23 * 60 else ("journal", d, off)  # 11 PM keeps its old slot
        out.append(_alarm(key, jat, title, msg, prio, ["notebook"], open_))
    return out


def plan(save: dict, now: datetime, prof: dict | None = None) -> list[dict]:
    """Every alarm that could fire in the next ~2 days, wanted or not (unwanted ones get cancelled)."""
    if not save:
        return []
    out = _tasks(save, now) + NU.build(save, now, prof, _alarm) + _timer(save, now) + _live(save, now, prof)
    for d in (now.date(), now.date() + timedelta(days=1)):
        out += _prayers(save, d, now) + _day(save, d, now) + _daily_reminders(save, d, now)
    for d in (now.date() - timedelta(days=1), now.date(), now.date() + timedelta(days=1)):
        out += _journal(save, d, now)
    out += _commitments(save, now)
    lo, hi = now + timedelta(seconds=MIN_LEAD), now + HORIZON
    return [a for a in out if lo <= a["at"] <= hi]


def _sig(a: dict) -> str:
    return hashlib.sha1(f"{a['at'].isoformat()}|{a['title']}|{a['message']}|{a['priority']}|{a.get('go')}"
                        .encode()).hexdigest()[:12]


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
    # alarms we queued that aren't in the plan any more (a block or deadline was MOVED, so its alarm got a new id):
    # take the old ones back too, or they still go off at the old time
    planned = {a["seq"] for a in alarms}
    soon = now.timestamp() + MIN_LEAD + 5  # too close to call back reliably / not planned because it's imminent
    for seq, v in list(m.items()):
        if seq not in planned and v[1] != "x" and v[0] > soon:
            cancel.append({"seq": seq, "at": datetime.fromtimestamp(v[0], now.tzinfo), "title": "", "message": ""})
            m[seq] = [v[0], "x"]
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
            here = f"{click}{'&' if '?' in click else '?'}to={a['to']}" if a.get("to") else click
            body["click"] = here
            body["actions"] = [{"action": "view", "label": "Open Deadline or Die", "url": here, "clear": True}]
            if a.get("go"):
                tid, mins = a["go"]
                go = f"{click}{'&' if '?' in click else '?'}go={tid}&m={int(mins)}"
                body["actions"] = [{"action": "view", "label": f"▶️ Start {int(mins)} min", "url": go, "clear": True},
                                   {"action": "view", "label": "Open app", "url": click, "clear": True}]
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


def sync(save: dict, topic: str | None, now: datetime, posted: dict, click: str | None = None,
         prof: dict | None = None) -> tuple[dict, int, int]:
    """Plan → diff → send. Returns (new posted-map, posts+cancels made, failures). Failed posts are forgotten so the
    next sync retries them."""
    if not topic:
        return posted or {}, 0, 0
    post, cancel, m = diff(plan(save, now, prof), posted, now)
    bad = send(topic, post, cancel, click)
    for q in bad:  # forget them so the next sync retries
        m.pop(q, None)
    return m, len(post) + len(cancel), len(bad)


def held(topic: str, server: str = SERVER) -> list[dict]:
    """What ntfy is actually holding for us right now (scheduled, not yet delivered)."""
    import json as _j
    import requests
    r = requests.get(f"{server.rstrip('/')}/{topic}/json", params={"poll": "1", "sched": "1"}, timeout=15)
    out = []
    for line in r.text.splitlines():
        try:
            m = _j.loads(line)
        except ValueError:
            continue
        if m.get("event", "message") == "message":
            out.append(m)
    return out


def reconcile(save: dict, topic: str | None, now: datetime, prof: dict | None = None,
              server: str = SERVER, ghosts_only: bool = False) -> tuple[int, list[str], int]:
    """Sweep out vestigial alerts: anything ntfy is holding for us that today's plan doesn't want (a task that was
    moved, renamed, finished or deleted; a block that was dropped; an alert type an update removed; anything a lost
    or rolled-back posted-map no longer remembers). The plan is the truth.
    Returns (held, the sequence ids taken back, how many held ones carried an id we could check)."""
    if not topic:
        return 0, [], 0
    wanted = {a["seq"]: a for a in plan(save, now, prof) if a["wanted"]}
    soon = now.timestamp() + MIN_LEAD + 5
    stale = []
    msgs = held(topic, server)
    for m in msgs:
        seq = m.get("sequence_id") or ""
        if not seq.startswith("dod") or m.get("time", 0) <= soon:
            continue  # not one of our queued alarms, or about to fire anyway
        a = wanted.get(seq)
        if a is None or (not ghosts_only and abs(a["at"].timestamp() - m.get("time", 0)) > 90):
            stale.append({"seq": seq, "at": datetime.fromtimestamp(m.get("time", 0), now.tzinfo),
                          "title": "", "message": ""})
    if stale:
        send(topic, [], stale, None, server)
    return len(msgs), [x["seq"] for x in stale], sum(1 for m in msgs if (m.get("sequence_id") or "").startswith("dod"))
