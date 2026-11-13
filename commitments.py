"""
📍 Commitments: showing up for the things you said you'd be at. No Streamlit imports.

Three kinds:
  weekly  🔁  a fixed slot every week (Taekwondo Thu 7 PM). Check in from 20 min before to 15 min after the start;
              later than that (but before it ends) is a late check-in: half pay.
  quota   🎯  "the office 3× a week": any allowed day counts. Tap in, tap out once you've stayed long enough.
              Settled when the week (Mon–Sun) ends: each missing visit costs.
  oneoff  📌  one date and time (a club event, a hang out, a side quest). Settled once.

Stakes, per commitment:
  red     🔴  people count on me (coaching, volunteering): pays well, a flake costs 2× and adds rival heat
  yellow  🟡  normal: a flake costs 1×
  green   🟢  bonus only: coins if you go, nothing if you don't (fun plans never turn into chores)

Proof is a check-in. With a pin dropped at the venue, the phone's location is compared to it right then: only the
distance is kept, never your coordinates. No pin, or no location: a photo works. Cancelling 3+ h ahead with a reason
is free (3 a month); later than that costs half. A flake (no check-in, no notice) costs and resets the streak.
Everything that costs or pays scales with your level factor, so it never gets easier the better you get.
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta

KINDS = {"weekly": "🔁 Every week", "quota": "🎯 Weekly quota", "oneoff": "📌 One-off"}
STAKES = {
    "red": {"label": "🔴 People count on me", "pay": 40, "flake": 80},
    "yellow": {"label": "🟡 Normal", "pay": 30, "flake": 40},
    "green": {"label": "🟢 Bonus only", "pay": 20, "flake": 0},
}
EARLY_MIN = 20            # check-in opens this long before the start
ON_TIME_MIN = 15          # up to this long after the start still counts as on time
CANCEL_AHEAD_H = 3        # cancel at least this far ahead (with a reason) and it's free
FREE_CANCELS_PER_MONTH = 3
LATE_FORGIVE_DAYS = 30    # one late check-in in this window keeps the streak
PIN_RADIUS_M = 250
STAY_DEFAULT = 120        # quota visits: minutes you have to stay (0 = the tap-in counts)
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def items(save: dict, active_only: bool = True) -> list[dict]:
    xs = save.setdefault("commitments", [])
    return [c for c in xs if c.get("active", True)] if active_only else xs


def get(save: dict, cid: str) -> dict | None:
    return next((c for c in items(save, False) if c["id"] == cid), None)


def add(save: dict, name: str, kind: str, stakes: str, now: datetime, *, days=None, time="19:00", minutes=90,
        on=None, per_week=3, stay=STAY_DEFAULT, travel=20) -> dict:
    c = {"id": uuid.uuid4().hex[:10], "name": name.strip()[:60], "kind": kind, "stakes": stakes,
         "days": sorted(days or ([0, 1, 2, 3, 4] if kind == "quota" else [])), "time": time, "minutes": int(minutes),
         "date": on.isoformat() if on else None, "per_week": int(per_week), "stay": int(stay), "travel": int(travel),
         "pin": None, "radius": PIN_RADIUS_M, "active": True, "created": now.isoformat(), "streak": 0, "best": 0}
    items(save, False).append(c)
    return c


def _key(cid: str, d: date) -> str:
    return f"{cid}|{d.isoformat()}"


def rec(save: dict, cid: str, d: date) -> dict | None:
    return save.get("attendance", {}).get(_key(cid, d))


def _set(save: dict, cid: str, d: date, **kw) -> dict:
    r = save.setdefault("attendance", {}).setdefault(_key(cid, d), {})
    r.update(kw)
    return r


def start_on(c: dict, d: date, tz) -> datetime | None:
    """When a weekly / one-off commitment starts on day d (None if it doesn't happen that day)."""
    if c["kind"] == "weekly" and d.weekday() not in c["days"]:
        return None
    if c["kind"] == "oneoff" and c.get("date") != d.isoformat():
        return None
    if c["kind"] == "quota":
        return None
    hh, mm = (int(x) for x in c["time"].split(":"))
    return datetime.combine(d, datetime.min.time(), tz).replace(hour=hh, minute=mm)


def window(c: dict, start: datetime) -> tuple[datetime, datetime, datetime]:
    """(check-in opens, on-time cutoff, it's over)."""
    end = start + timedelta(minutes=max(15, int(c.get("minutes") or 60)))
    return start - timedelta(minutes=EARLY_MIN), start + timedelta(minutes=ON_TIME_MIN), max(end, start + timedelta(minutes=ON_TIME_MIN))


def created_before(c: dict, when: datetime) -> bool:
    return datetime.fromisoformat(c["created"]) <= when


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Haversine, metres."""
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def verify(c: dict, fix: dict | None, photo: bool) -> tuple[bool, str, float | None]:
    """Is this check-in proven? A location fix near the pin, or a photo. Returns (ok, how, distance)."""
    if fix and c.get("pin") and fix.get("lat") is not None:
        d = distance_m((fix["lat"], fix["lon"]), (c["pin"]["lat"], c["pin"]["lon"]))
        slack = min(float(fix.get("acc") or 0), 150.0)
        if d <= c.get("radius", PIN_RADIUS_M) + slack:
            return True, "location", round(d)
        if photo:
            return True, "photo", round(d)
        return False, f"you're {d / 1000:.1f} km from the pin" if d >= 1000 else f"you're {d:.0f} m from the pin", round(d)
    if photo:
        return True, "photo", None
    if not c.get("pin"):
        return False, "no pin for this place yet: add a photo (or drop a pin once you're there)", None
    return False, "couldn't get your location: add a photo instead", None


def _streak_after(c: dict, status: str, when: datetime) -> None:
    if status == "attended":
        c["streak"] = int(c.get("streak", 0)) + 1
    elif status == "late":
        last = c.get("last_late")
        if last and (when - datetime.fromisoformat(last)).days < LATE_FORGIVE_DAYS:
            c["streak"] = 0
        else:
            c["streak"] = int(c.get("streak", 0)) + 1
        c["last_late"] = when.isoformat()
    elif status == "flaked":
        c["streak"] = 0
    c["best"] = max(int(c.get("best", 0)), int(c.get("streak", 0)))


def check_in(save: dict, c: dict, now: datetime, how: str, dist: float | None, bank, lf: float) -> tuple[bool, str]:
    """📍 For weekly / one-off: on time or late (half pay). For quotas: tap in (and the stay clock starts)."""
    d = now.date()
    if c["kind"] == "quota":
        r = rec(save, c["id"], d) or {}
        if r.get("status") in ("in", "visit"):
            return False, "Already checked in today."
        if c.get("days") and d.weekday() not in c["days"]:
            return False, f"{c['name']} only counts on {', '.join(WD[i] for i in c['days'])}."
        _set(save, c["id"], d, status="in", at=now.isoformat(), how=how, dist=dist)
        if not int(c.get("stay") or 0):
            return check_out(save, c, now, bank, lf)
        return True, f"📍 Checked in at {c['name']}. Stay {c['stay']} min and tap out to count the visit."
    start = start_on(c, d, now.tzinfo)
    if not start:
        return False, f"{c['name']} isn't on today."
    opens, on_time, end = window(c, start)
    r = rec(save, c["id"], d) or {}
    if r.get("status"):
        return False, f"Already {r['status']} for today."
    if now < opens:
        return False, f"Check-in opens at {opens:%I:%M %p}".replace(" 0", " ") + "."
    if now > end:
        return False, "It's over: too late to check in."
    status = "attended" if now <= on_time else "late"
    pay = round(STAKES[c["stakes"]]["pay"] * lf * (1 if status == "attended" else 0.5))
    _set(save, c["id"], d, status=status, at=now.isoformat(), how=how, dist=dist, paid=pay)
    _streak_after(c, status, now)
    bank(save, pay, f"📍 {c['name']}" + (" (late)" if status == "late" else ""))
    if status == "attended":
        return True, f"📍 **{c['name']}**: you showed up. +{pay} · 🔥 {c['streak']} in a row."
    return True, f"📍 **{c['name']}**: late, but here. +{pay} (half)." + (
        " Streak kept (once a month)." if c["streak"] else " That's the second late this month: streak reset.")


def check_out(save: dict, c: dict, now: datetime, bank, lf: float) -> tuple[bool, str]:
    """🎯 Quota visits: tap out; the visit counts once you've stayed long enough."""
    d = now.date()
    r = rec(save, c["id"], d) or {}
    if r.get("status") != "in":
        return False, "Not checked in."
    stayed = (now - datetime.fromisoformat(r["at"])).total_seconds() / 60
    need = int(c.get("stay") or 0)
    if stayed < need:
        return False, f"{stayed:.0f} of {need} min so far: stay a bit longer for it to count."
    pay = round(STAKES[c["stakes"]]["pay"] * lf)
    _set(save, c["id"], d, status="visit", out=now.isoformat(), stay=round(stayed), paid=pay)
    bank(save, pay, f"📍 {c['name']} visit")
    done, target, _, _ = quota_week(save, c, d)
    return True, f"📍 **{c['name']}** visit counted ({done}/{target} this week). +{pay}"


def cancel(save: dict, c: dict, d: date, now: datetime, reason: str, bank, lf: float) -> tuple[bool, str]:
    """Cancel one occurrence. 3+ h ahead with a reason: free (FREE_CANCELS_PER_MONTH a month). Later: half a flake."""
    start = start_on(c, d, now.tzinfo)
    if not start or (rec(save, c["id"], d) or {}).get("status"):
        return False, "Nothing to cancel."
    if not reason.strip():
        return False, "Say why (one line)."
    month = now.strftime("%Y-%m")
    used = sum(1 for k, r in save.get("attendance", {}).items()
               if r.get("status") == "cancelled" and r.get("free") and (r.get("at") or "")[:7] == month)
    ahead = (start - now).total_seconds() / 3600
    free = ahead >= CANCEL_AHEAD_H and used < FREE_CANCELS_PER_MONTH
    cost = 0 if free else round(STAKES[c["stakes"]]["flake"] * lf * 0.5)
    _set(save, c["id"], d, status="cancelled", at=now.isoformat(), reason=reason.strip()[:120], free=free, cost=cost)
    if cost:
        bank(save, -cost, f"📍 Late cancel: {c['name']}")
    if free:
        return True, f"Cancelled {c['name']} ({FREE_CANCELS_PER_MONTH - used - 1} free cancels left this month). Streak kept."
    why = "under 3 h before" if ahead < CANCEL_AHEAD_H else "free cancels used up this month"
    return True, f"Cancelled {c['name']}, {why}: −{cost}. Streak kept, since you said so instead of flaking."


def week_of(d: date) -> tuple[date, date]:
    s = d - timedelta(days=d.weekday())
    return s, s + timedelta(days=6)


def quota_week(save: dict, c: dict, d: date) -> tuple[int, int, date, date]:
    s, e = week_of(d)
    done = sum(1 for i in range(7) if (rec(save, c["id"], s + timedelta(days=i)) or {}).get("status") == "visit")
    return done, int(c.get("per_week") or 1), s, e


def quota_pace(save: dict, c: dict, d: date) -> tuple[int, int]:
    """(visits still needed this week, allowed days left including today)."""
    done, target, s, e = quota_week(save, c, d)
    days_left = sum(1 for i in range((e - d).days + 1) if not c.get("days") or (d + timedelta(days=i)).weekday() in c["days"])
    if (rec(save, c["id"], d) or {}).get("status") == "visit":
        days_left -= 1
    return max(0, target - done), max(0, days_left)


def settle(save: dict, now: datetime, bank, lf: float) -> list[str]:
    """Close what's over: flakes for missed weekly / one-off slots, quota weeks that ended short.
    Looks back from the last settle (never before a commitment was created). Returns messages."""
    msgs = []
    last = datetime.fromisoformat(save["commit_settled"]) if save.get("commit_settled") else now - timedelta(days=1)
    last = max(last, now - timedelta(days=21))
    for c in items(save, False):
        made = datetime.fromisoformat(c["created"])
        if c["kind"] in ("weekly", "oneoff"):
            d = max(last, made).date()
            while d <= now.date():
                st_ = start_on(c, d, now.tzinfo)
                if st_ and st_ >= made:
                    _, _, end = window(c, st_)
                    if last < end <= now and not (rec(save, c["id"], d) or {}).get("status"):
                        cost = round(STAKES[c["stakes"]]["flake"] * lf)
                        _set(save, c["id"], d, status="flaked", at=end.isoformat(), cost=cost)
                        _streak_after(c, "flaked", end)
                        if cost:
                            bank(save, -cost, f"📍 Flaked: {c['name']} ({d:%a %b} {d.day})")
                            save["rival_heat"] = save.get("rival_heat", 0) + 1
                            msgs.append(f"📍 **Flaked on {c['name']}** ({d:%a}): no check-in, no notice. −{cost}, "
                                        "streak reset, rivals +1 heat.")
                        else:
                            msgs.append(f"📍 Skipped {c['name']} ({d:%a}). Bonus only, so no cost.")
                    if c["kind"] == "oneoff" and end <= now:
                        c["active"] = False  # done with: drops off the list
                d += timedelta(days=1)
        else:  # quota: weeks that ended (Sunday 23:59) since the last settle
            s, e = week_of(max(last, made).date())
            while True:
                end = datetime.combine(e + timedelta(days=1), datetime.min.time(), now.tzinfo)
                if end > now:
                    break
                if last < end and end > made:
                    done, target, _, _ = quota_week(save, c, s)
                    miss = max(0, target - done)
                    first_week = made > datetime.combine(s, datetime.min.time(), now.tzinfo)
                    if miss and not first_week:
                        cost = round(STAKES[c["stakes"]]["flake"] * lf * 0.5 * miss)
                        c["streak"] = 0
                        if cost:
                            bank(save, -cost, f"📍 {c['name']}: {done}/{target} for the week of {s:%b} {s.day}")
                            msgs.append(f"📍 **{c['name']}**: {done}/{target} visits last week. −{cost}, streak reset.")
                    elif not miss:
                        c["streak"] = int(c.get("streak", 0)) + 1
                        c["best"] = max(int(c.get("best", 0)), c["streak"])
                s, e = s + timedelta(days=7), e + timedelta(days=7)
    save["commit_settled"] = now.isoformat()
    return msgs


def attended_on(save: dict, d: date) -> bool:
    """Showing up counts as a finish for the day streak (not toward qualifying)."""
    iso = d.isoformat()
    return any(k.endswith("|" + iso) and r.get("status") in ("attended", "late", "visit")
               for k, r in save.get("attendance", {}).items())


def upcoming(save: dict, now: datetime, days: int = 7) -> list[tuple[dict, datetime]]:
    """Weekly / one-off slots from now on, soonest first (today's still-open ones included)."""
    out = []
    for c in items(save):
        for i in range(days + 1):
            d = now.date() + timedelta(days=i)
            st_ = start_on(c, d, now.tzinfo)
            if st_ and window(c, st_)[2] >= now:
                out.append((c, st_))
    return sorted(out, key=lambda x: x[1])


def rate(save: dict, c: dict, today: date, weeks: int = 8) -> tuple[int, int]:
    """(showed up, counted) over the last `weeks` weeks: cancellations don't count either way."""
    since = today - timedelta(weeks=weeks)
    got = tot = 0
    for k, r in save.get("attendance", {}).items():
        cid, iso = k.split("|")
        if cid != c["id"] or iso < since.isoformat():
            continue
        if r.get("status") in ("attended", "late", "visit"):
            got += 1
            tot += 1
        elif r.get("status") == "flaked":
            tot += 1
    return got, tot
