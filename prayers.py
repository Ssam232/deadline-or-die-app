"""
🕌 Prayer times, computed locally (the PrayTimes.org astronomical method) — no API, works in the app and the nagger.

Windows: Fajr → sunrise · Dhuhr → Asr · Asr → Maghrib · Maghrib → Isha · Isha → 23:30 (so it lands inside the
app's day). Calgary defaults; method and Asr school are settings.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, time as dtime, timedelta

METHODS = {  # name: (fajr angle, isha angle or "+N" minutes after maghrib)
    "ISNA": (15.0, 15.0),
    "MWL": (18.0, 17.0),
    "Egypt": (19.5, 17.5),
    "Karachi": (18.0, 18.0),
    "Umm al-Qura": (18.5, "+90"),
}
ASR = {"Standard": 1, "Hanafi": 2}
NAMES = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
CALGARY = (51.0447, -114.0719)
ISHA_END = dtime(23, 30)
PRAYER_RX = re.compile(r"pray|salah|salat|namaz|🕌", re.I)


def is_prayer_daily(h: dict) -> bool:
    return h.get("kind") == "prayer" or bool(PRAYER_RX.search(h.get("name", "")))


# ── astronomy (degrees in, degrees out) ──
def _sin(d): return math.sin(math.radians(d))
def _cos(d): return math.cos(math.radians(d))
def _tan(d): return math.tan(math.radians(d))
def _asin(x): return math.degrees(math.asin(x))
def _acos(x): return math.degrees(math.acos(x))
def _atan2(y, x): return math.degrees(math.atan2(y, x))
def _acot(x): return math.degrees(math.atan(1 / x))
def _fix(a, b): return a - b * math.floor(a / b)


def _julian(y: int, m: int, d: int) -> float:
    if m <= 2:
        y, m = y - 1, m + 12
    a = math.floor(y / 100)
    b = 2 - a + math.floor(a / 4)
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def _sun(jd: float) -> tuple[float, float]:
    D = jd - 2451545.0
    g = _fix(357.529 + 0.98560028 * D, 360)
    q = _fix(280.459 + 0.98564736 * D, 360)
    L = _fix(q + 1.915 * _sin(g) + 0.020 * _sin(2 * g), 360)
    e = 23.439 - 0.00000036 * D
    ra = _fix(_atan2(_cos(e) * _sin(L), _cos(L)) / 15, 24)
    eqt = q / 15 - ra
    return _asin(_sin(e) * _sin(L)), eqt


def _times(d: date, lat: float, lng: float, tz_hours: float, method: str, asr_school: str) -> dict:
    fajr_a, isha_a = METHODS.get(method, METHODS["ISNA"])
    jd = _julian(d.year, d.month, d.day) - lng / (15 * 24)

    def midday(t):
        return _fix(12 - _sun(jd + t)[1], 24)

    def angle_time(angle, t, ccw=False):
        decl = _sun(jd + t)[0]
        noon = midday(t)
        x = (-_sin(angle) - _sin(decl) * _sin(lat)) / (_cos(decl) * _cos(lat))
        if x < -1 or x > 1:
            return None  # the sun never gets that low (high-latitude summer)
        T = _acos(x) / 15
        return noon + (-T if ccw else T)

    def asr_time(factor, t):
        decl = _sun(jd + t)[0]
        return angle_time(-_acot(factor + _tan(abs(lat - decl))), t)

    t = {"fajr": 5 / 24, "sunrise": 6 / 24, "dhuhr": 12 / 24, "asr": 13 / 24, "sunset": 18 / 24, "isha": 18 / 24}
    out = {
        "Fajr": angle_time(fajr_a, t["fajr"], ccw=True),
        "Sunrise": angle_time(0.833, t["sunrise"], ccw=True),
        "Dhuhr": midday(t["dhuhr"]),
        "Asr": asr_time(ASR.get(asr_school, 1), t["asr"]),
        "Maghrib": angle_time(0.833, t["sunset"]),
    }
    out["Isha"] = (out["Maghrib"] + int(isha_a[1:]) / 60) if isinstance(isha_a, str) else angle_time(isha_a, t["isha"])
    # high latitudes: cap Fajr/Isha at (angle/60) of the night, the "angle-based" rule
    night = 24 - (out["Maghrib"] - out["Sunrise"])
    fa_port = fajr_a / 60 * night
    if out["Fajr"] is None or out["Sunrise"] - out["Fajr"] > fa_port:
        out["Fajr"] = out["Sunrise"] - fa_port
    if not isinstance(isha_a, str):
        is_port = isha_a / 60 * night
        if out["Isha"] is None or out["Isha"] - out["Maghrib"] > is_port:
            out["Isha"] = out["Maghrib"] + is_port
    adj = tz_hours - lng / 15
    out = {k: v + adj for k, v in out.items()}
    out["Dhuhr"] += 1 / 60  # a minute after the sun passes the meridian
    return out


def times_for(d: date, tz, lat: float = CALGARY[0], lng: float = CALGARY[1], method: str = "ISNA",
              asr_school: str = "Standard") -> dict[str, datetime]:
    off = datetime.combine(d, dtime(12, 0), tz).utcoffset().total_seconds() / 3600
    hrs = _times(d, lat, lng, off, method, asr_school)
    base = datetime.combine(d, dtime(0, 0), tz)
    return {k: base + timedelta(minutes=round(v * 60)) for k, v in hrs.items()}


def windows(d: date, tz, **kw) -> list[dict]:
    """The five prayers with [start, end) windows for the day."""
    t = times_for(d, tz, **kw)
    ends = [t["Sunrise"], t["Asr"], t["Maghrib"], t["Isha"], datetime.combine(d, ISHA_END, tz)]
    return [{"name": n, "start": t[n], "end": e, "i": i} for i, (n, e) in enumerate(zip(NAMES, ends))]


def status(count: int, now: datetime, **kw) -> dict:
    """Where you are today: current/next prayer, how many are due, whether the current one is logged."""
    ws = windows(now.date(), now.tzinfo, **kw)
    due = sum(1 for w in ws if w["start"] <= now)
    cur = next((w for w in ws if w["start"] <= now < w["end"]), None)
    nxt = next((w for w in ws if w["start"] > now), None)
    return {"windows": ws, "due": due, "current": cur, "next": nxt,
            "behind": max(0, due - count), "current_logged": bool(cur) and count >= cur["i"] + 1}


def settings_of(save: dict) -> dict:
    s = save.get("settings", {})
    return {"method": s.get("prayer_method", "ISNA"), "asr_school": s.get("prayer_asr", "Standard"),
            "lat": float(s.get("prayer_lat", CALGARY[0])), "lng": float(s.get("prayer_lng", CALGARY[1]))}


def nags(save: dict, mem: dict, now: datetime, count_fn) -> list[tuple]:
    """Escalating pushes for the current prayer while it isn't logged. Breaks quiet hours on purpose."""
    out = []
    habits = [h for h in save.get("habits", []) if is_prayer_daily(h)]
    if not habits:
        return out
    h = habits[0]
    count = count_fn(save, h["id"], now.date())
    st_ = status(count, now, **settings_of(save))
    pm = mem.setdefault("prayer", {})
    if pm.get("date") != now.date().isoformat():
        pm.clear()
        pm["date"] = now.date().isoformat()
    cur = st_["current"]
    if cur and not st_["current_logged"]:
        left = (cur["end"] - now).total_seconds() / 60
        n, tag = cur["name"], f"You're at {count}/{h['target']}."
        if left <= 20:
            last = pm.get(f"{n}_last")
            if not last or (now - datetime.fromisoformat(last)).total_seconds() >= 9 * 60:
                pm[f"{n}_last"] = now.isoformat()
                out.append((f"⏳ {n} ends in {int(left)} min", f"Pray now, then tap +1. {tag}", 5, ["mosque"]))
        elif left <= 45 and not pm.get(f"{n}_45"):
            pm[f"{n}_45"] = True
            out.append((f"🕌 {n} ends in {int(left)} min", f"Don't let it slip. {tag}", 4, ["mosque"]))
        elif not pm.get(f"{n}_start") and (now - cur["start"]).total_seconds() < 40 * 60:
            pm[f"{n}_start"] = True
            out.append((f"🕌 {n} time ({cur['start']:%I:%M %p})".replace("(0", "("),
                        f"Window closes {cur['end']:%I:%M %p}. {tag}".replace(" 0", " "), 3, ["mosque"]))
    # missed: the previous window closed while you were still behind
    prev = [w for w in st_["windows"] if w["end"] <= now]
    if prev:
        p = prev[-1]
        if count < p["i"] + 1 and not pm.get(f"{p['name']}_missed") and (now - p["end"]).total_seconds() < 40 * 60:
            pm[f"{p['name']}_missed"] = True
            out.append((f"🕌 {p['name']} window closed", f"Still {count}/{h['target']}. If you prayed, log it in "
                                                         "the app.", 4, ["mosque"]))
    return out
