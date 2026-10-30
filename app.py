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
import threading
import time
import uuid
from datetime import date, datetime, time as dtime, timedelta
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components



def _drop_stale_local_modules() -> None:
    """Streamlit Cloud re-runs app.py after a git pull but keeps the old copies of the other .py files in memory, so
    a new app.py can call something an old module doesn't have yet. If any of our modules changed on disk since it
    was imported (its .pyc still records the old source mtime), forget them all so the imports below load fresh."""
    import sys
    here = str(Path(__file__).resolve().parent) + os.sep
    mods = {n: m for n, m in list(sys.modules.items())  # string prefix check: resolving thousands of paths costs ~80 ms
            if n != "__main__" and isinstance(getattr(m, "__file__", None), str) and m.__file__.startswith(here)
            and os.sep not in m.__file__[len(here):]}

    def stale(m) -> bool:
        try:
            pyc = getattr(m, "__cached__", None)
            if not pyc or not os.path.exists(pyc):
                return False
            with open(pyc, "rb") as fh:
                head = fh.read(16)
            if int.from_bytes(head[4:8], "little") != 0:  # hash-based pyc: no mtime to compare
                return False
            return int(os.stat(m.__file__).st_mtime) & 0xFFFFFFFF != int.from_bytes(head[8:12], "little")
        except OSError:
            return False

    if any(stale(m) for m in mods.values()):
        for n in mods:
            sys.modules.pop(n, None)


_drop_stale_local_modules()

import board as B  # noqa: E402
import carart  # noqa: E402
import contracts as K
import events as EV
import garage as G
import insights as I
import daily
import dailies as DL
import locks as LK
import pomo as PM
import prayers as PR
import alarms as AL
import shield as SH
import tracks as TR
import journal as J
import nudges as NU
import prep as P
import quickparse as Q
import raceviz as RV
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

TRACKS = [  # prizes stay a side-dish to real work at every stage (see race_sim in the README)
    {"name": "Parking Lot Sprint", "laps": 3, "level": 1, "fee": 8, "ai": (30, 48), "prize": [50, 25, 12]},
    {"name": "Bow River Circuit", "laps": 5, "level": 2, "fee": 20, "ai": (55, 75), "prize": [90, 45, 22]},
    {"name": "Foothills Grand Prix", "laps": 7, "level": 4, "fee": 35, "ai": (80, 105), "prize": [140, 70, 35]},
    {"name": "Rockies 6 Hours", "laps": 10, "level": 6, "fee": 50, "ai": (115, 150), "prize": [200, 100, 50]},
    {"name": "Thesis Defense Ring", "laps": 12, "level": 8, "fee": 70, "ai": (150, 200), "prize": [260, 130, 65]},
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


SESSION_TTL = 90  # seconds before re-reading the save from Notion (and pulling new Notion tasks)


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


@st.cache_data(ttl=2400, show_spinner=False)
def _proof_url(token: str, page_id: str) -> str | None:
    """The proof file attached to a task's Notion page (Notion's file links last about an hour)."""
    try:
        pg = Notion(token).req("GET", f"/pages/{page_id}")
        f = ((pg.get("properties", {}).get("Proof file") or {}).get("files") or [None])[0]
        return (f.get("file") or f.get("external") or {}).get("url") if f else None
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _board_map(token: str, db: str) -> dict:
    return B.detect(Notion(token), db)


@st.cache_data(ttl=300, show_spinner=False)
def _board_today(token: str, db: str, day_iso: str) -> list[dict]:
    m = _board_map(token, db)
    return B.pull_day(Notion(token), m, date.fromisoformat(day_iso))


@st.cache_data(ttl=300, show_spinner=False)
def _board_range(token: str, db: str, start_iso: str, days: int) -> list[dict]:
    m = _board_map(token, db)
    return B.pull_range(Notion(token), m, date.fromisoformat(start_iso), days, tz=TZ)


@st.cache_data(ttl=600, show_spinner=False)
def _zotero_list(user: str, key: str, coll: str) -> list[dict]:
    return Z.to_read(user, key, coll)


def zotero_cfg(state: dict) -> tuple[str, str, str] | None:
    u, k = get_secret("ZOTERO_USER_ID"), get_secret("ZOTERO_API_KEY")
    return (str(u), k, state["settings"].get("zotero_collection") or "To Read") if u and k else None


def board_cfg(state: dict) -> tuple[str, str] | None:
    db, token = state["settings"].get("board_db"), get_secret("NOTION_TOKEN")
    return (token, db) if db and token else None


def out_cfg(state: dict) -> tuple[str, str] | None:
    """The write-only output board (e.g. Fortuna)."""
    db, token = state["settings"].get("out_db"), get_secret("NOTION_TOKEN")
    return (token, db) if db and token else None


def notion_ctx() -> tuple[Notion, dict] | None:
    cfg = notion_cfg()
    return (Notion(cfg[0]), _workspace(*cfg)) if cfg else None


def load_state() -> dict:
    """Notion save if configured (cached per session for SESSION_TTL), else the local file."""
    if not notion_cfg():
        return _load_local() or default_state()
    cached = st.session_state.get("_state")
    if cached is not None and (time.time() - st.session_state.get("_state_ts", 0) < SESSION_TTL
                               or _saver().pending()):
        return cached
    _saver().flush(5)  # never read Notion while our own write is still landing
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


def _push_tasks(n: Notion, ids: dict, state: dict, _retry: bool = True) -> list[str]:
    errors = _push_tasks_once(n, ids, state)
    if _retry and any("is not a property that exists" in e for e in errors):
        from notion_store import _dress_db  # a long-running server can predate newer columns: add them, retry once
        _dress_db(n, ids["tasks_db"])
        errors = _push_tasks_once(n, ids, state)
    return errors


def _push_tasks_once(n: Notion, ids: dict, state: dict) -> list[str]:
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


def remember_app_url(state: dict) -> None:
    """Save this app's own address (no key) so the GitHub nagger's pushes open the app even without APP_URL."""
    try:
        from urllib.parse import urlsplit
        u = urlsplit(st.context.url or "")
        base = f"{u.scheme}://{u.netloc}/" if u.scheme in ("http", "https") and u.netloc else None
    except Exception:  # noqa: BLE001
        base = None
    if base and "localhost" not in base and "127.0.0.1" not in base and state["settings"].get("app_url") != base:
        state["settings"]["app_url"] = base
        save_state(state)


def _hm_left(mins: int) -> str:
    h, m = divmod(int(mins), 60)
    return f"{h}h {m:02d}m" if h and m else f"{h}h" if h else f"{m}m"


def rebalance_pit_checks(state: dict) -> bool:
    """One-time: open, unstarted quick items (inbox, emails, calls, booking…) become 🔧 pit checks at honest times."""
    if state["settings"].get("honest_v1"):
        return False
    state["settings"]["honest_v1"] = True
    for t in state["tasks"]:
        if t.get("status") != "open" or (t.get("focus_min") or 0) > 0 or V.guess_category(t["title"]) != "pit":
            continue
        cat, mins = V.honest(t["title"], "pit", t.get("minutes"), chosen=True)
        if (cat, mins) != (t.get("category"), t.get("minutes")):
            v = V.value(cat, mins)
            t.update(category=cat, minutes=mins, difficulty=V.size_label(mins), reward=v["reward"],
                     penalty=v["penalty"], xp=v["xp"])
    return True


def _start_timer(state: dict, t: dict, mins: int) -> None:
    """Start a focus timer on `t` with your saved break setting."""
    cfg = state["settings"]
    preset = PM.PRESETS.get(cfg.get("pomo", "off"), ("", None))[1]
    work, brk = preset or ((cfg.get("pomo_work"), cfg.get("pomo_brk")) if cfg.get("pomo") == "custom" else (None, None))
    state["timer"] = {"task_id": t["id"], "start": now().isoformat(), "planned": int(mins), "work": work, "brk": brk}
    _mark_started(t)
    save_state(state)


def start_from_link(state: dict) -> None:
    """▶️ Start on a phone nudge opens ?go=<task id|new>&m=<min>: start that timer straight away, then tidy the URL."""
    go, m = st.query_params.get("go"), st.query_params.get("m")
    if not go:
        return
    for k in ("go", "m"):
        st.query_params.pop(k, None)
    if state.get("timer"):
        flash("⏱️ A timer is already running — carry on.", "info")
        return
    try:
        mins = max(5, min(240, int(m or 25)))
    except ValueError:
        mins = 25
    cfg = state["settings"]
    preset = PM.PRESETS.get(cfg.get("pomo", "off"), ("", None))[1]
    work, brk = preset or ((cfg.get("pomo_work"), cfg.get("pomo_brk")) if cfg.get("pomo") == "custom" else (None, None))
    t = next((x for x in state["tasks"] if x["id"] == go and x["status"] == "open"), None)
    if not t:
        t = _timer_task(state, "", mins, PM.wall_minutes(mins, work, brk))
    state["timer"] = {"task_id": t["id"], "start": now().isoformat(), "planned": mins, "work": work, "brk": brk}
    _mark_started(t)
    save_state(state)
    flash(f"▶️ **{t['title']}** — {mins}-min timer running. Phone face-down.", sound="win")


def sync_alarms(state: dict) -> None:
    """Top-of-run check (time passing changes the plan too): save only if the alarms changed."""
    if _refresh_alarms(state):
        save_state(state)


def _refresh_alarms(state: dict) -> bool:
    """Queue/cancel exact-time phone alarms on ntfy (alarms.py) in the background. True if anything changed."""
    topic = get_secret("NTFY_TOPIC")
    if not topic:
        return False
    posted = dict(state.get("alarms", {}))
    while AL.FAILED:  # last background send hit an error → retry those
        posted.pop(AL.FAILED.pop(), None)
    try:
        post, cancel, m = AL.diff(AL.plan(state, now(), globals().get("PROFILE")), posted, now())
    except Exception:  # noqa: BLE001 — alarms are best-effort, never break the app
        return False
    state["alarms"] = m
    if not (post or cancel):
        return False
    threading.Thread(target=AL.send, args=(topic, post, cancel, app_link()), daemon=True).start()
    return True


# ── saving: instant on screen, synced to Notion in the background ──
SYNC_FIELDS = ("sync_page", "_sig", "out_page", "out_state", "out_sig", "out_archived",
               "board_page", "board_state", "board_pushed", "board_archived", "board_src")
DASH_EVERY = 45  # seconds between dashboard refreshes


def _notion_sync(n: Notion, ids: dict, state: dict, out_map: dict | None, app_url: str | None,
                 dash: bool) -> list[str]:
    """All the Notion round-trips for one save. Mutates `state` (adds page ids) — never touches Streamlit."""
    errs = _push_tasks(n, ids, state)
    try:  # board problems never block saving
        errs += B.retract_pushed(n, state["tasks"])  # input board is read-only: undo old pushes
        if out_map:
            errs += B.sync_out(n, out_map, state["tasks"], now())
    except Exception as e:
        errs.append(f"board: {e}")
    save_json(n, ids["save_page"], state)
    if dash and ids.get("dashboard"):
        try:
            update_dashboard(n, ids["dashboard"], state, TZ, app_url)
        except NotionError:
            pass
    return errs


class _Saver:
    """One background worker per server. Coalesces rapid saves into one Notion write of the latest state,
    and remembers every Notion id it has created so a fast second click can never create a duplicate."""

    def __init__(self):
        self.lock, self.ev = threading.Lock(), threading.Event()
        self.job, self.busy, self.errors = None, False, []
        self.known: dict[str, dict] = {}   # task id -> sync fields (None = removed)
        self.last_dash, self.last_ok = 0.0, 0.0
        threading.Thread(target=self._run, daemon=True, name="dod-saver").start()

    def submit(self, live: dict, snapshot: str, ctx: tuple) -> None:
        with self.lock:
            self.job = (live, snapshot, ctx)
        self.ev.set()

    def pending(self) -> bool:
        return self.busy or self.job is not None

    def flush(self, timeout: float = 20) -> None:
        t0 = time.time()
        while self.pending() and time.time() - t0 < timeout:
            time.sleep(0.05)

    def _apply_known(self, tasks: list[dict]) -> None:
        for t in tasks:
            for f, v in self.known.get(t["id"], {}).items():
                if v is None:
                    t.pop(f, None)
                else:
                    t[f] = v

    def _run(self) -> None:
        while True:
            self.ev.wait()
            time.sleep(0.3)  # let a burst of taps coalesce
            with self.lock:
                self.ev.clear()
                job, self.job = self.job, None
                if not job:
                    continue
                self.busy = True
            live, snapshot, (token, ids, out_map, app_url) = job
            try:
                snap = json.loads(snapshot)
                self._apply_known(snap["tasks"])
                dash = time.time() - self.last_dash > DASH_EVERY
                errs = _notion_sync(Notion(token), ids, snap, out_map, app_url, dash)
                if dash:
                    self.last_dash = time.time()
                with self.lock:
                    for t in snap["tasks"]:
                        self.known[t["id"]] = {f: t.get(f) for f in SYNC_FIELDS}
                    self._apply_known(live.get("tasks", []))  # hand the new ids back to the live game
                    self.errors += errs
                    self.last_ok = time.time()
            except Exception as e:  # noqa: BLE001
                with self.lock:
                    self.errors.append(f"save: {e}")
            finally:
                with self.lock:
                    self.busy = False
                if self.job:
                    self.ev.set()


@st.cache_resource(show_spinner=False)
def _saver() -> _Saver:
    return _Saver()


def save_state(state: dict) -> None:
    broadcast_lock(state)
    _refresh_alarms(state)
    snapshot = json.dumps(state, default=str)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(snapshot)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass
    if not notion_cfg():
        return
    st.session_state["_state"], st.session_state["_state_ts"] = state, time.time()
    try:
        n, ids = notion_ctx()
        oc = out_cfg(state)
        out_map = _board_map(*oc) if oc else None
        if os.getenv("DOD_SYNC_SAVE"):  # tests: do it inline
            errs = _notion_sync(n, ids, state, out_map, get_secret("APP_URL"), True)
            if errs:
                flash("⚠️ Some tasks didn't sync to Notion: " + "; ".join(errs[:3]), "warning")
            return
        _saver().submit(state, snapshot, (get_secret("NOTION_TOKEN"), ids, out_map, get_secret("APP_URL")))
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
    """Local time. Tests can pin the clock to a time of day with DOD_TEST_CLOCK=HH:MM (today's date, real minutes
    keep ticking) so results don't depend on whether they run before or after the 11 AM qualifying cutoff."""
    real = datetime.now(TZ)
    pin = os.getenv("DOD_TEST_CLOCK")
    if pin:
        h, m = (int(x) for x in pin.split(":"))
        return real.replace(hour=h, minute=m)
    return real


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
    if delta < 0 and SH.is_penalty(reason):  # 🛡️ damage limiter: over the 24 h cap → held, not gone
        want = -int(delta)
        charged = SH.absorb(state, want, reason, now())
        if charged < want:
            note = f"🛡️ Damage capped: {want - charged} held from {reason[:48]}. Finish one task in {SH.HOLD_HOURS} h and it's cancelled."
            try:
                st.session_state.setdefault("flash", []).append(("info", note))
            except Exception:  # noqa: BLE001
                pass
        delta = -charged
        if not charged:
            return
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
    chosen = bool(minutes)
    minutes = int(minutes or V.minutes_for_size(difficulty))
    category = category if category in V.CATEGORIES else V.guess_category(title)
    category, minutes = V.honest(title, category, minutes, chosen=chosen)  # no inflated pit checks
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
    boost = state.get("boost_until")
    dbl = 2 if EV.is_double(at) or t.get("double") or (boost and parse_dt(boost) > at) else 1
    tok = state.setdefault("tokens", {"double": 0, "upgrade": 0})
    used_token = False
    if dbl == 1 and tok.get("double", 0) > 0:
        tok["double"] -= 1
        dbl, used_token = 2, True
    t["_guard"] = guard * dbl
    total = int(round(base * (1 + early + danger) * streak_mult * ext_cut * guard * dbl))
    parts = [f"base {base}"] + guard_why + (["×2 ⚡ token"] if used_token else ["×2 ⚡ double"] if dbl == 2 else [])
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
def timer_proof(t: dict) -> tuple[float, float]:
    """(minutes on the focus timer, minutes needed for the timer alone to count as proof: 80% of honest time)."""
    return float(t.get("focus_min") or 0), float(max(10, round(0.8 * (t.get("minutes") or 30))))


def render_proof_form(state: dict, t: dict, mode: str, scope: str = "") -> None:
    """mode: 'open' (normal completion) or 'redeem' (finishing a missed task for a partial refund)."""
    s = state["settings"]
    k = f"{scope}{mode}_{t['id']}"
    use_ai = s["ai_steward"] and bool(get_secret("ANTHROPIC_API_KEY"))
    fm, need = timer_proof(t)
    timer_ok = fm >= need
    if fm:
        dot = "#2ec4b6" if timer_ok else "#5b6070"
        tail = ("— that's your proof. A file or link is optional." if timer_ok else
                f"— log {need - fm:.0f} more min and the timer alone counts as proof.")
        st.markdown(f"<div class='dod-row' style='border:0;padding:2px 0 6px'><span class='dod-dot' "
                    f"style='background:{dot}'></span><div><b>⏱️ {fm:.0f} of {t.get('minutes') or 0} min on the "
                    f"focus timer</b> <span class='m'>{tail}</span></div></div>", unsafe_allow_html=True)
        if f"note_{k}" not in st.session_state:
            st.session_state[f"note_{k}"] = f"⏱️ {fm:.0f} min on the focus timer. "
    note = st.text_area("What did you do?", key=f"note_{k}", placeholder="Be specific — the steward reads this.")
    up = st.file_uploader("Proof file (photo, screenshot, PDF, code…)" + (" — optional" if timer_ok else ""),
                          type=PROOF_TYPES, key=f"file_{k}")
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
    if timer_ok:
        pass  # logged focus time is the proof: no file or link needed
    elif not up and (t.get("minutes") or 0) >= V.FILE_REQUIRED_FROM:
        errors.append(f"Tasks of {V.FILE_REQUIRED_FROM}+ min need a real file as proof (screenshot, doc, photo), "
                      f"or {need:.0f} min on the focus timer.")
    elif s["strict_proof"] and not up:
        errors.append(f"Strict mode: attach a file, or log {need:.0f} min on the focus timer.")
    if not timer_ok and not up and not link.strip():
        errors.append(f"Attach a file or a link, or log {need:.0f} min on the focus timer.")
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
                stamp = f"\n[App-verified: {fm:.0f} min logged on the focus timer for this task]" if fm else ""
                verdict = ai_verify(state, t, note + stamp, link, data, up.name if up else "", up.type if up else "")
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
              "proof_file": proof_path, "verdict": verdict, "proof_timer": round(fm, 1) if timer_ok else None})
    if mode == "open":
        reward, why = compute_reward(state, t, at)
        bank(state, reward, f"🏁 Done: {t['title']}")
        shield_msgs = SH.on_finish(state, at, reward, bank)
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
        msg += f"\n\n{crate}" + "".join(f"\n\n{m_}" for m_ in shield_msgs)
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
        for m_ in SH.on_finish(state, at, refund, bank):
            st.session_state.setdefault("flash", []).append(("success", m_))
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
         click=app_link())
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
    fk = st.session_state.setdefault(f"_{key}_n", 0)
    c1, c2 = st.columns(2)
    d = c1.date_input("Due date", value=now().date() + timedelta(days=1), min_value=now().date(), key=f"{key}_d{fk}")
    with c2:
        tm = time_wheel("Due time", dtime(23, 55), key=f"{key}_t{fk}")
    start_dt = start_picker(f"{key}_s{fk}", default=None, label="I'll start in (optional)")
    with st.form(key, clear_on_submit=True):
        title = st.text_input("Task", placeholder="e.g. Draft the methods section")
        details = st.text_area("Details / what counts as done", height=70)
        if goal_id is None and state["goals"]:
            opts = ["(no goal)"] + [g["title"] for g in state["goals"]]
            pick = st.selectbox("Part of goal", opts)
            gid = None if pick == "(no goal)" else state["goals"][opts.index(pick) - 1]["id"]
        else:
            gid = goal_id
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
                if start_dt:
                    t.update(scheduled=start_dt.isoformat(), scheduled_time=True)
                state["tasks"].append(t)
                st.session_state[f"_{key}_n"] = fk + 1
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


def track_rating(state: dict, track: dict) -> float:
    """Like car_rating, but parts this track rewards count 30% more."""
    car = state["car"]
    mid = car.get("model") if car.get("model") in CAR_BY_ID else CARS[0]["id"]
    eff = G.effective(car["parts"], mid)
    focus = RV.TRACK_CHARACTER.get(track["name"], ([], ""))[0]
    raw = CAR_BY_ID[mid]["base"] + sum(eff[k] * PARTS[k]["weight"] * (1.3 if k in focus else 1.0) for k in PARTS)
    return raw * (0.55 + 0.45 * car["condition"] / 100)


RACE_DAY_CAP = 3  # races a day, max — however rich you are
TICKET_MIN_TASK = 30  # a finish earns a ticket only if the task was worth 30+ honest minutes


def sandbag(state: dict, track: dict) -> float:
    """Prize multiplier: 1.0 on a fair track, shrinking (to 0.3) the more your car outclasses it."""
    r, hi = track_rating(state, track), track["ai"][1]
    return 1.0 if r <= hi else max(0.3, min(1.0, hi * 1.15 / r))


def race_tickets(state: dict) -> tuple[int, str]:
    """Races are earned: 1 ticket per proof-backed finish today + 1 per full focus session (25+ min) today."""
    today = now().date()
    iso = today.isoformat()
    finishes = sum(1 for t in daily.finished_on(state, today) if (t.get("minutes") or 0) >= TICKET_MIN_TASK)
    sessions = sum(1 for x in state.get("focus_log", []) if x.get("date") == iso and x.get("full") and x["min"] >= 25)
    raced = sum(1 for r in state.get("races", []) if r["ts"][:10] == iso)
    left = max(0, min(RACE_DAY_CAP, finishes + sessions) - raced)
    if raced >= RACE_DAY_CAP:
        why = f"That's {RACE_DAY_CAP} races today — the track's closed till tomorrow."
    elif not left:
        why = ("No race tickets. Finish a 30+ min task with proof, or complete a 25+ min focus session, "
               "to earn one.")
    else:
        why = f"🎟️ {left} race ticket{'s' if left > 1 else ''} · earned from {finishes} finish(es) + {sessions} session(s) today"
    return left, why


@st.fragment(run_every=2)
def _race_result(rp: dict) -> None:
    """The result stays hidden until the cars cross the line, then reveals itself (and refreshes your coins)."""
    if not rp.get("revealed"):
        left = rp["reveal_at"] - time.time()
        if left > 0:
            st.caption(f"🏁 Result in {int(left) + 1}s — watch it play out.")
            return
        rp["revealed"] = True
        kind, msg, snd, party = rp["result"]
        st.session_state["sound"] = snd
        if party:
            st.session_state["celebrate"] = True
        st.rerun()  # full app: coins in the cluster catch up, sound (and balloons) play
    kind, msg, *_ = rp["result"]
    getattr(st, kind)(msg)
    st.markdown(rp["why"])


