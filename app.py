"""
🏁 Deadline or Die — make deadlines deadly.

Every task has a deadline, a reward and a penalty.
  • Prove it's done (photo / screenshot / file / link) → coins + XP → upgrade your car → race your procrastination rivals.
  • Miss it → lose coins, damage the car, reset your streak, and serve your own real-world consequence.
    Debt or unserved penalties = BLACK FLAG (no racing) until you fix it.

Run:  streamlit run app.py
"""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import math
import os
import random
import re
import time
import uuid
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

import board as B
import carart
import contracts as K
import events as EV
import garage as G
import daily
import locks as LK
import lounge as L
import valuation as V
import zotero as Z
from notify import push
from notion_store import (Notion, NotionError, STATUS, archive_page, due_to_dt, ensure_workspace, load_json,
                          pull_rows, save_json, task_props, update_dashboard, upload_proof, upsert_task)

# ─────────────────────────── config ───────────────────────────
TZ = ZoneInfo(os.getenv("DOD_TZ", "America/Edmonton"))
DATA_DIR = Path(os.getenv("DOD_DATA_DIR", Path(__file__).parent / "data"))
PROOF_DIR = DATA_DIR / "proofs"
STATE_FILE = DATA_DIR / "state.json"
RACE_TICK = float(os.getenv("DOD_RACE_TICK", "0.12"))  # seconds per animation frame

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
NOTION_VERSION = "2022-06-28"
DONE_WORDS = {"done", "complete", "completed", "finished", "✅"}

DIFFICULTY = {
    "Quick": {"reward": 20, "penalty": 15, "xp": 10, "hint": "under an hour"},
    "Medium": {"reward": 45, "penalty": 35, "xp": 25, "hint": "one solid session"},
    "Big": {"reward": 100, "penalty": 80, "xp": 60, "hint": "several sessions"},
    "Boss": {"reward": 250, "penalty": 200, "xp": 150, "hint": "major milestone"},
}

PARTS = {
    "engine": {"label": "Engine", "icon": "🔥", "base": 60, "weight": 6, "desc": "Straight-line pace"},
    "tires": {"label": "Tires", "icon": "🛞", "base": 50, "weight": 5, "desc": "Corner grip"},
    "aero": {"label": "Aero", "icon": "🌀", "base": 45, "weight": 4, "desc": "High-speed stability"},
    "brakes": {"label": "Brakes", "icon": "🛑", "base": 40, "weight": 4, "desc": "Late braking"},
    "turbo": {"label": "Forced induction", "icon": "💨", "base": 80, "weight": 5, "desc": "Overtaking punch"},
    "weight": {"label": "Weight reduction", "icon": "🪶", "base": 45, "weight": 4, "desc": "Power-to-weight"},
}
MAX_PART_LEVEL = 5

RIVALS = [
    "Tomorrow Tom", "Snooze Button", "Doomscroll Dan", "Just-One-Episode",
    "Night-Before Nate", "Perfectionist Pat", "Inbox Zero-ish", "Busywork Bella",
    "'Quick Break' Quinn", "Reorganize-My-Desk Rob",
]

# Your garage: a real-model progression, unlocked by driver level + coins. Drawings are stylized silhouettes.
CARS = [
    {"id": "civic_si", "name": "Honda Civic Si", "base": 40, "cost": 0, "level": 1, "body": "sedan",
     "blurb": "Where every Honda guy starts. Rev it out."},
    {"id": "integra_r", "name": "Honda Integra Type R (DC2)", "base": 50, "cost": 400, "level": 2, "body": "coupe",
     "blurb": "Hand-ported legend. Earned, not bought."},
    {"id": "s2000", "name": "Honda S2000", "base": 60, "cost": 900, "level": 3, "body": "roadster",
     "blurb": "9,000 rpm. Roof down, deadlines done."},
    {"id": "ctr", "name": "Honda Civic Type R (FL5)", "base": 72, "cost": 1800, "level": 4, "body": "hatch",
     "blurb": "The wing says it all."},
    {"id": "nsx", "name": "Honda NSX (NA1)", "base": 85, "cost": 3500, "level": 5, "body": "super",
     "blurb": "The one that embarrassed Ferrari."},
    {"id": "nsx_s", "name": "Honda NSX Type S", "base": 100, "cost": 6000, "level": 7, "body": "super",
     "blurb": "Final form of the road car."},
    {"id": "nsx_gt3", "name": "Honda NSX GT3 Evo", "base": 120, "cost": 10000, "level": 9, "body": "gt3",
     "blurb": "The race car. Same class as your rig — park it next to it."},
]
CAR_BY_ID = {c["id"]: c for c in CARS}

TRACKS = [
    {"name": "Parking Lot Sprint", "laps": 3, "level": 1, "fee": 10, "ai": (30, 48), "prize": [60, 30, 15]},
    {"name": "Bow River Circuit", "laps": 5, "level": 2, "fee": 25, "ai": (55, 75), "prize": [150, 75, 35]},
    {"name": "Foothills Grand Prix", "laps": 7, "level": 4, "fee": 60, "ai": (80, 105), "prize": [360, 180, 90]},
    {"name": "Rockies 6 Hours", "laps": 10, "level": 6, "fee": 120, "ai": (115, 150), "prize": [800, 400, 200]},
    {"name": "Thesis Defense Ring", "laps": 12, "level": 8, "fee": 250, "ai": (150, 200), "prize": [2000, 900, 400]},
]

# ── conditioning layer ──
# Rivals are your procrastination habits. Every miss feeds them ("heat" = they race faster).
TAUNTS = [
    "Tomorrow Tom: \"There's always tomorrow, right {name}?\"",
    "Doomscroll Dan just lapped you. He didn't even look up from his phone.",
    "Snooze Button: \"Five more minutes. Then five more. Then the deadline.\"",
    "Night-Before Nate is pocketing your coins. Thanks for the fuel, {name}.",
    "Perfectionist Pat: \"If it couldn't be perfect, why start at all?\"",
    "Just-One-Episode: \"Told you we had time.\"",
    "Reorganize-My-Desk Rob: \"At least your desk looks nice.\"",
    "'Quick Break' Quinn waves from the pit lane. Your car's in the wall.",
]
HYPE = [
    "That's how a closer drives, {name}.",
    "Clean lap. Rivals in the mirror.",
    "Fanatec-level precision. Send it.",
    "Tomorrow Tom just watched you leave him for dead.",
    "Every deadline you hit makes the next one easier. Keep the tires warm.",
    "That's a purple sector, {name}.",
    "The car's getting faster. So are you.",
]
CONSEQUENCE_PRESETS = [
    "(write my own)",
    "🔒 Games locked on PC + phone until it's done",
    "No sim racing until it's done",
    "No gaming (PS5 / Switch) tonight",
    "No manga/manhwa for 24h",
    "Phone in another room all evening",
    "Tell a friend I missed it",
]
STARTER_GOALS_DEFAULT = [  # override with a STARTER_GOALS list in secrets to make these yours
    ("Finish a big writing project", "Future you will thank you."),
    ("Ship a side project", "Done beats perfect."),
    ("Get in shape for a goal date", "Show up for yourself."),
]
# Pit crate after every approved proof — variable-ratio rewards (with a pity timer).
CRATE_TABLE = [  # (weight, kind)
    (52, "coins_small"), (20, "coins_big"), (11, "part"), (8, "shield"), (6, "repair"), (3, "jackpot"),
]
PITY_AFTER = 6               # guarantee a rare drop after this many commons in a row
DANGER_DAYS = {1, 2}         # Tue/Wed: unstructured days → +20% for finishing on them
IDLE_GRACE_DAYS = 2          # car starts rusting after this many days with nothing finished
RUST_PER_DAY = 4

MISS_DAMAGE = 15          # car condition lost per missed deadline
REDEEM_WINDOW_H = 72      # hours after a miss you can still finish it for a partial refund
FREE_DELETE_MIN = 10      # minutes after creating a task you can delete it for free (typo fixes)
GOAL_BONUS = (150, 100)   # coins, xp for finishing a whole goal
REPAIR_COST_PER_PT = 2

PROOF_TYPES = ["png", "jpg", "jpeg", "webp", "gif", "pdf", "txt", "md", "csv", "py", "r", "json",
               "docx", "xlsx", "pptx"]
IMAGE_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
TEXT_EXT = {".txt", ".md", ".csv", ".py", ".r", ".json"}

STEWARD_SYSTEM = (
    "You are the race steward in a productivity game. The player says they finished a real-world task and "
    "submitted proof. Decide whether the evidence reasonably shows THIS task was actually done. Be fair but "
    "skeptical: reject proof that is unrelated to the task, generic, a stock image, or a vague claim with nothing "
    "backing it. Partial evidence is fine only if it clearly shows meaningful work on this exact task. "
    'Reply with JSON only: {"approved": true or false, "confidence": number 0-1, '
    '"comment": "one or two sentences in the voice of a race steward"}'
)

PLANNER_SYSTEM = (
    "You break long-term goals into concrete milestones for someone who procrastinates. Every milestone must be a "
    "specific deliverable that can be proven with a photo, screenshot, file or link. Space them realistically between "
    "today and the target date and front-load small wins so momentum builds. Reply with JSON only: a list of 4-10 "
    'objects {"title": str, "due": "YYYY-MM-DD", "difficulty": "Quick"|"Medium"|"Big"|"Boss", "proof_hint": str}.'
)


# ─────────────────────────── state ───────────────────────────
def default_state() -> dict:
    return {
        "version": 1,
        "coins": 50,
        "xp": 0,
        "streak": 0,
        "best_streak": 0,
        "car": {"name": "Project GT3", "number": 28, "color": "#e63946", "model": "civic_si", "owned": ["civic_si"],
                "parts": {k: 0 for k in PARTS}, "condition": 100},
        "goals": [],
        "tasks": [],
        "penalty_box": [],
        "ledger": [],
        "races": [],
        "proof_hashes": [],
        "rival_heat": 0,
        "shields": 0,
        "since_rare": 0,
        "last_done_date": datetime.now(TZ).date().isoformat(),
        "rust_days": 0,
        "dnfs": 0,
        "settings": {
            "player_name": os.getenv("PLAYER_NAME", "Driver"),
            "sounds": True,
            "grace_minutes": 30,
            "strict_proof": True,
            "ai_steward": True,
            "model": "claude-haiku-5-5",
            "extension_hours": 24,
            "max_extensions": 2,
            "notion_db": "",
            "notion_date_prop": "",
            "notion_done_prop": "",
        },
    }


def _merge(defaults: dict, loaded: dict) -> dict:
    out = dict(defaults)
    for k, v in loaded.items():
        if isinstance(v, dict) and isinstance(defaults.get(k), dict):
            out[k] = _merge(defaults[k], v)
        else:
            out[k] = v
    return out


SESSION_TTL = 20  # seconds before re-reading the save from Notion (and pulling new Notion tasks)


def _load_local() -> dict | None:
    if STATE_FILE.exists():
        try:
            return _merge(default_state(), json.loads(STATE_FILE.read_text()))
        except Exception as e:  # corrupted file: keep a copy, start fresh
            STATE_FILE.rename(STATE_FILE.with_suffix(f".broken-{int(time.time())}.json"))
            st.warning(f"Save file was unreadable ({e}); started fresh and kept a copy.")
    return None


def notion_cfg() -> tuple[str, str] | None:
    token, parent = get_secret("NOTION_TOKEN"), get_secret("NOTION_PARENT_PAGE")
    return (token, parent) if token and parent else None


@st.cache_resource(show_spinner="Setting up your Notion workspace…")
def _workspace(token: str, parent: str) -> dict:
    return ensure_workspace(Notion(token), parent)


@st.cache_data(ttl=3600, show_spinner=False)
def _board_map(token: str, db: str) -> dict:
    return B.detect(Notion(token), db)


@st.cache_data(ttl=300, show_spinner=False)
def _board_today(token: str, db: str, day_iso: str) -> list[dict]:
    m = _board_map(token, db)
    return B.pull_day(Notion(token), m, date.fromisoformat(day_iso))


@st.cache_data(ttl=600, show_spinner=False)
def _zotero_list(user: str, key: str, coll: str) -> list[dict]:
    return Z.to_read(user, key, coll)


def zotero_cfg(state: dict) -> tuple[str, str, str] | None:
    u, k = get_secret("ZOTERO_USER_ID"), get_secret("ZOTERO_API_KEY")
    return (str(u), k, state["settings"].get("zotero_collection") or "To Read") if u and k else None


def board_cfg(state: dict) -> tuple[str, str] | None:
    db, token = state["settings"].get("board_db"), get_secret("NOTION_TOKEN")
    return (token, db) if db and token else None


def notion_ctx() -> tuple[Notion, dict] | None:
    cfg = notion_cfg()
    return (Notion(cfg[0]), _workspace(*cfg)) if cfg else None


def load_state() -> dict:
    """Notion save if configured (cached per session for SESSION_TTL), else the local file."""
    if not notion_cfg():
        return _load_local() or default_state()
    cached = st.session_state.get("_state")
    if cached is not None and time.time() - st.session_state.get("_state_ts", 0) < SESSION_TTL:
        return cached
    try:
        n, ids = notion_ctx()
        data = load_json(n, ids["save_page"])
    except Exception as e:
        # Never fall back to a blank game here — a later save would overwrite the real one.
        st.error(f"Can't reach your Notion save right now: {e}")
        st.button("Retry")
        st.stop()
    if data is None:  # first run on Notion: carry over any local progress
        data = _load_local() or default_state()
        st.session_state["_needs_save"] = True
    state = _merge(default_state(), data)
    st.session_state["_state"], st.session_state["_state_ts"] = state, time.time()
    st.session_state["_fresh_load"] = True
    return state


