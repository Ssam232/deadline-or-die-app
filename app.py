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
import copy
import hashlib
import html
import zlib
import io
import json
import math
import os
import random
import re
import statistics
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
import commitments as CM
import crew as CR
import rank as RK
import locks as LK
import pomo as PM
import prayers as PR
import alarms as AL
import shield as SH
import tracks as TR
import journal as J
import nudges as NU
import prep as P
import roadmap as R
import notion_goals as NG
import backups as BK
import journal_notion as JN
import quickparse as Q
import raceviz as RV
import seasons as SE
import lounge as L
import valuation as V
import zotero as Z
from notify import push
from notion_store import (Notion, NotionError, STATUS, archive_page, due_to_dt, ensure_workspace, load_json,
                          pull_rows, save_json, task_props, update_dashboard, upload_proof, upsert_task)

# ─────────────────────────── config ───────────────────────────
from tzfix import TZ  # Alberta: UTC-6 all year (safe against stale tz data on a server)
DATA_DIR = Path(os.getenv("DOD_DATA_DIR", Path(__file__).parent / "data"))
PROOF_DIR = DATA_DIR / "proofs"
STATE_FILE = DATA_DIR / "state.json"
RACE_TICK = float(os.getenv("DOD_RACE_TICK", "0.12"))  # seconds per animation frame

ANTHROPIC_URL = os.getenv("DOD_ANTHROPIC_URL", "https://api.anthropic.com/v1/messages")  # tests use a stub
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
MAX_PART_LEVEL = 7  # L6–L7 only fit the Acura ladder's chassis (see garage.CHASSIS)
PRESTIGE_STEP, PRESTIGE_MAX = 0.05, 4  # each retired build: +5% on task coins, up to +20%

RIVALS = [
    "Tomorrow Tom", "Snooze Button", "Doomscroll Dan", "Just-One-Episode",
    "Night-Before Nate", "Perfectionist Pat", "Inbox Zero-ish", "Busywork Bella",
    "'Quick Break' Quinn", "Reorganize-My-Desk Rob",
]

# Your garage: a real-model progression, unlocked by driver level + coins. Drawings are stylized silhouettes.
CARS = [  # one ladder in rough real-world performance order; Honda cars kept their levels and prices
    {"id": "civic_si", "name": "Honda Civic Si", "base": 40, "cost": 0, "level": 1, "body": "sedan",
     "blurb": "Where every Honda guy starts. Rev it out."},
    {"id": "crx", "name": "Honda CR-X SiR", "base": 42, "cost": 150, "level": 1, "body": "crx",
     "blurb": "Two seats, no weight, all fun. The first cheap thrill."},
    {"id": "tsx", "name": "Acura TSX", "base": 44, "cost": 250, "level": 2, "body": "tsx",
     "blurb": "The grown-up sport sedan. Quietly quick, and a K24 that loves revs."},
    {"id": "rsx", "name": "Acura RSX Type-S", "base": 47, "cost": 320, "level": 2, "body": "rsx",
     "blurb": "A light three-door with a K20 that sings past 8,000 rpm."},
    {"id": "s660", "name": "Honda S660", "base": 46, "cost": 300, "level": 2, "body": "s660",
     "blurb": "A mid-engine roadster small enough to park sideways. Grins per horsepower: off the chart."},
    {"id": "integra_r", "name": "Honda Integra Type R (DC2)", "base": 50, "cost": 400, "level": 2, "body": "coupe",
     "blurb": "Hand-ported legend. Earned, not bought."},
    {"id": "prelude", "name": "Honda Prelude Type SH", "base": 55, "cost": 650, "level": 3, "body": "prelude",
     "blurb": "A front-wheel-drive coupe that steers its own rear end through corners."},
    {"id": "legend", "name": "Acura Legend Coupe", "base": 58, "cost": 800, "level": 3, "body": "legend",
     "blurb": "The car that started Acura. A long-hood V6 grand tourer."},
    {"id": "s2000", "name": "Honda S2000", "base": 60, "cost": 900, "level": 3, "body": "roadster",
     "blurb": "9,000 rpm. Roof down, deadlines done."},
    {"id": "integra_s", "name": "Acura Integra Type S", "base": 66, "cost": 1400, "level": 4, "body": "integra_s",
     "blurb": "The Integra name, back with a turbo and three pedals."},
    {"id": "ctr", "name": "Honda Civic Type R (FL5)", "base": 72, "cost": 1800, "level": 4, "body": "hatch",
     "blurb": "The wing says it all."},
    {"id": "tlx_s", "name": "Acura TLX Type S", "base": 78, "cost": 2600, "level": 5, "body": "tlx",
     "blurb": "Turbo V6 and a rear axle that pushes you through the corner."},
    {"id": "nsx", "name": "Honda NSX (NA1)", "base": 85, "cost": 3500, "level": 5, "body": "super",
     "blurb": "The one that embarrassed Ferrari."},
    {"id": "acura_nsx", "name": "Acura NSX", "base": 94, "cost": 4800, "level": 6, "body": "super3",
     "blurb": "Three motors, one engine, zero excuses."},
    {"id": "nsx_s", "name": "Honda NSX Type S", "base": 100, "cost": 6000, "level": 7, "body": "super2",
     "blurb": "Final form of the road car."},
    {"id": "ctr_tcr", "name": "Honda Civic Type R TCR", "base": 110, "cost": 8000, "level": 8, "body": "tcr",
     "blurb": "The Type R, built for touring-car racing. Your first real race car."},
    {"id": "nsx_gt3", "name": "Honda NSX GT3 Evo", "base": 120, "cost": 10000, "level": 9, "body": "gt3",
     "blurb": "The race car. Same class as your rig — park it next to it."},
    {"id": "nsx_evo22", "name": "Acura NSX GT3 Evo22", "base": 150, "cost": 18000, "level": 12, "body": "gt3evo",
     "blurb": "The final evolution of the GT3 car."},
    {"id": "arx05", "name": "Acura ARX-05", "base": 170, "cost": 28000, "level": 14, "body": "proto05",
     "blurb": "A three-time endurance champion prototype. One step from the top."},
    {"id": "arx06", "name": "Acura ARX-06", "base": 190, "cost": 40000, "level": 16, "body": "proto",
     "blurb": "A prototype. The top of the ladder — the whole year's work in one car."},
]
CAR_BY_ID = {c["id"]: c for c in CARS}
SHOWROOM_PAINT = {"civic_si": ("#b3122a", 21), "integra_r": ("#f1f0ea", 11), "s2000": ("#1f4aa8", 2),
                  "ctr": ("#e7e6e1", 1), "nsx": ("#c8102e", 8), "nsx_s": ("#e8a43a", 30), "nsx_gt3": ("#f2f2ee", 30),
                  "rsx": ("#f0b323", 5), "tsx": ("#2b4a8a", 14), "integra_s": ("#2f6fb5", 23), "tlx_s": ("#b71c1c", 35),
                  "acura_nsx": ("#c9ccd1", 17), "nsx_evo22": ("#ff6a13", 93), "arx06": ("#d7263d", 6),
                  "crx": ("#c41e2a", 88), "s660": ("#f4c400", 66), "prelude": ("#1d3b6e", 97), "legend": ("#2b2d33", 91),
                  "ctr_tcr": ("#f2f2ee", 12), "arx05": ("#1a1a1a", 10)}
# what each one comes with from the factory, so the showroom shows it at its best stock spec
SHOWROOM_SPEC = {"ctr_tcr": {"tires": 4, "aero": 4, "brakes": 4, "weight": 3},
                 "arx05": {"tires": 5, "aero": 5, "brakes": 5, "weight": 5}, "civic_si": {"tires": 1}, "integra_r": {"tires": 2, "aero": 1, "brakes": 1},
                 "s2000": {"tires": 2, "brakes": 1}, "ctr": {"tires": 3, "aero": 3, "brakes": 3},
                 "nsx": {"tires": 3, "brakes": 2}, "nsx_s": {"tires": 4, "aero": 2, "brakes": 4},
                 "nsx_gt3": {"tires": 5, "aero": 5, "brakes": 5, "weight": 4},
                 "rsx": {"tires": 2, "brakes": 1}, "tsx": {"tires": 2, "brakes": 2},
                 "integra_s": {"tires": 3, "aero": 2, "brakes": 3}, "tlx_s": {"tires": 3, "brakes": 3, "aero": 1},
                 "acura_nsx": {"tires": 4, "aero": 2, "brakes": 4}, "nsx_evo22": {"tires": 5, "aero": 5, "brakes": 5, "weight": 4},
                 "arx06": {"tires": 5, "aero": 5, "brakes": 5, "weight": 5}}

TRACKS = [  # prizes stay a side-dish to real work at every stage (see race_sim in the README)
    {"name": "Parking Lot Sprint", "laps": 3, "level": 1, "fee": 8, "ai": (30, 48), "prize": [50, 25, 12]},
    {"name": "Bow River Circuit", "laps": 5, "level": 2, "fee": 20, "ai": (55, 75), "prize": [90, 45, 22]},
    {"name": "Foothills Grand Prix", "laps": 7, "level": 4, "fee": 35, "ai": (80, 105), "prize": [140, 70, 35]},
    {"name": "Rockies 6 Hours", "laps": 10, "level": 6, "fee": 50, "ai": (115, 150), "prize": [200, 100, 50]},
    {"name": "Thesis Defense Ring", "laps": 12, "level": 8, "fee": 70, "ai": (150, 200), "prize": [260, 130, 65]},
    # the Acura-era endurance tracks: wider, faster fields; sweet-spot EV stays below the Ring's (race_sim2)
    {"name": "Prairie 12 Hours", "laps": 14, "level": 11, "fee": 95, "ai": (225, 300), "prize": [230, 115, 55]},
    {"name": "Defense Day 24", "laps": 16, "level": 14, "fee": 120, "ai": (285, 380), "prize": [270, 135, 65]},
    # the long game: tiers above the old top, so there's always a faster grid to buy your way into
    {"name": "Kananaskis Night Stage", "laps": 18, "level": 17, "fee": 150, "ai": (360, 470), "prize": [320, 160, 80]},
    {"name": "Icefields Endurance", "laps": 20, "level": 20, "fee": 185, "ai": (430, 560), "prize": [380, 190, 95]},
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
        "todos": [],
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


@st.cache_resource
def _swr_store() -> dict:
    return {"data": {}, "busy": set(), "lock": threading.Lock()}  # process-wide: every session shares it


def swr(ttl: int):
    """⚡ Stale-while-revalidate for slow lookups (Notion boards, Zotero). A fresh answer is returned as is; an
    old one is returned straight away while a background thread fetches the new one for the next run. Only a
    first-ever call waits. So the page never stalls for seconds just because a 5-minute cache ran out."""
    def deco(fn):
        name = fn.__name__

        def fetch(key, args):
            S = _swr_store()
            try:
                val = fn(*args)
                with S["lock"]:
                    S["data"][key] = (time.time(), val)
            except Exception:  # noqa: BLE001 — keep serving the old answer; try again in 30 s
                with S["lock"]:
                    if key in S["data"]:
                        S["data"][key] = (time.time() - ttl + 30, S["data"][key][1])
            finally:
                S["busy"].discard(key)

        def wrapper(*args):
            S, key = _swr_store(), (name,) + args
            hit = S["data"].get(key)
            if hit is None:
                val = fn(*args)  # first time: nothing to show yet, so wait for it
                with S["lock"]:
                    S["data"][key] = (time.time(), val)
                    if len(S["data"]) > 300:  # old days' entries
                        for k_ in sorted(S["data"], key=lambda k_: S["data"][k_][0])[:100]:
                            S["data"].pop(k_, None)
                return copy.deepcopy(val)
            if time.time() - hit[0] > ttl and key not in S["busy"]:
                S["busy"].add(key)
                threading.Thread(target=fetch, args=(key, args), daemon=True).start()
            return copy.deepcopy(hit[1])

        def clear():
            S = _swr_store()
            with S["lock"]:
                for k_ in [k_ for k_ in S["data"] if k_[0] == name]:
                    S["data"].pop(k_, None)
        wrapper.clear = clear
        wrapper.__name__, wrapper.__doc__ = name, fn.__doc__
        return wrapper
    return deco


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


@swr(3600)
def _board_map(token: str, db: str) -> dict:
    return B.detect(Notion(token), db)


@swr(300)
def _board_today(token: str, db: str, day_iso: str) -> list[dict]:
    m = _board_map(token, db)
    return B.pull_day(Notion(token), m, date.fromisoformat(day_iso))


@swr(300)
def _board_range(token: str, db: str, start_iso: str, days: int) -> list[dict]:
    m = _board_map(token, db)
    return B.pull_range(Notion(token), m, date.fromisoformat(start_iso), days, tz=TZ)


@st.cache_resource
def _zotero_seen() -> dict:
    return {"v": None}  # process-wide, like the caches it guards (app.py's own globals reset on every rerun)


@swr(20)
def _zotero_version(user: str, key: str) -> str:
    try:
        return Z.library_version(user, key)
    except Exception:  # noqa: BLE001
        return ""


def zotero_fresh(zc: tuple | None) -> None:
    """Drops the cached Zotero lists as soon as anything changes in Zotero (checked at most every 20 s), so papers
    saved, moved or edited there show up right away instead of after the 10-minute cache."""
    if not zc:
        return
    v, seen = _zotero_version(zc[0], zc[1]), _zotero_seen()
    if v and v != seen["v"]:
        if seen["v"] is not None:
            _zotero_list.clear()
            _zotero_reading.clear()
            _zotero_inbox.clear()
            _zotero_topics.clear()
        seen["v"] = v


@swr(600)
def _zotero_list(user: str, key: str, coll: str) -> list[dict]:
    return Z.to_read(user, key, coll)


@swr(600)
def _zotero_reading(user: str, key: str, coll: str) -> list[dict]:
    return Z.reading_list(user, key, coll)


def zotero_cfg(state: dict) -> tuple[str, str, str] | None:
    u, k = get_secret("ZOTERO_USER_ID"), get_secret("ZOTERO_API_KEY")
    return (str(u), k, state["settings"].get("zotero_collection") or "To Read") if u and k else None


def board_cfg(state: dict) -> tuple[str, str] | None:
    db, token = state["settings"].get("board_db"), get_secret("NOTION_TOKEN")
    return (token, db) if db and token else None


def journal_cfg(state: dict) -> tuple[str, str] | None:
    """Your Notion journal database (calendar): evening entries are written into it."""
    db, token = state["settings"].get("journal_db"), get_secret("NOTION_TOKEN")
    return (token, db) if db and token else None


@swr(600)
def _journal_map(token: str, db: str) -> dict:
    return JN.detect(Notion(token), db)


def out_cfg(state: dict) -> tuple[str, str] | None:
    """The write-only output board (e.g. Fortuna)."""
    db, token = state["settings"].get("out_db"), get_secret("NOTION_TOKEN")
    return (token, db) if db and token else None


def notion_ctx() -> tuple[Notion, dict] | None:
    cfg = notion_cfg()
    return (Notion(cfg[0]), _workspace(*cfg)) if cfg else None


def _jr_sig(pm: dict) -> str:
    """What a journal entry says (not its Notion bookkeeping): if this changes, Notion gets rewritten."""
    return json.dumps({x: pm.get(x) for x in sorted(pm)
                       if not x.startswith("notion_") and x not in ("paid", "sig_for")}, sort_keys=True, default=str)


def _scrub(state: dict) -> dict:
    """Repairs: drop the journal 'sig_for' copies that once nested inside each other on every save (Nov 2026).
    If anything was removed, the cleaned copy is saved straight away."""
    hit = False
    for e in (state.get("journal") or {}).values():
        pm = (e or {}).get("pm") if isinstance(e, dict) else None
        if isinstance(pm, dict) and "sig_for" in pm:
            pm.pop("sig_for", None)
            hit = True
        if isinstance(pm, dict) and len(str(pm.get("notion_sig") or "")) > 200_000:  # a signature that swallowed
            pm.pop("notion_sig", None)  # the snowball: drop it (the day is simply rewritten to Notion once)
            hit = True
    if hit:
        try:
            st.session_state["_resave"] = True
        except Exception:  # noqa: BLE001 — called outside a session (background thread)
            pass
    return state


def _recover_save(n, ids) -> tuple[dict | None, str]:
    """Newest good copy of the game: (data, where it came from) or (None, "")."""
    import gc
    best = _mem_latest()  # the newest in-memory copy: the registry, this saver, or one from before the last update
    for o in [_saver()] + [o for o in gc.get_objects() if type(o).__name__ == "_Saver"]:
        lt = getattr(o, "latest", None)
        if lt and isinstance(lt[1], dict) and lt[1].get("tasks") is not None and (not best or lt[0] > best[0]):
            best = lt
    if best:
        return _scrub(json.loads(json.dumps(best[1], default=str))), "the copy this server had in memory (your latest)"
    cfg = notion_cfg()
    for b in (_safe(BK.listing, n, cfg[1]) or [])[:6]:
        d = _safe(BK.load, n, b["id"])
        if isinstance(d, dict) and d.get("tasks") is not None:
            return _scrub(d), f"the backup from {b['title'].split(' · ')[0]}"
    return None, ""


def _mem_latest() -> tuple[float, dict] | None:
    """The newest game state any tab/device on this server has saved or loaded (survives code updates)."""
    import sys
    return getattr(sys, "_dod_latest", None) or getattr(_saver(), "latest", None)


def _offer_latest(state: dict, saved: bool = False) -> bool:
    """Publish `state` as the newest copy. A copy that was only *loaded* can't displace one with a higher save
    number (rev): a page that loaded an older copy from Notion used to publish it and drag every other tab back."""
    import sys
    cur = _mem_latest()
    if not saved and cur and cur[1] is not state and int(cur[1].get("rev", 0)) > int(state.get("rev", 0)):
        return False
    sys._dod_latest = (time.time(), state)
    try:
        _saver().latest = sys._dod_latest
    except Exception:  # noqa: BLE001
        pass
    return True


def load_state() -> dict:
    """Notion save if configured (cached per session for SESSION_TTL), else the local file."""
    if not notion_cfg():
        return _load_local() or default_state()
    cached = st.session_state.get("_state")
    latest = _mem_latest()  # the newest game state ANY tab/device on this server has saved
    if cached is not None and latest and latest[1] is not cached and latest[0] > st.session_state.get("_state_ts", 0) \
            and int(latest[1].get("rev", 0)) >= int(cached.get("rev", 0)):
        # another tab (phone vs laptop) saved after this one last loaded: use that, never a stale copy —
        # otherwise a daily ticked on one device shows unticked on the other, and the next save there undoes it
        st.session_state["_state"], st.session_state["_state_ts"] = latest[1], time.time()
        return _scrub(latest[1])
    if cached is not None and (time.time() - st.session_state.get("_state_ts", 0) < SESSION_TTL
                               or _saver().pending()):
        return _scrub(cached)
    _saver().flush(5)  # never read Notion while our own write is still landing
    try:
        n, ids = notion_ctx()
        data = load_json(n, ids["save_page"])
    except ValueError as e:
        # The save is there but its text is damaged (a write that didn't fully land). Don't lock you out:
        # take the newest good copy — this server's memory first, then the rolling backups — and rewrite the save.
        data, src = _recover_save(n, ids)
        if data is None:
            st.error(f"Your Notion save is damaged ({e}) and no good copy was found. Restore one in "
                     "Notion: 🗄️ Backups (auto).")
            st.button("Retry")
            st.stop()
        st.session_state["_resave"] = True
        st.session_state.setdefault("flash", []).append(
            ("warning", f"🛟 Your save in Notion was damaged, so I loaded {src} and rewrote it. Check the last few "
                        "things you did."))
    except Exception as e:
        # Never fall back to a blank game here — a later save would overwrite the real one.
        st.error(f"Can't reach your Notion save right now: {e}")
        st.button("Retry")
        st.stop()
    if data is None:  # first run on Notion: carry over any local progress
        data = _load_local() or default_state()
        st.session_state["_needs_save"] = True
    if cached is not None and int(cached.get("rev", 0)) > int(data.get("rev", 0)):
        # Notion is behind this tab (a background save didn't land): keep the newer copy and send it again,
        # instead of quietly rolling your progress back to the last save that made it
        st.session_state["_state_ts"] = time.time()
        st.session_state["_resave"] = True
        return _scrub(cached)
    mem = _mem_latest()
    landing = _saver().pending() or getattr(_saver(), "dirty", False)
    if landing and mem and isinstance(mem[1], dict) and int(mem[1].get("rev", 0)) > int(data.get("rev", 0)):
        # Notion is behind because our newest save is still landing (or didn't make it): use this server's copy,
        # never the older one — otherwise your next tap saves the old copy over your newest progress
        st.session_state["_state"], st.session_state["_state_ts"] = mem[1], time.time()
        return _scrub(mem[1])
    state = _scrub(_merge(default_state(), data))
    st.session_state["_state"], st.session_state["_state_ts"] = state, time.time()
    _offer_latest(state)
    st.session_state["_fresh_load"] = True
    st.session_state["_fresh_this_run"] = True
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
    state["timer"] = {"pins": 0, "pouts": 0, "task_id": t["id"], "start": now().isoformat(), "planned": int(mins), "work": work, "brk": brk}
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
    state["timer"] = {"pins": 0, "pouts": 0, "task_id": t["id"], "start": now().isoformat(), "planned": mins, "work": work, "brk": brk}
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
    sw = _saver()
    if globals().get("PROFILE") is not None and time.time() - getattr(sw, "last_sweep", 0) > SWEEP_EVERY:  # 🧹 vestigial alerts: what ntfy holds but no
        sw.last_sweep = time.time()                                 # plan wants (moved, finished, deleted…) goes
        snap, n_ = json.loads(json.dumps(state, default=str)), now()
        threading.Thread(target=lambda: _quiet(AL.reconcile, snap, topic, n_, globals().get("PROFILE"),
                                               ghosts_only=True), daemon=True).start()
    if not (post or cancel):
        return False
    threading.Thread(target=AL.send, args=(topic, post, cancel, app_link()), daemon=True).start()
    return True


SWEEP_EVERY = 300  # seconds between sweeps of ntfy's queue from the app (the nagger also sweeps every run)


def _quiet(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:  # noqa: BLE001 — a sweep must never break the app
        return None


# ── saving: instant on screen, synced to Notion in the background ──
SYNC_FIELDS = ("sync_page", "_sig", "out_page", "out_state", "out_sig", "out_archived",
               "board_page", "board_state", "board_pushed", "board_archived", "board_src")
DASH_EVERY = 45  # seconds between dashboard refreshes


def _journal_header(state: dict, d: date, pm: dict) -> str:
    done = J.done_on(state, d, TZ)
    return (f"{J.MOODS.get(pm.get('mood'), '')} {J.MOOD_WORDS.get(pm.get('mood'), '')} · energy "
            f"{J.ENERGY.get(pm.get('energy'), '')} · ⏱️ {hmin(J.focus_on(state, d))} focused · ✅ {len(done)} done"
            + (f" ({', '.join(t['title'] for t in done[:4])})" if done else ""))


def _recap_cards(items: list, tone: str, empty: str, clip: int = 240) -> str:
    """Journal snippets as cards: a day badge, the text, and long ones folded behind 'See more' (opens in place)."""
    if not items:
        return f"<div class='dod-rc-empty'>{empty}</div>"
    out = []
    for d_, txt in items:
        txt = (txt or "").strip()
        day = f"<span class='dod-rc-day'>{d_:%a}</span>"
        body = html.escape(txt).replace("\n", "<br>")
        if len(txt) <= clip:
            out.append(f"<div class='dod-rc {tone}'>{day}<div class='dod-rc-t'>{body}</div></div>")
        else:
            cut = txt[:clip].rsplit(" ", 1)[0].rstrip(",.;: ")
            out.append(f"<details class='dod-rc {tone}'><summary>{day}<span class='dod-rc-less'>Show less ▴</span>"
                       f"<div class='dod-rc-t'>{html.escape(cut)}…<span class='dod-rc-more'>See more · "
                       f"{len(txt.split())} words</span></div></summary><div class='dod-rc-full'>{body}</div></details>")
    return "<div class='dod-rc-list'>" + "".join(out) + "</div>"


def import_notion_journal(state: dict, days: int = 7) -> list[str]:
    """Days you journaled straight into the Notion journal become app entries (they count, and pay if written
    in that day's window). Days you journaled in the app are left alone, and nothing is written back."""
    jc = journal_cfg(state)
    if not jc:
        return []
    jm = _journal_map(*jc)
    for e_ in (state.get("journal") or {}).values():  # tidy entries already imported (template helper text)
        pm_ = (e_ or {}).get("pm") if isinstance(e_, dict) else None
        if pm_ and pm_.get("notion_source"):
            JN.strip_hints(pm_)
            pm_["notion_sig"] = _jr_sig(pm_)  # still yours in Notion: never write the app's copy into that page
    rev_mood = {w: k for k, w in J.MOOD_WORDS.items()}
    known = {pm["notion_page"]: pm.get("notion_edited") for e in (state.get("journal") or {}).values()
             if isinstance(e, dict) for pm in [e.get("pm") or {}] if pm.get("notion_source") and pm.get("notion_page")}
    got = []
    for x in JN.read_entries(Notion(jc[0]), jm, now().date() - timedelta(days=days), known):
        d, cur = x["date"], J.peek(state, x["date"]).get("pm") or {}
        if cur and not cur.get("notion_source"):
            continue  # you journaled this day in the app: that entry wins
        times = [parse_dt(t_) for t_ in (x["created"], x["edited"]) if t_]
        on_time = next((t_ for t_ in times if J.journal_date(t_.astimezone(TZ)) == d), None)
        mood = rev_mood.get(x["mood_word"]) or (int(float(x["mood_word"])) if x["mood_word"][:1].isdigit() else 3)
        entry = {**x["answers"], "mood": max(1, min(5, mood)), "energy": cur.get("energy", 3)}
        paid = J.close_day(state, d, entry, (on_time or times[-1]).astimezone(TZ), bank)
        pm = J.peek(state, d)["pm"]
        pm.update(notion_page=x["page"], notion_edited=x["edited"], notion_source=True)
        pm["notion_sig"] = _jr_sig(pm)  # it came from Notion: never write the app's copy back into your page
        got.append(f"📓 Imported your Notion journal for **{d:%a %b} {d.day}**" + (f" · +{paid} 🪙" if paid else ""))
    return got


def sync_journal(n: Notion, jm: dict, state: dict) -> list[str]:
    """Evening entries → your Notion journal, one page per day (only days since you linked it)."""
    errs, since = [], state["settings"].get("journal_since", "9999")
    qs = J.questions(state)
    for k, e in (state.get("journal") or {}).items():
        pm = e.get("pm")
        if not pm or k < since:
            continue
        sig = _jr_sig(pm)
        if pm.get("notion_sig") == sig:
            continue
        try:
            d = date.fromisoformat(k)
            at_ = parse_dt(pm["at"]) if pm.get("at") else None
            pm.update(JN.write_day(n, jm, d, pm, qs, _journal_header(state, d, pm), J.MOOD_WORDS.get(pm.get("mood"), ""),
                                   when=f"{at_:%A %b} {at_.day} · {at_:%I:%M %p}".replace(" 0", " ") if at_ else ""))
            pm["notion_sig"] = sig
        except Exception as ex:  # noqa: BLE001 — never block saving
            errs.append(f"journal {k}: {ex}")
    return errs


def _notion_sync(n: Notion, ids: dict, state: dict, out_map: dict | None, app_url: str | None,
                 dash: bool, in_map: dict | None = None, jr_map: dict | None = None) -> list[str]:
    """All the Notion round-trips for one save. Mutates `state` (adds page ids) — never touches Streamlit."""
    errs = _push_tasks(n, ids, state)
    try:  # board problems never block saving
        errs += B.retract_pushed(n, state["tasks"])  # input board is read-only: undo old pushes
        if out_map:
            errs += B.sync_out(n, out_map, state["tasks"], now())
        if in_map:  # long-term goals → one card each on the Assignments calendar
            errs += B.sync_goals(n, in_map, state.get("goals", []))
        if jr_map:  # evening journal → that day's page in your Notion journal
            errs += sync_journal(n, jr_map, state)
    except Exception as e:
        errs.append(f"board: {e}")
    save_json(n, ids["save_page"], state, budget=2)  # leftover blocks (if any): a few per save, the health check does the rest
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
        self.known_goals: dict[str, dict] = {}  # goal id -> Assignments card fields
        self.known_journal: dict[str, dict] = {}  # day -> Notion journal page fields
        self.latest: tuple[float, dict] | None = None  # (when, state) of the newest save from any session
        self.dirty = False  # the last save didn't reach Notion → the next run sends it again
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

    def _apply_known_goals(self, goals: list[dict]) -> None:
        for g in goals:
            for f, v in self.known_goals.get(g["id"], {}).items():
                if v is not None:
                    g[f] = v

    def _apply_known_journal(self, journal: dict) -> None:
        for k, f in self.known_journal.items():
            pm = (journal.get(k) or {}).get("pm")
            if pm is not None:
                for fk in ("notion_page", "notion_blocks"):
                    if f.get(fk) is not None:
                        pm[fk] = f[fk]
                pm.pop("sig_for", None)
                if f.get("notion_sig") and f.get("sig_for") == _jr_sig(pm):
                    pm["notion_sig"] = f["notion_sig"]

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
            live, snapshot, (token, ids, out_map, app_url, in_map, jr_map) = job
            try:
                snap = json.loads(snapshot)
                self._apply_known(snap["tasks"])
                self._apply_known_goals(snap.get("goals", []))
                self._apply_known_journal(snap.get("journal", {}))
                dash = time.time() - self.last_dash > DASH_EVERY
                errs = _notion_sync(Notion(token), ids, snap, out_map, app_url, dash, in_map, jr_map)
                if dash:
                    self.last_dash = time.time()
                with self.lock:
                    for t in snap["tasks"]:
                        self.known[t["id"]] = {f: t.get(f) for f in SYNC_FIELDS}
                    for g in snap.get("goals", []):
                        self.known_goals[g["id"]] = {f: g.get(f) for f in B.GOAL_FIELDS}
                    for k_, e_ in (snap.get("journal") or {}).items():
                        pm_ = e_.get("pm") or {}
                        if pm_.get("notion_page"):
                            self.known_journal[k_] = {
                                "notion_page": pm_["notion_page"], "notion_blocks": pm_.get("notion_blocks"),
                                "notion_sig": pm_.get("notion_sig"),
                                "sig_for": _jr_sig(pm_)}
                    self._apply_known_journal(live.get("journal", {}))
                    self._apply_known(live.get("tasks", []))  # hand the new ids back to the live game
                    self._apply_known_goals(live.get("goals", []))
                    self.errors += errs
                    self.last_ok = time.time()
                    self.dirty = False
            except Exception as e:  # noqa: BLE001
                with self.lock:
                    self.errors.append(f"save: {e}")
                    self.dirty = True
            finally:
                with self.lock:
                    self.busy = False
                if self.job:
                    self.ev.set()


# The saver lives across reruns (one per server). Key it on the class's own code: when an update changes how
# saving works, a NEW saver starts instead of the old one (whose thread still runs the old code) being handed
# jobs it can't read, which made saves fail and later reloads roll your progress back.
_SAVER_V = hashlib.md5(b"".join(getattr(_Saver, f).__code__.co_code for f in
                                ("__init__", "_run", "_apply_known", "_apply_known_goals", "_apply_known_journal"))
                       ).hexdigest()[:12]


@st.cache_resource(show_spinner=False)
def _saver_for(version: str) -> _Saver:
    import gc
    for o in gc.get_objects():  # savers from before this update: no more writes, and no stale journal ids to re-apply
        if type(o).__name__ == "_Saver" and hasattr(o, "lock"):
            try:
                with o.lock:
                    o.job = None
                    o.known_journal = {}
            except Exception:  # noqa: BLE001
                pass
    return _Saver()


def _saver() -> _Saver:
    return _saver_for(_SAVER_V)


def needs_settle(state: dict, n_: datetime) -> bool:
    """Is this run about to charge or settle anything (a past day, a missed deadline, an expired hold)?"""
    y = n_.date() - timedelta(days=1)
    since = state.get("daily_since")
    if since and since <= y.isoformat() and not (state.get("days", {}).get(y.isoformat()) or {}).get("settled"):
        return True
    if DL.habits(state) and (state.get("habits_settled") or "") < y.isoformat():
        return True
    grace = timedelta(minutes=state["settings"].get("grace_minutes", 30))
    if any(t["status"] == "open" and n_ > parse_dt(t["deadline"]) + grace for t in state.get("tasks", [])):
        return True
    return any(parse_dt(h["until"]) <= n_ for h in state.get("held", []))


def _backup_async(state: dict, label: str) -> None:
    cfg = notion_cfg()
    if not cfg:
        return
    snap = json.dumps(state, default=str)
    threading.Thread(target=lambda: _safe(BK.snapshot, Notion(cfg[0]), cfg[1], snap, label, now()),
                     daemon=True).start()


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:  # noqa: BLE001 — a backup must never break the game
        return None


def fresh_for_settle(state: dict, fresh: bool) -> dict:
    """Before anything is charged: make sure we're settling from your newest save, not a stale copy, and take a
    backup first (once a day) so anything that goes wrong can be undone from Settings → Backup."""
    if not fresh:
        _saver().flush(15)
        try:
            n, ids = notion_ctx()
            data = load_json(n, ids["save_page"])
        except Exception:  # noqa: BLE001 — can't check: settle from what we have (penalties are capped anyway)
            data = None
        if data and int(data.get("rev", 0)) > int(state.get("rev", 0)):
            state = _merge(default_state(), data)
            st.session_state["_state"], st.session_state["_state_ts"] = state, time.time()
            _offer_latest(state)
    if state.get("backup_day") != now().date().isoformat():
        state["backup_day"] = now().date().isoformat()
        _backup_async(state, "before the day was settled")
    return state


SAVE_MAX = 3_000_000  # chars. A real save is well under 1 MB; anything near this is a bug snowballing.


def save_state(state: dict) -> None:
    _scrub(state)
    _m = _mem_latest()  # newer copy = higher rev than anything out there: a reload never trades it for an older one
    state["rev"] = max(int(state.get("rev", 0)), int(_m[1].get("rev", 0)) if _m and isinstance(_m[1], dict) else 0) + 1
    broadcast_lock(state)
    _refresh_alarms(state)
    snapshot = json.dumps(state, default=str)
    if len(snapshot) > SAVE_MAX:
        big = sorted(((k, len(json.dumps(v, default=str))) for k, v in state.items()), key=lambda kv: -kv[1])[:3]
        st.session_state.setdefault("flash", []).append(
            ("error", f"🛑 Not saving to Notion: the save ballooned to {len(snapshot):,} characters "
                      f"({', '.join(f'{k} {n:,}' for k, n in big)}). That's a bug, not your data — tell Claude."))
        return
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
    _offer_latest(state, saved=True)
    try:
        n, ids = notion_ctx()
        oc, bc, jc = out_cfg(state), board_cfg(state), journal_cfg(state)
        out_map = _board_map(*oc) if oc else None
        in_map = _board_map(*bc) if bc else None
        jr_map = _journal_map(*jc) if jc else None
        if os.getenv("DOD_SYNC_SAVE"):  # tests: do it inline
            try:
                errs = _notion_sync(n, ids, state, out_map, get_secret("APP_URL"), True, in_map, jr_map)
                _saver().dirty = False
            except Exception:
                _saver().dirty = True
                raise
            if errs:
                flash("⚠️ Some tasks didn't sync to Notion: " + "; ".join(errs[:3]), "warning")
            return
        _saver().submit(state, snapshot, (get_secret("NOTION_TOKEN"), ids, out_map, get_secret("APP_URL"), in_map,
                                          jr_map))
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


def xp_for_level(lvl: int) -> int:
    """Levels 1–10 as always (50·(L−1)²); past 10 the curve steepens so the Acura ladder is a months-long climb."""
    return 50 * (lvl - 1) ** 2 + (150 * (lvl - 10) ** 2 if lvl > 10 else 0)


def level_of(xp: int) -> int:
    lvl = int(math.sqrt(max(xp, 0) / 50)) + 1  # exact up to 10
    while lvl > 1 and xp_for_level(lvl) > xp:
        lvl -= 1
    while xp_for_level(lvl + 1) <= xp:
        lvl += 1
    return lvl


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
    _debt_episode(state)


def _debt_episode(state: dict) -> None:
    """⬛ Open / close a debt episode: when it started and how deep it got, so the climb out is visible."""
    c = state["coins"]
    if c < 0:
        if not state.get("debt_since"):
            state["debt_since"], state["debt_peak"] = now().isoformat(), c
        else:
            state["debt_peak"] = min(state.get("debt_peak", c), c)
    elif state.get("debt_since"):
        since, peak = parse_dt(state.pop("debt_since")), state.pop("debt_peak", 0)
        state["debts_cleared"] = state.get("debts_cleared", 0) + 1
        try:
            flash(f"🟢 Back in the green. Black flag lifted after {_span(now() - since)} (you were down to {peak}).",
                  celebrate=True, sound="win")
        except Exception:  # noqa: BLE001
            pass


def _md_inline(t: str) -> str:
    """Escape, then turn **bold** into <b>: for short markdown lines placed inside custom HTML."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(t))


def _span(d: timedelta) -> str:
    h = int(d.total_seconds() // 3600)
    return f"{h // 24} d {h % 24} h" if h >= 24 else f"{h} h" if h else f"{max(1, int(d.total_seconds() // 60))} min"


def car_rating(state: dict) -> float:
    car = state["car"]
    mid = car.get("model") if car.get("model") in CAR_BY_ID else CARS[0]["id"]
    eff = G.effective(car["parts"], mid)
    raw = CAR_BY_ID[mid]["base"] + sum(eff[k] * PARTS[k]["weight"] for k in PARTS)
    return raw * (0.55 + 0.45 * car["condition"] / 100)


def prestige_ready(state: dict) -> tuple[bool, int, int]:
    """(ready, cars owned, parts maxed): the whole ladder owned and every part tuned to the top."""
    car = state["car"]
    owned = sum(1 for c in CARS if c["id"] in car.get("owned", []))
    maxed = sum(1 for k in PARTS if int(car["parts"].get(k, 0)) >= MAX_PART_LEVEL)
    return owned == len(CARS) and maxed == len(PARTS), owned, maxed


def prestige_mult(state: dict) -> float:
    return 1 + PRESTIGE_STEP * min(int(state.get("prestige", 0)), PRESTIGE_MAX)


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


def last_active(state: dict) -> date:
    """The last day you did ANYTHING real: finished a task, logged a focus session, claimed a daily, or journaled."""
    days = [state.get("last_done_date") or "2000-01-01"]
    days += [x.get("date", "") for x in state.get("focus_log", [])[-50:]]
    days += [c.split("#", 1)[0] for c in state.get("habit_claims", [])[-60:]]
    days += [d for d, lg in (state.get("habit_log") or {}).items() if any(int(v or 0) > 0 for v in lg.values())]
    days += [k for k, e in (state.get("journal") or {}).items() if e.get("pm") or e.get("am")]
    today = now().date().isoformat()
    return date.fromisoformat(max(d for d in days if d and d <= today))


def process_rust(state: dict) -> str | None:
    """Loss aversion: an idle car rusts. ANY real activity holds it off (a finish, a focus session, ticking a daily,
    the journal). Rust charged under the old finishes-only rule is given back."""
    idle = (now().date() - last_active(state)).days
    due = max(0, idle - IDLE_GRACE_DAYS)
    if due < state["rust_days"]:  # you were active after all: the rust comes off
        back = RUST_PER_DAY * (state["rust_days"] - due)
        state["rust_days"] = due
        state["car"]["condition"] = min(100, state["car"]["condition"] + back)
        return f"🧽 Rust cleaned off: +{back}% condition. Your dailies and sessions count as keeping the car moving."
    new = due - state["rust_days"]
    if new <= 0:
        return None
    state["rust_days"] = due
    loss = RUST_PER_DAY * new
    state["car"]["condition"] = max(0, state["car"]["condition"] - loss)
    return (f"🟫 Nothing done in {idle} days (no finish, session, daily or journal). Your car's been sitting in the "
            f"garage rusting: −{loss}% condition. Do *anything* real to stop it.")


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
        open_parts = [k for k in PARTS if car["parts"][k] < 5]  # crates stop at L5: L6–L7 are bought, not dropped
        if not open_parts:
            bank(state, 150, "📦 Pit crate (parts maxed)")
            return "📦💎 Rare crate: crate parts maxed, so **+150 coins**"
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
    pm_ = prestige_mult(state)
    pr_ = float(t.get("prorate") or 1.0)  # timer under target as proof: pays its share
    am_ = float(t.get("time_mult") or 1.0)  # ⏳ the actual time you entered
    tb_ = TURBO_MULT if turbo_on(state, t.get("goal_id")) else 1.0  # ⚡ you invested in this goal
    total = int(round(base * (1 + early + danger) * streak_mult * ext_cut * guard * dbl * pm_ * pr_ * am_ * tb_))
    parts = [f"base {base}"] + guard_why + (["×2 ⚡ token"] if used_token else ["×2 ⚡ double"] if dbl == 2 else [])
    if early:
        parts.append(f"+{int(early * 100)}% early")
    if danger:
        parts.append("+20% danger-day")
    if state["streak"]:
        parts.append(f"×{streak_mult:.1f} streak")
    if t.get("extensions"):
        parts.append(f"−{int((1 - ext_cut) * 100)}% extensions")
    if pm_ > 1:
        parts.append(f"×{pm_:.2f} ⭐ prestige")
    if pr_ < 1:
        parts.append(f"×{pr_:.2f} timer pro-rated ({t.get('proof_timer', 0):.0f} min logged)")
    if am_ != 1:
        parts.append(f"×{am_:.2f} ⏳ took {t.get('actual_min')} of {t.get('minutes')} min")
    if tb_ > 1:
        parts.append(f"×{tb_:.2f} ⚡ turbo")
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


@st.cache_resource
def _bg_notes() -> list:
    """Problems from finish-line side jobs that ran after the page moved on; shown on your next tap."""
    return []


def _in_background(jobs: list) -> None:
    """Run (label, fn) jobs off the click path. Everything they need is resolved before this is called:
    a background thread can't read secrets or session state."""
    notes = _bg_notes()

    def run():
        for label, fn in jobs:
            try:
                r = fn()
                if isinstance(r, str) and r:
                    notes.append(f"{label}: {r}")
            except Exception as e:  # noqa: BLE001 — side jobs never break a finish
                notes.append(f"{label}: {e}")
    if jobs:
        threading.Thread(target=run, daemon=True).start()


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


def notion_mark_done(state: dict, t: dict, headers: dict | None = None) -> str | None:
    prop, typ = state["settings"].get("notion_done_prop"), t.get("notion_done_type")
    if not t.get("notion_id") or not prop or not typ:
        return None
    value = {"checkbox": {"checkbox": True}, "status": {"status": {"name": "Done"}},
             "select": {"select": {"name": "Done"}}}.get(typ)
    if not value:
        return None
    try:
        r = requests.patch(f"https://api.notion.com/v1/pages/{t['notion_id']}", headers=headers or notion_headers(),
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
    return float(t.get("focus_min") or 0), float(max(PRORATE_MIN, round(0.8 * (t.get("minutes") or 30))))


def pay_stages(state: dict) -> list[str]:
    """🧩 Cleared stages pay their bonus (once)."""
    msgs = []
    for g, n, bonus in R.settle(state["goals"], state["tasks"]):
        bank(state, bonus, f"🧩 Stage cleared: {n['title']}")
        msgs.append(f"🧩 **Stage cleared: {n['title']}** (+{bonus}) on the road to *{g['title']}*.")
    return msgs


def _proof_touch(k: str) -> None:
    """You're filling in this proof form: keep its panel open on every redraw."""
    st.session_state["proof_open"] = k


def proof_open(key: str) -> bool:
    return st.session_state.get("proof_open") == key


def fold(k: str, label: str, default: bool = True, card: bool = False):
    """A collapsible section that remembers whether you left it open or closed (saved with your data, so it
    sticks across reloads and devices). card=True styles it as one of the big section cards."""
    wk = ("card_" if card else "fold_") + k
    folds = state.setdefault("folds", {})
    cur = st.session_state.get(wk)
    if isinstance(cur, bool) and folds.get(k, default) != cur:
        folds[k] = cur  # you just opened/closed it
        save_state(state)
    # always hand Streamlit the state it's already in: a changed `expanded` would snap it back
    return st.expander(label, expanded=folds.get(k, default), key=wk, on_change="rerun")


def _open(e) -> bool:
    """Is this fold open? Collapsed sections aren't built at all: opening one reruns and fills it in."""
    return bool(os.getenv("DOD_ALL_TABS")) or getattr(e, "open", None) is not False


def togo_label(label: str, key: str, default) -> str:
    """A date box's label with its days to go, so the count stays in view while the calendar is open."""
    d_ = st.session_state.get(key, default)
    return f"{label} · {R.days_to_go(d_, now().date())}" if isinstance(d_, date) else label


def _toggle_fold(state: dict, k: str, default: bool = True) -> None:
    """A fold button that isn't an expander (for cards that hold expanders themselves). Remembered like fold()."""
    folds = state.setdefault("folds", {})
    folds[k] = not folds.get(k, default)
    save_state(state)


def _when(d: datetime) -> str:
    """A due time that doesn't tick: 'today 6:30 PM', 'Sat 11:59 PM'."""
    day = "today" if d.date() == now().date() else "tomorrow" if d.date() == now().date() + timedelta(days=1) \
        else f"{d:%a}"
    return f"{day} {d:%I:%M %p}".replace(" 0", " ")


OFFSCREEN_MAX_MIN, OFFSCREEN_PER_DAY = 45, 3  # calls, bookings, errands: short tasks, a few a day
PRORATE_MIN, PRORATE_FLOOR = 5, 0.0  # 5+ min on the timer counts as proof, paying exactly its share of the target
# ⏳ The actual time you type in scales the reward too: under your estimate pays its share (the proof shows it's done,
# so never under ×0.5); over it pays extra at a quarter rate, capped (an hour-long "15-min" task pays ×1.75, not ×4).
ACTUAL_FLOOR, ACTUAL_OVER_RATE, ACTUAL_CAP = 0.5, 0.25, 1.75


def time_mult(actual: float | None, est: float | None) -> float:
    if not actual or not est:
        return 1.0
    r = actual / est
    return round(max(ACTUAL_FLOOR, r) if r < 1 else min(ACTUAL_CAP, 1 + ACTUAL_OVER_RATE * (r - 1)), 3)


def offscreen_left(state: dict) -> int:
    today = now().date()
    used = sum(1 for x in state["tasks"] if x.get("proof_kind") == "offscreen" and x.get("completed_at")
               and parse_dt(x["completed_at"]).astimezone(TZ).date() == today)
    return max(0, OFFSCREEN_PER_DAY - used)


def render_proof_form(state: dict, t: dict, mode: str, scope: str = "") -> None:
    """mode: 'open' (normal completion) or 'redeem' (finishing a missed task for a partial refund)."""
    s = state["settings"]
    k = f"{scope}{mode}_{t['id']}"
    use_ai = s["ai_steward"] and bool(get_secret("ANTHROPIC_API_KEY"))
    fm, need = timer_proof(t)
    timer_ok = fm >= need
    partial = not timer_ok and fm >= PRORATE_MIN  # under target: still proof, but it pays its share
    pr_ = max(PRORATE_FLOOR, fm / need) if partial else 1.0
    if fm:
        dot = "#2ec4b6" if timer_ok else "#f5c518" if partial else "#5b6070"
        tail = ("— that's your proof. A file or link is optional." if timer_ok else
                f"— counts as proof on its own, paying ×{pr_:.2f} ({fm:.0f} of the {need:.0f} min the timer needs). "
                f"Attach a file or link for the full reward." if partial else
                f"— log {PRORATE_MIN - fm:.0f} more min and the timer counts as (pro-rated) proof.")
        st.markdown(f"<div class='dod-row' style='border:0;padding:2px 0 6px'><span class='dod-dot' "
                    f"style='background:{dot}'></span><div><b>⏱️ {fm:.0f} of {t.get('minutes') or 0} min on the "
                    f"focus timer</b> <span class='m'>{tail}</span></div></div>", unsafe_allow_html=True)
        if f"note_{k}" not in st.session_state:
            st.session_state[f"note_{k}"] = f"⏱️ {fm:.0f} min on the focus timer. "
    touch = {"on_change": _proof_touch, "args": (k,)}
    note = st.text_area("What did you do?", key=f"note_{k}", placeholder="Be specific — the steward reads this.", **touch)
    # 📞 real-world tasks (a call, a booking, an errand): no screenshot, but a detail you could only know by doing it
    offs, detail = False, ""
    if not timer_ok and (t.get("minutes") or 0) <= OFFSCREEN_MAX_MIN:
        left_o = offscreen_left(state)
        offs = st.toggle(f"📞 It happened off-screen: no screenshot ({left_o} of {OFFSCREEN_PER_DAY} left today)",
                         key=f"offs_{k}", disabled=not left_o,
                         help=f"For calls, bookings and errands up to {OFFSCREEN_MAX_MIN} min. Instead of a file, give "
                              f"a detail you could only know by doing it. A confirmation email or text screenshot is "
                              f"still the stronger proof if you have one.")
    if offs:
        detail = st.text_input("A detail you could only know by doing it", key=f"detail_{k}",
                               placeholder="Confirmation #, who you spoke to, the time it's booked for…", **touch)
        up, link = None, ""
    else:
        up = st.file_uploader("Proof file (photo, screenshot, PDF, code…)" + (" — optional" if timer_ok else
                              " — optional, pays in full" if partial else ""),
                              type=PROOF_TYPES, key=f"file_{k}", **touch)
        link = st.text_input("Link (optional — commit, Google Doc, Overleaf…)", key=f"link_{k}", **touch)
    actual = None
    if not timer_ok and not (partial and not up and not link.strip()):  # the timer isn't the proof: ask how long it took
        actual = st.number_input("Actual time taken (min, optional)", min_value=1, max_value=24 * 60, value=None, step=5,
                                 key=f"actual_{k}", placeholder=f"estimated {t.get('minutes') or '?'}",
                                 help=f"Scales the reward: under your estimate pays its share (never under "
                                      f"×{ACTUAL_FLOOR}); over it pays {ACTUAL_OVER_RATE:.0%} extra per extra "
                                      f"estimate, up to ×{ACTUAL_CAP}. Also trains your estimates in Log → Stats.")
        if actual and t.get("minutes"):
            st.caption(f"⏳ {actual} of {t['minutes']} min planned → pays **×{time_mult(actual, t['minutes']):.2f}**")
    g_ = next((g for g in state.get("goals", []) if g["id"] == t.get("goal_id")), None)
    pin = bool(g_) and st.checkbox(f"📝 Also pin “What did you do?” to the {g_['title'][:40]} roadmap as a note",
                                   key=f"pin_{k}", **touch) if g_ else False
    honor = True
    if use_ai:
        st.caption("🧑‍⚖️ The AI race steward will review this proof.")
    else:
        honor = st.checkbox("On my honor (and my car's paint job), this proof is real.", key=f"honor_{k}", **touch)
    if not st.button("📸 Submit proof", key=f"submit_{k}", type="primary", on_click=_proof_touch, args=(k,)):
        return

    errors, data, h = [], None, None
    if len(note.strip()) < 15:
        errors.append("Write at least a real sentence about what you did.")
    use_pr = partial and not offs and not up and not link.strip()  # the pro-rated timer is the proof
    if timer_ok or use_pr:
        pass  # logged focus time is the proof: no file or link needed
    elif offs:
        if len(detail.strip()) < 4:
            errors.append("Off-screen proof needs a checkable detail: a confirmation number, who you spoke to, or a time.")
        if not offscreen_left(state):
            errors.append(f"That's {OFFSCREEN_PER_DAY} off-screen proofs today. Attach a screenshot instead.")
    elif not up and (t.get("minutes") or 0) >= V.FILE_REQUIRED_FROM:
        errors.append(f"Tasks of {V.FILE_REQUIRED_FROM}+ min need a real file as proof (screenshot, doc, photo), "
                      f"or {need:.0f} min on the focus timer.")
    elif s["strict_proof"] and not up:
        errors.append(f"Strict mode: attach a file, or log {need:.0f} min on the focus timer "
                      f"({PRORATE_MIN}+ min counts too, pro-rated).")
    if not timer_ok and not use_pr and not offs and not up and not link.strip():
        errors.append(f"Attach a file or a link, or log {need:.0f} min on the focus timer "
                      f"({PRORATE_MIN}+ min counts too, pro-rated).")
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
                if use_pr:
                    stamp += (f"\n[The timer is under the {need:.0f} min target, so it counts as partial proof and the "
                              f"reward is pro-rated ×{pr_:.2f}. Judge whether the note describes real work.]")
                if offs:
                    stamp += f"\n[Off-screen task, no file possible. Detail given: {detail.strip()}]"
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
    if offs:
        t.update(proof_kind="offscreen", proof_detail=detail.strip()[:200])
    t.pop("prorate", None)
    if use_pr:
        t.update(prorate=round(pr_, 3), proof_timer=round(fm, 1), proof_kind="timer_partial")
    t.pop("time_mult", None)
    if actual:
        t["actual_min"] = int(actual)
        if not use_pr:  # the timer already sets the pay when it's the proof
            t["time_mult"] = time_mult(actual, t.get("minutes"))
    if pin and g_:  # the write-up becomes a sticky note on this block in the roadmap
        txt_ = re.sub(r"^⏱️ \d+ min on the focus timer\.\s*", "", note.strip()) or note.strip()
        g_.setdefault("notes", []).append({"id": uuid.uuid4().hex[:8], "text": txt_[:400], "on": "t_" + t["id"],
                                           "color": "green", "created": at.isoformat()})
    if mode == "open":
        reward, why = compute_reward(state, t, at)
        bank(state, reward, f"🏁 Done: {t['title']}")
        shield_msgs = SH.on_finish(state, at, reward, bank)
        g_ = t.pop("_guard", 1.0)
        xp_gain = max(1, round(t["xp"] * (min(1.0, g_) if g_ < 1.5 else 2) * float(t.get("prorate") or 1.0)
                                 * (1.1 if "spotter" in state.get("crew", []) else 1)  # 🔭 Mateo
                                     * float(t.get("time_mult") or 1.0)))
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
        msg += f"\n\n{crate}" + "".join(f"\n\n{m_}" for m_ in shield_msgs + pay_stages(state))
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
        refund = int(round(t["penalty"] // 2 * float(t.get("prorate") or 1.0) * float(t.get("time_mult") or 1.0)))
        bank(state, refund, f"🩹 Redeemed: {t['title']}")
        for m_ in SH.on_finish(state, at, refund, bank):
            st.session_state.setdefault("flash", []).append(("success", m_))
        state["xp"] += t["xp"] // 2
        t["status"], t["earned"] = "redeemed", refund
        for p in state["penalty_box"]:
            if p.get("task_id") == t["id"] and not p["served"]:
                p.update(served=True, served_at=now().isoformat(), how="redeemed")
        msg = f"🩹 Redeemed **{t['title']}** — +{refund} coins back, +{t['xp'] // 2} XP. Late, but done."
        msg += "".join(f"\n\n{m_}" for m_ in pay_stages(state))
        sound = "win"
    state["last_done_date"] = at.date().isoformat()
    state["rust_days"] = 0
    if verdict:
        msg += f"\n\n🧑‍⚖️ Steward: *{verdict['comment']}*"
    if level_of(state["xp"]) > old_level:
        msg += f"\n\n⬆️ **Driver level {level_of(state['xp'])}!** Check the Race tab for new tracks."
    # ⚡ The coins, XP and save are done. The rest (Zotero, ticking it off in Notion, uploading the proof file, the
    # phone buzz) are network calls that used to hold the page for seconds: they now finish in the background.
    jobs = []
    if paper_keys(t) and zotero_cfg(state):
        zc, zks = zotero_cfg(state), paper_keys(t)
        def _zot():
            for zk in zks:
                Z.mark_read(zc[0], zc[1], zk, zc[2])
            _zotero_list.clear()  # so the To Read list drops them
            _zotero_reading.clear()
        jobs.append(("Couldn't tag it read in Zotero", _zot))
        msg += f"\n\n📄 Tagging {'it' if len(zks) == 1 else f'all {len(zks)}'} **read** in Zotero."
    if t.get("notion_id") and state["settings"].get("notion_done_prop") and t.get("notion_done_type"):
        try:
            hdr, st_snap, t_snap = notion_headers(), {"settings": dict(state["settings"])}, dict(t)
            jobs.append(("Couldn't tick it off in your Notion list", lambda: notion_mark_done(st_snap, t_snap, hdr)))
        except RuntimeError as e:
            msg += f"\n\n(Couldn't tick it off in your Notion list: {e})"
    if up and t.get("sync_page") and notion_cfg():
        try:
            n_up, _ = notion_ctx()
            fname, page, utype = up.name, t["sync_page"], up.type

            def _upload():
                body, ctype = (shrink_image(data) if utype in IMAGE_MIME else (data, utype or "application/octet-stream"))
                upload_proof(n_up, page, Path(fname).stem + ".jpg" if utype in IMAGE_MIME else fname, body, ctype)
            jobs.append(("Proof file didn't upload to Notion", _upload))
        except Exception as e:
            msg += f"\n\n(Proof file didn't upload to Notion: {e})"
    save_state(state)
    # Reward hits the phone too — the buzz becomes the cue.
    plain_msg = re.sub(r"[*#]", "", msg.split("\n\n🧑‍⚖️")[0]).replace("CHECKERED FLAG\n", "")
    topic, link = get_secret("NTFY_TOPIC"), app_link()
    if topic:
        jobs.append(("Phone buzz didn't send", lambda: None if push(
            topic, "🏁 Checkered flag" if mode == "open" else "🩹 Redeemed", plain_msg.strip(),
            priority=4 if sound == "jackpot" else 3,
            tags=["checkered_flag", "moneybag"] if sound == "jackpot" else ["checkered_flag"], click=link)
            else "ntfy didn't take it"))
    _in_background(jobs)
    flash(msg, celebrate=(mode == "open"), sound=sound)
    st.rerun()


CAT_OPTS = ["auto"] + list(V.CATEGORIES)


def cat_label(k: str) -> str:
    return "✨ Auto (guess from title)" if k == "auto" else V.CATEGORIES[k]["label"]


def min_label(m: int) -> str:
    return hmin(m)


def msec(minutes: float) -> str:
    """For averages, where seconds are real: 30 min 27 s · 1 h 5 min (past an hour, seconds stop mattering)."""
    sec = int(round((minutes or 0) * 60))
    if not sec:
        return "0 min"
    if sec >= 3600:
        return hmin(sec / 60)
    m, r = divmod(sec, 60)
    return f"{r} s" if not m else f"{m} min" + (f" {r} s" if r else "")


def hmin(minutes: float) -> str:
    """A time for people, not a decimal: 45 min · 1 h · 1 h 30 min."""
    m = int(round(minutes or 0))
    h, r = divmod(m, 60)
    return f"{r} min" if not h else f"{h} h" + (f" {r} min" if r else "")


def points_guide() -> None:
    with fold("points", "💰 What's it worth? (points guide)", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            st.markdown(V.guide_markdown())


def task_form(state: dict, key: str, goal_id: str | None = None) -> None:
    fk = st.session_state.setdefault(f"_{key}_n", 0)
    # what → when → how big → (the rest is optional and tucked away)
    title = st.text_input("Task", placeholder="e.g. Draft the methods section", key=f"{key}_title{fk}")
    c1, c2 = st.columns(2)
    d = c1.date_input(togo_label("Due date", f"{key}_d{fk}", now().date() + timedelta(days=1)), value=now().date() + timedelta(days=1), min_value=now().date(), key=f"{key}_d{fk}")
    with c2:
        tm = time_wheel("Due time", dtime(23, 55), key=f"{key}_t{fk}")
    start_dt = start_picker(f"{key}_s{fk}", default=None, label="I'll start in (optional)")
    with st.form(key, clear_on_submit=True, border=False):
        mins = st.select_slider("Honest time it'll take", V.MINUTES, value=60, format_func=min_label, key=f"{key}_min")
        cp, cd = st.columns(2)
        prio_ = cp.pills("Priority", list(RK.PRIO), format_func=RK.PRIO.get, key=f"{key}_prio{fk}",
                         help=" · ".join(f"{RK.PRIO[o]}: {RK.PRIO_HELP[o]}" for o in RK.PRIO))
        diff_ = cd.pills("Difficulty", list(RK.DIFF), format_func=RK.DIFF.get, key=f"{key}_diff{fk}",
                         help=" · ".join(f"{RK.DIFF[o]}: {RK.DIFF_HELP[o]}" for o in RK.DIFF))
        gid = goal_id
        with st.expander("More: details, goal, type, consequence"):
            details = st.text_area("Details / what counts as done", height=70)
            if goal_id is None and state["goals"]:
                opts = ["(no goal)"] + [g["title"] for g in state["goals"]]
                pick = st.selectbox("Part of goal", opts)
                gid = None if pick == "(no goal)" else state["goals"][opts.index(pick) - 1]["id"]
            cat = st.selectbox("Category", CAT_OPTS, format_func=cat_label, key=f"{key}_cat")
            preset = st.selectbox("Real-world consequence if I miss it", CONSEQUENCE_PRESETS, index=1)
            custom = st.text_input("…or write your own", placeholder="Overrides the preset if filled in")
        cons = custom.strip() or ("" if preset == CONSEQUENCE_PRESETS[0] else preset)
        if st.form_submit_button("➕ Add task", type="primary", use_container_width=True):
            dl = datetime.combine(d, tm, TZ)
            if not title.strip():
                st.error("Give it a name.")
            elif dl <= now() + timedelta(minutes=5):
                st.error("Deadline has to be in the future.")
            else:
                t = make_task(title, details, dl, None, cons, gid, category=None if cat == "auto" else cat, minutes=mins)
                if start_dt:
                    t.update(scheduled=start_dt.isoformat(), scheduled_time=True)
                if prio_:
                    t["prio"] = prio_
                if diff_:
                    t["diff"] = diff_
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


TICKET_BANK_CAP = 6   # unused tickets carry over, up to this many
GP_DAY = 6            # 🏁 Sunday Grand Prix
INVITE_BANK = 1000    # 🎟️ the Invitational only calls when you're sitting on this much


def day_cap(state: dict) -> int:
    return RACE_DAY_CAP + (1 if "dj" in state.get("crew", []) else 0)  # 🎧 Kai talks the marshals into one more


def _tickets_earned(state: dict, d: date) -> int:
    iso = d.isoformat()
    finishes = sum(1 for t in daily.finished_on(state, d) if (t.get("minutes") or 0) >= TICKET_MIN_TASK)
    sessions = sum(int(float(x.get("min", 0)) // 25) for x in state.get("focus_log", []) if x.get("date") == iso)
    return finishes + sessions


def _races_on(state: dict, d: date, kinds=("race", "gp")) -> list[dict]:
    iso = d.isoformat()
    return [r for r in state.get("races", []) if r["ts"][:10] == iso and r.get("kind", "race") in kinds]


def ticket_carry(state: dict, today: date) -> int:
    """Unused tickets from the last two weeks roll forward, capped at TICKET_BANK_CAP."""
    c = 0
    for i in range(14, 0, -1):
        d = today - timedelta(days=i)
        c = min(TICKET_BANK_CAP, max(0, c + _tickets_earned(state, d) - len(_races_on(state, d))))
    return c


def race_tickets(state: dict) -> tuple[int, str]:
    """Races are earned: 1 ticket per proof-backed 30+ min finish + 1 per 25 min of timer focus. Unused tickets carry
    over (up to 6 banked). Still at most RACE_DAY_CAP regular races a day (the Sunday GP is extra)."""
    today = now().date()
    carry, earned = ticket_carry(state, today), _tickets_earned(state, today)
    used = len(_races_on(state, today))
    raced = len(_races_on(state, today, ("race",)))
    left = max(0, min(TICKET_BANK_CAP, carry + earned) - used)
    cap_ = day_cap(state)
    if raced >= cap_:
        why = f"That's {cap_} races today — the track's closed till tomorrow. Your {left} ticket(s) keep."
        return 0, why
    if not left:
        why = ("No race tickets. Finish a 30+ min task with proof, or log 25 min of focus on the timer, "
               f"to earn one. Unused tickets carry over (up to {TICKET_BANK_CAP}).")
    else:
        why = (f"🎟️ {left} race ticket{'s' if left > 1 else ''} · {carry} banked + {earned} earned today"
               f" · unused ones carry over (max {TICKET_BANK_CAP})"
               + (f" · up to {cap_ - raced} more race{'s' * (cap_ - raced != 1)} today" if left > cap_ - raced else ""))
    return left, why


def field_form(state: dict, track_name: str) -> float:
    """📈 The grid learns you. Wins (+1) and podiums (+½) at a track make its rivals faster there; off-days (−½) ease
    it back. 0–6 → rivals up to +21%. You never get to sit on a track you've mastered."""
    f = 0.0
    for r in [r for r in state.get("races", []) if r["track"] == track_name and r.get("kind", "race") != "inv"][:8]:
        f += 1 if r["pos"] == 1 else 0.5 if r["pos"] in (2, 3) else 0 if r["pos"] == "DNF" else -0.5
    return max(0.0, min(6.0, f))


def ai_range(state: dict, track: dict) -> tuple[int, int]:
    up = 1 + 0.035 * field_form(state, track["name"])
    return round(track["ai"][0] * up), round(track["ai"][1] * up)


def run_cost(state: dict, track: dict) -> int:
    """⛽ Fuel, tyres, brake pads: faster cars cost more to run, every lap."""
    car = state["car"]
    mid = car.get("model") if car.get("model") in CAR_BY_ID else CARS[0]["id"]
    rate = 1 + math.sqrt(CAR_BY_ID[mid]["cost"]) / 25
    return round(track["laps"] * rate * (0.7 if "tires" in state.get("crew", []) else 1))


def best_track(state: dict) -> int:
    """The auto-pick: the highest unlocked track you can actually win (your car inside its field), else the highest
    you can at least run with."""
    lv = level_of(state["xp"])
    ok = [i for i, t in enumerate(TRACKS) if lv >= t["level"]]
    if not ok:
        return 0
    win = [i for i in ok if track_rating(state, TRACKS[i]) >= ai_range(state, TRACKS[i])[0]]
    return win[-1] if win else ok[0]


def gp_track(state: dict) -> dict:
    """🏁 This Sunday's Grand Prix: your best track, half again as long, double the stakes."""
    t = dict(TRACKS[best_track(state)])
    t.update(name=t["name"], gp=True, laps=round(t["laps"] * 1.5), fee=t["fee"] * 2,
             prize=[round(x * 2.2) for x in t["prize"]])
    return t


def gp_open(state: dict) -> bool:
    n_ = now()
    return n_.weekday() == GP_DAY and not any(r.get("kind") == "gp" for r in _races_on(state, n_.date(), ("gp",)))


def invitational(state: dict) -> dict | None:
    """🎟️ When you're hoarding (bank > INVITE_BANK) a once-a-week invitation: a field built around YOUR pace.
    ~13% to win, ~50% podium; it costs more than it pays on average. It's for glory, and it spends."""
    n_ = now()
    if state["coins"] <= INVITE_BANK:
        return None
    wk = n_.isocalendar()[:2]
    if any(r.get("kind") == "inv" and parse_dt(r["ts"]).isocalendar()[:2] == wk for r in state.get("races", [])):
        return None
    lf = daily.level_factor(state)
    lv = level_of(state["xp"])
    base = dict([t for t in TRACKS if lv >= t["level"]][-1])  # the most prestigious track you've unlocked
    return dict(base, inv=True, fee=round(300 * lf), prize=[round(800 * lf), round(400 * lf), round(150 * lf)])


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


def _race_boosts(state: dict) -> float:
    """Rating bumps for this race: 🧪 consumables bought for it, and the 🧑‍🔧 strategist."""
    b = sum(SHOP_BOOSTS[k]["rating"] for k in state.get("boosts", []) if k in SHOP_BOOSTS)
    return b + (3 if "strategist" in state.get("crew", []) else 0)


def race_seconds(track: dict) -> int:
    return 8 + 5 * track["laps"]  # 23 s for a 3-lap sprint … 68 s for the 12-lap Ring


def simulate_race(state: dict, track: dict, kind: str = "race") -> None:
    """kind: race · gp (🏁 Sunday Grand Prix) · inv (🎟️ Invitational: a field built around your pace)."""
    car = state["car"]
    cond_before = car["condition"]
    heat_lvl = state["rival_heat"]
    boost = _race_boosts(state)
    you = {"name": f"#{car['number']} {car['name']}", "you": True,
           "rating": track_rating(state, track) + boost + random.gauss(0, 5), "color": car["color"]}
    heat = 3 * heat_lvl  # your misses literally make them faster
    lo_, hi_ = ai_range(state, track)  # 📈 …and so do your wins
    if kind == "inv":
        base_r = track_rating(state, track) + boost
        rivals = [{"name": n, "you": False, "rating": base_r + random.uniform(-6, 6) + heat + random.gauss(0, 5),
                   "color": RV.RIVAL_COLORS[i]} for i, n in enumerate(random.sample(RIVALS, 5))]
    else:
        rivals = [{"name": n, "you": False, "rating": random.uniform(lo_, hi_) + heat + random.gauss(0, 5),
                   "color": RV.RIVAL_COLORS[i]} for i, n in enumerate(random.sample(RIVALS, 5))]
    mult = sandbag(state, track) if kind != "inv" else 1.0
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
    payout = 0 if you["dnf"] else (round(track["prize"][pos - 1] * mult * (1.05 if "chief" in state.get("crew", []) else 1))
                                   if pos <= 3 else 0)
    wear = 2 + track["laps"] // 3
    if "engineer" in state.get("crew", []):
        wear = max(1, round(wear * 0.7))
    car["condition"] = max(0, car["condition"] - wear)
    state["xp"] += 5
    tag = {"gp": "🏁 Sunday GP: ", "inv": "🎟️ Invitational: "}.get(kind, "")
    if payout:
        bank(state, payout, f"🏆 P{pos} at {tag}{track['name']}")
    state["races"].insert(0, {"ts": now().isoformat(), "track": track["name"], "kind": kind,
                              "pos": "DNF" if you["dnf"] else pos, "payout": payout})
    if pos == 1 and not you["dnf"] and kind in ("gp", "inv"):
        state.setdefault("cups", []).append({"kind": kind, "track": track["name"], "date": now().date().isoformat()})
    state["boosts"] = []  # 🧪 one-race consumables are used up
    del state["races"][100:]
    save_state(state)
    winner = order[0]
    gap = (winner["dist"] - you["dist"]) / max(you["rating"], 1) * 1.7  # pseudo-seconds
    names = [html.escape(f["name"]) for f in field]
    title_ = {"gp": f"🏁 Sunday Grand Prix · {track['name']}", "inv": f"🎟️ Invitational · {track['name']}"}.get(kind, track["name"])
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
        "why": why, "title": title_, "result": res, "payout": payout,
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
        ev_date = c2.date_input(togo_label("When", "ev_date", today + timedelta(days=21)), value=today + timedelta(days=21), min_value=today + timedelta(days=1),
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
    if delta < 0 and n_ < h["target"] and DL.claimed(state, h["id"], d):
        back = DL.unclaim(state, h["id"], d, bank)
        flash(f"↩️ **{h['name']}** is under target again: claim undone, −{back} coins.", "info")
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
    fit_ = state["settings"].get("prayer_fit")
    st.caption("Today in Calgary: " + " · ".join(f"{k} {v:%I:%M}".replace(" 0", " ") for k, v in tt.items())
               + ". Reminders follow these windows; each +1 cancels that prayer's."
               + (f" 📲 Matched to your prayer app ({date.fromisoformat(fit_['on']):%b %d})." if fit_ else ""))
    with st.form(f"pr_match_{key}", border=False):
        st.markdown("**📲 Match my prayer app** · copy today's five times from the app (or mosque timetable) you "
                    "pray by. The reminders then follow it every day, seasons included.")
        cols = st.columns(5)
        typed = {n: cols[i].time_input(n, value=tt[n].time().replace(second=0, microsecond=0), step=60,
                                       key=f"pr_m_{key}_{n}") for i, n in enumerate(PR.NAMES)}
        c1, c2 = st.columns([1, 1])
        go = c1.form_submit_button("📲 Use these times", type="primary")
        reset = c2.form_submit_button("↺ Back to calculated", disabled=not fit_)
    if go:
        target = {n: datetime.combine(today, v, TZ) for n, v in typed.items()}
        state["settings"]["prayer_fit"] = PR.fit(today, TZ, target, lat=PR.settings_of(state)["lat"],
                                                 lng=PR.settings_of(state)["lng"])
        save_state(state)
        got = PR.times_for(today, TZ, **PR.settings_of(state))
        off = [n for n in PR.NAMES if abs((got[n] - target[n]).total_seconds()) > 60]
        flash("📲 Prayer times now follow your app." + (f" ({', '.join(off)} within a couple of minutes.)" if off else ""))
        st.rerun()
    if reset:
        state["settings"].pop("prayer_fit", None)
        save_state(state)
        flash("↺ Back to the calculated prayer times.")
        st.rerun()


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


def _bailed(state: dict):
    return lambda d: bool(daily.peek_day(state, d).get("bailout"))


@st.fragment
def render_dailies(state: dict) -> None:
    if st.session_state.pop("_dl_full", False):
        st.rerun(scope="app")
    today = DL.day_for(now(), _bailed(state))  # after a 🪂 bailout, that day's dailies stay open till 4 AM
    rows = DL.today_status(state, today)
    _dn = sum(r["done"] for r in rows)
    bail_ = bool(daily.peek_day(state, today).get("bailout"))
    with fold("dailies", "🔁 **Dailies**" + (f" :gray[{_dn}/{len(rows)}]" if rows else ""), card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            if rows:
                done = _dn
                stake, _ = DL.at_stake(state, today)
                if done == len(rows):
                    note = "<div style='color:#2ec4b6;font-size:.88rem'>All done today ✅</div>"
                elif bail_:
                    left_ = (DL.closes_at(today, TZ, _bailed(state)) - now()).total_seconds() / 60
                    note = (f"<div style='color:#8ab4ff;font-size:.88rem'>🪂 Bailout day"
                            + (f" ({today:%A})" if today != now().date() else "")
                            + f": open till 4 AM · <b>{hmin(max(0, left_))}</b> left. Misses cost nothing and keep "
                              "your streaks; anything you finish still counts.</div>")
                elif daily.is_rest(state, today):
                    note = ("<div style='color:#8ab4ff;font-size:.88rem'>🛌 Rest day: misses cost nothing and keep your "
                            "streaks</div>")
                elif stake:
                    note = (f"<div style='color:#ff6a5c;font-size:.88rem'>−{stake} 🪙 at midnight if "
                            "these aren't done</div>")
                else:
                    note = ("<div style='color:#8b909c;font-size:.88rem'>Day one is free: misses start "
                            "costing tomorrow</div>")
                open_ = [r for r in rows if not r["done"]]
                top_ = max(open_ or rows, key=lambda r: r["h"].get("streak") or 0)
                pctx = {"done": done, "total": len(rows), "left": len(rows) - done, "hour": now().hour,
                        "stake": stake or 0, "rest": bail_ or daily.is_rest(state, today),
                        "best": top_["h"]["name"], "best_streak": (top_["h"].get("streak") or 0) if open_ else 0}
                st.markdown(cast_say("marshal", CR.cast_line("marshal", pctx, f"{today}{now().hour}{done}"),
                                     note.replace("<div style=", "<span style=").replace("</div>", "</span>")),
                            unsafe_allow_html=True)  # 📋 Pearl watches the dailies; the plain facts sit under her line
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
            with fold("dl_manage", "⚙️ Manage dailies" if rows else
                      "🔁 Dailies — water, prayers, brushing… (low reward, big penalty)", False) as _fo:
                if _open(_fo):  # collapsed = not built (faster page, smaller download)
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


SUG_DUE_KINDS = ("d", "r", "b", "z")  # suggestions that become new tasks today (your own tasks keep their deadlines)
SUG_DUE_OPTS = {"6 PM": dtime(18, 0), "9 PM": dtime(21, 0), "Midnight": dtime(23, 59)}


def _sug_due_picker(keys: list, opts: dict, fk) -> dict:
    """🕛 Picked suggestions are due at midnight; this popover lets you give any one of them its own time."""
    out = {}
    changed = [k for k in keys if st.session_state.get(f"q_sd_{k}{fk}") not in (None, "Midnight")]
    lbl = (f"🕛 Suggestions due midnight" if not changed else f"🕛 Suggestions due midnight · {len(changed)} changed")
    with st.popover(lbl, use_container_width=False):
        st.caption("Each picked suggestion is due at midnight today. Change any one here.")
        for k in keys:
            ttl = opts[k][0].split(" · ")[0]
            v = st.pills(ttl, list(SUG_DUE_OPTS) + ["🎡"], default="Midnight", key=f"q_sd_{k}{fk}",
                         selection_mode="single") or "Midnight"
            if v == "🎡":
                out[k] = time_wheel("", dtime(23, 59), key=f"q_sdw_{k}{fk}")
            elif v != "Midnight":
                out[k] = SUG_DUE_OPTS[v]
    return out


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


def _slice_picker(state: dict, today, picked: list, opts: dict, fk) -> list:
    """⏱️ 'Put 45 min into Thesis chapter today': counts toward qualifying, the task's own deadline stays put.
    Returns the queued slices as [(task, minutes)]."""
    taken = {opts[k][1]["id"] for k in picked if k[:2] in ("t:", "g:")}
    have = {sl["tid"]: sl["min"] for sl in daily.slices(state, today)}
    cands = [t for t in sorted(state["tasks"], key=lambda t: t["deadline"]) if t["status"] == "open"
             and t["id"] not in taken and not t["title"].startswith("🚨")][:40]
    q = [x for x in st.session_state.setdefault("q_slices", []) if any(t["id"] == x[0] for t in cands)]
    st.session_state["q_slices"] = q
    by = {t["id"]: t for t in cands}
    with fold("q_slice", "⏱️ Or put time into something bigger · its deadline stays" + (f" ({len(q)})" if q else ""),
              bool(q)) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            st.caption("A slice counts toward the hour like a task, but it's done when the **focus timer** logs that much "
                       "on it today. Once locked in it can't shrink: minutes you don't log cost "
                       f"{daily.SLICE_PEN_PER_HOUR}/h (× your level) at midnight. Any real time on it saves the day from "
                       "being a zero.")
            if cands:
                c1, c2, c3 = st.columns([3, 2, 1], vertical_alignment="bottom")
                tid = c1.selectbox("Task", [t["id"] for t in cands], index=None, key=f"q_sl_t{fk}",
                                   format_func=lambda i: by[i]["title"] + f" · due {_rel_day(parse_dt(by[i]['deadline']), today)}"
                                   + (f" · ⏱️ {have[i]} min already" if i in have else ""),
                                   placeholder="Pick a task…", label_visibility="collapsed")
                mins = c2.segmented_control("Slice", daily.SLICE_LENGTHS, default=45, format_func=min_label,
                                            key=f"q_sl_m{fk}", label_visibility="collapsed")
                if c3.button("＋ Slice", key=f"q_sl_add{fk}", use_container_width=True, disabled=not (tid and mins)):
                    q = [x for x in q if x[0] != tid] + [(tid, int(mins))]
                    st.session_state["q_slices"] = q
                    st.rerun()
            else:
                st.caption("No open tasks to slice yet.")
            for i, (tid_, m_) in enumerate(q):
                c1, c2 = st.columns([6, 1], vertical_alignment="center")
                c1.markdown(f"⏱️ **{min_label(m_)}** on {html.escape(by[tid_]['title'])}")
                if c2.button("✕", key=f"q_sl_x{fk}_{i}", help="Not committed yet: remove it"):
                    st.session_state["q_slices"] = [x for x in q if x[0] != tid_]
                    st.rerun()
    return [(by[t_], m_) for t_, m_ in q]


def _q_restore(state: dict) -> None:
    if "q_pending" not in st.session_state:
        d = state.get("draft") or {}
        st.session_state["q_pending"] = ([_qi(x) for x in d.get("items", [])]
                                         if d.get("date") == now().date().isoformat() else [])
    st.session_state["q_pending"] = [_qi(x) for x in st.session_state["q_pending"]]


TIME_CHIPS = {"5m": 5, "10m": 10, "15m": 15, "30m": 30, "45m": 45, "1h": 60, "2h": 120}


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
def _q_tpl(key: str, state: dict) -> None:
    """One tap on a preset (📨 Clear inbox, 🧠 Write 300 words…) queues it for today's mission."""
    label = st.session_state.get(key)
    if not label:
        return
    _, mins, _cat = next(x for x in Q.TEMPLATES if x[0] == label)
    _q_put(label.split(" ", 1)[1], mins, state)
    st.session_state[key] = None


def render_qualify_form(state: dict) -> None:
    today = now().date()
    fk = st.session_state.setdefault("_qf_n", 0)  # bumped after a lock-in to reset every field
    # ── pick from what you already have: tap to select. Grouped by where it came from, short labels. ──
    opts, groups = {}, {"t": [], "b": [], "z": []}
    default_t = []
    for t in sorted([t for t in state["tasks"] if t["status"] == "open"
                     and not ((t.get("block") or {}).get("date", "") > today.isoformat())], key=lambda t: t["deadline"]):
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
            known_z = {k for t in state["tasks"] if t["status"] == "open" for k in paper_keys(t)}
            for p_ in [p_ for p_ in _zotero_list(*zc) if p_["key"] not in known_z][:6]:
                k = f"z:{p_['key']}"
                lab = Z.label(p_)
                opts[k] = ((lab[:52] + "…" if len(lab) > 53 else lab) + f" · {min_label(PAPER_MIN)}", p_)
                groups["z"].append(k)
        except Exception as e:
            st.caption(f"(Couldn't read Zotero: {e})")
    # 📝 to-dos (no due date) and 🗺️ roadmap blocks booked for later days: pull either into today
    for d_ in [x for x in state.get("todos", []) if not x.get("done")][:10]:
        k = f"d:{d_['id']}"
        opts[k] = (f"{d_['title'][:48]}" + (f" · {min_label(d_['minutes'])}" if d_.get("minutes") else ""), d_)
        groups.setdefault("d", []).append(k)
    gname = {g_["id"]: g_["title"] for g_ in state.get("goals", [])}
    for t in sorted((t for t in state["tasks"] if t["status"] == "open" and t.get("goal_id")
                     and (t.get("block") or {}).get("date", "") > today.isoformat()),
                    key=lambda t: t["block"]["date"])[:8]:
        k = f"g:{t['id']}"
        bd = date.fromisoformat(t["block"]["date"])
        opts[k] = (f"{t['title'][:40]} · {min_label(t['block']['minutes'])} · booked {bd:%a}", t)
        groups.setdefault("g", []).append(k)
    # 🕘 recents: things you did (or planned) on earlier days, to reuse with one tap
    open_titles = {t["title"].strip().lower() for t in state["tasks"] if t["status"] == "open"}
    seen = set()
    for t in sorted(state["tasks"], key=lambda t: t.get("completed_at") or t.get("created") or "", reverse=True):
        ttl = t["title"].strip()
        if (t["status"] in ("done", "redeemed", "failed") and ttl.lower() not in open_titles and ttl.lower() not in seen
                and not t.get("block") and not ttl.startswith(("🚨", "Work on:"))):
            seen.add(ttl.lower())
            k = f"r:{t['id']}"
            opts[k] = (f"{ttl[:48]} · {min_label(t.get('minutes') or 30)}", t)
            groups.setdefault("r", []).append(k)
        if len(groups.get("r", [])) >= 8:
            break
    picked = []
    qualified_ = daily.peek_day(state, today).get("qualified")
    heads = {"t": "Your tasks", "d": "📝 To-do", "g": "🗺️ From your roadmaps · do it today instead",
             "b": "From your board · an hour of prep on it", "z": "Reading list", "r": "🕘 Recent · do it again"}
    if any(groups.values()):
        st.markdown("<div class='dod-step'><b>1</b> Pick what you'll do today</div>", unsafe_allow_html=True)
    for g in [g_ for g_ in ("t", "d", "g", "b", "z", "r") if g_ in groups]:
        keys = groups[g]
        if keys:
            picked += st.pills(heads[g], keys, selection_mode="multi", key=f"q_pick_{g}{fk}",
                               default=default_t if g == "t" else None, format_func=lambda k: opts[k][0]) or []
    sl_new = _slice_picker(state, today, picked, opts, fk)  # ⏱️ time into something bigger, deadline untouched
    _q_restore(state)
    pending = st.session_state["q_pending"]
    queue_slot = st.container()  # drawn after the form runs, so a new entry shows without a second redraw
    # timing lives in one small popover: start + done-by, with the current choice on its label
    sk, dk = f"q_start{fk}_chip", f"q_due{fk}_chip"
    s_chip, d_chip = st.session_state.get(sk, "30m"), st.session_state.get(dk, "9 PM")
    s_lbl = ("now" if s_chip == "Now" else f"in {s_chip}" if s_chip in START_CHIPS and START_CHIPS[s_chip] else "at a set time")
    with st.popover(f"🕐 Start {s_lbl} · done by {d_chip}", use_container_width=False):
        start_dt = start_picker(f"q_start{fk}", default="30m")
        due_t = due_picker(f"q_due{fk}")
    sug = [k for k in picked if k[0] in SUG_DUE_KINDS]
    sug_t = _sug_due_picker(sug, opts, fk) if sug else {}
    st.markdown(f"<div class='dod-step'><b>{2 if any(groups.values()) else 1}</b> "
                f"{'Or add something new' if any(groups.values()) else 'What will you do today?'}</div>",
                unsafe_allow_html=True)
    # how much real work is picked: the 30-min floor shown live, instead of an error after you tap
    real = (sum((opts[k][1].get("minutes") or 60) for k in picked
                if k[:2] in ("t:", "r:") and V.counts_for_qualifying(opts[k][1]))
            + sum(60 for k in picked if k.startswith("b:")) + sum(PAPER_MIN for k in picked if k.startswith("z:"))
            + sum(_qi(x)[1] for x in pending if _qi(x)[2] != "pit") + sum(m_ for _, m_ in sl_new))
    n_sel = len(picked) + len(pending) + len(sl_new)
    need = daily.min_mission_minutes(state)
    st.pills("Quick add", [x[0] for x in Q.TEMPLATES], key=f"q_tpl{fk}", selection_mode="single",
             label_visibility="collapsed", on_change=_q_tpl, args=(f"q_tpl{fk}", state))
    with st.form(f"q_form{fk}", clear_on_submit=True, border=False, enter_to_submit=True):
        c1, c2, c3 = st.columns([0.8, 1.05, 0.3], vertical_alignment="bottom")
        txt_ = c1.text_input("New task", key=f"q_new{fk}", label_visibility="collapsed",
                             placeholder="e.g. Write 300 words of methods — Enter to add")
        min_ = c2.segmented_control("Time", list(TIME_CHIPS), default=None, key=f"q_min{fk}",
                                    label_visibility="collapsed",
                                    help="Leave it unpicked for an honest estimate (inbox/email = 10 min)")
        add_ = c3.form_submit_button("＋ Add", use_container_width=True, help="Or press Enter")
        if n_sel:
            ok_ = qualified_ or real >= need
            st.markdown(f"<div class='dod-meter {'ok' if ok_ else 'low'}'><b>{n_sel}</b> picked · "
                        f"<b>{min_label(real) if real else '0 min'}</b> of real work"
                        + ("" if qualified_ else (" ✅" if ok_ else f" · needs {need}+ (🔧 pit checks don't count)"))
                        + "</div>", unsafe_allow_html=True)
        verb = "Add" if qualified_ else "🚦 Lock in"
        go_ = st.form_submit_button(f"{verb} {n_sel} · {min_label(real)}" if n_sel and real else
                                    ("➕ Add to today" if qualified_ else "🚦 Lock it in"),
                                    type="primary", use_container_width=True, key=f"q_lock{fk}")  # stable id: the label changes
    start_t = (start_dt or now()).time()
    go_top = False
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
                   if k[:2] in ("t:", "r:", "g:") and V.counts_for_qualifying(opts[k][1]))
               + sum((opts[k][1].get("minutes") or 30) for k in picked if k.startswith("d:"))
               + sum(60 for k in picked if k.startswith("b:")) + sum(PAPER_MIN for k in picked if k.startswith("z:"))
               + sum(p_["minutes"] for p_ in parsed if V.counts_for_qualifying(p_))  # 🔧 pit checks don't count
               + sum(m_ for _, m_ in sl_new))  # ⏱️ slices count at the time you commit
    if dl <= now() + timedelta(minutes=5):  # late at night (or a time that's gone by): same time tomorrow
        dl += timedelta(days=1)
    if not parsed and not picked and not sl_new:
        st.error("Nothing to lock in yet. Type a task and press Enter (or Add), or pick one from your list.")
        return
    if minutes < daily.min_mission_minutes(state) and not daily.peek_day(state, today).get("qualified"):
        # the 30-min floor is for qualifying; once the day's locked in, additions are bonus and any size goes
        st.error(f"Too easy — {minutes} min of real work. Today's mission needs at least "
                 f"{daily.min_mission_minutes(state)}. 🔧 Pit checks (inbox, emails, calls…) don't count toward it. "
                 "Add something meatier, or put a time on it (e.g. “45m”).")
        return
    late_dl = dl if dl > now() + timedelta(minutes=5) else datetime.combine(today, dtime(23, 59), TZ)

    def sug_due(k: str) -> datetime:
        """A picked suggestion is due at midnight (11:59 PM) unless you set its own time; a time already gone → midnight."""
        d_ = datetime.combine(today, sug_t.get(k, dtime(23, 59)), TZ)
        return d_ if d_ > now() + timedelta(minutes=5) else datetime.combine(today, dtime(23, 59), TZ)
    ids = []
    for k in picked:
        kind, obj = k[0], opts[k][1]
        if kind == "t":
            ids.append(obj["id"])
        elif kind == "g":  # a roadmap block from a later day: move it to today (same start), keep any own deadline
            bk = obj["block"]
            obj.update(R.block_fields(today, bk["start"], int(bk["minutes"]), TZ))
            if obj.get("own_deadline") and parse_dt(obj["own_deadline"]) > parse_dt(obj["deadline"]):
                obj["deadline"] = obj["own_deadline"]
            ids.append(obj["id"])
        elif kind == "d":  # a to-do becomes a real task today
            t = todo_to_task(state, obj, sug_due(k))
            ids.append(t["id"])
        elif kind == "r":  # 🕘 a recent one, again: a fresh task with the same name, size and type
            t = make_task(obj["title"], obj.get("details", ""), sug_due(k), None, obj.get("consequence", ""),
                          obj.get("goal_id"), category=obj.get("category"), minutes=obj.get("minutes"))
            state["tasks"].append(t)
            ids.append(t["id"])
        elif kind == "b":
            b = obj
            if b["date"] and b["date"] > today.isoformat():  # future card → an hour of work on it today
                g = next((g for g in state["goals"] if B.clean_id(g.get("event_page") or "") == B.clean_id(b["id"])), None)
                t = make_task(f"Work on: {b['title']}", f"For {b['title']} on {date.fromisoformat(b['date']):%a %b %d} "
                              "(DECK 12 board). Proof: show what you made in the hour.", sug_due(k), None, "",
                              g["id"] if g else None, minutes=60)
            else:
                bt = None
                try:
                    bt = datetime.strptime(b["when"].upper().replace(".", ""), "%I:%M %p").time()
                    bdue = min(datetime.combine(today, bt, TZ) + timedelta(hours=2), datetime.combine(today, dtime(23, 59), TZ))
                except ValueError:
                    bdue = sug_due(k)
                if k in sug_t:
                    bdue = sug_due(k)
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
                          f"{p_['url']}", sug_due(k), None, "", category="deep", minutes=PAPER_MIN)
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
    for t_, m_ in sl_new:  # ⏱️ committed slices: locked from here on (add more any time, never shrink)
        daily.add_slice(state, today, t_, m_)
    msg = daily.lock_in(state, now(), ids, start_t.strftime("%H:%M"), bank)
    if sl_new:
        msg += (f" ⏱️ {len(sl_new)} slice{'s' * (len(sl_new) != 1)} committed: the timer finishes "
                f"{'them' if len(sl_new) > 1 else 'it'}; unlogged minutes cost at midnight.")
    st.session_state["_qf_n"] = fk + 1
    st.session_state["q_pending"] = []
    st.session_state["q_slices"] = []
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


REMOVE_REASONS = ["Duplicate of another task", "Merged into another task", "Plans changed: not needed anymore",
                  "Made by mistake", "Someone else is doing it", "Other"]
REMOVALS_PER_WEEK = 3  # free removals with a reason; past that it's Abandon (with the penalty) as before


def removals_this_week(state: dict) -> int:
    ws = now().date() - timedelta(days=now().weekday())
    return sum(1 for r in state.get("removals", []) if (r.get("at") or "")[:10] >= ws.isoformat() and not r.get("auto"))


def remove_task(state: dict, t: dict, reason: str, note: str) -> None:
    """Take an open task off the board without a penalty, with the reason on record (ledger + removals log).
    It's marked cancelled, not erased: the Notion row and Fortuna card get tidied by the normal sync."""
    t.update(status="cancelled", cancelled_at=now().isoformat(), cancel_reason=f"{reason}: {note}".strip(": "))
    t.pop("mission_day", None)
    state.setdefault("removals", []).append({"at": now().isoformat(), "title": t["title"][:80], "reason": reason,
                                             "note": note[:200]})
    del state["removals"][:-50]
    bank(state, 0, f"🗑️ Removed: {t['title'][:50]} ({reason}{': ' + note[:60] if note else ''})")


def render_remove(state: dict, t: dict, scope: str) -> None:
    left = REMOVALS_PER_WEEK - removals_this_week(state)
    with st.popover(f"🗑️ Remove with a reason · {max(0, left)} left this week", use_container_width=True):
        if left <= 0:
            st.caption(f"You've used your {REMOVALS_PER_WEEK} free removals this week. Abandon it (penalty) or finish it.")
            return
        why = st.selectbox("Why are you removing it?", REMOVE_REASONS, index=None, key=f"{scope}rmwhy_{t['id']}",
                           placeholder="Pick a reason")
        note = st.text_input("In a few words", key=f"{scope}rmnote_{t['id']}", max_chars=200,
                             placeholder="e.g. same paper as the Read: Development… task")
        ok = bool(why) and len(note.strip()) >= 8
        if not ok:
            st.caption("A reason and a short note (8+ characters) are required. No penalty; it goes in your ledger.")
        if st.button("Remove it", key=f"{scope}rm_{t['id']}", type="primary", disabled=not ok, use_container_width=True):
            remove_task(state, t, why, note.strip())
            save_state(state)
            flash(f"🗑️ Removed **{t['title'][:60]}** · {why}. No penalty ({left - 1} free removal"
                  f"{'s' * (left - 1 != 1)} left this week).")
            st.rerun()


READING_TASK = re.compile(r"\b(read|reading|paper|papers|article|articles|lit(erature)?\s*review)\b", re.I)


PAPER_MIN = 60  # minutes per paper on a reading task (flow extensions cover the rest)


def paper_keys(t: dict) -> list[str]:
    """The Zotero papers a task covers (older tasks have just one)."""
    return list(t.get("zotero_keys") or ([t["zotero_key"]] if t.get("zotero_key") else []))


def paper_label(p: dict, order: bool = True) -> str:
    """'A03 · Title — Smith et al., 2021': reading-order number first, author always shown."""
    who = ", ".join(x for x in (p.get("who"), p.get("year")) if x)
    return (f"{p['order']} · " if order and p.get("order") else "") + p["title"][:90] + (f" — {who}" if who else "")


def _pair_paper(state: dict, t: dict, widget: str, proof_key: str, papers: list[dict]) -> None:
    """Runs when you change the papers on a reading task: it takes their names and links, gets PAPER_MIN (1 h) per paper
    (the timer starts from that; flow extensions cover the rest), and finishing it marks them all read."""
    _proof_touch(proof_key)  # keep this panel open
    by = {p["key"]: p for p in papers}
    picks = [k for k in (st.session_state.get(widget) or []) if k in by]
    if picks:
        for k_, v_ in (("title_orig", t["title"]), ("details_orig", t.get("details", "")),
                       ("minutes_orig", t.get("minutes")), ("value_orig", [t.get("reward"), t.get("penalty"), t.get("xp")])):
            t.setdefault(k_, v_)
        first = by[picks[0]]
        mins = PAPER_MIN * len(picks)
        d_ = V.value(t.get("category") if t.get("category") in V.CATEGORIES else "deep", mins)
        t.update(zotero_keys=picks, zotero_key=picks[0], minutes=mins, reward=d_["reward"], penalty=d_["penalty"],
                 xp=d_["xp"], difficulty=V.size_label(mins),
                 title=f"📄 Read: {first['title'][:70]}" + (f" + {len(picks) - 1} more" if len(picks) > 1 else ""),
                 details=(t["details_orig"] + "  \n" if t["details_orig"] else "")
                 + "  \n".join(f"📄 {paper_label(by[k])}" + (f" · {by[k]['url']}" if by[k].get("url") else "") for k in picks))
        also = sorted({x["title"][:50] for x in state["tasks"] if x["status"] == "open" and x["id"] != t["id"]
                       and set(paper_keys(x)) & set(picks)})
        flash(f"📄 {len(picks)} paper{'s' * (len(picks) != 1)} · {min_label(mins)} on the timer · +{d_['reward']}. "
              "Finishing marks them read in Zotero."
              + (f" Also on: **{'**, **'.join(also)}**." if also else ""))
    else:
        for k_ in ("zotero_key", "zotero_keys"):
            t.pop(k_, None)
        if "title_orig" in t:
            t["title"] = t.pop("title_orig")
        if "details_orig" in t:
            t["details"] = t.pop("details_orig")
        if "minutes_orig" in t:
            t["minutes"] = t.pop("minutes_orig")
        if "value_orig" in t:
            t["reward"], t["penalty"], t["xp"] = t.pop("value_orig")
        flash("📄 Papers unpaired.")
    save_state(state)


def render_paper_pair(state: dict, t: dict, scope: str) -> None:
    """📄 For reading tasks: pick which papers from your Zotero reading list this one covers."""
    mine = paper_keys(t)
    if not (mine or READING_TASK.search(t.get("title_orig") or t["title"])):
        return
    zc = zotero_cfg(state)
    if not zc:
        return
    try:
        papers = _zotero_reading(*zc)
    except Exception:  # noqa: BLE001 — Zotero down: the task still works without it
        return
    taken = {k: x["title"] for x in state["tasks"] if x["status"] == "open" and x["id"] != t["id"] for k in paper_keys(x)}
    opts = [p for p in papers if p["status"] in ("unread", "reading") or p["key"] in mine]
    have = {p["key"] for p in opts}
    for k in mine:
        if k not in have:  # its paper isn't in what Zotero sent back (moved, or cached): still show it as picked
            opts.append({"key": k, "title": t["title"].replace("📄 Read: ", "").split(" + ")[0] if k == mine[0] else k,
                         "who": "", "year": "", "url": "", "status": "unread", "order": ""})
    if not opts:
        return
    opts.sort(key=lambda p: (p["title"] or "").casefold().lstrip("\"'“‘([ "))  # A→Z by title
    by = {p["key"]: p for p in opts}
    widget = f"{scope}pair_{t['id']}"
    cur = [k for k in mine if k in by]
    if st.session_state.get(widget) != cur:
        st.session_state[widget] = cur
    st.multiselect(f"📄 Which papers? · {PAPER_MIN} min each", list(by), key=widget,
                   format_func=lambda k: ("📖 " if by[k]["status"] == "reading" else "") + paper_label(by[k])
                   + (" · already a task" if k in taken else ""),
                   placeholder="Pick from your reading list", on_change=_pair_paper,
                   args=(state, t, widget, f"{scope}open_{t['id']}", opts),
                   help=f"Each paper adds {PAPER_MIN} min to this task (and its timer). It takes their names and links; "
                        "finishing it marks them all read in Zotero.")
    spares = [x for x in state["tasks"] if x["status"] == "open" and x["id"] != t["id"]
              and paper_keys(x) and set(paper_keys(x)) <= set(mine)]
    for x in spares:  # papers already covered here: drop the spare, no penalty (it's the same reading)
        if st.button(f"🗑️ Remove the spare “{x['title'][:50]}” (free: same paper)", key=f"{scope}spare_{t['id']}_{x['id']}",
                     use_container_width=True):
            _proof_touch(f"{scope}open_{t['id']}")
            t["focus_min"] = (t.get("focus_min") or 0) + (x.get("focus_min") or 0)  # keep timer minutes logged on it
            remove_task(state, x, "Duplicate of another task", f"same paper as {t['title'][:60]}")
            state["removals"][-1]["auto"] = True  # doesn't use up a weekly removal: it's provably the same paper
            save_state(state)
            flash(f"🗑️ Removed the spare **{x['title'][:60]}**. One task for this paper now.")
            st.rerun()


def render_task_row(state: dict, t: dict, scope: str = "") -> None:
    """One open task: due chip + value; opens to finish (proof), extend or abandon."""
    s = state["settings"]
    dl = parse_dt(t["deadline"])
    fm_ = t.get("focus_min") or 0
    # the label never ticks (no live countdown): a changing label can make Streamlit redraw the panel closed
    _ba = R.block_at(t, TZ)  # booked roadmap time: show when it's booked, not the end-of-day deadline
    _ch = RK.chips(t)
    with st.expander((_ch + " " if _ch else "")
                     + (f"🗺️ {t['title']} · booked {_when(_ba)}" if _ba else f"{chip(dl)} {t['title']} · due {_when(dl)}")
                     + f" · {min_label(t.get('minutes') or 30)}"
                     + f" · +{t['reward']}"
                     + (f" · ⏱️ {fm_:.0f}/{t.get('minutes') or 0}m" if fm_ else ""), key=f"exp_{scope}{t['id']}",
                     expanded=proof_open(f"{scope}open_{t['id']}")):
        st.caption(f"⏳ {fmt_left(dl - now())} left")
        render_tags(state, t, scope or "row")
        g = goal_title(state, t.get("goal_id"))
        st.markdown(
            f"**Due** {dl:%a %b %d, %I:%M %p} · **{t['difficulty']}** · +{t['reward']} 🪙 / −{t['penalty']} 🪙"
            + (f"  \n🎯 {g}" if g else "")
            + (f"  \n{t['details']}" if t.get("details") else "")
            + (f"  \n🚨 If missed: *{t['consequence']}*" if t.get("consequence") else "")
            + (f"  \n🚩 Rejected {t['rejections']}×" if t.get("rejections") else ""))
        render_paper_pair(state, t, scope)
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
        if not young:
            render_remove(state, t, scope)
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
    if stt["bailout"]:
        _lab = "🪂 **Bailed out**"
    elif stt["rest"]:
        _lab = "🛌 **Pit stop day**"
    elif not stt["qualified"]:
        _lab = "🚦 **Qualifying**" + (" :gray[optional today]" if stt["optional"] else "")
    else:
        _m = [t for t in stt["mission"] if t["status"] != "cancelled"]
        _sl = daily.slices(state, n_.date())
        _lab = (f"🏁 **Today's mission** :gray[{len(stt['mission_done']) + sum(daily.slice_done(state, x, n_.date()) for x in _sl)}"
                f"/{len(_m) + len(_sl)}]")
    with fold("live_card", _lab, card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            render_coming_up(state)
            _shield_strip(state, n_)
            if stt["bailout"]:
                b_ = stt["bailout"]
                st.markdown("### 🪂 Bailed out")
                st.caption(f"{b_['reason']} · {b_['why']}")
                st.markdown("<div class='dod-pills'><span>No zero-day</span><span>Dailies free till 4 AM</span>"
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
                    mins_left = int(left.total_seconds() // 60)
                    urgent = mins_left <= 30
                    st.markdown(
                        f"<div class='dod-mh'><div class='dod-mt'>🚦 Qualify by {stt['deadline']:%I:%M %p}</div>".replace("by 0", "by ")
                        + f"<div class='dod-mb' style='color:{'#ff6a5c' if urgent else 'var(--muted)'}'>{fmt_left(left)} left</div></div>"
                        f"<div class='dod-pills'><span>⛽ <b>+{c['qualify_fuel']}</b> fuel</span>"
                        f"<span>Miss it: the safety car picks (−{c['qualify_penalty']})</span></div>", unsafe_allow_html=True)
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
            m = mission_sorted(state, m)
            open_m = [t for t in m if t["status"] == "open"]
            sl_ = daily.slices(state, n_.date())
            sl_ok = [x for x in sl_ if daily.slice_done(state, x, n_.date())]
            left_min = sum(t.get("minutes") or 30 for t in open_m) + sum(
                max(0, x["min"] - daily.slice_logged(state, x["tid"], n_.date())) for x in sl_ if x not in sl_ok)
            segs = "".join(f"<i class='{'ok' if t['status'] in ('done', 'redeemed') else 'bad' if t['status'] != 'open' else ''}'>"
                           "</i>" for t in m) + "".join(f"<i class='{'ok' if x in sl_ok else ''}'></i>" for x in sl_)
            pills = [f"🔥 <b>{stt['day_streak']}</b>-day streak" + ("" if stt["done_today"] else " · +1 on your first finish")]
            if stt["start_at"]:
                pills.append(f"🚦 Start <b>{datetime.strptime(stt['start_at'], '%H:%M'):%I:%M %p}</b>".replace("<b>0", "<b>"))
            pills.append(f"⏱️ <b>{focus_today(state)}</b> min focused")
            st.markdown(
                f"<div class='dod-mh'><div class='dod-mb'>{len(done) + len(sl_ok)}/{len(m) + len(sl_)} done"
                + (f" · {_hm_left(left_min)} to go" if left_min > 0 else "") + "</div></div>"
                f"<div class='dod-seg'>{segs}</div>"
                "<div class='dod-pills'>" + "".join(f"<span>{x}</span>" for x in pills) + "</div>", unsafe_allow_html=True)
            tm = state.get("timer")
            render_sort_pick(state, "sort_mission")
            if st.toggle("↕ Arrange & set start times", key="arrange_on"):
                render_arrange(state, stt)
            _first = next((t for t in m if t["status"] == "open"), None)
            if _first and not tm:
                st.markdown(f"<div class='dod-start'>👉 <b>Start here:</b> {html.escape(_first['title'])}"
                            f"<span>{html.escape(RK.why_first(_first, n_))}</span></div>", unsafe_allow_html=True)
            for t in m:
                if t["status"] in ("done", "redeemed"):
                    st.markdown(f"<div class='dod-mrow ok'><span class='dod-dot'></span><div><s>{html.escape(t['title'])}</s>"
                                f" <span class='m'>+{t.get('reward', 0)} earned</span></div></div>", unsafe_allow_html=True)
                elif t["status"] == "cancelled":
                    continue
                elif t["status"] == "open":
                    dl = parse_dt(t["deadline"])
                    fm_ = t.get("focus_min") or 0
                    c1, c2 = st.container(key=f"mrow_{t['id']}").columns([6, 1], vertical_alignment="top")
                    _bk = t.get("block")
                    _lbl = (f"⏰ {datetime.strptime(_bk['start'], '%H:%M'):%I:%M %p}".replace("⏰ 0", "⏰ ")
                            + f" · {t['title']} · {min_label(t.get('minutes') or 30)} · 🗺️ {goal_title(state, t.get('goal_id'))[:28]}"
                            if _bk else (f"⏰ {datetime.strptime(t['start_set'], '%H:%M'):%I:%M %p}".replace("⏰ 0", "⏰ ")
                                         + f" · {t['title']} · {min_label(t.get('minutes') or 30)}") if t.get("start_set")
                            else f"{t['title']} · {min_label(t.get('minutes') or 30)} · {_rel_day(dl, n_.date())}")
                    _ch = RK.chips(t)
                    with c1.expander((_ch + " " if _ch else "") + _lbl + f" · +{t['reward']}"
                                     + (f" · ⏱️ {fm_:.0f}m" if fm_ else ""), key=f"exp_m_{t['id']}",
                                     expanded=proof_open(f"today_open_{t['id']}")):
                        render_tags(state, t, "m", extra=lambda t_=t: render_send_back(state, t_, f"m_{t_['id']}"))
                        render_paper_pair(state, t, "today_")
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
            for x in sl_:  # ⏱️ slices: locked in, finished by the timer
                lg_ = daily.slice_logged(state, x["tid"], n_.date())
                t_ = next((t for t in state["tasks"] if t["id"] == x["tid"]), None)
                if x in sl_ok:
                    st.markdown(f"<div class='dod-mrow ok'><span class='dod-dot'></span><div><s>⏱️ {min_label(x['min'])} on "
                                f"{html.escape(x['title'])}</s> <span class='m'>slice done</span></div></div>",
                                unsafe_allow_html=True)
                    continue
                c1, c2 = st.container(key=f"msl_{x['tid']}").columns([6, 1], vertical_alignment="center")
                pen_ = round(daily.SLICE_PEN_PER_HOUR * daily.level_factor(state) * (x["min"] - lg_) / 60)
                c1.markdown(f"⏱️ **{min_label(x['min'])}** on {html.escape(x['title'])} "
                            f"<span class='m'>· {hmin(lg_)} logged · −{pen_} if it's short at midnight</span>"
                            f"<div class='dod-seg'><i class='ok' style='flex:{max(lg_, 0.01):.2f}'></i>"
                            f"<i style='flex:{max(x['min'] - lg_, 0.01):.2f}'></i></div>", unsafe_allow_html=True)
                running = bool(tm) and tm.get("task_id") == x["tid"]
                if t_ and t_["status"] == "open" and c2.button(
                        "⏱️" if running else "▶", key=f"mslgo_{x['tid']}", use_container_width=True, disabled=bool(tm),
                        help="Running" if running else "Start the timer for the rest of this slice"):
                    mins = max(5, int(round(x["min"] - lg_)))
                    _start_timer(state, t_, mins)
                    flash(f"▶️ **{t_['title']}** — {mins} min to finish the slice. Phone face-down.", sound="win")
                    st.rerun()
            if (m or sl_) and len(done) == len(m) and len(sl_ok) == len(sl_):
                st.success("Mission complete. Anything else today is pure bonus. 🏆")
            elif not stt["done_today"] and not daily.slice_worked(state, n_.date()) and n_.hour >= 18 \
                    and n_.weekday() not in daily.WEEKEND:
                st.warning(f"⚠️ Zero finishes so far. Midnight = −{c['zero_day_penalty']} coins and your day streak dies. "
                           "Do the smallest one now.")
            _only_booked = bool(m) and all(t.get("block") for t in m)
            if _only_booked:
                st.caption("🗺️ Your booked blocks got you qualified. Anything else today? Add it below.")
            with fold("add_mission", "➕ Add to today's mission", _only_booked and n_ < stt["deadline"]) as _fo:
                if _open(_fo):  # collapsed = not built (faster page, smaller download)
                    render_qualify_form(state)


# ── 🪙 Coin sinks: race boosts · crew · dealer · turbo ──
SHOP_BOOSTS = {  # one race only; priced off the track's entry fee
    "nitro": {"label": "🧪 Nitro", "rating": 6, "k": 1.2, "why": "+6 rating for one race"},
    "setup": {"label": "🔧 Setup tune", "rating": 4, "k": 0.8, "why": "+4 rating for one race"},
}
TURBO_MULT, TURBO_DAYS = 1.25, 7
DEALER_HOURS = 48


def boost_price(k: str, track: dict) -> int:
    return max(10, round(track["fee"] * SHOP_BOOSTS[k]["k"]))


def render_boost_shop(state: dict, track: dict) -> None:
    have = state.setdefault("boosts", [])
    c = st.container(key="boost_row").columns(len(SHOP_BOOSTS))
    for col, (k, b) in zip(c, SHOP_BOOSTS.items()):
        if k in have:
            col.caption(f"✅ {b['label']} loaded")
        elif col.button(f"{b['label']} · {boost_price(k, track)} 🪙", key=f"boost_{k}", use_container_width=True,
                        help=b["why"] + " (used up in your next race)", disabled=state["coins"] < boost_price(k, track)):
            bank(state, -boost_price(k, track), f"{b['label']} for {track['name']}")
            have.append(k)
            save_state(state)
            st.rerun()


def crew_ctx(state: dict) -> dict:
    """What the crew knows about your day: they notice races, flakes, check-ins, streaks and long stints."""
    n_ = now()
    d = n_.date()
    y = d - timedelta(days=1)
    stt = daily.status(state, n_)
    att = state.get("attendance", {})
    recent = [(k, r) for k, r in att.items() if k.split("|")[1] >= y.isoformat()]
    fl = [k for k, r in recent if r.get("status") == "flaked"]
    ok_ = [k for k, r in recent if r.get("status") in ("attended", "late", "visit")]
    cname = lambda k: (CM.get(state, k.split("|")[0]) or {}).get("name", "it")  # noqa: E731
    today_r = [r for r in state.get("races", []) if r["ts"][:10] == d.isoformat()]
    last_r = today_r[0] if today_r else None
    ev, slot = None, n_.hour // 3
    tm = state.get("timer")
    if tm:
        el = PM.effective_elapsed(tm, n_.timestamp())
        ph, ph_left = PM.phase(el, tm.get("work"), tm.get("brk"), tm.get("planned") or 25)
        left = max(0.0, (tm.get("planned") or 25) - PM.work_done(el, tm.get("work"), tm.get("brk")))
        ev = ("paused" if tm.get("paused_at") else "t_break" if ph == "break" else "t_end" if left <= 5
              else "t_start" if el < 5 else "t_mid")
        slot = int(el // 4)  # a new line every few minutes while the clock runs
    elif stt.get("bailout"):
        ev = "bailout"
    elif stt.get("rest"):
        ev = "rest"
    return {"event": ev, "slot": slot, "hired": [k for k in CR.CREW if k in state.get("crew", [])],
            "name": state["settings"].get("player_name", "Driver"), "qualified": stt["qualified"],
            "focus": int(focus_today(state)), "done": len(daily.finished_on(state, d)),
            "streak": int(state.get("day_streak", 0)), "flaked": bool(fl), "flaked_what": cname(fl[0]) if fl else "",
            "attended": cname(ok_[0]) if ok_ else "", "won": bool(last_r and last_r["pos"] == 1),
            "raced": bool(last_r), "race_pos": last_r["pos"] if last_r else "", "race_track": last_r["track"] if last_r else "",
            "slices_short": n_.hour >= 17 and daily.slice_penalty(state, d)[0] > 0,
            "journaled": bool(J.peek(state, d).get("pm")), "coins": f"{state['coins']:,}", "coins_n": state["coins"],
            "zero_yday": y.weekday() not in daily.WEEKEND and not daily.finished_on(state, y)
                         and not any(x.get("date") == y.isoformat() for x in state.get("focus_log", [])),
            "hour": n_.hour, "wd": n_.weekday()}


def _crew_days(state: dict, k: str) -> int:
    since = (state.get("crew_since") or {}).get(k)
    return (now().date() - date.fromisoformat(since)).days if since else 0


def render_crew_card(state: dict) -> None:
    hired = [k for k in CR.CREW if k in state.get("crew", [])]
    with fold("crew", "🧑‍🔧 **Your crew**" + (f" :gray[{len(hired)}]" if hired else ""), True, card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            if not hired:
                st.markdown("<div class='dod-crew'>" + "".join(f"<div class='av ghost'>{CR.avatar_svg(k, 40)}</div>"
                                                               for k in CR.CREW) + "</div>", unsafe_allow_html=True)
                st.caption("Nobody in your garage yet. Hire a crew in 🔧 Garage: each brings a permanent perk, has "
                           "opinions about your day, and tells you more about themselves the longer they're with you.")
                return
            ctx = crew_ctx(state)
            mood = CR.mood(ctx)
            salt = now().date().isoformat()
            boss = state.get("principal") if state.get("principal") in hired else None
            if not boss and len(hired) > 1:
                st.caption("👑 Pick a team principal in 💬 Get to know your crew: they'll be the voice at the top.")
            for k in ([boss] + [x for x in hired if x != boss]) if boss else hired:
                c = CR.CREW[k]
                days = _crew_days(state, k)
                lvl, bname, nxt = CR.bond(days)
                hearts = "❤️" * lvl if lvl else "🤍"
                st.markdown(f"<div class='dod-crew'><div class='av'>{CR.avatar_svg(k, 52, mood)}</div><div>"
                            f"<b>{'👑 ' if k == boss else ''}{c['name']}</b> <span class='r'>· "
                            f"{'Team principal · ' if k == boss else ''}{c['role']} · {hearts}</span>"
                            f"<div class='say'>“{html.escape(CR.line(k, ctx, salt))}”</div></div></div>", unsafe_allow_html=True)
            b_ = CR.banter(hired, ctx, salt + str(now().hour // 3))
            if b_:
                a, sa, b2, sb = b_
                st.markdown(f"<div class='dod-banter'><b>{CR.CREW[a]['name']}:</b> {html.escape(sa)}<br>"
                            f"<b>{CR.CREW[b2]['name']}:</b> {html.escape(sb)}</div>", unsafe_allow_html=True)
            with fold("crew_know", "💬 Get to know your crew", False) as _fo:
                if _open(_fo):  # collapsed = not built (faster page, smaller download)
                    for k in hired:
                        c = CR.CREW[k]
                        days = _crew_days(state, k)
                        lvl, bname, nxt = CR.bond(days)
                        st.markdown(f"<div class='dod-crew'><div class='av'>{CR.avatar_svg(k, 44)}</div><div><b>{c['name']}</b> "
                                    f"<span class='r'>· {c['role']} · bond: <b>{bname}</b> ({days} day{'s' * (days != 1)})"
                                    + (f" · next in {nxt} days" if nxt else "") + "</span>"
                                    f"<div class='say'>{html.escape(c['bio'])}</div></div></div>", unsafe_allow_html=True)
                        st.caption(f"Quirk: {c['quirk']} · Likes: {c['likes']} · Always says: “{c['catch']}”")
                        if state.get("principal") == k:
                            st.caption(f"👑 {c['name']} is your team principal: the voice at the top of the app.")
                        elif st.button(f"👑 Make {c['name']} team principal", key=f"boss_{k}"):
                            state["principal"] = k
                            save_state(state)
                            flash(f"👑 **{c['name']}** is your team principal. “{c['catch']}”", sound="win")
                            st.rerun(scope="app")
                        told = CR.stories(k, days, hired)
                        for t_ in told:
                            st.markdown(f"<div class='dod-banter'>“{html.escape(t_)}”</div>", unsafe_allow_html=True)
                        _all = len(CR.stories(k, 10 ** 6, hired))
                        if len(told) < _all:
                            st.caption(f"🔒 {_all - len(told)} more stor{'ies' if _all - len(told) > 1 else 'y'} "
                                       f"as you two get closer.")


def cast_say(who: str, line: str, sub: str = "", tone: str = "") -> str:
    """A regular (not hired crew) saying something: face, name, one line, optional plain-facts footnote."""
    c = CR.CAST[who]
    return (f"<div class='dod-cast {tone}'><div class='av'>{CR.avatar_svg(who, 40)}</div><div>"
            f"<b>{html.escape(c['name'])}</b> <span class='r'>{c['role']}</span>"
            f"<div class='q'>{html.escape(line)}</div>" + (f"<div class='f'>{sub}</div>" if sub else "") + "</div></div>")


def crew_strip_html(state: dict) -> str:
    """🧑‍🔧 Your crew in the header on every tab: their faces, and one of them talking (rotates through the day)."""
    hired = [k for k in CR.CREW if k in state.get("crew", [])]
    if not hired:
        return ("<div class='dod-crewbar ghost'>" + "".join(f"<span class='f'>{CR.avatar_svg(k, 26)}</span>"
                                                           for k in list(CR.CREW)[:3])
                + "<span class='say'>No crew yet: hire one in 🔧 Garage</span></div>")
    try:
        ctx = crew_ctx(state)
        mood = CR.mood(ctx)
        n_ = now()
        boss = state.get("principal") if state.get("principal") in hired else None
        who = boss or hired[(ctx.get("slot", 0) + n_.hour // 2 + n_.timetuple().tm_yday) % len(hired)]
        said = CR.line(who, ctx, n_.date().isoformat())
    except Exception:  # noqa: BLE001 — the header must never break the page
        return ""
    order_ = ([who] + [k for k in hired if k != who]) if boss else hired
    faces = "".join(f"<span class='f{' on' if k == who else ''}{' boss' if k == boss else ''}' "
                    f"title='{CR.CREW[k]['name']} · {CR.CREW[k]['role']}'>{CR.avatar_svg(k, 34 if k == boss else 30, mood)}</span>"
                    for k in order_)
    tag = "👑 " if boss else ""
    return (f"<div class='dod-crewbar{' has-boss' if boss else ''}'><span class='faces'>{faces}</span><span class='say'>"
            f"<b>{tag}{CR.CREW[who]['name']}:</b> {html.escape(said)}</span></div>")


def render_crew_hire(state: dict) -> None:
    crew = state.setdefault("crew", [])
    with fold("crew_hire", f"🧑‍🔧 Crew — {len(crew)}/{len(CR.CREW)} hired", len(crew) < len(CR.CREW)) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            st.caption("Hire once, keep forever. Each brings a permanent perk and shows up on Today.")
            cols = st.columns(2)
            for i, (k, c) in enumerate(CR.CREW.items()):
                with cols[i % 2], st.container(border=True, key=f"crew_{k}"):
                    st.markdown(f"<div class='dod-crew'><div class='av{'' if k in crew else ' ghost'}'>{CR.avatar_svg(k, 56)}</div>"
                                f"<div><b>{c['name']}</b> <span class='r'>· {c['role']}</span>"
                                f"<div class='say'><b>{c['perk']}</b></div></div></div>", unsafe_allow_html=True)
                    st.caption(c["bio"])
                    price = dealer_price(state, "crew", k, c["price"])
                    if k in crew:
                        st.caption("✅ On the team")
                    elif st.button(f"Hire · {price:,} 🪙", key=f"hire_{k}", use_container_width=True,
                                   disabled=state["coins"] < price, type="primary"):
                        bank(state, -price, f"🧑‍🔧 Hired {c['name']} ({c['role']})")
                        crew.append(k)
                        state.setdefault("crew_since", {})[k] = now().date().isoformat()
                        _dealer_sold(state, "crew", k)
                        save_state(state)
                        flash(f"🧑‍🔧 **{c['name']}** joined the crew: {c['perk']}.", celebrate=True, sound="jackpot")
                        st.rerun()


def _dealer_window() -> int:
    return int(now().timestamp() // (DEALER_HOURS * 3600))


def _dealer_pool(state: dict) -> list[dict]:
    """Things the dealer can put on offer for you right now."""
    lv = level_of(state["xp"])
    car = state["car"]
    out = []
    for m in CARS:
        if m["id"] not in car.get("owned", []) and lv >= m["level"] and m["cost"]:
            out.append({"kind": "car", "id": m["id"], "name": m["name"], "price": m["cost"], "off": 0.2})
    for k, c in CR.CREW.items():
        if k not in state.get("crew", []):
            out.append({"kind": "crew", "id": k, "name": f"{c['name']}, {c['role']}", "price": c["price"], "off": 0.15})
    for k, (name, _a, _o, cost, need, _b) in THEMES.items():
        if k not in state.get("themes_owned", []) and lv >= need and cost:
            out.append({"kind": "theme", "id": k, "name": f"{name} paint", "price": cost, "off": 0.3})
    return out


def dealer_offer(state: dict) -> dict | None:
    """🛒 While you're sitting on more than INVITE_BANK, one rotating deal every 48 h."""
    if state["coins"] <= INVITE_BANK:
        return None
    w = _dealer_window()
    if (state.get("dealer") or {}).get("sold") == w:
        return None
    pool = _dealer_pool(state)
    if not pool:
        return None
    o = dict(pool[int(hashlib.sha1(str(w).encode()).hexdigest(), 16) % len(pool)])
    o["deal"] = round(o["price"] * (1 - o["off"]))
    o["ends"] = datetime.fromtimestamp((w + 1) * DEALER_HOURS * 3600, TZ)
    return o


def art_price(state: dict, full: int) -> int:
    return round(full * (0.75 if "artist" in state.get("crew", []) else 1))  # 🎨 Yuki does it at cost


def dealer_price(state: dict, kind: str, id_: str, full: int) -> int:
    o = dealer_offer(state)
    if kind == "theme":
        full = art_price(state, full)
    return o["deal"] if o and o["kind"] == kind and o["id"] == id_ else full


def _dealer_sold(state: dict, kind: str, id_: str) -> None:
    o = dealer_offer(state)
    if o and o["kind"] == kind and o["id"] == id_:
        state["dealer"] = {"sold": _dealer_window()}


def render_dealer(state: dict) -> None:
    o = dealer_offer(state)
    left = o["ends"] - now()
    with st.container(border=True, key="dealer_card"):
        st.markdown(f"**🛒 Dealer's offer** · {hmin(left.total_seconds() / 60)} left")
        st.markdown(f"{o['name']}: ~~{o['price']:,}~~ **{o['deal']:,} 🪙** ({int(o['off'] * 100)}% off)")
        st.caption("You're sitting on a lot of coins. Coins in the bank don't make the car faster.")
        if st.button(f"Buy · {o['deal']:,} 🪙", key="dealer_buy", use_container_width=True, type="primary"):
            bank(state, -o["deal"], f"🛒 Dealer: {o['name']}")
            if o["kind"] == "car":
                state["car"].setdefault("owned", ["civic_si"]).append(o["id"])
                state["car"]["model"] = o["id"]
            elif o["kind"] == "crew":
                state.setdefault("crew", []).append(o["id"])
                state.setdefault("crew_since", {})[o["id"]] = now().date().isoformat()
            elif o["kind"] == "theme":
                state.setdefault("themes_owned", ["phoenix"]).append(o["id"])
                state["ui_theme"] = o["id"]
            state["dealer"] = {"sold": _dealer_window()}
            save_state(state)
            flash(f"🛒 **{o['name']}** for {o['deal']:,}. Good deal.", celebrate=True, sound="jackpot")
            st.rerun()


def turbo_on(state: dict, gid: str | None) -> bool:
    until = (state.get("turbo") or {}).get(gid) if gid else None
    return bool(until) and now() < datetime.fromisoformat(until)


def turbo_cost(state: dict) -> int:
    return round(300 * daily.level_factor(state))


def render_turbo(state: dict, g: dict) -> None:
    """⚡ Spend coins on a goal: its tasks pay +25% for a week. The one coin sink that pays you back for working."""
    if turbo_on(state, g["id"]):
        until = datetime.fromisoformat(state["turbo"][g["id"]])
        st.caption(f"⚡ Turbo on: this goal's tasks pay ×{TURBO_MULT} until {until:%a %b} {until.day}.")
        return
    cost = turbo_cost(state)
    if st.button(f"⚡ Turbo this goal · {cost} 🪙", key=f"turbo_{g['id']}", disabled=state["coins"] < cost,
                 help=f"Every task on this goal pays ×{TURBO_MULT} for {TURBO_DAYS} days."):
        bank(state, -cost, f"⚡ Turbo: {g['title']}")
        state.setdefault("turbo", {})[g["id"]] = (now() + timedelta(days=TURBO_DAYS)).isoformat()
        save_state(state)
        flash(f"⚡ **{g['title']}** is turbocharged: ×{TURBO_MULT} on its tasks for {TURBO_DAYS} days. Go use it.",
              sound="win")
        st.rerun()


# ── 📍 Commitments: showing up ──
_GEO = components.declare_component("geo", path=str(Path(__file__).parent / "components" / "geo"))


def _geo(label: str, key: str, alt: bool = False) -> dict | None:
    """One tap = one location fix. Returns the fix (or {err}) once per tap, else None."""
    v = _GEO(label=label, alt=alt, key=key, default=None)
    if v and v.get("t") != st.session_state.get(f"_seen_{key}"):
        st.session_state[f"_seen_{key}"] = v.get("t")
        return v
    return None


def _cm_when(c: dict, st_: datetime) -> str:
    d = st_.date()
    day = "Today" if d == now().date() else "Tomorrow" if d == now().date() + timedelta(days=1) else f"{d:%a %b} {d.day}"
    return f"{day} {st_:%I:%M %p}".replace(" 0", " ")


def _cm_photo(state: dict, c: dict, key: str) -> bool:
    """📷 Fallback proof when location isn't possible. Returns True once a new photo is accepted."""
    with st.popover("📷 Use a photo instead", use_container_width=True):
        up = st.file_uploader("A photo from there", type=["jpg", "jpeg", "png", "heic", "webp"], key=f"{key}_up")
        if st.button("Check in with this photo", key=f"{key}_go", disabled=not up):
            h = hashlib.sha256(up.getvalue()).hexdigest()
            if h in state["proof_hashes"]:
                st.error("That photo's already been used as proof.")
                return False
            state["proof_hashes"].append(h)
            return True
    return False


def _cm_done(ok: bool, msg: str) -> None:
    if ok:
        save_state(state)
        flash(msg, sound="win")
        st.rerun(scope="app")
    else:
        st.error(msg)


def render_commitments(state: dict) -> None:
    n_ = now()
    lf = daily.level_factor(state)
    cs = CM.items(state)
    soon = [(c, t) for c, t in CM.upcoming(state, n_, 7)]
    today_ = [(c, t) for c, t in soon if t.date() == n_.date()]
    quotas = [c for c in cs if c["kind"] == "quota"]
    shown = [(c, t) for c, t in soon if t.date() <= n_.date() + timedelta(days=1)]
    done_today = sum(1 for c in cs if (CM.rec(state, c["id"], n_.date()) or {}).get("status") in ("attended", "late", "visit"))
    label = "📍 **Commitments**" + (f" :gray[{done_today}/{len(today_) + sum(1 for q in quotas if not q.get('days') or n_.weekday() in q['days'])} today]"
                                     if today_ or quotas else "")
    with fold("commitments", label, True, card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            if not cs:
                st.caption("Things you've said you'll show up for: classes, coaching, volunteering, the office 3× a week, "
                           "a club event. Check in when you get there; a no-show without notice costs.")
            for c, t in shown:
                r = CM.rec(state, c["id"], t.date()) or {}
                opens, on_time, end = CM.window(c, t)
                fire = f" · 🔥 {c['streak']}" if c.get("streak") else ""
                head = f"{C_STAKE_DOT[c['stakes']]} **{html.escape(c['name'])}** · {_cm_when(c, t)}{fire}"
                with st.container(border=True, key=f"cm_{c['id']}_{t.date()}"):
                    stt_ = r.get("status")
                    if stt_ in ("attended", "late"):
                        st.markdown(head + f"  \n✅ {'On time' if stt_ == 'attended' else 'Late'} · +{r.get('paid', 0)}"
                                    + (" · 📷" if r.get("how") == "photo" else f" · 📍 {r['dist']} m" if r.get("dist") is not None else ""))
                        continue
                    if stt_ == "cancelled":
                        st.markdown(head + f"  \n🚫 Cancelled: {html.escape(r.get('reason', ''))}"
                                    + (f" · −{r['cost']}" if r.get("cost") else " · free"))
                        continue
                    st.markdown(head)
                    if t.date() == n_.date() and opens <= n_ <= end:
                        late = n_ > on_time
                        st.caption(("⏰ Late now: half pay." if late else
                                    f"Check-in is open · on time until {on_time:%I:%M %p}".replace(" 0", " ")))
                        fix = _geo("📍 I'm here" + (" (late)" if late else ""), f"cmgeo_{c['id']}_{t.date()}")
                        if fix:
                            ok, how, dist = CM.verify(c, fix if not fix.get("err") else None, False)
                            if ok:
                                _cm_done(*CM.check_in(state, c, n_, how, dist, bank, lf))
                            else:
                                st.warning(f"Not verified: {how}.")
                        if _cm_photo(state, c, f"cmph_{c['id']}_{t.date()}"):
                            _cm_done(*CM.check_in(state, c, n_, "photo", None, bank, lf))
                    else:
                        pen = round(CM.STAKES[c["stakes"]]["flake"] * lf)
                        st.caption(f"Check-in opens {opens:%I:%M %p}".replace(" 0", " ")
                                   + (f" · 🌱 warm-up: counts from {CM.counts_from(c):%a %b} {CM.counts_from(c).day}"
                                      if CM.warming_up(c, t.date()) else
                                      f" · no-show without notice: −{pen}" if pen else " · bonus only"))
                        if True:  # cancelling is always possible (and free 3+ h ahead with a reason)
                            with st.popover("🚫 Can't make it", use_container_width=False):
                                free_ = (t - n_).total_seconds() / 3600 >= CM.CANCEL_AHEAD_H
                                st.caption("Free with a reason (3 a month)." if free_ else
                                           f"Under {CM.CANCEL_AHEAD_H} h out: costs half a flake. Still better than a no-show.")
                                why = st.text_input("Why", key=f"cmwhy_{c['id']}_{t.date()}", placeholder="Class cancelled · sick · …")
                                if st.button("Cancel this one", key=f"cmcx_{c['id']}_{t.date()}"):
                                    _cm_done(*CM.cancel(state, c, t.date(), n_, why, bank, lf))
            for c in quotas:
                done, target, ws, we = CM.quota_week(state, c, n_.date())
                need, left = CM.quota_pace(state, c, n_.date())
                r = CM.rec(state, c["id"], n_.date()) or {}
                with st.container(border=True, key=f"cmq_{c['id']}"):
                    pace = ("✅ Week done" if not need else
                            f"🌱 warm-up week: counts from {CM.counts_from(c):%a %b} {CM.counts_from(c).day}"
                            if CM.warming_up(c, n_.date()) else
                            f"⚠️ {need} left, {left} day{'s' * (left != 1)} to go" if need >= left else
                            f"{need} left · {left} days to go")
                    st.markdown(f"{C_STAKE_DOT[c['stakes']]} **{html.escape(c['name'])}** · {done}/{target} this week · {pace}"
                                + (f" · 🔥 {c['streak']} wk" if c.get("streak") else "")
                                + f"<div class='dod-seg'>" + "".join(f"<i class='{'ok' if i < done else ''}'></i>" for i in range(target))
                                + "</div>", unsafe_allow_html=True)
                    today_ok = not c.get("days") or n_.weekday() in c["days"]
                    if r.get("status") == "visit":
                        st.caption(f"✅ Today counted · {r.get('stay', 0)} min")
                    elif r.get("status") == "in":
                        stayed = (n_ - datetime.fromisoformat(r["at"])).total_seconds() / 60
                        st.caption(f"📍 In since {datetime.fromisoformat(r['at']):%I:%M %p}".replace(" 0", " ")
                                   + f" · {hmin(stayed)} of {hmin(c['stay'])}")
                        if st.button("👋 Tap out", key=f"cmout_{c['id']}", disabled=stayed < c["stay"],
                                     help=None if stayed >= c["stay"] else f"Counts after {hmin(c['stay'])}"):
                            _cm_done(*CM.check_out(state, c, n_, bank, lf))
                    elif today_ok and need:
                        fix = _geo("📍 I'm here", f"cmqgeo_{c['id']}_{n_.date()}")
                        if fix:
                            ok, how, dist = CM.verify(c, fix if not fix.get("err") else None, False)
                            if ok:
                                _cm_done(*CM.check_in(state, c, n_, how, dist, bank, lf))
                            else:
                                st.warning(f"Not verified: {how}.")
                        if _cm_photo(state, c, f"cmqph_{c['id']}_{n_.date()}"):
                            _cm_done(*CM.check_in(state, c, n_, "photo", None, bank, lf))
            later = [(c, t) for c, t in soon if t.date() > n_.date() + timedelta(days=1)]
            if later:
                st.caption("Later this week: " + " · ".join(f"{c['name']} {t:%a %b} {t.day} {t:%I:%M %p}".replace(" 0", " ")
                                                             for c, t in later[:6]))
            with fold("cm_manage", "➕ Add a commitment" if not cs else "⚙️ Add & manage commitments", False) as _fo:
                if _open(_fo):  # collapsed = not built (faster page, smaller download)
                    render_commitments_manage(state)


C_STAKE_DOT = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
CM_LENGTHS = [30, 45, 60, 90, 120, 180, 240, 300, 360, 480]


def render_commitments_manage(state: dict) -> None:
    n_ = now()
    kind = st.segmented_control("Kind", list(CM.KINDS), format_func=CM.KINDS.get, default="weekly", key="cm_kind")
    kind = kind or "weekly"
    with st.form("cm_add", clear_on_submit=True, border=False):
        name = st.text_input("What", placeholder={"weekly": "🥋 Taekwondo", "quota": "🏢 Office",
                                                   "oneoff": "🎉 Club event"}[kind], key="cm_name")
        stakes = st.radio("Stakes", list(CM.STAKES), format_func=lambda k: CM.STAKES[k]["label"], horizontal=True,
                          index=0 if kind == "weekly" else 1 if kind == "quota" else 2, key="cm_stakes")
        c1, c2, c3 = st.columns(3)
        days, on, per, stay, t_, mins = [], None, 3, CM.STAY_DEFAULT, dtime(19, 0), 90
        if kind == "weekly":
            days = st.pills("Days", CM.WD, selection_mode="multi", key="cm_days")
            t_ = c1.time_input("Starts", value=dtime(19, 0), step=900, key="cm_t")
            mins = c2.selectbox("Length", CM_LENGTHS, index=3, format_func=min_label, key="cm_len")
        elif kind == "oneoff":
            on = c1.date_input("Date", value=n_.date(), min_value=n_.date(), key="cm_on")
            t_ = c2.time_input("Starts", value=dtime(19, 0), step=900, key="cm_t1")
            mins = c3.selectbox("Length", CM_LENGTHS, index=3, format_func=min_label, key="cm_len1")
        else:
            per = c1.number_input("Times a week", 1, 7, 3, key="cm_per")
            stay = c2.selectbox("Stay at least", [0, 30, 60, 120, 180, 240], index=3,
                                format_func=lambda m: "just tap in" if not m else min_label(m), key="cm_stay")
            days = st.pills("Counts on", CM.WD, selection_mode="multi", default=CM.WD[:5], key="cm_qdays")
        travel = c3.number_input("Travel (min)", 0, 120, 20, 5, help="For the 🚗 leave-now nag.",
                                 key="cm_travel") if kind != "oneoff" else 20
        if st.form_submit_button("➕ Add commitment", type="primary"):
            dsel = [CM.WD.index(x) for x in (days or [])]
            if not name.strip():
                st.error("Name it.")
            elif kind == "weekly" and not dsel:
                st.error("Pick at least one day.")
            else:
                CM.add(state, name, kind, stakes, n_, days=dsel, time=t_.strftime("%H:%M"), minutes=mins, on=on,
                       per_week=per, stay=stay, travel=travel)
                save_state(state)
                flash(f"📍 Added **{name.strip()}**. Drop a pin the first time you're there, so check-ins can be "
                      "verified by location.")
                st.rerun(scope="app")
    for c in CM.items(state):
        got, tot = CM.rate(state, c, n_.date())
        when = (", ".join(CM.WD[i] for i in c["days"]) + f" {c['time']}" if c["kind"] == "weekly" else
                f"{c['date']} {c['time']}" if c["kind"] == "oneoff" else f"{c['per_week']}× a week")
        with st.container(border=True, key=f"cmm_{c['id']}"):
            st.markdown(f"{C_STAKE_DOT[c['stakes']]} **{html.escape(c['name'])}** · {when}"
                        + (f" · {got}/{tot} shown up" if tot else "")
                        + (" · 📌 pinned" if c.get("pin") else " · no pin yet"))
            c1, c2, c3 = st.columns(3)
            with c1:
                fix = _geo("📌 Pin = here" if not c.get("pin") else "📌 Re-pin here", f"cmpin_{c['id']}", alt=True)
                if fix and not fix.get("err"):
                    c["pin"] = {"lat": round(fix["lat"], 5), "lon": round(fix["lon"], 5)}
                    save_state(state)
                    flash(f"📌 Pinned {c['name']} here. Check-ins within {c.get('radius', CM.PIN_RADIUS_M)} m count.")
                    st.rerun(scope="app")
            new_st = c2.selectbox("Stakes", list(CM.STAKES), index=list(CM.STAKES).index(c["stakes"]),
                                  format_func=lambda k: CM.STAKES[k]["label"], key=f"cmst_{c['id']}",
                                  label_visibility="collapsed")
            if new_st != c["stakes"]:
                c["stakes"] = new_st
                save_state(state)
                st.rerun(scope="app")
            if c3.button("🗑️ Remove", key=f"cmdel_{c['id']}", use_container_width=True):
                c["active"] = False
                save_state(state)
                flash(f"Removed {c['name']}. Its history stays in your stats.")
                st.rerun(scope="app")


# ── Today: up next · your goals · the car ──
# Where a tap or a notification can land: section → (tab, the element to scroll to, the fold to open, extra state)
JUMPS = {
    "mission": ("🏁 Today", "tg_today", "live_card", {}),
    "timer": ("🏁 Today", "tg_timer", "timer", {}),
    "dailies": ("🏁 Today", "tg_dailies", "dailies", {}),
    "commit": ("🏁 Today", "tg_commit", "commitments", {}),
    "crew": ("🏁 Today", "tg_crew", "crew", {}),
    "journal": ("📒 Log", None, None, {"stats_view": "📓 Journal"}),
    "tasks": ("✅ Tasks", None, "tasks_open", {}),
    "goals": ("🎯 Goals", None, None, {}),
    "race": ("🏎️ Race", None, None, {}),
}


def _go_tab(label: str, to: str | None = None) -> None:
    st.session_state["nav"] = label
    if to in JUMPS:
        jump_to(to)


def jump_to(to: str) -> None:
    """Open the right tab, unfold the section and scroll to it (after this run renders)."""
    tab, el, fold_k, extra = JUMPS[to]
    st.session_state["nav"] = tab
    for k, v in extra.items():
        st.session_state[k] = v
    if fold_k:
        st.session_state["_open_fold"] = fold_k  # applied once the save is loaded this run (apply_jump)
    if el:
        st.session_state["_jump"] = el


def jump_from_link() -> None:
    """A notification opens ?to=<section>: land there, then tidy the URL."""
    to = st.query_params.get("to")
    if to:
        st.query_params.pop("to", None)
        if to in JUMPS:
            jump_to(to)


def apply_jump(state: dict) -> None:
    k = st.session_state.pop("_open_fold", None)
    if not k:
        return
    if not state.setdefault("folds", {}).get(k, False):
        state["folds"][k] = True
        save_state(state)
    for pre in ("card_", "fold_"):
        if pre + k in st.session_state:
            st.session_state[pre + k] = True


def render_jump() -> None:
    el = st.session_state.pop("_jump", None)
    if not el:
        return
    with st.container(key="jump_js"):
        st.iframe(f"""<script>
(function(){{const P=window.parent.document;let n=0;
 const go=()=>{{const e=P.querySelector('.st-key-{el}');
   if(e&&e.offsetHeight>0){{e.scrollIntoView({{behavior:'smooth',block:'start'}});
     e.style.transition='box-shadow .4s';e.style.boxShadow='0 0 0 2px var(--y,#f5c518)';e.style.borderRadius='16px';
     setTimeout(()=>{{e.style.boxShadow='none'}},1600);if(++n<3)setTimeout(go,500);}}
   else if(++n<25)setTimeout(go,200);}};
 setTimeout(go,150);}})();
</script>""", height=1)


def sort_mode(state: dict) -> str:
    m = state["settings"].get("task_sort")
    if m is None and daily.peek_day(state, now().date()).get("order"):
        return "mine"  # you arranged today's mission by hand and never picked an order: keep yours
    return m if m in RK.MODES else "start"


def _set_sort(state: dict, key: str) -> None:
    v = st.session_state.get(key)
    if v and v != sort_mode(state):
        state["settings"]["task_sort"] = v
        save_state(state)


def render_sort_pick(state: dict, key: str) -> None:
    """The order your tasks are shown in (one choice, used everywhere)."""
    st.session_state[key] = sort_mode(state)
    st.segmented_control("Order", list(RK.MODES), format_func=RK.MODES.get, key=key, label_visibility="collapsed",
                         on_change=_set_sort, args=(state, key),
                         help="✨ Start here puts anything due soon first, then the most important, and the easiest, "
                              "quickest of those on top: small win first, momentum after.")


def _set_tag(state: dict, t: dict, field: str, key: str) -> None:
    v = st.session_state.get(key)
    if v:
        t[field] = v
    else:
        t.pop(field, None)
    save_state(state)


def render_tags(state: dict, t: dict, scope: str, extra=None) -> None:
    """🔥📌🌱 priority and 🪶🧱🏔️ difficulty, one tap each (tap again to clear). `extra` draws in a third column
    (the mission row puts ↩️ Send back there)."""
    c1, c2 = st.columns(2)
    for col, field, opts, helps, label in ((c1, "prio", RK.PRIO, RK.PRIO_HELP, "Priority"),
                                           (c2, "diff", RK.DIFF, RK.DIFF_HELP, "Difficulty")):
        k = f"tag_{field}_{scope}_{t['id']}"
        st.session_state[k] = t.get(field) if t.get(field) in opts else None
        col.pills(label, list(opts), format_func=opts.get, key=k, on_change=_set_tag, args=(state, t, field, k),
                  help=" · ".join(f"{opts[o]}: {helps[o]}" for o in opts))
    if extra:
        with st.container(key=f"tagx_{scope}_{t['id']}"):
            extra()


def mission_sorted(state: dict, m: list[dict], d: date | None = None) -> list[dict]:
    """Today's mission in the order you picked (✨ Start here by default). ✋ My order = your ↕ Arrange order;
    booked blocks by time, then the rest. Finished items stay on top either way."""
    if sort_mode(state) != "mine":
        fin = [t for t in m if t["status"] != "open"]
        return fin + RK.rank([t for t in m if t["status"] == "open"], sort_mode(state), now())
    order = (daily.peek_day(state, d or now().date()).get("order") or [])
    pos = {tid: i for i, tid in enumerate(order)}

    def key(t):
        default = (0, t["block"]["start"]) if t.get("block") else (0, t["start_set"]) if t.get("start_set") \
            else (1, t["deadline"])
        return (pos.get(t["id"], len(pos)),) + default
    return sorted(m, key=key)


def _next_up(state: dict, stt: dict) -> dict | None:
    """The one thing to do now: the first open item in your mission order."""
    m = mission_sorted(state, [t for t in stt["mission"] if t["status"] == "open"])
    return m[0] if m else None


def _mv(state: dict, tid: str, step: int) -> None:
    """↑/↓ in Arrange: move one mission item (callback, so the list redraws already moved)."""
    stt = daily.status(state, now())
    ids = [t["id"] for t in mission_sorted(state, [t for t in stt["mission"] if t["status"] == "open"])]
    if tid not in ids:
        return
    i = ids.index(tid)
    j = max(0, min(len(ids) - 1, i + step))
    ids[i], ids[j] = ids[j], ids[i]
    daily.day(state, now().date())["order"] = ids
    state["settings"]["task_sort"] = "mine"  # arranging by hand = you want your own order
    save_state(state)


def _set_start(state: dict, tid: str, key: str) -> None:
    """A start time for a mission item (optional). Clearing it falls back to the planned schedule."""
    t = next((x for x in state["tasks"] if x["id"] == tid), None)
    if not t:
        return
    v = st.session_state.get(key)
    if not v or v == "—":
        t.pop("start_set", None)  # back to the day's plan
    else:
        t["start_set"] = v
        t.update(scheduled=datetime.combine(now().date(), datetime.strptime(v, "%H:%M").time(), TZ).isoformat(),
                 scheduled_time=True)
        if t.get("block"):
            t.update(R.block_fields(now().date(), t["start_set"], int(t["block"]["minutes"]), TZ))
    save_state(state)


ARR_TIMES = [f"{h:02d}:{m:02d}" for h in range(6, 24) for m in (0, 15, 30, 45)]


def _due_choices(t: dict) -> tuple[list, str]:
    """End-time options for a mission item: its current due time, then today's times still ahead.
    Tasks made today can move anywhere today; older ones only earlier (no free extensions)."""
    cur = parse_dt(t["deadline"]).astimezone(TZ)
    cur_v = cur.strftime("%Y-%m-%dT%H:%M")
    floor_ = now() + timedelta(minutes=10)
    made_today = parse_dt(t.get("created") or t["deadline"]).astimezone(TZ).date() == now().date()
    out = []
    for hm in ARR_TIMES + ["23:59"]:
        d_ = datetime.combine(now().date(), datetime.strptime(hm, "%H:%M").time(), TZ)
        if d_ > floor_ and (made_today or d_ < cur):
            out.append(d_.strftime("%Y-%m-%dT%H:%M"))
    return sorted(set(out + [cur_v])), cur_v


def _due_label(v: str) -> str:
    d_ = datetime.strptime(v, "%Y-%m-%dT%H:%M")
    hm = "midnight" if d_.strftime("%H:%M") == "23:59" else d_.strftime("%I:%M %p").lstrip("0")
    return f"due: {hm}" if d_.date() == now().date() else f"due: {d_:%a} {hm}"


def _set_due(state: dict, tid: str, key: str) -> None:
    t = next((x for x in state["tasks"] if x["id"] == tid), None)
    v = st.session_state.get(key)
    if not t or not v:
        return
    new = datetime.strptime(v, "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)
    if new.strftime("%Y-%m-%dT%H:%M") == parse_dt(t["deadline"]).astimezone(TZ).strftime("%Y-%m-%dT%H:%M"):
        return
    t["deadline"] = new.isoformat()
    t.pop("_sig", None)  # pushes the new due time to its Notion row (so sync doesn't read it as a moved date)
    save_state(state)


def _due_box(state: dict, t: dict, where) -> None:
    opts_, cur_v = _due_choices(t)
    k = f"arr_d_{t['id']}"
    where.selectbox("Due", opts_, index=opts_.index(cur_v), key=k, format_func=_due_label,
                    label_visibility="collapsed", on_change=_set_due, args=(state, t["id"], k))


def render_arrange(state: dict, stt: dict) -> None:
    """↕ Arrange: put today's mission in the order you'll do it (the top one is Up next) and, optionally, a start
    time on any of them (the phone gives you a heads-up and a ▶ Start)."""
    m = mission_sorted(state, [t for t in stt["mission"] if t["status"] == "open"])
    if not m:
        st.caption("Nothing open to arrange.")
        return
    st.caption("Drag to reorder (press and hold on a phone): the top one is Up next.")
    got = sortable([{"id": "m", "items": [{"id": t["id"], "label": t["title"],
                                           "sub": " · ".join(x for x in (min_label(t.get("minutes") or 30),
                                                             (f"⏰ {datetime.strptime(t.get('start_set') or t['block']['start'], '%H:%M'):%I:%M %p}".replace("⏰ 0", "⏰ ")
                                                              if (t.get("start_set") or t.get("block")) else "")) if x)}
                                          for t in m]}], key=f"arr_sort_{now().date()}", numbered=True)
    if got and got.get("m") and got["m"] != [t["id"] for t in m]:
        daily.day(state, now().date())["order"] = got["m"]
        state["settings"]["task_sort"] = "mine"  # dragging = you want your own order
        save_state(state)
        st.rerun()
    with fold("start_times", "⏰ Start times (optional)", any(t.get("start_set") for t in m)) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            st.caption("Leave a start on “any” and the day's plan decides. A set time gets a phone heads-up and a ▶ Start. "
                       "The second box is when it's due: set today, it can move to any time today; otherwise only earlier.")
            for t in m:
                st.markdown(f"<div class='dod-arr'>{html.escape(t['title'])}</div>", unsafe_allow_html=True)
                with st.container(key=f"arrrow_{t['id']}"):
                    c3, c4 = st.columns(2, vertical_alignment="center")
                _due_box(state, t, c4)
                cur = t.get("start_set") or ((t.get("block") or {}).get("start"))
                k = f"arr_t_{t['id']}"
                opts_ = ARR_TIMES if not cur or cur in ARR_TIMES else sorted(ARR_TIMES + [cur])
                c3.selectbox("Start", ["—"] + opts_, index=(["—"] + opts_).index(cur) if cur else 0, key=k,
                             format_func=lambda v: "start: any" if v == "—" else
                             datetime.strptime(v, "%H:%M").strftime("%I:%M %p").lstrip("0"),
                             label_visibility="collapsed", on_change=_set_start, args=(state, t["id"], k))


def render_up_next(state: dict) -> None:
    """🎯 The focal card: what's next, when, what it's for, and one big Start."""
    n_ = now()
    stt = daily.status(state, n_)
    if stt["rest"] or stt["bailout"]:
        return
    if not stt["qualified"]:
        if stt["optional"] or n_ >= stt["deadline"] or st.session_state.get("nav", "🏁 Today") == "🏁 Today":
            return  # (on Today the qualifying card itself is right there)
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.markdown(f"<div class='dod-next slim'><div class='k'>🚦 Qualify by {stt['deadline']:%I:%M %p}".replace("by 0", "by ")
                    + f" · {fmt_left(stt['deadline'] - n_)} left</div></div>", unsafe_allow_html=True)
        c2.button("Lock in →", key="upn_q", type="primary", use_container_width=True, on_click=_go_tab,
                  args=("🏁 Today", "mission"))
        return
    tm = state.get("timer")
    if tm and not os.getenv("DOD_ALL_TABS"):
        return  # the running clock is pinned to the top of the page instead
    if tm:
        t = next((x for x in state["tasks"] if x["id"] == tm.get("task_id")), None)
        st.markdown(f"<div class='dod-next run'><div class='k'>⏱️ In the zone</div>"
                    f"<div class='t'>{html.escape(t['title'] if t else 'Focus session')}</div>"
                    "<div class='m'>The clock's running. Phone face-down.</div></div>",
                    unsafe_allow_html=True)
        return
    t = _next_up(state, stt)
    if not t:
        st.markdown("<div class='dod-next done'><div class='k'>🏆 Mission complete</div>"
                    "<div class='t'>Everything you planned today is done.</div>"
                    "<div class='m'>Anything else is pure bonus. Or book time on a goal below.</div></div>",
                    unsafe_allow_html=True)
        return
    b = t.get("block") or ({"start": t["start_set"], "minutes": t.get("minutes") or 30} if t.get("start_set") else None)
    if b:
        at = datetime.strptime(b["start"], "%H:%M")
        when = f"{at:%I:%M %p}".lstrip("0")
        start_dt = datetime.combine(n_.date(), at.time(), TZ)
        rel = ("now" if start_dt <= n_ <= start_dt + timedelta(minutes=int(b["minutes"])) else
               f"in {fmt_left(start_dt - n_)}" if start_dt > n_ else "running late")
        kick = f"⏰ {when} · {rel}"
    else:
        kick = f"⏳ due {_when(parse_dt(t['deadline']))}"
    g = goal_title(state, t.get("goal_id"))
    mins = Q.session_length(t)
    with st.container(key="up_next"):
        st.markdown(f"<div class='dod-next'><div class='k'>Up next · {kick}</div>"
                    f"<div class='t'>{html.escape(t['title'])}</div>"
                    f"<div class='m'>{min_label(t.get('minutes') or 30)} · +{t['reward']} 🪙"
                    + (f" · 🗺️ {html.escape(g)}" if g else "") + "</div></div>", unsafe_allow_html=True)
        if st.button(f"▶ Start {mins} min", key="upn_go", type="primary", use_container_width=True):
            _start_timer(state, t, mins)
            flash(f"▶️ **{t['title']}** — {mins}-min timer running. Phone face-down.", sound="win")
            st.rerun()


def _book_now(state: dict, g: dict, mins: int = 45) -> dict | None:
    n_ = now()
    start = (n_ + timedelta(minutes=5)).replace(second=0, microsecond=0)
    start += timedelta(minutes=(30 - start.minute % 30) % 30)
    if start.date() != n_.date() or start.hour >= 23:
        return None
    t = make_task(f"Work on: {g['title']}", f"🗺️ {g['title']}", n_, None, "", g["id"], minutes=mins)
    t.update(R.block_fields(n_.date(), start.strftime("%H:%M"), mins, TZ), node=None)
    state["tasks"].append(t)
    daily.auto_qualify(state, n_, bank)
    return t


def todo_to_task(state: dict, d_: dict, due: datetime) -> dict:
    """A to-do (no due date) becomes a real task, due `due`. From then on it counts and can die like any task."""
    p_ = Q.parse(d_["title"], now())
    t = make_task(p_.get("title") or d_["title"], d_.get("note", ""), due, None, "", None,
                  category=p_.get("category"), minutes=d_.get("minutes") or p_.get("minutes") or 30)
    todos = state.get("todos", [])
    pos = next((i for i, x in enumerate(todos) if x["id"] == d_["id"]), len(todos))
    t["from_todo"] = dict(d_, pos=pos)  # so it can go back to the same spot (↩️ send back)
    state["tasks"].append(t)
    state["todos"] = [x for x in todos if x["id"] != d_["id"]]
    return t


def task_to_todo(state: dict, t: dict) -> dict:
    """↩️ The reverse: the task leaves (no penalty, no deadline) and the to-do comes back where it was."""
    d_ = dict(t.get("from_todo") or {"id": uuid.uuid4().hex[:8], "title": t["title"], "minutes": t.get("minutes"),
                                    "created": t.get("created") or now().isoformat()})
    pos = d_.pop("pos", None)
    d_.pop("done", None)
    d_.pop("done_at", None)
    todos = state.setdefault("todos", [])
    open_ = [x for x in todos if not x.get("done")]
    pos = len(open_) if pos is None else min(int(pos), len(open_))
    todos.insert(todos.index(open_[pos]) if pos < len(open_) else len(open_), d_)
    state["tasks"] = [x for x in state["tasks"] if x["id"] != t["id"]]
    return d_


def _returns_to_todo(t: dict) -> bool:
    """Came from the to-do list, or was made today just to fill the mission (no real deadline of its own)."""
    return bool(t.get("from_todo")) or (
        (t.get("created") or "")[:10] == now().date().isoformat() and not t.get("goal_id") and not t.get("block")
        and t.get("source") in ("manual", "quick", "qualify", "suggest", None) and not t.get("own_deadline"))


def render_send_back(state: dict, t: dict, key: str) -> None:
    """↩️ The send-back control on a mission row: shows the rule that applies right now."""
    ok, why, cost = daily.send_back_check(state, t, now())
    dest = "the to-do list" if _returns_to_todo(t) else "your task list (its own deadline stays)"
    with st.popover("↩️ Send back", help="Take it off today's mission"):
        st.markdown(f"**Send back:** {html.escape(t['title'])}")
        st.caption(f"Goes to {dest}. {why}")
        if ok:
            why_ = st.text_input("Why", key=f"sbw_{key}", placeholder="Blocked on someone · wrong day · …")
            if st.button(f"↩️ Send back{f' · −{cost}' if cost else ''}", key=f"sbgo_{key}", use_container_width=True):
                done, msg = daily.send_back(state, t, now(), why_ or "", bank)
                if done and _returns_to_todo(t):
                    task_to_todo(state, t)
                    msg += " It's back on your to-do list."
                if done:
                    save_state(state)
                    flash(msg)
                    st.rerun()
                else:
                    st.error(msg)


def render_todo(state: dict) -> None:
    """📝 Things to do some time, no due date and no penalty. Tick them off, or pull one into today (then it's a
    real task due tonight). They also show up as picks when you qualify."""
    todos = state.setdefault("todos", [])
    open_ = [x for x in todos if not x.get("done")]
    with fold("todo", f"📝 **To-do** :gray[{len(open_)} · no due dates]", default=True, card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            with st.form("todo_add", clear_on_submit=True, border=False):
                c1, c2 = st.columns([5, 1.2], vertical_alignment="bottom")
                txt = c1.text_input("Add a to-do", placeholder="Something to do some time… (add “45m” for a length)",
                                    label_visibility="collapsed", key="todo_txt")
                if c2.form_submit_button("Add", use_container_width=True, key="todo_add_go") and (txt or "").strip():
                    p_ = Q.parse(txt.strip(), now())
                    todos.append({"id": uuid.uuid4().hex[:8], "title": (p_.get("title") or txt).strip(),
                                  "minutes": p_.get("minutes") if re.search(r"\d\s*(m|min|h|hr)", txt, re.I) else None,
                                  "created": now().isoformat()})
                    save_state(state)
                    st.rerun()
            if not open_:
                st.caption("Nothing here. Park anything without a deadline: it'll be offered when you plan your day.")
            qual = daily.peek_day(state, now().date()).get("qualified")
            for d_ in open_:
                c1, c2, c3 = st.columns([6, 1.6, .8], vertical_alignment="center")
                if c1.checkbox(d_["title"] + (f" · {min_label(d_['minutes'])}" if d_.get("minutes") else ""),
                               key=f"todo_ck_{d_['id']}"):
                    d_.update(done=True, done_at=now().isoformat())
                    state["todos"] = [x for x in todos if not x.get("done")] + [x for x in todos if x.get("done")][-20:]
                    save_state(state)
                    flash(f"📝 Ticked off **{d_['title'][:60]}**.")
                    st.rerun()
                if c2.button("➕ Today", key=f"todo_today_{d_['id']}", use_container_width=True,
                             help="Make it a real task due tonight" + (" and add it to today's mission." if qual else ".")):
                    t = todo_to_task(state, d_, datetime.combine(now().date(), dtime(23, 59), TZ))
                    if qual:
                        t["mission_day"] = now().date().isoformat()
                    save_state(state)
                    flash(f"➕ **{t['title']}** is a task now, due tonight" + (" · in today's mission." if qual else "."))
                    st.rerun()
                if c3.button("✕", key=f"todo_x_{d_['id']}", help="Remove (no penalty)"):
                    state["todos"] = [x for x in todos if x["id"] != d_["id"]]
                    save_state(state)
                    st.rerun()


def render_goals_today(state: dict) -> None:
    """🗺️ Your long-term goals, in today's terms: how far along, what's next and when, one tap to book time."""
    n_ = now()
    today = n_.date()
    live = [g for g in state["goals"] if not g.get("claimed") and date.fromisoformat(g["target"]) >= today]
    if not live:
        return
    with fold("goals_today", f"🗺️ **Your goals** :gray[{len(live)}]", card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            for g in sorted(live, key=lambda g: g["target"])[:4]:
                gt = R.goal_tasks(g, state["tasks"])
                d_, n_all = R.progress(gt)
                days = (date.fromisoformat(g["target"]) - today).days
                nxt = min((t for t in gt if t["status"] == "open"),
                          key=lambda t: t.get("scheduled") or t["deadline"], default=None)
                if nxt and R.block_at(nxt, TZ):
                    nx = f"next: {html.escape(nxt['title'])} · {_when(R.block_at(nxt, TZ))}"
                elif nxt:
                    nx = f"next: {html.escape(nxt['title'])} · due {_when(parse_dt(nxt['deadline']))}"
                else:
                    nx = "nothing booked yet"
                pct = int(100 * d_ / n_all) if n_all else 0
                today_bl = [t for t in gt if (t.get("block") or {}).get("date") == today.isoformat()]
                c1, c2 = st.columns([5, 2], vertical_alignment="center")
                c1.markdown(f"<div class='dod-goal'><div class='h'><b>{html.escape(g['title'])}</b>"
                            f"<span>{'today' if days == 0 else f'{days} d'}</span></div>"
                            f"<div class='bar'><i style='width:{pct}%'></i></div>"
                            f"<div class='m'>{d_}/{n_all} done · {nx}</div></div>", unsafe_allow_html=True)
                if today_bl:
                    c2.markdown(f"<div class='dod-goal-tag'>✅ {len(today_bl)} booked today</div>", unsafe_allow_html=True)
                elif c2.button("🗓️ Book 45 min", key=f"gbook_{g['id']}", use_container_width=True,
                               help="Books the next half hour for this goal: it joins today's mission and Fortuna."):
                    t = _book_now(state, g)
                    if t:
                        save_state(state)
                        flash(f"🗓️ Booked **{t['title']}** at {R.block_at(t, TZ):%I:%M %p}. It's in today's mission.")
                        st.rerun()
                    else:
                        st.toast("Too late to book today. Plan tomorrow in the Goals tab.")
            st.button("Open the roadmaps →", key="goals_open", type="tertiary", on_click=_go_tab, args=("🎯 Goals",))


def render_car_card(state: dict) -> None:
    """🏎️ Your car, front and centre: condition, level, flag status."""
    car = state["car"]
    mid = car.get("model") if car.get("model") in CAR_BY_ID else CARS[0]["id"]
    cond = int(car["condition"])
    reasons = black_flag_reasons(state)
    lvl = level_of(state["xp"])
    into, span = state["xp"] - xp_for_level(lvl), xp_for_level(lvl + 1) - xp_for_level(lvl)
    left = max(0, PITY_AFTER - state["since_rare"])
    flag = (f"<span class='bad'>⬛ Black flag</span>" if reasons else "<span class='ok'>🟢 Green flag</span>")
    col = "#2ec4b6" if cond >= 60 else "#f5c518" if cond >= 30 else "#e10600"
    with st.container(key="car_card"):
        st.markdown(
            f"<div class='dod-car'><div class='img'>{carart.car_svg(CAR_BY_ID[mid]['body'], car['color'], car['number'], G.effective(car['parts'], mid), cond, width=360)}</div>"
            f"<div class='nm'><b>{html.escape(car.get('name') or CAR_BY_ID[mid]['name'])}</b> <span>#{html.escape(str(car['number']))} · "
            f"Level {lvl}</span>{flag}</div>"
            f"<div class='cond'><span>Condition</span><div class='bar'><i style='width:{cond}%;background:{col}'></i></div>"
            f"<b>{cond}%</b></div>"
            f"<div class='cond'><span>XP</span><div class='bar'><i style='width:{100 * into / max(1, span):.0f}%'></i></div>"
            f"<b>{into}/{span}</b></div>"
            f"<div class='chips'><span>🔥 heat {state['rival_heat']}</span><span>🛡️ {state['shields']}</span>"
            f"<span>📦 rare {'NEXT' if not left else f'≤{left}'}</span></div>"
            + (f"<div class='why'>{html.escape('; '.join(reasons))}</div>" if reasons else "") + "</div>",
            unsafe_allow_html=True)
        st.button("Garage →", key="car_garage", type="tertiary", on_click=_go_tab, args=("🔧 Garage",))


def render_season_card(state: dict) -> None:
    """🏆 The season on the Today rail: week, countdown, points and the title you're on course for."""
    pg = SE.progress(state, now().date())
    nxt = pg["next"]
    cab = state.get("trophies", [])
    with st.container(key="season_card"):
        st.markdown(
            f"<div class='dod-season'><div class='hd'><b>🏆 Season {pg['n']}</b><span>Week {pg['week']} of "
            f"{SE.SEASON_WEEKS} · {pg['left']} day{'s' * (pg['left'] != 1)} left</span></div>"
            f"<div class='bar'><i style='width:{100 * pg['frac']:.0f}%'></i></div>"
            f"<div class='pts'><b>{pg['points']}</b> pts · on course for {pg['cup']} <b>{html.escape(pg['title'])}</b>"
            + (f" · {nxt['need']} to {nxt['cup']} {html.escape(nxt['title'])}" if nxt else "") + "</div>"
            f"<div class='chips'><span>✅ {pg['finishes']} finishes</span><span>🏁 {pg['wins']} wins · "
            f"{pg['podiums']} podiums</span><span>🔥 best streak {pg['best_streak']} d</span></div>"
            f"<div class='why'>Finishes {SE.FINISH_POINTS} pts · wins {SE.RACE_POINTS[1]} · streak day "
            f"{SE.STREAK_POINTS}. Top track this season: {html.escape(RV.TOP_TRACK)} · "
            f"{html.escape(RV.layout_name(RV.TOP_TRACK))}.</div>"
            + (("<div class='cab'>" + (f"<span>⭐ Prestige ×{state['prestige']}</span>" if state.get("prestige") else "")
                + "".join(f"<span title='Season {t['n']}: {html.escape(t['title'])} · {t['points']} pts'>"
                          f"{t['cup']} S{t['n']}</span>" for t in cab[-8:]) + "</div>")
               if cab or state.get("prestige") else "")
            + "</div>", unsafe_allow_html=True)


# ── 📓 journal: morning check-in, evening questionnaire, weekly recap ──
def _scale_pills(label: str, opts: dict, key: str, default=None):
    return st.pills(label, list(opts), default=default, key=key, format_func=lambda k: opts[k])


DEBT_LOCKS = "🏎️ racing · 🎰 the Lounge · ⏳ extensions · 🔧 upgrades, cars & paint · 🎲 bets"


def debt_way_out(state: dict, n_: datetime) -> tuple[dict | None, int, int | None]:
    """(next task, what it pays with recovery fuel, finishes needed to clear the debt or None if open tasks can't)."""
    owed = -state["coins"]
    tasks = [t for t in state["tasks"] if t["status"] == "open"]
    first = Q.pick_next(tasks, n_, deep_hour=I.in_peak(globals().get("PROFILE"), n_.hour)) if tasks else None
    order = ([first] if first else []) + sorted((t for t in tasks if t is not first), key=lambda t: t["deadline"])
    pay = lambda t: int(t.get("reward", 0)) + max(1, round(int(t.get("reward", 0)) * SH.RECOVERY_BONUS))  # noqa: E731
    run = 0
    for i, t in enumerate(order, 1):
        run += pay(t)
        if run >= owed:
            return first, pay(first), i
    return first, (pay(first) if first else 0), None


def render_debt(state: dict) -> None:
    """⬛ In debt, the whole app says so: a black-flag strip on every tab, how deep, how long, what's locked, and the
    exact way out (next task, what it pays, how many finishes). Felt, never hopeless: the way out is always one tap."""
    c = state.get("coins", 0)
    if c >= 0:
        return
    n_ = now()
    if not state.get("debt_since"):
        _debt_episode(state)
    peak = min(state.get("debt_peak", c), c)
    since = parse_dt(state["debt_since"])
    climbed = c - peak
    pct = 100 * climbed / max(1, -peak)
    first, pays, n_out = debt_way_out(state, n_)
    bonus = SH.comeback_offer(state, n_)
    pays += bonus  # the first finish also collects the comeback bounty
    st.markdown(
        "<style>[data-testid='stApp']::after{content:'';position:fixed;left:0;right:0;top:0;height:5px;z-index:999990;"
        "pointer-events:none;background:repeating-linear-gradient(135deg,#e10600 0 10px,#0b0d11 10px 20px)}"
        ".dod-cluster{border-color:#5a1d1f!important;box-shadow:0 0 0 1px rgba(225,6,0,.18),0 10px 30px -12px rgba(225,6,0,.35)}"
        "</style>"
        "<div class='dod-debt'><div class='dod-debt-h'><span class='flag'>⬛ BLACK FLAG</span>"
        f"<span class='amt'>{c:,} 🪙</span><span class='m'>in the red {_span(n_ - since)}"
        + (f" · deepest {peak:,}" if peak < c else "") + "</span></div>"
        f"<div class='dod-debt-bar'><i style='width:{pct:.0f}%'></i></div>"
        f"<div class='m'>" + (f"Climbed <b>{climbed}</b> of {-peak} back · " if climbed else "")
        + f"<b>{-c}</b> to go</div>"
        f"<div class='m lock'>🔒 Locked until you're out: {DEBT_LOCKS}</div></div>", unsafe_allow_html=True)
    with st.container(key="debt_way"):
        a, b = st.columns([4, 1.1], vertical_alignment="center")
        if first:
            L = Q.session_length(first)
            after = c + pays
            extra = " + comeback bounty" if bonus else ""
            held = SH.held_total(state)
            a.markdown(f"**Way out →** {html.escape(first['title'])} pays **~+{pays}** with recovery fuel{extra}"
                       + (f" and cancels the {held} held" if held else "") + " → "
                       + ("**back in the green.** One finish clears it." if after >= 0 else
                          f"**{after:,}**. " + (f"About **{n_out}** finishes clear it." if n_out else
                                                "Your open tasks don't cover it yet: add the next real one.")))
            if b.button(f"▶ Start {L} min", key="debt_go", type="primary", use_container_width=True,
                        disabled=bool(state.get("timer"))):
                _start_timer(state, first, L)
                flash(f"▶️ **{first['title']}** — {L}-min timer running. Every finish pays +25% while you're down.",
                      sound="win")
                st.rerun()
        else:
            a.markdown("**Way out →** no open tasks. Add the next real one, and bank the small stuff: dailies, the "
                       f"morning check-in (+{J.AM_COINS}) and tonight's journal (up to +{J.PM_MAX}).")


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
    st.markdown("- No zero-day penalty; today's dailies aren't charged and their streaks are kept\n"
                "- Dailies stay open till 4 AM tonight\n- Your day streak is frozen (not broken)\n"
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
    """One tap on the way in. 6 AM to 3 PM, and only until you've answered."""
    d = now().date()
    if J.peek(state, d).get("am") or now().hour >= 15 or now().hour < J.NEW_DAY_AT:
        return
    with fold("checkin", "☀️ **How are you starting today?** :gray[+2 · one tap each]", card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
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
        for k, q, ph in J.questions(state):
            if k in J.MULTILINE or k.startswith("t:"):  # room for a few lines
                ans[k] = st.text_area(q, value=pm.get(k, ""), placeholder=ph, key=f"{key}_{k}", max_chars=600,
                                      height=84)
            else:
                ans[k] = st.text_input(q, value=pm.get(k, ""), placeholder=ph, key=f"{key}_{k}", max_chars=240)
        to_q = st.checkbox("Put the first line of “tomorrow” into tomorrow's mission queue", value=True,
                           key=f"{key}_toq")
        paid = pm.get("paid", 0)
        sub = st.form_submit_button("📓 Save the day" + (f" · up to +{J.PM_MAX - paid}" if paid < J.PM_MAX else ""),
                                    type="primary", use_container_width=True)
    if sub:
        if not (mood and energy):
            st.error("Pick a mood and an energy level first.")
            return
        got = J.close_day(state, d, {**ans, "mood": mood, "energy": energy}, now(), bank)
        tmr = next((x.strip(" -•") for x in (ans.get("tomorrow") or "").splitlines() if x.strip()), "")[:120]
        if to_q and tmr and d == J.journal_date(now()):
            p_ = Q.parse(tmr, now() + timedelta(days=1))
            state["draft"] = {"date": (d + timedelta(days=1)).isoformat(),
                              "items": [[tmr, p_["minutes"], p_["category"], False]]}
        save_state(state)
        flash(f"📓 Day saved{f' · +{got}' if got else ''}. {J.MOODS[mood]} — see it any time in Log → Journal.")
        st.rerun()


def render_close_day(state: dict) -> None:
    """5 PM to 4 AM: a short end-of-day questionnaire (after midnight it's still for the day you're closing)."""
    if not J.pm_open(now()):
        return
    d = J.journal_date(now())
    pm = J.peek(state, d).get("pm")
    if pm:
        st.markdown(f"<div class='dod-mrow ok'><span class='dod-dot'></span><div>📓 Day journaled "
                    f"{J.MOODS[pm['mood']]} <span class='m'>· +{pm.get('paid', 0)} · edit in Log → Journal</span></div>"
                    "</div>", unsafe_allow_html=True)
        return
    late = d != now().date()
    with fold("closeday", "📓 **Close the day**" + (f" :gray[{d:%A} · open till {J.PM_CLOSES} AM]" if late else ""), card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            st.caption(f"Two taps and a few lines. +{J.PM_BASE} for the taps, +{J.PM_PER_ANSWER} per real answer "
                       f"(up to +{J.PM_MAX}). It all lands in Log → Journal and your weekly recap.")
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
                f"<span>⏱️ <b>{hmin(r['focus_min'])}</b> focused</span><span>✅ <b>{r['done']}</b> done</span>"
                f"<span>Mood <b>{J.mood_face(r['mood_avg'])}</b>"
                + (f" {r['mood_avg']:.1f}/5" if r["mood_avg"] is not None else "") + "</span>"
                f"<span>📓 <b>{r['journaled']}</b>/7 journaled</span>"
                + (f"<span>🏆 Best: <b>{r['best']['date']:%a}</b> {hmin(r['best']['focus'])}</span>" if r["best"] else "")
                + "</div>", unsafe_allow_html=True)
    import altair as alt
    acc = accent(state)[0]
    df = pd.DataFrame([{"Day": f"{x['date']:%a}", "i": k, "Focus h": round(x["focus"] / 60, 2), "Focus": hmin(x["focus"]),
                        "Mood": x["mood"], "Face": J.mood_face(x["mood"]) if x["mood"] is not None else ""}
                       for k, x in enumerate(r["rows"])])
    if not df.empty:
        base = alt.Chart(df).encode(x=alt.X("Day:N", sort=alt.SortField("i"), title=None,
                                             axis=alt.Axis(labelAngle=0)))
        bars = base.mark_bar(cornerRadiusEnd=4, color=acc, size=26).encode(
            y=alt.Y("Focus h:Q", title="Focus hours"), tooltip=["Day", "Focus", "Mood"])
        faces = base.mark_text(dy=-12, fontSize=18).encode(y=alt.Y("Focus h:Q"), text="Face:N")
        _chart((bars + faces).properties(height=200))
    if r["focus_good_mood"] is not None and r["focus_low_mood"] is not None:
        st.caption(f"On 🙂/😄 days you focused {r['focus_good_mood']:.0f} min; on 😕/😫 days, "
                   f"{r['focus_low_mood']:.0f} min.")
    st.markdown(f"<div class='dod-rc-h'>🏆 Wins <span>{len(r['wins'])}</span></div>"
                + _recap_cards(r["wins"], "win", "None written yet."), unsafe_allow_html=True)
    with fold("jr_recap", "📋 Recap to paste", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            st.code(J.recap_text(r), language=None)
    if journal_cfg(state):
        if st.button("🔄 Pull entries I wrote in Notion", key="jr_pull", help="Brings in the last 7 days of entries you "
                     "wrote straight into your Notion journal (this also runs by itself when you open the app)."):
            try:
                got_ = import_notion_journal(state)
                if got_:
                    save_state(state)
                for m_ in got_ or ["📓 Nothing new in your Notion journal."]:
                    flash(m_)
            except Exception as e:  # noqa: BLE001
                flash(f"Couldn't read your Notion journal: {e}", "warning")
            st.rerun()
    st.markdown("#### 📓 Days")
    jd = J.journal_date(now())  # yesterday until 4 AM · none 4–6 AM · today from 6 AM
    if jd is None:
        st.caption(f"🌙 The journal reopens at {J.NEW_DAY_AT} AM for the new day.")
    elif not J.peek(state, jd).get("pm"):
        with fold("jr_today", ("✏️ Today" if jd == today else f"✏️ {jd:%A} (open till {J.PM_CLOSES} AM)")
                  + f", {jd:%a %b} {jd.day} · not journaled yet", False) as _fo:
            if _open(_fo):  # collapsed = not built (faster page, smaller download)
                _journal_form(state, jd, "jt")
    ents = J.entries(state)
    if not ents:
        st.caption("Your check-ins and evening entries land here, one card per day.")
    for d_, e in ents[:30]:
        am, pm = e.get("am") or {}, e.get("pm") or {}
        done = J.done_on(state, d_, TZ)
        head = (f"{d_:%a %b} {d_.day} · " + (f"{J.MOODS[am['mood']]}" if am else "·") + " → "
                + (f"{J.MOODS[pm['mood']]}" if pm else "·") + f" · ⏱️ {hmin(J.focus_on(state, d_))} · ✅ {len(done)}")
        with st.expander(head, key=f"exp_jr_{d_.isoformat()}"):
            if (d_ == jd and pm) or (d_.isoformat() in state.get("late_journal_ok", []) and not pm):
                _journal_form(state, d_, f"je_{d_.isoformat()}")
                continue
            qs = J.questions(state)
            known = {k for k, _, _ in qs}
            for k, q, _ in qs + [(k, k[2:].replace("-", " ").capitalize() if k.startswith("t:") else
                                  JN.CORE.get(k, (k,))[0], "") for k in J.answer_keys(pm) if k not in known]:
                if pm.get(k):
                    st.markdown(f"**{q}**  \n" + html.escape(pm[k]).replace("\n", "  \n"))
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
    lines = [f"{period}: {len(ts)} things done · {hmin(sum(t.get('minutes') or 0 for t in ts))}"]
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
    st.markdown(f"<div class='dod-pills'><span>✅ <b>{len(ts)}</b> done</span><span>🕒 <b>{hmin(mins)}</b> of work"
                f"</span><span>⏱️ <b>{hmin(timed)}</b> on the timer</span><span>🪙 <b>+{sum(t.get('reward', 0) for t in ts)}"
                f"</b></span></div>", unsafe_allow_html=True)
    with fold("stats_recap", "📋 Recap to paste (supervisor meeting, journal, thesis log)", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
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
        c2, c3 = st.container(key="row_pomo").columns(2)
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
TIMER_LENGTHS = [5, 10, 15, 25, 30, 45, 50, 60, 90, 120]
FLOW_MODE = -1          # 🌊 Flow: count up, no breaks, check-ins instead of a finish line
FLOW_CHECK = 90         # first check-in (a deep-work wave)…
FLOW_AGAIN = 30         # …then every 30 min after a "keep going"
FLOW_GRACE = 20         # no answer this long after a check-in → it stops and logs up to the check-in
FLOW_CAP = 240          # hard ceiling for one flow session
FLOW_REST_AT = 120      # past this it suggests a real break
FLOW_EVERY_OPTS = [20, 30, 45, 60, 90, 120]  # you pick how often flow checks in (first one, then every so often)


def _flow_every_pick(state: dict, key: str, where=None) -> int:
    """Only shown once 🌊 Flow is picked: how often it checks you're still going. Remembers your last pick."""
    cur = int(state["settings"].get("flow_every", FLOW_CHECK))
    opts = sorted({*FLOW_EVERY_OPTS, cur})
    v = (where or st).selectbox("🌊 Check in every", opts, index=opts.index(cur), key=key,
                                format_func=lambda m: f"{m} min" if m < 60 else f"{m // 60} h" + (f" {m % 60} min" if m % 60 else ""))
    if v != state["settings"].get("flow_every"):
        state["settings"]["flow_every"] = int(v)
    return int(v)


def _timer_task(state: dict, name: str, planned: int, wall: int) -> dict:
    """A task made on the spot from the timer: due tonight (or an hour after the session, if that's later)."""
    eod = datetime.combine(now().date(), dtime(23, 59), TZ)
    dl = max(eod, now() + timedelta(minutes=wall + 60))
    t = make_task((name or "").strip() or "Focus session", "Started from the focus timer.", dl, None, "",
                  source="timer", minutes=planned)
    state["tasks"].append(t)
    return t


def render_timer(state: dict, big: bool = False) -> None:
    tm = state.get("timer")
    open_t = sorted([t for t in state["tasks"] if t["status"] == "open"],
                    key=lambda t: (t.get("mission_day") != now().date().isoformat(), t["deadline"]))
    with fold("timer", "⏱️ **Focus timer**" + (" :red[● running]" if tm and not tm.get("paused") else
                                              " :orange[❚❚ paused]" if tm else ""), card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            if not tm:
                labels = {t["id"]: t["title"] for t in open_t}
                labels[NEW_SESSION] = "✏️ New task…"
                c1, c2 = st.container(key="row_tm1").columns([1.6, 1])
                tid = c1.selectbox("Working on", list(labels), format_func=labels.get, key="timer_task",
                                   label_visibility="collapsed")
                planned = c2.selectbox("Minutes", TIMER_LENGTHS + [0, FLOW_MODE], key="timer_len", label_visibility="collapsed",
                                       index=TIMER_LENGTHS.index(25),
                                       format_func=lambda m: "🌊 Flow (count up)" if m == FLOW_MODE else
                                       f"{m} min" if m else "Custom…")
                flow = planned == FLOW_MODE
                every = FLOW_CHECK
                if flow:
                    planned = FLOW_CAP
                    every = _flow_every_pick(state, "timer_every")
                    st.caption(f"🌊 **Flow:** counts up, no breaks. Every {every} min it checks you're still going (one tap); "
                               f"no answer in {FLOW_GRACE} min and it logs up to the check-in. You bank one free pause per stretch; "
                               f"unused ones carry over. Loot rolls every 25 min.")
                elif not planned:
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
                c3, c4 = st.container(key="row_tm2").columns([1.6, 1])
                work, brk = (None, None) if flow else _pomo_pick(state, c3)
                if c4.button("🎲 Pick for me", use_container_width=True, key="pick_next",
                             help="Picks your best next task and starts the timer"):
                    pick = Q.pick_next(state["tasks"], now(), deep_hour=I.in_peak(PROFILE, now().hour))
                    if pick:
                        plen = Q.session_length(pick)
                        state["timer"] = {"pins": 0, "pouts": 0, "task_id": pick["id"], "start": now().isoformat(), "planned": plen,
                                          "work": work, "brk": brk}
                        _mark_started(pick)
                        save_state(state)
                        flash(f"🎲 **Do this now: {pick['title']}** — {plen}-min focus timer started. Nothing else exists.",
                              sound="win")
                        st.rerun()
                wall = PM.wall_minutes(planned, work, brk)
                if st.button("▶️ Start flow · open-ended" if flow else
                             f"▶️ Start focus · {planned} min work" + (f" · done in {wall} min with breaks" if wall > planned else ""),
                             type="primary", use_container_width=True):
                    if tid == NEW_SESSION:
                        tid = _timer_task(state, new_name, 60 if flow else planned, 60 if flow else wall)["id"]
                    state["timer"] = {"pins": 0, "pouts": 0, "task_id": tid, "start": now().isoformat(), "planned": planned,
                                      "work": work, "brk": brk}
                    if flow:
                        state["timer"].update(flow=True, check=every, every=every)
                    _mark_started(next(x for x in state["tasks"] if x["id"] == tid))
                    save_state(state)
                    st.rerun()
                tok = state.get("tokens", {})
                claimed = state.get("challenge_claims", [])
                for ch in EV.focus_challenges(now().date(), TZ):  # 🎙️ Valenti calls the challenges
                    if ch["id"] in claimed:
                        st.markdown(cast_say("announcer", CR.cast_line("announcer", {"claimed": True}, ch["id"]),
                                             f"✅ <s>{html.escape(ch['label'])}</s>", "won"), unsafe_allow_html=True)
                    elif ch["start"] <= now() < ch["end"]:
                        left_ = fmt_left(ch["end"] - now())
                        st.markdown(cast_say("announcer", CR.cast_line("announcer", {"live": True, "label": ch["label"],
                                                                                      "left": left_}, ch["id"]),
                                             f"🔥 <b>LIVE CHALLENGE:</b> {html.escape(ch['label'])} · {left_} left to start",
                                             "live"), unsafe_allow_html=True)
                drops_left = EV.DROPS_PER_DAY - sum(x.get("drops", 1) for x in state.get("focus_log", [])
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
                mins = min(PM.credited(tm, PM.effective_elapsed(tm, now_ts)), tm["planned"] + 15 + tm.get("over_total", 0.0))
                state.pop("timer", None)
                if mins >= 1 and t:
                    _log_session(state, t, start, mins, tm)
                else:
                    save_state(state)
                flash(f"⏸️ Paused for over {PM.PAUSE_LIMIT_MIN} min, so the session ended.", "warning")
                st.rerun()
            title = (t["title"] if t else "—")
            st.markdown(f"#### ⏱️ {html.escape(title[:42] + ('…' if len(title) > 42 else ''))}")
            _timer_ring(state, tm, big=big)
            _timer_controls(state)


def _skip_break(state: dict) -> None:
    """Runs the moment you tap ☕ Skip break. Checks the clock right then (the button no longer waits for the
    controls' 10-second refresh to switch itself on), so a tap during a break always lands."""
    tm = state.get("timer")
    if not tm:
        return
    eff = PM.effective_elapsed(tm, now().timestamp())
    ph, left = PM.phase(eff, tm.get("work"), tm.get("brk"), tm["planned"])
    g, _ = PM.gate(tm, eff)
    if tm.get("paused_at"):
        flash("⏸️ Resume first, then skip the break.", "info")
    elif g == "pit_out":
        PM.confirm(tm, eff)
        save_state(state)
        flash("🟢 Pit out. Back on track.", "success")
    elif ph != "break":
        nxt = (tm.get("work") or 0) and ph == "work"
        flash("☕ No break right now" + (f" — the next one starts in {int(left) + 1} min." if nxt and tm.get("brk")
                                         and PM.work_done(eff, tm["work"], tm["brk"]) + left < tm["planned"] else "."), "info")
    else:
        tm["skipped"] = tm.get("skipped", 0.0) + left * 60
        if "pins" in tm:  # skipping the break is your pit out
            tm["pouts"] = int(tm.get("pins", 0))
        save_state(state)
        flash(f"☕ Break skipped ({int(left) + 1} min). Back on track.", "success")
    st.session_state["_tm_redraw"] = True


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
    if tm.get("flow") and not paused:
        chk = tm.get("check", FLOW_CHECK)
        if eff >= chk + FLOW_GRACE or eff >= FLOW_CAP:  # no answer at the check-in (or the 4 h ceiling): wrap it up
            mins = min(eff, chk if eff >= chk + FLOW_GRACE else FLOW_CAP)
            state.pop("timer", None)
            if t:
                _log_session(state, t, start, mins, tm)
            flash(f"🌊 Flow ended at {int(mins)} min" + (" (no answer at the check-in, so it's logged up to there)."
                                                         if mins < FLOW_CAP else " (the 4-hour ceiling)."), "info")
            st.rerun(scope="app")
        if eff >= chk:
            st.markdown(f"<div class='dod-flow-chk'>🌊 <b>{int(eff)} min in. Still flowing?</b> "
                        f"<span>No answer by {int(chk + FLOW_GRACE)} min and it logs up to {int(chk)}.</span></div>",
                        unsafe_allow_html=True)
            if st.button("🌊 Yes, keep going", type="primary", use_container_width=True, key="tm_flow_ok"):
                tm["check"] = int(eff) + int(tm.get("every") or FLOW_AGAIN)
                tm["period"] = tm.get("period", 0) + 1  # a new check-in stretch: its own pause
                save_state(state)
                st.rerun(scope="app")
        elif eff >= FLOW_REST_AT:
            st.caption(f"🌊 {int(eff)} min deep. A real break soon would bank this well.")
    gate_, over_ = PM.gate(tm, eff) if not paused else ("", 0.0)
    if gate_ == "pit_in":
        st.markdown(f"<div class='dod-flow-chk' style='border-color:#f5c518'>🔧 <b>Box, box. Stint done.</b> "
                    f"<span>Finish your thought: " + (f"you're {int(over_)} min over, and " if over_ >= 1 else "") + f"up to {PM.PIT_OVER_MAX} extra min still count as work. The "
                    f"{tm['brk']}-min break starts when you pit in.</span></div>", unsafe_allow_html=True)
        if st.button("🔧 Pit in", type="primary", use_container_width=True, key="tm_pitin"):
            PM.confirm(tm, eff)
            save_state(state)
            st.rerun(scope="app")
    elif gate_ == "pit_out":
        st.markdown(f"<div class='dod-flow-chk' style='border-color:#3ddc84'>🟢 <b>Break's up. Pit out?</b> "
                    f"<span>" + (f"{int(over_)} min over the break (that part doesn't count as work). " if over_ >= 1 else "") + "The next stint starts when "
                    f"you pit out.</span></div>", unsafe_allow_html=True)
        if st.button("🟢 Pit out", type="primary", use_container_width=True, key="tm_pitout"):
            PM.confirm(tm, eff)
            save_state(state)
            st.rerun(scope="app")
    c1, c2 = st.columns(2)
    if paused:
        if c1.button("▶️ Resume", use_container_width=True, key="tm_resume", type="primary"):
            tm["paused_total"] = tm.get("paused_total", 0.0) + (now_ts - parse_dt(tm["paused_at"]).timestamp())
            tm["paused_at"] = None
            save_state(state)
            st.rerun()
    elif tm.get("flow"):  # 🌊 flow: one free pause per check-in stretch, earned again at each check-in
        have = 1 + tm.get("period", 0) - tm.get("free_used", 0)  # banked: unused pauses carry over
        nxt = int(tm.get("check", FLOW_CHECK))
        if c1.button(f"⏸️ Pause · {have} banked" if have > 0 else f"⏸️ Next pause at {nxt} min", use_container_width=True,
                     key="tm_pause", disabled=have <= 0,
                     help=f"Flow banks one free pause per check-in stretch (every {tm.get('every') or FLOW_CHECK} min); "
                          f"unused ones carry over. Paused time doesn't count, and a pause over "
                          f"{PM.PAUSE_LIMIT_MIN} min ends the session."):
            tm["free_used"] = tm.get("free_used", 0) + 1
            tm["pauses"] = tm.get("pauses", 0) + 1
            tm["paused_at"] = now().isoformat()
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
    if st.session_state.pop("_tm_redraw", False):
        st.rerun(scope="app")  # the clock lives outside these controls: redraw it with the new times
    if not tm.get("flow") and not gate_:  # at a pit gate, the Pit in / Pit out button is the one to press
        c2.button("☕ Skip break", use_container_width=True, key="tm_skip", on_click=_skip_break, args=(state,),
                  help="Jump straight to the next work block (works whenever you're on a break).")
    wd_now = PM.work_done(eff, work, brk)
    near_end = tm["planned"] - wd_now <= FLOW_WINDOW
    if not tm.get("flow") and not paused and ph != "break" and near_end and tm.get("ext", 0) < FLOW_MAX_EXT:
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
            st.rerun(scope="app")
    c3, c4 = st.columns([3, 1])
    if c3.button("⏹️ Stop & log", type="secondary" if paused or gate_ else "primary", use_container_width=True, key="tm_stop"):
        mins = min(PM.credited(tm, eff), tm["planned"] + 15 + tm.get("over_total", 0.0))
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


def timer_keep_going(state: dict) -> None:
    """🌊 The 'keep going' answer, wherever it's pressed: a flow check-in → next check-in; a timed session → +15."""
    tm = state.get("timer")
    if not tm:
        return
    eff = PM.effective_elapsed(tm, now().timestamp())
    if tm.get("flow"):
        tm["check"] = int(eff) + int(tm.get("every") or FLOW_AGAIN)
        tm["period"] = tm.get("period", 0) + 1
    else:
        ph, _ = PM.phase(eff, tm.get("work"), tm.get("brk"), tm["planned"])
        tm["planned"] += FLOW_STEP
        tm["ext"] = tm.get("ext", 0) + FLOW_STEP
        if ph == "done":  # finished already: the extension starts from now, not from the old finish line
            tm["skipped"] = tm.get("skipped", 0.0) - max(0.0, (eff - PM.wall_minutes(
                tm["planned"] - FLOW_STEP, tm.get("work"), tm.get("brk"))) * 60)
    save_state(state)


def timer_stop_log(state: dict) -> None:
    """⏹️ Stop & log, wherever it's pressed."""
    tm = state.get("timer")
    if not tm:
        return
    t = next((x for x in state["tasks"] if x["id"] == tm["task_id"]), None)
    eff = PM.effective_elapsed(tm, now().timestamp())
    mins = min(PM.credited(tm, eff), tm["planned"] + 15 + tm.get("over_total", 0.0))
    state.pop("timer", None)
    if mins >= 1 and t:
        _log_session(state, t, parse_dt(tm["start"]), mins, tm)
    else:
        save_state(state)


def track_for(tm: dict) -> dict:
    """A real circuit for this session: same session → same track (stable across refreshes)."""
    return TR.TRACKS[int(hashlib.md5(tm["start"].encode()).hexdigest(), 16) % len(TR.TRACKS)]


# ── one clock everywhere: the big ring, the floating mini, the pop-out window and the browser tab title ──
# Plain JS (no f-string): dodTick(state, now) → what to show. The pop-out manager is injected into the page
# itself once, so it outlives Streamlit's reruns and keeps the pop-out window and tab title ticking.
TIMER_CORE_JS = r"""
function dodMMSS(ms){var a=Math.floor(Math.abs(ms)/1000);return String(Math.floor(a/60)).padStart(2,'0')+':'+String(a%60).padStart(2,'0');}
function dodTick(s,now){
 now=now+(s.OFF||0);
 var e=Math.max(0,(now-s.S-s.PT-(s.PA?now-s.PA:0)+s.SK)/60000),W=s.W,B=s.B,T=s.T;
 var wd=(!W||!B)?e:Math.floor(e/(W+B))*W+Math.min(e%(W+B),W);wd=Math.min(wd,T);
 var ph='work',left=(T-e)*60000;
 if(wd>=T)ph='done';else if(W&&B){var c=W+B,r=e%c;if(r<W)left=Math.min(W-r,T-wd)*60000;else{ph='break';left=(c-r)*60000;}}
 var gate='',over=0;  // pit in / pit out wait for your confirm
 if(s.GT&&W&&B&&!s.FL){var c_=W+B,n_=s.PI,m_=s.PO;  // from the pit ins/outs you've confirmed
  if(n_>m_){if(e>=n_*c_){gate='pitout';over=e-n_*c_;wd=n_*W;}}
  else if(e>=n_*c_+W&&(n_+1)*W<T){gate='pitin';over=e-n_*c_-W;wd=(n_+1)*W;}}
 var o={frac:s.FL?(e%25)/25:wd/T,color:s.ACC,ph:gate||ph,due:!!(s.FL&&e>=s.CHK)};
 if(s.PA){o.time=s.FL?dodMMSS(e*60000):dodMMSS(left);o.line='Paused '+dodMMSS(now-s.PA);o.color='#8b909c';}
 else if(s.FL){o.time=dodMMSS(e*60000);o.line=e>=s.CHK?'🌊 Check-in: still flowing?':'🌊 Flow · check-in at '+s.CHK+' min';
   if(e>=s.CHK)o.color='#29e3ff';}
 else if(gate==='pitin'){o.time='+'+dodMMSS(over*60000);o.line='🔧 Box, box: tap Pit in';o.color='#f5c518';}
 else if(gate==='pitout'){o.time='+'+dodMMSS(over*60000);o.line='🟢 Break\u2019s up: tap Pit out';o.color='#3ddc84';}
 else if(ph==='done'){o.time='+'+dodMMSS((e-s.WALL)*60000);o.line='🏁 Done. Stop & log it.';o.color='#ff6a5c';}
 else if(ph==='break'){o.time=dodMMSS(left);o.line='🔧 Break';o.color='#2ec4b6';}
 else{o.time=dodMMSS(left);o.line=Math.round(wd)+' of '+T+' min';}
 return o;}
"""


# ── splashes + sounds for the session's moments: pit stop (break starts), green flag (break over), flow check-in,
# chequered flag (done). Plain JS shared by the app page and the pop-out, so each can show them in its own window.
SPLASH_JS = r"""
var DOD_SP={pit:{e:'🔧',h:'PIT STOP',s:'Break time. Stand up, water, stretch. No phone in the pit lane.',c:'#2ec4b6'},
 go:{e:'🟢',h:'GREEN FLAG',s:'Break\u2019s over. Back to it.',c:'#3ddc84'},
 chk:{e:'🌊',h:'STILL FLOWING?',s:'Check-in: tap Keep going, or stop & log it.',c:'#29e3ff'},
 pitin:{e:'🔧',h:'BOX, BOX',s:'Stint done. Tap Pit in when you\u2019re ready: the break starts then.',c:'#f5c518'},
 pitout:{e:'🟢',h:'PIT OUT?',s:'Break\u2019s up. Tap Pit out to rejoin.',c:'#3ddc84'},
 fin:{e:'🏁',h:'CHEQUERED FLAG',s:'Session complete. Stop & log it.',c:'#ff6a5c'}};
function dodSplash(doc,kind,sub){
 var k=DOD_SP[kind];if(!k||!doc||!doc.body)return;var cls={pitin:'pit',pitout:'go'}[kind]||kind;
 var old=doc.getElementById('dod-sp');if(old)old.remove();
 if(!doc.getElementById('dod-sp-css')){var st=doc.createElement('style');st.id='dod-sp-css';st.textContent=
 '#dod-sp{position:fixed;inset:0;z-index:2147483000;pointer-events:none;display:flex;align-items:center;justify-content:center;'+
 'font-family:system-ui,-apple-system,sans-serif;animation:dspo .6s ease 4.6s forwards}'+
 '#dod-sp .bg{position:absolute;inset:0;background:radial-gradient(ellipse at center,transparent 35%,var(--c) 140%);'+
 'animation:dspp .5s ease-in-out 0s 6 alternate}'+
 '#dod-sp.fin .bg{background:radial-gradient(ellipse at center,transparent 45%,var(--c) 130%)}'+
 '#dod-sp.fin .fr{position:absolute;inset:0;padding:12px;box-sizing:border-box;'+
 'background:repeating-conic-gradient(#f2efe8 0 25%,#111318 0 50%) 0 0/14px 14px;'+
 '-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;'+
 'mask:linear-gradient(#000 0 0) content-box exclude,linear-gradient(#000 0 0);animation:dspp .55s ease-in-out 0s 8 alternate}'+
 '#dod-sp .cd{position:relative;text-align:center;padding:18px 26px;border-radius:18px;background:rgba(14,17,23,.86);'+
 'border:2px solid var(--c);box-shadow:0 0 0 6px rgba(0,0,0,.25),0 18px 60px rgba(0,0,0,.55);max-width:86vw;'+
 'animation:dspi .45s cubic-bezier(.2,1.4,.4,1) both}'+
 '#dod-sp .em{font-size:min(16vw,64px);line-height:1}#dod-sp .hd{font:800 min(9vw,40px)/1.1 system-ui,sans-serif;'+
 'letter-spacing:.08em;color:var(--c);margin:6px 0 4px}#dod-sp .sb{font-size:min(4.2vw,16px);color:#ece8df;opacity:.9}'+
 '#dod-sp .lt{display:flex;gap:8px;justify-content:center;margin-top:10px}#dod-sp .lt i{width:14px;height:14px;border-radius:50%;'+
 'background:#262b36}#dod-sp.go .lt i{animation:dspl .3s steps(1) both}#dod-sp.go .lt i:nth-child(2){animation-delay:.35s}'+
 '#dod-sp.go .lt i:nth-child(3){animation-delay:.7s}@keyframes dspl{to{background:#3ddc84;box-shadow:0 0 12px #3ddc84}}'+
 '@keyframes dspi{from{transform:scale(.6);opacity:0}to{transform:none;opacity:1}}'+
 '@keyframes dspp{from{opacity:.2}to{opacity:1}}@keyframes dspo{to{opacity:0;visibility:hidden}}'+
 '@media (prefers-reduced-motion:reduce){#dod-sp .bg,#dod-sp .fr,#dod-sp .cd{animation:none}}';doc.head.appendChild(st);}
 var o=doc.createElement('div');o.id='dod-sp';o.className=cls;o.style.setProperty('--c',k.c);
 o.innerHTML=(kind==='fin'?'<div class="fr"></div>':'')+'<div class="bg"></div><div class="cd"><div class="em"></div><div class="hd"></div>'+
  '<div class="sb"></div>'+(cls==='go'?'<div class="lt"><i></i><i></i><i></i></div>':'')+'</div>';
 o.querySelector('.em').textContent=k.e;o.querySelector('.hd').textContent=k.h;o.querySelector('.sb').textContent=sub||k.s;
 doc.body.appendChild(o);var w=doc.defaultView;w.setTimeout(function(){if(o.parentNode)o.remove();},5400);
 try{if(w.navigator.vibrate)w.navigator.vibrate(kind==='fin'?[400,150,400,150,800]:cls==='pit'?[300,120,300]:[150,80,150,80,400]);}catch(e){}}
function dodSound(win,kind){  // pit: two falling tones · go: start lights (3 low + 1 high) · chk: two pings · fin: rising fanfare
 try{var A=win.__dodAC=win.__dodAC||new (win.AudioContext||win.webkitAudioContext)();if(A.state==='suspended')A.resume();
  kind={pitin:'pit',pitout:'go'}[kind]||kind;
  var seq={pit:[[784,0,.28],[523,.32,.45]],go:[[440,0,.16],[440,.35,.16],[440,.7,.16],[880,1.05,.5]],
   chk:[[988,0,.14],[988,.22,.14]],fin:[[523,0,.16],[659,.18,.16],[784,.36,.16],[1047,.54,.6]]}[kind]||[];
  seq.forEach(function(x){var o=A.createOscillator(),g=A.createGain(),t=A.currentTime+x[1];o.type='triangle';o.frequency.value=x[0];
   g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(.22,t+.02);g.gain.exponentialRampToValueAtTime(.0001,t+x[2]);
   o.connect(g);g.connect(A.destination);o.start(t);o.stop(t+x[2]+.05);});}catch(e){}}
// what changed since the last look: one moment per change (loading the page mid-break shows nothing)
function dodMoment(memo,s,o){
 var key=s.PA?'pause':o.ph,id=s.S+':'+(s.FL?'f':'p'),m=memo[id];memo[id]={k:key,due:o.due};
 if(!m)return null;
 if(o.due&&!m.due&&!s.PA)return 'chk';
 if(m.k===key||s.PA||m.k==='pause')return null;
 if(key==='pitin')return 'pitin';if(key==='pitout')return 'pitout';
 if(key==='break'&&m.k!=='pitin')return 'pit';if(key==='work'&&m.k==='break')return 'go';if(key==='done')return 'fin';return null;}
"""

POP_PAGE_CSS = """*{box-sizing:border-box}html,body{margin:0;height:100%;background:#0e1117;color:#ece8df;
font-family:system-ui,-apple-system,sans-serif;overflow:hidden}
body{display:flex;flex-direction:column;align-items:center;padding:10px 12px 12px;gap:4px;text-align:center}
#n{font-size:13px;font-weight:600;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#svg{flex:1 1 auto;min-height:60px;width:100%;max-width:520px}
.row{display:flex;align-items:baseline;gap:10px;justify-content:center}
#t{font:700 clamp(30px,min(13vw,11vh),88px)/1 system-ui,sans-serif;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
#p{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#8b909c}
#bt{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin-top:6px;width:100%}
#bt button{flex:1 1 40%;min-height:36px;border-radius:10px;border:1px solid #343a47;background:#1b1f27;color:#ece8df;
 font:600 13px system-ui,sans-serif;cursor:pointer}#bt button.pri{background:#f5c518;border-color:#f5c518;color:#111}
#bt button:disabled{opacity:.45;cursor:default}#m{font-size:11px;color:#8b909c;min-height:14px}
.over #svg,.over #bt{opacity:.25;pointer-events:none}"""

POP_PAGE_BODY = ('<div id="n"></div><svg id="svg" viewBox="0 0 300 172" preserveAspectRatio="xMidYMid meet"></svg>'
                 '<div class="row"><div id="t">--:--</div><div id="p"></div></div><div id="m"></div><div id="bt"></div>')

# runs inside the pop-out window itself: its own clock (so a hidden app tab can't freeze it), the track and car,
# and buttons that press the app's real Pause / Skip break / Keep going / Stop & log
POP_PAGE_JS = TIMER_CORE_JS + SPLASH_JS + r"""
var S=null,H=window.__host,NS='http://www.w3.org/2000/svg',tr=null,L=0,car=null,trail=null,curD=null,sig='',busy=0;
function $(i){return document.getElementById(i);}
function track(){var v=$('svg');curD=S.trkD;v.innerHTML='<text id="tl" x="4" y="9" font-size="7" fill="#5b6070" letter-spacing=".07em"></text>'+
 '<path id="track" d="'+S.trkD+'" fill="none" stroke="#262b36" stroke-width="9" stroke-linejoin="round"/>'+
 '<path d="'+S.trkD+'" fill="none" stroke="#3a4050" stroke-width=".7" stroke-dasharray="3 4"/>'+
 '<path id="trail" d="'+S.trkD+'" fill="none" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="0 99999"/>'+
 '<g id="car">'+S.sprite+'</g>';$('tl').textContent=S.trkL;tr=$('track');L=tr.getTotalLength();car=$('car');trail=$('trail');}
function place(f){if(!tr)return;var d=L*Math.min(.9999,Math.max(0,f)),a=tr.getPointAtLength(d),b=tr.getPointAtLength(Math.min(L,d+1));
 car.setAttribute('transform','translate('+a.x+','+a.y+') rotate('+(Math.atan2(b.y-a.y,b.x-a.x)*180/Math.PI)+') scale(.85)');}
function act(k,b){if(!H||H.closed){$('m').textContent='The app tab is closed. Open it to use these.';return;}
 busy=Date.now();b.disabled=true;b.textContent='…';$('m').textContent='Sent to the app…';
 try{H.__dodAct(k);}catch(e){$('m').textContent='Couldn’t reach the app tab.';}}
function buttons(o){var L_=[];
 if(S.PA)L_.push(['tm_resume','▶️ Resume',0,1]);else L_.push(['tm_pause',S.pauseLabel,!S.canPause,0]);
 if(o.ph==='pitin'&&!S.PA)L_.push(['tm_pitin','🔧 Pit in',0,1]);
 if(o.ph==='pitout'&&!S.PA)L_.push(['tm_pitout','🟢 Pit out',0,1]);
 if(!S.FL&&o.ph==='break'&&!S.PA)L_.push(['tm_skip','☕ Skip break',0,0]);
 if(o.due&&!S.PA)L_.push(['tm_flow_ok','🌊 Keep going',0,1]);
 L_.push(['tm_stop','⏹️ Stop & log',0,!o.due&&!S.PA&&o.ph!=='pitin'&&o.ph!=='pitout']);
 var sg=JSON.stringify(L_);if(sg===sig||Date.now()-busy<2500)return;sig=sg;var bt=$('bt');bt.innerHTML='';
 L_.forEach(function(x){var b=document.createElement('button');b.textContent=x[1];b.disabled=!!x[2];if(x[3])b.className='pri';
  b.onclick=function(){act(x[0],b);};bt.appendChild(b);});}
window.__dodSet=function(s){try{LASTJ=JSON.stringify(s||null);}catch(e){}S=s;busy=0;sig='';$('m').textContent='';
 if(!s){document.body.className='over';$('t').textContent='✓';$('t').style.color='#2ec4b6';$('p').textContent='Session over';
  $('bt').innerHTML='';return;}
 document.body.className='';$('n').textContent=s.title;document.title='⏱️ '+s.title;if(s.trkD!==curD)track();tick();};
var MEMO={};
function tick(){if(!S)return;var o=dodTick(S,Date.now());
 var mo=dodMoment(MEMO,S,o);if(mo){dodSplash(document,mo);dodSound(window,mo);}$('t').textContent=o.time;$('t').style.color=o.color;$('p').textContent=o.line;
 if(trail){trail.setAttribute('stroke',S.PA?'#5b6070':S.ACC);trail.setAttribute('stroke-dasharray',(L*Math.min(1,o.frac))+' 99999');}
 place(o.ph==='done'?0:o.frac);document.title=o.time+' · '+S.title;buttons(o);}
setInterval(tick,250);
var LASTJ=null;
setInterval(function(){try{if(!H||H.closed)return;var j=JSON.stringify(H.__dodTimer||null);
 if(j!==LASTJ){LASTJ=j;window.__dodSet(H.__dodTimer||null);}}catch(e){}},1000);
if(H&&H.__dodTimer!==undefined){LASTJ=JSON.stringify(H.__dodTimer||null);window.__dodSet(H.__dodTimer);}
"""

POP_MANAGER_JS = TIMER_CORE_JS + SPLASH_JS + r"""
(function(){
 if(window.__dodPopInit==='v4')return;window.__dodPopInit='v4';var MEMO={};
 var W=window.__dodPopW||null,base=null;
 function build(w){var d=w.document;w.__host=window;w.__dodV=4;d.title='⏱️ Focus timer';
  d.head.innerHTML='<meta name="viewport" content="width=device-width,initial-scale=1"><style>'+__CSS__+'</style>';
  d.body.innerHTML=__BODY__;var sc=d.createElement('script');sc.textContent=__PAGE__;d.body.appendChild(sc);}
 window.__dodPush=function(){if(W&&!W.closed&&W.__dodSet){try{W.__dodSet(window.__dodTimer);}catch(e){}}};
 window.__dodPopOpen=function(){
  if(W&&!W.closed){try{W.focus();}catch(e){}window.__dodPush();return true;}
  var done=function(w){if(!w)return false;
   try{if(w.__dodSet&&w.__dodV!==4){w.close();w=window.open('','dodtimer','popup,width=360,height=420');if(!w)return false;}}catch(e){}
   W=window.__dodPopW=w;try{if(!w.__dodSet)build(w);else{w.__host=window;window.__dodPush();}}catch(e){}return true;};
  if(window.documentPictureInPicture){  // Chrome desktop: a window that floats over every app
   return documentPictureInPicture.requestWindow({width:340,height:360}).then(done).catch(function(){
    return done(window.open('','dodtimer','popup,width=360,height=420'));});}
  return done(window.open('','dodtimer','popup,width=360,height=420'));};
 // a button in the pop-out presses the app's own button (switching to Today first if you're on another tab)
 window.__dodAct=function(k){
  var find=function(){var b=document.querySelector('.st-key-'+k+' button');return b&&!b.disabled?b:null;};
  var b=find();if(b){b.click();return;}
  var tab=[].slice.call(document.querySelectorAll('[role=tab]')).filter(function(t){return /Today/.test(t.textContent);})[0];
  if(tab)tab.click();var n=0,iv=setInterval(function(){var b=find();if(b){clearInterval(iv);b.click();}else if(++n>30)clearInterval(iv);},400);};
 setInterval(function(){
  var s=window.__dodTimer,d=document;
  if(base===null)base=/^(⏱️|🔧|🟡)/.test(d.title)?'Deadline or Die':d.title;
  if(s){var o=dodTick(s,Date.now());
   var mo=dodMoment(MEMO,s,o);
   if(mo){var fk='dodfin:'+s.S,seen=false;
    if(mo==='fin'){try{seen=!!sessionStorage.getItem(fk);sessionStorage.setItem(fk,'1');}catch(e){}}
    if(!seen&&!d.getElementById('dod-fin'))dodSplash(d,mo);
    var popUp=W&&!W.closed;try{popUp=popUp&&W.document.visibilityState==='visible';}catch(e){}
    if(!popUp||d.visibilityState==='visible')dodSound(window,mo);}
   if(d.title.indexOf('SESSION DONE')<0)d.title=(o.ph==='break'&&!s.PA?'🔧 ':o.ph==='done'?'🏁 ':s.PA?'🟡 ':'⏱️ ')+o.time+' · '+s.title;}
  else{if(/^(⏱️|🔧|🏁 \d|🟡)/.test(d.title))d.title=base||'Deadline or Die';d.body.classList.remove('dod-focus');}
 },1000);
})();
""".replace("__CSS__", json.dumps(POP_PAGE_CSS)).replace("__BODY__", json.dumps(POP_PAGE_BODY)).replace(
    "__PAGE__", json.dumps(POP_PAGE_JS))


def _timer_js_state(state: dict, tm: dict | None) -> str:
    """The running timer as JSON for the client clocks (our own numbers and the task's name, JSON-escaped)."""
    if not tm:
        return "null"
    t = next((x for x in state["tasks"] if x["id"] == tm.get("task_id")), None)
    trk, car = track_for(tm), state["car"]
    mid = car.get("model", "civic_si")
    sprite = carart.car_topdown(CAR_BY_ID.get(mid, CAR_BY_ID["civic_si"])["body"], car["color"], car["number"],
                                G.effective(car["parts"], mid))
    if tm.get("flow"):
        have = 1 + tm.get("period", 0) - tm.get("free_used", 0)
        can_p, p_lbl = have > 0, (f"⏸️ Pause · {have} banked" if have > 0 else "⏸️ No pause banked")
    else:
        can_p, p_lbl = True, f"⏸️ Pause · −{PM.pause_cost(tm)} 🪙"
    return json.dumps({
        "S": int(parse_dt(tm["start"]).timestamp() * 1000), "PT": int(tm.get("paused_total", 0.0) * 1000),
        "SK": int(tm.get("skipped", 0.0) * 1000),
        "PA": int(parse_dt(tm["paused_at"]).timestamp() * 1000) if tm.get("paused_at") else 0,
        "W": tm.get("work") or 0, "B": tm.get("brk") or 0, "T": tm["planned"],
        "WALL": PM.wall_minutes(tm["planned"], tm.get("work") or None, tm.get("brk") or None),
        "FL": bool(tm.get("flow")), "CHK": int(tm.get("check", 0)), "ACC": accent(state)[0],
        "title": (t["title"] if t else "Focus session")[:60],
        "trkD": trk["d"], "trkL": f"{trk['name'].upper()} · {trk['km']:.3f} KM · {trk['series']}", "sprite": sprite,
        "canPause": can_p, "pauseLabel": p_lbl,
        "GT": "pins" in tm, "PI": int(tm.get("pins", 0)), "PO": int(tm.get("pouts", 0))}).replace("</", "<\\/")


def _timer_hook_js(state_json: str) -> str:
    """Runs in each clock frame: hands the page the latest timer and installs the pop-out manager once."""
    mgr = json.dumps(POP_MANAGER_JS).replace("</", "<\\/")
    return (f"(function(){{var P;try{{P=parent;P.document;}}catch(e){{return;}}"
            f"var s={state_json};if(s)s.OFF=(function(d){{return Math.abs(d)>120000?Math.round(d/900000)*900000:0}})"
            f"({int(time.time() // 60 * 60000)}-Date.now());P.__dodTimer=s;"
            f"if(P.__dodPopInit!=='v4'){{var sc=P.document.createElement('script');sc.textContent={mgr};"
            f"P.document.body.appendChild(sc);sc.remove();}}if(P.__dodPush)P.__dodPush();}})();")


def _popout_click_js() -> str:
    return "try{parent.__dodPopOpen&&parent.__dodPopOpen();}catch(e){}"


def render_timer_float(state: dict) -> None:
    """Off the Today page: a small clock floating in the corner (tap Open to jump back, ⧉ to pop it out).
    When no timer runs it still tells the page (and any pop-out) the session is over."""
    tm = state.get("timer")
    _embed = st.iframe if hasattr(st, "iframe") else __import__("streamlit.components.v1", fromlist=["html"]).html
    if not tm:
        if st.session_state.pop("_had_timer", False):
            with st.container(key="timer_gone"):
                _embed(f"<script>{_timer_hook_js('null')}</script>", height=1)
        return
    st.session_state["_had_timer"] = True
    sj = _timer_js_state(state, tm)
    with st.container(key="float_timer"):
        c1, c2 = st.columns([3, 1.1], vertical_alignment="center")
        with c1:
            _embed(f"""<style>body{{margin:0;font-family:system-ui,-apple-system,sans-serif;color:#ece8df;overflow:hidden}}
.r{{display:flex;align-items:center;gap:10px;height:40px}}#t{{font:800 21px/1 system-ui,sans-serif;font-variant-numeric:tabular-nums}}
#bar{{position:absolute;left:0;right:0;bottom:0;height:3px;background:#2a2f3a;border-radius:2px;overflow:hidden}}
#bar i{{display:block;height:100%;width:0;background:#f5c518;transition:width .5s linear}}
.m{{min-width:0;flex:1}}#n{{font-size:12px;color:#ece8df;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
#p{{font-size:11px;color:#8b909c;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
button{{background:#262b36;border:1px solid #3a4050;color:#ece8df;border-radius:8px;font-size:15px;width:34px;height:34px;cursor:pointer;flex:none}}</style>
<div class="r"><div id="t">--:--</div><div class="m"><div id="n"></div><div id="p"></div></div>
<button title="Pop out into its own window" onclick="{_popout_click_js()}">⧉</button></div><div id="bar"><i id="bi"></i></div>
<script>{TIMER_CORE_JS}
var S={sj};document.getElementById('n').textContent=S.title;{_timer_hook_js(sj)}
S.OFF=parent.__dodTimer?parent.__dodTimer.OFF:0;
function f(){{var o=dodTick(S,Date.now());var t=document.getElementById('t');t.textContent=o.time;t.style.color=o.color;
document.getElementById('p').textContent=o.line;var b=document.getElementById('bi');
b.style.width=Math.round(Math.max(0,Math.min(1,o.frac||0))*100)+'%';b.style.background=o.color||'#f5c518';
var box=frameElement&&frameElement.closest('.st-key-float_timer');
if(box){{box.classList.toggle('dod-due',!!(o.due||o.ph==='done'));}}}}
f();setInterval(f,500);
// hide the bar while the big timer itself is on screen (it comes back as soon as you scroll away or change tabs)
(function(){{var P=parent.document,PW=parent,box=frameElement&&frameElement.closest('.st-key-float_timer');if(!box)return;
 function chk(){{var h=PW.innerHeight,vis=false;
  P.querySelectorAll('.st-key-tg_live, .st-key-tg_timer').forEach(function(el){{var r=el.getBoundingClientRect();
   if(r.height>40&&r.top<h-40&&r.bottom>40)vis=true;}});  // any of the big timer on screen: one clock only
  box.classList.toggle('dod-hidebar',vis);}}
 chk();setInterval(chk,500);PW.addEventListener('scroll',chk,true);}})();</script>""", height=44)
        with c2:
            with st.container(key="bar_norm"):
                st.button("Timer", key="float_open", use_container_width=True, on_click=_go_tab,
                          args=("🏁 Today", "timer"), help="Jump to the full timer: pause, extend, pit, stop")
            with st.container(key="bar_end", horizontal=True, gap="small"):
                if st.button("🌊", key="bar_flow", help=f"Keep going (+{FLOW_STEP} min, or the next flow check-in)"):
                    timer_keep_going(state)
                    st.rerun(scope="app")
                if st.button("⏹️", key="bar_stop", help="Stop & log"):
                    timer_stop_log(state)
                    st.rerun(scope="app")


def _timer_ring(state: dict, tm: dict, big: bool = False) -> None:
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
    pop, hook = _popout_click_js(), _timer_hook_js(_timer_js_state(state, tm))
    _embed(f"""
<link href="https://fonts.googleapis.com/css2?family=Saira+Semi+Condensed:wght@700&display=swap" rel="stylesheet">
<style>
body{{margin:0;font-family:system-ui,sans-serif;color:#ece8df;overflow:hidden}}
.w{{display:flex;flex-direction:column;align-items:center}}
svg{{width:100%;max-width:{660 if big else 340}px;height:auto;display:block}}
.bt{{display:flex;gap:8px;justify-content:center;margin:8px 0 2px}}.bt button{{background:#1f232c;border:1px solid #343a47;color:#ece8df;border-radius:999px;padding:6px 14px;font:600 13px system-ui,sans-serif;cursor:pointer}}.bt button:hover{{border-color:{acc}}}#s{{font-size:{15 if big else 12.5}px!important}}
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
 <g id="lane"></g>
 <path id="trail" d="{trk['d']}" fill="none" stroke="{acc}" stroke-width="2.6" stroke-linecap="round"
   stroke-linejoin="round" stroke-dasharray="0 99999" opacity=".95"/>
 <g id="ticks"></g>
 <g id="sf"></g>
 <g id="crew"><circle id="c1" r="1.4" fill="#2ec4b6"/><circle id="c2" r="1.4" fill="#2ec4b6"/></g>
 <text id="pitl" font-size="6" font-weight="700" fill="#2ec4b6" text-anchor="middle" opacity="0">PIT</text>
 <text id="t" x="146" y="164" text-anchor="end"></text>
 <text id="p" x="154" y="160" text-anchor="start"></text>
 <g id="car"><circle id="halo" r="10" fill="#f5c518"/>{sprite}</g>
</svg><div id="flag"><i></i><b></b></div><div id="s"></div><div class="bt"><button onclick="{pop}" title="Open the clock in its own small window">⧉ Pop out</button><button id="fw" onclick="dodFocus(false)" title="Just the timer, filling this browser tab">▣ Fill tab</button><button id="fs" onclick="dodFocus(true)" title="Just the timer, filling the whole screen">⛶ Full screen</button></div></div>
<script>
// sounds mix with your music instead of pausing it (iOS 17+ audio session; harmless elsewhere)
try{{if(navigator.audioSession)navigator.audioSession.type='ambient';
 if(parent.navigator.audioSession)parent.navigator.audioSession.type='ambient';}}catch(e){{}}
const S={start_ms},PT={pt},SK={sk},PA={pa},W={work},B={brk},T={T},WALL={wall},LIM={limit},ACC='{acc}';
const OFF=(d=>Math.abs(d)>120000?Math.round(d/900000)*900000:0)({int(time.time() // 60 * 60000)}-Date.now());  // a device clock set wrong by hours (e.g. the wrong time zone picked) can't skew the timer
const TICKS=[{ticks}],EXT={ext},FL={'true' if tm.get('flow') else 'false'},CHK={int(tm.get('check', 0))};
const GT={'true' if 'pins' in tm else 'false'},PI={int(tm.get('pins', 0))},PO={int(tm.get('pouts', 0))};
function finish(){{  // whole-page "you're done" you can catch from across the room: once per session
 let P;try{{P=parent.document;}}catch(e){{return;}}
 const key='dodfin:'+S;try{{if(parent.sessionStorage.getItem(key))return;parent.sessionStorage.setItem(key,'1');}}catch(e){{}}
 if(P.getElementById('dod-fin'))return;
 const st=P.createElement('style');st.id='dod-fin-css';st.textContent=`
#dod-fin{{position:fixed;inset:0;z-index:999999;pointer-events:none;overflow:hidden;animation:dfo .7s ease 6.6s forwards}}
@keyframes dfo{{to{{opacity:0;visibility:hidden}}}}
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
 P.body.appendChild(o);
 // cleanup runs in the PAGE, not in this iframe: the app reruns right after a session ends and this frame is
 // thrown away, which used to take its timers with it and leave the flag on screen. CSS fades it out regardless.
 const sc=P.createElement('script');sc.textContent=`(function(){{
  setTimeout(function(){{var o=document.getElementById('dod-fin'),c=document.getElementById('dod-fin-css');
   if(o)o.remove();if(c)c.remove();}},7600);
  var t0=document.title.replace(/^🏁 SESSION DONE$/,'')||'Deadline or Die',on=true;
  var iv=setInterval(function(){{document.title=on?'🏁 SESSION DONE':t0;on=!on;}},900);
  function stop(){{clearInterval(iv);document.title=t0;}}
  window.addEventListener('focus',stop,{{once:true}});document.addEventListener('pointerdown',stop,{{once:true}});
  setTimeout(stop,600000);}})();`;
 P.body.appendChild(sc);sc.remove();
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
// 🔧 pit lane: peels off just before the start/finish line, the box sits beside the line, rejoins just after.
// Every stint is one lap ending at the line, so the car drives into the pit for its break and back out after.
const O=10,E=Math.min(28,L*.075),ST=!!(W&&B&&!FL);
function sm(t){{t=Math.max(0,Math.min(1,t));return t*t*(3-2*t);}}
function ptd(d){{d=((d%L)+L)%L;const a=tr.getPointAtLength(d),b=tr.getPointAtLength((d+1)%L);return [a.x,a.y,Math.atan2(b.y-a.y,b.x-a.x)];}}
// a straight lane beside the start/finish line, on whichever side has more room (real pit lanes don't hug corners)
const tx=Math.cos(a0),ty=Math.sin(a0);
function room(sg){{let m=1e9;for(let i=0;i<120;i++){{const p=tr.getPointAtLength(L*i/120);
 for(let t=-E*.4;t<=E*.4;t+=E*.2){{const lx=p0.x+t*tx+sg*O*nx,ly=p0.y+t*ty+sg*O*ny;m=Math.min(m,Math.hypot(p.x-lx,p.y-ly));}}}}return m;}}
const SG=room(1)>=room(-1)?1:-1;nx*=SG;ny*=SG;  // nx,ny now point at the pit side
function lp(t){{const q=ptd(t),w=sm((E-Math.abs(t))/(E*.6));  // on the track at the ends, on the lane in the middle
 return [q[0]+(p0.x+t*tx+O*nx-q[0])*w,q[1]+(p0.y+t*ty+O*ny-q[1])*w];}}
function lq(t){{const a=lp(t),b=lp(t+.8);return [a[0],a[1],Math.atan2(b[1]-a[1],b[0]-a[0])];}}
const [PX,PY]=lp(0);
if(ST){{let dd='';for(let t=-E;t<=E+.01;t+=1){{const q=lp(t);dd+=(dd?'L':'M')+q[0].toFixed(1)+','+q[1].toFixed(1);}}
 const ln=document.getElementById('lane');
 [['#2b303c',5,''],['#4a5162',.6,'2 3']].forEach(([c,wd_,da])=>{{const pp=document.createElementNS(NS,'path');pp.setAttribute('d',dd);
  pp.setAttribute('fill','none');pp.setAttribute('stroke',c);pp.setAttribute('stroke-width',wd_);pp.setAttribute('stroke-linecap','round');
  pp.setAttribute('stroke-linejoin','round');if(da)pp.setAttribute('stroke-dasharray',da);ln.appendChild(pp);}});
 const bx=document.createElementNS(NS,'rect');bx.setAttribute('x',-3.4);bx.setAttribute('y',-2.6);bx.setAttribute('width',6.8);
 bx.setAttribute('height',5.2);bx.setAttribute('rx',.8);bx.setAttribute('fill','none');bx.setAttribute('stroke','#2ec4b6');
 bx.setAttribute('stroke-width',.6);bx.setAttribute('opacity',.8);bx.setAttribute('transform','translate('+PX+','+PY+') rotate('+(a0*180/Math.PI)+')');
 ln.appendChild(bx);}}
document.getElementById('c1').setAttribute('cx',PX-ny*8);document.getElementById('c1').setAttribute('cy',PY+nx*8);
document.getElementById('c2').setAttribute('cx',PX+ny*8);document.getElementById('c2').setAttribute('cy',PY-nx*8);
const pl=document.getElementById('pitl');pl.setAttribute('x',PX+nx*8);pl.setAttribute('y',PY+ny*8+2);
if(!ST)TICKS.forEach(f=>{{const [a,ang]=at(f),dx=-Math.sin(ang)*5,dy=Math.cos(ang)*5,l=document.createElementNS(NS,'line');
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
function put(q){{car.setAttribute('transform','translate('+q[0]+','+q[1]+') rotate('+(q[2]*180/Math.PI)+') scale(.85)');}}
function frame(){{
 const now=Date.now()+OFF,e=eff(now),wd=Math.min(wdone(e),T),f=FL?(e%25)/25:wd/T;  // flow: a lap every 25 min
 let ph='work',left=(T-e)*60000;
 if(wd>=T)ph='done';
 else if(W&&B){{const c=W+B,r=e%c;if(r<W)left=Math.min(W-r,T-wd)*60000;else{{ph='break';left=(c-r)*60000;}}}}
 let gate='',over=0;  // pit in / pit out wait for your confirm
 if(GT&&W&&B&&!FL){{const c=W+B;  // from the pit ins/outs you've confirmed
  if(PI>PO){{if(e>=PI*c){{gate='pitout';over=e-PI*c;}}}}
  else if(e>=PI*c+W&&(PI+1)*W<T){{gate='pitin';over=e-PI*c-W;}}}}
 const pit=(ph==='break'&&gate!=='pitin'||gate==='pitout')&&!PA;
 let lf=f;
 if(ph==='done'){{lf=1;put(ptd(0));}}  // chequered flag: parked on the line
 else if(ST&&(pit||ph==='break'||gate==='pitin')){{lf=1;put(lq(0));}}  // in the box
 else if(ST){{const n=TICKS.length+1,k=Math.min(Math.floor(wd/W+1e-9),n-1),len=Math.min(W,T-k*W);
  lf=Math.min(1,Math.max(0,(wd-k*W)/len));const d=lf*L;
  put(k>0&&d<E?lq(d):k<n-1&&d>L-E?lq(d-L):ptd(d));}}  // out of the pit lane after a break / boxing at the end of a stint
 else put(ptd(Math.min(.9999,Math.max(0,f))*L));
 trail.setAttribute('stroke-dasharray',(L*Math.min(1,lf))+' 99999');
 w.className='w'+(PA?' blink':'')+(pit?' pit':'')+(ph==='done'&&!PA?' fin':'');
 pl.setAttribute('opacity',pit?1:0);
 const sec=Math.floor(now/1000);
 if(sec!==shown){{shown=sec;
  const t=document.getElementById('t'),p=document.getElementById('p'),s=document.getElementById('s');
  const blk=W&&B?Math.min(TICKS.length+1,Math.floor(e/(W+B))+1):1,stints=TICKS.length+1;
  if(PA){{t.textContent=mmss(left);t.style.fill='#8b909c';trail.style.stroke='#5b6070';
    p.textContent='🟡 Yellow flag';s.textContent='Paused '+mmss(now-PA)+' · retires the car at '+LIM+':00';}}
  else if(gate==='pitin'){{t.textContent='+'+mmss(over*60000);t.style.fill='#f5c518';trail.style.stroke=ACC;
    p.textContent='🔧 Box, box';s.textContent='Stint done. Pit in when you’re ready: the break starts then.';}}
  else if(gate==='pitout'){{t.textContent='+'+mmss(over*60000);t.style.fill='#3ddc84';trail.style.stroke=ACC;
    p.textContent='🟢 Pit out?';s.textContent='Break’s up. Pit out to start the next stint.';}}
  else if(ph==='done'){{t.textContent='+'+mmss((e-WALL)*60000);t.style.fill='#ff6a5c';trail.style.stroke=ACC;
    p.textContent='🏁 Chequered flag';s.textContent='Session complete. Stop & log it.';}}
  else if(pit){{t.textContent=mmss(left);t.style.fill='#2ec4b6';trail.style.stroke=ACC;
    p.textContent='🔧 Pit stop';s.textContent='Tyres, water, stretch. No phone in the pit lane.';}}
  else if(FL){{t.textContent=mmss(e*60000);t.style.fill=e>=CHK?'#29e3ff':ACC;trail.style.stroke=ACC;
    p.textContent=e>=CHK?'🌊 Check-in':'🌊 Flow · lap '+(Math.floor(e/25)+1);
    s.textContent=e>=CHK?'Still flowing? Tap below to keep going.':'Counting up · check-in at '+CHK+' min · phone face-down';
}}
  else{{t.textContent=mmss(left);t.style.fill=ACC;trail.style.stroke=ACC;
    p.textContent=EXT>0?('🌊 Flow · +'+EXT+' min'):stints>1?('Stint '+blk+' of '+stints):'Green flag';
    s.textContent=Math.round(wd)+' of '+T+' min · phone face-down';}}
  last=PA?'pause':ph;
  if(ph==='done'&&!PA)finish();}}
 requestAnimationFrame(frame);}}
frame();
{hook}
function dodFocus(full){{var P;try{{P=parent.document;}}catch(e){{return;}}
 var on=!P.body.classList.contains('dod-focus');P.body.classList.toggle('dod-focus',on);
 try{{var bg=getComputedStyle(P.querySelector('.stApp')).backgroundColor;P.body.style.setProperty('--dodbg',bg);}}catch(e){{}}
 try{{if(on&&full){{var el=P.documentElement;(el.requestFullscreen||el.webkitRequestFullscreen||function(){{}}).call(el);}}
  else if(!on&&(P.fullscreenElement||P.webkitFullscreenElement)){{(P.exitFullscreen||P.webkitExitFullscreen).call(P);}}}}catch(e){{}}
 fsLbl();}}
function fsLbl(){{try{{var on=parent.document.body.classList.contains('dod-focus');
 var sv=document.querySelector('svg');if(sv)sv.style.maxWidth=on?Math.max(340,Math.round((parent.innerHeight-330)*300/172))+'px':'';
 setTimeout(fit,50);
 document.getElementById('fs').style.display=on?'none':'';
 document.getElementById('fw').textContent=on?'✕ Exit':'▣ Fill tab';}}catch(e){{}}}}
fsLbl();
try{{parent.addEventListener('resize',fsLbl);}}catch(e){{}}
try{{parent.document.addEventListener('fullscreenchange',function(){{if(!parent.document.fullscreenElement){{parent.document.body.classList.remove('dod-focus');fsLbl();}}}});}}catch(e){{}}
function fit(){{try{{var h=Math.ceil(document.getElementById('w').getBoundingClientRect().height+6),el=window.frameElement;
 for(var i=0;i<4&&el;i++){{var tid=el.getAttribute('data-testid');if(i===0||el.style.height||tid==='stElementContainer'){{el.style.setProperty('height',h+'px','important');el.style.setProperty('min-height','0','important');el.style.setProperty('flex','none','important');}}if(tid==='stElementContainer')break;el=el.parentElement;}}}}catch(e){{}}}}
fit();new ResizeObserver(fit).observe(document.body);
</script>""", height=(380 if big else 262))  # our own static markup only — no user content goes in here


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
    full = mins >= 25 if tm.get("flow") else mins >= tm["planned"]
    t["focus_min"] = round(t.get("focus_min", 0) + mins, 2)
    state.setdefault("focus_log", []).append({"date": start.date().isoformat(), "task": t["id"],
                                              "min": round(mins, 2), "sec": int(round(mins * 60)), "full": full,
                                              "start": start.isoformat(), "cat": t.get("category")})
    del state["focus_log"][:-500]
    state["xp"] += int(mins // 5)
    drop_msg, snd = "", ("win" if full else None)
    today_log = [x for x in state["focus_log"] if x["date"] == now().date().isoformat()]
    rolls = int(mins // 25) if tm.get("flow") else 1  # a flow run gets a roll per 25 min, like a stack of sessions
    left_today = EV.DROPS_PER_DAY - sum(x.get("drops", 1) for x in today_log if x.get("drop"))
    msgs_ = []
    for _r in range(max(0, min(rolls, left_today)) if full and mins >= 25 else 0):
        kind = EV.roll_drop()
        state["focus_log"][-1]["drop"] = kind
        state["focus_log"][-1]["drops"] = _r + 1
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
        msgs_.append(drop_msg)
        snd = "jackpot" if kind in ("double_token", "upgrade_token") or snd == "jackpot" else "win"
    if len(msgs_) > 1:
        drop_msg = "  \n".join(msgs_)
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
    unserved = [p for p in state["penalty_box"] if not p["served"]]
    if unserved:
      with fold("penalty", f"🚨 **Penalty box** :gray[{len(unserved)}]", card=True) as _fo:
          if _open(_fo):  # collapsed = not built (faster page, smaller download)
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
    with fold("contracts", "📜 This week's contracts", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            render_contracts(state)
    with fold("ledger", "🧾 Coin ledger", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            if not state["ledger"]:
                st.caption("Nothing yet.")
            for e in state["ledger"][:15]:
                st.markdown(f"`{'+' if e['delta'] >= 0 else ''}{e['delta']:>5}` {e['reason']} "
                            f"<small>· {parse_dt(e['ts']):%b %d %I:%M %p}</small>", unsafe_allow_html=True)
    with fold("rules", "📖 Rules", False):
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
    # booked roadmap blocks show up on their own day, not as clutter before then
    rest = [t for t in open_tasks if t["id"] not in in_mission
            and not (t.get("block") and t["block"]["date"] > today)]
    _rd = [t for t in state["tasks"] if t["status"] == "failed" and not t.get("abandoned")
           and now() - parse_dt(t["failed_at"]) < timedelta(hours=REDEEM_WINDOW_H)]
    with fold("task_board", f"📋 **Everything else** :gray[{len(rest)} open"
              + (f" · {len(_rd)} to redeem" if _rd else "") + "]", card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            render_quick_add(state, "qa_top", boxed=False)
            if rest and (parse_dt(rest[0]["deadline"]) - now()) < timedelta(hours=6):
                st.warning(f"⏱️ **{rest[0]['title']}** dies in {fmt_left(parse_dt(rest[0]['deadline']) - now())} — "
                           f"−{rest[0]['penalty']} and {MISS_DAMAGE}% of your car. Start for 10 minutes.")
            for t in rest:
                render_task_row(state, t, "tb_")
            if not open_tasks:
                st.caption("Nothing open. Type one above, or tap a one-tap task.")
            redeemable = [t for t in state["tasks"] if t["status"] == "failed" and not t.get("abandoned")
                          and now() - parse_dt(t["failed_at"]) < timedelta(hours=REDEEM_WINDOW_H)]
            if redeemable:
                with st.container(border=True, key="tb_redeem_box"):
                    st.markdown(f"<div class='dod-sub red'>🩹 Missed · redeem for half back <span>{len(redeemable)}</span></div>",
                                unsafe_allow_html=True)
                    for t in redeemable:
                        left = parse_dt(t["failed_at"]) + timedelta(hours=REDEEM_WINDOW_H) - now()
                        with st.expander(f"💀 {t['title']} · by {_when(now() + left)}", key=f"exp_tb_{t['id']}",
                                         expanded=proof_open(f"tb_redeem_{t['id']}")):
                            render_proof_form(state, t, "redeem", scope="tb_")


READING_LABELS = {"unread": "To read", "reading": "Reading", "read": "Read", "dropped": "Dropped"}
READING_SORTS = {"Rank": lambda p: p.get("rank") or 9999,
                 "Read order": lambda p: p["order"] or "~",
                 "Newest first": lambda p: -int(p["year"]) if p["year"].isdigit() else 1,
                 "Oldest first": lambda p: int(p["year"]) if p["year"].isdigit() else 9999,
                 "Title": lambda p: p["title"].casefold(),
                 "Author": lambda p: p["who"].casefold() or "~",
                 "Question": lambda p: (sorted(p["facets"].get("question", [])) or ["~"])[0],
                 "Subject": lambda p: (p["facets"].get("subject", []) or ["~"])[0].casefold()}
READING_FILTERS = {"question": "Question", "subject": "Subject", "species": "Species", "sex": "Sex", "type": "Type", "source": "Added by", "scholarship": "Scholarship"}


def _paper_tags(p: dict) -> list[str]:
    """A paper's clickable tags as "filter|value". Its subject mostly repeats its question, so it only shows without one."""
    f = {k: p["facets"].get(k, []) for k in ("question", "subject", "species", "sex", "type", "source")}
    tags = [("question", v) for v in sorted(f["question"])] + ([] if f["question"] else [("subject", v) for v in f["subject"]])
    tags += ([("year", p["year"])] if p.get("year") else []) + [(n, v) for n in ("species", "sex", "type", "source", "scholarship") for v in f[n]]
    return [f"{n}|{v}" for n, v in tags]


def _toggle_tag_filters(widget: str, before: list[str]) -> None:
    """Runs when a tag is clicked: clicking one filters by it, clicking it again takes the filter off."""
    for tag in set(st.session_state.get(widget) or []) ^ set(before):
        name, value = tag.split("|", 1)
        key = f"reading_f_{name}"
        current = list(st.session_state.get(key) or [])
        st.session_state[key] = [v for v in current if v != value] if value in current else current + [value]


def _clear_reading_filters() -> None:
    for name in (*READING_FILTERS, "year"):
        st.session_state[f"reading_f_{name}"] = []
    st.session_state["reading_search"] = ""


def _set_paper_status(zc: tuple, p: dict, widget: str) -> None:
    """Runs when a paper's status control changes. Saves to Zotero, or puts the control back if that fails."""
    new = {v: k for k, v in READING_LABELS.items()}.get(st.session_state.get(widget))
    if not new:  # tapping the selected option clears it: treat that as no change
        st.session_state[widget] = READING_LABELS[p["status"]]
        return
    try:
        Z.set_status(zc[0], zc[1], p["key"], new, zc[2])
    except Exception as e:
        st.session_state[widget] = READING_LABELS[p["status"]]
        flash(f"Couldn't update that paper: {e}", "error")
        return
    _zotero_reading.clear()
    _zotero_list.clear()
    if new in ("read", "dropped") and any(p["key"] in paper_keys(t) and t["status"] == "open" for t in state["tasks"]):
        flash(f"📄 Marked **{READING_LABELS[new].lower()}**. Its task is still open on your list.", "warning")


@swr(600)
def _zotero_inbox(user: str, key: str, coll: str) -> tuple[str | None, list[dict]]:
    box = Z.inbox_folder(user, key, coll, create=True)
    return box, (Z.inbox_items(user, key, box) if box else [])


INBOX_READ_COINS = 5     # a paper you'd already read before it reached the list: a small thank-you, not a task's pay
INBOX_READ_MIN = 30      # logged as 30 focus minutes
INBOX_READ_PER_DAY = 3   # rewards stop after 3 a day; filing still works


def _inbox_rewards_today(state: dict) -> int:
    """Rewarded inbox filings made today (counted by when you filed them, not when you read them)."""
    return sum(1 for t in state["tasks"] if t.get("source") == "inbox-read" and t.get("earned")
               and (t.get("created") or "")[:10] == now().date().isoformat())


def _file_already_read(state: dict, it: dict, when: datetime, rewarded: bool) -> dict:
    """Records a paper you'd already read as a finished 30-minute deep-work task at the time you read it, so it
    counts in Stats, the recap and the scrapbook like any other task. The reward is the small inbox one."""
    when = min(when, now())
    t = make_task(f"📄 Read: {it['title'][:80]}", f"Already read before it reached the list (filed from the Inbox). {it['url']}",
                  when, category="deep", minutes=INBOX_READ_MIN, source="inbox-read")
    coins = INBOX_READ_COINS if rewarded else 0
    t.update({"status": "done", "completed_at": when.isoformat(), "reward": coins, "earned": coins,
              "minutes": INBOX_READ_MIN, "focus_min": INBOX_READ_MIN, "zotero_key": it["key"], "zotero_keys": [it["key"]],
              "proof_note": f"Already read. {INBOX_READ_MIN} min logged."})
    state["tasks"].append(t)
    start = when - timedelta(minutes=INBOX_READ_MIN)
    state.setdefault("focus_log", []).append({"date": start.date().isoformat(), "task": t["id"], "min": INBOX_READ_MIN,
                                              "full": False, "start": start.isoformat(), "cat": "deep"})
    if rewarded:
        bank(state, coins, f"📥 Already read: {it['title'][:50]}")
        state["xp"] += INBOX_READ_MIN // 5
    return t


def render_paper_inbox(state: dict, zc: tuple, papers: list[dict]) -> None:
    """📥 Papers you saved to the Zotero "Inbox" folder yourself. A short questionnaire per paper files it:
    already read → Read (a few coins + 30 focus min, no read order); not yet → To Read at the level and number
    you pick, bumping that level down. Either way it's tagged "manual entry"."""
    try:
        box, items = _zotero_inbox(*zc)
    except Exception as e:  # noqa: BLE001
        st.caption(f"(Couldn't check the Zotero Inbox: {e})")
        return
    if not box or not items:
        st.session_state.pop("inbox_open", None)
        return
    n_ = f"{len(items)} paper{'s' * (len(items) != 1)}"
    if not st.session_state.get("inbox_open"):
        c1, c2 = st.columns([3, 1.3], vertical_alignment="center")
        c1.markdown(f"📥 **{n_} in your Zotero Inbox**")
        if c2.button("📥 Import from Inbox", key="inbox_import", type="primary", use_container_width=True):
            st.session_state["inbox_open"] = True
            st.rerun()
        return
    with st.container(border=True):
        h1, h2 = st.columns([3, 1], vertical_alignment="center")
        h1.markdown(f"#### 📥 Import from Inbox · {n_}")
        if h2.button("Later", key="inbox_close", use_container_width=True):
            st.session_state.pop("inbox_open", None)
            st.rerun()
        for it in items:
            k = it["key"]
            st.markdown(f"<a href='{html.escape(it['url'], quote=True)}' target='_blank'>{html.escape(it['title'])}</a>"
                        f"<br><small style='color:#8b909c'>{html.escape(' · '.join(x for x in (it['who'], it['year'], it['journal']) if x))}</small>",
                        unsafe_allow_html=True)
            done_ = st.segmented_control(f"Already read {it['title'][:60]}?", ["Not yet", "Already read it"],
                                         default="Not yet", key=f"inbox_read_{k}") or "Not yet"
            qs = st.multiselect("Questions it answers", Z.QUESTIONS, key=f"inbox_q_{k}", placeholder="Optional")
            lv = num = None
            if done_ != "Not yet":
                c1, c2 = st.columns(2)
                rd = c1.date_input("Read on", now().date(), max_value=now().date(), key=f"inbox_d_{k}")
                rt = c2.time_input("Finished at", now().replace(second=0, microsecond=0).time(), step=900, key=f"inbox_t_{k}")
            if done_ == "Not yet":
                c1, c2 = st.columns(2)
                lv = c1.selectbox("Level", [*Z.LEVELS, ""], key=f"inbox_lv_{k}", index=1,
                                  format_func=lambda x: f"{x} · {Z.LEVELS[x]}" if x else "No order yet (set it later)")
                if lv:
                    size = sum(1 for p in papers if p["order"].startswith(lv))
                    num = c2.number_input(f"Number (1–{size + 1}; later papers in {lv} move down)", 1, size + 1, size + 1,
                                          key=f"inbox_n_{k}")
            left = INBOX_READ_PER_DAY - _inbox_rewards_today(state)
            label = ("📚 File as read" + (f" · +{INBOX_READ_COINS} 🪙 · {INBOX_READ_MIN} min" if left > 0 else "")
                     if done_ != "Not yet" else f"➕ Add to reading list{f' as {lv}{int(num):02d}' if lv else ''}")
            if st.button(label, key=f"inbox_go_{k}", type="primary", use_container_width=True):
                try:
                    Z.file_from_inbox(zc[0], zc[1], k, "read" if done_ != "Not yet" else "unread", qs, zc[2])
                    code = Z.place(zc[0], zc[1], papers, k, lv, int(num)) if lv else ""
                except Exception as e:  # noqa: BLE001
                    flash(f"Couldn't file that paper: {e}", "error")
                    st.rerun()
                if done_ != "Not yet":
                    t_ = _file_already_read(state, it, datetime.combine(rd, rt, TZ), left > 0)
                    save_state(state)
                    when_ = parse_dt(t_["completed_at"])
                    flash(f"📚 Filed as read on {when_:%a %b} {when_.day}, {when_:%H:%M} · {INBOX_READ_MIN} min logged"
                          + (f" · +{INBOX_READ_COINS} coins." if left > 0 else f". (Coins cap at {INBOX_READ_PER_DAY} a day.)"))
                else:
                    flash(f"➕ Added to your reading list{' as ' + code if code else ', not ordered yet'}.")
                _zotero_inbox.clear()
                _zotero_reading.clear()
                _zotero_list.clear()
                st.rerun()
            st.divider()
        st.caption("Save papers into the Inbox folder under LCR HCR CVxR with the Zotero browser button. "
                   "They're all tagged “manual entry”.")


@swr(600)
def _zotero_topics(user: str, key: str, coll: str) -> list[str]:
    return Z.search_topics(user, key, coll)


def render_search_topics(zc: tuple) -> None:
    """🔎 Extra topics the Sunday search looks for, beyond the guiding questions. Search only: no tags."""
    try:
        topics = _zotero_topics(*zc)
    except Exception as e:  # noqa: BLE001
        st.caption(f"(Couldn't read the search topics: {e})")
        return
    with fold("search_topics", f"🔎 Sunday search topics ({len(topics)})", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            st.caption("The Sunday run searches these on top of your guiding questions. Papers it finds for them join the "
                       "reading list like any other; no tag is added for a topic. They're kept as folders under "
                       "LCR HCR CVxR → Search topics in Zotero, so you can add one there too.")

            def _save(fn, topic: str, msg: str) -> None:
                try:
                    fn(zc[0], zc[1], topic, zc[2])
                    _zotero_topics.clear()
                    flash(msg)
                except Exception as e:  # noqa: BLE001
                    flash(f"Couldn't save that: {e}", "error")
                st.rerun()

            for i, t_ in enumerate(topics):
                c1, c2 = st.columns([6, 1], vertical_alignment="center")
                c1.markdown(f"• {html.escape(t_)}")
                if c2.button("✕", key=f"topic_rm_{i}", help="Stop searching for this", use_container_width=True):
                    _save(Z.remove_search_topic, t_, f"🔎 Removed **{t_}**.")
            with st.form("topic_add", clear_on_submit=True, border=False):
                c1, c2 = st.columns([6, 1], vertical_alignment="bottom")
                new_ = c1.text_input("New topic", placeholder="e.g. Diaphragm anatomy and remodelling")
                if c2.form_submit_button("Add", use_container_width=True) and new_.strip():
                    if new_.strip().casefold() in {x.casefold() for x in topics}:
                        flash("That topic is already on the list.", "warning")
                        st.rerun()
                    _save(Z.add_search_topic, new_.strip(), f"🔎 Added **{new_.strip()}**. The next Sunday run searches for it.")


def render_reading_list(state: dict) -> None:
    zc = zotero_cfg(state)
    zotero_fresh(zc)
    if not zc:
        st.caption("Add ZOTERO_USER_ID and ZOTERO_API_KEY in Settings to see your reading list here.")
        return
    try:
        papers = _zotero_reading(*zc)
    except Exception as e:
        st.caption(f"(Couldn't read Zotero: {e})")
        return
    render_paper_inbox(state, zc, papers)
    if not papers:
        st.caption(f"Nothing in “{zc[2]}” yet.")
        return
    count = {s_: sum(p["status"] == s_ for p in papers) for s_ in READING_LABELS}
    kept = len(papers) - count["dropped"]
    st.progress(count["read"] / kept if kept else 0.0,
                text=f"{count['read']} of {kept} read" + (f" · {count['reading']} in progress" if count["reading"] else "")
                     + (f" · {count['dropped']} dropped" if count["dropped"] else ""))
    views = {"To read": ("unread", "reading"), "Read": ("read",), "Dropped": ("dropped",),
             "All": ("unread", "reading", "read", "dropped")}
    view = st.segmented_control("Show", list(views), default="To read", key="reading_view",
                                label_visibility="collapsed") or "To read"
    ss_ = st.session_state  # folded away = the section isn't built, so fall back to whatever was last picked
    sort = ss_.get("reading_sort") or list(READING_SORTS)[0]
    search = (ss_.get("reading_search") or "").strip().casefold()
    picked = {f: ss_.get(f"reading_f_{f}") or [] for f in READING_FILTERS}
    picked_years = ss_.get("reading_f_year") or []
    with fold("reading_filter", "🔎 Sort and filter", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            c1, c2 = st.columns(2)
            sort = c1.selectbox("Sort by", list(READING_SORTS), key="reading_sort")
            search = c2.text_input("Search", placeholder="Title, author or journal", key="reading_search").strip().casefold()
            options = {f: sorted({v for p in papers for v in p["facets"].get(f, [])}) for f in READING_FILTERS}
            years = sorted({p["year"] for p in papers if p["year"]}, reverse=True)
            cols = st.columns(2)
            picked = {f: cols[i % 2].multiselect(READING_FILTERS[f], options[f], key=f"reading_f_{f}")
                      for i, f in enumerate(READING_FILTERS) if options[f]}
            picked_years = cols[len(picked) % 2].multiselect("Year", years, key="reading_f_year")
    filtered = bool(search or picked_years or any(picked.values()))
    shown = [p for p in papers if p["status"] in views[view]
             and (not picked_years or p["year"] in picked_years)
             and all(not vals or set(vals) & set(p["facets"].get(f, [])) for f, vals in picked.items())
             and (not search or search in f"{p['title']} {p['who']} {p['journal']}".casefold())]
    shown.sort(key=READING_SORTS[sort])  # stable, so ties stay in read order
    if filtered:
        c1, c2 = st.columns([4, 1.2], vertical_alignment="center")
        c1.caption(f"Showing {len(shown)} of {sum(p['status'] in views[view] for p in papers)}.")
        c2.button("✕ Clear filters", key="reading_clear", use_container_width=True, on_click=_clear_reading_filters)
    if not shown:
        st.caption("No papers match those filters." if filtered else
                   {"Read": "Nothing read yet.", "Dropped": "Nothing dropped."}.get(view, "All caught up."))
    st.markdown("<style>[class*='st-key-paper_tags_'] button{min-height:1.5rem;padding:0 .55rem}"
                "[class*='st-key-paper_tags_'] button p{font-size:.74rem}</style>", unsafe_allow_html=True)
    open_keys = {k for t in state["tasks"] if t["status"] == "open" for k in paper_keys(t)}
    seen_levels = {"last": object()}

    def _row(p: dict) -> None:
        head = ("Reading now" if p["status"] == "reading" else "Up next" if p.get("rank") else READING_LABELS[p["status"]]) \
            if sort == "Rank" else (p["level"] or "Not ordered yet") if sort == "Read order" else \
               ((sorted(p["facets"].get("question", [])) or ["No question"])[0] if sort == "Question" else
                ((p["facets"].get("subject", []) or ["No subject"])[0] if sort == "Subject" else None))
        if head and head != seen_levels["last"]:
            seen_levels["last"] = head
            st.markdown(f"<div class='dod-sec' style='margin-top:.9rem'>{html.escape(head)}</div>", unsafe_allow_html=True)
        meta = " · ".join(html.escape(x) for x in (p["journal"], "needs check" if p["needs_check"] else "") if x)
        who_ = f"<b style='color:#c9ccd4'>{html.escape(p['who'])}</b>" if p["who"] else "<i>author unknown</i>"
        num = (f"<b style='color:#e10600'>#{p['rank']}</b> · " if p.get("rank") else "") + \
              (f"<b>{html.escape(p['order'])}</b> · " if p["order"] else "")
        st.markdown(f"{num}<a href='{html.escape(p['url'], quote=True)}' target='_blank'>{html.escape(p['title'])}</a>"
                    + f"<br><small style='color:#8b909c'>{who_}{' · ' + meta if meta else ''}</small>",
                    unsafe_allow_html=True)
        tags = _paper_tags(p)
        if tags:
            on = [t for t in tags if t.split("|", 1)[1] in (st.session_state.get(f"reading_f_{t.split('|', 1)[0]}") or [])]
            widget = f"paper_tags_{p['key']}_{zlib.crc32('~'.join(on).encode())}"  # stays in step with the active filters
            st.pills(f"Tags of {p['title'][:60]}", tags, selection_mode="multi", default=on, key=widget,
                     format_func=lambda t: t.split("|", 1)[1], label_visibility="collapsed",
                     on_change=_toggle_tag_filters, args=(widget, on))
        c1, c3, c2 = st.columns([4, 1, 1.2], vertical_alignment="center")
        with c3.popover(f"🔢 {p['order'] or 'order'}", use_container_width=True, help="Set this paper's reading order"):
            lv_ = st.selectbox("Level", list(Z.LEVELS), key=f"ord_lv_{p['key']}",
                               index=list(Z.LEVELS).index(p["order"][0]) if p["order"] else 1,
                               format_func=lambda k: f"{k} · {Z.LEVELS[k]}")
            nm_ = st.number_input("Number", 1, 99, int(p["order"][1:]) if p["order"] else 1, key=f"ord_n_{p['key']}")
            if st.button("Save order", key=f"ord_go_{p['key']}", type="primary", use_container_width=True):
                try:
                    lab_ = Z.place(zc[0], zc[1], papers, p["key"], lv_, nm_)  # bumps the rest of the level down
                    _zotero_reading.clear()
                    _zotero_list.clear()
                    flash(f"🔢 **{p['title'][:60]}** is now {lab_}.")
                except Exception as e:  # noqa: BLE001
                    flash(f"Couldn't set the order: {e}", "error")
                st.rerun()
        widget = f"paper_{p['key']}_{p['status']}"  # a new status starts a fresh control
        c1.segmented_control(f"Status of {p['title'][:60]}", list(READING_LABELS.values()),
                             default=READING_LABELS[p["status"]], key=widget, label_visibility="collapsed",
                             on_change=_set_paper_status, args=(zc, p, widget))
        if p["key"] in open_keys:
            c2.caption("On your tasks")
        elif p["status"] in ("unread", "reading"):
            if c2.button("➕ Task", key=f"paper_task_{p['key']}", use_container_width=True,
                         help="A 45-minute deep-work task, due tonight. Finishing it with proof earns coins and marks the paper read."):
                nt = make_task(f"📄 Read: {p['title'][:80]}", f"Proof: photo/screenshot of your notes + a 2-line summary. {p['url']}",
                               datetime.combine(now().date(), dtime(23, 59), TZ), None, "", category="deep", minutes=45)
                nt["zotero_key"], nt["zotero_keys"] = p["key"], [p["key"]]
                if daily.peek_day(state, now().date()).get("qualified"):
                    nt["mission_day"] = now().date().isoformat()
                state["tasks"].append(nt)
                save_state(state)
                flash(f"📄 **{nt['title']}** added, due tonight" + (" · in today's mission" if nt.get("mission_day") else "") + ".")
                st.rerun()

    # the next few papers; the rest stay a tap away. Sorting or filtering shows everything that matches.
    first = 6 if view == "To read" and sort in ("Rank", "Read order") and not filtered else len(shown)
    for p in shown[:first]:
        _row(p)
    if len(shown) > first:
        with fold("reading_more", f"Show {len(shown) - first} more", False) as _fo:
            if _open(_fo):  # collapsed = not built (faster page, smaller download)
                for p in shown[first:]:
                    _row(p)
    st.caption("Ticking a paper here only tracks it. Coins come from finishing its task with proof.")
    render_search_topics(zc)


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
# Smooth view switches. Installed once into the page: on a tap that swaps a view (a main tab, or one of the view
# pickers below) the old view fades out at once, a skeleton holds its place if the rerun takes a moment, and the new
# view fades in only after Streamlit has finished drawing it (script state back to idle + two frames). The page
# height is held during the swap so nothing jumps or scrolls. Pure decoration: it never blocks, gives up after 6 s.
VIEW_KEYS = ["stats_view", "fx_kind", "fx_prev", "fx_next", "sb_per", "jr_week", "dl_view", "set_sec"]
VIEW_IN_COLUMNS = ["fx_kind", "fx_prev", "fx_next"]
TRANSITIONS_JS = """<script>(function(){
let P;try{P=parent.document;}catch(e){return;}
const W=parent;if(W.__dodTx)return;W.__dodTx=1;
const KEYS=%s,COLS=%s,H=P.documentElement;
let pend=null,fs=null;
const app=()=>P.querySelector('[data-testid="stApp"]');
const running=()=>{const a=app(),v=a&&a.getAttribute('data-test-script-state');return v==='running'||v==='rerunRequested';};
const main=()=>P.querySelector('[data-testid="stMainBlockContainer"]')||P.querySelector('.block-container');
function start(kind,anchor){
  if(pend)finish(true);
  const m=main();if(m){m.style.minHeight=m.offsetHeight+'px';}
  if(kind==='tab')H.setAttribute('data-dod-switch','1');
  if(anchor)anchor.setAttribute('data-dod-anchor','1');
  pend={t0:Date.now(),saw:false,anchor:anchor};
  clearTimeout(fs);fs=setTimeout(()=>finish(),6000);
  (function tick(){if(!pend)return;
    if(running())pend.saw=true;
    else if(pend.saw||Date.now()-pend.t0>700){
      // idle again: let React commit and charts lay out before revealing
      requestAnimationFrame(()=>requestAnimationFrame(()=>setTimeout(()=>{if(pend&&!running())finish();else setTimeout(tick,40);},60)));return;}
    setTimeout(tick,40);})();
}
function finish(now){
  if(!pend)return;const a=pend.anchor;pend=null;clearTimeout(fs);
  H.removeAttribute('data-dod-switch');
  P.querySelectorAll('[data-dod-anchor]').forEach(e=>e.removeAttribute('data-dod-anchor'));
  const m=main();if(m)setTimeout(()=>{if(!pend)m.style.minHeight='';},now?0:450);
}
function topNode(el,cols){
  let n=el;
  if(cols){const hb=el.closest('[data-testid="stHorizontalBlock"]');if(hb)n=hb;}
  while(n.parentElement&&!n.parentElement.matches('[data-testid="stVerticalBlock"]'))n=n.parentElement;
  return n;
}
// tabs select on press (before 'click'), so catch them on pointerdown / Enter
function onTab(ev){
  const t=ev.target;if(!t||!t.closest)return;
  const tab=t.closest('[role="tab"]');if(!tab)return;
  if(ev.type==='keydown'&&ev.key!=='Enter'&&ev.key!==' ')return;
  const tabs=tab.closest('[data-testid="stTabs"]');
  // only the main tab bar reruns; nested tabs switch instantly in the browser
  if(tabs&&!tabs.parentElement.closest('[role="tabpanel"]')&&tab.getAttribute('aria-selected')!=='true')start('tab',null);
}
P.addEventListener('pointerdown',onTab,true);P.addEventListener('keydown',onTab,true);
P.addEventListener('click',function(ev){
  const t=ev.target;if(!t||!t.closest||t.closest('[role="tab"]'))return;
  const b=t.closest('button');if(!b||b.disabled)return;
  const box=b.closest('[class*="st-key-"]');if(!box)return;
  const k=KEYS.find(k=>box.classList.contains('st-key-'+k));if(!k)return;
  if(b.closest('[data-testid="stButtonGroup"]')&&(b.getAttribute('aria-checked')==='true'||b.getAttribute('aria-pressed')==='true'||b.getAttribute('kind')==='segmented_controlActive'))return;
  start('view',topNode(box,COLS.includes(k)));
},true);
})();</script>""" % (json.dumps(VIEW_KEYS), json.dumps(VIEW_IN_COLUMNS))

CSS = """<style>
:root{--y:#f5c518;--r:#e10600;--t:#2ec4b6;--panel:#1b1f27;--line:#2c313c;--muted:#8b909c}
.block-container{max-width:1280px;padding-top:2.6rem}
.st-key-rail [data-testid="stVerticalBlockBorderWrapper"],.st-key-rail>div{gap:.9rem}
[data-testid="stBaseButton-primary"] *,[data-testid="stBaseButton-primaryFormSubmit"] *{color:#14171d!important;font-weight:700}
.st-key-card_live_card > [data-testid="stExpander"] > details{border-left:4px solid var(--y)!important}
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
.dod-crewbar{margin-left:auto;display:flex;align-items:center;gap:10px;max-width:min(520px,100%);min-width:0;
  padding:5px 12px 5px 6px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.03)}
.dod-crewbar .faces{display:flex;flex:0 0 auto}.dod-crewbar .f{line-height:0;margin-left:-8px;border-radius:50%;
  box-shadow:0 0 0 2px #12151c;transition:transform .2s}.dod-crewbar .f:first-child{margin-left:0}
.dod-crewbar .f.on{transform:translateY(-2px) scale(1.12);z-index:2}
.dod-crewbar .say{font-size:.84rem;color:#d6d8dd;line-height:1.3;overflow:hidden;display:-webkit-box;
  -webkit-line-clamp:2;-webkit-box-orient:vertical}
.dod-crewbar .say b{color:var(--y)}
.dod-crewbar.ghost{opacity:.6}.dod-crewbar.ghost .f{filter:grayscale(1)}
.dod-crewbar.has-boss .f.boss{box-shadow:0 0 0 2px #12151c,0 0 0 4px var(--y);transform:none;margin-right:6px}
.dod-crewbar.has-boss .f:not(.boss){opacity:.75}
@media (max-width:640px){.dod-crewbar{margin-left:0;width:100%;max-width:100%;border-radius:14px}}
.dod-cluster{display:grid;grid-template-columns:repeat(4,1fr);background:var(--deep,#101319);border:1px solid var(--line);
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
.dod-bar{flex:1;height:4px;background:var(--track,#262b36);border-radius:2px;overflow:hidden}
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
.dod-debt{border:1px solid #5a1d1f;border-left:4px solid var(--r);border-radius:12px;padding:10px 14px;margin:.5rem 0 .3rem;
  background:linear-gradient(90deg,rgba(225,6,0,.12),rgba(225,6,0,.03) 60%,transparent);animation:dodIn .35s ease-out both}
.dod-debt-h{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px}
.dod-debt .flag{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:800;letter-spacing:.06em;color:#ece8df}
.dod-debt .amt{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:800;font-size:1.35rem;color:var(--r)}
.dod-debt .m{color:var(--muted);font-size:.85rem}.dod-debt .m b{color:#ece8df}
.dod-debt .lock{margin-top:2px;font-size:.8rem}
.dod-debt-bar{height:6px;border-radius:4px;background:#2a1416;overflow:hidden;margin:7px 0 4px}
.dod-debt-bar i{display:block;height:100%;background:linear-gradient(90deg,var(--r),var(--t));border-radius:4px;
  animation:dodGrow .9s cubic-bezier(.2,.7,.2,1) both;--from:0%}
.st-key-debt_way{margin:0 0 .6rem}
.st-key-debt_way p{margin:0}
[class*="st-key-win_"]{animation:dodDropOut .7s ease-in 9s both;overflow:hidden}
/* roadmap flow chart: readable on a phone — it keeps its size and you swipe sideways */
@media (max-width:640px){[data-testid="stGraphVizChart"]{overflow-x:auto;-webkit-overflow-scrolling:touch}
  [data-testid="stGraphVizChart"] svg{min-width:660px;height:auto}}
/* ── Today, redesigned: one focal card, quiet sections, the car up top on the right ── */
.dod-cell.carcell{position:relative;overflow:hidden}
.dod-mini-car{position:absolute;right:6px;bottom:4px;width:46%;max-width:150px;opacity:.95;pointer-events:none}
.dod-mini-car svg{width:100%;height:auto;display:block;filter:drop-shadow(0 6px 8px rgba(0,0,0,.4))}
@media (max-width:640px){.st-key-car_card,.st-key-car_card+div{display:none!important}
  .dod-mini-car{width:46%;top:10px;bottom:auto;right:8px}}
.dod-arr{font-size:.92rem;color:#ece8df;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dod-arr b{color:var(--y);margin-right:4px}.dod-arr span{color:var(--muted);font-size:.8rem;margin-left:4px}
[class*="st-key-arr_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.35rem}
[class*="st-key-arr_"] [data-testid="stColumn"]{min-width:0!important}
[class*="st-key-arr_"] [data-testid="stColumn"]:nth-child(1),[class*="st-key-arr_"] [data-testid="stColumn"]:nth-child(2){
  flex:0 0 2.4rem!important;width:2.4rem!important}
[class*="st-key-arr_"] [data-testid="stColumn"]:nth-child(4){flex:0 0 7.2rem!important;width:7.2rem!important}
.dod-step{display:flex;align-items:center;gap:8px;font-weight:600;color:#ece8df;margin:.5rem 0 .2rem;font-size:.95rem}
.dod-step b{width:1.35rem;height:1.35rem;border-radius:50%;background:var(--y);color:#111;display:inline-flex;
  align-items:center;justify-content:center;font-size:.78rem}
.dod-meter{font-size:.85rem;color:var(--muted);padding:6px 10px;border-radius:10px;background:var(--card,#141821);
  border:1px solid var(--line);margin:.35rem 0 .1rem}
.dod-meter b{color:#ece8df}.dod-meter.ok{border-color:rgba(46,196,182,.4)}.dod-meter.low{border-color:rgba(225,6,0,.45)}
/* Today on a phone: flatten the two columns into one list and put the sections in a phone-friendly order */
@media (max-width:640px){
  .st-key-today_grid > [data-testid="stHorizontalBlock"],
  .st-key-today_grid > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"]{display:flex!important;flex-direction:column!important;gap:0!important}
  .st-key-today_grid > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  .st-key-today_grid > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  .st-key-today_grid > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > [data-testid="stVerticalBlock"],
  .st-key-today_grid > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > [data-testid="stVerticalBlock"]{display:contents!important}
  .st-key-today_grid > * > [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *,
  .st-key-today_grid > * > * > [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *{order:50;margin-bottom:.8rem}
  .st-key-today_grid .st-key-tg_checkin{order:1}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_checkin){order:1}
  .st-key-today_grid .st-key-tg_today{order:2}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_today){order:2}
  .st-key-today_grid .st-key-tg_timer{order:3}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_timer){order:3}
  .st-key-today_grid .st-key-tg_h_show{order:4}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_h_show){order:4}
  .st-key-today_grid .st-key-tg_commit{order:5}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_commit){order:5}
  .st-key-today_grid .st-key-tg_dailies{order:6}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_dailies){order:6}
  .st-key-today_grid .st-key-tg_h_plan{order:7}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_h_plan){order:7}
  .st-key-today_grid .st-key-tg_goals{order:8}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_goals){order:8}
  .st-key-today_grid .st-key-tg_todo{order:9}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_todo){order:9}
  .st-key-today_grid .st-key-tg_board{order:10}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_board){order:10}
  .st-key-today_grid .st-key-tg_close{order:11}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_close){order:11}
  .st-key-today_grid .st-key-tg_h_team{order:12}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_h_team){order:12}
  .st-key-today_grid .st-key-tg_crew{order:13}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_crew){order:13}
  .st-key-today_grid .st-key-tg_dealer{order:14}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_dealer){order:14}
  .st-key-today_grid .st-key-tg_season{order:15}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_season){order:15}
  .st-key-today_grid .st-key-tg_status{order:16}
  .st-key-today_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > *:has(> .st-key-tg_status){order:16}
  .st-key-today_grid .st-key-tg_car{order:40;display:none!important}
}
@media (max-width:640px){
  .st-key-fx_row [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.25rem}
  .st-key-fx_row [data-testid="stColumn"]{min-width:0!important}
  .st-key-fx_row [data-testid="stColumn"]:nth-child(1){flex:1 1 auto!important}
  .st-key-fx_row [data-testid="stColumn"]:nth-child(2),.st-key-fx_row [data-testid="stColumn"]:nth-child(3){
    flex:0 0 2.1rem!important;width:2.1rem!important}
  .st-key-fx_row [data-testid="stColumn"]:nth-child(2) button,.st-key-fx_row [data-testid="stColumn"]:nth-child(3) button{
    padding-left:0;padding-right:0}
  .st-key-fx_row [data-testid="stColumn"]:nth-child(4){flex:0 0 4.3rem!important;width:4.3rem!important;font-size:.78rem}
  .st-key-fx_row [data-testid="stButtonGroup"] button{padding-left:.55rem;padding-right:.55rem}
  .dod-cluster{grid-template-columns:repeat(4,1fr)!important}
  .dod-cluster .dod-cell{padding:8px 8px!important;border-left:1px solid var(--line)!important}
  .dod-cluster .dod-cell:first-child{border-left:0!important}
  .dod-cluster .dod-v{font-size:1.25rem!important}
  .dod-cluster .dod-k{font-size:.68rem!important}
  .dod-cluster .dod-s{display:none}
  .dod-mini-car{width:70%!important;top:4px!important;right:4px!important;opacity:.55}
  .dod-hero h1{font-size:1.6rem!important}
  .dod-next{padding:12px 14px 10px}.dod-next .t{font-size:1.25rem}
}
/* zone labels: quiet dividers that group Today (and long tabs) into a few named areas */
.dod-zone{display:flex;align-items:baseline;gap:10px;margin:.9rem 2px .1rem;padding-top:.7rem;border-top:1px solid var(--line)}
.dod-zone b{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:700;font-size:.82rem;letter-spacing:.14em;
  text-transform:uppercase;color:var(--y)}
.dod-zone span{font-size:.8rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* one type scale inside cards: card headings never shout louder than the page */
[data-testid="stVerticalBlockBorderWrapper"] h3,[data-testid="stExpander"] h3{font-size:1.2rem!important;line-height:1.3!important;
  padding:.1rem 0 .25rem!important}
[data-testid="stVerticalBlockBorderWrapper"] h4,[data-testid="stExpander"] h4{font-size:1.02rem!important;padding:.1rem 0 .2rem!important}
/* stat tiles (race, shop): numbers you compare, laid out to be compared */
.dod-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:.3rem 0 .6rem}
.dod-tiles div{border:1px solid var(--line);border-radius:12px;padding:8px 10px;background:var(--card,#141821)}
.dod-tiles small{display:block;color:var(--muted);font-size:.7rem;letter-spacing:.06em;text-transform:uppercase}
.dod-tiles b{font-size:1rem;font-weight:700;white-space:nowrap}
/* small control rows (key="row_…") stay side by side on a phone */
[class*="st-key-row_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;flex-direction:row!important;gap:8px!important}
[class*="st-key-row_"] [data-testid="stColumn"]{min-width:0!important;width:auto!important}
/* button rows stay rows on a phone where they're a pair of choices */
.st-key-boost_row [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:8px!important}
.st-key-boost_row [data-testid="stColumn"]{min-width:0!important;flex:1 1 0!important;width:auto!important}
@media (max-width:640px){
  .dod-hero{margin-bottom:.3rem!important;gap:2px 12px!important}
  .dod-quote.top{margin:.1rem 0 .7rem!important;font-size:.84rem!important}
}
.dod-sec{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:700;font-size:1.15rem;margin:0 0 .4rem;
  display:flex;flex-wrap:wrap;align-items:baseline;column-gap:10px;row-gap:0}
.dod-sec span{font-family:inherit;font-weight:500;font-size:.85rem;color:var(--muted)}
/* section cards: collapsible, remembered (fold(..., card=True)) */
[class*="st-key-card_"] > [data-testid="stExpander"] > details{border-radius:14px}
[class*="st-key-card_"] > [data-testid="stExpander"] > details > summary{padding-top:.7rem;padding-bottom:.7rem}
[class*="st-key-card_"] > [data-testid="stExpander"] > details > summary p{font-family:'Saira Semi Condensed',system-ui,sans-serif;
  font-size:1.12rem;line-height:1.3}
[class*="st-key-card_"] > [data-testid="stExpander"] > details > summary p strong{font-weight:700}
.st-key-card_tasks_open > [data-testid="stExpander"] > details{border-left:3px solid var(--y,#f5c518)!important}
.st-key-card_tasks_redeem > [data-testid="stExpander"] > details{border-color:rgba(225,6,0,.35)!important;
  border-left:3px solid #e10600!important;background:rgba(225,6,0,.05)}
.st-key-card_tasks_recent > [data-testid="stExpander"] > details{border-color:rgba(46,196,182,.3)!important;
  border-left:3px solid #2ec4b6!important;background:rgba(46,196,182,.04)}
.st-key-tb_redeem_box{border-color:rgba(225,6,0,.35)!important;border-left:3px solid #e10600!important;background:rgba(225,6,0,.05)}
.st-key-card_tasks_recent [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.5rem!important}
.st-key-card_tasks_recent [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child{min-width:0!important;flex:1 1 auto!important}
.st-key-card_tasks_recent [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child{min-width:92px!important;flex:0 0 92px!important}
.st-key-card_tasks_recent [data-testid="stHorizontalBlock"] p{margin:0}
.dod-sub{font-weight:700;font-size:.9rem;display:flex;gap:8px;align-items:baseline;margin:0 0 .2rem}
.dod-sub.red{color:#ff6b63}.dod-sub span{font-weight:500;color:var(--muted)}
.dod-next{position:relative;border-radius:16px;padding:16px 18px 14px;margin:0 0 .5rem;overflow:hidden;
  background:linear-gradient(135deg,rgba(245,197,24,.16),rgba(245,197,24,.03) 55%,transparent),#141821;
  border:1px solid rgba(245,197,24,.35);animation:dodIn .35s ease-out both}
.dod-next::after{content:"";position:absolute;right:-30px;top:-30px;width:140px;height:140px;opacity:.07;
  background:repeating-conic-gradient(#fff 0 25%,transparent 0 50%) 0 0/22px 22px;transform:rotate(12deg)}
.dod-next .k{color:var(--y);font-size:.8rem;font-weight:600;letter-spacing:.04em;text-transform:uppercase}
.dod-next .t{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:700;font-size:1.6rem;line-height:1.15;
  margin:.2rem 0 .25rem;color:#ece8df}
.dod-next .m{color:var(--muted);font-size:.9rem}
.dod-next.slim{padding:10px 14px}.dod-next.slim::after{display:none}
.dod-next.run{border-color:rgba(46,196,182,.45);background:linear-gradient(135deg,rgba(46,196,182,.16),transparent 60%),var(--card,#141821)}
.dod-next.run .k{color:var(--t)}
.dod-next.done{border-color:rgba(46,196,182,.35);background:linear-gradient(135deg,rgba(46,196,182,.12),transparent 60%),var(--card,#141821)}
.dod-next.done .k{color:var(--t)}
.st-key-up_next [data-testid^="stBaseButton-primary"]{font-size:1.05rem;padding:.6rem 0;border-radius:12px}
.dod-goal{padding:4px 0 2px}
.dod-goal .h{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.dod-goal .h b{color:#ece8df;font-weight:600}.dod-goal .h span{color:var(--muted);font-size:.8rem;white-space:nowrap}
.dod-goal .bar{height:6px;border-radius:4px;background:var(--track,#262b36);overflow:hidden;margin:6px 0 4px}
.dod-goal .bar i{display:block;height:100%;background:linear-gradient(90deg,var(--y),var(--t));border-radius:4px;
  animation:dodGrow .9s cubic-bezier(.2,.7,.2,1) both;--from:0%}
.dod-goal .m{color:var(--muted);font-size:.82rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dod-goal-tag{color:var(--t);font-size:.82rem;text-align:center}
.st-key-card_goals_today [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.6rem}
.st-key-card_goals_today [data-testid="stColumn"]{min-width:0!important}
.st-key-card_goals_today [data-testid="stColumn"]:last-child{flex:0 0 7.6rem!important;width:7.6rem!important}
.dod-car{border:1px solid var(--line);border-radius:16px;padding:10px 14px 12px;margin:0 0 .5rem;
  background:radial-gradient(120% 90% at 50% 0%,#1e2330,#121620 70%)}
.dod-car .img svg{width:100%;height:auto;display:block;filter:drop-shadow(0 10px 14px rgba(0,0,0,.45))}
.dod-car .nm{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin:2px 0 6px}
.dod-car .nm b{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-size:1.1rem;color:#ece8df}
.dod-car .nm span{color:var(--muted);font-size:.82rem}
.dod-car .nm .ok,.dod-car .nm .bad{margin-left:auto;font-size:.8rem;font-weight:600}
.dod-car .nm .ok{color:var(--t)}.dod-car .nm .bad{color:#ff6a5c}
.dod-car .cond{display:flex;align-items:center;gap:8px;font-size:.8rem;color:var(--muted);margin:3px 0}
.dod-car .cond span{width:4.6rem}.dod-car .cond b{color:#ece8df;font-weight:600;min-width:3.4rem;text-align:right}
.dod-car .cond .bar{flex:1;height:5px;border-radius:3px;background:var(--track,#262b36);overflow:hidden}
.dod-car .cond .bar i{display:block;height:100%;background:var(--y);border-radius:3px}
.dod-car .chips{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.dod-car .chips span{font-size:.75rem;color:var(--muted);background:var(--card,#141821);border:1px solid var(--line);border-radius:999px;
  padding:2px 9px}
.dod-car .why{color:#ff6a5c;font-size:.8rem;margin-top:6px}
.dod-today{padding:2px 2px 4px}.dod-today .top{display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.dod-today .when{color:var(--muted);font-size:.8rem;letter-spacing:.04em;text-transform:uppercase}
.dod-today .ttl{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:800;font-size:1.7rem;line-height:1.15;color:#ece8df}
.dod-today .sub{color:var(--muted);font-size:.85rem;margin-top:3px}
.dod-today .rings{display:flex;align-items:center;gap:12px}.dod-today .lg{display:flex;flex-direction:column;gap:3px;font-size:.8rem;font-weight:600}
.dod-today .tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);
  border-radius:12px;overflow:hidden;margin:12px 0}
.dod-today .tiles div{background:var(--card,#141821);padding:9px 12px;display:flex;flex-direction:column;gap:1px}
.dod-today .tiles span{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.05em}
.dod-today .tiles b{font-size:1.35rem;color:#ece8df;font-variant-numeric:tabular-nums}
.dod-today .tiles i{font-style:normal;color:var(--muted);font-size:.74rem;min-height:1em}
.dod-today .tl .lab{color:var(--muted);font-size:.75rem;margin-bottom:4px}
.dod-today .splits{width:100%;border-collapse:collapse;margin-top:10px;font-size:.84rem}
.dod-today .splits th{color:var(--muted);font-weight:600;text-align:left;font-size:.72rem;text-transform:uppercase;padding:4px 6px;
  border-bottom:1px solid var(--line)}
.dod-today .splits td{padding:5px 6px;border-bottom:1px solid var(--line);color:#d6d2c8}
.dod-today .splits td:nth-child(3){font-variant-numeric:tabular-nums;white-space:nowrap}
.dod-today .none{color:var(--muted);font-size:.85rem;margin-top:10px}
@media (max-width:640px){.dod-today .tiles{grid-template-columns:repeat(2,1fr)}.dod-today .ttl{font-size:1.4rem}}
.dod-season{border:1px solid var(--line);border-radius:16px;padding:10px 14px 12px;margin:0 0 .5rem;
  background:radial-gradient(120% 90% at 50% 0%,#232033,#121620 70%)}
.dod-season .hd{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.dod-season .hd b{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-size:1.05rem;color:#ece8df}
.dod-season .hd span{margin-left:auto;color:var(--muted);font-size:.8rem}
.dod-season .bar{height:6px;border-radius:3px;background:var(--track,#262b36);overflow:hidden;margin:7px 0 6px}
.dod-season .bar i{display:block;height:100%;background:linear-gradient(90deg,#f5c518,#ff9f1c);border-radius:3px}
.dod-season .pts{font-size:.86rem;color:#d6d2c8}.dod-season .pts b{color:#ece8df}
.dod-season .chips,.dod-season .cab{display:flex;gap:6px;margin-top:7px;flex-wrap:wrap}
.dod-season .chips span,.dod-season .cab span{font-size:.75rem;color:var(--muted);background:var(--card,#141821);
  border:1px solid var(--line);border-radius:999px;padding:2px 9px}
.dod-season .cab span{color:#f5c518;border-color:#5a4a12}
.dod-season .why{color:var(--muted);font-size:.74rem;margin-top:6px}
.st-key-car_card [data-testid^="stBaseButton-tertiary"],.st-key-card_goals_today [data-testid^="stBaseButton-tertiary"]{
  color:var(--muted);font-size:.85rem;padding:0;min-height:0}
.st-key-drop_reveal{animation:dodDropOut .6s ease-in 4.8s both;overflow:hidden}
.dod-drop{display:flex;gap:14px;align-items:center;padding:12px 16px;border:1px solid var(--y);border-radius:14px;
  background:radial-gradient(120% 160% at 0% 50%,rgba(245,197,24,.16),transparent 60%),#141821;
  box-shadow:0 0 0 1px rgba(245,197,24,.15),0 10px 30px -10px rgba(245,197,24,.35)}
.dod-drop-box{font-size:2.3rem;animation:dodDropPop .7s cubic-bezier(.2,1.6,.4,1) both}
.dod-drop-k{color:var(--muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.06em}
.dod-drop-v{font-size:1.1rem;color:#ece8df;animation:dodIn .4s ease-out .25s both}.dod-drop-v b{color:var(--y)}
@keyframes dodDropPop{0%{transform:scale(.3) rotate(-18deg);opacity:0}60%{transform:scale(1.25) rotate(8deg);opacity:1}
  100%{transform:none}}
@keyframes dodDropOut{from{opacity:1;max-height:200px}to{opacity:0;max-height:0;margin:0;padding:0}}
.dod-shield span.hot{border-color:var(--y);color:#ece8df;background:rgba(245,197,24,.08)}
.st-key-audio_session{position:absolute!important;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none}
.dod-ci{margin:-.2rem 0 .1rem}.dod-ci .m{color:var(--muted);font-size:.85rem;margin-left:4px}
.st-key-card_checkin [data-testid="stButtonGroup"] button,.st-key-card_closeday [data-testid="stButtonGroup"] button,
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
.dod-boot-bar{width:180px;height:4px;border-radius:4px;background:var(--track,#262b36);overflow:hidden}
.dod-boot-bar i{display:block;width:40%;height:100%;background:var(--y);border-radius:4px;animation:dodSlide 1.1s ease-in-out infinite}
@keyframes dodBob{from{transform:translateY(0)}to{transform:translateY(-6px)}}
.dod-flow-chk{background:rgba(41,227,255,.08);border:1px solid rgba(41,227,255,.35);border-radius:10px;padding:8px 12px;
  margin:4px 0 8px;animation:dodPulse 2s ease-in-out infinite}.dod-flow-chk span{display:block;color:var(--muted);font-size:.85rem}
@keyframes dodPulse{0%,100%{box-shadow:0 0 0 0 rgba(41,227,255,.0)}50%{box-shadow:0 0 0 4px rgba(41,227,255,.12)}}
.dod-togo{display:flex;flex-wrap:wrap;gap:6px;margin:-.2rem 0 .6rem}
.dod-togo span{font-size:.8rem;color:var(--muted);background:rgba(255,255,255,.04);border:1px solid var(--line);
  border-radius:999px;padding:2px 10px}.dod-togo span b{color:#d8d4cb;font-weight:600}
.dod-togo span.g{color:var(--y);border-color:var(--y)}
/* ── showroom ── */
.dod-sr{border-radius:14px;overflow:hidden;margin:-.2rem 0 .2rem}
.dod-sr svg{display:block;transition:transform .35s ease}.dod-sr:hover svg{transform:scale(1.015)}
.dod-sr.locked svg{filter:grayscale(.85) brightness(.6)}
.dod-sr-n{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:800;font-size:1.15rem;letter-spacing:.01em}
.dod-sr-s{color:var(--muted);font-size:.85rem}
/* ── weekly recap cards (wins / what got in the way) ── */
.dod-rc-h{font-weight:700;margin:.4rem 0 .5rem;display:flex;gap:8px;align-items:baseline}
.dod-rc-h span{font-weight:500;color:var(--muted);font-size:.85rem}
.dod-rc-list{display:flex;flex-direction:column;gap:8px}
.dod-rc{display:block;background:var(--card,#141821);border:1px solid var(--line);border-left:3px solid #2ec4b6;
  border-radius:10px;padding:9px 12px;line-height:1.5;font-size:.93rem}
.dod-rc.block{border-left-color:#ff6a5c}
.dod-rc>summary{list-style:none;cursor:pointer}.dod-rc>summary::-webkit-details-marker{display:none}
.dod-rc-day{display:inline-block;font-size:.72rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
  color:var(--muted);background:rgba(255,255,255,.05);border-radius:6px;padding:1px 7px;margin-bottom:4px}
.dod-rc-t{color:#d8d4cb}
.dod-rc-more,.dod-rc-less{display:inline-block;margin-left:6px;color:var(--y);font-weight:600;font-size:.82rem;white-space:nowrap}
.dod-rc-less{display:none;float:right;margin:0}details.dod-rc[open] .dod-rc-less{display:inline-block}
details.dod-rc[open]>summary .dod-rc-t{display:none}
.dod-rc-full{color:#d8d4cb;animation:dodIn .2s ease-out}
.dod-rc-empty{color:var(--muted);font-size:.9rem}
/* ── the loading screen (sign-in check + first load) ── */
.dod-load{min-height:72vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;
  background:radial-gradient(60% 45% at 50% 42%,rgba(245,197,24,.07),transparent 70%);animation:dodIn .35s ease-out both}
.st-key-jump_js{position:absolute;height:0;overflow:hidden}
.dod-load.cover{position:fixed;inset:0;z-index:999980;min-height:100vh;background-color:#12151c;
  animation:dodCoverOut .01s 20s forwards}  /* safety: never covers the app for more than 20 s */
@keyframes dodCoverOut{to{visibility:hidden;pointer-events:none}}
.dod-load-lights{display:flex;gap:10px;padding:10px 14px;border-radius:12px;background:#0b0d11;border:1px solid #232833}
.dod-load-lights i{width:16px;height:16px;border-radius:50%;background:#2a1012;box-shadow:inset 0 0 0 2px #3a1416;
  animation:dodLight 2.6s infinite}
.dod-load-lights i:nth-child(2){animation-delay:.25s}.dod-load-lights i:nth-child(3){animation-delay:.5s}
.dod-load-lights i:nth-child(4){animation-delay:.75s}.dod-load-lights i:nth-child(5){animation-delay:1s}
@keyframes dodLight{0%,5%{background:#2a1012;box-shadow:inset 0 0 0 2px #3a1416}
  8%,60%{background:#ff2a1f;box-shadow:0 0 14px 2px rgba(255,42,31,.7),inset 0 0 0 2px #ff6a5c}
  64%,100%{background:#2a1012;box-shadow:inset 0 0 0 2px #3a1416}}
.dod-load-title{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:800;font-style:italic;
  font-size:clamp(1.6rem,6vw,2.4rem);letter-spacing:.02em;color:#ece8df}
.dod-load-title b{color:#f5c518}
.dod-load-track{position:relative;width:min(340px,82vw);height:54px;border-radius:12px;overflow:hidden;
  background:#1a1d24;border:1px solid #2c313c}
.dod-load-track::before{content:'';position:absolute;left:0;right:0;top:50%;height:3px;margin-top:-1.5px;
  background:repeating-linear-gradient(90deg,#f5c518 0 22px,transparent 22px 44px);opacity:.55;
  animation:dodRoad .45s linear infinite}
.dod-load-track::after{content:'';position:absolute;right:0;top:0;bottom:0;width:22px;
  background:conic-gradient(#ece8df 25%,#111 0 50%,#ece8df 0 75%,#111 0) 0 0/11px 11px;opacity:.85}
@keyframes dodRoad{from{background-position:0 0}to{background-position:-44px 0}}
.dod-load-car{position:absolute;left:50%;top:50%;font-size:2rem;transform:translate(-50%,-55%) scaleX(-1);
  animation:dodCar .5s ease-in-out infinite alternate;filter:drop-shadow(0 4px 6px rgba(0,0,0,.5))}
@keyframes dodCar{from{transform:translate(-56%,-58%) scaleX(-1)}to{transform:translate(-44%,-52%) scaleX(-1)}}
.dod-load-tips{position:relative;height:1.4rem;width:min(340px,82vw);text-align:center;color:#8b909c;font-size:.92rem}
.dod-load-tips span{position:absolute;inset:0;opacity:0;animation:dodTip 7.5s infinite}
.dod-load-tips span:nth-child(2){animation-delay:2.5s}.dod-load-tips span:nth-child(3){animation-delay:5s}
@keyframes dodTip{0%{opacity:0;transform:translateY(4px)}6%,28%{opacity:1;transform:none}34%,100%{opacity:0}}
.st-key-pw_late{animation:dodLate .4s 4s both}
@keyframes dodLate{from{opacity:0;visibility:hidden}to{opacity:1;visibility:visible}}
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
[data-testid="stToast"]{background:var(--panel)!important;border:1px solid var(--line);border-left:3px solid var(--y);
  color:#ece8df;box-shadow:0 8px 24px rgba(0,0,0,.45)}
[class*="st-key-scrap_"] img{max-height:210px;object-fit:cover;width:100%;border-radius:10px}
.dod-scrap-tile{height:96px;border-radius:10px;background:linear-gradient(135deg,var(--panel),var(--card,#141821));display:flex;
  align-items:center;justify-content:center;font-size:2.4rem;margin-bottom:.4rem;border:1px solid var(--line)}
.dod-mh{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:.1rem 0 .5rem}
.dod-mt{font-family:'Saira Semi Condensed',system-ui,sans-serif;font-weight:700;font-size:1.55rem;line-height:1.1}
.dod-mb{color:var(--muted);font-size:.9rem;white-space:nowrap}
.dod-seg{display:flex;gap:5px;margin:0 0 .7rem}
.dod-seg i{flex:1;height:7px;border-radius:4px;background:var(--track,#262b36);transition:background .4s}
.dod-seg i.ok{background:var(--y)} .dod-seg i.bad{background:var(--r)}
.dod-pills{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 .8rem}
.dod-pills span{font-size:.8rem;color:var(--muted);background:var(--card,#141821);border:1px solid var(--line);border-radius:999px;
  padding:3px 10px}
.dod-pills b{color:#ece8df;font-weight:600}
.dod-crew{display:flex;gap:12px;align-items:center;margin:6px 0 10px}.dod-crew .av{flex:0 0 auto;line-height:0}
.dod-crew .av.ghost{opacity:.28;filter:grayscale(1)}.dod-crew .r{color:#8b909c;font-size:.85rem}
.dod-crew .say{font-size:.92rem;margin-top:2px}
.dod-quote{margin-top:8px;padding:10px 12px;border-left:3px solid var(--y);font-style:italic;
  color:#d6d8dd;font-size:.92rem;background:rgba(255,255,255,.03);border-radius:0 8px 8px 0}
.dod-quote span{display:block;font-style:normal;color:#8b909c;font-size:.8rem;margin-top:4px}
.dod-start{margin:.2rem 0 .55rem;padding:9px 12px;border-radius:12px;border:1px solid rgba(245,197,24,.45);
  background:linear-gradient(90deg,rgba(245,197,24,.12),rgba(245,197,24,.02));font-size:.95rem}
.dod-start b{color:var(--y)}.dod-start span{display:block;color:#b8bcc6;font-size:.84rem;margin-top:2px}
.dod-quote.top{margin:-.2rem 0 .9rem;padding:6px 12px;font-size:.9rem;background:none}
.dod-quote.top span{display:block;margin-top:2px}
.dod-cast{display:flex;gap:10px;align-items:flex-start;margin:.3rem 0 .6rem;padding:9px 12px;border-radius:12px;
  background:rgba(255,255,255,.04);border:1px solid var(--line)}
.dod-cast .av{flex:0 0 40px;line-height:0}.dod-cast b{font-size:.88rem}
.dod-cast .r{color:var(--muted);font-size:.75rem;margin-left:4px}
.dod-cast .q{font-size:.92rem;line-height:1.4;margin-top:1px}.dod-cast .f{font-size:.84rem;margin-top:4px;color:#b8bcc6}
.dod-cast.live{border-color:rgba(225,6,0,.55);background:linear-gradient(90deg,rgba(225,6,0,.14),rgba(225,6,0,.02))}
.dod-cast.won{border-color:rgba(46,196,182,.45)}
.dod-banter{margin:4px 0 10px;padding:9px 12px;border-radius:10px;background:rgba(255,255,255,.04);font-size:.9rem;
  line-height:1.45}
.dod-mrow{display:flex;gap:10px;align-items:center;padding:9px 14px;margin:0 0 .5rem;border:1px solid var(--line);
  border-radius:12px;background:var(--card,#141821)}
.dod-mrow .m{color:var(--muted);font-size:.85rem;margin-left:6px}
.dod-mrow.ok .dod-dot{background:var(--t)} .dod-mrow.ok s{color:var(--muted)}
.dod-mrow.bad .dod-dot{background:var(--r)} .dod-mrow.bad{border-color:#4a1f22}
[class*="st-key-mrow_"] > [data-testid="stHorizontalBlock"],
[class*="st-key-mrow_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.5rem}
[class*="st-key-mrow_"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
[class*="st-key-mrow_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]{min-width:0!important}
[class*="st-key-mrow_"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child,
[class*="st-key-mrow_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child{flex:0 0 3.2rem!important;width:3.2rem!important}
[class*="st-key-qrow_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.4rem}
[class*="st-key-bplays_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.4rem}
[class*="st-key-goalcard_"] [data-testid="stHorizontalBlock"]:has([class*="st-key-gfold_"]){flex-wrap:nowrap!important;flex-direction:row!important}
[class*="st-key-goalcard_"] [data-testid="stColumn"]:has([class*="st-key-gfold_"]){flex:0 0 2.6rem!important;width:2.6rem!important;min-width:0!important}
[class*="st-key-goalcard_"] [data-testid="stColumn"]:has(h3){min-width:0!important;flex:1 1 auto!important}
.st-key-tg_live{max-width:860px;margin:0 auto .6rem;width:100%}
.st-key-tg_live h4{font-size:1.35rem!important;text-align:center}
body.dod-focus .st-key-tg_live{position:fixed!important;top:0!important;left:0!important;right:0!important;bottom:0!important;
  width:100vw!important;height:100vh!important;height:100dvh!important;max-width:none!important;margin:0!important;z-index:1000001;
  background:var(--dodbg,#0e1117);overflow-y:auto!important;padding:max(2vh,10px) max(4vw,10px)!important;
  display:flex!important;flex-direction:column!important;justify-content:flex-start!important;box-sizing:border-box}
body.dod-focus .st-key-tg_live > div{max-width:min(1400px,100%);width:100%;margin:auto!important}
body.dod-focus{overflow:hidden}
body.dod-focus [data-testid="stTabPanel"],body.dod-focus [data-testid="stMain"],body.dod-focus .stMain{transform:none!important;contain:none!important;animation:none!important}
/* ⏱️ a running timer lives in a bar pinned to the top of every tab */
.st-key-float_timer{position:fixed!important;top:8px;left:12px;right:60px;z-index:999995;width:auto!important;
  max-width:760px;margin:0 auto;background:rgba(20,23,30,.94);backdrop-filter:blur(8px);
  border:1px solid rgba(245,197,24,.45);border-radius:14px;padding:4px 8px 4px 12px;box-shadow:0 8px 24px rgba(0,0,0,.45);
  bottom:auto!important;height:auto!important;max-height:64px;overflow:hidden;flex:none!important}
body:has(.st-key-float_timer) [data-testid="stToolbarActions"]{display:none!important}
.st-key-float_timer{transition:transform .25s ease,opacity .25s ease}
.st-key-float_timer.dod-hidebar{transform:translateY(-140%);opacity:0;pointer-events:none}
.st-key-float_timer .st-key-bar_end{display:none!important}
.st-key-float_timer.dod-due .st-key-bar_end{display:flex!important;flex-wrap:nowrap!important}
.st-key-float_timer.dod-due .st-key-bar_norm{display:none!important}
.st-key-float_timer.dod-due{border-color:#ff6a5c}
.st-key-float_timer .st-key-bar_end button{min-width:0!important;padding:0 .55rem!important;font-size:1.15rem}
body:has(.st-key-float_timer) [data-testid="stMainBlockContainer"]{padding-top:4.6rem!important}
.st-key-float_timer [data-testid="stElementContainer"]{margin:0!important}
.st-key-float_timer [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;flex-direction:row!important;gap:.5rem}
.st-key-float_timer [data-testid="stColumn"]{min-width:0!important}
.st-key-float_timer [data-testid="stColumn"]:last-child{flex:0 0 92px!important;width:92px!important}
.st-key-float_timer iframe{display:block}
.st-key-timer_gone{position:absolute!important;width:1px;height:1px;overflow:hidden;opacity:0}
@media (max-width:640px){.st-key-float_timer{left:10px;right:10px;bottom:10px;width:auto!important}}
[class*="st-key-arrrow_"] [data-testid="stHorizontalBlock"],
.st-key-today_grid [class*="st-key-arrrow_"] [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;flex-direction:row!important;gap:.4rem!important}
[class*="st-key-arrrow_"] [data-testid="stColumn"]{min-width:0!important;width:50%!important;flex:1 1 50%!important}
[class*="st-key-arrrow_"]{margin:-.2rem 0 .5rem}
.st-key-fold_start_times .dod-arr{line-height:1.5;padding-top:.15rem}
[class*="st-key-bplays_"] [data-testid="stColumn"]{min-width:0!important}
[class*="st-key-bplays_"] [data-testid="stColumn"]:first-child p{margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
[class*="st-key-bplays_"] [data-testid="stColumn"]:last-child{flex:0 0 3rem!important;width:3rem!important}
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
[role="tabpanel"]{animation:dodIn .3s ease-out both}
/* view switches (tabs, view pickers): the old view fades out on tap, a skeleton holds the space while the app
   reruns, and the new view fades in once it's fully drawn, so the swap itself is never seen (see TRANSITIONS_JS) */
[role="tabpanel"]>*,[data-dod-anchor]~*{transition:opacity .26s ease,transform .26s cubic-bezier(.2,.7,.2,1)}
html[data-dod-switch] [role="tabpanel"]:not([hidden])>*,[data-dod-anchor]~*{opacity:0!important;
  transform:translateY(4px);transition:opacity .1s ease,transform .1s ease!important;pointer-events:none}
html[data-dod-switch] [role="tabpanel"]:not([hidden]){position:relative;min-height:180px}
[data-dod-anchor]{position:relative}
html[data-dod-switch] [role="tabpanel"]:not([hidden])::before,[data-dod-anchor]::after{content:"";
  position:absolute;left:0;right:0;height:150px;z-index:2;pointer-events:none;border-radius:6px;
  background:linear-gradient(#222733,#222733) 0 0/58% 24px no-repeat,linear-gradient(#222733,#222733) 0 44px/100% 14px no-repeat,
    linear-gradient(#222733,#222733) 0 70px/86% 14px no-repeat,linear-gradient(#222733,#222733) 0 96px/93% 14px no-repeat,
    linear-gradient(#222733,#222733) 0 122px/64% 14px no-repeat;
  animation:dodSkShow .01s linear .18s both,dodSkPulse .8s ease-in-out .18s infinite alternate}
html[data-dod-switch] [role="tabpanel"]:not([hidden])::before{top:14px}
[data-dod-anchor]::after{top:calc(100% + 16px)}
@keyframes dodSkShow{from{visibility:hidden}to{visibility:visible}}
@keyframes dodSkPulse{from{opacity:.45}to{opacity:1}}
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
    "valencia": ("Valencia Red", "#c4142f", "#ffffff", 1400, 5, "A deep red pearl for the cars that earned it."),
    "longbeach": ("Long Beach Blue", "#3f78c9", "#ffffff", 1800, 6, "The bright blue of a sunny track day."),
    "sonic": ("Sonic Gray", "#8f98a3", "#14171d", 2400, 8, "Liquid-metal grey. Understated, expensive."),
}


# ── 🏁 Kits: full themes that restyle the whole app (background, surfaces, borders, fonts, shape, effects) ──
_F = "https://fonts.googleapis.com/css2?family="
KITS = {
    "stock": dict(name="Stock", cost=0, level=1, blurb="The factory look. Paints from the Paint shop apply here.",
                  accent=None),
    "night": dict(name="Night Race", cost=600, level=2, blurb="Floodlights over a midnight street circuit. Cyan glow.",
                  accent="#29e3ff", on="#051018", bg="#070b16", card="#0d1424", panel="#111a2e", deep="#0a1020",
                  track="#1a2540", line="#1f3157", muted="#7f8fb0", radius="14px",
                  head="Rajdhani", head_w="700", fonts="Rajdhani:wght@600;700",
                  app_bg="radial-gradient(900px 420px at 12% -8%,rgba(41,227,255,.13),transparent 70%),"
                         "radial-gradient(800px 400px at 88% -8%,rgba(255,255,255,.07),transparent 70%),#070b16",
                  extra="[data-testid=stExpander] details{box-shadow:0 0 0 1px rgba(41,227,255,.07),0 10px 30px rgba(0,0,0,.45)}"
                        "h1,h2,h3,.dod-hero h1,.dod-load-title{text-shadow:0 0 18px rgba(41,227,255,.35)}"),
    "stealth": dict(name="Stealth", cost=700, level=2, blurb="Murdered-out. Pure black, white accents, sharp edges.",
                    accent="#ffffff", on="#000000", bg="#000000", card="#080808", panel="#0d0d0d", deep="#050505",
                    track="#1c1c1c", line="#1f1f1f", muted="#7a7a7a", radius="4px",
                    head="Barlow Condensed", head_w="700", fonts="Barlow+Condensed:wght@600;700",
                    app_bg="#000000",
                    extra="h1,h2,h3,h4,.dod-hero h1,[data-testid=stExpander] summary p strong{text-transform:uppercase;"
                          "letter-spacing:.06em}.dod-hero h1{font-style:normal}"),
    "gulf": dict(name="Gulf Livery", cost=800, level=2, blurb="Powder blue and orange: the most famous livery in racing.",
                 accent="#ff7a1a", on="#14171d", bg="#0f1a24", card="#12202c", panel="#152634", deep="#0d1720",
                 track="#20384a", line="#23435a", muted="#8aa4b8", radius="12px",
                 head="Archivo Black", head_w="400", fonts="Archivo+Black",
                 app_bg="linear-gradient(180deg,#8fc8e8 0 4px,#ff7a1a 4px 8px,transparent 8px),#0f1a24",
                 extra="[data-testid=stExpander] details{border-top:3px solid #8fc8e8!important}"
                       ".dod-hero h1{color:#8fc8e8;font-style:normal}.dod-hero h1::after{content:'';display:block;"
                       "height:4px;width:64px;margin-top:6px;background:#ff7a1a;border-radius:2px}"),
    "carbon": dict(name="Carbon", cost=900, level=3, blurb="Carbon-fibre weave, gloss panels, race red.",
                   accent="#e10600", on="#ffffff", bg="#1a1a1a", card="#161617", panel="#1d1d1f", deep="#121213",
                   track="#2b2b2e", line="#333336", muted="#9a9aa0", radius="10px",
                   head="Russo One", head_w="400", fonts="Russo+One",
                   app_bg="radial-gradient(#0d0d0d 15%,transparent 16%) 0 0/14px 14px,"
                          "radial-gradient(#0d0d0d 15%,transparent 16%) 7px 7px/14px 14px,"
                          "radial-gradient(rgba(255,255,255,.07) 15%,transparent 20%) 0 1px/14px 14px,"
                          "radial-gradient(rgba(255,255,255,.07) 15%,transparent 20%) 7px 8px/14px 14px,#1f1f21",
                   extra="[data-testid=stExpander] details{background:linear-gradient(180deg,#1f1f22,#141416)!important;"
                         "box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 8px 24px rgba(0,0,0,.5)}"
                         ".dod-hero h1{font-style:normal}"),
    "lemans": dict(name="Le Mans Dusk", cost=1200, level=3, blurb="Hour 20 of 24: sunset sky, frosted-glass panels.",
                   accent="#ffb347", on="#1a1020", bg="#1a1033", card="rgba(20,14,34,.55)", panel="rgba(28,20,44,.6)",
                   deep="rgba(16,10,28,.6)", track="rgba(255,255,255,.12)", line="rgba(255,255,255,.10)",
                   muted="#b8a8c8", radius="16px", head="Bebas Neue", head_w="400", fonts="Bebas+Neue",
                   app_bg="linear-gradient(180deg,#1a1033 0%,#2b1438 38%,#4a1f2c 72%,#6b2a1a 100%) fixed",
                   extra="[data-testid=stExpander] details,.dod-cluster,.dod-next{backdrop-filter:blur(12px);"
                         "-webkit-backdrop-filter:blur(12px)}h1,h2,h3,.dod-hero h1,[data-testid=stExpander] summary p strong"
                         "{letter-spacing:.04em}.dod-hero h1{font-style:normal;font-size:2.6rem}"),
    "arcade": dict(name="Pole Position '82", cost=1500, level=4, blurb="Arcade cabinet: neon grid, scanlines, pixel font.",
                   accent="#ff2bd6", on="#0b0016", bg="#0b0016", card="#120022", panel="#16002a", deep="#0d001a",
                   track="#2a0a44", line="#3b1460", muted="#a58fc4", radius="0px",
                   head="Press Start 2P", head_w="400", fonts="Press+Start+2P", head_scale=".62",
                   app_bg="linear-gradient(rgba(255,43,214,.07) 1px,transparent 1px) 0 0/100% 34px,"
                          "linear-gradient(90deg,rgba(0,255,200,.05) 1px,transparent 1px) 0 0/34px 100%,#0b0016",
                   extra="[data-testid=stApp]::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:999989;"
                         "background:repeating-linear-gradient(0deg,rgba(0,0,0,.18) 0 1px,transparent 1px 3px)}"
                         "[data-testid=stExpander] details{border:2px solid rgba(0,255,200,.35)!important}"
                         "h1,h2,h3,.dod-hero h1,.dod-load-title{text-shadow:0 0 10px rgba(255,43,214,.7)}"
                         ".dod-hero h1{font-style:normal}"),
}


def active_kit(state: dict) -> dict | None:
    """The kit being shown: a free preview from the shop (this visit only), else the one you've fitted."""
    k = st.session_state.get("kit_preview") or state.get("ui_kit", "stock")
    kit = KITS.get(k)
    return kit if kit and kit.get("accent") else None


def accent(state: dict) -> tuple[str, str]:
    kit = active_kit(state)
    if kit:
        return kit["accent"], kit["on"]
    k = state.get("ui_theme", "phoenix")
    _, acc, on, *_ = THEMES.get(k, THEMES["phoenix"])
    return acc, on


def _kit_swatch(k: str, kit: dict) -> str:
    """A tiny mock of the app drawn in the kit's own style."""
    if not kit.get("accent"):
        acc = THEMES.get("phoenix")[1]
        bg, card, line, head, r, on, muted = "#14171d", "#1b1f27", "#2c313c", "Saira Semi Condensed", "10px", "#14171d", "#8b909c"
        app_bg = bg
    else:
        acc, bg, card, line, head, r, on, muted, app_bg = (kit["accent"], kit["bg"], kit["card"], kit["line"], kit["head"],
                                                           kit["radius"], kit["on"], kit["muted"], kit["app_bg"])
    fs = ".62rem" if k == "arcade" else ".95rem"
    return (f"<div style='height:112px;border-radius:12px;overflow:hidden;border:1px solid #2c313c;background:{app_bg};"
            f"background-color:{bg};padding:12px;position:relative'>"
            f"<div style='background:{card};border:1px solid {line};border-radius:{r};padding:8px 10px'>"
            f"<div style=\"font-family:'{head}',sans-serif;font-size:{fs};color:#ece8df;margin-bottom:6px\">"
            f"🏁 TODAY'S MISSION</div><div style='height:5px;border-radius:3px;background:{line};overflow:hidden'>"
            f"<div style='width:62%;height:100%;background:{acc}'></div></div>"
            f"<div style='display:flex;gap:6px;margin-top:8px'><span style='background:{acc};color:{on};font-size:.68rem;"
            f"font-weight:700;padding:3px 9px;border-radius:{r}'>START</span><span style='color:{muted};font-size:.7rem'>"
            f"2/3 · 45m to go</span></div></div></div>")


def render_kits(state: dict) -> None:
    owned = state.setdefault("kits_owned", ["stock"])
    cur = state.get("ui_kit", "stock")
    prev = st.session_state.get("kit_preview")
    lvl_now = level_of(state["xp"])
    with fold("kits", "🏁 Kits — restyle the whole app", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            st.caption("A kit changes everything: background, cards, borders, fonts, corners and effects. "
                       "Try any of them free before you buy.")
            st.markdown("<style>@import url('" + _F + "&family=".join(k["fonts"] for k in KITS.values() if k.get("fonts"))
                        + "&display=swap');</style>", unsafe_allow_html=True)
            items = list(KITS.items())
            for i in range(0, len(items), 3):
                cols = st.columns(3)
                for col, (k, kit) in zip(cols, items[i:i + 3]):
                    with col:
                        st.markdown(_kit_swatch(k, kit) + f"<div style='margin-top:6px'><b>{kit['name']}</b></div>"
                                    f"<div style='color:var(--muted);font-size:.82rem;min-height:2.6em'>{kit['blurb']}</div>",
                                    unsafe_allow_html=True)
                        c1, c2 = st.columns(2)
                        if k == cur and not prev:
                            c1.caption("✅ Fitted")
                        elif k in owned:
                            if c1.button("Fit", key=f"kit_fit_{k}", use_container_width=True):
                                state["ui_kit"] = k
                                st.session_state.pop("kit_preview", None)
                                save_state(state)
                                flash(f"🏁 {kit['name']} fitted.")
                                st.rerun()
                        elif lvl_now < kit["level"]:
                            c1.caption(f"🔒 Level {kit['level']}")
                        elif c1.button(f"{art_price(state, kit['cost']):,} 🪙", key=f"kit_buy_{k}", use_container_width=True,
                                       disabled=state["coins"] < art_price(state, kit["cost"]), help="Buy it and fit it"):
                            bank(state, -art_price(state, kit["cost"]), f"🏁 Kit: {kit['name']}")
                            owned.append(k)
                            state["ui_kit"] = k
                            st.session_state.pop("kit_preview", None)
                            save_state(state)
                            flash(f"🏁 **{kit['name']}** bought and fitted.", celebrate=True, sound="jackpot")
                            st.rerun()
                        if k != "stock" and k not in owned:
                            if prev == k:
                                if c2.button("Stop", key=f"kit_stop_{k}", use_container_width=True):
                                    st.session_state.pop("kit_preview", None)
                                    st.rerun()
                            elif c2.button("👀 Try it", key=f"kit_try_{k}", use_container_width=True,
                                           help="Preview it on the whole app (just this visit)"):
                                st.session_state["kit_preview"] = k
                                st.rerun()


def kit_css(kit: dict) -> str:
    h, sc = f"'{kit['head']}',system-ui,sans-serif", kit.get("head_scale")
    size = (f"h1{{font-size:calc(2.75rem*{sc})!important}}h2{{font-size:calc(2.25rem*{sc})!important}}"
            f"h3{{font-size:calc(1.75rem*{sc})!important}}h4{{font-size:calc(1.5rem*{sc})!important}}"
            f".dod-hero h1{{font-size:calc(2.2rem*{sc})!important}}[data-testid=stExpander] summary p strong"
            f"{{font-size:.8em}}.dod-load-title{{font-size:1.3rem}}" if sc else "")
    r = kit["radius"]
    return (f":root{{--panel:{kit['panel']};--line:{kit['line']};--muted:{kit['muted']};--card:{kit['card']};"
            f"--deep:{kit['deep']};--track:{kit['track']}}}"
            f"[data-testid=stApp]{{background:{kit['app_bg']}!important;background-color:{kit['bg']}!important}}"
            f"[data-testid=stHeader],[data-testid=stBottomBlockContainer]{{background:transparent!important}}"
            f"[data-testid=stExpander] details{{background:{kit['card']};border-color:{kit['line']}!important;"
            f"border-radius:{r}!important}}"
            f"[data-testid=stExpander] summary:hover{{background:rgba(255,255,255,.03)}}"
            f"[data-testid=stVerticalBlock][class*=st-key-]{{border-color:{kit['line']}}}"
            f"[data-baseweb=select]>div,[data-baseweb=input],[data-baseweb=textarea],[data-baseweb=base-input],"
            f"[data-testid=stNumberInputContainer]{{background:{kit['panel']}!important;border-color:{kit['line']}!important;"
            f"border-radius:{r}!important}}"
            f"[data-baseweb=input] input,[data-baseweb=textarea] textarea{{background:transparent!important}}"
            f"[data-testid^=stBaseButton-secondary],[data-testid^=stBaseButton-pills],[data-testid=stButtonGroup] button"
            f"{{background:{kit['panel']}!important;border-color:{kit['line']}!important;border-radius:{r}!important}}"
            f"[data-testid^=stBaseButton-primary]{{border-radius:{r}!important}}"
            f"[data-baseweb=popover]>div,[data-baseweb=menu]{{background:{kit['deep']}!important}}"
            f".dod-cluster,.dod-next,.dod-load-track,.dod-load-lights{{border-radius:{r}!important}}"
            f"h1,h2,h3,h4,.dod-hero h1,.dod-sec,.dod-load-title,[data-baseweb=tab] p,[data-testid=stMetricValue],"
            f"[data-testid=stExpander] summary p strong,.dod-mt,.dod-next .t{{font-family:{h}!important;"
            f"font-weight:{kit['head_w']}!important}}"
            + size + kit.get("extra", ""))


def theme_css(state: dict) -> str:
    kit = active_kit(state)
    acc, on = accent(state)
    r, g, b = (int(acc[i:i + 2], 16) for i in (1, 3, 5))
    soft = f"rgba({r},{g},{b},.14)"
    imp = f"@import url('{_F}{kit['fonts']}&display=swap');" if kit else ""
    return f"""<style>{imp}
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
{kit_css(kit) if kit else ""}
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
        ("Coins", f"{coins:,}", "⬛ black flag" if coins < 0 else "", coins < 0),
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
    car = state["car"]
    mid = car.get("model") if car.get("model") in CAR_BY_ID else CARS[0]["id"]
    mini = carart.car_svg(CAR_BY_ID[mid]["body"], car["color"], car["number"], G.effective(car["parts"], mid),
                          cond, width=150)
    st.markdown(
        f"<div class='dod-cluster{intro}'>" + "".join(
            f"<div class='dod-cell{' carcell' if k == 'Car' else ''}'>"
            + (f"<div class='dod-mini-car'>{mini}</div>" if k == "Car" else "") + f"<div class='dod-k'>{k}</div>"
            f"<div class='dod-v{' bad' if bad else ''}{' chg' if k in prev and prev[k] != v else ''}'>{v}</div>"
            f"<div class='dod-s'>{sub or '&nbsp;'}</div></div>" for k, v, sub, bad in cells)
        + f"<div class='dod-xp'><b>Level {lvl}</b><div class='dod-bar'>"
          f"<i style='width:{pct:.0f}%;--from:{min(prev_pct, pct) if prev_pct <= pct else 0:.0f}%'></i></div>"
          f"{into}/{span} XP · task streak {state['streak']}</div></div>", unsafe_allow_html=True)


# ─────────────────────────── app ───────────────────────────
st.set_page_config(page_title="Deadline or Die", page_icon="🏁", layout="wide")
_T_SESSION = st.session_state.setdefault("_t_session", time.time())  # when this visit started (login timing)


@st.cache_resource
def _server_started() -> float:
    return time.time()


_COLD = time.time() - _server_started() < 90 and st.session_state.setdefault("_cold", True)
st.markdown(CSS, unsafe_allow_html=True)
with st.container(key="audio_session"):  # iOS: app sounds mix with your music instead of pausing it
    st.iframe("<script>try{for(const w of [window,parent])if(w.navigator.audioSession)"
              "w.navigator.audioSession.type='ambient';}catch(e){}</script>" + TRANSITIONS_JS, height=1)
if get_secret("NTFY_TOPIC") and not os.getenv("NTFY_TOPIC"):
    os.environ["NTFY_TOPIC"] = get_secret("NTFY_TOPIC")  # same secret seed as the nagger for surprise events

# Password gate — set APP_PASSWORD in secrets so nobody else can see your tasks and proof.
# Log in once per device: the key is kept in a cookie + localStorage (components/keeper), so links without ?k=,
# notification taps and the app waking from sleep all skip the password.
_pw = get_secret("APP_PASSWORD")


def _loader(tips: tuple[str, str, str] = ("Warming up the tyres…", "Fuelling up your save…",
                                          "Checking the pit wall…")) -> str:
    return ("<div class='dod-load'><div class='dod-load-lights'><i></i><i></i><i></i><i></i><i></i></div>"
            "<div class='dod-load-title'>DEADLINE <b>OR</b> DIE</div>"
            "<div class='dod-load-track'><div class='dod-load-car'>🏎️</div></div>"
            "<div class='dod-load-tips'>" + "".join(f"<span>{t}</span>" for t in tips) + "</div></div>")
_SORT = components.declare_component("sortable", path=str(Path(__file__).parent / "components" / "sortable"))


def sortable(groups: list[dict], key: str, cross: bool = False, numbered: bool = False) -> dict | None:
    """Drag-to-reorder lists (mouse or touch). Returns {group id: [item ids]} once per drag, else None."""
    try:
        ev = _SORT(groups=groups, cross=cross, numbered=numbered, accent=accent(globals().get("state") or {})[0]
                   if globals().get("state") else "#f5c518", key=key, default=None)
    except Exception:  # noqa: BLE001
        return None
    if ev and ev.get("t") != st.session_state.get(f"{key}_t"):
        st.session_state[f"{key}_t"] = ev.get("t")
        return ev.get("groups")
    return None


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
        st.markdown("<style>div[data-testid='stElementContainer']:has(iframe[title*='keeper'])"
                    "{position:absolute;width:0;height:0;overflow:hidden}</style>", unsafe_allow_html=True)
        if _held is None:  # still asking the browser whether it's a remembered device: just the loading screen
            st.markdown(_loader(("Checking this device…", "Warming up the tyres…", "Fuelling up your save…")),
                        unsafe_allow_html=True)
            box = st.container(key="pw_late")  # only shows if the check takes more than a few seconds
        else:
            st.markdown("<div class='dod-load' style='min-height:38vh;justify-content:flex-end'>"
                        "<div class='dod-load-lights'><i></i><i></i><i></i><i></i><i></i></div>"
                        "<div class='dod-load-title'>DEADLINE <b>OR</b> DIE</div></div>", unsafe_allow_html=True)
            box = st.container()
        entered = box.text_input("Password", type="password")
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
    _boot.markdown(_loader(), unsafe_allow_html=True)
state = load_state()
st.markdown(theme_css(state), unsafe_allow_html=True)
PROFILE = I.profile(state, now().date(), TZ)  # history before today → steers today's surprises (same in the nagger)
EV.set_profile(PROFILE)

# ⚡ Checking Notion for tasks you added there waits until the page is on screen (bottom of this script)
_SYNC_LATER = bool(st.session_state.get("_fresh_load") and notion_cfg())  # cleared once it has run
sync_msgs = st.session_state.pop("_sync_msgs", [])
_T_LOADED = time.time()

if _boot is not None:  # keep the start lights up (as a cover) while the page builds underneath; lifted at the very end
    _boot.markdown(_loader(("Warming up the tyres…", "Building your day…", "Checking Notion…")).replace(
        "class='dod-load'", "class='dod-load cover'", 1), unsafe_allow_html=True)
if notion_cfg() and needs_settle(state, now()):
    state = fresh_for_settle(state, fresh=st.session_state.pop("_fresh_this_run", False))
st.session_state.pop("_fresh_this_run", None)
if st.session_state.pop("_resave", False) or (getattr(_saver(), "dirty", False) and not _saver().pending()):
    st.session_state["_needs_save"] = True  # a save that didn't reach Notion goes again
crash_msgs = process_overdue(state)
crash_msgs += daily.settle(state, now(), bank, make_safety_car)
_excused = daily.excuse_outages(state, bank)
crash_msgs += DL.settle(state, DL.day_for(now(), _bailed(state)), bank, daily.is_rest)
crash_msgs += SH.settle(state, now(), bank)
crash_msgs += CM.settle(state, now(), bank, daily.level_factor(state))  # 📍 flakes and quota weeks
_made_good = daily.make_good(state, bank, DL)
_moved_off = daily.release_moved(state)
# 🏆 seasons: keep the season's best streak, close a finished season (trophy + fresh grid), rotate the top track
SE.track_streak(state, now().date())
_new_trophies = SE.rollover(state, now().date())
RV.SEASON = SE.season_of(now().date())[0]
if _new_trophies:
    save_state(state)
    for _tr in _new_trophies:
        flash(f"{_tr['cup']} **Season {_tr['n']} — {_tr['title']}**: {_tr['points']} pts · {_tr['finishes']} finishes · "
              f"{_tr['wins']} wins · best streak {_tr['best_streak']} d. Rival heat reset, and {RV.TOP_TRACK} has a new "
              f"layout ({RV.layout_name(RV.TOP_TRACK)}). Cars, paint and coins carry over.", celebrate=True, sound="jackpot")
if _moved_off:
    _made_good = _made_good + [
        "🗺️ Off today's mission: " + ", ".join(
            f"**{t['title']}** (now {date.fromisoformat(t['block']['date']):%a %b} {date.fromisoformat(t['block']['date']).day})"
            for t in _moved_off[:3]) + ". It joins that day's mission instead."]
_auto_q = daily.auto_qualify(state, now(), bank)
_made_good = _made_good + DL.fix_claims(state, now().date(), bank)
if _auto_q:
    _made_good = _made_good + [_auto_q]
if _made_good:
    st.session_state.setdefault("flash", []).extend(("info", m) for m in _made_good)
rust_msg = process_rust(state)
if _excused:
    crash_msgs = [m for m in crash_msgs if "MISSED QUALIFYING" not in m]
    st.session_state.setdefault("flash", []).extend(("info", m) for m in _excused)
if crash_msgs or rust_msg or _excused or _made_good or st.session_state.pop("_needs_save", False):
    save_state(state)
    if crash_msgs:
        st.session_state["sound"] = "fail"
if rebalance_pit_checks(state):
    save_state(state)
start_from_link(state)
jump_from_link()
apply_jump(state)
remember_app_url(state)
sync_alarms(state)

PLAYER = state["settings"].get("player_name") or "driver"
hour = now().hour
greet = "Late night" if hour < 5 else "Morning" if hour < 12 else "Afternoon" if hour < 18 else "Evening"
st.markdown(f"<div class='dod-hero'><h1>Deadline or Die</h1><p>{greet}, {html.escape(PLAYER)}. Prove it or pay for it."
            + (" It's a danger day: no one's watching, so everything you finish pays +20%."
               if now().weekday() in DANGER_DAYS else "") + "</p>" + crew_strip_html(state) + "</div>",
            unsafe_allow_html=True)
if st.session_state.get("nav", "🏁 Today") == "🏁 Today" or os.getenv("DOD_ALL_TABS"):  # the words on the wall: Today only
    _q, _who = CR.quote_of_day(now().date())
    st.markdown(f"<div class='dod-quote top'>“{html.escape(_q)}”<span>— {html.escape(_who)}</span></div>",
                unsafe_allow_html=True)
render_cluster(state)
render_debt(state)
if st.session_state.get("kit_preview") in KITS:
    _pk = KITS[st.session_state["kit_preview"]]
    _c1, _c2 = st.columns([5, 1], vertical_alignment="center")
    _c1.info(f"👀 Previewing the **{_pk['name']}** kit ({_pk['cost']:,} 🪙). Only you see this, just this visit. "
             "Buy it in Garage → 🏁 Kits.")
    if _c2.button("Stop preview", key="kit_stop_top", use_container_width=True):
        st.session_state.pop("kit_preview", None)
        st.rerun()

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
    (st.success if rust_msg.startswith("🧽") else st.warning)(rust_msg)
TOAST_ICON = {"success": "✅", "info": "💬"}
while _bg_notes():  # a background finish-line job hit a snag since your last tap
    flash(f"⚠️ {_bg_notes().pop(0)}", "warning")
for kind, m in st.session_state.pop("flash", []):
    if kind in TOAST_ICON and len(m) <= 170 and "\n" not in m:
        lead = m.split(" ", 1)
        icon = lead[0] if len(lead) == 2 and not lead[0][:1].isalnum() and len(lead[0]) <= 3 and "*" not in lead[0] else None
        st.toast(lead[1] if icon else m, icon=icon or TOAST_ICON[kind], duration="long" if len(m) > 90 else "short")
    elif kind == "success":  # the big win card: has its moment, then clears itself
        with st.container(key=f"win_{abs(hash(m)) % 10**8}"):
            st.success(m)
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

_reveal = st.session_state.pop("drop_reveal", None)
if _reveal:  # 🎁 the moment you open it: what you got, then the card clears itself
    with st.container(key="drop_reveal"):
        st.markdown(f"<div class='dod-drop'><div class='dod-drop-box'>{_reveal['icon']}</div>"
                    f"<div><div class='dod-drop-k'>{html.escape(_reveal['title'])} · opened</div>"
                    f"<div class='dod-drop-v'>{_md_inline(_reveal['out'])}</div></div></div>", unsafe_allow_html=True)
for e in EV.active(now()):
    claims = state.setdefault("event_claims", [])
    if e["id"] in claims:
        continue  # claimed drops leave; only live offers stay on screen
    left = fmt_left(e["end"] - now())
    with st.container(border=True, key=f"ev_card_{e['id'].replace('#', '_')}"):
        st.markdown(f"#### 🎉 LIVE · {e['title']} · {left} left")
        st.caption(e["banner"].replace("**", ""))
        if e["type"] in ("supply", "pitcrew"):
            if st.button("🎁 Open it" if e["type"] == "supply" else "🔧 Repair me", key=f"ev_{e['id']}", type="primary"):
                claims.append(e["id"])
                if e["type"] == "supply":
                    out = open_crate(state, {"reward": 45})
                else:
                    state["car"]["condition"] = min(100, state["car"]["condition"] + 30)
                    out = "🔧 Pit crew fixed you up: **+30% condition**."
                save_state(state)
                st.session_state["drop_reveal"] = {"title": e["title"], "out": out,
                                                   "icon": "🎁" if e["type"] == "supply" else "🔧"}
                st.session_state["celebrate"] = True
                st.session_state["sound"] = "jackpot"
                st.rerun()

snd = st.session_state.pop("sound", None)
if snd and state["settings"].get("sounds", True):
    with st.container(key="sfx"):  # plays, but the player bar stays out of sight
        st.markdown("<style>.st-key-sfx{position:fixed!important;left:-9999px;top:0;width:1px;height:1px;"
                    "overflow:hidden;opacity:0;pointer-events:none}</style>", unsafe_allow_html=True)
        st.audio(tone_wav(SOUNDS[snd]), format="audio/wav", autoplay=True)


render_up_next(state)  # 🎯 on every page, above the tabs
lvl = level_of(state["xp"])

open_tasks = sorted([t for t in state["tasks"] if t["status"] == "open"], key=lambda t: t["deadline"])
tab_today, tab_tasks, tab_reading, tab_goals, tab_stats, tab_garage, tab_race, tab_lounge, tab_set = st.tabs(
    ["🏁 Today", "✅ Tasks", "📚 Reading list", "🎯 Goals", "📒 Log", "🔧 Garage", "🏎️ Race", "🎰 Lounge", "⚙️ Settings"],
    key="nav", on_change="ignore" if os.getenv("DOD_ALL_TABS") else "rerun")  # remembers the open tab; only it runs

# ── Today: the cockpit. Do-now on the left, instruments on the right; stacks on a phone. ──
with tab_today:
  if tab_today.open is not False:
    # one row of two columns (no gaps on a wide screen); on a phone the CSS interleaves the sections so the
    # timer and dailies come right after the mission (see .st-key-today_grid)
    if state.get("timer"):  # a session running: the clock takes the stage, full width at the top
        with st.container(key="tg_live"):
            render_timer(state, big=True)
    with st.container(key="today_grid"):
        c_main, c_rail = st.columns([1.55, 1], gap="large")

        def _sec(key: str, title: str, sub: str = "") -> None:
            with st.container(key=key):
                st.markdown(f"<div class='dod-zone'><b>{title}</b><span>{sub}</span></div>", unsafe_allow_html=True)

        with c_main:
            with st.container(key="tg_checkin"):
                render_checkin(state)
            with st.container(key="tg_today"):
                render_today(state)
            _sec("tg_h_show", "Show up", "the things you said you'd be at, and the daily basics")
            with st.container(key="tg_commit"):
                render_commitments(state)
            _sec("tg_h_plan", "Plan", "goals, loose ends, what's coming")
            with st.container(key="tg_goals"):
                render_goals_today(state)
            with st.container(key="tg_todo"):
                render_todo(state)
            with st.container(key="tg_close"):
                render_close_day(state)
            with st.container(key="tg_board"):
                render_task_board(state, open_tasks)
        with c_rail:
            if not state.get("timer"):
                with st.container(key="tg_timer"):
                    render_timer(state)
            with st.container(key="tg_dailies"):
                render_dailies(state)
            _sec("tg_h_team", "Your team", "car, crew, season")
            with st.container(key="tg_car"):
                render_car_card(state)
            with st.container(key="tg_crew"):
                render_crew_card(state)
            if dealer_offer(state):
                with st.container(key="tg_dealer"):
                    render_dealer(state)
            with st.container(key="tg_season"):
                render_season_card(state)
            with st.container(key="tg_status"):
                render_race_status(state)
                _stt = daily.status(state, now())
                if _stt["qualified"] and not _stt["rest"] and not _stt["bailout"]:
                    _bail_button(state, _stt)  # (before qualifying it sits in the qualifying card)

# ── Pit Wall ──
# ── Tasks ──
with tab_tasks:
  if tab_tasks.open is not False:
    with fold("tasks_open", f"📋 **Open tasks** :gray[{len(open_tasks)}]", card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            if not open_tasks:
                st.caption("Nothing open. Add one below.")
            else:
                render_sort_pick(state, "sort_tasks")
            _ord = (open_tasks if sort_mode(state) == "mine" else RK.rank(open_tasks, sort_mode(state), now()))
            if _ord and sort_mode(state) == "start":
                st.markdown(f"<div class='dod-start'>👉 <b>Start here:</b> {html.escape(_ord[0]['title'])}"
                            f"<span>{html.escape(RK.why_first(_ord[0], now()))}</span></div>", unsafe_allow_html=True)
            for t in _ord:
                render_task_row(state, t, "tt_")
    redeemable = [t for t in state["tasks"] if t["status"] == "failed" and not t.get("abandoned")
                  and now() - parse_dt(t["failed_at"]) < timedelta(hours=REDEEM_WINDOW_H)]
    if redeemable:
        with fold("tasks_redeem", f"🩹 **Redeemable** :gray[{len(redeemable)}]", card=True) as _fo:
            if _open(_fo):  # collapsed = not built (faster page, smaller download)
                st.caption(f"Missed — finish within {REDEEM_WINDOW_H}h of the miss for half the penalty back.")
                for t in redeemable:
                    left = parse_dt(t["failed_at"]) + timedelta(hours=REDEEM_WINDOW_H) - now()
                    with st.expander(f"💀 {t['title']} · redeem by {_when(now() + left)}", key=f"exp_rd_{t['id']}",
                                     expanded=proof_open(f"redeem_{t['id']}")):
                        render_proof_form(state, t, "redeem")

    done = [t for t in state["tasks"] if t["status"] in ("done", "redeemed")]
    recents, seen_ = [], {t["title"].strip().lower() for t in open_tasks}
    for t in sorted(done, key=lambda t: t["completed_at"], reverse=True):
        if t["title"].strip().lower() not in seen_ and not t.get("block"):
            seen_.add(t["title"].strip().lower())
            recents.append(t)
    recents = recents[:15]

    def _again_row(t: dict) -> None:
        c1, c2 = st.columns([5, 1.3], vertical_alignment="center")
        c1.markdown(f"{html.escape(t['title'])} <small style='color:#8b909c'>· {min_label(t.get('minutes') or 30)}"
                    f" · last {parse_dt(t['completed_at']):%a %b %d}</small>", unsafe_allow_html=True)
        if c2.button("↻ Again", key=f"again_{t['id']}", use_container_width=True,
                     help="A fresh copy, due tonight. Lock it into today's mission from Today."):
            nt = make_task(t["title"], t.get("details", ""), datetime.combine(now().date(), dtime(23, 59), TZ),
                           None, t.get("consequence", ""), t.get("goal_id"), category=t.get("category"),
                           minutes=t.get("minutes"))
            if daily.peek_day(state, now().date()).get("qualified"):
                nt["mission_day"] = now().date().isoformat()
            state["tasks"].append(nt)
            save_state(state)
            flash(f"↻ **{nt['title']}** again, due tonight" + (" · in today's mission" if nt.get("mission_day") else "") + ".")
            st.rerun()

    if recents:
        with fold("tasks_recent", f"🕘 **Recent · do it again** :gray[{len(recents)}]", card=True) as _fo:
            if _open(_fo):  # collapsed = not built (faster page, smaller download)
                st.caption("Done before, not open now. One tap brings it back for today.")
                for t in recents[:4]:
                    _again_row(t)
                if len(recents) > 4:
                    with fold("recent_more", f"More ({len(recents) - 4})", False) as _fo:
                        if _open(_fo):  # collapsed = not built (faster page, smaller download)
                            for t in recents[4:]:
                                _again_row(t)

    st.markdown("<div class='dod-sec' style='margin-top:1.2rem'>🧰 Add &amp; manage</div>", unsafe_allow_html=True)
    with fold("new_task", "➕ New task", not open_tasks) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            task_form(state, "new_task_form")
    with fold("import", "📥 Import from Notion", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            notion_import(state)
    points_guide()
    if done:
        with fold("completed", f"🏆 Completed ({len(done)})", False) as _fo:
            if _open(_fo):  # collapsed = not built (faster page, smaller download)
                for t in sorted(done, key=lambda t: t["completed_at"], reverse=True)[:30]:
                    icon = "🏁" if t["status"] == "done" else "🩹"
                    st.markdown(f"{icon} **{t['title']}** · +{t.get('earned', 0)} 🪙 "
                                f"<small>· {parse_dt(t['completed_at']):%b %d}</small>", unsafe_allow_html=True)

def render_new_goal(state: dict) -> None:
    """A big goal, typed or picked from your Assignments board (read-only: the app never writes to it)."""
    today = now().date()
    bc = board_cfg(state)
    src = "✍️ Type it"
    if bc:
        src = st.segmented_control("Source", ["✍️ Type it", "📚 From Assignments"], default="✍️ Type it",
                                   key="ng_src", label_visibility="collapsed") or "✍️ Type it"
    title0, target0, page = "", today + timedelta(days=30), None
    if src == "📚 From Assignments":
        try:
            taken = {B.clean_id(x) for g in state["goals"] for x in (g.get("assign_page"), g.get("event_page")) if x}
            items = [b for b in _board_range(*bc, today.isoformat(), EVENT_LOOKAHEAD)
                     if not b.get("recurring") and B.clean_id(b["id"]) not in taken]
        except Exception as e:  # noqa: BLE001
            items = []
            st.caption(f"(Couldn't read the board: {e})")
        if not items:
            st.caption(f"Nothing upcoming on the board in the next {EVENT_LOOKAHEAD} days that isn't a goal yet.")
            return
        lbl = {b["id"]: _board_label(b, today) for b in items}
        pid = st.selectbox("Assignment", list(lbl), format_func=lbl.get, key="ng_pick")
        b = next(x for x in items if x["id"] == pid)
        title0, page = b["title"], b["id"]
        target0 = max(today, date.fromisoformat(b["date"])) if b.get("date") else target0
    k = f"ng_{page or 'typed'}"
    title = st.text_input("Goal", value=title0, key=f"{k}_t", placeholder="The big thing you're working towards")
    c1, c2 = st.columns([2, 1])
    why = c1.text_input("Why it matters (shown when you need it)", key=f"{k}_w")
    target = c2.date_input(togo_label("Target date", f"{k}_d", target0), value=target0, min_value=today, key=f"{k}_d")
    if st.button("🗺️ Create goal & plan it", type="primary", key=f"{k}_go"):
        if not (title or "").strip():
            st.error("Name the goal first.")
            return
        g = {"id": uuid.uuid4().hex[:10], "title": title.strip(), "why": (why or "").strip(),
             "target": target.isoformat(), "created": now().isoformat(), "claimed": False}
        if page:
            g["assign_page"] = page  # a reference only: Assignments stays read-only
        state["goals"].append(g)
        save_state(state)
        st.session_state["rm_open"] = g["id"]
        flash(f"🗺️ **{g['title']}** is on the board. Add stages and book work time in its roadmap below.")
        st.rerun()


def render_add_work(state: dict, g: dict) -> None:
    """➕ One form for everything you add to a roadmap. Two checkboxes decide what it is:
    🗓️ Book time  → it sits on a day and time (repeat it over several days). Alone, a block dies at the end of its day.
    📌 Deadline   → it's due by a date. Alone, it's a deliverable with no slot; with booking, missing the slot
                    isn't fatal: it only dies at its deadline."""
    gid, opts = g["id"], _stage_opts(g)
    target = date.fromisoformat(g["target"]) if g.get("target") else None
    today = now().date()
    last = max((date.fromisoformat(t["block"]["date"]) for t in R.goal_tasks(g, state["tasks"]) if t.get("block")),
               default=None)
    first0 = max(today, last + timedelta(days=1)) if last else today
    what = st.text_input("What", placeholder="Read · Meeting · Draft · Submit ethics amendment · Send draft to Walter",
                         key=f"aw_what_{gid}")
    under = st.selectbox("Part of", list(opts), format_func=opts.get, key=f"aw_under_{gid}")
    k1, k2 = st.columns(2)
    book = k1.checkbox("🗓️ Book time for it", value=True, key=f"aw_book_{gid}",
                       help="Puts it on a day and time: calendar, phone heads-up, that day's mission.")
    has_dl = k2.checkbox("📌 It has its own deadline", value=False, key=f"aw_dl_{gid}",
                         help="A date it must be done by. With booked time too, missing the slot isn't fatal: "
                              "it only dies at the deadline.")
    days, skip, first, start = 1, False, None, None
    if book:
        c1, c2, c3 = st.columns(3)
        first = c1.date_input(togo_label("First day" if not has_dl else "Work on it", f"aw_first_{gid}", first0),
                              value=first0, min_value=today, key=f"aw_first_{gid}")
        days = c2.number_input("Days", 1, 21, 1, key=f"aw_days_{gid}",
                               help="Read for 2 days → 2. One block per day, same time each day.")
        start = c3.time_input("Start", value=dtime(9, 0), step=900, key=f"aw_start_{gid}")
    c4, c5, c6 = st.columns(3)
    mins = c4.selectbox("Length" if book else "Est. length", BLOCK_LENGTHS, index=BLOCK_LENGTHS.index(60), format_func=min_label,
                        key=f"aw_len_{gid}")
    cat = c5.selectbox("Type", ["auto"] + list(V.CATEGORIES), format_func=cat_label, key=f"aw_cat_{gid}")
    if book and int(days) > 1:
        skip = c6.checkbox("Skip weekends", value=False, key=f"aw_skip_{gid}")
    due_d, due_t, rel = None, dtime(23, 59), False
    if has_dl:
        rel = bool(target) and st.segmented_control(
            "Deadline", ["Before the goal's due date", "Pick a date"], default="Before the goal's due date",
            key=f"aw_mode_{gid}") != "Pick a date"
        d1, d2 = st.columns(2)
        if rel:
            span = max(0, (target - today).days)
            before = d1.number_input(f"Days before {target:%b} {target.day} · {R.days_to_go(target, today)} (required)",
                                     0, span, value=None, step=1, key=f"aw_before_{gid}", placeholder="e.g. 7",
                                     help="0 = on the goal's due date. Counts back from it, so the plan moves with the goal.")
            due_d = target - timedelta(days=int(before)) if before is not None else None
        else:
            _picked = st.session_state.get(f"aw_due_{gid}")
            due_d = d1.date_input(("Deadline · " + R.days_to_go(_picked, today) if _picked else "Deadline (required)")
                                  + (f" · goal {R.days_to_go(target, today)}" if target else ""),
                                  value=None, min_value=today, key=f"aw_due_{gid}",
                                  help="The date it must be done by.")
        due_t = d2.time_input("Due at", value=dtime(23, 59), step=900, key=f"aw_due_t_{gid}")
        if due_d:
            gap = (target - due_d).days if target else None
            st.caption(f"📅 Due **{due_d:%a %b} {due_d.day}** · **{R.days_to_go(due_d, today)}**"
                       + ("" if gap is None else " · the goal's due date" if gap == 0 else
                          f" · {gap} day{'s' * (gap != 1)} before the goal's" if gap > 0 else
                          f" · {-gap} day{'s' * (gap != -1)} after the goal's"))
            if target and due_d > target:
                st.caption(f"⚠️ That's after the goal's target ({target:%a %b} {target.day}).")
        elif target:
            st.caption(f"🏁 The goal is due **{target:%a %b} {target.day}** · **{R.days_to_go(target, today)}**")
    if not book and not has_dl:
        st.caption("Tick at least one: book time for it, give it a deadline, or both.")
    label = ("🗓️📌 Book it with a deadline" if book and has_dl else "🗓️ Book it" if book else "📌 Add it")
    if not st.button(label, type="primary", key=f"aw_go_{gid}", disabled=not (book or has_dl)):
        return
    ds = R.block_days(first, int(days), skip) if book else []
    if not (what or "").strip():
        st.error("Name it first.")
    elif has_dl and not due_d:
        st.error("Set a deadline (or untick 📌).")
    elif has_dl and book and ds and ds[-1] > due_d:
        st.error("The booked day is after the deadline: move one of them.")
    else:
        due = datetime.combine(due_d, due_t, TZ) if has_dl else None
        made = []
        for i, d_ in enumerate(ds or [None], 1):
            title = what.strip() + (f" · day {i}/{len(ds)}" if len(ds) > 1 else "")
            t = make_task(title, f"🗺️ {g['title']}", due or now(), None, "", gid,
                          category=None if cat == "auto" else cat, minutes=int(mins))
            t["node"] = under or None
            if d_:
                t.update(R.block_fields(d_, start.strftime("%H:%M"), int(mins), TZ))
            if due:
                t["deadline"] = due.isoformat()
                if d_:
                    t["own_deadline"] = due.isoformat()
                if rel:
                    t["due_before_goal"] = (target - due_d).days  # the plan stays relative to the goal's date
            state["tasks"].append(t)
            made.append(t)
        save_state(state)
        if book:
            span = f"{ds[0]:%a %b} {ds[0].day}" + (f" → {ds[-1]:%a %b} {ds[-1].day}" if len(ds) > 1 else "")
            msg = (f"🗓️ Booked **{what.strip()}** · {len(ds)} block{'s' if len(ds) > 1 else ''} · {span} at "
                   f"{start:%I:%M %p}".replace(" 0", " ") + f" · +{made[0]['reward']} each")
        else:
            msg = f"📌 **{what.strip()}** added"
        flash(msg + (f" · due {_when(due)}" if due else "") + ".")
        for k_ in ("what", "due", "before", "days", "first", "under"):
            st.session_state.pop(f"aw_{k_}_{gid}", None)
        st.rerun()


def render_block_editor(state: dict, g: dict, only: str | None = None, kp: str = "be") -> None:
    """Edit any open piece of the roadmap: booked blocks and blocks with just a deadline. Rename, re-stage, move the
    deadline, book (or un-book) time for it, resize, or drop it. The Notion calendar card follows.
    only=<task id>: edit that one straight away (tapped on the flow chart)."""
    gid = g["id"]
    items = sorted((t for t in R.goal_tasks(g, state["tasks"]) if t["status"] == "open"),
                   key=lambda t: t.get("scheduled") or t["deadline"])
    if only:
        items = [t for t in items if t["id"] == only]
    if not items:
        st.caption("Nothing open to edit yet." if not only else "That one's finished (or gone), so there's nothing to edit.")
        return
    lbl = {t["id"]: f"{t['title']} · {R._fmt_block(t, TZ)}" for t in items}
    tid = only or st.selectbox("Block", list(lbl), format_func=lbl.get, key=f"{kp}_pick_{gid}")
    t = next(x for x in items if x["id"] == tid)
    b = t.get("block") or {}
    opts = _stage_opts(g)
    k = f"{kp}_{tid}"
    due0 = parse_dt(t.get("own_deadline") or t["deadline"])
    title = st.text_input("What", value=t["title"], key=f"{k}_t")
    under = st.selectbox("Part of", list(opts), index=list(opts).index(t.get("node") or "")
                         if (t.get("node") or "") in opts else 0, format_func=opts.get, key=f"{k}_u")
    c1, c2, c3 = st.columns(3)
    _picked = st.session_state.get(f"{k}_dd") or max(now().date(), due0.date())
    due_d = c1.date_input(f"Deadline · {R.days_to_go(_picked, now().date())}", value=max(now().date(), due0.date()),
                          min_value=now().date(), key=f"{k}_dd")
    due_t = c2.time_input("Due at", value=due0.timetz().replace(tzinfo=None), step=900, key=f"{k}_dt")
    cur_m = int(b.get("minutes") or t.get("minutes") or 45)
    lens = sorted(set(BLOCK_LENGTHS + [cur_m]))
    mins = c3.selectbox("Length", lens, index=lens.index(cur_m), format_func=min_label, key=f"{k}_m")
    book = st.toggle("🗓️ Booked time", value=bool(b), key=f"{k}_bk",
                     help="On: it sits on a day and time (calendar, heads-up, that day's mission). Off: just the deadline.")
    if book:
        b1, b2 = st.columns(2)
        bday0 = date.fromisoformat(b["date"]) if b else min(due_d, max(now().date(), due_d))
        day = b1.date_input(togo_label("Work on it", f"{k}_d", max(now().date(), bday0)), value=max(now().date(), bday0), min_value=now().date(), key=f"{k}_d")
        hh, mm = (int(x) for x in (b.get("start") or "09:00").split(":"))
        start = b2.time_input("Start", value=dtime(hh, mm), step=900, key=f"{k}_s")
    if g.get("target") and t.get("due_before_goal") is not None:
        st.caption(f"📅 Set relative to the goal's due date: saving keeps it relative "
                   f"({(date.fromisoformat(g['target']) - due_d).days} days before) · due **{R.days_to_go(due_d, now().date())}**.")
    else:
        st.caption(f"📅 Due **{due_d:%a %b} {due_d.day}** · **{R.days_to_go(due_d, now().date())}**"
                   + (f" · goal {R.days_to_go(date.fromisoformat(g['target']), now().date())}" if g.get("target") else ""))
    if st.button("💾 Save changes", type="primary", key=f"{k}_save") and (title or "").strip():
        if book and day > due_d:
            st.error("The booked day is after the deadline: move one of them.")
            return
        due = datetime.combine(due_d, due_t, TZ)
        t["title"], t["node"] = title.strip(), under or None
        if book:
            t.update(R.block_fields(day, start.strftime("%H:%M"), int(mins), TZ))
            t["own_deadline"] = due.isoformat()
            t["deadline"] = max(due, parse_dt(t["deadline"])).isoformat()
        else:
            for k_ in ("block", "scheduled", "scheduled_time", "own_deadline"):
                t.pop(k_, None)
            t["deadline"] = due.isoformat()
            if t.get("mission_day") and t["mission_day"] != now().date().isoformat():
                t.pop("mission_day", None)
        if t.get("due_before_goal") is not None and g.get("target"):
            t["due_before_goal"] = (date.fromisoformat(g["target"]) - due_d).days
        if int(mins) != int(t.get("minutes") or 0):
            v = V.value(t["category"], int(mins))
            t.update(minutes=int(mins), reward=v["reward"], penalty=v["penalty"], xp=v["xp"],
                     difficulty=V.size_label(int(mins)))
        save_state(state)
        flash(f"✏️ **{t['title']}** · due {_when(due)}" + (f" · booked {_when(R.block_at(t, TZ))}" if book else "")
              + ". Calendar updated.")
        st.rerun()
    if t.get("focus_min"):
        st.caption("Has focus time logged, so it can't be dropped: finish it instead.")
    elif st.button("🗑️ Drop this block (no penalty)", key=f"{k}_x",
                   help="Planned work you no longer need. It leaves the roadmap and the calendar."):
        t.update(status="cancelled", cancelled_at=now().isoformat())
        t.pop("mission_day", None)
        save_state(state)
        flash(f"🗑️ Dropped **{t['title']}** from the plan.")
        st.rerun()


def render_roadmap_draft(state: dict, g: dict) -> None:
    """✨ A starter plan for this goal, worked back from its target date (what the old event-prep did), as
    booked blocks you can edit before booking: step, day, time, length, stage."""
    gid = g["id"]
    today, target = now().date(), date.fromisoformat(g["target"])
    if target <= today:
        st.caption("The target date is today or past: move it in ✏️ Edit goal to draft a plan.")
        return
    kinds = list(P.KINDS)
    c1, c2 = st.columns([2, 1])
    kind = c1.selectbox("What is it?", kinds, index=kinds.index(P.guess_kind(g["title"])),
                        format_func=lambda k: P.KINDS[k][0], key=f"rd_kind_{gid}")
    at = c2.time_input("Usual start", value=dtime(10, 0), step=900, key=f"rd_at_{gid}")
    stage_names = ["🏁 The goal"] + [n["title"] for n in R.stages(g)]
    steps = P.plan(kind, target, today)
    if get_secret("ANTHROPIC_API_KEY"):  # 🤖 or let Claude draft the steps for THIS goal
        with st.popover("🤖 Let Claude draft it instead"):
            extra = st.text_area("Anything Claude should know (constraints, busy weeks…)", key=f"rd_ctx_{gid}", height=70)
            if st.button("Draft with Claude", key=f"rd_ai_go_{gid}"):
                with st.spinner("Planning…"):
                    try:
                        st.session_state[f"rd_ai_{gid}"] = [
                            {"title": x.get("title", ""), "due": max(today, min(target, to_date(x.get("due")) or target)),
                             "minutes": V.minutes_for_size(x.get("difficulty") if x.get("difficulty") in DIFFICULTY
                                                           else "Medium"), "category": None}
                            for x in ai_plan(state, g, extra) if x.get("title")]
                    except Exception as e:
                        st.error(str(e))
        if st.session_state.get(f"rd_ai_{gid}"):
            steps = st.session_state[f"rd_ai_{gid}"]
            st.caption("🤖 Claude's draft. " + ("" if True else ""))
            if st.button("↺ Back to the starter plan", key=f"rd_ai_x_{gid}", type="tertiary"):
                st.session_state.pop(f"rd_ai_{gid}", None)
                st.rerun()
    df = pd.DataFrame([{"add": True, "step": x["title"], "day": x["due"], "start": at,
                        "minutes": min(BLOCK_LENGTHS, key=lambda m: abs(m - int(x["minutes"] or 30))),
                        "stage": stage_names[0]} for x in steps])
    st.caption(f"Worked back from {target:%a %b} {target.day} ({(target - today).days} days). Change anything, "
               "untick what you don't need, then book it. Every row becomes a block on the chart, in Fortuna, "
               "and on the day it's booked for.")
    ed = st.data_editor(df, hide_index=True, key=f"rd_ed_{gid}_{kind}_{len(steps)}", use_container_width=True, column_config={
        "add": st.column_config.CheckboxColumn("✔", width="small"),
        "step": st.column_config.TextColumn("Step", width="large"),
        "day": st.column_config.DateColumn("Day", min_value=today, max_value=target),
        "start": st.column_config.TimeColumn("Start", step=900, format="h:mm a"),
        "minutes": st.column_config.SelectboxColumn("Length", options=BLOCK_LENGTHS),
        "stage": st.column_config.SelectboxColumn("Stage", options=stage_names),
    })
    rows = [r for r in ed.to_dict("records") if r["add"] and str(r["step"]).strip() and to_date(r["day"])]
    if rows:
        st.markdown("<div class='dod-togo'>" + "".join(
            f"<span><b>{html.escape(str(r['step'])[:28])}</b> · {R.days_to_go(to_date(r['day']), today)}</span>"
            for r in sorted(rows, key=lambda r: to_date(r["day"]))) + f"<span class='g'>🏁 goal · "
            f"{R.days_to_go(target, today)}</span></div>", unsafe_allow_html=True)
    if st.button(f"🗓️ Book {len(rows)} block{'s' * (len(rows) != 1)}", type="primary", key=f"rd_go_{gid}",
                 disabled=not rows):
        by_name = {n["title"]: n["id"] for n in R.stages(g)}
        for r in rows:
            st_ = r["start"] if isinstance(r["start"], dtime) else at
            mins = int(r["minutes"] or 30)
            t = make_task(str(r["step"]).strip(), f"🗺️ {g['title']}", now(), None, "", gid, minutes=mins,
                          category=next((c for _, ttl, _m, c in P.KINDS[kind][1] if ttl == r["step"]), None))
            t.update(R.block_fields(to_date(r["day"]), st_.strftime("%H:%M"), mins, TZ),
                     node=by_name.get(r["stage"]))
            state["tasks"].append(t)
        save_state(state)
        flash(f"🗓️ Booked {len(rows)} blocks for **{g['title']}**. Tap any box on the chart to fine-tune it.")
        st.rerun()


def render_stage_editor(state: dict, g: dict, only: str | None = None, kp: str = "se") -> None:
    """Rename a stage, change what it feeds into, or delete it (its blocks and sub-stages move up a level)."""
    gid = g["id"]
    if not R.stages(g):
        st.caption("No stages yet. Add one in 🧩 Add a stage.")
        return
    opts = _stage_opts(g)
    sid = only or st.selectbox("Stage", [n["id"] for n in R.stages(g)], format_func=lambda i: opts.get(i, i).strip(),
                               key=f"{kp}_pick_{gid}")
    n = next((x for x in R.stages(g) if x["id"] == sid), None)
    if not n:
        return
    allowed = {"": opts[""], **{x["id"]: opts[x["id"]] for x in R.move_options(g, sid)}}
    k = f"{kp}_{sid}"
    with st.form(f"{k}_form", border=False):
        name = st.text_input("Stage name", value=n["title"], key=f"{k}_t")
        cur = n.get("parent") or ""
        par = st.selectbox("Feeds into", list(allowed), index=list(allowed).index(cur) if cur in allowed else 0,
                           format_func=allowed.get, key=f"{k}_p")
        go = st.form_submit_button("💾 Save stage", type="primary")
    if go and (name or "").strip():
        R.update_stage(g, sid, title=name, parent=par or None)
        save_state(state)
        flash(f"🧩 Stage **{name.strip()}** saved.")
        st.rerun()
    inside = len(R.children(g, sid)) + sum(t.get("node") == sid for t in R.goal_tasks(g, state["tasks"]))
    up = opts.get(n.get("parent") or "", "").strip()
    if st.checkbox(f"Delete this stage" + (f" (its {inside} item{'s' * (inside != 1)} move up to {up})" if inside else ""),
                   key=f"{k}_delchk") and st.button("🗑️ Delete stage", key=f"{k}_del"):
        R.delete_stage(g, state["tasks"], sid)
        st.session_state.pop(f"flow_sel_{gid}", None)
        save_state(state)
        flash(f"🗑️ Stage **{n['title']}** deleted" + (f"; its contents moved up to {up}." if inside else "."))
        st.rerun()


def render_task_quick_edit(state: dict, g: dict, tid: str) -> None:
    """A milestone (not a booked block): rename it, move it to a stage, change its due date."""
    t = next((x for x in R.goal_tasks(g, state["tasks"]) if x["id"] == tid), None)
    if not t or t["status"] != "open":
        st.caption("That one's finished (or gone), so there's nothing to edit.")
        return
    opts = _stage_opts(g)
    k = f"me_{tid}"
    dl = parse_dt(t["deadline"])
    with st.form(f"{k}_form", border=False):
        title = st.text_input("What", value=t["title"], key=f"{k}_t")
        c1, c2 = st.columns(2)
        under = c1.selectbox("Part of", list(opts), index=list(opts).index(t.get("node") or "")
                             if (t.get("node") or "") in opts else 0, format_func=opts.get, key=f"{k}_u")
        due = c2.date_input(togo_label("Due", f"{k}_d", max(now().date(), dl.date())), value=max(now().date(), dl.date()), min_value=now().date(), key=f"{k}_d")
        go = st.form_submit_button("💾 Save", type="primary")
    if go and (title or "").strip():
        t.update(title=title.strip(), node=under or None,
                 deadline=datetime.combine(due, dl.time().replace(tzinfo=None), TZ).isoformat())
        save_state(state)
        flash(f"✏️ **{t['title']}** saved.")
        st.rerun()


_FLOW = components.declare_component("flow", path=str(Path(__file__).parent / "components" / "flow"))


def render_roadmap_arrange(state: dict, g: dict) -> None:
    """↕ The roadmap as drag lists: one per stage (and the goal itself). Drag a step into another stage to move it
    there; drag it up or down to do it sooner or later: booked steps trade their time slots, in order."""
    gid = g["id"]
    tasks = [t for t in R.goal_tasks(g, state["tasks"]) if t["status"] == "open"]
    when = lambda t: t.get("scheduled") or t["deadline"]  # noqa: E731
    sub = lambda t: (_when(R.block_at(t, TZ)) + f" · {min_label(t['block']['minutes'])}" if t.get("block")  # noqa: E731
                     else "due " + _when(parse_dt(t["deadline"])))
    groups = [{"id": "__goal", "title": f"🏁 <b>{html.escape(g['title'])}</b> (straight into the goal)",
               "items": [{"id": t["id"], "label": t["title"], "sub": sub(t)}
                         for t in sorted((t for t in tasks if not t.get("node")), key=when)]}]
    for n in R.stages(g):
        groups.append({"id": n["id"], "title": "&nbsp;" * 3 * R.depth(g, n["id"]) + f"🧩 <b>{html.escape(n['title'])}</b>",
                       "items": [{"id": t["id"], "label": t["title"], "sub": sub(t)}
                                 for t in sorted((t for t in tasks if t.get("node") == n["id"]), key=when)]})
    st.caption("Press and drag (hold first on a phone). Moving a booked step up or down swaps it into an earlier "
               "or later slot; its length stays the same.")
    got = sortable(groups, key=f"rm_sort_{gid}", cross=True)
    if not got:
        return
    by_id = {t["id"]: t for t in tasks}
    changed = False
    for grp, ids in got.items():
        node = None if grp == "__goal" else grp
        mine = [by_id[i] for i in ids if i in by_id]
        for t in mine:
            if (t.get("node") or None) != node:
                t["node"] = node
                changed = True
        bl = [t for t in mine if t.get("block")]
        slots = sorted((t["block"]["date"], t["block"]["start"]) for t in bl)
        for t, (d_, s_) in zip(bl, slots):
            if (t["block"]["date"], t["block"]["start"]) != (d_, s_):
                t.update(R.block_fields(date.fromisoformat(d_), s_, int(t["block"]["minutes"]), TZ))
                changed = True
    if changed:
        save_state(state)
        flash("↕ Roadmap rearranged. The chart, Fortuna and your phone alerts follow.")
        st.rerun()


NOTE_COLOR_LABELS = {"yellow": "🟨 Yellow", "blue": "🟦 Blue", "green": "🟩 Green", "pink": "🩷 Pink", "grey": "⬜ Grey"}


def _note_targets(state: dict, g: dict) -> dict:
    """Where a note can sit on the roadmap: the goal itself, any stage, or any block."""
    opts = {"goal": f"🏁 The goal: {g['title'][:40]}"}
    for n, label in NG._stage_order(g):
        opts["s_" + n["id"]] = f"🧩 {label[:50]}"
    for t in sorted(R.goal_tasks(g, state["tasks"]), key=lambda t: t["deadline"]):
        opts["t_" + t["id"]] = f"▪️ {t['title'][:46]}"
    return opts


def render_goal_notes(state: dict, g: dict, only: str | None = None) -> None:
    """📝 Notes on the roadmap: sticky notes for the goal's aspects (why it matters, risks, who's involved…),
    pinned to the goal, a stage or a block, so they show up right on the flow chart."""
    gid = g["id"]
    targets = _note_targets(state, g)
    notes_ = g.setdefault("notes", [])
    if only is None:
        st.caption("Sticky notes that sit on the flow chart: the goal's aspects, risks, people, ideas. "
                   "Pin each to the goal, a stage or a block. Tap one on the chart to edit it.")
        with st.form(f"gn_add_{gid}", clear_on_submit=True, border=False):
            txt = st.text_area("Note", placeholder="e.g. Walter needs 2 weeks to review · Ethics is the bottleneck",
                               height=80, key=f"gn_txt_{gid}")
            c1, c2 = st.columns([2, 1])
            on = c1.selectbox("Pin it to", list(targets), format_func=targets.get, key=f"gn_on_{gid}")
            col = c2.selectbox("Colour", list(NOTE_COLOR_LABELS), format_func=NOTE_COLOR_LABELS.get, key=f"gn_col_{gid}")
            if st.form_submit_button("📝 Add note", type="primary") and (txt or "").strip():
                notes_.append({"id": uuid.uuid4().hex[:8], "text": txt.strip()[:400], "on": on, "color": col,
                               "created": now().isoformat()})
                save_state(state)
                st.rerun()
    for n in [x for x in notes_ if only is None or x["id"] == only]:
        k = f"{'gnf' if only else 'gn'}_{gid}_{n['id']}"
        with st.container(border=only is None, key=f"{k}_box"):
            txt = st.text_area("Note", value=n["text"], height=80, key=f"{k}_t",
                               label_visibility="collapsed" if only is None else "visible")
            c1, c2, c3, c4 = st.columns([2, 1.2, 1, 0.6], vertical_alignment="bottom")
            cur = n.get("on") if n.get("on") in targets else "goal"
            on = c1.selectbox("Pinned to", list(targets), index=list(targets).index(cur), format_func=targets.get,
                              key=f"{k}_on")
            col = c2.selectbox("Colour", list(NOTE_COLOR_LABELS), format_func=NOTE_COLOR_LABELS.get, key=f"{k}_c",
                               index=list(NOTE_COLOR_LABELS).index(n.get("color", "yellow"))
                               if n.get("color", "yellow") in NOTE_COLOR_LABELS else 0)
            if c3.button("💾 Save", key=f"{k}_s", use_container_width=True) and (txt or "").strip():
                n.update(text=txt.strip()[:400], on=on, color=col)
                save_state(state)
                st.rerun()
            if c4.button("🗑️", key=f"{k}_x", use_container_width=True, help="Delete this note"):
                g["notes"] = [x for x in notes_ if x["id"] != n["id"]]
                st.session_state.pop(f"flow_sel_{gid}", None)
                save_state(state)
                st.rerun()


def render_quick_note(state: dict, g: dict, target: str, head) -> None:
    """＋ on a roadmap box: one field, already pinned to that box. Enter or Add and it's on the chart."""
    gid = g["id"]
    targets = _note_targets(state, g)
    if target not in targets:
        target = "goal"
    head.markdown(f"**📝 Note on** {html.escape(targets[target])}")
    with st.form(f"qn_{gid}", clear_on_submit=True, border=False, enter_to_submit=True):
        txt = st.text_input("Note", placeholder="An aspect, a risk, a person, an idea…", key=f"qn_txt_{gid}",
                            label_visibility="collapsed", max_chars=400)
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        col = c1.pills("Colour", list(NOTE_COLOR_LABELS), default="yellow", key=f"qn_col_{gid}",
                       format_func=lambda c: NOTE_COLOR_LABELS[c].split()[0], label_visibility="collapsed") or "yellow"
        if c2.form_submit_button("📝 Add", type="primary", use_container_width=True) and (txt or "").strip():
            g.setdefault("notes", []).append({"id": uuid.uuid4().hex[:8], "text": txt.strip()[:400], "on": target,
                                              "color": col, "created": now().isoformat()})
            st.session_state.pop(f"flow_sel_{gid}", None)
            save_state(state)
            st.rerun()


def render_flow(state: dict, g: dict) -> None:
    """The roadmap as a flow chart you can tap: the box you tap opens for editing right underneath."""
    gid = g["id"]
    dot = R.dot(g, state["tasks"], now(), accent(state)[0])
    sel = st.session_state.get(f"flow_sel_{gid}")
    try:
        ev = _FLOW(dot=dot, sel=sel or "", key=f"flow_{gid}", default=None)
    except Exception:  # noqa: BLE001 — never lose the chart: fall back to the plain (non-tappable) one
        ev = None
        st.graphviz_chart(dot, use_container_width=True)
    if ev and ev.get("t") != st.session_state.get(f"flow_t_{gid}"):
        st.session_state[f"flow_t_{gid}"] = ev.get("t")
        sel = st.session_state[f"flow_sel_{gid}"] = ("add:" if ev.get("add") else "") + (ev.get("id") or "")
        _flow_preselect(state, g, sel)
    if not sel:
        return False
    with st.container(border=True, key=f"flow_ed_{gid}"):
        c1, c2 = st.columns([6, 1], vertical_alignment="center")
        if c2.button("✕", key=f"flow_x_{gid}", help="Close the editor"):
            st.session_state.pop(f"flow_sel_{gid}", None)
            st.rerun()
        if sel.startswith("add:"):  # the ＋ badge: just a quick note, nothing else
            render_quick_note(state, g, sel[4:], c1)
            return False
        t = next((x for x in state["tasks"] if x["id"] == sel[2:]), None) if sel.startswith("t_") else None
        n = next((x for x in R.stages(g) if x["id"] == sel[2:]), None) if sel.startswith("s_") else None
        name = ("the goal" if sel == "goal" else t["title"] if t else n["title"] if n else
                "a note" if sel.startswith("n_") else "the roadmap")
        c1.markdown(f"**✏️ Editing {html.escape(name)}** <span style='color:#8b909c;font-size:.85em'>· "
                    f"every roadmap tool is here</span>", unsafe_allow_html=True)
        if sel.startswith("n_"):
            render_goal_notes(state, g, only=sel[2:])
        if t and t["status"] == "open":
            render_block_play(state, t, kp="fbp")
        elif t:  # finished blocks can't be re-booked, but their name / stage / date can change
            render_task_quick_edit(state, g, sel[2:])
        render_roadmap_planner(state, g, sel=sel)
    return True


def _flow_preselect(state: dict, g: dict, sel: str) -> None:
    """A fresh tap on the chart points the editor's pickers at what you tapped."""
    gid = g["id"]
    if sel.startswith("t_") and any(t["id"] == sel[2:] and t["status"] == "open" for t in R.goal_tasks(g, state["tasks"])):
        st.session_state[f"be_pick_{gid}"] = sel[2:]
    elif sel.startswith("s_") and any(n["id"] == sel[2:] for n in R.stages(g)):
        st.session_state[f"se_pick_{gid}"] = sel[2:]


def start_block(state: dict, t: dict, mins: int, every: int = FLOW_CHECK) -> None:
    """▶ on a roadmap block: start the focus timer on it — 🌊 flow (FLOW_MODE) or a set length."""
    if mins == FLOW_MODE:
        _start_timer(state, t, FLOW_CAP)
        state["timer"].update(flow=True, check=int(every), every=int(every), work=None, brk=None)
        save_state(state)
        flash(f"🌊 **{t['title']}** — flow timer counting up. Checks in every {every} min.", sound="win")
    else:
        _start_timer(state, t, mins)
        flash(f"▶️ **{t['title']}** — {mins}-min focus timer running. Phone face-down.", sound="win")


def render_block_play(state: dict, t: dict, kp: str = "bp") -> None:
    """The ▶ on a block: asks flow (default) or a set timer, then starts it."""
    if t["status"] != "open":
        return
    running = state.get("timer")
    with st.popover("▶ Start a focus timer on it" if kp == "fbp" else "▶", help="Start the focus timer on this block",
                    use_container_width=True):
        if running:
            cur = next((x["title"] for x in state["tasks"] if x["id"] == running.get("task_id")), "another task")
            st.warning(f"⏱️ A timer is already running on **{cur}**. Stop it first.")
            return
        own = int((t.get("block") or {}).get("minutes") or t.get("minutes") or 0)
        lens = [FLOW_MODE] + sorted({5, 10, 15, 25, 30, 45, 60, *([own] if 5 <= own <= 240 else [])})
        m = st.radio("How long?", lens, key=f"{kp}_len_{t['id']}", horizontal=True,
                     format_func=lambda x: "🌊 Flow" if x == FLOW_MODE else
                     f"{x} min" + (" (block)" if x == own else ""))
        every = FLOW_CHECK
        if m == FLOW_MODE:
            every = _flow_every_pick(state, f"{kp}_every_{t['id']}")
            st.caption(f"🌊 Flow counts up with no breaks and checks you're still going every {every} min. "
                       f"One free pause banked per stretch.")
        else:
            st.caption("A set timer with your usual break setting.")
        if st.button("▶️ Start", type="primary", use_container_width=True, key=f"{kp}_go_{t['id']}"):
            start_block(state, t, m, every)
            st.rerun()


def render_block_plays(state: dict, g: dict) -> None:
    """A ▶ for every open block under the goal's flow chart."""
    open_ = sorted((x for x in state["tasks"] if x.get("goal_id") == g["id"] and x["status"] == "open"),
                   key=lambda x: (x.get("block") or {}).get("date") or x["deadline"][:10])
    if not open_:
        return
    with st.container(key=f"bplays_{g['id']}"):
        for t in open_:
            c1, c2 = st.columns([7, 1], vertical_alignment="center")
            b = t.get("block")
            when = (f"{date.fromisoformat(b['date']):%a %b %d} · {b['start']} · {b['minutes']} min" if b
                    else f"due {parse_dt(t['deadline']):%b %d}")
            c1.markdown(f"{html.escape(t['title'])} <small style='color:var(--muted)'>· {when}</small>",
                        unsafe_allow_html=True)
            with c2:
                render_block_play(state, t, kp=f"bp_{g['id']}")


def render_goal_edit(state: dict, g: dict, k0: str = "ge") -> None:
    target = date.fromisoformat(g["target"])
    with st.form(f"{k0}_form_{g['id']}", border=False):
        nt = st.text_input("Goal", value=g["title"], key=f"{k0}_t_{g['id']}")
        c1, c2 = st.columns([2, 1])
        nw = c1.text_input("Why it matters", value=g.get("why", ""), key=f"{k0}_w_{g['id']}")
        nd = c2.date_input(togo_label("Target date", f"{k0}_d_{g['id']}", target), value=target, key=f"{k0}_d_{g['id']}")
        if st.form_submit_button("💾 Save", type="primary") and (nt or "").strip():
            g.update(title=nt.strip(), why=(nw or "").strip(), target=nd.isoformat())
            moved_ = 0
            for x in state["tasks"]:  # tasks set relative to the due date move with it
                if x.get("goal_id") == g["id"] and x["status"] == "open" and x.get("due_before_goal") is not None:
                    old_ = parse_dt(x.get("own_deadline") or x["deadline"])
                    new_ = datetime.combine(nd - timedelta(days=int(x["due_before_goal"])), old_.timetz())
                    if new_ != old_:
                        if x.get("block"):
                            x["own_deadline"] = new_.isoformat()
                            day_end = datetime.combine(date.fromisoformat(x["block"]["date"]), dtime(23, 59), TZ)
                            x["deadline"] = max(new_, day_end).isoformat()
                        else:
                            x["deadline"] = new_.isoformat()
                        moved_ += 1
            if moved_:
                st.session_state.setdefault("flash", []).append(
                    ("info", f"📅 {moved_} task{'s' * (moved_ != 1)} set relative to the due date moved with it."))
            save_state(state)
            flash(f"✏️ **{g['title']}** updated" + (" (and its Assignments card)." if B.is_long_term(g)
                                                      and board_cfg(state) else "."))
            st.rerun()


def _stage_opts(g: dict) -> dict[str, str]:
    out = {"": "🏁 Straight into the goal"}

    def walk(parent, lvl):
        for n in R.children(g, parent):
            out[n["id"]] = "  " * lvl + ("└ " if lvl else "") + "🧩 " + n["title"]
            walk(n["id"], lvl + 1)
    walk(None, 0)
    return out


BLOCK_LENGTHS = [5, 10, 15, 30, 45, 60, 90, 120, 180, 240]


def render_roadmap_planner(state: dict, g: dict, sel: str | None = None) -> None:
    """Stages (nestable) + scheduled work blocks for one goal. sel = what was tapped on the flow chart: the pane
    opens there on the matching tab (with a 🎯 Goal tab too), already pointed at it."""
    gid = g["id"]
    opts = _stage_opts(g)
    labels = ["✨ Draft for me", "➕ Add work", "✏️ Edit blocks", "🧩 Add a stage", "🧩 Edit stages", "📝 Notes"]
    if sel is not None:
        labels.append("🎯 Goal")
        open_t = next((t for t in R.goal_tasks(g, state["tasks"]) if "t_" + t["id"] == sel), None)
        default = ("✏️ Edit blocks" if open_t and open_t["status"] == "open" else "🧩 Edit stages" if sel.startswith("s_")
                   else "📝 Notes" if sel.startswith("n_") else "🎯 Goal" if sel == "goal" else "➕ Add work")
        tabs = st.tabs(labels, default=default, key=f"rmtabs_{gid}_{st.session_state.get(f'flow_t_{gid}') or 0}")
        with tabs[6]:
            render_goal_edit(state, g, "fg")
    else:
        tabs = st.tabs(labels)
    t0, t1, t4, t2, t3, t6 = tabs[:6]
    with t6:
        render_goal_notes(state, g)
    with t0:
        render_roadmap_draft(state, g)
    with t1:
        render_add_work(state, g)
    with t4:
        render_block_editor(state, g)
    with t2:
        with st.form(f"rs_form_{gid}", clear_on_submit=True, border=False):
            name = st.text_input("Stage", placeholder="e.g. Literature review · Data analysis · Write-up")
            par = st.selectbox("Feeds into", list(opts), format_func=opts.get, key=f"rs_par_{gid}")
            if st.form_submit_button("🧩 Add stage", type="primary") and (name or "").strip():
                R.add_stage(g, name, par or None)
                save_state(state)
                flash(f"🧩 Stage **{name.strip()}** added. Book work blocks into it.")
                st.rerun()
        st.caption(f"Clear every block under a stage → **+{R.STAGE_BASE}–{R.STAGE_MAX}** stage bonus. "
                   "Stages can sit inside other stages.")
    with t3:
        render_stage_editor(state, g)


# ── Goals ──
with tab_reading:
  if tab_reading.open is not False:
    render_reading_list(state)

with tab_goals:
  if tab_goals.open is not False:
    with fold("new_goal", "🗺️ New goal", not state["goals"]) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            render_new_goal(state)


    has_key = bool(get_secret("ANTHROPIC_API_KEY"))
    for g in state["goals"]:
        gtasks = R.goal_tasks(g, state["tasks"])  # dropped (cancelled) blocks don't count
        n_done = sum(t["status"] in R.DONE for t in gtasks)
        target = date.fromisoformat(g["target"])
        with st.container(border=True, key=f"goalcard_{g['id']}"):
            fk_ = f"goal_{g['id']}"
            g_open = state.setdefault("folds", {}).get(fk_, True)
            h1, h2 = st.columns([12, 1], vertical_alignment="center")
            h1.markdown(f"### {P.KINDS[g['event_kind']][0].split()[0] if g.get('event_kind') in P.KINDS else '🎯'} "
                        f"{g['title']}")
            h2.button("▲" if g_open else "▼", key=f"gfold_{g['id']}", on_click=_toggle_fold, args=(state, fk_, True),
                      help="Fold this goal up" if g_open else "Open this goal")
            if not g_open:
                n_open_ = sum(1 for t in gtasks if t["status"] == "open")
                st.caption(f"{n_done}/{len(gtasks)} done · {n_open_} open · target {target:%b} {target.day} · "
                           f"{R.days_to_go(target, now().date())}")
                continue
            if g.get("why"):
                st.caption(f"Why: {g['why']}")
            for ev in g.get("events", []):
                st.caption(f"🗓️ Feeds in: {ev['title']} · {date.fromisoformat(ev['date']):%b %d}")
            st.progress(n_done / len(gtasks) if gtasks else 0.0,
                        text=f"{n_done}/{len(gtasks)} milestones · {'📅 event' if g.get('event_kind') else 'target'} "
                             f"{target:%b %d, %Y} "
                             f"({(target - now().date()).days} days)")
            render_turbo(state, g)
            big = R.goal_bonus(g, state["tasks"])
            flow_ed = False  # True when the editor is open under the flow chart (then it holds the planner)
            if gtasks or R.stages(g) or R.notes(g):  # any goal with something in it gets its chart
                n_open = sum(1 for t in gtasks if t["status"] == "open")
                with fold(f"flow_{g['id']}", f"🗺️ Flowchart · {len(R.stages(g))} stages · {n_open} open blocks") as _fo:
                    if _open(_fo):  # collapsed = not built (faster page, smaller download)
                        flow_ed = render_flow(state, g)
                render_block_plays(state, g)
                if st.toggle("↕ Drag to rearrange", key=f"rm_arr_{g['id']}",
                             help="Drag steps between stages, or up/down to change which comes first."):
                    render_roadmap_arrange(state, g)
                st.caption(f"🪙 Each block pays its own coins · 🧩 a cleared stage +{R.STAGE_BASE}–{R.STAGE_MAX} · "
                           f"🏆 the whole goal **+{big}**")
            else:
                for t in sorted(gtasks, key=lambda t: t["deadline"]):
                    icon = {"open": chip(parse_dt(t["deadline"])), "done": "🏁", "redeemed": "🩹",
                            "failed": "💀"}[t["status"]]
                    st.markdown(f"{icon} {t['title']} <small>· {parse_dt(t['deadline']):%b %d}</small>",
                                unsafe_allow_html=True)

            with st.expander("✏️ Edit goal", key=f"exp_ge_{g['id']}"):
                render_goal_edit(state, g)
            with st.expander("🗺️ Plan the roadmap · stages + booked work time", key=f"exp_rm_{g['id']}",
                             expanded=(not gtasks and not R.stages(g)) or st.session_state.get("rm_open") == g["id"]):
                if flow_ed:
                    st.caption("It's open under the flowchart ↑ right now (✕ there closes it and brings it back here).")
                else:
                    render_roadmap_planner(state, g)

            if gtasks and len(gtasks) >= 3 and n_done == len(gtasks) and not g.get("claimed"):
                if st.button(f"🏆 Claim finish-line bonus (+{big} 🪙)", key=f"claim_{g['id']}",
                             type="primary"):
                    g["claimed"] = True
                    bank(state, big, f"🏆 Goal complete: {g['title']}")
                    state["xp"] += GOAL_BONUS[1]
                    save_state(state)
                    flash(f"🏆 Goal **{g['title']}** complete! +{big} coins, +{GOAL_BONUS[1]} XP.",
                          celebrate=True)
                    st.rerun()

            if not any(t["status"] == "open" for t in gtasks):
                if st.checkbox("Delete this goal", key=f"gdel_chk_{g['id']}") and \
                        st.button("Delete", key=f"gdel_{g['id']}"):
                    card = g.get("assign_out") or (_saver().known_goals.get(g["id"]) or {}).get("assign_out")
                    if card and get_secret("NOTION_TOKEN"):  # take its card off the Assignments calendar too
                        try:
                            Notion(get_secret("NOTION_TOKEN")).req("PATCH", f"/pages/{card}", json={"archived": True})
                        except Exception:  # noqa: BLE001
                            pass
                    state["goals"].remove(g)
                    save_state(state)
                    st.rerun()

# ── Stats ──
VIZ = {"normal": "#3987e5", "dead": "#d95926", "peak": "#199e70", "low": "#1d2735", "grid": "#2b2e36"}


PERIODS = ["Week", "30 days", "Month", "Year"]


def _period(kind: str, back: int, today: date) -> tuple[date, date, str]:
    if kind == "Week":
        lo = today - timedelta(days=today.weekday()) - timedelta(weeks=back)
        hi = lo + timedelta(days=6)
        return lo, hi, ("This week" if back == 0 else "Last week" if back == 1 else f"Week of {lo:%b} {lo.day}")
    if kind == "30 days":  # rolling: the last 30 days up to today, then 30-day steps back
        hi = today - timedelta(days=30 * back)
        lo = hi - timedelta(days=29)
        return lo, hi, ("Last 30 days" if back == 0 else f"{lo:%b} {lo.day} – {hi:%b} {hi.day}")
    if kind == "Month":
        y, m = today.year, today.month - back
        while m < 1:
            y, m = y - 1, m + 12
        lo = date(y, m, 1)
        hi = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        return lo, hi, f"{lo:%B %Y}"
    lo, hi = date(today.year - back, 1, 1), date(today.year - back, 12, 31)
    return lo, hi, str(lo.year)


def _day_name(peak_h: int | None, focus: float, goal: int) -> str:
    """A Strava-style title for the day from when you worked and how much."""
    if not focus:
        return "Rest day so far"
    when = ("Early" if peak_h < 8 else "Morning" if peak_h < 12 else "Afternoon" if peak_h < 17
            else "Evening" if peak_h < 21 else "Late-night") if peak_h is not None else "Focus"
    size = "Monster" if focus >= goal * 1.5 else "Big" if focus >= goal else "Solid" if focus >= goal * .5 else "Quick"
    kind = "grind" if focus >= goal else "session" if focus < 90 else "block"
    return f"{size} {when.lower() if size else when} {kind}".capitalize()


def _rings_svg(vals: list[tuple[float, str]], size: int = 132) -> str:
    """Activity rings: (fraction, colour) from the outside in; past 100% the ring laps itself."""
    out = [f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">']
    for i, (f, col) in enumerate(vals):
        r = size / 2 - 9 - i * 15
        circ = 2 * math.pi * r
        out.append(f'<circle cx="{size / 2}" cy="{size / 2}" r="{r:.1f}" fill="none" stroke="{col}" stroke-opacity=".18" stroke-width="11"/>')
        f1 = min(f, 1.0)
        if f1 > 0:
            out.append(f'<circle cx="{size / 2}" cy="{size / 2}" r="{r:.1f}" fill="none" stroke="{col}" stroke-width="11" '
                       f'stroke-linecap="round" stroke-dasharray="{circ * f1:.1f} {circ:.1f}" '
                       f'transform="rotate(-90 {size / 2} {size / 2})"/>')
        if f > 1:
            f2 = min(f - 1, 1.0)
            out.append(f'<circle cx="{size / 2}" cy="{size / 2}" r="{r:.1f}" fill="none" stroke="{_mix(col, "#ffffff", .25)}" '
                       f'stroke-width="11" stroke-linecap="round" stroke-dasharray="{circ * f2:.1f} {circ:.1f}" '
                       f'transform="rotate(-90 {size / 2} {size / 2})"/>')
    return "".join(out) + "</svg>"


def estimate_accuracy(state: dict, today: date, days: int = 28):
    """Median actual ÷ estimated minutes for recently finished tasks with a real time:
    the 'Actual time taken' you typed, or the focus timer when it was the full proof.
    Returns (overall, count, [(category, ratio)] for categories with 3+ tasks) or None."""
    since = (today - timedelta(days=days)).isoformat()
    rows = []
    for t in state.get("tasks", []):
        if t.get("status") not in ("done", "redeemed") or (t.get("completed_at") or "")[:10] < since:
            continue
        est = t.get("minutes") or 0
        act = t.get("actual_min") or (t.get("proof_timer") if not t.get("prorate") else None)
        if est > 0 and act:
            rows.append((t.get("category") or "other", act / est))
    if len(rows) < 3:
        return None
    by: dict = {}
    for c_, r_ in rows:
        by.setdefault(c_, []).append(r_)
    cats = sorted(((c_, statistics.median(v)) for c_, v in by.items() if len(v) >= 3), key=lambda x: -x[1])
    return statistics.median(r_ for _, r_ in rows), len(rows), cats[:3]


def render_today_recap(state: dict) -> None:
    """🏁 Today, like a post-workout screen: a name for the day, activity rings, the big numbers, a timeline of your
    sessions over a heat strip of the hours, and the splits."""
    n_ = now()
    today = n_.date()
    acc = accent(state)[0]
    goal = int(NU.cfg(state)["focus_goal"])
    logs = sorted((x for x in state.get("focus_log", []) if (parse_dt(x["start"]).astimezone(TZ).date() if x.get("start")
                                                               else date.fromisoformat(x["date"]) if x.get("date") else None) == today),
                  key=lambda x: x.get("start") or "")
    timed = [x for x in logs if x.get("start")]  # (very old entries have no start time: counted, not drawn)
    g = I.focus_grid(state, today, today, TZ)
    focus = sum(g["day"].values())
    week = I.focus_grid(state, today - timedelta(days=7), today - timedelta(days=1), TZ)
    avg7 = sum(week["day"].values()) / 7
    longest = max((float(x.get("min", 0)) for x in logs), default=0.0)
    hours = {h: g["dh"].get((today, h), 0.0) for h in range(5, 24)}
    peak = max(hours, key=hours.get) if focus else None
    stt = daily.status(state, n_)
    m_all = [t for t in stt["mission"] if t["status"] != "cancelled"]
    m_done = len(stt["mission_done"])
    done = [t for t in state["tasks"] if t.get("status") in ("done", "redeemed") and t.get("completed_at")
            and parse_dt(t["completed_at"]).astimezone(TZ).date() == today]
    led = [e for e in state.get("ledger", []) if parse_dt(e["ts"]).astimezone(TZ).date() == today]
    earned = sum(e["delta"] for e in led if e["delta"] > 0)
    net = sum(e["delta"] for e in led)
    races = [r for r in state.get("races", []) if (r.get("ts") or "")[:10] == today.isoformat()]
    title = _day_name(peak, focus, goal)
    rings = _rings_svg([(focus / goal if goal else 0, "#ff375f"), (m_done / len(m_all) if m_all else 0, "#3ddc84"),
                        (longest / 60, "#29e3ff")])
    vs = focus - avg7
    # timeline: 5 AM → midnight, every session as a block; the hour strip under it is today's row of the heatmap
    H0, H1, W_ = 5, 24, 600.0
    def xh(t_):  # noqa: E306
        return (t_ - H0) / (H1 - H0) * W_
    blocks = []
    for x in timed:
        st_ = parse_dt(x["start"]).astimezone(TZ)
        a = st_.hour + st_.minute / 60
        b = a + float(x.get("min", 0)) / 60
        if b < H0 or a > H1:
            continue
        t_ = next((t["title"] for t in state["tasks"] if t["id"] == x.get("task")), "Focus")
        blocks.append(f'<rect x="{xh(max(a, H0)):.1f}" y="6" width="{max(2.5, xh(min(b, H1)) - xh(max(a, H0))):.1f}" height="26" rx="5" '
                      f'fill="{acc}"><title>{html.escape(t_[:60])} · {st_:%I:%M %p} · {hmin(float(x.get("min", 0)))}</title></rect>')
    top_ = max(hours.values()) or 1
    strip = "".join(f'<rect x="{xh(h) + 1:.1f}" y="40" width="{W_ / (H1 - H0) - 2:.1f}" height="14" rx="3" '
                    f'fill="{acc if v else "#262b36"}" fill-opacity="{(.18 + .82 * v / top_) if v else 1:.2f}">'
                    f'<title>{_hlabel(h)} · {hmin(v)}</title></rect>' for h, v in hours.items())
    ticks = "".join(f'<text x="{xh(h):.1f}" y="70" font-size="10" fill="#8b909c" text-anchor="middle">{_hlabel(h)}</text>'
                    for h in (6, 9, 12, 15, 18, 21))
    nowx = xh(n_.hour + n_.minute / 60)
    now_mk = (f'<line x1="{nowx:.1f}" y1="0" x2="{nowx:.1f}" y2="56" stroke="#ece8df" stroke-opacity=".5" stroke-dasharray="2 3"/>'
              if H0 <= n_.hour < H1 else "")
    timeline = (f'<svg viewBox="0 0 {W_:.0f} 74" width="100%" xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="6" width="{W_:.0f}" height="26" rx="6" fill="#1b1f27"/>{"".join(blocks)}{strip}{now_mk}{ticks}</svg>')
    tiles = [("Focus", hmin(focus), (f"{'+' if vs >= 0 else '−'}{hmin(abs(vs))} vs your 7-day avg" if avg7 or focus else "")),
             ("Sessions", str(len(logs)), f"avg {hmin(focus / len(logs))}" if logs else ""),
             ("Longest stint", hmin(longest) if longest else "—", "an hour block ✓" if longest >= 60 else
              (f"{hmin(60 - longest)} short of an hour" if longest else "")),
             ("Finished", str(len(done)), f"mission {m_done}/{len(m_all)}" if m_all else ""),
             ("Coins", f"{'+' if net >= 0 else '−'}{abs(net)}", f"earned {earned}" if earned else ""),
             ("Best hour", _hlabel(peak) if peak is not None else "—", hmin(hours[peak]) if peak is not None else "")]
    splits = "".join(
        f"<tr><td>{parse_dt(x['start']).astimezone(TZ).strftime('%I:%M %p').lstrip('0')}</td><td>"
        f"{html.escape(next((t['title'] for t in state['tasks'] if t['id'] == x.get('task')), 'Focus')[:46])}</td>"
        f"<td>{hmin(float(x.get('min', 0)))}</td><td>{'🏁' if x.get('full') else ''}{'📦' * min(5, (lambda d_: len(d_) if isinstance(d_, list) else int(d_ or 0))(x.get('drops')))}</td></tr>"
        for x in timed)
    st.markdown(
        f"<div class='dod-today'><div class='top'><div><div class='when'>{n_:%A, %B} {n_.day} · Today</div>"
        f"<div class='ttl'>{html.escape(title)}</div>"
        f"<div class='sub'>🔥 {stt['day_streak']}-day streak · {'✅ qualified' if stt['qualified'] else '⏳ not qualified yet'}"
        + (f" · 🏎️ {len(races)} race{'s' * (len(races) != 1)}" if races else "") + "</div></div>"
        f"<div class='rings'>{rings}<div class='lg'><span style='color:#ff375f'>● Focus {int(min(999, 100 * focus / goal)) if goal else 0}%</span>"
        f"<span style='color:#3ddc84'>● Mission {m_done}/{len(m_all)}</span>"
        f"<span style='color:#29e3ff'>● Hour block {int(min(100, 100 * longest / 60))}%</span></div></div></div>"
        "<div class='tiles'>" + "".join(f"<div><span>{a}</span><b>{b}</b><i>{c}</i></div>" for a, b, c in tiles) + "</div>"
        f"<div class='tl'><div class='lab'>Today's sessions · the strip is today's row of the heatmap</div>{timeline}</div>"
        + (f"<table class='splits'><tr><th>Start</th><th>Task</th><th>Time</th><th></th></tr>{splits}</table>" if timed
           else "<div class='none'>No timer sessions yet today. Start one from Today and this fills in live.</div>")
        + "</div>", unsafe_allow_html=True)


def render_focus_periods(state: dict) -> None:
    """⏱️ When you actually work: timer sessions only, by week / month / year, with the previous period to compare."""
    import altair as alt
    acc = accent(state)[0]
    light = _mix(acc, "#ffffff", .55)
    today = now().date()
    c1, c2, c3, c4 = st.container(key="fx_row").columns([2.4, .45, .45, 2], vertical_alignment="center")
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
    delta = (f"<span>{'▲' if total >= prev else '▼'} <b>{hmin(abs(total - prev))}</b> vs previous</span>"
             if prev or total else "")
    st.markdown("<div class='dod-pills'>"
                f"<span>⏱️ <b>{hmin(total)}</b> focused</span>"
                f"<span>📅 <b>{len(active)}</b>/{len(days_in) or 0} days</span>"
                + (f"<span>Avg <b>{hmin(total / len(active))}</b> on days you worked</span>" if active else "")
                + (f"<span>🏆 Best <b>{best:%a %b} {best.day}</b> · {hmin(g['day'][best])}</span>" if best else "")
                + delta + "</div>", unsafe_allow_html=True)
    if not total:
        st.caption("No timer sessions in this period. Only the ⏱️ focus timer counts here: claiming a task or "
                   "ticking a daily isn't working time.")
        return
    # 1) over time
    if kind == "Year":
        label_of = lambda d: f"{d:%b}"  # noqa: E731
        rows = [{"When": date(lo.year, m, 1).strftime("%b"), "i": m,
                 "Hours": round(sum(v for d, v in g["day"].items() if d.month == m) / 60, 1),
                 "Time": hmin(sum(v for d, v in g["day"].items() if d.month == m))} for m in range(1, 13)]
    else:
        label_of = ((lambda d: f"{d:%a}") if kind == "Week" else (lambda d: f"{d.month}/{d.day}") if kind == "30 days"
                    else (lambda d: str(d.day)))  # noqa: E731
        rows = [{"When": label_of(d), "i": i,
                 "Hours": round(g["day"].get(d, 0) / 60, 2), "Time": hmin(g["day"].get(d, 0)), "now": d == today}
                for i, d in enumerate(lo + timedelta(days=k) for k in range((hi - lo).days + 1))]
    df = pd.DataFrame(rows)
    unit = "month" if kind == "Year" else "day"
    st.markdown(f"**Focus over time** · hours per {unit} · <span style='opacity:.6'>tap bars to filter the chart "
                f"below</span>", unsafe_allow_html=True)
    # one selection drives both charts: tap bars here and "When in the day" narrows to them
    pick = alt.selection_point(name="pick", fields=["When"], toggle="true", empty=True)
    top_chart = alt.Chart(df).mark_bar(cornerRadiusEnd=4, color=acc,
                                       **({} if kind in ("Month", "30 days") else {"size": 26})).encode(
        x=alt.X("When:N", sort=alt.SortField("i"), title=None,
                axis=alt.Axis(labelAngle=-50 if kind == "30 days" else 0, labelFontSize=9 if kind == "30 days" else 11)),
        y=alt.Y("Hours:Q", title="Hours"), tooltip=["When", alt.Tooltip("Time:N", title="Focus")],
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
    hrs["Avg/day"] = [msec(sum(v for (d, hh), v in g["dh"].items() if hh == h and in_sel(d)) / span) for h in hrs["h"]]
    top = hrs.sort_values("Min/day", ascending=False).iloc[0]
    scope = (f"{', '.join(sorted(chosen, key=lambda w: df.loc[df['When'] == w, 'i'].iloc[0]))} only"
             if chosen else label)
    st.markdown(f"**When in the day** · {scope} · avg minutes per working day at each hour"
                + (f" · peak **{top['Hour']}**" if top["Min/day"] > 0 else " · nothing logged"))
    _chart(alt.Chart(hrs).mark_bar(cornerRadiusEnd=3, color=acc).encode(
        x=alt.X("Hour:N", sort=alt.SortField("h"), title=None),
        y=alt.Y("Min/day:Q", title="Min / day"), tooltip=["Hour", alt.Tooltip("Avg/day:N", title="Avg/day")]).properties(height=170))
    # 3) weekday × hour
    wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if kind == "Week":
        cells = [{"Day": f"{lo + timedelta(days=i):%a}", "d": i, "Hour": _hlabel(h), "h": h,
                  "Minutes": round(g["dh"].get((lo + timedelta(days=i), h), 0)),
                  "Focus": hmin(g["dh"].get((lo + timedelta(days=i), h), 0))} for i in range(7) for h in range(5, 24)]
        ttl = "**Day × hour** · minutes"
    else:
        agg = defaultdict(float)
        for (d, h), v in g["dh"].items():
            agg[(d.weekday(), h)] += v
        cells = [{"Day": wd[i], "d": i, "Hour": _hlabel(h), "h": h, "Minutes": round(agg.get((i, h), 0)), "Focus": hmin(agg.get((i, h), 0))}
                 for i in range(7) for h in range(5, 24)]
        ttl = "**Weekday × hour** · total minutes in the period"
    st.markdown(ttl)
    _chart(alt.Chart(pd.DataFrame(cells)).mark_rect(cornerRadius=3, stroke="#0e1117", strokeWidth=2).encode(
        x=alt.X("Hour:N", sort=alt.SortField("h"), title=None),
        y=alt.Y("Day:N", sort=alt.SortField("d"), title=None),
        color=alt.Color("Minutes:Q", scale=alt.Scale(range=[VIZ["low"], acc, light], interpolate="rgb"),
                        legend=alt.Legend(title="Min")),
        tooltip=["Day", "Hour", "Focus"]).properties(height=220))


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
    stats_view = st.segmented_control("Log view", ["📊 Stats", "📸 Scrapbook", "📓 Journal"], default="📊 Stats",
                                      key="stats_view", label_visibility="collapsed") or "📊 Stats"
    if stats_view == "📸 Scrapbook":
        render_scrapbook(state)
    elif stats_view == "📓 Journal":
        render_journal(state)
  if tab_stats.open is not False and stats_view == "📊 Stats":
    import altair as alt
    _acc = accent(state)[0]
    VIZ = {**VIZ, "normal": _acc, "light": _mix(_acc, "#ffffff", .55)}
    with fold("stats_today", f"🏁 Today · {now():%a %b} {now().day}", card=True) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            render_today_recap(state)
    full = I.history(state, now().date() + timedelta(days=1), TZ)  # last 28 days, today included
    k = st.container(key="stat_kpis").columns(4)
    k[0].metric("Finished · 28 days", full["done"],
                help="Tasks you finished with proof (incl. redeemed) in the last 28 days.")
    rate = full["on_time"] / full["done"] if full["done"] else None
    k[1].metric("On time", f"{rate:.0%}" if rate is not None else "—",
                delta=f"{full['failed']} missed" if full["failed"] else None, delta_color="inverse")
    k[2].metric("Focus", (lambda m_: f"{m_ // 60}h {m_ % 60:02d}m" if m_ >= 60 else f"{m_}m")(int(round(full['focus_min']))), help="Timer-logged work minutes (breaks excluded).")
    k[3].metric("Active days", f"{full['active_days']}/28")
    zc_ = zotero_cfg(state)
    if zc_:
        try:
            papers_ = _zotero_reading(*zc_)
        except Exception as e:
            papers_ = None
            st.caption(f"(Couldn't read your reading list from Zotero: {e})")
        if papers_:
            n_ = {s_: sum(p["status"] == s_ for p in papers_) for s_ in READING_LABELS}
            r_ = st.columns(4)
            r_[0].metric("📚 Papers read", n_["read"], help="All time, from your Reading list tab.")
            r_[1].metric("Reading now", n_["reading"])
            r_[2].metric("Still to read", n_["unread"])
            r_[3].metric("Dropped", n_["dropped"])
    hr_ = DL.hit_rate(state, now().date())
    if hr_ is not None:
        st.caption(f"🔁 Dailies hit rate (28 days): **{hr_:.0%}**")
    ea_ = estimate_accuracy(state, now().date())
    if ea_:
        r_, n_, cats_ = ea_
        verdict_ = ("right on" if 0.9 <= r_ <= 1.1 else
                    f"tasks take **{r_:.1f}×** what you plan" if r_ > 1 else f"tasks take **{r_:.0%}** of what you plan")
        st.caption(f"⏳ Estimates (28 days, {n_} tasks with a real time): {verdict_}"
                   + (" · " + " · ".join(f"{V.CATEGORIES.get(c_, {}).get('label', c_)} ×{v_:.1f}" for c_, v_ in cats_)
                      if cats_ else ""),
                   help="From the 'Actual time taken' you enter when submitting proof, or the focus timer when it "
                        "was the proof. Median of actual ÷ estimate.")

    if not full["done"] and not full["focus_min"]:
        st.info("Nothing logged yet. Finish a task or run a focus session and this page starts filling in.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Hours by category** · 28 days")
            cat = pd.DataFrame([{"Category": V.CATEGORIES.get(c_, {}).get("label", c_), "Hours": round(m_ / 60, 1), "Time": hmin(m_)}
                                for c_, m_ in full["cat_min"].items()]).sort_values("Hours", ascending=False) \
                if full["cat_min"] else pd.DataFrame({"Category": [], "Hours": []})
            _chart(alt.Chart(cat).mark_bar(cornerRadiusEnd=4, color=VIZ["normal"]).encode(
                x=alt.X("Hours:Q", title="Hours"),
                y=alt.Y("Category:N", sort="-x", title=None, scale=alt.Scale(paddingInner=0.35),
                        axis=alt.Axis(labelLimit=160)),
                tooltip=["Category", alt.Tooltip("Time:N", title="Focus")]).properties(height=max(150, 46 * len(cat))))
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
                   f"(you're at {PROFILE['active_days']} day(s), {hmin(PROFILE['total_min'])}, up to yesterday). "
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
    with fold("table_view", "📋 Table view", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
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
            rpp = REPAIR_COST_PER_PT * (0.75 if "medic" in state.get("crew", []) else 1)  # 🩺 Noor
            afford = min(missing, int(max(state["coins"], 0) // rpp))
            if afford:
                if st.button(f"🔧 Repair +{afford}% ({round(afford * rpp)} 🪙)"):
                    car["condition"] += afford
                    bank(state, -round(afford * rpp), "🔧 Repairs")
                    save_state(state)
                    flash("Repaired.")
                    st.rerun()
            else:
                st.caption("Can't afford repairs. Go finish something.")

    render_crew_hire(state)
    render_kits(state)
    with fold("paint", "🎨 Paint shop — colour the whole app", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            _kit_on = active_kit(state)
            st.caption(f"Your **{_kit_on['name']}** kit sets its own colours: switch to Stock (above) to use these."
                       if _kit_on else "Unlock Honda colours for the app itself: buttons, timer, instrument cluster, everything.")
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
                    elif st.button(f"{dealer_price(state, 'theme', k, cost):,} 🪙", key=f"theme_buy_{k}", use_container_width=True,
                                   disabled=state["coins"] < dealer_price(state, "theme", k, cost)):
                        bank(state, -dealer_price(state, "theme", k, cost), f"🎨 Paint: {name}")
                        _dealer_sold(state, "theme", k)
                        owned_t.append(k)
                        state["ui_theme"] = k
                        save_state(state)
                        flash(f"🎨 **{name}** unlocked and applied.", celebrate=True, sound="jackpot")
                        st.rerun()

    with fold("showroom", "🏢 Showroom — the Honda & Acura ladder", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            lvl_now = level_of(state["xp"])
            owned = car.setdefault("owned", ["civic_si"])
            for m in CARS:
                paint_, num_ = SHOWROOM_PAINT.get(m["id"], ("#c8102e", 1))
                locked_ = lvl_now < m["level"] and m["id"] not in owned
                tag = "🟢 driving" if m["id"] == car.get("model") else "✅ owned" if m["id"] in owned else \
                      ("🔒 level " + str(m["level"]) if lvl_now < m["level"] else f"{m['cost']:,} 🪙")
                with st.container(border=True, key=f"sr_{m['id']}"):
                    st.markdown(f"<div class='dod-sr{' locked' if locked_ else ''}'>"
                                + carart.car_svg(m["body"], paint_, num_, SHOWROOM_SPEC.get(m["id"], {}), 100, width=640,
                                                 studio=True) + "</div>", unsafe_allow_html=True)
                    c1, c2 = st.columns([3, 2], vertical_alignment="center")
                    c1.markdown(f"<div class='dod-sr-n'>{m['name']}</div><div class='dod-sr-s'>Base {m['base']} · tunes to "
                                f"L{G.cap(m['id'])} · {m['blurb']}</div>", unsafe_allow_html=True)
                    if m["id"] == car.get("model"):
                        c2.caption(tag)
                    elif m["id"] in owned:
                        if c2.button("Drive it", key=f"drive_{m['id']}", use_container_width=True):
                            car["model"] = m["id"]
                            save_state(state)
                            st.rerun()
                    elif lvl_now < m["level"]:
                        c2.caption(tag)
                    elif c2.button(f"Buy · {dealer_price(state, 'car', m['id'], m['cost']):,} 🪙", key=f"buy_{m['id']}",
                                   disabled=state["coins"] < dealer_price(state, "car", m["id"], m["cost"]),
                                   type="primary", use_container_width=True):
                        bank(state, -dealer_price(state, "car", m["id"], m["cost"]), f"🏢 Bought {m['name']}")
                        _dealer_sold(state, "car", m["id"])
                        owned.append(m["id"])
                        car["model"] = m["id"]
                        save_state(state)
                        flash(f"🔑 **{m['name']}** is yours. Every coin of it came from finished work.", celebrate=True,
                              sound="jackpot")
                        st.rerun()

    ready_, n_own, n_max = prestige_ready(state)
    pres = int(state.get("prestige", 0))
    with fold("prestige", f"⭐ Prestige{f' ×{pres}' if pres else ''}", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
            st.caption(f"Own the whole ladder ({len(CARS)} cars) and tune every part to L{MAX_PART_LEVEL}, then retire the "
                       f"build: all parts go back to stock, you keep every car, your paint and your coins, and you get a "
                       f"permanent ⭐ badge plus **+{int(PRESTIGE_STEP * 100)}% coins on every task** "
                       f"(stacks to +{int(PRESTIGE_STEP * PRESTIGE_MAX * 100)}%).")
            st.progress(min(1.0, (n_own + n_max) / (len(CARS) + len(PARTS))),
                        text=f"🚗 {n_own}/{len(CARS)} cars owned · 🔧 {n_max}/{len(PARTS)} parts at L{MAX_PART_LEVEL}"
                             + (f" · ⭐ ×{pres} (+{int((prestige_mult(state) - 1) * 100)}% coins now)" if pres else ""))
            if ready_:
                sure = st.checkbox("I'm retiring this build: every part back to stock", key="pres_sure")
                if st.button("⭐ Retire the build", type="primary", disabled=not sure, key="pres_go"):
                    for k in PARTS:
                        car["parts"][k] = 0
                    state["prestige"] = pres + 1
                    state.setdefault("prestige_log", []).append({"at": now().isoformat(), "n": pres + 1})
                    save_state(state)
                    flash(f"⭐ **Prestige {pres + 1}.** The build is retired; the badge is forever. Task coins now pay "
                          f"×{prestige_mult(state):.2f}. Time to build it again.", celebrate=True, sound="jackpot")
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

    with fold("livery", "🎨 Livery", False) as _fo:
        if _open(_fo):  # collapsed = not built (faster page, smaller download)
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
        rp_ = st.session_state.get("race_replay")
        racing = bool(rp_ and not rp_.get("revealed"))
        left_t, why_t = race_tickets(state)
        # 🏁 Sunday Grand Prix · 🎟️ Invitational: the big-stakes events, on top when they're on
        if gp_open(state):
            g_ = gp_track(state)
            with st.container(border=True, key="gp_card"):
                st.markdown(f"### 🏁 Sunday Grand Prix · {g_['name']}")
                st.caption(f"{g_['laps']} laps, double season points, and a 🏆 for the cabinet if you win. "
                           f"Needs a ticket; doesn't count toward today's {RACE_DAY_CAP} races.")
                lo_, hi_ = ai_range(state, g_)
                st.markdown(f"<div class='dod-tiles'><div><small>Your car</small><b>{track_rating(state, g_):.0f}</b></div>"
                            f"<div><small>Rivals</small><b>{lo_}–{hi_}</b></div>"
                            f"<div><small>Laps</small><b>{g_['laps']}</b></div>"
                            f"<div><small>Entry + ⛽</small><b>{g_['fee']} + {run_cost(state, g_)} 🪙</b></div>"
                            f"<div><small>Purse</small><b>🥇{g_['prize'][0]} 🥈{g_['prize'][1]} 🥉{g_['prize'][2]}</b></div></div>",
                            unsafe_allow_html=True)
                cost_ = g_["fee"] + run_cost(state, g_)
                if st.button(f"🏁 Start the Grand Prix · {cost_} 🪙", type="primary", key="gp_go",
                             disabled=racing or not left_t or state["coins"] < cost_ or lvl < 1):
                    bank(state, -g_["fee"], f"🎟️ Entry: Sunday GP at {g_['name']}")
                    bank(state, -run_cost(state, g_), f"⛽ Running costs: {g_['name']}")
                    simulate_race(state, g_, "gp")
        inv_ = invitational(state)
        if inv_:
            with st.container(border=True, key="inv_card"):
                st.markdown(f"### 🎟️ You're invited · {inv_['name']}")
                st.caption(f"You're sitting on {state['coins']:,} coins, so the Invitational called. A field built "
                           "around your pace: no easy wins, no sandbagging. Once a week, no ticket needed.")
                st.markdown(f"<div class='dod-tiles'><div><small>Laps</small><b>{inv_['laps']}</b></div>"
                            f"<div><small>Entry + ⛽</small><b>{inv_['fee']} + {run_cost(state, inv_)} 🪙</b></div>"
                            f"<div><small>Purse</small><b>🥇{inv_['prize'][0]} 🥈{inv_['prize'][1]} 🥉{inv_['prize'][2]}</b></div>"
                            f"<div><small>Win</small><b>🏆 trophy</b></div></div>", unsafe_allow_html=True)
                cost_ = inv_["fee"] + run_cost(state, inv_)
                if st.button(f"🎟️ Accept · {cost_} 🪙", key="inv_go", disabled=racing, use_container_width=True):
                    bank(state, -inv_["fee"], f"🎟️ Entry: Invitational at {inv_['name']}")
                    bank(state, -run_cost(state, inv_), f"⛽ Running costs: {inv_['name']}")
                    simulate_race(state, inv_, "inv")
        names = [t["name"] for t in TRACKS]

        def track_label(n: str) -> str:
            t = next(t for t in TRACKS if t["name"] == n)
            locked = lvl < t["level"]
            return f"{'🔒 ' if locked else ''}{n} — {t['laps']} laps" + (f" (level {t['level']})" if locked else "")

        pick = st.selectbox("Track", names, index=best_track(state), format_func=track_label,
                            help="Starts on the highest track you can actually win.")
        track = TRACKS[names.index(pick)]
        lo, hi = ai_range(state, track)
        rating = track_rating(state, track)
        st.caption("🏁 " + RV.TRACK_CHARACTER.get(track["name"], ([], ""))[1].capitalize() + "."
                   + (f" Season {RV.SEASON} layout: **{RV.layout_name(track['name'])}**." if track["name"] == RV.TOP_TRACK else ""))
        m_ = sandbag(state, track)
        pz = [round(x * m_) for x in track["prize"]]
        rc = run_cost(state, track)
        edge_ = "#2ec4b6" if rating >= hi else "#f5c518" if rating >= lo else "#e10600"
        st.markdown(f"<div class='dod-tiles'><div><small>Your car</small><b style='color:{edge_}'>{rating:.0f}</b></div>"
                    f"<div><small>Rivals</small><b>{lo}–{hi}</b></div>"
                    f"<div><small>Laps</small><b>{track['laps']}</b></div>"
                    f"<div><small>Entry + ⛽ running</small><b>{track['fee']} + {rc} 🪙</b></div>"
                    f"<div><small>Prizes</small><b>🥇{pz[0]} 🥈{pz[1]} 🥉{pz[2]}</b></div></div>", unsafe_allow_html=True)
        ff = field_form(state, track["name"])
        if ff:
            st.caption(f"📈 This grid has learned you: rivals **+{ff * 3.5:.0f}%** from your recent results here. "
                       "Win more and they get faster; move up a tier to keep the money flowing.")
        if m_ < 1:
            st.caption(f"🪜 You outclass this track: fast rivals show up and prizes pay ×{m_:.2f}. "
                       "Move up a track for full prizes.")
        if car["condition"] < 40:
            st.warning("Car under 40% — real risk of a DNF.")
        if lvl < track["level"]:
            st.info(f"Unlocks at driver level {track['level']}. Earn XP by finishing tasks.")
        else:
            render_boost_shop(state, track)
            st.caption(why_t)
            cost_ = track["fee"] + rc + sum(boost_price(k, track) for k in state.get("boosts", []))
            if state["coins"] < track["fee"] + rc:
                st.info("Can't cover the entry fee and running costs.")
            elif racing:
                st.button("🏎️ Race in progress…", disabled=True)
            elif st.button(f"🚦 Lights out · {track['fee'] + rc} 🪙", type="primary", disabled=not left_t,
                           use_container_width=True):
                bank(state, -track["fee"], f"🎟️ Entry: {track['name']}")
                bank(state, -rc, f"⛽ Running costs: {track['name']}")
                simulate_race(state, track)

        rp = st.session_state.get("race_replay")
        if rp:
            st.markdown(f"#### 📺 {rp['title']}")
            (st.iframe if hasattr(st, "iframe") else __import__("streamlit.components.v1", fromlist=["html"]).html)(
                rp["html"], height=460)
            _race_result(rp)

        _hide = 1 if (st.session_state.get("race_replay") or {}).get("revealed") is False else 0
        if state["races"][_hide:]:
            with fold("race_history", "Race history", False) as _fo:
                if _open(_fo):  # collapsed = not built (faster page, smaller download)
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
            st.caption("Input: its cards become suggestions and events to prep for (the app only adds a card per "
                       "long-term goal). Output: your tasks land on it at the time they're set to happen. Journal: "
                       "your evening entry becomes that day's page, in your template's layout.")
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
                if s.get("journal_db"):
                    try:
                        jm_ = _journal_map(tok, s["journal_db"])
                        pr_ = s.get("journal_prompts") or []
                        rows.append((True, f"Journal: {jm_['name']}",
                                     f"writes each evening entry as that day's page · {len(pr_)} prompts from your "
                                     "template" if pr_ else "writes each evening entry as that day's page · no template "
                                     "prompts found (using the app's questions)"))
                    except Exception as e:
                        rows.append((False, "Journal: can't read it", str(e)[:90]))
                else:
                    rows.append((None, "Journal: not linked", "pick your Notion journal below → Use as journal"))
                status_rows(rows)
                if s.get("journal_db"):
                    j1, j2 = st.columns(2)
                    if j1.button("↻ Re-read journal template", use_container_width=True):
                        try:
                            s["journal_prompts"] = JN.read_prompts(Notion(tok), _journal_map(tok, s["journal_db"]))
                            save_state(state)
                            flash(f"📓 {len(s['journal_prompts'])} prompts from your journal template.")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
                    if j2.button("Unlink journal", use_container_width=True):
                        s["journal_db"] = ""
                        s.pop("journal_prompts", None)
                        save_state(state)
                        st.rerun()
                    if s.get("journal_prompts"):
                        st.caption("Tonight's questions: " + " · ".join(q for _, q, _ in J.questions(state)))
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
                        c1, c2, c3, c4 = st.columns(4)
                        if c4.button("Use as journal", use_container_width=True,
                                     help="Your Notion journal (calendar). Evening entries are written into it, laid "
                                          "out like your template."):
                            try:
                                jm_ = JN.detect(Notion(tok), pick)
                                s.update(journal_db=pick, journal_since=now().date().isoformat(),
                                         journal_prompts=JN.read_prompts(Notion(tok), jm_))
                                save_state(state)
                                st.session_state.pop("board_list", None)
                                flash(f"📓 Journal linked: **{jm_['name']}** · {len(s['journal_prompts'])} prompts from "
                                      "your template merged into tonight's questions.")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
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
        with fold("adv", "Claude model and Notion import", False) as _fo:
            if _open(_fo):  # collapsed = not built (faster page, smaller download)
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
                    _backup_async(state, "before restoring a file")
                    new_ = _merge(default_state(), json.loads(restore.getvalue()))
                    new_["rev"] = int(state.get("rev", 0)) + 1
                    save_state(new_)
                    flash("Save restored.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Couldn't read that file: {e}")
        if notion_cfg():
            with st.container(border=True, key="auto_backups"):
                st.markdown("#### 🗄️ Automatic backups")
                st.caption(f"A copy of your save is kept each day before anything is settled, and before any "
                           f"restore or reset. The newest {BK.KEEP} are kept in Notion under “{BK.ROOT_TITLE}”.")
                cfg_ = notion_cfg()
                c1, c2 = st.columns(2)
                if c1.button("📸 Back up now", use_container_width=True):
                    _safe(BK.snapshot, Notion(cfg_[0]), cfg_[1], json.dumps(state, default=str), "manual", now())
                    flash("📸 Backed up.")
                    st.rerun()
                if c2.button("↻ Show backups", use_container_width=True) or st.session_state.get("bk_list"):
                    st.session_state["bk_list"] = _safe(BK.listing, Notion(cfg_[0]), cfg_[1]) or []
                bl = st.session_state.get("bk_list")
                if bl:
                    pick = st.selectbox("Backup", [b["id"] for b in bl], key="bk_pick",
                                        format_func=lambda i: next(b["title"] for b in bl if b["id"] == i))
                    data_ = _safe(BK.load, Notion(cfg_[0]), pick)
                    if data_:
                        ds_ = sorted((data_.get("journal") or {}).keys())[-3:]
                        st.caption(f"Coins {data_.get('coins', '?')} · {len(data_.get('tasks', []))} tasks · "
                                   f"journal days {', '.join(ds_) or '—'}")
                        if st.checkbox("Replace my current save with this backup", key="bk_ok") and \
                                st.button("Restore backup", type="primary", key="bk_go"):
                            _backup_async(state, "before restoring a backup")
                            new_ = _merge(default_state(), data_)
                            new_["rev"] = int(state.get("rev", 0)) + 1
                            save_state(new_)
                            st.session_state.pop("bk_list", None)
                            flash("🗄️ Backup restored.")
                            st.rerun()
        with st.expander("Reset everything"):
            st.caption("Wipes coins, cars, tasks and history. A backup is taken first.")
            if st.checkbox("I want to wipe everything") and st.button("Reset game"):
                _backup_async(state, "before reset")
                fresh_ = default_state()
                fresh_["rev"] = int(state.get("rev", 0)) + 1
                save_state(fresh_)
                flash("Fresh start.", "warning")
                st.rerun()


# 🎯 Goals mirrored into Notion (a page per goal: stages as headings, blocks as sub-headings), off the click path
def goals_to_notion(state: dict) -> None:
    cfg = notion_cfg()
    if not cfg or state.get("settings", {}).get("goals_notion") is False:
        return
    import sys as _sys
    box = _sys.__dict__.setdefault("_dod_goals_sync", {"busy": False, "known": None, "err": None})
    if box["known"] is not None and box["known"] != state.get("notion_goals"):
        state["notion_goals"] = box["known"]  # what the last background run built: keep it, so pages are reused
        save_state(state)
    if box["busy"]:
        return
    goals, tasks, today = [dict(g) for g in state.get("goals", [])], json.loads(json.dumps(state["tasks"])), now().date()
    known = dict(state.get("notion_goals") or {})
    want = NG.wanted(goals, tasks, TZ, today)
    have = {k: (v or {}).get("sig") for k, v in known.items() if k != "_root"}
    if want == have and known.get("_root"):
        return
    box["busy"] = True
    token, parent = cfg

    def run():
        try:
            box["known"] = NG.sync(Notion(token), parent, goals, tasks, known, TZ, today)
            box["err"] = None
        except Exception as e:  # noqa: BLE001 — a mirror never breaks the app
            box["err"] = str(e)[:200]
        finally:
            box["busy"] = False
    threading.Thread(target=run, daemon=True).start()


# ── after the page is drawn ──
try:
    render_timer_float(state)
except Exception:  # noqa: BLE001 — a clock never breaks the page
    pass
try:
    goals_to_notion(state)
except Exception:  # noqa: BLE001
    pass
if _boot is not None and notion_cfg():  # how long this login took, by stage (read by the health check)
    _pl = state.setdefault("perf_log", [])
    _pl.append({"at": now().isoformat()[:16], "cold": bool(st.session_state.get("_cold")),
                "to_data": round(_T_LOADED - _T_SESSION, 1), "to_page": round(time.time() - _T_SESSION, 1)})
    del _pl[:-10]
if _SYNC_LATER:
    st.session_state.pop("_fresh_load", None)
    try:
        _sm, _changed = sync_from_notion(state)
    except Exception as e:  # noqa: BLE001
        _sm, _changed = [("warning", f"Couldn't sync tasks with Notion: {e}")], False
    try:
        _jr = import_notion_journal(state)
        if _jr:
            _sm, _changed = list(_sm) + [("success", m_) for m_ in _jr], True
    except Exception as e:  # noqa: BLE001 — the journal import never blocks the app
        _sm = list(_sm) + [("warning", f"Couldn't read your Notion journal: {e}")]
    if _changed:
        save_state(state)
    if _sm or _changed:
        st.session_state["_sync_msgs"] = _sm
        st.rerun()
render_jump()
if _boot is not None:  # everything is on the page and synced: lights out
    _boot.empty()
    st.session_state["_booted"] = True