def race_seconds(track: dict) -> int:
    return 8 + 5 * track["laps"]  # 23 s for a 3-lap sprint … 68 s for the 12-lap Ring


def simulate_race(state: dict, track: dict) -> None:
    car = state["car"]
    cond_before = car["condition"]
    heat_lvl = state["rival_heat"]
    you = {"name": f"#{car['number']} {car['name']}", "you": True,
           "rating": track_rating(state, track) + random.gauss(0, 5), "color": car["color"]}
    heat = 3 * heat_lvl  # your misses literally make them faster
    rivals = [{"name": n, "you": False, "rating": random.uniform(*track["ai"]) + heat + random.gauss(0, 5),
               "color": RV.RIVAL_COLORS[i]} for i, n in enumerate(random.sample(RIVALS, 5))]
    mult = sandbag(state, track)
    if mult < 1:  # you outclass the track: the fast guys show up too
        for r_ in rivals[:2]:
            r_["rating"] = you["rating"] * random.uniform(0.9, 1.06) + random.gauss(0, 5)
    field = [you] + rivals
    for f in field:
        f["dist"], f["dnf"] = 0.0, False
    ticks = track["laps"] * 6
    dnf_risk = 0.004 if car["condition"] < 40 else 0.0
    history, dnf_tick = [], None
    for i in range(ticks):
        for f in field:
            if f["dnf"]:
                continue
            if f["you"] and random.random() < dnf_risk:
                f["dnf"], dnf_tick = True, i
                continue
            f["dist"] += max(0, f["rating"] + random.gauss(0, 9))
        history.append([f["dist"] for f in field])

    order = sorted(field, key=lambda f: (not f["dnf"], f["dist"]), reverse=True)
    pos = next(i for i, f in enumerate(order, 1) if f["you"])
    payout = 0 if you["dnf"] else (round(track["prize"][pos - 1] * mult) if pos <= 3 else 0)
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
    names = [html.escape(f["name"]) for f in field]
    ticker = RV.narrate(history, [f["name"] for f in field], 0, track["laps"], track["name"], dnf_tick, random.Random())
    mid = car.get("model") if car.get("model") in CAR_BY_ID else CARS[0]["id"]
    why = RV.explain("DNF" if you["dnf"] else pos, gap, track["name"], cond_before, heat_lvl,
                     G.effective(car["parts"], mid), G.cap(mid), G.PART_INFO, G.installed, G.next_upgrade)
    if mult < 1:
        why += (f"\n- 🪜 Your car outclasses {track['name']}, so two fast rivals joined and prizes paid "
                f"×{mult:.2f}. Move up a track for full prizes.")
    secs = race_seconds(track)
    if you["dnf"]:
        res = ("error", f"💥 DNF at {track['name']} — the car gave out. Repair it before the next race.", "fail", False)
    elif pos == 1:
        res = ("success", f"🏆 **WIN** at {track['name']}! +{payout} coins. Tomorrow Tom eats your dust.", "jackpot", True)
    elif payout:
        res = ("success", f"P{pos} at {track['name']} — +{payout} coins. **{gap:.1f}s** off {winner['name']}.", "win", False)
    else:
        res = ("warning", f"P{pos} at {track['name']}, **{gap:.1f}s** off the win.", "fail", False)
    st.session_state["race_replay"] = {
        "html": RV.replay_html(track["name"], history, names, [f["color"] for f in field], 0, track["laps"],
                               ticker, dnf_tick, seconds=secs, start_ms=time.time() * 1000),
        "why": why, "title": track["name"], "result": res, "payout": payout,
        "reveal_at": time.time() + secs + 1, "revealed": False,
    }
    st.rerun()


def remember_key(pw: str) -> str:
    return hashlib.sha256(f"dod-remember:{pw}".encode()).hexdigest()[:24]


def make_safety_car(due: datetime) -> dict:
    return make_task(daily.SAFETY_CAR_TITLE, "Proof: a screenshot of a 30-min timer + one line on what you did.",
                     due, None, "🔒 Games locked on PC + phone until it's done", category="deep", minutes=30)


def _next_half_hour() -> dtime:
    n = now() + timedelta(minutes=30)
    return dtime(n.hour, 0 if n.minute < 30 else 30)


BOARD_LOOKAHEAD = 7       # qualifying shows today + this many days of board cards
EVENT_LOOKAHEAD = 60      # the event planner looks this far ahead


def _rel_day(dt: datetime, today: date) -> str:
    """'tonight' · '2 PM' · 'tmrw 9 AM' · 'Mon' — the shortest way to say when."""
    hm = dt.strftime("%I:%M %p").lstrip("0").replace(":00", "")
    if dt.date() == today:
        return "tonight" if dt.hour >= 23 else hm
    if dt.date() == today + timedelta(days=1):
        return "tmrw" if dt.hour >= 23 else f"tmrw {hm}"
    return f"{dt:%a}" if dt.hour >= 23 else f"{dt:%a} {hm}"


def _board_chip(b: dict, today: date) -> str:
    d = date.fromisoformat(b["date"]) if b.get("date") else today
    day = "today" if d == today else "tmrw" if d == today + timedelta(days=1) else f"{d:%a %b} {d.day}"
    when = (b.get("when") or "").replace(":00", "")
    return f"{b['title']} · {day}" + (f" {when}" if when else "") + (" · 🔁" if b.get("recurring") else "")


def _board_label(b: dict, today: date) -> str:
    d = date.fromisoformat(b["date"]) if b.get("date") else today
    day = "Today" if d == today else "Tomorrow" if d == today + timedelta(days=1) else f"{d:%a %b %d}"
    return (f"{day} · {b['title']}" + (f" · {b['when']}" if b.get("when") else "")
            + (" · 🔁 weekly" if b.get("recurring") else ""))


def render_coming_up(state: dict) -> None:
    """Countdown strip for event goals in the next 30 days — with the very next prep step."""
    today = now().date()
    lines = []
    for g in state["goals"]:
        if not g.get("event_page") and not g.get("event_kind"):
            continue
        days = (date.fromisoformat(g["target"]) - today).days
        if not 0 <= days <= 30:
            continue
        gt = [t for t in state["tasks"] if t.get("goal_id") == g["id"]]
        nxt = min((t for t in gt if t["status"] == "open"), key=lambda t: t["deadline"], default=None)
        done = sum(t["status"] in ("done", "redeemed") for t in gt)
        when = "TODAY" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
        lines.append(f"🗓️ **{g['title']}** {when} · prep {done}/{len(gt)}"
                     + (f" · next: *{nxt['title']}* ({parse_dt(nxt['deadline']):%a})" if nxt else ""))
    if lines:
        st.caption("  \n".join(lines[:3]))


def render_event_planner(state: dict) -> None:
    """Pick an upcoming event (board or typed) → a goal with a back-planned prep schedule."""
    today = now().date()
    bc = board_cfg(state)
    events = []
    if bc:
        try:
            taken = {B.clean_id(g.get("event_page") or "") for g in state["goals"]}
            events = [b for b in _board_range(*bc, (today + timedelta(days=1)).isoformat(), EVENT_LOOKAHEAD)
                      if B.clean_id(b["id"]) not in taken and not b.get("recurring")]
        except Exception as e:
            st.caption(f"(Couldn't read your board: {e})")
    opts = {b["id"]: _board_label(b, today) for b in events}
    opts["__typed"] = "✏️ Not on the board — type it"
    pick = st.selectbox("Event", list(opts), format_func=opts.get, key="ev_pick")
    if pick == "__typed":
        c1, c2 = st.columns([2, 1])
        title = c1.text_input("What is it?", placeholder="e.g. CSB conference — poster", key="ev_title")
        ev_date = c2.date_input("When", value=today + timedelta(days=21), min_value=today + timedelta(days=1),
                                key="ev_date")
        page = None
    else:
        b = next(x for x in events if x["id"] == pick)
        title, ev_date, page = b["title"], date.fromisoformat(b["date"]), b["id"]
    if not title.strip():
        return
    kinds = list(P.KINDS)
    c1, c2 = st.columns(2)
    kind = c1.selectbox("What do you need to prepare?", kinds, index=kinds.index(P.guess_kind(title)),
                        format_func=lambda k: P.KINDS[k][0], key=f"ev_kind_{pick}")
    gopts = ["__new"] + [g["id"] for g in state["goals"]]
    gl = {"__new": f"New goal: {title[:50]}", **{g["id"]: f"Feeds into: {g['title']}" for g in state["goals"]}}
    into = c2.selectbox("Goal", gopts, format_func=gl.get, key=f"ev_into_{pick}",
                        help="Make it its own goal, or let the prep count toward a bigger one you already have.")
    days = (ev_date - today).days
    st.caption(f"📅 {ev_date:%a %b %d} — **{days} days** away. Steps are planned backwards from the date"
               + (" (squeezed — it's close)." if days <= max(-o for o, *_ in P.KINDS[kind][1]) else ".")
               + " Edit anything, untick what you don't need.")
    plan = P.plan(kind, ev_date, today, label=title)
    df = pd.DataFrame([{"add": True, "title": s["title"], "due": s["due"], "minutes": s["minutes"],
                        "category": s["category"]} for s in plan])
    ed = st.data_editor(df, hide_index=True, key=f"ev_ed_{pick}_{kind}_{into}", use_container_width=True,
                        column_config={
                            "add": st.column_config.CheckboxColumn("✔", width="small"),
                            "title": st.column_config.TextColumn("Prep step", width="large"),
                            "due": st.column_config.DateColumn("Due", min_value=today, max_value=ev_date),
                            "minutes": st.column_config.SelectboxColumn("Honest time", options=V.MINUTES),
                            "category": st.column_config.SelectboxColumn("Type", options=list(V.CATEGORIES)),
                        })
    rows = [r for r in ed.to_dict("records") if r["add"] and str(r["title"]).strip() and to_date(r["due"])]
    total = sum(V.value(r["category"], int(r["minutes"]))["reward"] for r in rows)
    if st.button(f"🎯 Lock in the prep plan · {len(rows)} steps · worth {total} 🪙", type="primary",
                 key=f"ev_go_{pick}", disabled=not rows):
        if into == "__new":
            g = {"id": uuid.uuid4().hex[:10], "title": title.strip(), "why": f"📅 {ev_date:%a %b %d} — show up ready.",
                 "target": ev_date.isoformat(), "created": now().isoformat(), "claimed": False,
                 "event_page": page, "event_kind": kind}
            state["goals"].append(g)
        else:
            g = next(x for x in state["goals"] if x["id"] == into)
            g.setdefault("events", []).append({"title": title.strip(), "date": ev_date.isoformat(), "page": page})
            if page and not g.get("event_page"):
                g["event_page"] = page
        n_ = 0
        for r in rows:
            d = to_date(r["due"])
            dl = datetime.combine(d, dtime(23, 59), TZ)
            if dl <= now():
                continue
            pt = make_task(str(r["title"]).strip(), f"Prep for {title.strip()} ({ev_date:%b %d}).",
                           dl, None, "", g["id"], category=r["category"], minutes=int(r["minutes"]))
            pt.update(scheduled=datetime.combine(d, dtime(0, 0), TZ).isoformat(), scheduled_time=False)
            state["tasks"].append(pt)
            n_ += 1
        save_state(state)
        flash(f"🎯 **{g['title']}** — {n_} prep steps on the clock. The next 7 days of them are on your DECK 12 "
              "board now. Every step you finish fills the goal.", sound="win")
        st.rerun()



# ─────────────────────────── time entry: chips + scroll wheel ───────────────────────────
_WHEEL_DIR = Path(__file__).parent / "components" / "timewheel"
START_CHIPS = {"Now": 0, "30m": 30, "1h": 60, "2h": 120, "3h": 180, "🎡": None}


def time_wheel(label: str, value: dtime, key: str, step: int = 5) -> dtime:
    """iPhone-style scroll wheel (hour · minute · AM/PM). Falls back to a plain time box if components can't load."""
    try:
        import streamlit.components.v1 as components
        wheel = components.declare_component("timewheel", path=str(_WHEEL_DIR))
        acc = accent(st.session_state.get("_state") or {})[0]
        v = wheel(label=label, value=value.strftime("%H:%M"), step=step, accent=acc, key=key,
                  default=value.strftime("%H:%M"))
        h, m = (int(x) for x in str(v).split(":"))
        return dtime(h, m)
    except Exception:  # noqa: BLE001
        return st.time_input(label, value=value, key=f"{key}_fb")


def _round_up(d: datetime, step: int = 5) -> datetime:
    d = d.replace(second=0, microsecond=0)
    return d + timedelta(minutes=(-d.minute) % step)


def start_picker(key: str, default: str | None = "30m", label: str = "Start") -> datetime | None:
    """'Start: Now · 30m · 1h · 2h · 3h · 🎡'. The chosen time shows in the label. Returns None if not set."""
    opts = list(START_CHIPS)
    sel = st.session_state.get(f"{key}_chip", default)
    if sel in START_CHIPS and START_CHIPS[sel] is not None:
        shown = f"{label} · {_round_up(now() + timedelta(minutes=START_CHIPS[sel])):%I:%M %p}".replace("· 0", "· ")
    else:
        shown = label
    pick = st.pills(shown, opts, default=default, key=f"{key}_chip", selection_mode="single",
                    help="🎡 = pick an exact time on the wheel")
    if pick is None:
        return None
    if START_CHIPS[pick] is None:
        t = time_wheel("", _round_up(now() + timedelta(minutes=30), 15).time(), key=f"{key}_wheel")
        start = datetime.combine(now().date(), t, TZ)
        return start + timedelta(days=1) if start < now() - timedelta(minutes=5) else start
    return _round_up(now() + timedelta(minutes=START_CHIPS[pick]))