def _push_tasks(n: Notion, ids: dict, state: dict) -> list[str]:
    errors = []
    for t in state["tasks"]:
        goal = goal_title(state, t.get("goal_id"))
        sig = hashlib.md5(json.dumps(task_props(t, goal), sort_keys=True, default=str).encode()).hexdigest()
        if t.get("_sig") == sig and t.get("sync_page"):
            continue
        try:
            upsert_task(n, ids["tasks_db"], t, goal)
        except NotionError:
            try:  # row was deleted in Notion — deleting it there doesn't get you out of it
                t.pop("sync_page", None)
                upsert_task(n, ids["tasks_db"], t, goal)
            except NotionError as e:
                errors.append(f"{t['title']}: {e}")
                continue
        t["_sig"] = sig
    return errors


def broadcast_lock(state: dict) -> None:
    for p in state.get("penalty_box", []):  # enforced locks expire after 24h
        if p.get("enforced") and not p["served"] and now() - parse_dt(p["created"]) >= timedelta(hours=LK.LOCK_HOURS):
            p.update(served=True, served_at=now().isoformat(), how="expired")
    st_ = LK.status(state, now())
    msg = LK.message(st_)
    if msg != state.get("_lock_msg") and LK.publish(get_secret("NTFY_TOPIC"), st_):
        state["_lock_msg"] = msg


def save_state(state: dict) -> None:
    broadcast_lock(state)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    os.replace(tmp, STATE_FILE)
    if not notion_cfg():
        return
    try:
        n, ids = notion_ctx()
        errs = _push_tasks(n, ids, state)
        bc = board_cfg(state)
        if bc:
            try:
                errs += B.sync_out(n, _board_map(*bc), state["tasks"], now())
            except Exception as e:  # board problems never block saving
                errs.append(f"board: {e}")
        save_json(n, ids["save_page"], state)
        st.session_state["_state"], st.session_state["_state_ts"] = state, time.time()
        if ids.get("dashboard"):
            try:
                update_dashboard(n, ids["dashboard"], state, TZ, get_secret("APP_URL"))
            except NotionError:
                pass
        if errs:
            flash("⚠️ Some tasks didn't sync to Notion: " + "; ".join(errs[:3]), "warning")
    except Exception as e:
        flash(f"⚠️ Couldn't save to Notion ({e}). Your progress is kept on this server for now.", "error")


def sync_from_notion(state: dict) -> tuple[list[tuple[str, str]], bool]:
    """Pull new rows added in Notion; undo cheating (Done without proof, moved dates, deleted rows)."""
    n, ids = notion_ctx()
    rows = pull_rows(n, ids["tasks_db"])
    seen = {r["page_id"] for r in rows}
    mine = {t["sync_page"]: t for t in state["tasks"] if t.get("sync_page")}
    msgs, changed, no_date = [], False, 0
    for r in rows:
        t = mine.get(r["page_id"])
        if t is None:
            if r["app_id"] or r["status"] in ("Done", "Failed", "Redeemed"):
                continue
            if not r["due"]:
                no_date += 1
                continue
            dl = due_to_dt(r["due"], TZ)
            if dl <= now() + timedelta(minutes=5):
                msgs.append(("warning", f"Notion task **{r['title'] or '(untitled)'}** has a past due date — "
                                        "give it a future one to bring it into the game."))
                continue
            size = r["size"] if r["size"] in DIFFICULTY else "Medium"
            t = make_task(r["title"] or "(untitled)", "", dl, size, r["consequence"], source="notion-sync",
                          category=r.get("category"), minutes=r.get("minutes"))
            t["sync_page"] = r["page_id"]
            if r.get("created"):  # the clock starts when you wrote it down in Notion, not when the app saw it
                t["created"] = parse_dt(r["created"]).astimezone(TZ).isoformat()
            state["tasks"].append(t)
            changed = True
            msgs.append(("info", f"📥 Pulled **{t['title']}** in from Notion — due {dl:%a %b %d, %I:%M %p}, "
                                 f"+{t['reward']}/−{t['penalty']}."))
            continue
        if r["title"] and r["title"] != t["title"]:
            t["title"], changed = r["title"], True
        if r["status"] != STATUS.get(t["status"]):
            if t["status"] == "open" and r["status"] in ("Done", "Redeemed"):
                msgs.append(("error", f"🚩 You ticked **{t['title']}** off in Notion. Nice try — proof happens "
                                      "in the app. Flipped back to Open."))
            t.pop("_sig", None)
            changed = True
        elif r["due"] and abs((due_to_dt(r["due"], TZ) - parse_dt(t["deadline"])).total_seconds()) > 60:
            msgs.append(("warning", f"⏳ Moving **{t['title']}**'s date in Notion doesn't count — deadlines only "
                                    "move by buying an extension. Put it back."))
            t.pop("_sig", None)
            changed = True
    for page, t in mine.items():
        if page not in seen and t["status"] == "open":
            try:
                n.req("PATCH", f"/pages/{page}", json={"archived": False})
            except NotionError:
                t.pop("sync_page", None)
            t.pop("_sig", None)
            changed = True
            msgs.append(("error", f"🚩 Deleting **{t['title']}** in Notion doesn't delete the deadline. It's back."))
    if no_date:
        msgs.append(("info", f"{no_date} Notion task(s) have no Due date — add one and they'll join the game."))
    return msgs, changed


# ─────────────────────────── helpers ───────────────────────────
def now() -> datetime:
    return datetime.now(TZ)