def _prayer_line(state: dict, count: int) -> str:
    """'Asr now · ends 6:17 PM' (red if it isn't logged) or 'next: Maghrib 6:17 PM'."""
    try:
        ps = PR.status(count, now(), **PR.settings_of(state))
    except Exception:  # noqa: BLE001
        return ""
    hm = lambda d: d.strftime("%I:%M %p").lstrip("0")  # noqa: E731
    cur, nxt = ps["current"], ps["next"]
    if cur and not ps["current_logged"]:
        mins = int((cur["end"] - now()).total_seconds() // 60)
        col = "#ff6a5c" if mins <= 45 else "#f5c518"
        return (f"<div style='font-size:.85rem;color:{col}'>🕌 {cur['name']} now · ends {hm(cur['end'])} "
                f"({mins} min)</div>")
    if nxt:
        return f"<div style='font-size:.85rem;color:#8b909c'>next: {nxt['name']} {hm(nxt['start'])}</div>"
    return "<div style='font-size:.85rem;color:#8b909c'>all of today's prayer windows are done</div>"


def _dl_tap(state: dict, h: dict, d, delta: int) -> None:
    """+1 / ↩ as a click callback: the dailies card redraws already updated, without rerunning the page."""
    n_ = DL.tap(state, h["id"], d, delta)
    save_state(state)
    if delta > 0 and n_ >= h["target"]:
        flash(f"🔁 **{h['name']}** {n_}/{h['target']} — claim it!", sound="win")
        st.session_state["_dl_full"] = True  # celebrate on the whole page


def _prayer_settings(state: dict, today, key: str) -> None:
    """Calculation method + Asr school and today's timetable — only shown where a prayer daily is involved."""
    ps_ = PR.settings_of(state)
    c5, c6 = st.columns(2)
    meth = c5.selectbox("Method", list(PR.METHODS), key=f"pr_method_{key}",
                        index=list(PR.METHODS).index(ps_["method"]) if ps_["method"] in PR.METHODS else 0)
    asr_ = c6.selectbox("Asr", list(PR.ASR), key=f"pr_asr_{key}",
                        index=list(PR.ASR).index(ps_["asr_school"]) if ps_["asr_school"] in PR.ASR else 0,
                        help="Standard (Shafi/Maliki/Hanbali) or Hanafi (later Asr).")
    if (meth, asr_) != (ps_["method"], ps_["asr_school"]):
        state["settings"].update(prayer_method=meth, prayer_asr=asr_)
        save_state(state)
    tt = PR.times_for(today, TZ, **PR.settings_of(state))
    st.caption("Today in Calgary: " + " · ".join(f"{k} {v:%I:%M}".replace(" 0", " ") for k, v in tt.items())
               + ". Reminders follow these windows; each +1 cancels that prayer's.")


REMIND_HOURS = [f"{h:02d}:00" for h in range(6, 24)]


def _hour_label(hm: str) -> str:
    t = datetime.strptime(hm, "%H:%M")
    return t.strftime("%I %p" if t.minute == 0 else "%I:%M %p").lstrip("0").replace(" AM", "a").replace(" PM", "p")


def _remind_picker(key: str, mode: str, cur, h: dict | None = None):
    """🔕 / 🔔 spread / ⏰ pick hours. Returns 'off', 'spread' or a sorted list of 'HH:MM'. Tapping hour chips means
    nothing can be mistyped."""
    m = st.segmented_control("Reminders", list(DL.REMIND_OPTS), default=mode, format_func=DL.REMIND_OPTS.get,
                             key=f"{key}_m", label_visibility="collapsed") or mode
    if m == "times":
        have = cur if isinstance(cur, list) and cur else ["08:00", "13:00", "20:00"]
        opts = sorted(set(REMIND_HOURS) | set(have))  # keep any older half-hour times visible
        picked = st.pills("Remind me at", opts, selection_mode="multi", default=have, format_func=_hour_label,
                          key=f"{key}_t", label_visibility="collapsed")
        if not picked:
            st.caption("Tap at least one hour — until then it keeps your last times.")
            return have
        return sorted(picked)
    times = DL.remind_times({**(h or {"target": 1}), "remind": "spread"}) if m == "spread" else []
    if times:
        st.caption("⏰ " + ", ".join(_hour_label(x) for x in times))
    return m


@st.fragment
def render_dailies(state: dict) -> None:
    if st.session_state.pop("_dl_full", False):
        st.rerun(scope="app")
    today = now().date()
    rows = DL.today_status(state, today)
    with st.container(border=True):
        if rows:
            done = sum(r["done"] for r in rows)
            stake, _ = DL.at_stake(state, today)
            st.markdown(f"#### 🔁 Dailies · {done}/{len(rows)}")
            if done == len(rows):
                note = "<div style='color:#2ec4b6;font-size:.88rem;margin-top:-.6rem'>All done today ✅</div>"
            elif stake:
                note = (f"<div style='color:#ff6a5c;font-size:.88rem;margin-top:-.6rem'>−{stake} 🪙 at midnight if "
                        "these aren't done</div>")
            else:
                note = ("<div style='color:#8b909c;font-size:.88rem;margin-top:-.6rem'>Day one is free: misses start "
                        "costing tomorrow</div>")
            st.markdown(note, unsafe_allow_html=True)
            for r in rows:
                h = r["h"]
                c1, c2, c3 = st.container(key=f"dlrow_{h['id']}").columns([5, 1, 2], vertical_alignment="center")
                dots = "●" * min(r["count"], h["target"]) + "○" * max(0, h["target"] - r["count"])
                c1.markdown(f"**{h['name']}** &nbsp;<span style='letter-spacing:2px;color:{'#199e70' if r['done'] else '#9aa0ad'}'>"
                            f"{dots}</span> <small>{r['count']}/{h['target']}"
                            + (f" · 🔥{h['streak']}" if h.get("streak") else "") + "</small>"
                            + (_prayer_line(state, r["count"]) if PR.is_prayer_daily(h) else ""),
                            unsafe_allow_html=True)
                c2.button("↩", key=f"dl_undo_{h['id']}", help="Undo one", disabled=r["count"] == 0,
                          on_click=_dl_tap, args=(state, h, today, -1))
                if r["done"] and not r["claimed"]:
                    if c3.button(f"🏆 Claim +{DL.reward(h)}", key=f"dl_claim_{h['id']}", type="primary",
                                 use_container_width=True):
                        DL.claim(state, h["id"], today, bank)
                        save_state(state)
                        flash(f"🔁 **{h['name']}** done for today — +{DL.reward(h)} 🪙 · streak {h['streak']} 🔥",
                              sound="win")
                        st.rerun(scope="app")
                elif r["claimed"]:
                    c3.markdown("✅ claimed")
                else:
                    c3.button("+1", key=f"dl_tap_{h['id']}", use_container_width=True,
                              on_click=_dl_tap, args=(state, h, today, 1))
        with st.expander("⚙️ Manage dailies" if rows else
                         "🔁 Dailies — water, prayers, brushing… (low reward, big penalty)"):
            live = [h for h in DL.habits(state) if not h.get("end") or h["end"] >= today.isoformat()]
            views = ["Your dailies", "＋ Add new"]
            if "_dl_view_next" in st.session_state:
                st.session_state["dl_view"] = st.session_state.pop("_dl_view_next")
            view = st.segmented_control("View", views, default=views[0] if live else views[1], key="dl_view",
                                        label_visibility="collapsed") or (views[0] if live else views[1])
            if view == views[1]:
                _daily_add_form(state, today)
            elif not live:
                st.caption("No dailies yet — add one.")
            else:
                for h in live:
                    _daily_card(state, h, today)
                st.caption("Removing a daily takes effect tomorrow, so today still counts.")


def _daily_card(state: dict, h: dict, today) -> None:
    """One daily: name, what it's worth, when it runs, and its reminders. Remove lives behind ⋯ (no fat-finger)."""
    ended = h.get("end") == today.isoformat()
    days = "every day" if len(h["days"]) == 7 else " ".join(DL.WEEKDAYS[i] for i in h["days"])
    is_pr = PR.is_prayer_daily(h)
    times = DL.remind_times(h)
    if is_pr:
        bell = "🔔 prayer windows"
    elif times:
        bell = "🔔 " + ", ".join(datetime.strptime(x, "%H:%M").strftime("%I:%M%p").lstrip("0").lower() for x in times[:4]) \
            + (f" +{len(times) - 4}" if len(times) > 4 else "")
    else:
        bell = "🔕 no reminders"
    with st.container(border=True):
        c1, c2 = st.container(key=f"dlh_{h['id']}").columns([6, 1], vertical_alignment="center")
        c1.markdown(f"**{html.escape(h['name'])}** &nbsp;<span class='m'>×{h['target']} a day</span>"
                    + ("&nbsp; <span style='color:#ff6a5c'>ends tonight</span>" if ended else ""),
                    unsafe_allow_html=True)
        with c2.popover("⋯", use_container_width=True):
            if ended:
                st.caption("Removed: it stops after tonight.")
                if st.button("↩ Keep it", key=f"dl_un_{h['id']}", use_container_width=True):
                    h["end"] = None  # changed your mind before midnight
                    save_state(state)
                    st.rerun(scope="app")
            else:
                st.caption("Stops tomorrow; today still counts.")
                if st.button("🗑 Remove", key=f"dl_rm_{h['id']}", use_container_width=True):
                    DL.remove(state, h["id"], today)
                    save_state(state)
                    st.rerun(scope="app")
        st.caption(f"+{DL.reward(h)} 🪙 done · −{DL.penalty(h)} 🪙 missed · {days} · {bell}")
        if ended:
            return
        if is_pr:
            with st.popover("🕌 Prayer times & method", use_container_width=True):
                _prayer_settings(state, today, h["id"])
        else:
            new_r = _remind_picker(f"dl_r_{h['id']}", DL.remind_mode(h), h.get("remind"), h)
            if new_r != (h.get("remind") or "off"):
                h["remind"] = new_r
                save_state(state)


def _daily_add_form(state: dict, today) -> None:
    names = [p[0] for p in DL.PRESETS] + ["✏️ Custom…"]
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    pick = c1.selectbox("Daily", names, key="dl_pick")
    target = c2.number_input("Times a day", 1, 20, dict(DL.PRESETS).get(pick, 1), key=f"dl_target_{pick}")
    name = st.text_input("Name", key="dl_name", placeholder="e.g. 🌙 Journal") if pick == names[-1] else pick
    days = st.pills("Days", list(range(7)), selection_mode="multi", default=list(range(7)),
                    format_func=lambda i: DL.WEEKDAYS[i], key="dl_days") or list(range(7))
    is_pr = PR.is_prayer_daily({"name": name or ""})
    rem = None
    if is_pr:
        st.caption("🕌 Reminders follow the real prayer windows.")
        _prayer_settings(state, today, "new")
    else:
        st.markdown("<div style='font-size:.85rem;color:#8b909c;margin:4px 0 -6px'>Reminders</div>",
                    unsafe_allow_html=True)
        rem = _remind_picker("dl_new", "spread", None, {"target": target})
    st.markdown(f"<div class='dod-row' style='border:0;padding:6px 0'><div>Worth <b>+{DL.reward(target)}</b> 🪙 when "
                f"done · <b>−{DL.penalty(target)}</b> 🪙 if missed at midnight <span class='m'>· set by the game: the "
                f"fewer times a day, the less it pays and the more it costs</span></div></div>", unsafe_allow_html=True)
    if st.button("➕ Add daily", type="primary", disabled=not (name or "").strip(), use_container_width=True):
        h = DL.add(state, name, target, days, today)
        if rem is not None:
            h["remind"] = rem
        st.session_state["_dl_view_next"] = "Your dailies"
        save_state(state)
        flash(f"🔁 **{h['name']}** ×{h['target']}/day added: +{DL.reward(h)} when done, −{DL.penalty(h)} if missed. "
              "Starts counting today.")
        st.rerun(scope="app")


DUE_CHIPS = {"6 PM": dtime(18, 0), "9 PM": dtime(21, 0), "Midnight": dtime(23, 59), "🎡": None}


def due_picker(key: str, default: str = "9 PM") -> dtime:
    """'Done by: 6 PM · 9 PM · Midnight · 🎡'. Chips already in the past are hidden."""
    opts = [k for k, v in DUE_CHIPS.items() if v is None or k == "Midnight"
            or datetime.combine(now().date(), v, TZ) > now() + timedelta(minutes=20)]
    default = default if default in opts else opts[0]
    pick = st.pills("Done by", opts, default=default, key=f"{key}_chip", selection_mode="single") or default
    if DUE_CHIPS[pick] is None:
        return time_wheel("", dtime(21, 0), key=f"{key}_wheel")
    return DUE_CHIPS[pick]


def _q_keep(state: dict | None) -> None:
    """Save the queued-but-not-locked tasks with the game, so a reload, a dropped connection or an app restart
    doesn't eat them."""
    if state is None:
        return
    items = [list(x) for x in st.session_state.get("q_pending", [])]
    cur = state.get("draft") or {}
    if not items and cur.get("date", "") > now().date().isoformat():
        return  # tomorrow's "one thing" from tonight's journal: leave it alone
    new = {"date": now().date().isoformat(), "items": items} if items else None
    if state.get("draft") != new:
        state["draft"] = new
        save_state(state)


def _qi(x) -> list:
    """A queued task as [text, minutes, category, set_by_you]. Old drafts were (text, minutes)."""
    x = list(x)
    if len(x) < 3:
        x.append(Q.parse(x[0], now())["category"])
    if len(x) < 4:
        x.append(False)
    return x


def _q_restore(state: dict) -> None:
    if "q_pending" not in st.session_state:
        d = state.get("draft") or {}
        st.session_state["q_pending"] = ([_qi(x) for x in d.get("items", [])]
                                         if d.get("date") == now().date().isoformat() else [])
    st.session_state["q_pending"] = [_qi(x) for x in st.session_state["q_pending"]]


TIME_CHIPS = {"10m": 10, "15m": 15, "30m": 30, "45m": 45, "1h": 60, "2h": 120}


def _q_put(txt: str, chip_min: int | None, state: dict | None) -> None:
    """Queue a typed task with the chosen time (a time typed in the text, like '45m', wins; no chip = our honest
    estimate, e.g. 10 min for inbox/email). Same name = replaced."""
    txt = txt.strip()
    p_ = Q.parse(txt, now())
    typed = re.search(r"\d+(?:\.\d+)?\s*(h|hr|hrs|hour|hours|m|min|mins|minutes)\b", txt, re.I)
    pend = st.session_state.setdefault("q_pending", [])
    pend[:] = [x for x in pend if Q.parse(x[0], now())["title"].lower() != p_["title"].lower()]
    cat, mins = p_["category"], p_["minutes"]
    if chip_min and not typed:
        cat, mins = V.honest(p_["title"], p_["category"], chip_min, chosen=True)
    pend.append([txt, mins, cat, bool(typed or chip_min)])  # no time given → our guess, shown as a suggestion
    _q_keep(state)


def _q_edit(i: int, key: str, state: dict | None) -> None:
    """Change a queued task's type or time from its suggestion chip."""
    pend = st.session_state.get("q_pending") or []
    if i >= len(pend):
        return
    it = _qi(pend[i])
    cat = st.session_state.get(f"{key}_c") or it[2]
    mins = TIME_CHIPS.get(st.session_state.get(f"{key}_m") or "", it[1])
    it[2], it[1] = V.honest(Q.parse(it[0], now())["title"], cat, mins, chosen=True)
    it[3] = True
    pend[i] = it
    _q_keep(state)


def _q_drop(i: int, state: dict | None) -> None:
    pend = st.session_state.get("q_pending") or []
    if i < len(pend):
        pend.pop(i)
        _q_keep(state)


def _render_queue(where, pending: list, fk: int, state: dict) -> None:
    """Queued tasks: title · a chip with our guess (type + time) you can tap to change · ✕."""
    if not pending:
        return
    with where:
        st.markdown("<div style='font-size:.85rem;color:#8b909c;margin:2px 0 4px'>Queued · <b>?</b> = our guess, "
                    "tap to change the type or time</div>", unsafe_allow_html=True)
        for i, x in enumerate(pending):
            txt, mins, cat, sure = _qi(x)
            title = Q.parse(txt, now())["title"]
            key = f"q_it{fk}_{i}_{hashlib.md5(txt.encode()).hexdigest()[:6]}"
            icon = V.CATEGORIES.get(cat, {}).get("label", "✅ x").split(" ")[0]
            short = {"pit": "Pit", "admin": "Admin", "deep": "Deep", "health": "Health", "life": "Life",
                     "show": "Show"}.get(cat, cat)
            c1, c2, c3 = st.container(key=f"qrow_{key}").columns([2, 1.6, 0.4], vertical_alignment="center")
            c1.markdown(f"**{html.escape(title)}**")
            with c2.popover(f"{icon} {short} · {mins}m" + ("" if sure else " ?"), use_container_width=True):
                st.pills("Type", list(V.CATEGORIES), default=cat, format_func=lambda k: V.CATEGORIES[k]["label"],
                         key=f"{key}_c", on_change=_q_edit, args=(i, key, state))
                cur = next((k for k, v in TIME_CHIPS.items() if v == mins), None)
                st.pills("Time", list(TIME_CHIPS), default=cur, key=f"{key}_m", on_change=_q_edit,
                         args=(i, key, state))
                st.caption("🔧 Pit checks cap at 15 min (inbox/email at 10) and don't count toward qualifying.")
            c3.button("✕", key=f"{key}_x", on_click=_q_drop, args=(i, state), help="Remove")


@st.fragment
def render_qualify_form(state: dict) -> None:
    today = now().date()
    fk = st.session_state.setdefault("_qf_n", 0)  # bumped after a lock-in to reset every field
    # ── pick from what you already have: tap to select. Grouped by where it came from, short labels. ──
    opts, groups = {}, {"t": [], "b": [], "z": []}
    default_t = []
    for t in sorted([t for t in state["tasks"] if t["status"] == "open"], key=lambda t: t["deadline"]):
        k = f"t:{t['id']}"
        opts[k] = (f"{t['title']} · {min_label(t.get('minutes') or 30)} · {_rel_day(parse_dt(t['deadline']), today)}", t)
        groups["t"].append(k)
        if parse_dt(t["deadline"]).date() <= today:
            default_t.append(k)
    bc = board_cfg(state)
    if bc:
        try:
            for b in _board_range(*bc, today.isoformat(), BOARD_LOOKAHEAD + 1):
                if not B.already_have(b, state["tasks"], date.fromisoformat(b["date"]) if b.get("date") else today):
                    k = f"b:{b['id']}"
                    opts[k] = (_board_chip(b, today), b)
                    groups["b"].append(k)
            groups["b"] = groups["b"][:10]
        except Exception as e:
            st.caption(f"(Couldn't read your board: {e})")
    zc = zotero_cfg(state)
    if zc:
        try:
            known_z = {t.get("zotero_key") for t in state["tasks"] if t["status"] == "open"}
            for p_ in [p_ for p_ in _zotero_list(*zc) if p_["key"] not in known_z][:6]:
                k = f"z:{p_['key']}"
                lab = Z.label(p_)
                opts[k] = ((lab[:52] + "…" if len(lab) > 53 else lab) + " · 45m", p_)
                groups["z"].append(k)
        except Exception as e:
            st.caption(f"(Couldn't read Zotero: {e})")
    picked = []
    heads = {"t": "✅ Your tasks", "b": "📅 On your board (prep / work on it)", "z": "📄 Reading list"}
    for g, keys in groups.items():
        if keys:
            picked += st.pills(heads[g], keys, selection_mode="multi", key=f"q_pick_{g}{fk}",
                               default=default_t if g == "t" else None, format_func=lambda k: opts[k][0]) or []
    _q_restore(state)
    pending = st.session_state["q_pending"]
    c1, c2 = st.columns([1.15, 1])
    with c1:
        start_dt = start_picker(f"q_start{fk}", default="30m")
    with c2:
        due_t = due_picker(f"q_due{fk}")
    start_t = (start_dt or now()).time()
    n_sel = len(picked) + len(pending)
    go_top = False
    if picked or pending:  # selected ≠ locked in: put the button right here, not below the fold
        sel_min = (sum((opts[k][1].get("minutes") or 60) for k in picked if k.startswith("t:"))
                   + sum(60 for k in picked if k.startswith("b:")) + sum(45 for k in picked if k.startswith("z:"))
                   + sum(_qi(x)[1] for x in pending))
        verb = "Add" if daily.peek_day(state, today).get("qualified") else "🚦 Lock in"
        go_top = st.button(f"{verb} {n_sel} · {min_label(sel_min)}", type="primary", use_container_width=True,
                           key=f"q_top{fk}", help="Selected isn't locked in until you tap this.")
    queue_slot = st.container()  # drawn after the form runs, so a new entry shows without a second redraw
    # one mini-form: type → tap a time → Enter (or Add). Nothing is taken until you add it, so tapping a time chip
    # never grabs half-typed text — and Lock it in is part of the form, so half-typed text gets locked in too.
    with st.form(f"q_form{fk}", clear_on_submit=True, border=False, enter_to_submit=True):
        c1, c2, c3 = st.columns([0.8, 1.05, 0.3], vertical_alignment="bottom")
        txt_ = c1.text_input("Add a task" if not opts else "Or add a new one", key=f"q_new{fk}",
                             placeholder="e.g. Write 300 words of methods — Enter to add")
        min_ = c2.segmented_control("Time", list(TIME_CHIPS), default=None, key=f"q_min{fk}",
                                    label_visibility="collapsed",
                                    help="Leave it unpicked for an honest estimate (inbox/email = 10 min)")
        add_ = c3.form_submit_button("＋ Add", use_container_width=True, help="Or press Enter")
        go_ = st.form_submit_button("🚦 Lock it in", type="primary", use_container_width=True)
    go_ = go_ or go_top
    if (add_ or go_) and (txt_ or "").strip():
        _q_put(txt_, TIME_CHIPS.get(min_) if min_ else None, state)
        pending = st.session_state["q_pending"]
    _render_queue(queue_slot, pending, fk, state)
    if not go_:
        return
    dl = datetime.combine(today, due_t, TZ)
    parsed = []
    for x in pending:
        ttl, mins_, cat_, _ = _qi(x)
        p_ = Q.parse(ttl, now())
        p_["minutes"], p_["category"] = mins_, cat_
        parsed.append(p_)
    minutes = (sum((opts[k][1].get("minutes") or 60) for k in picked
                   if k.startswith("t:") and V.counts_for_qualifying(opts[k][1]))
               + sum(60 for k in picked if k.startswith("b:")) + sum(45 for k in picked if k.startswith("z:"))
               + sum(p_["minutes"] for p_ in parsed if V.counts_for_qualifying(p_)))  # 🔧 pit checks don't count
    if dl <= now() + timedelta(minutes=5):  # late at night (or a time that's gone by): same time tomorrow
        dl += timedelta(days=1)
    if not parsed and not picked:
        st.error("Nothing to lock in yet. Type a task and press Enter (or Add), or pick one from your list.")
        return
    if minutes < daily.min_mission_minutes(state) and not daily.peek_day(state, today).get("qualified"):
        # the 30-min floor is for qualifying; once the day's locked in, additions are bonus and any size goes
        st.error(f"Too easy — {minutes} min of real work. Today's mission needs at least "
                 f"{daily.min_mission_minutes(state)}. 🔧 Pit checks (inbox, emails, calls…) don't count toward it. "
                 "Add something meatier, or put a time on it (e.g. “45m”).")
        return
    late_dl = dl if dl > now() + timedelta(minutes=5) else datetime.combine(today, dtime(23, 59), TZ)
    ids = []
    for k in picked:
        kind, obj = k[0], opts[k][1]
        if kind == "t":
            ids.append(obj["id"])
        elif kind == "b":
            b = obj
            if b["date"] and b["date"] > today.isoformat():  # future card → an hour of work on it today
                g = next((g for g in state["goals"] if B.clean_id(g.get("event_page") or "") == B.clean_id(b["id"])), None)
                t = make_task(f"Work on: {b['title']}", f"For {b['title']} on {date.fromisoformat(b['date']):%a %b %d} "
                              "(DECK 12 board). Proof: show what you made in the hour.", late_dl, None, "",
                              g["id"] if g else None, minutes=60)
            else:
                bt = None
                try:
                    bt = datetime.strptime(b["when"].upper().replace(".", ""), "%I:%M %p").time()
                    bdue = min(datetime.combine(today, bt, TZ) + timedelta(hours=2), datetime.combine(today, dtime(23, 59), TZ))
                except ValueError:
                    bdue = late_dl
                if bdue <= now() + timedelta(minutes=5):
                    bdue = datetime.combine(today, dtime(23, 59), TZ)
                t = make_task(b["title"], "From your DECK 12 board", bdue, None, "", minutes=60)
                if bt:
                    t.update(scheduled=datetime.combine(today, bt, TZ).isoformat(), scheduled_time=True)
            t["board_src"] = b["id"]  # remembered so it isn't suggested twice — never written to
            state["tasks"].append(t)
            ids.append(t["id"])
        else:
            p_ = obj
            t = make_task(f"📄 Read: {p_['title'][:80]}", f"Proof: photo/screenshot of your notes + a 2-line summary. "
                          f"{p_['url']}", late_dl, None, "", category="deep", minutes=45)
            t["zotero_key"] = p_["key"]
            state["tasks"].append(t)
            ids.append(t["id"])
    for p_ in parsed:
        t = make_task(p_["title"], "", p_["due"] if p_["when_given"] else dl, None, "", category=p_["category"],
                      minutes=p_["minutes"])
        if p_["at"]:
            t.update(scheduled=p_["at"].isoformat(), scheduled_time=True)
        state["tasks"].append(t)
        ids.append(t["id"])
    msg = daily.lock_in(state, now(), ids, start_t.strftime("%H:%M"), bank)
    st.session_state["_qf_n"] = fk + 1
    st.session_state["q_pending"] = []
    state["draft"] = None
    cursor = max(start_dt or now(), now()).replace(second=0, microsecond=0)  # 11:45 PM + 1h = tomorrow, not today
    for tid in ids:  # lay the mission out as a schedule from your start time (for the output board)
        t = next(x for x in state["tasks"] if x["id"] == tid)
        if t.get("scheduled") and parse_dt(t["scheduled"]).date() >= today:
            continue
        t.update(scheduled=cursor.isoformat(), scheduled_time=True)
        cursor += timedelta(minutes=(t.get("minutes") or 30) + 10)
    save_state(state)
    flash(msg + f" You start at **{start_t:%I:%M %p}** — the phone will check.".replace("**0", "**"), sound="win")
    st.rerun(scope="app")


def render_task_row(state: dict, t: dict, scope: str = "") -> None:
    """One open task: due chip + value; opens to finish (proof), extend or abandon."""
    s = state["settings"]
    dl = parse_dt(t["deadline"])
    fm_ = t.get("focus_min") or 0
    with st.expander(f"{chip(dl)} {t['title']} · {fmt_left(dl - now())} · +{t['reward']}"
                     + (f" · ⏱️ {fm_:.0f}/{t.get('minutes') or 0}m" if fm_ else "")):
        g = goal_title(state, t.get("goal_id"))
        st.markdown(
            f"**Due** {dl:%a %b %d, %I:%M %p} · **{t['difficulty']}** · +{t['reward']} 🪙 / −{t['penalty']} 🪙"
            + (f"  \n🎯 {g}" if g else "")
            + (f"  \n{t['details']}" if t.get("details") else "")
            + (f"  \n🚨 If missed: *{t['consequence']}*" if t.get("consequence") else "")
            + (f"  \n🚩 Rejected {t['rejections']}×" if t.get("rejections") else ""))
        render_proof_form(state, t, "open", scope=scope)

        st.divider()
        ca, cb = st.columns(2)
        ext_cost = math.ceil(t["penalty"] * 0.3)
        if t["extensions"] < s["max_extensions"]:
            if ca.button(f"⏳ +{s['extension_hours']}h ({ext_cost} 🪙)", key=f"{scope}ext_{t['id']}"):
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
        if cb.checkbox("Confirm", key=f"{scope}conf_{t['id']}") and cb.button(label, key=f"{scope}ab_{t['id']}"):
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



def render_today(state: dict) -> None:
    n_ = now()
    stt = daily.status(state, n_)
    c = daily.cfg(state)
    with st.container(border=True, key="live_card"):
        render_coming_up(state)
        _shield_strip(state, n_)
        if stt["bailout"]:
            b_ = stt["bailout"]
            st.markdown("### 🪂 Bailed out")
            st.caption(f"{b_['reason']} · {b_['why']}")
            st.markdown("<div class='dod-pills'><span>No zero-day</span><span>Dailies not charged</span>"
                        "<span>Streak frozen</span>" + (f"<span>{len(b_['moved'])} moved to tomorrow</span>"
                                                        if b_.get("moved") else "") + "</div>", unsafe_allow_html=True)
            st.caption("Rest, reset. Prayer reminders keep going; everything else is quiet until tomorrow.")
            return
        if stt["rest"]:
            st.markdown("### 🛌 Pit stop day")
            st.caption("Recharge. Nothing counts against you today. Back on the grid tomorrow.")
            return
        if not stt["qualified"] and stt["optional"]:
            st.markdown("### 🚦 Weekend: qualifying is optional")
            st.caption(f"Sleep in. Lock in a mission any time today for +{c['qualify_fuel']} fuel. Not locking in "
                       "costs nothing.")
            render_qualify_form(state)
            _bail_button(state, stt)
            return
        if not stt["qualified"]:
            left = stt["deadline"] - n_
            if left.total_seconds() > 0:
                st.markdown(f"### 🚦 Qualifying closes in {fmt_left(left)}")
                st.caption(f"Lock in today's mission before **{stt['deadline']:%I:%M %p}** for +{c['qualify_fuel']} fuel. "
                           f"Miss it and the safety car picks for you (−{c['qualify_penalty']}).")
            else:
                if daily.peek_day(state, n_.date()).get("excused"):
                    st.markdown("### 🚦 Lock in today's mission")
                    st.caption(f"Qualifying was excused (the app was down at the deadline). Locking in still pays "
                               f"+{c['qualify_fuel']}.")
                else:
                    st.markdown("### 🚦 Qualifying missed")
                    st.caption("The safety car is out. You can still lock in your own mission.")
            render_qualify_form(state)
            if stt["pit_stops_left"] and left.total_seconds() > 0:
                if st.checkbox("Pull out before qualifying (sick / too tired to start)", key="pit_chk") and \
                        st.button(f"🛌 Take a pit stop ({stt['pit_stops_left']} left this week)"):
                    daily.pit_stop(state, n_)
                    save_state(state)
                    flash("🛌 Pit stop. Rest properly — the grid forms again tomorrow.", "info")
                    st.rerun()
            else:
                _bail_button(state, stt)
            return
        m, done = stt["mission"], stt["mission_done"]
        open_m = [t for t in m if t["status"] == "open"]
        left_min = sum(t.get("minutes") or 30 for t in open_m)
        segs = "".join(f"<i class='{'ok' if t['status'] in ('done', 'redeemed') else 'bad' if t['status'] != 'open' else ''}'>"
                       "</i>" for t in m)
        pills = [f"🔥 Day streak <b>{stt['day_streak']}</b>" + ("" if stt["done_today"] else " · +1 on your first finish")]
        if stt["start_at"]:
            pills.append(f"🚦 Start <b>{datetime.strptime(stt['start_at'], '%H:%M'):%I:%M %p}</b>".replace("<b>0", "<b>"))
        pills.append(f"⏱️ <b>{focus_today(state)}</b> min focused")
        _am = J.peek(state, n_.date()).get("am")
        if _am:
            pills.append(f"☀️ {J.MOODS[_am['mood']]} {J.ENERGY[_am['energy']]}")
        st.markdown(
            f"<div class='dod-mh'><div class='dod-mt'>🏁 Today's mission</div><div class='dod-mb'>{len(done)}/{len(m)}"
            + (f" · {_hm_left(left_min)} to go" if open_m else " · done") + "</div></div>"
            f"<div class='dod-seg'>{segs}</div>"
            "<div class='dod-pills'>" + "".join(f"<span>{x}</span>" for x in pills) + "</div>", unsafe_allow_html=True)
        tm = state.get("timer")
        for t in m:
            if t["status"] in ("done", "redeemed"):
                st.markdown(f"<div class='dod-mrow ok'><span class='dod-dot'></span><div><s>{html.escape(t['title'])}</s>"
                            f" <span class='m'>+{t.get('reward', 0)} earned</span></div></div>", unsafe_allow_html=True)
            elif t["status"] == "open":
                dl = parse_dt(t["deadline"])
                fm_ = t.get("focus_min") or 0
                c1, c2 = st.container(key=f"mrow_{t['id']}").columns([6, 1], vertical_alignment="top")
                with c1.expander(f"{t['title']} · {min_label(t.get('minutes') or 30)} · {_rel_day(dl, n_.date())} · "
                                 f"+{t['reward']}" + (f" · ⏱️ {fm_:.0f}m" if fm_ else "")):
                    render_proof_form(state, t, "open", scope="today_")
                running = bool(tm) and tm.get("task_id") == t["id"]
                if c2.button("⏱️" if running else "▶", key=f"mgo_{t['id']}", use_container_width=True,
                             disabled=bool(tm), help="Running" if running else "Start a focus timer on this"):
                    mins = Q.session_length(t)
                    _start_timer(state, t, mins)
                    flash(f"▶️ **{t['title']}** — {mins}-min timer running. Phone face-down.", sound="win")
                    st.rerun()
            else:
                st.markdown(f"<div class='dod-mrow bad'><span class='dod-dot'></span><div>{html.escape(t['title'])}"
                            f" <span class='m'>missed</span></div></div>", unsafe_allow_html=True)
        if m and len(done) == len(m):
            st.success("Mission complete. Anything else today is pure bonus. 🏆")
        elif not stt["done_today"] and n_.hour >= 18:
            st.warning(f"⚠️ Zero finishes so far. Midnight = −{c['zero_day_penalty']} coins and your day streak dies. "
                       "Do the smallest one now.")
        with st.expander("➕ Add to today's mission"):
            render_qualify_form(state)
        _bail_button(state, stt)


# ── 📓 journal: morning check-in, evening questionnaire, weekly recap ──
def _scale_pills(label: str, opts: dict, key: str, default=None):
    return st.pills(label, list(opts), default=default, key=key, format_func=lambda k: opts[k])


def _shield_strip(state: dict, n_: datetime) -> None:
    """🛡️ What the damage limiter is holding / offering right now (only shows when something's on the table)."""
    bits = []
    held = SH.held_total(state)
    if held:
        until = min(parse_dt(h["until"]) for h in state["held"])
        bits.append(f"<span class='hot'>🛡️ <b>{held}</b> held · finish one task by {until:%a %I:%M %p}".replace(" 0", " ")
                    + " and it's cancelled</span>")
    offer = SH.comeback_offer(state, n_)
    if offer:
        bits.append(f"<span class='hot'>🔥 Comeback: your first finish today wins back <b>+{offer}</b></span>")
    if state.get("coins", 0) < 0:
        bits.append("<span>🔧 In debt: finishes pay <b>+25%</b> until you're out</span>")
    if state.get("shields"):
        bits.append(f"<span>🛡️ Streak shields <b>{state['shields']}</b>/{SH.SHIELD_MAX}</span>")
    if bits:
        st.markdown("<div class='dod-pills dod-shield'>" + "".join(bits) + "</div>", unsafe_allow_html=True)


def _bail_button(state: dict, stt: dict) -> None:
    left = stt.get("bailouts_left", 0)
    if left:
        if st.button("🪂 Rough day? Bail out", type="tertiary", key="bail_open",
                     help=f"Pull the cord on today, any time. {left} left this week."):
            st.session_state.pop("bail_s2", None)
            st.session_state["bail_show"] = True
        if st.session_state.get("bail_show"):
            _bail_dialog(state)
    else:
        st.caption("🪂 This week's bailout is used.")


def _bail_close() -> None:
    for k in ("bail_show", "bail_s2"):
        st.session_state.pop(k, None)


@st.dialog("🪂 Bail out of today", on_dismiss=_bail_close)
def _bail_dialog(state: dict) -> None:
    n_ = now()
    st.caption(f"Once a week ({daily.bailouts_left(state, n_.date())} left). Today stops counting against you, "
               "but it should cost you a moment of honesty.")
    reason = st.pills("1 · What's going on?", daily.BAIL_REASONS, key="bail_r")
    if not reason:
        return
    small = sorted((t for t in state["tasks"] if t["status"] == "open"), key=lambda t: t.get("minutes") or 30)
    if not st.session_state.get("bail_s2"):
        st.markdown("**2 · Before you pull the cord**")
        if small and reason not in ("🚨 Emergency", "🤒 Sick"):
            t = small[0]
            st.caption(f"Could you do just 10 minutes of **{t['title']}** instead? Ten minutes keeps the day alive.")
            c1, c2 = st.columns(2)
            if c1.button("⏱️ Do 10 min instead", type="primary", use_container_width=True, key="bail_10"):
                _start_timer(state, t, 10)
                _bail_close()
                flash(f"⏱️ 10 minutes on **{t['title']}**. That's all. Then decide.", sound="win")
                st.rerun()
            c2.button("No, I need out", use_container_width=True, key="bail_no",
                      on_click=lambda: st.session_state.__setitem__("bail_s2", True))
            return
        st.session_state["bail_s2"] = True
    why = st.text_area("3 · In a sentence: what happened, and what will you do instead?", key="bail_why",
                       placeholder="e.g. Car died on the highway, spent the day sorting the tow. Early night, "
                                   "restart tomorrow at 9.", max_chars=300)
    moving = [t for t in daily.bail_preview(state, n_) if not t["title"].startswith("🚨 Safety car")]
    st.markdown("**4 · What happens**")
    st.markdown("- No zero-day penalty; today's dailies aren't charged\n- Your day streak is frozen (not broken)\n"
                + (f"- Moves to tomorrow: {', '.join(t['title'] for t in moving)}\n" if moving else "")
                + "- Penalties already taken today stay taken\n- Uses this week's bailout")
    conf = st.text_input("Type BAIL OUT to confirm", key="bail_conf")
    ok = len((why or "").strip()) >= 25 and conf.strip().upper() == "BAIL OUT"
    if len((why or "").strip()) < 25:
        st.caption("A real sentence, please (25+ characters).")
    if st.button("🪂 Pull the cord", type="primary", disabled=not ok, use_container_width=True, key="bail_go"):
        res = daily.bail_out(state, n_, reason, why)
        if res is None:
            st.error("No bailout left this week.")
            return
        save_state(state)
        _bail_close()
        flash("🪂 Bailed out. Today doesn't count against you" + (f"; {len(res['moved'])} task(s) moved to tomorrow"
                                                                 if res["moved"] else "") + ". Rest, reset.", "info")
        st.rerun()


def render_checkin(state: dict) -> None:
    """One tap on the way in. Only before 3 PM and only until you've answered."""
    d = now().date()
    if J.peek(state, d).get("am") or now().hour >= 15:
        return
    with st.container(border=True, key="checkin"):
        st.markdown("<div class='dod-ci'>☀️ <b>How are you starting today?</b> <span class='m'>+2 · one tap each</span>"
                    "</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            mood = _scale_pills("Mood", J.MOODS, "ci_mood")
        with c2:
            energy = _scale_pills("Energy", J.ENERGY, "ci_energy")
        if mood and energy:
            got = J.check_in(state, d, mood, energy, now(), bank)
            save_state(state)
            flash(f"☀️ Logged: {J.MOODS[mood]} {J.MOOD_WORDS[mood]}, energy {J.ENERGY[energy]}"
                  + (f" · +{got}" if got else ""))
            st.rerun()


def _journal_form(state: dict, d, key: str) -> None:
    pm = J.peek(state, d).get("pm") or {}
    with st.form(f"jf_{key}", border=False):
        c1, c2 = st.columns(2)
        with c1:
            mood = _scale_pills("How was the day?", J.MOODS, f"{key}_mood", pm.get("mood"))
        with c2:
            energy = _scale_pills("Energy now", J.ENERGY, f"{key}_energy", pm.get("energy"))
        ans = {}
        for k, q, ph in J.QUESTIONS:
            ans[k] = st.text_input(q, value=pm.get(k, ""), placeholder=ph, key=f"{key}_{k}", max_chars=240)
        to_q = st.checkbox("Put “the one thing” into tomorrow's mission queue", value=True, key=f"{key}_toq")
        paid = pm.get("paid", 0)
        sub = st.form_submit_button("📓 Save the day" + (f" · up to +{J.PM_MAX - paid}" if paid < J.PM_MAX else ""),
                                    type="primary", use_container_width=True)
    if sub:
        if not (mood and energy):
            st.error("Pick a mood and an energy level first.")
            return
        got = J.close_day(state, d, {**ans, "mood": mood, "energy": energy}, now(), bank)
        tmr = (ans.get("tomorrow") or "").strip()
        if to_q and tmr and d == now().date():
            p_ = Q.parse(tmr, now() + timedelta(days=1))
            state["draft"] = {"date": (d + timedelta(days=1)).isoformat(),
                              "items": [[tmr, p_["minutes"], p_["category"], False]]}
        save_state(state)
        flash(f"📓 Day saved{f' · +{got}' if got else ''}. {J.MOODS[mood]} — see it any time in Stats → Journal.")
        st.rerun()


def render_close_day(state: dict) -> None:
    """From 5 PM: a short end-of-day questionnaire. Pays a little, once."""
    d = now().date()
    if now().hour < J.PM_OPENS:
        return
    pm = J.peek(state, d).get("pm")
    if pm:
        st.markdown(f"<div class='dod-mrow ok'><span class='dod-dot'></span><div>📓 Day journaled "
                    f"{J.MOODS[pm['mood']]} <span class='m'>· +{pm.get('paid', 0)} · edit in Stats → Journal</span></div>"
                    "</div>", unsafe_allow_html=True)
        return
    with st.container(border=True, key="closeday"):
        st.markdown(f"### 📓 Close the day")
        st.caption(f"Two taps and a few lines. +{J.PM_BASE} for the taps, +{J.PM_PER_ANSWER} per real answer "
                   f"(up to +{J.PM_MAX}). It all lands in Stats → Journal and your weekly recap.")
        _journal_form(state, d, "cd")


def render_journal(state: dict) -> None:
    today = now().date()
    ws_this = J.week_start(today)
    pick = st.segmented_control("Week", ["This week", "Last week"], default="This week", key="jr_week",
                                label_visibility="collapsed") or "This week"
    ws = ws_this if pick == "This week" else ws_this - timedelta(days=7)
    r = J.recap(state, ws, TZ, through=today if pick == "This week" else None)
    end = ws + timedelta(days=6)
    st.markdown(f"#### 🗓️ {'Week so far' if pick == 'This week' and today < end else 'Weekly recap'} · "
                f"{ws:%b} {ws.day}–{end:%b} {end.day}")
    st.markdown("<div class='dod-pills'>"
                f"<span>⏱️ <b>{r['focus_min'] / 60:.1f} h</b> focused</span><span>✅ <b>{r['done']}</b> done</span>"
                f"<span>Mood <b>{J.mood_face(r['mood_avg'])}</b>"
                + (f" {r['mood_avg']:.1f}/5" if r["mood_avg"] is not None else "") + "</span>"
                f"<span>📓 <b>{r['journaled']}</b>/7 journaled</span>"
                + (f"<span>🏆 Best: <b>{r['best']['date']:%a}</b> {r['best']['focus'] / 60:.1f} h</span>" if r["best"] else "")
                + "</div>", unsafe_allow_html=True)
    import altair as alt
    acc = accent(state)[0]
    df = pd.DataFrame([{"Day": f"{x['date']:%a}", "i": k, "Focus h": round(x["focus"] / 60, 2),
                        "Mood": x["mood"], "Face": J.mood_face(x["mood"]) if x["mood"] is not None else ""}
                       for k, x in enumerate(r["rows"])])
    if not df.empty:
        base = alt.Chart(df).encode(x=alt.X("Day:N", sort=alt.SortField("i"), title=None,
                                             axis=alt.Axis(labelAngle=0)))
        bars = base.mark_bar(cornerRadiusEnd=4, color=acc, size=26).encode(
            y=alt.Y("Focus h:Q", title="Focus hours"), tooltip=["Day", "Focus h", "Mood"])
        faces = base.mark_text(dy=-12, fontSize=18).encode(y=alt.Y("Focus h:Q"), text="Face:N")
        _chart((bars + faces).properties(height=200))
    if r["focus_good_mood"] is not None and r["focus_low_mood"] is not None:
        st.caption(f"On 🙂/😄 days you focused {r['focus_good_mood']:.0f} min; on 😕/😫 days, "
                   f"{r['focus_low_mood']:.0f} min.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🏆 Wins**")
        st.markdown("\n".join(f"- *{d_:%a}* {html.escape(w)}" for d_, w in r["wins"]) or "<span class='m'>None "
                    "written yet.</span>", unsafe_allow_html=True)
    with c2:
        st.markdown("**🧱 What got in the way**")
        st.markdown("\n".join(f"- *{d_:%a}* {html.escape(b)}" for d_, b in r["blockers"]) or "<span class='m'>"
                    "Nothing logged.</span>", unsafe_allow_html=True)
    with st.expander("📋 Recap to paste"):
        st.code(J.recap_text(r), language=None)
    st.markdown("#### 📓 Days")
    if not J.peek(state, today).get("pm"):
        with st.expander(f"✏️ Today, {today:%a %b} {today.day} · not journaled yet"):
            _journal_form(state, today, "jt")
    ents = J.entries(state)
    if not ents:
        st.caption("Your check-ins and evening entries land here, one card per day.")
    for d_, e in ents[:30]:
        am, pm = e.get("am") or {}, e.get("pm") or {}
        done = J.done_on(state, d_, TZ)
        head = (f"{d_:%a %b} {d_.day} · " + (f"{J.MOODS[am['mood']]}" if am else "·") + " → "
                + (f"{J.MOODS[pm['mood']]}" if pm else "·") + f" · ⏱️ {J.focus_on(state, d_) / 60:.1f} h · ✅ {len(done)}")
        with st.expander(head):
            if d_ == today and pm:
                _journal_form(state, d_, f"je_{d_.isoformat()}")
                continue
            for k, q, _ in J.QUESTIONS:
                if pm.get(k):
                    st.markdown(f"**{q}**  \n{html.escape(pm[k])}")
            if done:
                st.caption("Finished: " + " · ".join(t["title"] for t in done[:8]))
            if not pm:
                st.caption("No evening entry that day.")


IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
SCRAP_PERIODS = ["This week", "Last week", "This month", "All"]


def _scrap_tasks(state: dict, period: str) -> list[dict]:
    today = now().date()
    wk = today - timedelta(days=today.weekday())
    lo, hi = {"This week": (wk, today), "Last week": (wk - timedelta(days=7), wk - timedelta(days=1)),
              "This month": (today.replace(day=1), today)}.get(period, (date.min, date.max))
    out = []
    for t in state["tasks"]:
        if t.get("status") in ("done", "redeemed") and t.get("completed_at"):
            d = parse_dt(t["completed_at"]).date()
            if lo <= d <= hi:
                out.append(t)
    return sorted(out, key=lambda t: t["completed_at"], reverse=True)


def _recap_text(ts: list[dict], period: str) -> str:
    by = {}
    for t in ts:
        by.setdefault(t.get("category") or "admin", []).append(t)
    lines = [f"{period}: {len(ts)} things done · {sum(t.get('minutes') or 0 for t in ts) / 60:.1f} h"]
    for cat in V.CATEGORIES:
        if by.get(cat):
            lines.append(f"\n{V.CATEGORIES[cat]['label']}")
            for t in sorted(by[cat], key=lambda t: t["completed_at"]):
                note = re.sub(r"^\s*(⏱️)?\s*[\d.]+ min on the focus timer\.\s*", "", t.get("proof_note") or "")
                note = note.strip().split("\n")[0][:90]
                lines.append(f"• {t['title']} ({parse_dt(t['completed_at']):%a}, {min_label(t.get('minutes') or 0)})"
                             + (f" — {note}" if note and not note.lower().startswith(t['title'].lower()) else ""))
    return "\n".join(lines)


def render_scrapbook(state: dict) -> None:
    """📸 Everything you've proven, by week: the photo, what you wrote, the link, the time. Plus a recap to paste."""
    per = st.segmented_control("Period", SCRAP_PERIODS, default="This week", key="sb_per",
                               label_visibility="collapsed") or "This week"
    ts = _scrap_tasks(state, per)
    if not ts:
        st.caption("Nothing finished in this period yet. Every proof you submit lands here.")
        return
    mins = sum(t.get("minutes") or 0 for t in ts)
    timed = sum(t.get("focus_min") or 0 for t in ts)
    st.markdown(f"<div class='dod-pills'><span>✅ <b>{len(ts)}</b> done</span><span>🕒 <b>{mins / 60:.1f} h</b> of work"
                f"</span><span>⏱️ <b>{timed / 60:.1f} h</b> on the timer</span><span>🪙 <b>+{sum(t.get('reward', 0) for t in ts)}"
                f"</b></span></div>", unsafe_allow_html=True)
    with st.expander("📋 Recap to paste (supervisor meeting, journal, thesis log)"):
        st.code(_recap_text(ts, per), language=None)
    cfg = notion_cfg()
    cols = st.columns(3)
    fetched = 0
    for i, t in enumerate(ts[:36]):
        with cols[i % 3].container(border=True, key=f"scrap_{t['id']}"):
            img = None
            pf = t.get("proof_file") or ""
            if pf.lower().endswith(IMG_EXT) and Path(pf).exists():
                img = pf
            elif pf.lower().endswith(IMG_EXT) and cfg and t.get("sync_page") and fetched < 12:
                fetched += 1
                img = _proof_url(cfg[0], t["sync_page"])
            if img:
                try:
                    st.image(img, width="stretch")
                except Exception:  # noqa: BLE001
                    img = None
            if not img:
                icon = V.CATEGORIES.get(t.get("category") or "", {}).get("label", "✅ ").split(" ")[0]
                st.markdown(f"<div class='dod-scrap-tile'>{icon}</div>", unsafe_allow_html=True)
            d = parse_dt(t["completed_at"])
            badges = []
            if t.get("proof_timer") or (t.get("focus_min") or 0) >= 1:
                badges.append(f"⏱️ {int(t.get('proof_timer') or t.get('focus_min'))}m")
            if t.get("status") == "redeemed":
                badges.append("🩹 late")
            st.markdown(f"**{html.escape(t['title'])}**  \n<span class='m' style='color:#8b909c;font-size:.85rem'>"
                        f"{d:%a %b} {d.day} · {min_label(t.get('minutes') or 0)} · +{t.get('reward', 0)}"
                        + (" · " + " · ".join(badges) if badges else "") + "</span>", unsafe_allow_html=True)
            note = re.sub(r"^\s*(⏱️)?\s*[\d.]+ min on the focus timer\.\s*", "", t.get("proof_note") or "").strip()
            if note:
                st.caption(note[:180] + ("…" if len(note) > 180 else ""))
            if t.get("proof_link"):
                st.markdown(f"[↗ Open the proof]({t['proof_link']})")
    if len(ts) > 36:
        st.caption(f"…and {len(ts) - 36} more. Narrow the period to see them.")


def focus_today(state: dict) -> int:
    today = now().date().isoformat()
    return int(sum(x["min"] for x in state.get("focus_log", []) if x["date"] == today))


def _add_quick(state: dict, title: str, minutes: int, due: datetime, category: str, at: datetime | None = None) -> dict:
    t = make_task(title, "", due, None, "", category=category, minutes=minutes)
    if at:
        t.update(scheduled=at.isoformat(), scheduled_time=True)
    stt = daily.status(state, now())
    if due.date() == now().date() and stt["qualified"]:
        t["mission_day"] = now().date().isoformat()
    state["tasks"].append(t)
    save_state(state)
    return t


def _tpl_pick(key: str) -> None:
    """A preset fills the editor — nothing is added until you confirm."""
    label = st.session_state.get(f"{key}_tpls")
    if not label:
        return
    _, mins, cat = next(x for x in Q.TEMPLATES if x[0] == label)
    st.session_state[f"{key}_draft"] = {"title": label.split(" ", 1)[1], "minutes": mins, "cat": cat,
                                        "due": datetime.combine(now().date(), dtime(23, 59), TZ).isoformat(), "at": None,
                                        "v": st.session_state.get(f"{key}_draft", {}).get("v", 0) + 1}
    st.session_state[f"{key}_tpls"] = None


SHORT_CAT = {"pit": "🔧 Pit", "admin": "📨 Admin", "deep": "🧠 Deep", "health": "💪 Health", "life": "🧺 Life",
             "show": "🪑 Show"}
DUE_OPTS = {"Tonight": 0, "Tomorrow": 1, "In 2 days": 2, "In a week": 7}


def _draft_editor(state: dict, key: str) -> None:
    """Edit a quick task before it's added: name, time, type, when it's due."""
    d = st.session_state[f"{key}_draft"]
    k = f"{key}_e{d['v']}"
    due0 = parse_dt(d["due"])
    with st.container(border=True, key=f"{key}_editor"):
        title = st.text_input("Task", value=d["title"], key=f"{k}_t", max_chars=120)
        cur = next((c for c, v in TIME_CHIPS.items() if v == d["minutes"]), None)
        tchips = list(TIME_CHIPS) if cur else [f"{d['minutes']}m"] + list(TIME_CHIPS)
        tm = st.pills("Time", tchips, default=cur or tchips[0], key=f"{k}_m") or (cur or tchips[0])
        cat = st.pills("Type", list(SHORT_CAT), default=d["cat"], format_func=SHORT_CAT.get, key=f"{k}_c") or d["cat"]
        typed_due = due0.date() != now().date() or due0.time() != dtime(23, 59)
        dopts = ([f"As typed · {due0:%a %I:%M %p}".replace(" 0", " ")] if typed_due else []) + list(DUE_OPTS)
        dsel = st.pills("Due", dopts, default=dopts[0], key=f"{k}_d") or dopts[0]
        mins = TIME_CHIPS.get(tm) or int(tm.rstrip("m"))
        cat, mins = V.honest(title, cat, mins, chosen=True)
        due = due0 if dsel.startswith("As typed") else datetime.combine(
            now().date() + timedelta(days=DUE_OPTS[dsel]), dtime(23, 59), TZ)
        v = V.value(cat, mins)
        st.caption(f"{V.CATEGORIES[cat]['label']} · {min_label(mins)} → **+{v['reward']}** / −{v['penalty']}"
                   + (" · 🔧 pit checks cap at 15 min (inbox 10)" if cat == "pit" else ""))
        c1, c2 = st.columns([3, 1])
        if c1.button("✅ Add task", type="primary", use_container_width=True, key=f"{k}_ok",
                     disabled=not (title or "").strip()):
            at = parse_dt(d["at"]) if d.get("at") else None
            t = _add_quick(state, title.strip(), mins, due, cat, at=at)
            st.session_state.pop(f"{key}_draft", None)
            flash(f"⚡ Added **{t['title']}** · {min_label(t['minutes'])} → +{t['reward']} · due "
                  f"{due:%a %I:%M %p}".replace(" 0", " ") + (" · in today's mission" if t.get("mission_day") else ""))
            st.rerun()
        if c2.button("✕", use_container_width=True, key=f"{k}_x", help="Discard"):
            st.session_state.pop(f"{key}_draft", None)
            st.rerun()


def render_quick_add(state: dict, key: str = "qa", boxed: bool = True) -> None:
    with (st.container(border=True) if boxed else st.container()):
        with st.form(f"{key}_form", clear_on_submit=True, border=False):
            c1, c2 = st.columns([5, 1])
            text = c1.text_input("⚡ Quick add", label_visibility="collapsed",
                                 placeholder="⚡ Quick add — “email walter 15m by 3pm”, “gym at 6pm”, “read in 1h”")
            go = c2.form_submit_button("Add", type="primary", use_container_width=True)
        if go and text.strip():  # parse it, then let you check / change it before it's added
            p = Q.parse(text, now())
            st.session_state[f"{key}_draft"] = {"title": p["title"], "minutes": p["minutes"], "cat": p["category"],
                                                "due": p["due"].isoformat(), "at": p["at"].isoformat() if p["at"] else None,
                                                "v": st.session_state.get(f"{key}_draft", {}).get("v", 0) + 1}
        if st.session_state.get(f"{key}_draft"):
            _draft_editor(state, key)
        st.pills("Presets", [x[0] for x in Q.TEMPLATES], key=f"{key}_tpls", selection_mode="single",
                 label_visibility="collapsed", on_change=_tpl_pick, args=(key,))


def _mark_started(t: dict) -> None:
    """No schedule yet? Then the output board shows it when you actually started it."""
    if not t.get("scheduled") or parse_dt(t["scheduled"]).date() != now().date():
        t.update(scheduled=now().replace(second=0, microsecond=0).isoformat(), scheduled_time=True)


def _pomo_pick(state: dict, where=None) -> tuple[int | None, int | None]:
    """Break-at picker. Remembers your choice."""
    where = where or st
    cfg = state["settings"]
    keys = list(PM.PRESETS)
    cur = cfg.get("pomo", "off")
    mode = where.selectbox("Breaks", keys, index=keys.index(cur) if cur in keys else 0, label_visibility="collapsed",
                           format_func=lambda k: "☕ " + PM.PRESETS[k][0], key="pomo_mode")
    if mode == "custom":
        c2, c3 = st.columns(2)
        work = c2.number_input("Break at (min)", 10, 120, int(cfg.get("pomo_work", 45)), 5, key="pomo_w")
        brk = c3.number_input("Break (min)", 2, 30, int(cfg.get("pomo_brk", 10)), 1, key="pomo_b")
    else:
        work, brk = PM.PRESETS[mode][1] or (None, None)
    if (mode, work, brk) != (cur, cfg.get("pomo_work"), cfg.get("pomo_brk")) and \
            (mode != cur or mode == "custom"):
        cfg.update(pomo=mode, pomo_work=work, pomo_brk=brk)
        save_state(state)
    return (int(work), int(brk)) if work and brk else (None, None)


NEW_SESSION = "__new__"
TIMER_LENGTHS = [25, 30, 45, 50, 60, 90, 120]


def _timer_task(state: dict, name: str, planned: int, wall: int) -> dict:
    """A task made on the spot from the timer: due tonight (or an hour after the session, if that's later)."""
    eod = datetime.combine(now().date(), dtime(23, 59), TZ)
    dl = max(eod, now() + timedelta(minutes=wall + 60))
    t = make_task((name or "").strip() or "Focus session", "Started from the focus timer.", dl, None, "",
                  source="timer", minutes=planned)
    state["tasks"].append(t)
    return t


def render_timer(state: dict) -> None:
    tm = state.get("timer")
    open_t = sorted([t for t in state["tasks"] if t["status"] == "open"],
                    key=lambda t: (t.get("mission_day") != now().date().isoformat(), t["deadline"]))
    with st.container(border=True):
        if not tm:
            st.markdown("#### ⏱️ Focus timer")
            labels = {t["id"]: t["title"] for t in open_t}
            labels[NEW_SESSION] = "✏️ New task…"
            c1, c2 = st.columns([1.6, 1])
            tid = c1.selectbox("Working on", list(labels), format_func=labels.get, key="timer_task",
                               label_visibility="collapsed")
            planned = c2.selectbox("Minutes", TIMER_LENGTHS + [0], key="timer_len", label_visibility="collapsed",
                                   format_func=lambda m: f"{m} min" if m else "Custom…")
            if not planned:
                planned = int(c2.number_input("Custom minutes", 5, 240, int(state["settings"].get("timer_custom", 40)),
                                              5, key="timer_custom", label_visibility="collapsed"))
                if planned != state["settings"].get("timer_custom"):
                    state["settings"]["timer_custom"] = planned
            new_name = ""
            if tid == NEW_SESSION:
                new_name = st.text_input("What are you working on?", key="timer_new", max_chars=120,
                                         placeholder="e.g. Poster figures · blank = just a focus session",
                                         label_visibility="collapsed")
                st.caption("Becomes a task due tonight. Run the timer and it's your proof — finish it after.")
            c3, c4 = st.columns([1.6, 1])
            work, brk = _pomo_pick(state, c3)
            if c4.button("🎲 Pick for me", use_container_width=True, key="pick_next",
                         help="Picks your best next task and starts the timer"):
                pick = Q.pick_next(state["tasks"], now(), deep_hour=I.in_peak(PROFILE, now().hour))
                if pick:
                    plen = Q.session_length(pick)
                    state["timer"] = {"task_id": pick["id"], "start": now().isoformat(), "planned": plen,
                                      "work": work, "brk": brk}
                    _mark_started(pick)
                    save_state(state)
                    flash(f"🎲 **Do this now: {pick['title']}** — {plen}-min focus timer started. Nothing else exists.",
                          sound="win")
                    st.rerun()
            wall = PM.wall_minutes(planned, work, brk)
            if st.button(f"▶️ Start focus · {planned} min work" + (f" · done in {wall} min with breaks" if wall > planned else ""),
                         type="primary", use_container_width=True):
                if tid == NEW_SESSION:
                    tid = _timer_task(state, new_name, planned, PM.wall_minutes(planned, work, brk))["id"]
                state["timer"] = {"task_id": tid, "start": now().isoformat(), "planned": planned,
                                  "work": work, "brk": brk}
                _mark_started(next(x for x in state["tasks"] if x["id"] == tid))
                save_state(state)
                st.rerun()
            tok = state.get("tokens", {})
            claimed = state.get("challenge_claims", [])
            for ch in EV.focus_challenges(now().date(), TZ):
                if ch["id"] in claimed:
                    st.markdown(f"✅ ~~{ch['label']}~~")
                elif ch["start"] <= now() < ch["end"]:
                    st.markdown(f"🔥 **LIVE CHALLENGE:** {ch['label']} — {fmt_left(ch['end'] - now())} left to start")
            drops_left = EV.DROPS_PER_DAY - sum(1 for x in state.get("focus_log", [])
                                                 if x["date"] == now().date().isoformat() and x.get("drop"))
            st.caption(f"Today **{focus_today(state)} min** · timer-verified tasks pay +{int(V.TIMER_BONUS * 100)}% · "
                       f"25+ min sessions drop loot ({max(0, drops_left)} left) · surprise challenges buzz your phone"
                       + (f" Tokens: ⚡×{tok.get('double', 0)} 🔧×{tok.get('upgrade', 0)}"
                          if tok.get("double") or tok.get("upgrade") else ""))
            return
        t = next((x for x in state["tasks"] if x["id"] == tm["task_id"]), None)
        start = parse_dt(tm["start"])
        work, brk = tm.get("work"), tm.get("brk")
        now_ts = now().timestamp()
        if tm.get("paused_at") and PM.paused_for(tm, now_ts) > PM.PAUSE_LIMIT_MIN:
            mins = min(PM.work_done(PM.effective_elapsed(tm, now_ts), work, brk), tm["planned"] + 15)
            state.pop("timer", None)
            if mins >= 1 and t:
                _log_session(state, t, start, mins, tm)
            else:
                save_state(state)
            flash(f"⏸️ Paused for over {PM.PAUSE_LIMIT_MIN} min, so the session ended.", "warning")
            st.rerun()
        title = (t["title"] if t else "—")
        st.markdown(f"#### ⏱️ {html.escape(title[:42] + ('…' if len(title) > 42 else ''))}")
        _timer_ring(state, tm)
        _timer_controls(state)


@st.fragment(run_every=10)
def _timer_controls(state: dict) -> None:
    """Pause / skip break / stop. Refreshes itself so 'Skip break' shows up when a break starts."""
    tm = state.get("timer")
    if not tm:
        return
    t = next((x for x in state["tasks"] if x["id"] == tm["task_id"]), None)
    start = parse_dt(tm["start"])
    work, brk = tm.get("work"), tm.get("brk")
    now_ts = now().timestamp()
    eff = PM.effective_elapsed(tm, now_ts)
    ph, left = PM.phase(eff, work, brk, tm["planned"])
    paused = bool(tm.get("paused_at"))
    c1, c2 = st.columns(2)
    if paused:
        if c1.button("▶️ Resume", use_container_width=True, key="tm_resume", type="primary"):
            tm["paused_total"] = tm.get("paused_total", 0.0) + (now_ts - parse_dt(tm["paused_at"]).timestamp())
            tm["paused_at"] = None
            save_state(state)
            st.rerun()
    elif c1.button(f"⏸️ Pause · −{PM.pause_cost(tm)} 🪙", use_container_width=True, key="tm_pause",
                   help=f"Each pause costs a little more (2, 4, 6…). Paused time doesn't count, and a pause over "
                        f"{PM.PAUSE_LIMIT_MIN} min ends the session."):
        cost = PM.pause_cost(tm)
        tm["pauses"] = tm.get("pauses", 0) + 1
        tm["paused_at"] = now().isoformat()
        bank(state, -cost, f"⏸️ Pause #{tm['pauses']} during focus")
        save_state(state)
        st.rerun()
    in_break = ph == "break" and not paused
    if c2.button("☕ Skip break", use_container_width=True, key="tm_skip", disabled=not in_break,
                 help="Jump straight to the next work block." if in_break else "Shows up during a break."):
        tm["skipped"] = tm.get("skipped", 0.0) + left * 60
        save_state(state)
        st.rerun()
    wd_now = PM.work_done(eff, work, brk)
    near_end = tm["planned"] - wd_now <= FLOW_WINDOW
    if not paused and ph != "break" and near_end and tm.get("ext", 0) < FLOW_MAX_EXT:
        if st.button(f"🌊 In the zone? +{FLOW_STEP} min", use_container_width=True, key="tm_ext",
                     help=f"Keep going while it flows. Extra minutes pay a small flow bonus (+1 per {FLOW_COIN_PER} "
                          f"min) and the whole thing logs as one block, so a 50 + 15 counts as your 1-hour block."):
            tm["planned"] += FLOW_STEP
            tm["ext"] = tm.get("ext", 0) + FLOW_STEP
            if ph == "done":  # finished already: the extension starts from now, not from the old finish line
                tm["skipped"] = tm.get("skipped", 0.0) - max(0.0, (eff - PM.wall_minutes(
                    tm["planned"] - FLOW_STEP, work, brk)) * 60)
            save_state(state)
            st.toast(f"Flow mode: +{FLOW_STEP} min. Ride it.", icon="🌊")
            st.rerun()
    c3, c4 = st.columns([3, 1])
    if c3.button("⏹️ Stop & log", type="secondary" if paused else "primary", use_container_width=True, key="tm_stop"):
        mins = min(PM.work_done(eff, work, brk), tm["planned"] + 15)
        state.pop("timer", None)
        if mins >= 1 and t:
            _log_session(state, t, start, mins, tm)
        else:
            save_state(state)
        st.rerun()
    if c4.button("✖", use_container_width=True, key="tm_cancel", help="Cancel without logging"):
        state.pop("timer", None)
        save_state(state)
        st.rerun()


def track_for(tm: dict) -> dict:
    """A real circuit for this session: same session → same track (stable across refreshes)."""
    return TR.TRACKS[int(hashlib.md5(tm["start"].encode()).hexdigest(), 16) % len(TR.TRACKS)]


def _timer_ring(state: dict, tm: dict) -> None:
    """Your car lapping a real circuit, clock underneath. Pure client-side clock; only our own data goes in."""
    work, brk, T = tm.get("work") or 0, tm.get("brk") or 0, tm["planned"]
    start_ms = int(parse_dt(tm["start"]).timestamp() * 1000)
    pt = int(tm.get("paused_total", 0.0) * 1000)
    sk = int(tm.get("skipped", 0.0) * 1000)
    pa = int(parse_dt(tm["paused_at"]).timestamp() * 1000) if tm.get("paused_at") else 0
    wall = PM.wall_minutes(T, work or None, brk or None)
    acc = accent(state)[0]
    limit = PM.PAUSE_LIMIT_MIN
    _embed = st.iframe if hasattr(st, "iframe") else __import__("streamlit.components.v1", fromlist=["html"]).html
    blocks = math.ceil(T / work) if work and brk else 1
    ticks = "".join(f"{k * work / T:.4f}," for k in range(1, blocks)) if blocks > 1 else ""
    trk = track_for(tm)
    car = state["car"]
    mid = car.get("model", "civic_si")
    sprite = carart.car_topdown(CAR_BY_ID.get(mid, CAR_BY_ID["civic_si"])["body"], car["color"], car["number"],
                                G.effective(car["parts"], mid))
    ext = int(tm.get("ext", 0))
    label = html.escape(f"{trk['name'].upper()} · {trk['km']:.3f} KM · {trk['series']}")
    _embed(f"""
<link href="https://fonts.googleapis.com/css2?family=Saira+Semi+Condensed:wght@700&display=swap" rel="stylesheet">
<style>
body{{margin:0;font-family:system-ui,sans-serif;color:#ece8df;overflow:hidden}}
.w{{display:flex;flex-direction:column;align-items:center}}
svg{{width:100%;max-width:340px;height:auto;display:block}}
#t{{font:700 27px 'Saira Semi Condensed',system-ui,sans-serif;font-variant-numeric:tabular-nums}}
.w{{position:relative;overflow:hidden}}
#flag{{position:absolute;top:14%;left:-110px;width:96px;height:118px;pointer-events:none;opacity:0;z-index:5}}
#flag i{{position:absolute;left:0;top:0;width:3px;height:118px;border-radius:2px;background:linear-gradient(#e7e9ee,#8b909c)}}
#flag b{{position:absolute;left:3px;top:2px;width:88px;height:58px;transform-origin:left center;border-radius:0 3px 3px 0;
  background:conic-gradient(#f2efe8 25%,#111318 0 50%,#f2efe8 0 75%,#111318 0) 0 0/14.6px 14.6px;
  box-shadow:0 6px 18px rgba(0,0,0,.45);animation:wave .32s ease-in-out infinite alternate}}
.fin #flag{{animation:sweep 2.6s cubic-bezier(.45,.05,.35,1) .15s forwards}}
@keyframes sweep{{0%{{left:-110px;opacity:1}}88%{{opacity:1}}100%{{left:calc(100% + 20px);opacity:0}}}}
@keyframes wave{{from{{transform:perspective(160px) rotateY(-14deg) skewY(-5deg)}}to{{transform:perspective(160px) rotateY(12deg) skewY(5deg)}}}}
.fin #t{{animation:pulse 1.2s ease-in-out 3}}
@keyframes pulse{{50%{{opacity:.45}}}}
#p{{font-size:10.5px;fill:#8b909c;letter-spacing:.06em;text-transform:uppercase}}
#s{{font-size:12.5px;color:#8b909c;margin-top:1px;text-align:center;min-height:16px}}
#halo{{opacity:0}} .blink #halo{{animation:hz 1s steps(2,end) infinite}}
@keyframes hz{{0%{{opacity:.9}}50%{{opacity:0}}}}
#crew{{opacity:0}} .pit #crew{{opacity:1;animation:gun .35s linear infinite}}
@keyframes gun{{50%{{opacity:.25}}}}
@media (prefers-reduced-motion:reduce){{.blink #halo,.pit #crew,#flag b,.fin #t{{animation:none}}
  .fin #flag{{animation:none;opacity:1;left:auto;right:6px;transform:scale(.4);transform-origin:top right}}}}
</style>
<div class="w" id="w">
<svg viewBox="0 0 300 172" aria-label="Focus session progress">
 <text x="4" y="9" font-size="7" fill="#5b6070" letter-spacing=".07em">{label}</text>
 <path id="track" d="{trk['d']}" fill="none" stroke="#262b36" stroke-width="9" stroke-linejoin="round"/>
 <path d="{trk['d']}" fill="none" stroke="#3a4050" stroke-width=".7" stroke-dasharray="3 4"/>
 <path id="trail" d="{trk['d']}" fill="none" stroke="{acc}" stroke-width="2.6" stroke-linecap="round"
   stroke-linejoin="round" stroke-dasharray="0 99999" opacity=".95"/>
 <g id="ticks"></g>
 <g id="sf"></g>
 <g id="crew"><circle id="c1" r="1.4" fill="#2ec4b6"/><circle id="c2" r="1.4" fill="#2ec4b6"/></g>
 <text id="pitl" font-size="6" font-weight="700" fill="#2ec4b6" text-anchor="middle" opacity="0">PIT</text>
 <text id="t" x="146" y="164" text-anchor="end"></text>
 <text id="p" x="154" y="160" text-anchor="start"></text>
 <g id="car"><circle id="halo" r="10" fill="#f5c518"/>{sprite}</g>
</svg><div id="flag"><i></i><b></b></div><div id="s"></div></div>
<script>
// sounds mix with your music instead of pausing it (iOS 17+ audio session; harmless elsewhere)
try{{if(navigator.audioSession)navigator.audioSession.type='ambient';
 if(parent.navigator.audioSession)parent.navigator.audioSession.type='ambient';}}catch(e){{}}
const S={start_ms},PT={pt},SK={sk},PA={pa},W={work},B={brk},T={T},WALL={wall},LIM={limit},ACC='{acc}';
const TICKS=[{ticks}],EXT={ext};
function finish(){{  // whole-page "you're done" you can catch from across the room: once per session
 let P;try{{P=parent.document;}}catch(e){{return;}}
 const key='dodfin:'+S;try{{if(parent.sessionStorage.getItem(key))return;parent.sessionStorage.setItem(key,'1');}}catch(e){{}}
 if(P.getElementById('dod-fin'))return;
 const st=P.createElement('style');st.id='dod-fin-css';st.textContent=`
#dod-fin{{position:fixed;inset:0;z-index:999999;pointer-events:none;overflow:hidden}}
#dod-fin .fr{{position:absolute;inset:0;padding:14px;box-sizing:border-box;
  background:repeating-conic-gradient(#f2efe8 0 25%,#111318 0 50%) 0 0/14px 14px;
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;
  mask:linear-gradient(#000 0 0) content-box exclude,linear-gradient(#000 0 0);
  animation:dfp .55s ease-in-out 0s 12 alternate}}
#dod-fin .gl{{position:absolute;inset:0;background:radial-gradient(ellipse at center,transparent 45%,${{'{acc}'}}55 100%);animation:dfp .55s ease-in-out 0s 12 alternate}}
#dod-fin .fl{{position:absolute;top:22%;left:-40vw;width:min(70vw,520px);height:min(44vw,330px);transform-origin:left center;
  background:repeating-conic-gradient(#f2efe8 0 25%,#111318 0 50%) 0 0/ 12% 18%;border-left:8px solid #c9ccd2;
  box-shadow:0 20px 50px rgba(0,0,0,.5);animation:dfs 3.2s cubic-bezier(.45,.05,.35,1) .2s forwards,dfw .3s ease-in-out infinite alternate}}
@keyframes dfp{{from{{opacity:.15}}to{{opacity:1}}}}
@keyframes dfs{{0%{{left:-75vw}}100%{{left:110vw}}}}
@keyframes dfw{{from{{transform:perspective(600px) rotateY(-12deg) skewY(-4deg)}}to{{transform:perspective(600px) rotateY(10deg) skewY(4deg)}}}}
@media (prefers-reduced-motion:reduce){{#dod-fin .fl{{display:none}}#dod-fin .fr,#dod-fin .gl{{animation:none}}}}`;
 P.head.appendChild(st);
 const o=P.createElement('div');o.id='dod-fin';o.innerHTML='<div class="gl"></div><div class="fr"></div><div class="fl"></div>';
 P.body.appendChild(o);setTimeout(()=>{{o.remove();st.remove();}},7800);
 // tab title blinks until you come back to it
 const t0=P.title;let on=true;const iv=setInterval(()=>{{P.title=on?'🏁 SESSION DONE':t0;on=!on;}},900);
 const stop=()=>{{clearInterval(iv);P.title=t0;}};
 parent.addEventListener('focus',stop,{{once:true}});P.addEventListener('pointerdown',stop,{{once:true}});
 setTimeout(stop,10*60*1000);
 try{{if(parent.navigator.vibrate)parent.navigator.vibrate([400,150,400,150,800]);}}catch(e){{}}}}
const tr=document.getElementById('track'),L=tr.getTotalLength(),car=document.getElementById('car');
const trail=document.getElementById('trail'),w=document.getElementById('w'),NS='http://www.w3.org/2000/svg';
function at(f){{const d=L*Math.min(.9999,Math.max(0,f)),a=tr.getPointAtLength(d),b=tr.getPointAtLength(Math.min(L,d+1));
 return [a,Math.atan2(b.y-a.y,b.x-a.x)];}}
// centre of the track (to know which side is "inside"), start/finish line, pit spot
let cx=0,cy=0;for(let i=0;i<60;i++){{const p=tr.getPointAtLength(L*i/60);cx+=p.x/60;cy+=p.y/60;}}
const [p0,a0]=at(0);let nx=-Math.sin(a0),ny=Math.cos(a0);if((cx-p0.x)*nx+(cy-p0.y)*ny<0){{nx=-nx;ny=-ny;}}
const sf=document.getElementById('sf');
for(let k=-2;k<2;k++)for(let j=0;j<2;j++){{const r=document.createElementNS(NS,'rect');
 r.setAttribute('x',-1+j*1.2);r.setAttribute('y',k*1.2);r.setAttribute('width',1.2);r.setAttribute('height',1.2);
 r.setAttribute('fill',(k+j)%2?'#ece8df':'#14161c');sf.appendChild(r);}}
sf.setAttribute('transform','translate('+p0.x+','+p0.y+') rotate('+(a0*180/Math.PI)+')');
const PX=p0.x+nx*11,PY=p0.y+ny*11;
document.getElementById('c1').setAttribute('cx',PX-ny*8);document.getElementById('c1').setAttribute('cy',PY+nx*8);
document.getElementById('c2').setAttribute('cx',PX+ny*8);document.getElementById('c2').setAttribute('cy',PY-nx*8);
const pl=document.getElementById('pitl');pl.setAttribute('x',PX+nx*8);pl.setAttribute('y',PY+ny*8+2);
TICKS.forEach(f=>{{const [a,ang]=at(f),dx=-Math.sin(ang)*5,dy=Math.cos(ang)*5,l=document.createElementNS(NS,'line');
 l.setAttribute('x1',a.x-dx);l.setAttribute('y1',a.y-dy);l.setAttribute('x2',a.x+dx);l.setAttribute('y2',a.y+dy);
 l.setAttribute('stroke','#2ec4b6');l.setAttribute('stroke-width','1.2');l.setAttribute('opacity','.8');
 document.getElementById('ticks').appendChild(l);}});
let last=null,ac=null,shown=-1;
function beep(n){{try{{ac=ac||new (window.AudioContext||window.webkitAudioContext)();
 for(let i=0;i<n;i++){{const o=ac.createOscillator(),g=ac.createGain();o.frequency.value=n>1?660:880;
 o.connect(g);g.connect(ac.destination);g.gain.value=.15;o.start(ac.currentTime+i*.25);o.stop(ac.currentTime+i*.25+.18);}}}}catch(e){{}}}}
function mmss(ms){{const a=Math.floor(Math.abs(ms)/1000);return String(Math.floor(a/60)).padStart(2,'0')+':'+String(a%60).padStart(2,'0');}}
function eff(now){{return Math.max(0,(now-S-PT-(PA?now-PA:0)+SK)/60000);}}
function wdone(e){{if(!W||!B)return e;const c=W+B;return Math.floor(e/c)*W+Math.min(e%c,W);}}
function place(f,pit){{
 if(pit){{car.setAttribute('transform','translate('+PX+','+PY+') rotate('+(a0*180/Math.PI)+') scale(.85)');return;}}
 const [a,ang]=at(f);car.setAttribute('transform','translate('+a.x+','+a.y+') rotate('+(ang*180/Math.PI)+') scale(.85)');}}
function frame(){{
 const now=Date.now(),e=eff(now),wd=Math.min(wdone(e),T),f=wd/T;
 let ph='work',left=(T-e)*60000;
 if(wd>=T)ph='done';
 else if(W&&B){{const c=W+B,r=e%c;if(r<W)left=Math.min(W-r,T-wd)*60000;else{{ph='break';left=(c-r)*60000;}}}}
 const pit=ph==='break'&&!PA;
 place(ph==='done'?0:f,pit);
 trail.setAttribute('stroke-dasharray',(L*Math.min(1,f))+' 99999');
 w.className='w'+(PA?' blink':'')+(pit?' pit':'')+(ph==='done'&&!PA?' fin':'');
 pl.setAttribute('opacity',pit?1:0);
 const sec=Math.floor(now/1000);
 if(sec!==shown){{shown=sec;
  const t=document.getElementById('t'),p=document.getElementById('p'),s=document.getElementById('s');
  const blk=W&&B?Math.min(TICKS.length+1,Math.floor(e/(W+B))+1):1,stints=TICKS.length+1;
  if(PA){{t.textContent=mmss(left);t.style.fill='#8b909c';trail.style.stroke='#5b6070';
    p.textContent='🟡 Yellow flag';s.textContent='Paused '+mmss(now-PA)+' · retires the car at '+LIM+':00';}}
  else if(ph==='done'){{t.textContent='+'+mmss((e-WALL)*60000);t.style.fill='#ff6a5c';trail.style.stroke=ACC;
    p.textContent='🏁 Chequered flag';s.textContent='Session complete. Stop & log it.';}}
  else if(pit){{t.textContent=mmss(left);t.style.fill='#2ec4b6';trail.style.stroke=ACC;
    p.textContent='🔧 Pit stop';s.textContent='Tyres, water, stretch. No phone in the pit lane.';}}
  else{{t.textContent=mmss(left);t.style.fill=ACC;trail.style.stroke=ACC;
    p.textContent=EXT>0?('🌊 Flow · +'+EXT+' min'):stints>1?('Stint '+blk+' of '+stints):'Green flag';
    s.textContent=Math.round(wd)+' of '+T+' min · phone face-down';}}
  const key=PA?'pause':ph;if(last&&last!==key&&!PA)beep(ph==='work'?2:ph==='break'?1:3);last=key;
  if(ph==='done'&&!PA)finish();}}
 requestAnimationFrame(frame);}}
frame();
</script>""", height=232)  # our own static markup only — no user content goes in here


FLOW_STEP = 15          # minutes per "keep going"
FLOW_MAX_EXT = 60       # at most an extra hour per session
FLOW_WINDOW = 10        # the button shows in the last 10 min of work, or once the session is done
FLOW_COIN_PER = 3       # +1 coin per 3 flow minutes actually worked (15 min → +5)
FLOW_BONUS_CAP = 20


def flow_bonus(tm: dict, mins: float) -> tuple[int, float]:
    """(coins, flow minutes): minutes worked past the ORIGINAL plan, only when you chose to extend."""
    ext = tm.get("ext", 0)
    if not ext:
        return 0, 0.0
    flow = max(0.0, min(mins, tm["planned"]) - (tm["planned"] - ext))
    return min(FLOW_BONUS_CAP, int(flow // FLOW_COIN_PER)), flow


def _log_session(state: dict, t: dict, start: datetime, mins: float, tm: dict) -> None:
    """Credit a finished/stopped focus session: focus minutes, XP, loot drop, focus challenge."""
    full = mins >= tm["planned"]
    t["focus_min"] = round(t.get("focus_min", 0) + mins, 1)
    state.setdefault("focus_log", []).append({"date": start.date().isoformat(), "task": t["id"],
                                              "min": round(mins, 1), "full": full,
                                              "start": start.isoformat(), "cat": t.get("category")})
    del state["focus_log"][:-500]
    state["xp"] += int(mins // 5)
    drop_msg, snd = "", ("win" if full else None)
    today_log = [x for x in state["focus_log"] if x["date"] == now().date().isoformat()]
    if full and mins >= 25 and sum(1 for x in today_log if x.get("drop")) < EV.DROPS_PER_DAY:
        kind = EV.roll_drop()
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
        snd = "jackpot" if kind in ("double_token", "upgrade_token") else "win"
    done_ch = state.setdefault("challenge_claims", [])
    for ch in EV.focus_challenges(now().date(), TZ):
        if ch["id"] not in done_ch and ch["start"] <= start < ch["end"] and mins >= ch["minutes"]:
            done_ch.append(ch["id"])
            t["double"] = True
            state["xp"] += int(mins // 5)  # the session's own XP counts twice
            extra = ("\n\n" + open_crate(state, {"reward": 45})) if ch["kind"] == "double_crate" else ""
            drop_msg = (f"🏆 **FOCUS CHALLENGE WON** — this session counts ⚡ double: *{t['title']}* now "
                        f"pays **2× coins & XP** when you finish it, and you got +{int(mins // 5)} bonus XP."
                        + extra + ("\n\n" + drop_msg if drop_msg else ""))
            snd = "jackpot"
    save_state(state)
    fm_, need_ = timer_proof(t)
    if fm_ >= need_ and t.get("status") == "open":
        drop_msg = (drop_msg + "\n\n" if drop_msg else "") + (
            f"✅ {fm_:.0f} min logged on *{t['title']}* — that counts as proof. Open it and submit to collect.")
    fb, fmin = flow_bonus(tm, mins)
    if fb:
        bank(state, fb, f"🌊 Flow bonus ({int(fmin)} extra min)")
        state["focus_log"][-1]["flow"] = round(fmin, 1)
        save_state(state)
        drop_msg = (drop_msg + "\n\n" if drop_msg else "") + f"🌊 **Flow bonus +{fb}** for {int(fmin)} extra minutes."
    flash(f"⏱️ Logged **{int(mins)} min** on *{t['title']}*" + (" — full session! 🔥" if full else "")
          + f" +{int(mins // 5)} XP. Today: {focus_today(state)} min." + (f"\n\n{drop_msg}" if drop_msg else ""),
          sound=snd, celebrate=bool(drop_msg))


def render_race_status(state: dict) -> None:
    """Right-rail status: flag, rivals, penalty box, contracts, ledger, rules — compact."""
    reasons = black_flag_reasons(state)
    left = max(0, PITY_AFTER - state["since_rare"])
    with st.container(border=True):
        flag = ("<span style='color:#ff6a5c'>⬛ <b>Black flag</b> — " + html.escape("; ".join(reasons)) + "</span>"
                if reasons else "<span style='color:#2ec4b6'>🟢 <b>Green flag</b> — clear to race</span>")
        st.markdown(f"{flag}<div class='dod-row' style='border:0;padding:8px 0 0'><div class='m'>"
                    f"🔥 Rival heat <b style='color:#ece8df'>{state['rival_heat']}</b> &nbsp; "
                    f"🛡️ Shields <b style='color:#ece8df'>{state['shields']}</b> &nbsp; "
                    f"📦 Rare drop <b style='color:#ece8df'>{'NEXT' if not left else f'≤{left}'}</b></div></div>",
                    unsafe_allow_html=True)
        unserved = [p for p in state["penalty_box"] if not p["served"]]
        for p in unserved:
            st.markdown(f"🚨 **{p['consequence']}**  \n<small>for missing *{html.escape(p['task'])}*</small>",
                        unsafe_allow_html=True)
            if p.get("enforced"):
                st.caption(f"🔒 Enforced on PC + phone. Lifts when you redeem *{p['task']}* or after {LK.LOCK_HOURS}h.")
            elif st.checkbox("I actually served this", key=f"served_chk_{p['id']}") and \
                    st.button("Release me", key=f"served_{p['id']}"):
                p["served"], p["served_at"] = True, now().isoformat()
                save_state(state)
                flash("Penalty served. Back on track.")
                st.rerun()
    render_contracts(state)
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


def render_task_board(state: dict, open_tasks: list[dict]) -> None:
    """Add + every open task in one place, right under the mission."""
    today = now().date().isoformat()
    stt = daily.status(state, now())
    in_mission = {t["id"] for t in stt["mission"]} if stt["qualified"] else set()
    rest = [t for t in open_tasks if t["id"] not in in_mission]
    with st.container(border=True):
        st.markdown(f"#### Tasks · {len(open_tasks)} open")
        render_quick_add(state, "qa_top", boxed=False)
        if rest and (parse_dt(rest[0]["deadline"]) - now()) < timedelta(hours=6):
            st.warning(f"⏱️ **{rest[0]['title']}** dies in {fmt_left(parse_dt(rest[0]['deadline']) - now())} — "
                       f"−{rest[0]['penalty']} and {MISS_DAMAGE}% of your car. Start for 10 minutes.")
        if in_mission and rest:
            st.caption("Also on your plate")
        for t in rest:
            render_task_row(state, t, "tb_")
        if not open_tasks:
            st.caption("Nothing open. Type one above, or tap a one-tap task.")
        redeemable = [t for t in state["tasks"] if t["status"] == "failed" and not t.get("abandoned")
                      and now() - parse_dt(t["failed_at"]) < timedelta(hours=REDEEM_WINDOW_H)]
        for t in redeemable:
            left = parse_dt(t["failed_at"]) + timedelta(hours=REDEEM_WINDOW_H) - now()
            with st.expander(f"🩹 {t['title']} · {fmt_left(left)} to redeem for half back"):
                render_proof_form(state, t, "redeem", scope="tb_")


def render_contracts(state: dict) -> None:
    n_ = now()
    claimed = state.setdefault("contracts_claimed", [])
    with st.container(border=True):
        st.markdown("#### 📜 This week's contracts")
        for c in K.this_week(n_):
            p, key = K.progress(state, c, n_), K.claim_key(c, n_)
            unit = " min" if c.get("unit") == "min" else ""
            st.progress(min(1.0, p / c["goal"]),
                        text=f"{c['title']} · +{c['reward']} 🪙 · {min(p, c['goal'])}{unit}/{c['goal']}{unit}"
                        + (" ✅" if key in claimed else ""))
            if key not in claimed and p >= c["goal"] and st.button(f"Claim +{c['reward']} 🪙", key=f"claim_{c['id']}",
                                                                   type="primary"):
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
    reason = L.closed_reason(state, now().date(), black_flag_reasons(state))
    ticket = L.entry_ticket(state, now().date())
    if ticket and not reason:
        st.caption(ticket)
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



# ─────────────────────────── look & feel ───────────────────────────
# Fonts + colours live in .streamlit/config.toml (Barlow / Saira Semi Condensed, asphalt + Phoenix Yellow).
# This only adds what the theme can't: the instrument cluster, the live-card rail, dark text on yellow buttons.
CSS = """<style>
:root{--y:#f5c518;--r:#e10600;--t:#2ec4b6;--panel:#1b1f27;--line:#2c313c;--muted:#8b909c}
.block-container{max-width:1280px;padding-top:2.6rem}
.st-key-rail [data-testid="stVerticalBlockBorderWrapper"],.st-key-rail>div{gap:.9rem}
[data-testid="stBaseButton-primary"] *,[data-testid="stBaseButton-primaryFormSubmit"] *{color:#14171d!important;font-weight:700}
.st-key-live_card{border-left:4px solid var(--y)!important}
[data-testid="stMultiSelectTagsContainer"] [data-tag],[data-baseweb="tag"]{background:#2a2f3a!important;
  border:1px solid #3a404d!important}
[data-testid="stMultiSelectTagsContainer"] [data-tag] *,[data-baseweb="tag"] *{color:#ece8df!important}
[data-testid="stMultiSelectTagsContainer"] [data-tag] svg{fill:#8b909c!important;color:#8b909c!important}
[data-baseweb="tab-list"]{gap:4px;border-bottom:1px solid var(--line)}
[data-baseweb="tab"] p{font-family:"Saira Semi Condensed",sans-serif;font-weight:600;font-size:1rem}
[data-testid="stMetricValue"]{font-family:"Saira Semi Condensed",sans-serif;font-variant-numeric:tabular-nums}
.dod-hero h1{font-family:"Saira Semi Condensed",sans-serif;font-weight:800;font-style:italic;font-size:2.2rem;
  line-height:1;margin:0;padding:0;letter-spacing:-.01em}
.dod-hero{display:flex;align-items:baseline;gap:18px;flex-wrap:wrap;margin-bottom:.7rem}
.dod-hero p{color:var(--muted);margin:0;font-size:.95rem}
.dod-cluster{display:grid;grid-template-columns:repeat(4,1fr);background:#101319;border:1px solid var(--line);
  border-radius:14px;overflow:hidden;margin:0 0 1.1rem}
.dod-cell{padding:8px 16px 6px;border-left:1px solid var(--line)}
.dod-cell:first-child{border-left:0}
.dod-k{color:var(--muted);font-size:.82rem}
.dod-v{font-family:"Saira Semi Condensed",sans-serif;font-weight:700;font-size:1.75rem;line-height:1.05;color:var(--y);
  font-variant-numeric:tabular-nums}
.dod-v.bad{color:var(--r)}
.dod-s{font-size:.78rem;color:var(--muted)}
.dod-xp{grid-column:1/-1;border-top:1px solid var(--line);padding:6px 16px;display:flex;align-items:center;gap:12px;
  font-size:.84rem;color:var(--muted)}
.dod-xp b{color:#ece8df;font-weight:600}
.dod-bar{flex:1;height:4px;background:#262b36;border-radius:2px;overflow:hidden}
.dod-bar i{display:block;height:100%;background:var(--y)}
.dod-rows{margin:.2rem 0 .6rem}
.dod-row{display:flex;gap:10px;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line)}
.dod-row:last-child{border-bottom:0}
.dod-dot{width:8px;height:8px;border-radius:50%;flex:none}
.dod-row .m{color:var(--muted);font-size:.9rem}
/* don't grey the page out while Streamlit reruns — it makes every click feel slow */
[data-stale="true"],.stale-element{opacity:1!important;transition:none!important}
[data-testid="stStatusWidget"]{opacity:.55}
/* motion: one entrance, feedback on change and on press, nothing that loops */
@keyframes dodIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes dodPop{0%{transform:scale(1)}35%{transform:scale(1.12);text-shadow:0 0 18px var(--y)}100%{transform:scale(1)}}
@keyframes dodGrow{from{width:var(--from)}}
.dod-cluster.intro .dod-cell{animation:dodIn .5s cubic-bezier(.2,.7,.2,1) both}
.dod-cell:nth-child(2){animation-delay:.05s}.dod-cell:nth-child(3){animation-delay:.1s}.dod-cell:nth-child(4){animation-delay:.15s}
.dod-v{display:inline-block;transform-origin:left center}
.dod-v.chg{animation:dodPop .7s cubic-bezier(.2,.7,.2,1) .25s both}
.dod-bar i{animation:dodGrow .9s cubic-bezier(.2,.7,.2,1) both}
[data-testid^="stBaseButton"]{transition:transform .08s ease,filter .15s ease,background-color .2s ease}
[data-testid^="stBaseButton"]:hover{filter:brightness(1.08)}
[data-testid^="stBaseButton"]:active{transform:scale(.97)}
[data-testid="stExpanderDetails"]{animation:dodIn .28s ease-out both}
[data-stale="true"]{opacity:1!important;transition:none!important}
[data-testid="InputInstructions"]{display:none}
.dod-shield span.hot{border-color:var(--y);color:#ece8df;background:rgba(245,197,24,.08)}
.st-key-audio_session{position:absolute!important;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none}
.dod-ci{margin:-.2rem 0 .1rem}.dod-ci .m{color:var(--muted);font-size:.85rem;margin-left:4px}
.st-key-checkin [data-testid="stButtonGroup"] button,.st-key-closeday [data-testid="stButtonGroup"] button,
[class*="st-key-jf_"] [data-testid="stButtonGroup"] button{font-size:1.15rem;min-width:2.6rem}
/* working… : a slim racing-stripe bar while the app thinks (only shows if it takes > ~0.2 s) */
[data-testid="stApp"][data-test-script-state="running"]::before{content:"";position:fixed;top:0;left:0;right:0;height:3px;
  z-index:1000100;background:linear-gradient(90deg,transparent,var(--y),transparent);background-size:40% 100%;
  background-repeat:no-repeat;animation:dodRun 1s linear infinite,dodFadeIn .2s ease .2s both}
@keyframes dodRun{from{background-position:-40% 0}to{background-position:140% 0}}
@keyframes dodFadeIn{from{opacity:0}to{opacity:1}}
/* first-load splash */
.dod-boot{min-height:60vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px}
.dod-boot-car{font-size:3rem;animation:dodBob .9s ease-in-out infinite alternate}
.dod-boot-t{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:700;font-size:1.2rem;color:#ece8df}
.dod-boot-bar{width:180px;height:4px;border-radius:4px;background:#262b36;overflow:hidden}
.dod-boot-bar i{display:block;width:40%;height:100%;background:var(--y);border-radius:4px;animation:dodSlide 1.1s ease-in-out infinite}
@keyframes dodBob{from{transform:translateY(0)}to{transform:translateY(-6px)}}
@keyframes dodSlide{0%{transform:translateX(-100%)}100%{transform:translateX(260%)}}
/* dailies rows: name · ↩ · +1 on one line on phones */
[class*="st-key-dlrow_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.4rem}
[class*="st-key-dlrow_"] [data-testid="stColumn"]{min-width:0!important}
[class*="st-key-dlrow_"] [data-testid="stColumn"]:nth-child(2){flex:0 0 2.6rem!important;width:2.6rem!important}
[class*="st-key-dlrow_"] [data-testid="stColumn"]:nth-child(3){flex:0 0 5.2rem!important;width:5.2rem!important}
/* stats numbers: 2 × 2 on phones */
@media (max-width:640px){.st-key-stat_kpis [data-testid="stHorizontalBlock"]{flex-wrap:wrap!important;gap:.5rem 1rem}
  .st-key-stat_kpis [data-testid="stColumn"]{flex:1 1 calc(50% - 1rem)!important;min-width:calc(50% - 1rem)!important}}
/* toasts in the app's colours */
[data-testid="stToast"]{background:#1b1f27!important;border:1px solid var(--line);border-left:3px solid var(--y);
  color:#ece8df;box-shadow:0 8px 24px rgba(0,0,0,.45)}
[class*="st-key-scrap_"] img{max-height:210px;object-fit:cover;width:100%;border-radius:10px}
.dod-scrap-tile{height:96px;border-radius:10px;background:linear-gradient(135deg,#1b1f27,#141821);display:flex;
  align-items:center;justify-content:center;font-size:2.4rem;margin-bottom:.4rem;border:1px solid var(--line)}
.dod-mh{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:.1rem 0 .5rem}
.dod-mt{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:700;font-size:1.55rem;line-height:1.1}
.dod-mb{color:var(--muted);font-size:.9rem;white-space:nowrap}
.dod-seg{display:flex;gap:5px;margin:0 0 .7rem}
.dod-seg i{flex:1;height:7px;border-radius:4px;background:#262b36;transition:background .4s}
.dod-seg i.ok{background:var(--y)} .dod-seg i.bad{background:var(--r)}
.dod-pills{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 .8rem}
.dod-pills span{font-size:.8rem;color:var(--muted);background:#141821;border:1px solid var(--line);border-radius:999px;
  padding:3px 10px}
.dod-pills b{color:#ece8df;font-weight:600}
.dod-mrow{display:flex;gap:10px;align-items:center;padding:9px 14px;margin:0 0 .5rem;border:1px solid var(--line);
  border-radius:12px;background:#141821}
.dod-mrow .m{color:var(--muted);font-size:.85rem;margin-left:6px}
.dod-mrow.ok .dod-dot{background:var(--t)} .dod-mrow.ok s{color:var(--muted)}
.dod-mrow.bad .dod-dot{background:var(--r)} .dod-mrow.bad{border-color:#4a1f22}
[class*="st-key-mrow_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.5rem}
[class*="st-key-mrow_"] [data-testid="stColumn"]{min-width:0!important}
[class*="st-key-mrow_"] [data-testid="stColumn"]:last-child{flex:0 0 3.2rem!important;width:3.2rem!important}
[class*="st-key-qrow_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.4rem}
[class*="st-key-qrow_"] [data-testid="stColumn"]{min-width:0!important}
[class*="st-key-qrow_"] [data-testid="stColumn"]:first-child p{margin:0;overflow:hidden;text-overflow:ellipsis}
[class*="st-key-qrow_"] [data-testid="stColumn"]:last-child{flex:0 0 2.6rem!important;width:2.6rem!important}
[class*="st-key-qrow_"] [data-testid="stColumn"]:nth-child(2){flex:0 0 8.4rem!important;width:8.4rem!important}
[class*="st-key-mgo_"] button{color:var(--y);border-color:var(--y)!important;font-size:1.05rem}
[class*="st-key-mgo_"] button:disabled{color:var(--muted);border-color:var(--line)!important}
@media (max-width:640px){.dod-mt{font-size:1.2rem}.dod-mb{font-size:.8rem}}
[class*="st-key-dlh_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.5rem}
[class*="st-key-dlh_"] [data-testid="stColumn"]{min-width:0!important}
[class*="st-key-dlh_"] [data-testid="stColumn"]:last-child{flex:0 0 3.2rem!important;width:3.2rem!important}
[data-baseweb="tab-panel"]{animation:dodIn .3s ease-out both}
[data-testid="stProgressBarTrack"] div{transition:width .6s cubic-bezier(.2,.7,.2,1)}
[data-baseweb="tab-highlight"]{transition:all .25s ease}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
@media (max-width:640px){
  .dod-cluster{grid-template-columns:repeat(2,1fr)}
  .dod-cell:nth-child(3){border-left:0}
  .dod-cell:nth-child(n+3){border-top:1px solid var(--line)}
  .dod-hero h1{font-size:2.2rem}
}
</style>"""



# ── 🎨 Paint shop: UI themes you unlock in the Garage (Honda colours) ──
THEMES = {  # key: (name, accent, text-on-accent, cost, level, blurb)
    "phoenix": ("Phoenix Yellow", "#f5c518", "#14171d", 0, 1, "The yellow the DC2 Integra Type R made famous."),
    "apex": ("Apex Blue", "#6a8dff", "#0d1020", 300, 2, "Apex Blue Pearl: an S2000 colour."),
    "mugen": ("Mugen Gold", "#d9a441", "#14171d", 500, 3, "Gold wheels on a white Civic: the tuner look."),
    "nsx": ("NSX Orange", "#ff7a1a", "#14171d", 700, 3, "A loud orange pearl off the NSX colour chart."),
    "ctr": ("Championship White", "#f1efe8", "#14171d", 1000, 4, "White with a red badge: the Type R signature."),
}


def accent(state: dict) -> tuple[str, str]:
    k = state.get("ui_theme", "phoenix")
    _, acc, on, *_ = THEMES.get(k, THEMES["phoenix"])
    return acc, on


def theme_css(state: dict) -> str:
    acc, on = accent(state)
    r, g, b = (int(acc[i:i + 2], 16) for i in (1, 3, 5))
    soft = f"rgba({r},{g},{b},.14)"
    return f"""<style>
:root{{--y:{acc}}}
[data-testid^="stBaseButton-primary"]{{background:{acc}!important;border-color:{acc}!important}}
[data-testid^="stBaseButton-primary"] *{{color:{on}!important}}
[data-testid="stTab"][aria-selected="true"],[data-testid="stTab"][aria-selected="true"] *{{color:{acc}!important}}
[data-baseweb="tab-highlight"]{{background-color:{acc}!important}}
[data-testid="stProgressBarTrack"] div{{background-color:{acc}!important}}
[data-testid="stButtonGroup"] button[aria-checked="true"]{{border-color:{acc}!important;background:{soft}!important}}
[data-testid="stButtonGroup"] button[aria-checked="true"] *{{color:{acc}!important}}
[data-testid="stSlider"] [role="slider"]{{background-color:{acc}!important}}
[data-testid="stSliderThumbValue"]{{color:{acc}!important}}
a{{color:{acc}}}
</style>"""


def status_rows(rows: list[tuple]) -> None:
    """[(state, title, detail)] with state True=connected, False=missing, None=off. Quiet list, not alert boxes."""
    col = {True: "#2ec4b6", False: "#e10600", None: "#5b6070"}
    st.markdown("<div class='dod-rows'>" + "".join(
        f"<div class='dod-row'><span class='dod-dot' style='background:{col[ok]}'></span><div><b>{html.escape(t)}</b>"
        + (f" <span class='m'>{html.escape(d)}</span>" if d else "") + "</div></div>" for ok, t, d in rows) + "</div>",
        unsafe_allow_html=True)


def render_cluster(state: dict) -> None:
    lvl = level_of(state["xp"])
    into, span = state["xp"] - xp_for_level(lvl), xp_for_level(lvl + 1) - xp_for_level(lvl)
    ds, cond, coins = state.get("day_streak", 0), state["car"]["condition"], state["coins"]
    rp = st.session_state.get("race_replay") or {}
    if rp.get("revealed") is False:
        coins -= rp.get("payout", 0)  # no spoilers while the race is still running
    cells = [
        ("Coins", f"{coins:,}", "in debt — black flag" if coins < 0 else "", coins < 0),
        ("Day streak", f"{ds}", f"best {state.get('best_day_streak', 0)}", False),
        ("Focus today", f"{focus_today(state)}m", "", False),
        ("Car", f"{cond}%", "repair in the Garage" if cond < 60 else "", cond < 40),
    ]
    prev = st.session_state.get("_cluster_prev", {})
    pct = 100 * into / span
    prev_pct = prev.get("xp_pct", pct)
    st.session_state["_cluster_prev"] = {**{k: v for k, v, _, _ in cells}, "xp_pct": pct}
    intro = "" if st.session_state.get("_cluster_seen") else " intro"
    st.session_state["_cluster_seen"] = True
    st.markdown(
        f"<div class='dod-cluster{intro}'>" + "".join(
            f"<div class='dod-cell'><div class='dod-k'>{k}</div>"
            f"<div class='dod-v{' bad' if bad else ''}{' chg' if k in prev and prev[k] != v else ''}'>{v}</div>"
            f"<div class='dod-s'>{sub or '&nbsp;'}</div></div>" for k, v, sub, bad in cells)
        + f"<div class='dod-xp'><b>Level {lvl}</b><div class='dod-bar'>"
          f"<i style='width:{pct:.0f}%;--from:{min(prev_pct, pct) if prev_pct <= pct else 0:.0f}%'></i></div>"
          f"{into}/{span} XP · task streak {state['streak']}</div></div>", unsafe_allow_html=True)


# ─────────────────────────── app ───────────────────────────
st.set_page_config(page_title="Deadline or Die", page_icon="🏁", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
with st.container(key="audio_session"):  # iOS: app sounds mix with your music instead of pausing it
    st.iframe("<script>try{for(const w of [window,parent])if(w.navigator.audioSession)"
              "w.navigator.audioSession.type='ambient';}catch(e){}</script>", height=1)
if get_secret("NTFY_TOPIC") and not os.getenv("NTFY_TOPIC"):
    os.environ["NTFY_TOPIC"] = get_secret("NTFY_TOPIC")  # same secret seed as the nagger for surprise events

# Password gate — set APP_PASSWORD in secrets so nobody else can see your tasks and proof.
# Log in once per device: the key is kept in a cookie + localStorage (components/keeper), so links without ?k=,
# notification taps and the app waking from sleep all skip the password.
_pw = get_secret("APP_PASSWORD")
_KEEPER = components.declare_component("keeper", path=str(Path(__file__).parent / "components" / "keeper"))


def _keeper(set_: str | None = None, clear: bool = False):
    try:
        return _KEEPER(set=set_, clear=clear, key="keeper", default=None)
    except Exception:  # noqa: BLE001
        return None


if _pw:
    _tok = remember_key(_pw)
    if not st.session_state.get("_authed"):
        try:
            _ck = st.context.cookies.get("dod_k")
        except Exception:  # noqa: BLE001
            _ck = None
        if st.query_params.get("k") == _tok or _ck == _tok:
            st.session_state["_authed"] = True
            st.session_state["_persist"] = _ck != _tok  # came via the link: remember this device too
    if not st.session_state.get("_authed"):
        _held = _keeper()  # None until the browser answers (a moment after first paint), then "" or the key
        if _held == _tok:
            st.session_state["_authed"] = True
            st.session_state["_persist"] = True
            st.rerun()
        st.title("🏁 Deadline or Die")
        if _held is None:
            st.caption("Checking this device…")
        entered = st.text_input("Password", type="password")
        if entered:
            if hashlib.sha256(entered.encode()).digest() == hashlib.sha256(_pw.encode()).digest():
                st.session_state["_authed"] = True
                st.session_state["_persist"] = True
                st.rerun()
            st.error("Wrong password.")
        st.stop()
    if st.session_state.get("_persist"):  # write the key into this browser, then stop asking
        if _keeper(set_=_tok) == _tok:
            st.session_state["_persist"] = False
        st.markdown("<style>div[data-testid='stElementContainer']:has(iframe[title*='keeper'])"
                    "{position:absolute;width:0;height:0;overflow:hidden}</style>", unsafe_allow_html=True)


def app_link() -> str | None:
    """APP_URL with the remember-me key, so taps on notifications land logged in."""
    base = get_secret("APP_URL") or ((globals().get("state") or {}).get("settings") or {}).get("app_url")
    if not base or not _pw:
        return base
    return f"{base.split('?')[0]}?k={remember_key(_pw)}"


_boot = st.empty() if "_booted" not in st.session_state else None
if _boot is not None:
    _boot.markdown("<div class='dod-boot'><div class='dod-boot-car'>🏎️</div><div class='dod-boot-t'>Warming up the "
                   "tyres…</div><div class='dod-boot-bar'><i></i></div></div>", unsafe_allow_html=True)
state = load_state()
st.markdown(theme_css(state), unsafe_allow_html=True)
PROFILE = I.profile(state, now().date(), TZ)  # history before today → steers today's surprises (same in the nagger)
EV.set_profile(PROFILE)

sync_msgs = []
if st.session_state.pop("_fresh_load", False) and notion_cfg():
    try:
        sync_msgs, changed = sync_from_notion(state)
        if changed:
            st.session_state["_needs_save"] = True
    except Exception as e:
        sync_msgs = [("warning", f"Couldn't sync tasks with Notion: {e}")]

if _boot is not None:
    _boot.empty()
    st.session_state["_booted"] = True
crash_msgs = process_overdue(state)
crash_msgs += daily.settle(state, now(), bank, make_safety_car)
_excused = daily.excuse_outages(state, bank)
crash_msgs += DL.settle(state, now().date(), bank, daily.is_rest)
crash_msgs += SH.settle(state, now(), bank)
rust_msg = process_rust(state)
if _excused:
    crash_msgs = [m for m in crash_msgs if "MISSED QUALIFYING" not in m]
    st.session_state.setdefault("flash", []).extend(("info", m) for m in _excused)
if crash_msgs or rust_msg or _excused or st.session_state.pop("_needs_save", False):
    save_state(state)
    if crash_msgs:
        st.session_state["sound"] = "fail"
if rebalance_pit_checks(state):
    save_state(state)
start_from_link(state)
remember_app_url(state)
sync_alarms(state)

PLAYER = state["settings"].get("player_name") or "driver"
hour = now().hour
greet = "Late night" if hour < 5 else "Morning" if hour < 12 else "Afternoon" if hour < 18 else "Evening"
st.markdown(f"<div class='dod-hero'><h1>Deadline or Die</h1><p>{greet}, {html.escape(PLAYER)}. Prove it or pay for it."
            + (" It's a danger day: no one's watching, so everything you finish pays +20%."
               if now().weekday() in DANGER_DAYS else "") + "</p></div>", unsafe_allow_html=True)
render_cluster(state)

for kind, m in sync_msgs:
    getattr(st, kind)(m)
if notion_cfg():
    with _saver().lock:
        _bg_errs, _saver().errors = _saver().errors[:], []
    if _bg_errs:
        st.warning("⚠️ Some changes didn't sync to Notion: " + "; ".join(_bg_errs[:3]))
for m in crash_msgs:
    st.error(m)
if rust_msg:
    st.warning(rust_msg)
TOAST_ICON = {"success": "✅", "info": "💬"}
for kind, m in st.session_state.pop("flash", []):
    if kind in TOAST_ICON and len(m) <= 170 and "\n" not in m:
        lead = m.split(" ", 1)
        icon = lead[0] if len(lead) == 2 and not lead[0][:1].isalnum() and len(lead[0]) <= 3 and "*" not in lead[0] else None
        st.toast(lead[1] if icon else m, icon=icon or TOAST_ICON[kind], duration="long" if len(m) > 90 else "short")
    else:
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
    with st.container(key="sfx"):  # plays, but the player bar stays out of sight
        st.markdown("<style>.st-key-sfx{position:fixed!important;left:-9999px;top:0;width:1px;height:1px;"
                    "overflow:hidden;opacity:0;pointer-events:none}</style>", unsafe_allow_html=True)
        st.audio(tone_wav(SOUNDS[snd]), format="audio/wav", autoplay=True)


lvl = level_of(state["xp"])

open_tasks = sorted([t for t in state["tasks"] if t["status"] == "open"], key=lambda t: t["deadline"])
tab_today, tab_tasks, tab_goals, tab_stats, tab_garage, tab_race, tab_lounge, tab_set = st.tabs(
    ["🏁 Today", "✅ Tasks", "🎯 Goals", "📊 Stats", "🔧 Garage", "🏎️ Race", "🎰 Lounge", "⚙️ Settings"],
    key="nav", on_change="ignore" if os.getenv("DOD_ALL_TABS") else "rerun")  # remembers the open tab; only it runs

# ── Today: the cockpit. Do-now on the left, instruments on the right; stacks on a phone. ──
with tab_today:
  if tab_today.open is not False:
    c_main, c_rail = st.columns([1.55, 1], gap="large")
    with c_main:
        render_checkin(state)
        render_today(state)
        render_close_day(state)
        render_task_board(state, open_tasks)
    with c_rail:
        render_timer(state)
        render_dailies(state)
        render_race_status(state)

# ── Pit Wall ──
# ── Tasks ──
with tab_tasks:
  if tab_tasks.open is not False:
    points_guide()
    with st.expander("➕ New task", expanded=not open_tasks):
        task_form(state, "new_task_form")
    with st.expander("📥 Import from Notion"):
        notion_import(state)

    st.subheader(f"Open ({len(open_tasks)})")
    for t in open_tasks:
        render_task_row(state, t, "tt_")

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
  if tab_goals.open is not False:
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

    with st.expander("🗓️ Prep for an upcoming event (conference, talk, exam, submission…)",
                     expanded=not any(g.get("event_kind") for g in state["goals"])):
        st.caption("Pick something coming up on your DECK 12 board. It becomes a goal with prep steps planned "
                   "backwards from the date — each step is a real deadline, and finishing them fills the goal.")
        render_event_planner(state)

    has_key = bool(get_secret("ANTHROPIC_API_KEY"))
    for g in state["goals"]:
        gtasks = [t for t in state["tasks"] if t.get("goal_id") == g["id"]]
        n_done = sum(t["status"] == "done" for t in gtasks)
        target = date.fromisoformat(g["target"])
        with st.container(border=True):
            st.markdown(f"### {P.KINDS[g['event_kind']][0].split()[0] if g.get('event_kind') in P.KINDS else '🎯'} "
                        f"{g['title']}")
            if g.get("why"):
                st.caption(f"Why: {g['why']}")
            for ev in g.get("events", []):
                st.caption(f"🗓️ Feeds in: {ev['title']} · {date.fromisoformat(ev['date']):%b %d}")
            st.progress(n_done / len(gtasks) if gtasks else 0.0,
                        text=f"{n_done}/{len(gtasks)} milestones · {'📅 event' if g.get('event_kind') else 'target'} "
                             f"{target:%b %d, %Y} "
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

# ── Stats ──
VIZ = {"normal": "#3987e5", "dead": "#d95926", "peak": "#199e70", "low": "#1d2735", "grid": "#2b2e36"}


PERIODS = ["Week", "Month", "Year"]


def _period(kind: str, back: int, today: date) -> tuple[date, date, str]:
    if kind == "Week":
        lo = today - timedelta(days=today.weekday()) - timedelta(weeks=back)
        hi = lo + timedelta(days=6)
        return lo, hi, ("This week" if back == 0 else "Last week" if back == 1 else f"Week of {lo:%b} {lo.day}")
    if kind == "Month":
        y, m = today.year, today.month - back
        while m < 1:
            y, m = y - 1, m + 12
        lo = date(y, m, 1)
        hi = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        return lo, hi, f"{lo:%B %Y}"
    lo, hi = date(today.year - back, 1, 1), date(today.year - back, 12, 31)
    return lo, hi, str(lo.year)


def render_focus_periods(state: dict) -> None:
    """⏱️ When you actually work: timer sessions only, by week / month / year, with the previous period to compare."""
    import altair as alt
    acc = accent(state)[0]
    light = _mix(acc, "#ffffff", .55)
    today = now().date()
    c1, c2, c3, c4 = st.columns([2.4, .45, .45, 2], vertical_alignment="center")
    kind = c1.segmented_control("Period", PERIODS, default="Week", key="fx_kind",
                                label_visibility="collapsed") or "Week"
    if st.session_state.get("_fx_kind") != kind:
        st.session_state["_fx_kind"], st.session_state["fx_back"] = kind, 0
    back = st.session_state.get("fx_back", 0)
    if c2.button("‹", key="fx_prev", use_container_width=True, help="Earlier"):
        st.session_state["fx_back"] = back = back + 1
    if c3.button("›", key="fx_next", use_container_width=True, disabled=back == 0, help="Later"):
        st.session_state["fx_back"] = back = max(0, back - 1)
    lo, hi, label = _period(kind, back, today)
    plo, phi, _ = _period(kind, back + 1, today)
    c4.markdown(f"**{label}**")
    g = I.focus_grid(state, lo, hi, TZ)
    prev = sum(I.focus_grid(state, plo, phi, TZ)["day"].values())
    total = sum(g["day"].values())
    days_in = [lo + timedelta(days=i) for i in range((min(hi, today) - lo).days + 1)] if lo <= today else []
    active = [d for d in days_in if g["day"].get(d, 0) >= 1]
    best = max(active, key=lambda d: g["day"][d]) if active else None
    delta = (f"<span>{'▲' if total >= prev else '▼'} <b>{abs(total - prev) / 60:.1f} h</b> vs previous</span>"
             if prev or total else "")
    st.markdown("<div class='dod-pills'>"
                f"<span>⏱️ <b>{total / 60:.1f} h</b> focused</span>"
                f"<span>📅 <b>{len(active)}</b>/{len(days_in) or 0} days</span>"
                + (f"<span>Avg <b>{total / len(active) / 60:.1f} h</b> on days you worked</span>" if active else "")
                + (f"<span>🏆 Best <b>{best:%a %b} {best.day}</b> · {g['day'][best] / 60:.1f} h</span>" if best else "")
                + delta + "</div>", unsafe_allow_html=True)
    if not total:
        st.caption("No timer sessions in this period. Only the ⏱️ focus timer counts here: claiming a task or "
                   "ticking a daily isn't working time.")
        return
    # 1) over time
    if kind == "Year":
        label_of = lambda d: f"{d:%b}"  # noqa: E731
        rows = [{"When": date(lo.year, m, 1).strftime("%b"), "i": m,
                 "Hours": round(sum(v for d, v in g["day"].items() if d.month == m) / 60, 1)} for m in range(1, 13)]
    else:
        label_of = (lambda d: f"{d:%a}") if kind == "Week" else (lambda d: str(d.day))  # noqa: E731
        rows = [{"When": (f"{d:%a}" if kind == "Week" else str(d.day)), "i": i,
                 "Hours": round(g["day"].get(d, 0) / 60, 2), "now": d == today}
                for i, d in enumerate(lo + timedelta(days=k) for k in range((hi - lo).days + 1))]
    df = pd.DataFrame(rows)
    unit = "month" if kind == "Year" else "day"
    st.markdown(f"**Focus over time** · hours per {unit} · <span style='opacity:.6'>tap bars to filter the chart "
                f"below</span>", unsafe_allow_html=True)
    # one selection drives both charts: tap bars here and "When in the day" narrows to them
    pick = alt.selection_point(name="pick", fields=["When"], toggle="true", empty=True)
    top_chart = alt.Chart(df).mark_bar(cornerRadiusEnd=4, color=acc,
                                       **({} if kind == "Month" else {"size": 26})).encode(
        x=alt.X("When:N", sort=alt.SortField("i"), title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Hours:Q", title="Hours"), tooltip=["When", "Hours"],
        opacity=alt.condition(pick, alt.value(1), alt.value(.3))).add_params(pick).properties(height=190)
    try:
        ev = st.altair_chart(top_chart, width="stretch", on_select="rerun", selection_mode="pick",
                             key=f"fx_pick_{kind}_{back}")
        chosen = {x.get("When") for x in ((ev or {}).get("selection", {}).get("pick") or []) if x.get("When")}
    except Exception:  # noqa: BLE001 — older Streamlit: plain chart, no linking
        _chart(top_chart)
        chosen = set()
    # 2) time of day, over the same period (or just the bars you picked)
    in_sel = (lambda d: label_of(d) in chosen) if chosen else (lambda d: True)  # noqa: E731
    sel_days = {d for d in active if in_sel(d)}
    span = max(1, len(sel_days))
    hrs = pd.DataFrame([{"Hour": _hlabel(h), "h": h,
                         "Min/day": round(sum(v for (d, hh), v in g["dh"].items() if hh == h and in_sel(d)) / span, 1)}
                        for h in range(5, 24)])
    top = hrs.sort_values("Min/day", ascending=False).iloc[0]
    scope = (f"{', '.join(sorted(chosen, key=lambda w: df.loc[df['When'] == w, 'i'].iloc[0]))} only"
             if chosen else label)
    st.markdown(f"**When in the day** · {scope} · avg minutes per working day at each hour"
                + (f" · peak **{top['Hour']}**" if top["Min/day"] > 0 else " · nothing logged"))
    _chart(alt.Chart(hrs).mark_bar(cornerRadiusEnd=3, color=acc).encode(
        x=alt.X("Hour:N", sort=alt.SortField("h"), title=None),
        y=alt.Y("Min/day:Q", title="Min / day"), tooltip=["Hour", "Min/day"]).properties(height=170))
    # 3) weekday × hour
    wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if kind == "Week":
        cells = [{"Day": f"{lo + timedelta(days=i):%a}", "d": i, "Hour": _hlabel(h), "h": h,
                  "Minutes": round(g["dh"].get((lo + timedelta(days=i), h), 0))} for i in range(7) for h in range(5, 24)]
        ttl = "**Day × hour** · minutes"
    else:
        agg = defaultdict(float)
        for (d, h), v in g["dh"].items():
            agg[(d.weekday(), h)] += v
        cells = [{"Day": wd[i], "d": i, "Hour": _hlabel(h), "h": h, "Minutes": round(agg.get((i, h), 0))}
                 for i in range(7) for h in range(5, 24)]
        ttl = "**Weekday × hour** · total minutes in the period"
    st.markdown(ttl)
    _chart(alt.Chart(pd.DataFrame(cells)).mark_rect(cornerRadius=3, stroke="#0e1117", strokeWidth=2).encode(
        x=alt.X("Hour:N", sort=alt.SortField("h"), title=None),
        y=alt.Y("Day:N", sort=alt.SortField("d"), title=None),
        color=alt.Color("Minutes:Q", scale=alt.Scale(range=[VIZ["low"], acc, light], interpolate="rgb"),
                        legend=alt.Legend(title="Min")),
        tooltip=["Day", "Hour", "Minutes"]).properties(height=220))


def _mix(hex_: str, other: str, t: float) -> str:
    a = [int(hex_[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _chart(c) -> None:
    try:
        st.altair_chart(c, width="stretch")
    except TypeError:
        st.altair_chart(c, use_container_width=True)


def _hlabel(h: int) -> str:
    return datetime(2000, 1, 1, h).strftime("%I %p").lstrip("0")


with tab_stats:
  if tab_stats.open is not False:
    stats_view = st.segmented_control("Stats view", ["📊 Numbers", "📸 Scrapbook", "📓 Journal"], default="📊 Numbers",
                                      key="stats_view", label_visibility="collapsed") or "📊 Numbers"
    if stats_view == "📸 Scrapbook":
        render_scrapbook(state)
    elif stats_view == "📓 Journal":
        render_journal(state)
  if tab_stats.open is not False and stats_view == "📊 Numbers":
    import altair as alt
    _acc = accent(state)[0]
    VIZ = {**VIZ, "normal": _acc, "light": _mix(_acc, "#ffffff", .55)}
    full = I.history(state, now().date() + timedelta(days=1), TZ)  # last 28 days, today included
    k = st.container(key="stat_kpis").columns(4)
    k[0].metric("Finished · 28 days", full["done"],
                help="Tasks you finished with proof (incl. redeemed) in the last 28 days.")
    rate = full["on_time"] / full["done"] if full["done"] else None
    k[1].metric("On time", f"{rate:.0%}" if rate is not None else "—",
                delta=f"{full['failed']} missed" if full["failed"] else None, delta_color="inverse")
    k[2].metric("Focus hours", f"{full['focus_min'] / 60:.1f}", help="Timer-logged work minutes (breaks excluded).")
    k[3].metric("Active days", f"{full['active_days']}/28")
    hr_ = DL.hit_rate(state, now().date())
    if hr_ is not None:
        st.caption(f"🔁 Dailies hit rate (28 days): **{hr_:.0%}**")

    if not full["done"] and not full["focus_min"]:
        st.info("Nothing logged yet. Finish a task or run a focus session and this page starts filling in.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Hours by category** · 28 days")
            cat = pd.DataFrame([{"Category": V.CATEGORIES.get(c_, {}).get("label", c_), "Hours": round(m_ / 60, 1)}
                                for c_, m_ in full["cat_min"].items()]).sort_values("Hours", ascending=False) \
                if full["cat_min"] else pd.DataFrame({"Category": [], "Hours": []})
            _chart(alt.Chart(cat).mark_bar(cornerRadiusEnd=4, color=VIZ["normal"]).encode(
                x=alt.X("Hours:Q", title="Hours"),
                y=alt.Y("Category:N", sort="-x", title=None, scale=alt.Scale(paddingInner=0.35),
                        axis=alt.Axis(labelLimit=160)),
                tooltip=["Category", "Hours"]).properties(height=max(150, 46 * len(cat))))
        with c2:
            st.markdown("**Finishes per week**")
            wk = pd.DataFrame([{"Week of": f"{w:%b %d}", "Finished": n_} for w, n_ in full["weeks"]])
            _chart(alt.Chart(wk).mark_bar(cornerRadiusEnd=4, color=VIZ["normal"], size=22).encode(
                x=alt.X("Week of:N", sort=None, title=None), y=alt.Y("Finished:Q", title="Tasks"),
                tooltip=["Week of", "Finished"]).properties(height=200))

        render_focus_periods(state)

    st.subheader("🧠 How the engine uses this")
    if not PROFILE["ready"]:
        st.caption(f"The engine starts steering after {I.MIN_ACTIVE_DAYS} active days with 2+ hours logged "
                   f"(you're at {PROFILE['active_days']} day(s), {PROFILE['total_min'] / 60:.1f} h, up to yesterday). "
                   "Until then, surprises are spread evenly from 9 AM to 7 PM.")
    else:
        w0, w1 = PROFILE["window"]
        st.markdown(
            f"- 🕘 **Your working day:** {_hlabel(w0)}–{_hlabel(w1 % 24)}"
            + (f", usually starting around **{_hlabel(PROFILE['usual_start'])}**" if PROFILE["usual_start"] is not None else "")
            + f".\n- 🟢 **Peak hours:** {I.fmt_hours(PROFILE['peak'])} → 🎲 *Just tell me what to do* hands you the "
              "meaty task in these hours; outside them, the quick win."
            + f"\n- 🟠 **Dead zones:** {I.fmt_hours(PROFILE['dead'])} — you're up, but not working. ⏱️ Focus challenges "
              "and ⚡ live events are up to **4×** likelier to land here, and 💡 phone suggestions aim here too."
            + f"\n- ☀️ **Morning briefing** lands at {_hlabel(I.brief_hour(PROFILE, 8))} (an hour before you usually start)."
            + "\n\nBuilt from history up to yesterday, so today's surprises stay put while you work.")
    with st.expander("📋 Table view"):
        st.dataframe(pd.DataFrame({"Hour": [_hlabel(h_) for h_ in range(24)],
                                   "Minutes (28d)": [round(x) for x in full["hour_min"]]}), hide_index=True)

# ── Garage ──
with tab_garage:
  if tab_garage.open is not False:
    car = state["car"]
    model = CAR_BY_ID.get(car.get("model"), CARS[0])
    g_l, g_r = st.columns([1.3, 1], gap="large", vertical_alignment="center")
    g_l.markdown(car_svg(car), unsafe_allow_html=True)
    with g_r:
        st.markdown(f"### #{car['number']} {car['name']}")
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

    with st.expander("🎨 Paint shop — colour the whole app", expanded=False):
        st.caption("Unlock Honda colours for the app itself: buttons, timer, instrument cluster, everything.")
        owned_t = state.setdefault("themes_owned", ["phoenix"])
        cur_t = state.get("ui_theme", "phoenix")
        lvl_now = level_of(state["xp"])
        cols = st.columns(len(THEMES))
        for col, (k, (name, acc, on, cost, need, blurb)) in zip(cols, THEMES.items()):
            with col:
                st.markdown(f"<div style='height:54px;border-radius:10px;background:linear-gradient(135deg,{acc},"
                            f"{acc}cc);border:1px solid #2c313c;margin-bottom:6px'></div><b>{name}</b>"
                            f"<div style='color:#8b909c;font-size:.82rem;min-height:2.6em'>{blurb}</div>",
                            unsafe_allow_html=True)
                if k == cur_t:
                    st.caption("✅ In use")
                elif k in owned_t:
                    if st.button("Use", key=f"theme_use_{k}", use_container_width=True):
                        state["ui_theme"] = k
                        save_state(state)
                        flash(f"🎨 {name} applied.")
                        st.rerun()
                elif lvl_now < need:
                    st.caption(f"🔒 Level {need}")
                elif st.button(f"{cost:,} 🪙", key=f"theme_buy_{k}", use_container_width=True,
                               disabled=state["coins"] < cost):
                    bank(state, -cost, f"🎨 Paint: {name}")
                    owned_t.append(k)
                    state["ui_theme"] = k
                    save_state(state)
                    flash(f"🎨 **{name}** unlocked and applied.", celebrate=True, sound="jackpot")
                    st.rerun()

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
  if tab_race.open is not False:
    car = state["car"]
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
        rating = track_rating(state, track)
        st.caption("🏁 " + RV.TRACK_CHARACTER.get(track["name"], ([], ""))[1].capitalize() + ".")
        m_ = sandbag(state, track)
        pz = [round(x * m_) for x in track["prize"]]
        st.markdown(f"Your car **{rating:.0f}** here vs rivals **{lo}–{hi}** · Entry **{track['fee']} 🪙** · "
                    f"Prizes 🥇{pz[0]} 🥈{pz[1]} 🥉{pz[2]}")
        if m_ < 1:
            st.caption(f"🪜 You outclass this track: fast rivals show up and prizes pay ×{m_:.2f}. "
                       "Move up a track for full prizes.")
        if car["condition"] < 40:
            st.warning("Car under 40% — real risk of a DNF.")
        if lvl < track["level"]:
            st.info(f"Unlocks at driver level {track['level']}. Earn XP by finishing tasks.")
        else:
            left_t, why_t = race_tickets(state)
            rp_ = st.session_state.get("race_replay")
            racing = bool(rp_ and not rp_.get("revealed"))
            st.caption(why_t)
            if state["coins"] < track["fee"]:
                st.info("Can't cover the entry fee.")
            elif racing:
                st.button("🏎️ Race in progress…", disabled=True)
            elif st.button("🚦 Lights out", type="primary", disabled=not left_t):
                bank(state, -track["fee"], f"🎟️ Entry: {track['name']}")
                simulate_race(state, track)

        rp = st.session_state.get("race_replay")
        if rp:
            st.markdown(f"#### 📺 {rp['title']}")
            (st.iframe if hasattr(st, "iframe") else __import__("streamlit.components.v1", fromlist=["html"]).html)(
                rp["html"], height=460)
            _race_result(rp)

        _hide = 1 if (st.session_state.get("race_replay") or {}).get("revealed") is False else 0
        if state["races"][_hide:]:
            with st.expander("Race history"):
                for r in state["races"][_hide:15]:
                    pos = r["pos"] if r["pos"] == "DNF" else f"P{r['pos']}"
                    st.markdown(f"**{pos}** {r['track']} · +{r['payout']} 🪙 "
                                f"<small>· {parse_dt(r['ts']):%b %d}</small>", unsafe_allow_html=True)

# ── Lounge ──
with tab_lounge:
  if tab_lounge.open is not False:
    render_lounge(state)

# ── Settings ──
with tab_set:
  if tab_set.open is not False:
    s = state["settings"]
    sec = st.segmented_control("Section", ["Driver", "Rules", "Boards", "Phone & locks", "Integrations", "Backup"],
                               default="Driver", key="set_sec", label_visibility="collapsed") or "Driver"
    tok = get_secret("NOTION_TOKEN")

    if sec == "Driver":
        with st.container(border=True):
            st.markdown("#### Driver")
            with st.form("set_driver", border=False):
                pname = st.text_input("Name the app calls you", value=s.get("player_name", "Driver"))
                sounds = st.toggle("Sound cues when you win or miss", value=s.get("sounds", True))
                focus_lock = st.toggle("Block games while a focus session runs", value=s.get("focus_lock", True))
                if st.form_submit_button("Save", type="primary"):
                    s.update(player_name=pname.strip() or "Driver", sounds=sounds, focus_lock=focus_lock)
                    save_state(state)
                    flash("Saved.")
                    st.rerun()

    elif sec == "Rules":
        dc = daily.cfg(state)
        wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        with st.container(border=True):
            st.markdown("#### Rules")
            with st.form("set_rules", border=False):
                c1, c2 = st.columns(2)
                q_by = c1.slider("Lock in your mission by", 6, 16, int(dc["qualify_by"]),
                                 format="%d:00", help="After this, the safety car picks your task (24h clock).")
                grace = c2.slider("Grace after a deadline (min)", 0, 240, int(s["grace_minutes"]), 15)
                c3, c4 = st.columns(2)
                ext_h = c3.slider("Extension length (h)", 1, 72, int(s["extension_hours"]))
                max_ext = c4.slider("Extensions per task", 0, 5, int(s["max_extensions"]))
                rest = st.pills("Standing rest days (never penalized)", wd, selection_mode="multi",
                                default=[wd[i] for i in dc["rest_days"]])
                strict = st.toggle("Every proof needs a file", value=s["strict_proof"])
                ai = st.toggle("Claude checks your proof", value=s["ai_steward"],
                               help="Needs an Anthropic API key (Integrations).")
                if st.form_submit_button("Save rules", type="primary"):
                    s.update(grace_minutes=int(grace), strict_proof=strict, extension_hours=int(ext_h),
                             max_extensions=int(max_ext), qualify_by=int(q_by), rest_days=[wd.index(x) for x in rest or []],
                             ai_steward=ai)
                    save_state(state)
                    flash("Rules saved.")
                    st.rerun()

    elif sec == "Boards":
        with st.container(border=True):
            st.markdown("#### DECK 12 boards")
            st.caption("Input is read-only: its cards become suggestions and events to prep for. Output is "
                       "write-only: your tasks land on it at the time they're set to happen. Neither is ever "
                       "touched the other way.")
            if not notion_cfg():
                status_rows([(False, "Notion isn't connected", "add NOTION_TOKEN and NOTION_PARENT_PAGE to secrets")])
            else:
                rows = []
                for key_, label_ in (("board_db", "Input"), ("out_db", "Output")):
                    cur = s.get(key_)
                    if not cur:
                        rows.append((None, f"{label_}: not linked", ""))
                        continue
                    try:
                        m_ = _board_map(tok, cur)
                        rows.append((True, f"{label_}: {m_['name']}",
                                     "reads " + ", ".join(x for x in (m_["title"], m_["date"], m_["weekday"]) if x)
                                     if key_ == "board_db" else
                                     "writes " + ", ".join(x for x in (m_["title"], m_["date"], m_["weekday"], m_["time"]) if x)))
                    except Exception as e:
                        rows.append((False, f"{label_}: can't read it", str(e)[:90]))
                status_rows(rows)
                if s.get("board_db") and s.get("board_db") == s.get("out_db"):
                    st.warning("Input and output are the same board. Pick a separate board for output.")
                c1, c2, c3 = st.columns(3)
                if c1.button("Find boards", use_container_width=True):
                    try:
                        n_, ids_ = notion_ctx()
                        st.session_state["board_list"] = B.list_databases(n_, {ids_["tasks_db"].replace("-", "")})
                    except Exception as e:
                        st.error(str(e))
                if s.get("board_db") and c2.button("Unlink input", use_container_width=True):
                    s["board_db"] = ""
                    save_state(state)
                    st.rerun()
                if s.get("out_db") and c3.button("Unlink output", use_container_width=True):
                    s["out_db"] = ""
                    save_state(state)
                    st.rerun()
                dbs = st.session_state.get("board_list")
                if dbs is not None:
                    if not dbs:
                        st.info("No other databases are visible. If your board is a linked view, share its source "
                                "database with the Deadline or Die connection.")
                    else:
                        pick = st.selectbox("Board", [d["id"] for d in dbs],
                                            format_func=lambda i: next(d["title"] for d in dbs if d["id"] == i))
                        c1, c2, c3 = st.columns(3)
                        if c1.button("Preview", use_container_width=True):
                            try:
                                m = B.detect(Notion(tok), pick)
                                items = B.pull_day(Notion(tok), m, now().date())
                                st.caption(B.describe(m) + " · today: " + (", ".join(i["title"] for i in items) or "nothing"))
                            except Exception as e:
                                st.error(str(e))
                        if c2.button("Use as input", use_container_width=True):
                            s["board_db"] = pick
                            save_state(state)
                            st.session_state.pop("board_list", None)
                            flash("Input board linked. Its cards show up as suggestions.")
                            st.rerun()
                        if c3.button("Use as output", type="primary", use_container_width=True):
                            s["out_db"] = pick
                            save_state(state)
                            st.session_state.pop("board_list", None)
                            flash("Output board linked. Your tasks now land on it.")
                            st.rerun()

    elif sec == "Phone & locks":
        topic = get_secret("NTFY_TOPIC")
        lt = LK.topic(topic)
        with st.container(border=True):
            st.markdown("#### Phone & locks")
            status_rows([
                (bool(topic), "Phone nags" if topic else "Phone nags are off", "ntfy topic set" if topic else
                 "set NTFY_TOPIC in secrets"),
                (bool(lt), "Lock broadcast", f"{lt} · now {LK.message(LK.status(state, now()))}" if lt else
                 "needs NTFY_TOPIC"),
            ])
            if topic and st.button("Send a test buzz"):
                ok = push(topic, "🏁 Deadline or Die", f"Test buzz, {PLAYER}. This is what a checkered flag feels like.",
                          priority=4, tags=["checkered_flag"], click=app_link())
                if ok:
                    st.toast("📳 Buzz sent — check your phone.")
                else:
                    st.toast("ntfy didn't accept it. Check the topic name.", icon="⚠️")
            st.caption("No push on iPhone? Remove and re-add the topic in the ntfy app, and check Settings → "
                       "Notifications → ntfy (banners on, delivery Immediate, not filtered by a Focus).")
        with st.container(border=True):
            st.markdown("#### 🚦 Focus nudges")
            st.caption("Pushes in your work hours that name one task and carry a ▶️ Start button (opens the app with "
                       "the timer running). They skip while a timer runs, stop once you hit your daily focus goal, "
                       "and get louder if you ignore them.")
            nc = NU.cfg(state)
            ss = state["settings"]
            every = st.segmented_control("How often", list(NU.EVERY_OPTS), default=nc["nudge_every"],
                                         format_func=NU.EVERY_OPTS.get, key="nu_every")
            c1, c2, c3 = st.columns(3)
            hrs = list(range(6, 24))
            lab = lambda h: datetime(2000, 1, 1, h).strftime("%I %p").lstrip("0")  # noqa: E731
            a_ = c1.selectbox("From", hrs[:-1], index=hrs.index(nc["nudge_start"]), format_func=lab, key="nu_a")
            b_ = c2.selectbox("Until", [h for h in hrs if h > a_], format_func=lab, key="nu_b",
                              index=max(0, [h for h in hrs if h > a_].index(nc["nudge_end"]))
                              if nc["nudge_end"] in [h for h in hrs if h > a_] else 0)
            goal = c3.number_input("Daily focus goal (min)", 30, 600, int(nc["focus_goal"]), 15, key="nu_goal")
            wk = st.toggle("Weekends too", value=bool(nc["nudge_weekends"]), key="nu_wk")
            new = {"nudge_every": every if every is not None else nc["nudge_every"], "nudge_start": a_,
                   "nudge_end": b_, "focus_goal": int(goal), "nudge_weekends": wk}
            if any(ss.get(k, NU.DEFAULTS[k]) != v for k, v in new.items()):
                ss.update(new)
                save_state(state)
            if PROFILE and PROFILE.get("ready"):
                w0, w1 = PROFILE["window"]
                st.caption(f"Your history says you work {lab(w0)}–{lab(w1)}, best around "
                           + ", ".join(lab(h) for h in PROFILE["peak"]) + ". Peak-hour nudges hand you the meaty task.")
        if _pw:
            with st.container(border=True):
                st.markdown("#### Open without a password")
                st.caption("Open this link once on your phone, then Share → Add to Home Screen. Put it in the "
                           "APP_URL secret too, so notifications open logged in. Treat it like a password.")
                st.code(f"{(get_secret('APP_URL') or '').split('?')[0]}?k={remember_key(_pw)}", language=None)

    elif sec == "Integrations":
        names = {"NOTION_TOKEN": "Notion", "NOTION_PARENT_PAGE": "Notion page", "NTFY_TOPIC": "Phone (ntfy)",
                 "APP_URL": "App link", "ZOTERO_USER_ID": "Zotero user", "ZOTERO_API_KEY": "Zotero key",
                 "ANTHROPIC_API_KEY": "Claude (proof checks, planning)"}
        with st.container(border=True):
            st.markdown("#### Connections")
            if notion_cfg():
                try:
                    notion_ctx()
                    nrow = (True, "Saving to Notion", "tasks, save file and nagger memory live under your page")
                except Exception as e:
                    nrow = (False, "Notion is set but unreachable", str(e)[:90])
            else:
                nrow = (False, "Saving on this server only", "add NOTION_TOKEN + NOTION_PARENT_PAGE")
            status_rows([nrow] + [(bool(get_secret(k)), v, "set" if get_secret(k) else "not set")
                                  for k, v in names.items() if k not in ("NOTION_TOKEN", "NOTION_PARENT_PAGE")])
            st.caption("Keys belong in the Streamlit secrets box (and GitHub secrets for the phone nagger). "
                       "Anything typed below lasts for this session only.")
            with st.expander("Enter a key for this session"):
                kname = st.selectbox("Key", [k for k in names if not get_secret(k) or st.session_state.get(f"secret_{k}")],
                                     format_func=names.get) if any(not get_secret(k) for k in names) else None
                if kname:
                    val = st.text_input("Value", type="password" if "KEY" in kname or "TOKEN" in kname else "default",
                                        key=f"in_{kname}")
                    if val:
                        st.session_state[f"secret_{kname}"] = val.strip()
                else:
                    st.caption("Everything is already set.")
        with st.container(border=True):
            st.markdown("#### Zotero")
            if zotero_cfg(state):
                zc_ = zotero_cfg(state)
                c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
                new_coll = c1.text_input("Collection to pull papers from", value=zc_[2], key="zot_coll")
                if c2.button("Test", use_container_width=True):
                    try:
                        ps = Z.to_read(*zc_[:2], new_coll)
                        st.success(f"{len(ps)} unread in “{new_coll}”. First up: {Z.label(ps[0]) if ps else 'nothing'}")
                    except Exception as e:
                        st.error(str(e))
                if c3.button("Save", use_container_width=True) and new_coll.strip():
                    s["zotero_collection"] = new_coll.strip()
                    save_state(state)
                    st.rerun()
            else:
                st.caption("Add ZOTERO_USER_ID and ZOTERO_API_KEY to secrets. Both are on zotero.org/settings/keys; "
                           "the user ID is at the top of that page.")
        with st.expander("Claude model and Notion import"):
            with st.form("set_adv", border=False):
                model = st.text_input("Claude model", value=s["model"])
                db = st.text_input("Import tasks from another Notion database (link or ID)", value=s["notion_db"])
                c1, c2 = st.columns(2)
                dprop = c1.text_input("Due-date property (blank = first date)", value=s["notion_date_prop"])
                fprop = c2.text_input("Done property (optional)", value=s["notion_done_prop"])
                if st.form_submit_button("Save", type="primary"):
                    s.update(model=model.strip(), notion_db=db.strip(), notion_date_prop=dprop.strip(),
                             notion_done_prop=fprop.strip())
                    save_state(state)
                    flash("Saved.")
                    st.rerun()

    else:  # Backup
        with st.container(border=True):
            st.markdown("#### Backup")
            st.download_button("Download save file", json.dumps(state, indent=2, default=str),
                               file_name=f"deadline-or-die-{now():%Y%m%d}.json", mime="application/json")
            restore = st.file_uploader("Restore from a save file", type=["json"], key="restore")
            if restore and st.button("Restore this save"):
                try:
                    save_state(_merge(default_state(), json.loads(restore.getvalue())))
                    flash("Save restored.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Couldn't read that file: {e}")
        with st.expander("Reset everything"):
            st.caption("Wipes coins, cars, tasks and history. Download a backup first.")
            if st.checkbox("I want to wipe everything") and st.button("Reset game"):
                save_state(default_state())
                flash("Fresh start.", "warning")
                st.rerun()