def parse_dt(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def to_date(v) -> date | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.date()
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def fmt_left(td: timedelta) -> str:
    secs = int(td.total_seconds())
    sign = "-" if secs < 0 else ""
    secs = abs(secs)
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        out = f"{d}d {h}h"
    elif h:
        out = f"{h}h {m}m"
    else:
        out = f"{m}m"
    return f"{sign}{out}"


def chip(deadline: datetime) -> str:
    hrs = (deadline - now()).total_seconds() / 3600
    if hrs < 0:
        return "💀"
    if hrs < 12:
        return "🔴"
    if hrs < 48:
        return "🟡"
    return "🟢"


def level_of(xp: int) -> int:
    return int(math.sqrt(max(xp, 0) / 50)) + 1


def xp_for_level(lvl: int) -> int:
    return 50 * (lvl - 1) ** 2


def bank(state: dict, delta: int, reason: str) -> None:
    state["coins"] += int(delta)
    state["ledger"].insert(0, {"ts": now().isoformat(), "delta": int(delta), "reason": reason})
    del state["ledger"][300:]


def car_rating(state: dict) -> float:
    car = state["car"]
    mid = car.get("model") if car.get("model") in CAR_BY_ID else CARS[0]["id"]
    eff = G.effective(car["parts"], mid)
    raw = CAR_BY_ID[mid]["base"] + sum(eff[k] * PARTS[k]["weight"] for k in PARTS)
    return raw * (0.55 + 0.45 * car["condition"] / 100)


def part_cost(part: str, lvl: int) -> int:
    return int(PARTS[part]["base"] * 2 ** lvl)


def goal_title(state: dict, gid: str | None) -> str:
    for g in state["goals"]:
        if g["id"] == gid:
            return g["title"]
    return ""


def get_secret(name: str) -> str | None:
    v = st.session_state.get(f"secret_{name}")
    if v:
        return v
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    return v or os.getenv(name)


def starter_goals() -> list[tuple[str, str]]:
    """Your real goals live in secrets (STARTER_GOALS = [["Goal", "Why"], ...]), not in public code."""
    raw = get_secret("STARTER_GOALS")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    try:
        goals = [(str(g[0]), str(g[1]) if len(g) > 1 else "") for g in (raw or [])]
    except (TypeError, IndexError, KeyError):
        goals = []
    return goals or STARTER_GOALS_DEFAULT


def flash(msg: str, kind: str = "success", celebrate: bool = False, sound: str | None = None) -> None:
    st.session_state.setdefault("flash", []).append((kind, msg))
    if celebrate:
        st.session_state["celebrate"] = True
    if sound:
        st.session_state["sound"] = sound


def make_task(title, details, deadline: datetime, difficulty=None, consequence="", goal_id=None,
              source="manual", notion=None, category=None, minutes=None) -> dict:
    minutes = int(minutes or V.minutes_for_size(difficulty))
    category = category if category in V.CATEGORIES else V.guess_category(title)
    d = V.value(category, minutes)
    difficulty = V.size_label(minutes)
    t = {
        "id": uuid.uuid4().hex[:10],
        "title": title.strip(),
        "details": details.strip(),
        "goal_id": goal_id,
        "deadline": deadline.isoformat(),
        "created": now().isoformat(),
        "difficulty": difficulty,
        "reward": d["reward"],
        "penalty": d["penalty"],
        "xp": d["xp"],
        "consequence": consequence.strip(),
        "status": "open",
        "extensions": 0,
        "rejections": 0,
        "source": source,
        "category": category,
        "minutes": minutes,
        "focus_min": 0,
    }
    if notion:
        t.update(notion)
    return t


# ─────────────────────────── game rules ───────────────────────────
def fail_task(state: dict, t: dict, reason: str) -> str:
    t["status"] = "failed"
    t["failed_at"] = now().isoformat()
    t["penalty"] = round(t["penalty"] * daily.level_factor(state))  # pros pay more for misses
    bank(state, -t["penalty"], f"💀 {reason}: {t['title']}")
    state["car"]["condition"] = max(0, state["car"]["condition"] - MISS_DAMAGE)
    state["rival_heat"] += 1
    state["dnfs"] += 1
    lost_streak = state["streak"]
    if state["shields"] > 0 and lost_streak:
        state["shields"] -= 1
        streak_line = f"🛡️ Streak shield absorbed the hit — {lost_streak}-streak survives ({state['shields']} left)."
    else:
        state["streak"] = 0
        streak_line = f"Your **{lost_streak}-task streak is gone.**" if lost_streak else "Streak: 0."
    if t.get("consequence"):
        state["penalty_box"].append({"id": uuid.uuid4().hex[:8], "task": t["title"], "task_id": t["id"],
                                     "consequence": t["consequence"], "created": now().isoformat(),
                                     "served": False,
                                     "enforced": t["consequence"].startswith(LK.ENFORCED_MARK)})
    name = state["settings"].get("player_name") or "driver"
    msg = (f"### 💀 DNF — {reason.lower()}\n**{t['title']}**\n\n"
           f"−{t['penalty']} coins · −{MISS_DAMAGE}% car condition · {streak_line}\n\n"
           f"🔥 Your rivals got faster (heat {state['rival_heat']}).  \n"
           f"*{random.choice(TAUNTS).format(name=name)}*")
    if t.get("consequence"):
        msg += f"\n\n🚨 **Penalty box:** {t['consequence']}"
    if reason != "Abandoned":
        msg += f"\n\n🩹 You have {REDEEM_WINDOW_H}h to finish it anyway and claw back half."
    return msg


def process_rust(state: dict) -> str | None:
    """Loss aversion: an idle car rusts. Finishing anything resets the clock."""
    idle = (now().date() - date.fromisoformat(state["last_done_date"])).days
    due = max(0, idle - IDLE_GRACE_DAYS)
    new = due - state["rust_days"]
    if new <= 0:
        return None
    state["rust_days"] = due
    loss = RUST_PER_DAY * new
    state["car"]["condition"] = max(0, state["car"]["condition"] - loss)
    return (f"🟫 Nothing finished in {idle} days. Your car's been sitting in the garage rusting: "
            f"−{loss}% condition. Finish *anything* to stop it.")


def open_crate(state: dict, t: dict) -> str:
    """Variable-ratio reward after every approved proof."""
    rare = {"part", "shield", "repair", "jackpot"}
    if state["since_rare"] >= PITY_AFTER:
        pool = [(w, k) for w, k in CRATE_TABLE if k in rare]
    else:
        pool = CRATE_TABLE
    kind = random.choices([k for _, k in pool], weights=[w for w, _ in pool])[0]
    state["since_rare"] = 0 if kind in rare else state["since_rare"] + 1
    car = state["car"]
    if kind == "coins_small":
        n = random.randint(5, 15)
        bank(state, n, "📦 Pit crate")
        return f"📦 Pit crate: **+{n} coins**"
    if kind == "coins_big":
        n = max(20, t["reward"] // 2)
        bank(state, n, "📦 Pit crate (big)")
        return f"📦✨ Big crate: **+{n} coins**"
    if kind == "part":
        open_parts = [k for k in PARTS if car["parts"][k] < MAX_PART_LEVEL]
        if not open_parts:
            bank(state, 150, "📦 Pit crate (parts maxed)")
            return "📦💎 Rare crate: parts maxed, so **+150 coins**"
        k = random.choice(open_parts)
        car["parts"][k] += 1
        return f"📦💎 **RARE DROP — free {PARTS[k]['icon']} {PARTS[k]['label']} upgrade → L{car['parts'][k]}**"
    if kind == "shield":
        state["shields"] += 1
        return f"📦🛡️ **RARE DROP — streak shield** (you have {state['shields']}). Absorbs one miss."
    if kind == "repair":
        car["condition"] = min(100, car["condition"] + 25)
        return "📦🔧 **RARE DROP — pit crew repair, +25% condition**"
    n = t["reward"] * 3
    bank(state, n, "📦 JACKPOT")
    return f"📦💰💰💰 **JACKPOT — +{n} coins!!!**"


def tone_wav(notes: tuple) -> bytes:
    """Signature sounds — same cue every time so the brain learns it."""
    import struct
    import wave
    rate, frames = 22050, bytearray()
    for freq, dur in notes:
        n = int(rate * dur)
        for i in range(n):
            env = min(1.0, i / 300) * min(1.0, (n - i) / 900)
            v = 0.35 * env * (math.sin(2 * math.pi * freq * i / rate)
                              + 0.3 * math.sin(4 * math.pi * freq * i / rate))
            frames += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


SOUNDS = {
    "win": ((523, .08), (659, .08), (784, .08), (1047, .25)),
    "jackpot": ((784, .07), (988, .07), (1175, .07), (1568, .07), (1175, .07), (1568, .35)),
    "fail": ((196, .28), (147, .55)),
}


def process_overdue(state: dict) -> list[str]:
    grace = timedelta(minutes=state["settings"]["grace_minutes"])
    msgs = []
    for t in state["tasks"]:
        if t["status"] == "open" and now() > parse_dt(t["deadline"]) + grace:
            msgs.append(fail_task(state, t, "Missed deadline"))
    return msgs


def black_flag_reasons(state: dict) -> list[str]:
    reasons = []
    if state["coins"] < 0:
        reasons.append(f"you're {abs(state['coins'])} coins in debt")
    unserved = [p for p in state["penalty_box"] if not p["served"]]
    if unserved:
        reasons.append(f"{len(unserved)} real-world penalt{'y' if len(unserved) == 1 else 'ies'} not served")
    if state["car"]["condition"] < 20:
        reasons.append("your car is wrecked (under 20%) — repair it in the Garage")
    return reasons


def compute_reward(state: dict, t: dict, at: datetime) -> tuple[int, str]:
    base = t["reward"]
    hours_early = (parse_dt(t["deadline"]) - at).total_seconds() / 3600
    early = 0.25 if hours_early >= 24 else 0.10 if hours_early >= 6 else 0.0
    danger = 0.20 if at.weekday() in DANGER_DAYS else 0.0
    streak_mult = 1 + 0.1 * min(state["streak"], 10)
    ext_cut = 1 - 0.15 * t.get("extensions", 0)
    paid_today = sum(x.get("minutes") or 60 for x in state["tasks"] if x.get("status") == "done"
                     and (x.get("completed_at") or "")[:10] == at.date().isoformat())
    guard, guard_why = V.payout(base, t, parse_dt(t["created"]), at, paid_today, t.get("focus_min", 0))
    t["_guard"] = guard
    dbl = 2 if EV.is_double(at) else 1
    tok = state.setdefault("tokens", {"double": 0, "upgrade": 0})
    used_token = False
    if dbl == 1 and tok.get("double", 0) > 0:
        tok["double"] -= 1
        dbl, used_token = 2, True
    t["_guard"] = guard * dbl
    total = int(round(base * (1 + early + danger) * streak_mult * ext_cut * guard * dbl))
    parts = [f"base {base}"] + guard_why + (["×2 ⚡ token"] if used_token else ["×2 ⚡ event"] if dbl == 2 else [])
    if early:
        parts.append(f"+{int(early * 100)}% early")
    if danger:
        parts.append("+20% danger-day")
    if state["streak"]:
        parts.append(f"×{streak_mult:.1f} streak")
    if t.get("extensions"):
        parts.append(f"−{int((1 - ext_cut) * 100)}% extensions")
    return total, ", ".join(parts)


# ─────────────────────────── Claude (optional) ───────────────────────────
def claude(messages: list, system: str, model: str, max_tokens: int = 700) -> str:
    key = get_secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No ANTHROPIC_API_KEY set")
    r = requests.post(
        ANTHROPIC_URL,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens, "system": system, "messages": messages},
        timeout=90,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Claude API {r.status_code}: {r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


def extract_json(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if not m:
            raise ValueError(f"No JSON in reply: {text[:200]}")
        return json.loads(m.group(1))


def shrink_image(data: bytes) -> tuple[bytes, str]:
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    im.thumbnail((1568, 1568))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def ai_verify(state: dict, t: dict, note: str, link: str, data: bytes | None, filename: str, mime: str) -> dict:
    content = []
    if data:
        ext = Path(filename).suffix.lower()
        if mime in IMAGE_MIME:
            img, img_mime = shrink_image(data)
            content.append({"type": "image", "source": {"type": "base64", "media_type": img_mime,
                                                        "data": base64.b64encode(img).decode()}})
        elif mime == "application/pdf" and len(data) < 20_000_000:
            content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                           "data": base64.b64encode(data).decode()}})
        elif ext in TEXT_EXT:
            content.append({"type": "text", "text": f"Attached file {filename}:\n"
                                                    f"{data.decode('utf-8', 'replace')[:8000]}"})
        else:
            content.append({"type": "text", "text": f"(Attached {filename}, type {mime}, can't be displayed. "
                                                    "Judge from the note and link.)"})
    content.append({"type": "text", "text": (
        f"TASK: {t['title']}\nDETAILS: {t.get('details') or '-'}\n"
        f"GOAL: {goal_title(state, t.get('goal_id')) or '-'}\n"
        f"DEADLINE: {t['deadline']}\nSUBMITTED: {now().isoformat()}\n"
        f"PLAYER NOTE: {note}\nLINK: {link or '-'}\n\nVerdict?")})
    out = extract_json(claude([{"role": "user", "content": content}], STEWARD_SYSTEM,
                              state["settings"]["model"], 400))
    return {"approved": bool(out.get("approved")), "confidence": float(out.get("confidence", 0)),
            "comment": str(out.get("comment", ""))}


def ai_plan(state: dict, goal: dict, extra: str) -> list[dict]:
    prompt = (f"GOAL: {goal['title']}\nWHY IT MATTERS: {goal.get('why') or '-'}\n"
              f"TODAY: {now().date().isoformat()}\nTARGET DATE: {goal['target']}\n"
              f"CONTEXT: {extra or '-'}")
    out = extract_json(claude([{"role": "user", "content": prompt}], PLANNER_SYSTEM,
                              state["settings"]["model"], 1500))
    return out if isinstance(out, list) else out.get("milestones", [])


# ─────────────────────────── Notion (optional) ───────────────────────────
def clean_notion_id(s: str) -> str:
    from notion_store import clean_id
    return clean_id(s)


def notion_headers() -> dict:
    token = get_secret("NOTION_TOKEN")
    if not token:
        raise RuntimeError("No NOTION_TOKEN set (Settings tab or .streamlit/secrets.toml).")
    return {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json"}


def _notion_err(r) -> str:
    try:
        return f"Notion {r.status_code}: {r.json().get('message')}"
    except Exception:
        return f"Notion {r.status_code}: {r.text[:200]}"


def notion_fetch(db: str) -> list[dict]:
    headers, out, cursor = notion_headers(), [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{clean_notion_id(db)}/query",
                          headers=headers, json=body, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(_notion_err(r))
        data = r.json()
        out += data.get("results", [])
        if not data.get("has_more"):
            return out
        cursor = data.get("next_cursor")


def notion_parse(page: dict, date_prop: str, done_prop: str) -> dict:
    props = page.get("properties", {})
    title = "".join(x.get("plain_text", "") for p in props.values() if p.get("type") == "title"
                    for x in p.get("title", []))
    dp = props.get(date_prop) if date_prop else next((p for p in props.values() if p.get("type") == "date"), None)
    start = ((dp or {}).get("date") or {}).get("start") if (dp or {}).get("type") == "date" else None
    done, done_type = False, None
    fp = props.get(done_prop) if done_prop else None
    if fp:
        done_type = fp.get("type")
        if done_type == "checkbox":
            done = bool(fp.get("checkbox"))
        elif done_type in ("status", "select"):
            done = ((fp.get(done_type) or {}).get("name", "")).lower() in DONE_WORDS
    return {"notion_id": page["id"], "title": title.strip() or "(untitled)", "due": start,
            "done": done, "done_type": done_type}


def notion_mark_done(state: dict, t: dict) -> str | None:
    prop, typ = state["settings"].get("notion_done_prop"), t.get("notion_done_type")
    if not t.get("notion_id") or not prop or not typ:
        return None
    value = {"checkbox": {"checkbox": True}, "status": {"status": {"name": "Done"}},
             "select": {"select": {"name": "Done"}}}.get(typ)
    if not value:
        return None
    try:
        r = requests.patch(f"https://api.notion.com/v1/pages/{t['notion_id']}", headers=notion_headers(),
                           json={"properties": {prop: value}}, timeout=30)
        return None if r.status_code == 200 else _notion_err(r)
    except Exception as e:
        return str(e)


# ─────────────────────────── car art ───────────────────────────
BODIES = {
    "sedan": ('M18 84 L22 64 Q26 54 48 52 L104 46 Q128 28 170 26 Q205 26 232 44 L286 54 Q306 58 308 74 L306 84 Z',
              'M112 47 Q132 32 168 31 Q196 31 218 45 Z'),
    "coupe": ('M18 84 L22 66 Q28 56 52 54 L112 48 Q140 32 176 31 Q206 33 226 48 L288 56 Q306 60 308 74 L306 84 Z',
              'M120 49 Q144 36 174 35 Q200 37 216 48 Z'),
    "roadster": ('M18 84 L22 68 Q30 60 60 58 L150 56 L168 50 L176 56 L288 60 Q306 63 308 74 L306 84 Z',
                 'M150 56 L166 40 L170 41 L160 56 Z'),
    "hatch": ('M18 84 L20 56 Q22 46 44 44 L100 42 Q126 26 168 25 Q206 26 232 42 L286 52 Q306 56 308 72 L306 84 Z',
              'M106 43 Q130 30 166 29 Q196 30 218 43 Z'),
    "super": ('M16 84 L20 72 Q40 64 90 60 Q130 42 172 40 Q214 42 246 58 L300 66 Q312 72 310 84 Z',
              'M134 57 Q158 45 186 45 Q208 47 226 58 Z'),
    "gt3": ('M12 86 L16 72 Q38 63 90 59 Q130 41 172 39 Q214 41 246 57 L302 65 Q316 72 314 86 Z',
            'M134 56 Q158 44 186 44 Q208 46 226 57 Z'),
}


def car_svg(car: dict) -> str:
    mid = car.get("model") if car.get("model") in CAR_BY_ID else CARS[0]["id"]
    return carart.car_svg(CAR_BY_ID[mid]["body"], car["color"], car["number"], G.effective(car["parts"], mid),
                          car["condition"])


# ─────────────────────────── UI pieces ───────────────────────────
def render_proof_form(state: dict, t: dict, mode: str, scope: str = "") -> None:
    """mode: 'open' (normal completion) or 'redeem' (finishing a missed task for a partial refund)."""
    s = state["settings"]
    k = f"{scope}{mode}_{t['id']}"
    use_ai = s["ai_steward"] and bool(get_secret("ANTHROPIC_API_KEY"))
    note = st.text_area("What did you do?", key=f"note_{k}", placeholder="Be specific — the steward reads this.")
    up = st.file_uploader("Proof file (photo, screenshot, PDF, code…)", type=PROOF_TYPES, key=f"file_{k}")
    link = st.text_input("Link (optional — commit, Google Doc, Overleaf…)", key=f"link_{k}")
    honor = True
    if use_ai:
        st.caption("🧑‍⚖️ The AI race steward will review this proof.")
    else:
        honor = st.checkbox("On my honor (and my car's paint job), this proof is real.", key=f"honor_{k}")
    if not st.button("📸 Submit proof", key=f"submit_{k}", type="primary"):
        return

    errors, data, h = [], None, None
    if len(note.strip()) < 15:
        errors.append("Write at least a real sentence about what you did.")
    if not up and (t.get("minutes") or 0) >= V.FILE_REQUIRED_FROM:
        errors.append(f"Tasks of {V.FILE_REQUIRED_FROM}+ min need a real file as proof (screenshot, doc, photo).")
    elif s["strict_proof"] and not up:
        errors.append("Strict mode: attach a file (turn off in Settings if you must).")
    if not up and not link.strip():
        errors.append("Attach a file or a link.")
    if up:
        data = up.getvalue()
        h = hashlib.sha256(data).hexdigest()
        if h in state["proof_hashes"]:
            errors.append("That exact file was already used as proof for another task. Nice try. 🚩")
    if not honor:
        errors.append("Tick the honor box.")
    if errors:
        for e in errors:
            st.error(e)
        return

    verdict = None
    if use_ai:
        with st.spinner("Race steward reviewing your proof…"):
            try:
                verdict = ai_verify(state, t, note, link, data, up.name if up else "", up.type if up else "")
            except Exception as e:
                st.error(f"Steward unreachable: {e}. Try again, or turn off the AI steward in Settings.")
                return
        if not verdict["approved"]:
            t["rejections"] = t.get("rejections", 0) + 1
            save_state(state)
            st.error(f"🚩 Proof rejected — {verdict['comment']}")
            return

    # ✅ accepted
    proof_path = None
    if up:
        PROOF_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", up.name)[-60:]
        proof_path = str(PROOF_DIR / f"{t['id']}_{safe}")
        Path(proof_path).write_bytes(data)
        state["proof_hashes"].append(h)
    at = now()
    old_level = level_of(state["xp"])
    t.update({"completed_at": at.isoformat(), "proof_note": note.strip(), "proof_link": link.strip(),
              "proof_file": proof_path, "verdict": verdict})
    if mode == "open":
        reward, why = compute_reward(state, t, at)
        bank(state, reward, f"🏁 Done: {t['title']}")
        g_ = t.pop("_guard", 1.0)
        xp_gain = max(1, round(t["xp"] * (min(1.0, g_) if g_ < 1.5 else 2)))
        state["xp"] += xp_gain
        state["streak"] += 1
        state["best_streak"] = max(state["best_streak"], state["streak"])
        t["status"], t["earned"] = "done", reward
        name = state["settings"].get("player_name") or "driver"
        g = goal_title(state, t.get("goal_id"))
        msg = (f"### 🏁 CHECKERED FLAG\n**{t['title']}**\n\n"
               f"**+{reward} coins** ({why}) · +{xp_gain} XP · streak **{state['streak']}** 🔥\n\n"
               f"*{random.choice(HYPE).format(name=name)}*")
        if g:
            mine = [x for x in state["tasks"] if x.get("goal_id") == t.get("goal_id")]
            msg += f"\n\n🎯 One lap closer to **{g}** ({sum(x['status'] == 'done' for x in mine)}/{len(mine)})."
        crate = open_crate(state, t)
        msg += f"\n\n{crate}"
        claims = state.setdefault("event_claims", [])
        for e in EV.active(at):
            if e["type"] == "bounty" and t.get("category") == "deep" and e["id"] not in claims:
                claims.append(e["id"])
                bank(state, EV.BOUNTY, "🎯 Bounty")
                msg += f"\n\n🎯 **BOUNTY CLAIMED: +{EV.BOUNTY}.** Tomorrow Tom pays up."
        if state["rival_heat"]:
            state["rival_heat"] -= 1
            msg += f"\n\n❄️ You took speed back from the rivals (heat {state['rival_heat']})."
        sound = "jackpot" if ("JACKPOT" in crate or "RARE" in crate) else "win"
    else:
        refund = t["penalty"] // 2
        bank(state, refund, f"🩹 Redeemed: {t['title']}")
        state["xp"] += t["xp"] // 2
        t["status"], t["earned"] = "redeemed", refund
        for p in state["penalty_box"]:
            if p.get("task_id") == t["id"] and not p["served"]:
                p.update(served=True, served_at=now().isoformat(), how="redeemed")
        msg = f"🩹 Redeemed **{t['title']}** — +{refund} coins back, +{t['xp'] // 2} XP. Late, but done."
        sound = "win"
    state["last_done_date"] = at.date().isoformat()
    state["rust_days"] = 0
    if verdict:
        msg += f"\n\n🧑‍⚖️ Steward: *{verdict['comment']}*"
    if level_of(state["xp"]) > old_level:
        msg += f"\n\n⬆️ **Driver level {level_of(state['xp'])}!** Check the Race tab for new tracks."
    if t.get("zotero_key") and zotero_cfg(state):
        try:
            zc = zotero_cfg(state)
            Z.mark_read(zc[0], zc[1], t["zotero_key"])
            _zotero_list.clear()
            msg += "\n\n📄 Tagged **read** in Zotero."
        except Exception as e:
            msg += f"\n\n(Couldn't tag it in Zotero: {e})"
    err = notion_mark_done(state, t)
    if err:
        msg += f"\n\n(Couldn't tick it off in your Notion list: {err})"
    if up and t.get("sync_page") and notion_cfg():
        try:
            n, _ = notion_ctx()
            fname = up.name
            body, ctype = (shrink_image(data) if up.type in IMAGE_MIME else (data, up.type or "application/octet-stream"))
            if up.type in IMAGE_MIME:
                fname = Path(up.name).stem + ".jpg"
            upload_proof(n, t["sync_page"], fname, body, ctype)
        except Exception as e:
            msg += f"\n\n(Proof file didn't upload to Notion: {e})"
    save_state(state)
    # Reward hits the phone too — the buzz becomes the cue.
    plain_msg = re.sub(r"[*#]", "", msg.split("\n\n🧑‍⚖️")[0]).replace("CHECKERED FLAG\n", "")
    push(get_secret("NTFY_TOPIC"), "🏁 Checkered flag" if mode == "open" else "🩹 Redeemed", plain_msg.strip(),
         priority=4 if sound == "jackpot" else 3,
         tags=["checkered_flag", "moneybag"] if sound == "jackpot" else ["checkered_flag"],
         click=get_secret("APP_URL"))
    flash(msg, celebrate=(mode == "open"), sound=sound)
    st.rerun()


CAT_OPTS = ["auto"] + list(V.CATEGORIES)


def cat_label(k: str) -> str:
    return "✨ Auto (guess from title)" if k == "auto" else V.CATEGORIES[k]["label"]


def min_label(m: int) -> str:
    return f"{m} min" if m < 60 else f"{m / 60:g} h"


def points_guide() -> None:
    with st.expander("💰 What's it worth? (points guide)"):
        st.markdown(V.guide_markdown())


def task_form(state: dict, key: str, goal_id: str | None = None) -> None:
    with st.form(key, clear_on_submit=True):
        title = st.text_input("Task", placeholder="e.g. Draft the methods section")
        details = st.text_area("Details / what counts as done", height=70)
        if goal_id is None and state["goals"]:
            opts = ["(no goal)"] + [g["title"] for g in state["goals"]]
            pick = st.selectbox("Part of goal", opts)
            gid = None if pick == "(no goal)" else state["goals"][opts.index(pick) - 1]["id"]
        else:
            gid = goal_id
        c1, c2 = st.columns(2)
        d = c1.date_input("Due date", value=now().date() + timedelta(days=1), min_value=now().date())
        tm = c2.time_input("Due time", value=dtime(23, 59))
        c3, c4 = st.columns(2)
        cat = c3.selectbox("Category", CAT_OPTS, format_func=cat_label, key=f"{key}_cat")
        mins = c4.select_slider("Honest time it'll take", V.MINUTES, value=60, format_func=min_label, key=f"{key}_min")
        preset = st.selectbox("Real-world consequence if I miss it", CONSEQUENCE_PRESETS, index=1)
        custom = st.text_input("…or write your own", placeholder="Overrides the preset if filled in")
        cons = custom.strip() or ("" if preset == CONSEQUENCE_PRESETS[0] else preset)
        if st.form_submit_button("➕ Add task", type="primary"):
            dl = datetime.combine(d, tm, TZ)
            if not title.strip():
                st.error("Give it a name.")
            elif dl <= now() + timedelta(minutes=5):
                st.error("Deadline has to be in the future.")
            else:
                t = make_task(title, details, dl, None, cons, gid, category=None if cat == "auto" else cat, minutes=mins)
                state["tasks"].append(t)
                save_state(state)
                flash(f"Added **{t['title']}** · {V.CATEGORIES[t['category']]['label']} · {min_label(t['minutes'])} "
                      f"→ worth **+{t['reward']}** / −{t['penalty']} · due {dl:%a %b %d, %I:%M %p}.")
                st.rerun()


def notion_import(state: dict) -> None:
    s = state["settings"]
    if not (s["notion_db"] and get_secret("NOTION_TOKEN")):
        if notion_cfg():
            st.caption("Your 🏁 Deadline or Die table in Notion syncs automatically — just add rows with a Due date. "
                       "To pull from a different task list, paste its link in ⚙️ Settings.")
        else:
            st.info("Add your Notion token and database link in ⚙️ Settings first.")
        return
    if st.button("🔄 Fetch from Notion"):
        try:
            with st.spinner("Reading your Notion database…"):
                pages = notion_fetch(s["notion_db"])
            known = {t.get("notion_id") for t in state["tasks"]}
            rows = [notion_parse(p, s["notion_date_prop"], s["notion_done_prop"]) for p in pages]
            st.session_state["notion_rows"] = [r for r in rows if not r["done"] and r["notion_id"] not in known]
        except Exception as e:
            st.error(str(e))
    rows = st.session_state.get("notion_rows")
    if rows is None:
        return
    if not rows:
        st.success("Nothing new to import — everything open is already here.")
        return
    df = pd.DataFrame([{
        "import": bool(r["due"]),
        "title": r["title"],
        "due_date": to_date(r["due"]) if r["due"] else None,
        "due_time": (r["due"][11:16] if r["due"] and len(r["due"]) > 10 else "23:59"),
        "size": "Medium",
        "consequence": "",
        "notion_id": r["notion_id"],
        "done_type": r["done_type"],
    } for r in rows])
    edited = st.data_editor(
        df, hide_index=True, key="notion_editor",
        column_order=["import", "title", "due_date", "due_time", "size", "consequence"],
        column_config={
            "import": st.column_config.CheckboxColumn("✔"),
            "due_date": st.column_config.DateColumn("Due"),
            "due_time": st.column_config.TextColumn("Time (HH:MM)"),
            "size": st.column_config.SelectboxColumn("Size", options=list(DIFFICULTY)),
        },
    )
    if st.button("📥 Import selected", type="primary"):
        added, skipped = 0, 0
        for r in edited.to_dict("records"):
            if not r["import"]:
                continue
            d = to_date(r["due_date"])
            try:
                hh, mm = (int(x) for x in str(r["due_time"] or "23:59").split(":")[:2])
            except ValueError:
                hh, mm = 23, 59
            if not d or datetime.combine(d, dtime(hh, mm), TZ) <= now():
                skipped += 1
                continue
            state["tasks"].append(make_task(
                r["title"], "", datetime.combine(d, dtime(hh, mm), TZ), r["size"] or "Medium",
                r["consequence"] or "", source="notion",
                notion={"notion_id": r["notion_id"], "notion_done_type": r["done_type"]}))
            added += 1
        save_state(state)
        st.session_state.pop("notion_rows", None)
        flash(f"Imported {added} task(s) from Notion."
              + (f" Skipped {skipped} with no due date or a past one — set a future date to import them." if skipped else ""))
        st.rerun()


def simulate_race(state: dict, track: dict) -> None:
    car = state["car"]
    you = {"name": f"#{car['number']} {car['name']} (you)", "you": True,
           "rating": car_rating(state) + random.gauss(0, 5)}
    heat = 3 * state["rival_heat"]  # your misses literally make them faster
    rivals = [{"name": n, "you": False, "rating": random.uniform(*track["ai"]) + heat + random.gauss(0, 5)}
              for n in random.sample(RIVALS, 5)]
    field = [you] + rivals
    for f in field:
        f["dist"], f["dnf"] = 0.0, False
    ticks = track["laps"] * 6
    dnf_risk = 0.004 if car["condition"] < 40 else 0.0
    board = st.empty()
    for i in range(ticks):
        for f in field:
            if f["dnf"]:
                continue
            if f["you"] and random.random() < dnf_risk:
                f["dnf"] = True
                continue
            f["dist"] += max(0, f["rating"] + random.gauss(0, 9))
        order = sorted(field, key=lambda f: (not f["dnf"], f["dist"]), reverse=True)
        lead = max(order[0]["dist"], 1)
        lines = [f"LAP {min(track['laps'], i // 6 + 1)}/{track['laps']}"]
        for pos, f in enumerate(order, 1):
            n = int(22 * f["dist"] / lead)
            tag = "DNF" if f["dnf"] else f"P{pos}"
            arrow = "◀" if f["you"] else " "
            lines.append(f"{tag:>3} {'█' * n}{'░' * (22 - n)} {f['name'][:24]} {arrow}")
        board.code("\n".join(lines), language=None)
        time.sleep(RACE_TICK)

    order = sorted(field, key=lambda f: (not f["dnf"], f["dist"]), reverse=True)
    pos = next(i for i, f in enumerate(order, 1) if f["you"])
    payout = 0 if you["dnf"] else (track["prize"][pos - 1] if pos <= 3 else 0)
    wear = 2 + track["laps"] // 3
    car["condition"] = max(0, car["condition"] - wear)
    state["xp"] += 5
    if payout:
        bank(state, payout, f"🏆 P{pos} at {track['name']}")
    state["races"].insert(0, {"ts": now().isoformat(), "track": track["name"],
                              "pos": "DNF" if you["dnf"] else pos, "payout": payout})
    del state["races"][100:]
    save_state(state)
    winner = order[0]
    gap = (winner["dist"] - you["dist"]) / max(you["rating"], 1) * 1.7  # pseudo-seconds
    if you["dnf"]:
        flash(f"💥 DNF at {track['name']} — the car gave out. Repair it before the next race.", "error",
              sound="fail")
    elif pos == 1:
        flash(f"🏆 **WIN** at {track['name']}! +{payout} coins. Tomorrow Tom eats your dust.", celebrate=True,
              sound="jackpot")
    elif payout:
        flash(f"P{pos} at {track['name']} — +{payout} coins. **{gap:.1f}s** off {winner['name']}. "
              f"One more upgrade and that's yours.", sound="win")
    else:
        flash(f"P{pos} at {track['name']}, **{gap:.1f}s** off the win. "
              + (f"Your misses gave the rivals +{heat} pace. " if heat else "")
              + "Finish a task, upgrade, come back.", "warning", sound="fail")
    st.rerun()


def remember_key(pw: str) -> str:
    return hashlib.sha256(f"dod-remember:{pw}".encode()).hexdigest()[:24]


def make_safety_car(due: datetime) -> dict:
    return make_task(daily.SAFETY_CAR_TITLE, "Proof: a screenshot of a 30-min timer + one line on what you did.",
                     due, None, "🔒 Games locked on PC + phone until it's done", category="deep", minutes=30)


def _next_half_hour() -> dtime:
    n = now() + timedelta(minutes=30)
    return dtime(n.hour, 0 if n.minute < 30 else 30)


def render_qualify_form(state: dict) -> None:
    today = now().date()
    open_t = sorted([t for t in state["tasks"] if t["status"] == "open"], key=lambda t: t["deadline"])
    with st.form("qualify_form", clear_on_submit=True):
        picked = []
        if open_t:
            labels = {t["id"]: f"{t['title']} — {parse_dt(t['deadline']):%a %I:%M %p}" for t in open_t}
            picked = st.multiselect("Already on the board", list(labels), format_func=labels.get,
                                    default=[t["id"] for t in open_t if parse_dt(t["deadline"]).date() <= today])
        bc = board_cfg(state)
        board_pick, board_items = [], []
        if bc:
            try:
                known = {t.get("board_page") for t in state["tasks"]}
                board_items = [b for b in _board_today(*bc, today.isoformat()) if b["id"] not in known]
            except Exception as e:
                st.caption(f"(Couldn't read your board: {e})")
            if board_items:
                blabels = {b["id"]: b["title"] + (f" · {b['when']}" if b["when"] else "") for b in board_items}
                board_pick = st.multiselect("📅 From your DECK 12 board today", list(blabels), format_func=blabels.get,
                                            help="Pick the ones that actually need doing — they'll tick off on your board too.")
        zc = zotero_cfg(state)
        paper_pick, papers = [], []
        if zc:
            try:
                known_z = {t.get("zotero_key") for t in state["tasks"] if t["status"] == "open"}
                papers = [p for p in _zotero_list(*zc) if p["key"] not in known_z][:8]
            except Exception as e:
                st.caption(f"(Couldn't read Zotero: {e})")
            if papers:
                plabels = {p["key"]: Z.label(p) for p in papers}
                paper_pick = st.multiselect(f"📄 From your Zotero “{zc[2]}”", list(plabels), format_func=plabels.get,
                                            help="45 min of deep work each. Proof: your notes + a 2-line summary.")
        st.caption("Add what you'll finish **today** — small and specific beats big and vague. "
                   "Value = category × honest minutes (guide in ✅ Tasks).")
        new = [st.text_input(f"Mission {i + 1}", key=f"q_new_{i}", label_visibility="collapsed",
                             placeholder=["e.g. Write 300 words of the methods section",
                                          "e.g. Email supervisor about the OVx timeline",
                                          "optional third one"][i]) for i in range(3)]
        c1, c2 = st.columns(2)
        due_t = c1.time_input("Done by", value=dtime(21, 0))
        start_t = c2.time_input("I'll START at", value=_next_half_hour(),
                                help="Your phone will hold you to this.")
        c3, c4 = st.columns(2)
        cat = c3.selectbox("Category of new ones", CAT_OPTS, format_func=cat_label, key="q_cat")
        mins = c4.select_slider("Honest time each", V.MINUTES, value=30, format_func=min_label, key="q_min")
        if st.form_submit_button("🚦 Lock it in", type="primary", use_container_width=True):
            titles = [x.strip() for x in new if x.strip()]
            dl = datetime.combine(today, due_t, TZ)
            if titles and dl <= now() + timedelta(minutes=5):
                st.error("'Done by' has to be later today.")
            elif not titles and not picked and not board_pick and not paper_pick:
                st.error("Pick at least one thing. One small thing counts.")
            elif (sum(x.get("minutes") or 60 for x in state["tasks"] if x["id"] in picked) + len(titles) * mins
                  + len(board_pick) * 60 + len(paper_pick) * 45) < daily.min_mission_minutes(state):
                st.error(f"Too easy. Today's mission needs at least {daily.min_mission_minutes(state)} minutes of "
                         "honest work in total — add something or pick a bigger time.")
            else:
                ids = list(picked)
                for bid in board_pick:
                    b = next(x for x in board_items if x["id"] == bid)
                    try:
                        bt = datetime.strptime(b["when"].upper().replace(".", ""), "%I:%M %p").time()
                        bdue = min(datetime.combine(today, bt, TZ) + timedelta(hours=2),
                                   datetime.combine(today, dtime(23, 59), TZ))
                    except ValueError:
                        bdue = datetime.combine(today, dtime(21, 0), TZ)
                    if bdue <= now() + timedelta(minutes=5):
                        bdue = datetime.combine(today, dtime(23, 59), TZ)
                    t = make_task(b["title"], "From your DECK 12 board", bdue, None, "", minutes=60)
                    t.update(board_page=b["id"], board_state="open")
                    state["tasks"].append(t)
                    ids.append(t["id"])
                for pk in paper_pick:
                    p = next(x for x in papers if x["key"] == pk)
                    pdl = dl if dl > now() + timedelta(minutes=5) else datetime.combine(today, dtime(23, 59), TZ)
                    t = make_task(f"📄 Read: {p['title'][:80]}", f"Proof: photo/screenshot of your notes + a 2-line "
                                  f"summary. {p['url']}", pdl, None, "", category="deep", minutes=45)
                    t["zotero_key"] = pk
                    state["tasks"].append(t)
                    ids.append(t["id"])
                for title in titles:
                    t = make_task(title, "", dl, None, "", category=None if cat == "auto" else cat, minutes=mins)
                    state["tasks"].append(t)
                    ids.append(t["id"])
                msg = daily.lock_in(state, now(), ids, start_t.strftime("%H:%M"), bank)
                save_state(state)
                flash(msg + f" You start at **{start_t:%I:%M %p}** — the phone will check.", sound="win")
                st.rerun()


def render_today(state: dict) -> None:
    n_ = now()
    stt = daily.status(state, n_)
    c = daily.cfg(state)
    with st.container(border=True):
        if stt["rest"]:
            st.markdown("### 🛌 Pit stop day")
            st.caption("Recharge. Nothing counts against you today. Back on the grid tomorrow.")
            return
        if not stt["qualified"]:
            left = stt["deadline"] - n_
            if left.total_seconds() > 0:
                st.markdown(f"### 🚦 Qualifying closes in {fmt_left(left)}")
                st.caption(f"Lock in today's mission before **{stt['deadline']:%I:%M %p}** for +{c['qualify_fuel']} fuel. "
                           f"Miss it and the safety car picks for you (−{c['qualify_penalty']}).")
            else:
                st.markdown("### 🚦 Qualifying missed")
                st.caption("The safety car is out. You can still lock in your own mission.")
            render_qualify_form(state)
            if stt["pit_stops_left"]:
                if st.checkbox("I'm sick / genuinely need a rest day", key="pit_chk") and \
                        st.button(f"🛌 Take a pit stop ({stt['pit_stops_left']} left this week)"):
                    daily.pit_stop(state, n_)
                    save_state(state)
                    flash("🛌 Pit stop. Rest properly — the grid forms again tomorrow.", "info")
                    st.rerun()
            return
        m, done = stt["mission"], stt["mission_done"]
        st.markdown(f"### 🏁 Today's mission · {len(done)}/{len(m)}")
        st.progress(len(done) / len(m) if m else 0.0)
        bits = [f"📅 day streak **{stt['day_streak']}**" + (" (+1 when you finish one today)" if not stt["done_today"] else " ✅")]
        if stt["start_at"]:
            bits.append(f"you said you'd start at **{datetime.strptime(stt['start_at'], '%H:%M'):%I:%M %p}**")
        st.caption(" · ".join(bits))
        for t in m:
            if t["status"] in ("done", "redeemed"):
                st.markdown(f"✅ ~~{t['title']}~~")
            elif t["status"] == "open":
                dl = parse_dt(t["deadline"])
                with st.expander(f"📸 {t['title']} · {fmt_left(dl - n_)} left"):
                    render_proof_form(state, t, "open", scope="today_")
            else:
                st.markdown(f"💀 {t['title']}")
        if m and len(done) == len(m):
            st.success("Mission complete. Anything else today is pure bonus. 🏆")
        elif not stt["done_today"] and n_.hour >= 18:
            st.warning(f"⚠️ Zero finishes so far. Midnight = −{c['zero_day_penalty']} coins and your day streak dies. "
                       "Do the smallest one now.")
        with st.expander("➕ Add to today's mission"):
            render_qualify_form(state)


def focus_today(state: dict) -> int:
    today = now().date().isoformat()
    return int(sum(x["min"] for x in state.get("focus_log", []) if x["date"] == today))


def render_timer(state: dict) -> None:
    tm = state.get("timer")
    open_t = sorted([t for t in state["tasks"] if t["status"] == "open"],
                    key=lambda t: (t.get("mission_day") != now().date().isoformat(), t["deadline"]))
    with st.container(border=True):
        if not tm:
            st.markdown("#### ⏱️ Focus timer")
            if not open_t:
                st.caption("Add a task first — the timer is a receipt for real work.")
                return
            labels = {t["id"]: t["title"] for t in open_t}
            c1, c2 = st.columns([3, 1])
            tid = c1.selectbox("Working on", list(labels), format_func=labels.get, key="timer_task",
                               label_visibility="collapsed")
            planned = c2.selectbox("Minutes", [25, 50, 90], key="timer_len", label_visibility="collapsed")
            if st.button("▶️ Start focus", type="primary", use_container_width=True):
                state["timer"] = {"task_id": tid, "start": now().isoformat(), "planned": planned}
                save_state(state)
                st.rerun()
            g0, g1 = EV.golden_hour(now().date(), TZ)
            tok = state.get("tokens", {})
            golden_txt = (f"🌅 **Golden hour is NOW** (till {g1:%I:%M %p}) — sessions started now drop guaranteed loot."
                          if g0 <= now() < g1 else f"🌅 Golden hour today: {g0:%I:%M}–{g1:%I:%M %p}.")
            drops_left = EV.DROPS_PER_DAY - sum(1 for x in state.get("focus_log", [])
                                                 if x["date"] == now().date().isoformat() and x.get("drop"))
            st.caption(f"Full 25+ min sessions drop loot ({max(0, drops_left)} left today). {golden_txt} "
                       f"Timer-verified tasks pay **+{int(V.TIMER_BONUS * 100)}%**. Today: **{focus_today(state)} min**."
                       + (f" Tokens: ⚡×{tok.get('double', 0)} 🔧×{tok.get('upgrade', 0)}"
                          if tok.get("double") or tok.get("upgrade") else ""))
            return
        t = next((x for x in state["tasks"] if x["id"] == tm["task_id"]), None)
        start = parse_dt(tm["start"])
        end_ms = int((start + timedelta(minutes=tm["planned"])).timestamp() * 1000)
        st.markdown(f"#### ⏱️ Focusing: {t['title'] if t else '—'}")
        _embed = st.iframe if hasattr(st, "iframe") else __import__("streamlit.components.v1", fromlist=["html"]).html
        _embed(f"""
<div id="t" style="font:700 46px ui-monospace,Menlo,monospace;color:#e63946;text-align:center;"></div>
<div id="s" style="font:14px system-ui;color:#aaa;text-align:center;"></div>
<script>
const end={end_ms};
function f(){{const r=end-Date.now();const a=Math.floor(Math.abs(r)/1000);
document.getElementById('t').textContent=(r<0?'+':'')+String(Math.floor(a/60)).padStart(2,'0')+':'+String(a%60).padStart(2,'0');
document.getElementById('s').textContent=r<0?'🏁 Session done — log it.':'Phone face-down. One thing only.';}}
f();setInterval(f,500);
</script>""", height=90)  # our own static markup only — no user content goes in here
        c1, c2 = st.columns(2)
        if c1.button("⏹️ Stop & log", type="primary", use_container_width=True):
            mins = min((now() - start).total_seconds() / 60, tm["planned"] + 15)
            state.pop("timer", None)
            if mins >= 1 and t:
                full = mins >= tm["planned"]
                t["focus_min"] = round(t.get("focus_min", 0) + mins, 1)
                state.setdefault("focus_log", []).append({"date": now().date().isoformat(), "task": t["id"],
                                                          "min": round(mins, 1), "full": full})
                del state["focus_log"][:-500]
                state["xp"] += int(mins // 5)
                drop_msg, snd = "", ("win" if full else None)
                today_log = [x for x in state["focus_log"] if x["date"] == now().date().isoformat()]
                if full and mins >= 25 and sum(1 for x in today_log if x.get("drop")) < EV.DROPS_PER_DAY:
                    g0, g1 = EV.golden_hour(now().date(), TZ)
                    golden = g0 <= start < g1
                    kind = EV.roll_drop(golden)
                    state["focus_log"][-1]["drop"] = kind
                    tok = state.setdefault("tokens", {"double": 0, "upgrade": 0})
                    if kind == "xp":
                        state["xp"] += 20
                        drop_msg = "🎁 Session drop: **+20 XP**"
                    elif kind == "coins":
                        bank(state, 30, "🎁 Session drop")
                        drop_msg = "🎁 Session drop: **+30 coins**"
                    elif kind == "crate":
                        drop_msg = "🎁 Session drop → " + open_crate(state, {"reward": 45})
                    elif kind == "double_token":
                        tok["double"] = tok.get("double", 0) + 1
                        drop_msg = "🎁 Session drop: **⚡ 2× token** — your next finish pays double."
                    else:
                        tok["upgrade"] = tok.get("upgrade", 0) + 1
                        drop_msg = "🎁 Session drop: **🔧 free-upgrade token** — install any part for free in the Garage."
                    if golden:
                        drop_msg = "🌅 **Golden hour bonus!** " + drop_msg
                    snd = "jackpot" if kind in ("double_token", "upgrade_token") or golden else "win"
                save_state(state)
                flash(f"⏱️ Logged **{int(mins)} min** on *{t['title']}*" + (" — full session! 🔥" if full else "")
                      + f" +{int(mins // 5)} XP. Today: {focus_today(state)} min." + (f"\n\n{drop_msg}" if drop_msg else ""),
                      sound=snd, celebrate=bool(drop_msg))
            else:
                save_state(state)
            st.rerun()
        if c2.button("✖️ Cancel", use_container_width=True):
            state.pop("timer", None)
            save_state(state)
            st.rerun()


def render_contracts(state: dict) -> None:
    n_ = now()
    st.subheader("📜 This week's contracts")
    claimed = state.setdefault("contracts_claimed", [])
    for c in K.this_week(n_):
        p, key = K.progress(state, c, n_), K.claim_key(c, n_)
        with st.container(border=True):
            unit = " min" if c.get("unit") == "min" else ""
            st.markdown(f"**{c['title']}** · +{c['reward']} 🪙")
            st.progress(min(1.0, p / c["goal"]), text=f"{min(p, c['goal'])}{unit} / {c['goal']}{unit}")
            if key in claimed:
                st.caption("✅ Claimed")
            elif p >= c["goal"] and st.button(f"Claim +{c['reward']} 🪙", key=f"claim_{c['id']}", type="primary"):
                claimed.append(key)
                bank(state, c["reward"], f"📜 Contract: {c['title']}")
                save_state(state)
                flash(f"📜 Contract complete: **{c['title']}** · +{c['reward']} coins!", celebrate=True, sound="jackpot")
                st.rerun()
    st.caption("New contracts every Monday.")


def _cards(cs: list[str], hide_second: bool = False) -> str:
    return " ".join("🂠" if hide_second and i == 1 else f"`{c}`" for i, c in enumerate(cs))


def render_lounge(state: dict) -> None:
    today = now().date().isoformat()
    finished = len(daily.finished_on(state, now().date()))
    reason = L.closed_reason(state, today, finished, black_flag_reasons(state))
    rec = L.day_record(state, today)
    st.caption(f"Today: {rec['hands']}/{L.MAX_HANDS} hands · net {rec['net']:+d} 🪙 · max bet {L.MAX_BET} · "
               "the house has an edge — this is where coins go to have fun, not to multiply.")
    g = st.session_state.get("bj")
    if reason and not (g and not g["over"]):
        st.info(f"🚪 {reason}")
        return

    def settle(payout: int, bet: int, label: str) -> None:
        rec["hands"] += 1
        rec["net"] += payout - bet
        if payout:
            bank(state, payout, f"🎰 {label}")
        save_state(state)

    tab_bj, tab_dice = st.tabs(["🃏 Blackjack", "🎲 Snake eyes"])
    with tab_bj:
        if not g or g["over"]:
            if g:
                st.markdown(f"Dealer {_cards(g['dealer'])} ({L.hand_value(g['dealer'])}) · "
                            f"You {_cards(g['player'])} ({L.hand_value(g['player'])})")
                (st.success if g["payout"] > g["bet"] else st.info if g["payout"] == g["bet"] else st.error)(
                    f"{g['result']} — {'+' if g['payout'] - g['bet'] >= 0 else ''}{g['payout'] - g['bet']} 🪙")
            bet = st.slider("Bet", 5, min(L.MAX_BET, max(5, state["coins"])), 10, step=5, key="bj_bet")
            if st.button("Deal", type="primary", disabled=state["coins"] < bet):
                bank(state, -bet, "🎰 Blackjack bet")
                g = L.deal(bet)
                st.session_state["bj"] = g
                if g["over"]:
                    settle(g["payout"], bet, "Blackjack")
                else:
                    save_state(state)
                st.rerun()
        else:
            st.markdown(f"Dealer {_cards(g['dealer'], hide_second=True)}")
            st.markdown(f"You {_cards(g['player'])} (**{L.hand_value(g['player'])}**) · bet {g['bet']}")
            c1, c2 = st.columns(2)
            if c1.button("Hit", use_container_width=True):
                L.hit(g)
                if g["over"]:
                    settle(g["payout"], g["bet"], "Blackjack")
                st.rerun()
            if c2.button("Stand", type="primary", use_container_width=True):
                L.stand(g)
                settle(g["payout"], g["bet"], "Blackjack")
                st.rerun()
    with tab_dice:
        last = st.session_state.get("dice_last")
        if last:
            d1, d2 = last["dice"]
            st.markdown(f"<div style='font-size:64px;text-align:center'>{L.DICE[d1 - 1]} {L.DICE[d2 - 1]}</div>",
                        unsafe_allow_html=True)
            (st.success if last["payout"] else st.error)(
                f"{L.SNAKE_BETS[last['choice']][0]}: rolled {d1 + d2} — "
                + (f"+{last['payout'] - last['bet']} 🪙" if last["payout"] else f"−{last['bet']} 🪙"))
        choice = st.radio("Bet on", list(L.SNAKE_BETS), horizontal=True, key="dice_choice",
                          format_func=lambda k: f"{L.SNAKE_BETS[k][0]} ({L.SNAKE_BETS[k][1]}×)")
        bet = st.slider("Bet", 5, min(L.MAX_BET, max(5, state["coins"])), 10, step=5, key="dice_bet")
        if st.button("🎲 Roll", type="primary", disabled=bool(reason) or state["coins"] < bet):
            bank(state, -bet, "🎰 Snake eyes bet")
            dice = L.roll()
            pay = L.snake_payout(choice, dice, bet)
            settle(pay, bet, "Snake eyes")
            st.session_state["dice_last"] = {"dice": dice, "choice": choice, "bet": bet, "payout": pay}
            if dice == (1, 1) and choice == "snake":
                flash("🐍🐍 SNAKE EYES! 30×!", celebrate=True, sound="jackpot")
            st.rerun()


# ─────────────────────────── app ───────────────────────────
st.set_page_config(page_title="Deadline or Die", page_icon="🏁", layout="centered")

# Password gate — set APP_PASSWORD in secrets so nobody else can see your tasks and proof.
_pw = get_secret("APP_PASSWORD")
if _pw and not st.session_state.get("_authed") and st.query_params.get("k") == remember_key(_pw):
    st.session_state["_authed"] = True
if _pw and not st.session_state.get("_authed"):
    st.title("🏁 Deadline or Die")
    entered = st.text_input("Password", type="password")
    if entered:
        if hashlib.sha256(entered.encode()).digest() == hashlib.sha256(_pw.encode()).digest():
            st.session_state["_authed"] = True
            st.query_params["k"] = remember_key(_pw)  # bookmark / home-screen this URL = no more password
            st.rerun()
        st.error("Wrong password.")
    st.stop()

state = load_state()

sync_msgs = []
if st.session_state.pop("_fresh_load", False) and notion_cfg():
    try:
        sync_msgs, changed = sync_from_notion(state)
        if changed:
            st.session_state["_needs_save"] = True
    except Exception as e:
        sync_msgs = [("warning", f"Couldn't sync tasks with Notion: {e}")]

crash_msgs = process_overdue(state)
crash_msgs += daily.settle(state, now(), bank, make_safety_car)
rust_msg = process_rust(state)
if crash_msgs or rust_msg or st.session_state.pop("_needs_save", False):
    save_state(state)
    if crash_msgs:
        st.session_state["sound"] = "fail"

PLAYER = state["settings"].get("player_name") or "driver"
st.title("🏁 Deadline or Die")
hour = now().hour
greet = "Late night" if hour < 5 else "Morning" if hour < 12 else "Afternoon" if hour < 18 else "Evening"
st.caption(f"{greet}, {PLAYER}. Prove it or pay for it."
           + (" It's a danger day — no one's watching you today. +20% on everything you finish."
              if now().weekday() in DANGER_DAYS else ""))

for kind, m in sync_msgs:
    getattr(st, kind)(m)
for m in crash_msgs:
    st.error(m)
if rust_msg:
    st.warning(rust_msg)
for kind, m in st.session_state.pop("flash", []):
    getattr(st, kind)(m)
if st.session_state.pop("celebrate", False):
    st.balloons()
_lk = LK.status(state, now())
if _lk["locked"]:
    with st.container(border=True):
        st.markdown("#### 🔒 LOCKED — games are blocked")
        st.caption(" · ".join(_lk["reasons"]))
        cost = round(LK.UNLOCK_COST * daily.level_factor(state))
        if st.checkbox("I genuinely need an emergency unlock", key="unlock_chk") and \
                st.button(f"🆘 Unlock for {LK.UNLOCK_HOURS}h · −{cost} 🪙", key="unlock_btn"):
            bank(state, -cost, "🆘 Emergency unlock")
            state["override_until"] = (now() + timedelta(hours=LK.UNLOCK_HOURS)).isoformat()
            save_state(state)
            flash(f"🆘 Unlocked for {LK.UNLOCK_HOURS}h. That cost {cost} coins — and Tomorrow Tom saw it.", "warning")
            st.rerun()
elif _lk.get("override"):
    st.caption(f"🆘 Emergency unlock active until {parse_dt(state['override_until']):%I:%M %p}.")

for e in EV.active(now()):
    left = fmt_left(e["end"] - now())
    claims = state.setdefault("event_claims", [])
    with st.container(border=True):
        st.markdown(f"#### 🎉 LIVE · {e['title']} · {left} left")
        st.caption(e["banner"].replace("**", ""))
        if e["type"] in ("supply", "pitcrew") and e["id"] not in claims:
            if st.button("🎁 Claim" if e["type"] == "supply" else "🔧 Repair me", key=f"ev_{e['id']}", type="primary"):
                claims.append(e["id"])
                if e["type"] == "supply":
                    out = open_crate(state, {"reward": 45})
                else:
                    state["car"]["condition"] = min(100, state["car"]["condition"] + 30)
                    out = "🔧 Pit crew fixed you up: +30% condition."
                save_state(state)
                flash(out, celebrate=True, sound="jackpot")
                st.rerun()
        elif e["id"] in claims:
            st.caption("✅ Claimed")

snd = st.session_state.pop("sound", None)
if snd and state["settings"].get("sounds", True):
    st.audio(tone_wav(SOUNDS[snd]), format="audio/wav", autoplay=True)

render_today(state)

render_timer(state)

lvl = level_of(state["xp"])
ds = state.get("day_streak", 0)
c1, c2, c3, c4 = st.columns(4)
c1.metric("🪙 Coins", state["coins"])
c2.metric("📅 Day streak", f"{ds} 🔥" if ds else "0", f"best {state.get('best_day_streak', 0)}", delta_color="off")
c3.metric("⏱️ Focus today", f"{focus_today(state)}m")
c4.metric("🔧 Car", f"{state['car']['condition']}%")
st.caption(f"🧑‍✈️ Level {lvl} · {state['xp'] - xp_for_level(lvl)}/{xp_for_level(lvl + 1) - xp_for_level(lvl)} XP · "
           f"task streak {state['streak']} (best {state['best_streak']})")

tab_pit, tab_tasks, tab_goals, tab_garage, tab_race, tab_lounge, tab_set = st.tabs(
    ["🏁 Pit Wall", "✅ Tasks", "🎯 Goals", "🔧 Garage", "🏎️ Race", "🎰 Lounge", "⚙️ Settings"])

open_tasks = sorted([t for t in state["tasks"] if t["status"] == "open"], key=lambda t: t["deadline"])

# ── Pit Wall ──
with tab_pit:
    reasons = black_flag_reasons(state)
    if reasons:
        st.error("⬛ **BLACK FLAG** — racing locked: " + "; ".join(reasons) + ".")
    else:
        st.success("🟢 **Green flag** — you're clear to race.")

    h1, h2, h3 = st.columns(3)
    h1.metric("🔥 Rival heat", state["rival_heat"], "your misses fuel them", delta_color="off")
    h2.metric("🛡️ Shields", state["shields"])
    left = max(0, PITY_AFTER - state["since_rare"])
    h3.metric("📦 Rare drop", f"≤{left} away" if left else "NEXT", delta_color="off")
    if open_tasks:
        nxt = open_tasks[0]
        hrs = (parse_dt(nxt["deadline"]) - now()).total_seconds() / 3600
        if hrs < 24:
            st.warning(f"⏱️ **{nxt['title']}** dies in {fmt_left(parse_dt(nxt['deadline']) - now())}. "
                       f"That's {nxt['penalty']} coins, {MISS_DAMAGE}% of your car and a {state['streak']}-streak "
                       f"on the line. Start for 10 minutes. Just 10.")

    unserved = [p for p in state["penalty_box"] if not p["served"]]
    if unserved:
        st.subheader("🚨 Penalty box")
        for p in unserved:
            with st.container(border=True):
                st.markdown(f"**{p['consequence']}**  \n<small>for missing *{html.escape(p['task'])}*</small>",
                            unsafe_allow_html=True)
                if p.get("enforced"):
                    st.caption(f"🔒 Enforced on your PC + phone. Lifts when you finish *{p['task']}* (🩹 redeem it) "
                               f"or after {LK.LOCK_HOURS}h.")
                elif st.checkbox("I actually served this", key=f"served_chk_{p['id']}") and \
                        st.button("Release me", key=f"served_{p['id']}"):
                    p["served"], p["served_at"] = True, now().isoformat()
                    save_state(state)
                    flash("Penalty served. Back on track.")
                    st.rerun()

    render_contracts(state)

    st.subheader("⏱️ Next up")
    if not open_tasks:
        st.info("No open tasks. Add one in ✅ Tasks — or break a goal down in 🎯 Goals.")
    for t in open_tasks[:6]:
        dl = parse_dt(t["deadline"])
        g = goal_title(state, t.get("goal_id"))
        st.markdown(f"{chip(dl)} **{t['title']}** — {fmt_left(dl - now())} left  \n"
                    f"<small>{dl:%a %b %d, %I:%M %p} · +{t['reward']} / −{t['penalty']}"
                    f"{' · 🎯 ' + html.escape(g) if g else ''}</small>", unsafe_allow_html=True)

    with st.expander("📜 Ledger"):
        if not state["ledger"]:
            st.caption("Nothing yet.")
        for e in state["ledger"][:15]:
            st.markdown(f"`{'+' if e['delta'] >= 0 else ''}{e['delta']:>5}` {e['reason']} "
                        f"<small>· {parse_dt(e['ts']):%b %d %I:%M %p}</small>", unsafe_allow_html=True)

    with st.expander("📖 Rules"):
        st.markdown(f"""
- **Every task** has a deadline, a reward and a penalty (set by its size).
- **Finish it → submit proof** (file and/or link + a note). With an Anthropic key, an AI race steward checks it; otherwise it's on your honor. The same file can never be reused.
- **Rewards:** +25% if done 24h+ early (+10% if 6h+), ×0.1 per streak (up to ×2), XP toward driver level.
- **Miss it** (after a {state['settings']['grace_minutes']}-min grace): lose the penalty coins, −{MISS_DAMAGE}% car condition, streak resets, and your real-world consequence lands in the penalty box.
- **Black flag** (no racing) while you're in debt, have unserved penalties, or your car is under 20%.
- **Redemption:** finish a missed task within {REDEEM_WINDOW_H}h for half the penalty back.
- **Extensions** cost 30% of the penalty and cut the reward 15% each (max {state['settings']['max_extensions']}).
- **Abandoning** a task = taking the penalty (free only in the first {FREE_DELETE_MIN} min, for typos).
- **Goals:** finish every task in a goal (3+) for a +{GOAL_BONUS[0]} coin bonus.
- **Pit crates:** every approved proof opens one — coins, free part upgrades, streak shields, repairs, or a 3× jackpot. A rare drop is guaranteed after {PITY_AFTER} commons.
- **Danger days** (Tue/Wed, no one's watching): +20% on anything finished.
- **Rival heat:** every miss makes your rivals +3 faster in races. Every finish takes 1 back.
- **Rust:** finish nothing for {IDLE_GRACE_DAYS}+ days and the car loses {RUST_PER_DAY}%/day sitting in the garage.
""")

# ── Tasks ──
with tab_tasks:
    points_guide()
    with st.expander("➕ New task", expanded=not open_tasks):
        task_form(state, "new_task_form")
    with st.expander("📥 Import from Notion"):
        notion_import(state)

    st.subheader(f"Open ({len(open_tasks)})")
    s = state["settings"]
    for t in open_tasks:
        dl = parse_dt(t["deadline"])
        with st.expander(f"{chip(dl)} {t['title']} · {fmt_left(dl - now())}"):
            g = goal_title(state, t.get("goal_id"))
            st.markdown(
                f"**Due** {dl:%a %b %d, %I:%M %p} · **{t['difficulty']}** · +{t['reward']} 🪙 / −{t['penalty']} 🪙"
                + (f"  \n🎯 {g}" if g else "")
                + (f"  \n{t['details']}" if t.get("details") else "")
                + (f"  \n🚨 If missed: *{t['consequence']}*" if t.get("consequence") else "")
                + (f"  \n🚩 Rejected {t['rejections']}×" if t.get("rejections") else ""))
            render_proof_form(state, t, "open")

            st.divider()
            ca, cb = st.columns(2)
            ext_cost = math.ceil(t["penalty"] * 0.3)
            if t["extensions"] < s["max_extensions"]:
                if ca.button(f"⏳ +{s['extension_hours']}h ({ext_cost} 🪙)", key=f"ext_{t['id']}"):
                    if state["coins"] < ext_cost:
                        st.error("Can't afford it. Guess you're doing it on time.")
                    else:
                        bank(state, -ext_cost, f"⏳ Extension: {t['title']}")
                        t["deadline"] = (dl + timedelta(hours=s["extension_hours"])).isoformat()
                        t["extensions"] += 1
                        save_state(state)
                        flash(f"Extended to {parse_dt(t['deadline']):%a %b %d, %I:%M %p}. Reward cut 15%.", "warning")
                        st.rerun()
            else:
                ca.caption("No extensions left.")
            young = now() - parse_dt(t["created"]) < timedelta(minutes=FREE_DELETE_MIN)
            label = "🗑️ Delete (free)" if young else f"🏳️ Abandon (−{t['penalty']} 🪙)"
            if cb.checkbox("Confirm", key=f"conf_{t['id']}") and cb.button(label, key=f"ab_{t['id']}"):
                if young:
                    state["tasks"].remove(t)
                    if t.get("sync_page") and notion_cfg():
                        try:
                            archive_page(notion_ctx()[0], t["sync_page"])
                        except Exception:
                            pass
                    save_state(state)
                    flash("Deleted.")
                else:
                    t["abandoned"] = True
                    save_state(state)
                    flash(fail_task(state, t, "Abandoned"), "error", sound="fail")
                    save_state(state)
                st.rerun()

    redeemable = [t for t in state["tasks"] if t["status"] == "failed" and not t.get("abandoned")
                  and now() - parse_dt(t["failed_at"]) < timedelta(hours=REDEEM_WINDOW_H)]
    if redeemable:
        st.subheader("🩹 Redeemable")
        st.caption(f"Missed — but finish within {REDEEM_WINDOW_H}h of the miss for half the penalty back.")
        for t in redeemable:
            left = parse_dt(t["failed_at"]) + timedelta(hours=REDEEM_WINDOW_H) - now()
            with st.expander(f"💀 {t['title']} · {fmt_left(left)} to redeem"):
                render_proof_form(state, t, "redeem")

    done = [t for t in state["tasks"] if t["status"] in ("done", "redeemed")]
    if done:
        with st.expander(f"🏆 Completed ({len(done)})"):
            for t in sorted(done, key=lambda t: t["completed_at"], reverse=True)[:30]:
                icon = "🏁" if t["status"] == "done" else "🩹"
                st.markdown(f"{icon} **{t['title']}** · +{t.get('earned', 0)} 🪙 "
                            f"<small>· {parse_dt(t['completed_at']):%b %d}</small>", unsafe_allow_html=True)

# ── Goals ──
with tab_goals:
    existing = {g["title"] for g in state["goals"]}
    starters = [s_ for s_ in starter_goals() if s_[0] not in existing]
    if starters:
        with st.expander("⚡ Quick-start goals", expanded=not state["goals"]):
            with st.form("starter_form"):
                pick = st.selectbox("Goal", [s_[0] for s_ in starters])
                tgt = st.date_input("Target date", value=now().date() + timedelta(days=60),
                                    min_value=now().date(), key="starter_target")
                if st.form_submit_button("Start this goal", type="primary"):
                    why = dict(starters)[pick]
                    state["goals"].append({"id": uuid.uuid4().hex[:10], "title": pick, "why": why,
                                           "target": tgt.isoformat(), "created": now().isoformat(),
                                           "claimed": False})
                    save_state(state)
                    flash(f"🎯 **{pick}** is on the board. Break it into deadlines below.")
                    st.rerun()

    with st.expander("🎯 New long-term goal", expanded=not state["goals"] and not starters):
        with st.form("goal_form", clear_on_submit=True):
            gt = st.text_input("Goal", placeholder="e.g. Submit the paper to a journal")
            why = st.text_input("Why it matters (shown when you need it)")
            target = st.date_input("Target date", value=now().date() + timedelta(days=60), min_value=now().date())
            if st.form_submit_button("Create goal", type="primary") and gt.strip():
                state["goals"].append({"id": uuid.uuid4().hex[:10], "title": gt.strip(), "why": why.strip(),
                                       "target": target.isoformat(), "created": now().isoformat(),
                                       "claimed": False})
                save_state(state)
                flash(f"Goal created. Now break it down into deadlines.")
                st.rerun()

    has_key = bool(get_secret("ANTHROPIC_API_KEY"))
    for g in state["goals"]:
        gtasks = [t for t in state["tasks"] if t.get("goal_id") == g["id"]]
        n_done = sum(t["status"] == "done" for t in gtasks)
        target = date.fromisoformat(g["target"])
        with st.container(border=True):
            st.markdown(f"### 🎯 {g['title']}")
            if g.get("why"):
                st.caption(f"Why: {g['why']}")
            st.progress(n_done / len(gtasks) if gtasks else 0.0,
                        text=f"{n_done}/{len(gtasks)} milestones · target {target:%b %d, %Y} "
                             f"({(target - now().date()).days} days)")
            for t in sorted(gtasks, key=lambda t: t["deadline"]):
                icon = {"open": chip(parse_dt(t["deadline"])), "done": "🏁", "redeemed": "🩹",
                        "failed": "💀"}[t["status"]]
                st.markdown(f"{icon} {t['title']} <small>· {parse_dt(t['deadline']):%b %d}</small>",
                            unsafe_allow_html=True)

            if gtasks and len(gtasks) >= 3 and n_done == len(gtasks) and not g.get("claimed"):
                if st.button(f"🏆 Claim finish-line bonus (+{GOAL_BONUS[0]} 🪙)", key=f"claim_{g['id']}",
                             type="primary"):
                    g["claimed"] = True
                    bank(state, GOAL_BONUS[0], f"🏆 Goal complete: {g['title']}")
                    state["xp"] += GOAL_BONUS[1]
                    save_state(state)
                    flash(f"🏆 Goal **{g['title']}** complete! +{GOAL_BONUS[0]} coins, +{GOAL_BONUS[1]} XP.",
                          celebrate=True)
                    st.rerun()

            with st.expander("➕ Add a milestone"):
                task_form(state, f"ms_form_{g['id']}", goal_id=g["id"])

            with st.expander("🤖 Break it down with Claude"):
                if not has_key:
                    st.caption("Add an Anthropic API key in ⚙️ Settings to let Claude draft milestones.")
                else:
                    extra = st.text_area("Anything Claude should know (constraints, busy weeks…)",
                                         key=f"ctx_{g['id']}", height=70)
                    if st.button("Draft milestones", key=f"plan_{g['id']}"):
                        with st.spinner("Planning…"):
                            try:
                                st.session_state[f"plan_{g['id']}"] = ai_plan(state, g, extra)
                            except Exception as e:
                                st.error(str(e))
                    plan = st.session_state.get(f"plan_{g['id']}")
                    if plan:
                        df = pd.DataFrame([{
                            "add": True, "title": p.get("title", ""), "due": to_date(p.get("due")),
                            "size": p.get("difficulty") if p.get("difficulty") in DIFFICULTY else "Medium",
                            "proof": p.get("proof_hint", ""), "consequence": "",
                        } for p in plan])
                        ed = st.data_editor(df, hide_index=True, key=f"plan_ed_{g['id']}", column_config={
                            "add": st.column_config.CheckboxColumn("✔"),
                            "due": st.column_config.DateColumn("Due"),
                            "size": st.column_config.SelectboxColumn("Size", options=list(DIFFICULTY)),
                            "proof": st.column_config.TextColumn("Proof idea"),
                        })
                        if st.button("Add selected as deadlines", key=f"plan_add_{g['id']}", type="primary"):
                            n = 0
                            for r in ed.to_dict("records"):
                                d = to_date(r["due"])
                                if r["add"] and d and str(r["title"]).strip():
                                    dl = datetime.combine(d, dtime(23, 59), TZ)
                                    if dl > now():
                                        state["tasks"].append(make_task(
                                            r["title"], f"Proof: {r['proof']}" if r["proof"] else "", dl,
                                            r["size"] or "Medium", r["consequence"] or "", g["id"]))
                                        n += 1
                            save_state(state)
                            st.session_state.pop(f"plan_{g['id']}", None)
                            flash(f"Added {n} deadline(s) to **{g['title']}**.")
                            st.rerun()

            if not any(t["status"] == "open" for t in gtasks):
                if st.checkbox("Delete this goal", key=f"gdel_chk_{g['id']}") and \
                        st.button("Delete", key=f"gdel_{g['id']}"):
                    state["goals"].remove(g)
                    save_state(state)
                    st.rerun()

# ── Garage ──
with tab_garage:
    car = state["car"]
    st.markdown(car_svg(car), unsafe_allow_html=True)
    st.markdown(f"### #{car['number']} {car['name']}")
    model = CAR_BY_ID.get(car.get("model"), CARS[0])
    st.caption(f"**{model['name']}** · performance rating **{car_rating(state):.0f}** — {model['blurb']}")
    st.caption(f"📚 {G.CHASSIS[model['id']][1]}")

    st.progress(car["condition"] / 100, text=f"Condition {car['condition']}%")
    missing = 100 - car["condition"]
    if missing:
        afford = min(missing, max(state["coins"], 0) // REPAIR_COST_PER_PT)
        if afford:
            if st.button(f"🔧 Repair +{afford}% ({afford * REPAIR_COST_PER_PT} 🪙)"):
                car["condition"] += afford
                bank(state, -afford * REPAIR_COST_PER_PT, "🔧 Repairs")
                save_state(state)
                flash("Repaired.")
                st.rerun()
        else:
            st.caption("Can't afford repairs. Go finish something.")

    with st.expander("🏢 Showroom — the Honda ladder", expanded=False):
        lvl_now = level_of(state["xp"])
        owned = car.setdefault("owned", ["civic_si"])
        for m in CARS:
            c1, c2 = st.columns([3, 2])
            tag = "🟢 driving" if m["id"] == car.get("model") else "✅ owned" if m["id"] in owned else \
                  ("🔒 level " + str(m["level"]) if lvl_now < m["level"] else f"{m['cost']:,} 🪙")
            c1.markdown(f"**{m['name']}** · base {m['base']} · tunes to L{G.cap(m['id'])}  \n"
                        f"<small>{m['blurb']}</small>", unsafe_allow_html=True)
            if m["id"] == car.get("model"):
                c2.caption(tag)
            elif m["id"] in owned:
                if c2.button("Drive it", key=f"drive_{m['id']}"):
                    car["model"] = m["id"]
                    save_state(state)
                    st.rerun()
            elif lvl_now < m["level"]:
                c2.caption(tag)
            elif c2.button(f"Buy · {m['cost']:,} 🪙", key=f"buy_{m['id']}", disabled=state["coins"] < m["cost"]):
                bank(state, -m["cost"], f"🏢 Bought {m['name']}")
                owned.append(m["id"])
                car["model"] = m["id"]
                save_state(state)
                flash(f"🔑 **{m['name']}** is yours. Every coin of it came from finished work.", celebrate=True,
                      sound="jackpot")
                st.rerun()

    st.subheader("Upgrades")
    cap_now = G.cap(model["id"])
    st.caption(f"This chassis can be tuned to **L{cap_now}**. Parts you buy stay yours — move up the Honda ladder "
               "to unlock the rest. Each upgrade comes with a 💡 lesson.")
    for key, p in PARTS.items():
        lv = car["parts"].setdefault(key, 0)
        with st.container(border=True):
            c1, c2 = st.columns([3, 2])
            c1.markdown(f"**{p['icon']} {p['label']}** · L{lv}/{MAX_PART_LEVEL}  \n"
                        f"<small>Installed: {G.installed(key, lv)}"
                        f"{f' (running at L{cap_now} on this chassis)' if lv > cap_now else ''}</small>",
                        unsafe_allow_html=True)
            nxt = G.next_upgrade(key, lv)
            if not nxt:
                c2.caption("Maxed ✅")
            elif lv >= cap_now:
                c2.caption(f"🔒 Chassis limit L{cap_now}")
            else:
                cost = part_cost(key, lv)
                if state.get("tokens", {}).get("upgrade", 0) > 0 and c2.button("🔧 Install free (token)", key=f"tok_{key}"):
                    state["tokens"]["upgrade"] -= 1
                    car["parts"][key] += 1
                    save_state(state)
                    flash(f"{p['icon']} **{nxt[0]}** installed with a free-upgrade token.\n\n💡 {nxt[1]}", sound="jackpot")
                    st.rerun()
                if c2.button(f"Install · {cost} 🪙", key=f"up_{key}", disabled=state["coins"] < cost):
                    car["parts"][key] += 1
                    bank(state, -cost, f"⚙️ {nxt[0]}")
                    save_state(state)
                    flash(f"{p['icon']} **{nxt[0]}** installed.\n\n💡 {nxt[1]}", sound="win")
                    st.rerun()
            if nxt:
                st.caption(f"Next: **{nxt[0]}** — 💡 {nxt[1]}")
            if lv:
                with st.expander("📚 What's installed"):
                    for i in range(lv):
                        n_, why = G.UPGRADES[key][i]
                        st.markdown(f"**L{i + 1} {n_}** — {why}")

    with st.expander("🎨 Livery"):
        with st.form("livery"):
            name = st.text_input("Car name", value=car["name"], max_chars=24)
            num = st.number_input("Number", 1, 99, value=int(car["number"]))
            color = st.color_picker("Paint", value=car["color"])
            if st.form_submit_button("Save livery"):
                car.update({"name": name.strip() or car["name"], "number": int(num), "color": color})
                save_state(state)
                st.rerun()

# ── Race ──
with tab_race:
    reasons = black_flag_reasons(state)
    if reasons:
        st.error("⬛ **Black flag.** Race control won't let you out: " + "; ".join(reasons) + ".")
        st.caption("Clear it on the Pit Wall / Garage, or finish tasks to get out of debt.")
    else:
        rating = car_rating(state)
        names = [t["name"] for t in TRACKS]
        def track_label(n: str) -> str:
            t = next(t for t in TRACKS if t["name"] == n)
            locked = lvl < t["level"]
            return f"{'🔒 ' if locked else ''}{n} — {t['laps']} laps" + (f" (level {t['level']})" if locked else "")

        pick = st.selectbox("Track", names, format_func=track_label)
        track = TRACKS[names.index(pick)]
        lo, hi = track["ai"]
        st.markdown(f"Your car **{rating:.0f}** vs rivals **{lo}–{hi}** · Entry **{track['fee']} 🪙** · "
                    f"Prizes 🥇{track['prize'][0]} 🥈{track['prize'][1]} 🥉{track['prize'][2]}")
        if car["condition"] < 40:
            st.warning("Car under 40% — real risk of a DNF.")
        if lvl < track["level"]:
            st.info(f"Unlocks at driver level {track['level']}. Earn XP by finishing tasks.")
        elif state["coins"] < track["fee"]:
            st.info("Can't cover the entry fee.")
        elif st.button("🚦 Lights out", type="primary"):
            bank(state, -track["fee"], f"🎟️ Entry: {track['name']}")
            simulate_race(state, track)

        if state["races"]:
            with st.expander("Race history"):
                for r in state["races"][:15]:
                    pos = r["pos"] if r["pos"] == "DNF" else f"P{r['pos']}"
                    st.markdown(f"**{pos}** {r['track']} · +{r['payout']} 🪙 "
                                f"<small>· {parse_dt(r['ts']):%b %d}</small>", unsafe_allow_html=True)

# ── Lounge ──
with tab_lounge:
    render_lounge(state)

# ── Settings ──
with tab_set:
    s = state["settings"]
    with st.form("settings"):
        st.subheader("You")
        pname = st.text_input("Driver name", value=s.get("player_name", "Driver"))
        sounds = st.toggle("Sound cues (win chime / fail buzzer)", value=s.get("sounds", True))
        focus_lock = st.toggle("🔒 Block games while a focus session runs", value=s.get("focus_lock", True))
        st.subheader("Rules")
        grace = st.number_input("Grace period after deadline (minutes)", 0, 240, value=int(s["grace_minutes"]))
        strict = st.toggle("Strict proof — a file is always required", value=s["strict_proof"])
        ext_h = st.number_input("Extension length (hours)", 1, 72, value=int(s["extension_hours"]))
        max_ext = st.number_input("Max extensions per task", 0, 5, value=int(s["max_extensions"]))
        st.subheader("Daily qualifying")
        dc = daily.cfg(state)
        q_by = st.number_input("Mission must be locked in by (hour, 24h)", 6, 16, value=int(dc["qualify_by"]))
        wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        rest = st.multiselect("Standing rest days (never penalized)", wd, default=[wd[i] for i in dc["rest_days"]])
        st.subheader("AI race steward (Claude)")
        ai = st.toggle("Have Claude verify proof", value=s["ai_steward"])
        model = st.text_input("Model", value=s["model"])
        st.subheader("Import from another Notion database (optional)")
        st.caption("Your synced Deadline or Die table is automatic. This is for pulling from an existing task list.")
        db = st.text_input("Database link or ID", value=s["notion_db"])
        dprop = st.text_input("Due-date property name (blank = first date property)", value=s["notion_date_prop"])
        fprop = st.text_input("Done property name (checkbox / status / select — optional)",
                              value=s["notion_done_prop"])
        if st.form_submit_button("Save settings", type="primary"):
            s.update({"player_name": pname.strip() or "Driver", "sounds": sounds, "focus_lock": focus_lock, "grace_minutes": int(grace), "strict_proof": strict, "extension_hours": int(ext_h),
                      "max_extensions": int(max_ext), "qualify_by": int(q_by), "rest_days": [wd.index(x) for x in rest],
                      "ai_steward": ai, "model": model.strip(),
                      "notion_db": db.strip(), "notion_date_prop": dprop.strip(),
                      "notion_done_prop": fprop.strip()})
            save_state(state)
            flash("Settings saved.")
            st.rerun()

    st.subheader("Connections")
    if notion_cfg():
        try:
            _ids = notion_ctx()[1]
            st.success("💾 Saving to Notion — your tasks table, save file and nagger memory live under your "
                       "Deadline or Die page.")
        except Exception as e:
            st.error(f"Notion configured but not reachable: {e}")
    else:
        st.info("💾 Saving to this machine only. Add NOTION_TOKEN + NOTION_PARENT_PAGE to save to Notion "
                "(required on Streamlit Cloud — its disk gets wiped).")
    topic = get_secret("NTFY_TOPIC")
    if topic:
        if st.button("📳 Send a test buzz to my phone"):
            ok = push(topic, "🏁 Deadline or Die", f"Test buzz, {PLAYER}. This is what a checkered flag feels like.",
                      priority=4, tags=["checkered_flag"], click=get_secret("APP_URL"))
            st.success("Sent — check your phone.") if ok else st.error("ntfy didn't accept it. Check the topic name.")
    else:
        st.caption("📳 Phone buzzes off — set NTFY_TOPIC (see README).")

    st.subheader("🗓️ Your DECK 12 board")
    st.caption("Link your existing board (e.g. Assignments): today's cards become one-tap mission suggestions, and "
               "Deadline or Die tasks due this week show up on it as 🏁 cards that tick off when you finish.")
    if not notion_cfg():
        st.caption("Needs the Notion connection first.")
    else:
        cur = s.get("board_db")
        if cur:
            try:
                st.success("Linked: " + B.describe(_board_map(get_secret("NOTION_TOKEN"), cur)))
            except Exception as e:
                st.error(f"Can't read the linked board: {e}. Is it inside DECK 12 (shared with the integration)?")
        if st.button("🔎 Find my boards"):
            try:
                n_, ids_ = notion_ctx()
                st.session_state["board_list"] = B.list_databases(n_, {ids_["tasks_db"].replace("-", "")})
            except Exception as e:
                st.error(str(e))
        dbs = st.session_state.get("board_list")
        if dbs is not None:
            if not dbs:
                st.info("No other databases are visible. If your board is a linked view, share its source database "
                        "with the Deadline or Die connection.")
            else:
                pick = st.selectbox("Which one is your board?", [d["id"] for d in dbs],
                                    format_func=lambda i: next(d["title"] for d in dbs if d["id"] == i))
                c1, c2 = st.columns(2)
                if c1.button("Test it"):
                    try:
                        m = B.detect(Notion(get_secret("NOTION_TOKEN")), pick)
                        st.info(B.describe(m))
                        items = B.pull_day(Notion(get_secret("NOTION_TOKEN")), m, now().date())
                        st.caption("Today on it: " + (", ".join(i["title"] for i in items) or "nothing"))
                    except Exception as e:
                        st.error(str(e))
                if c2.button("Link it", type="primary"):
                    s["board_db"] = pick
                    save_state(state)
                    st.session_state.pop("board_list", None)
                    flash("🗓️ Board linked. Today's cards now show up when you set your mission.")
                    st.rerun()
        if cur and st.button("Unlink board"):
            s["board_db"] = ""
            save_state(state)
            st.rerun()

    st.subheader("🔒 Lock enforcement")
    lt = LK.topic(get_secret("NTFY_TOPIC"))
    if lt:
        st.caption(f"Lock state is broadcast to **{lt}** — the PC enforcer and the iPhone Shortcut read it "
                   "(setup in the README). Current: " + LK.message(LK.status(state, now())))
    else:
        st.caption("Set NTFY_TOPIC to enable PC/phone locks.")
    if _pw:
        st.subheader("📱 Remember-me link")
        st.caption("Open this link once on your phone, then Share → Add to Home Screen: no password from then on. "
                   "Put it in the APP_URL secret (GitHub + Streamlit) so notifications open logged in too. "
                   "Treat it like a password.")
        st.code(f"{(get_secret('APP_URL') or '').split('?')[0]}?k={remember_key(_pw)}", language=None)

    st.subheader("📄 Zotero reading list")
    if zotero_cfg(state):
        zc_ = zotero_cfg(state)
        new_coll = st.text_input("Collection to pull papers from", value=zc_[2], key="zot_coll")
        c1, c2 = st.columns(2)
        if c1.button("Test Zotero"):
            try:
                ps = Z.to_read(*zc_[:2], new_coll)
                st.success(f"{len(ps)} unread papers in “{new_coll}”. First up: {Z.label(ps[0]) if ps else '—'}")
            except Exception as e:
                st.error(str(e))
        if c2.button("Save collection") and new_coll.strip():
            s["zotero_collection"] = new_coll.strip()
            save_state(state)
            st.rerun()
    else:
        st.caption("Add ZOTERO_USER_ID and ZOTERO_API_KEY below (or in secrets). Get both at zotero.org/settings/keys — "
                   "the user ID is shown at the top of that page.")

    st.subheader("Keys")
    st.caption("Best: put them in `.streamlit/secrets.toml` (or the Streamlit Cloud secrets box). "
               "Anything typed here lasts for this session only.")
    for name in ("ANTHROPIC_API_KEY", "NOTION_TOKEN", "NOTION_PARENT_PAGE", "NTFY_TOPIC", "APP_URL",
                 "ZOTERO_USER_ID", "ZOTERO_API_KEY"):
        if get_secret(name) and not st.session_state.get(f"secret_{name}"):
            st.caption(f"{name}: ✅ set in secrets")
            continue
        val = st.text_input(name, type="password" if "KEY" in name or "TOKEN" in name else "default",
                            key=f"in_{name}")
        if val:
            st.session_state[f"secret_{name}"] = val.strip()
        st.caption(f"{name}: {'✅ set' if get_secret(name) else '❌ not set'}")

    st.subheader("Backup")
    st.download_button("⬇️ Download save file", json.dumps(state, indent=2, default=str),
                       file_name=f"deadline-or-die-{now():%Y%m%d}.json", mime="application/json")
    restore = st.file_uploader("Restore from a save file", type=["json"], key="restore")
    if restore and st.button("Restore"):
        try:
            save_state(_merge(default_state(), json.loads(restore.getvalue())))
            flash("Save restored.")
            st.rerun()
        except Exception as e:
            st.error(f"Couldn't read that file: {e}")

    with st.expander("☠️ Danger zone"):
        if st.checkbox("I want to wipe everything") and st.button("Reset game"):
            save_state(default_state())
            flash("Fresh start.", "warning")
            st.rerun()
