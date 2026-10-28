"""
🔒 Locks — consequences that actually bite.

You're LOCKED (games blocked on PC + phone) while:
  • an enforced 🔒 consequence is in the penalty box (from a missed task), for up to 24h
    — finishing the missed task (redemption) lifts it immediately, or
  • a focus session is running (optional, on by default).
An emergency unlock buys 1 hour of freedom for coins, so you're never truly trapped.

The current state is broadcast to `<NTFY_TOPIC>-lock` as a plain "LOCKED: …" / "OPEN" message.
The PC enforcer and the iPhone Shortcut both just read that.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import requests

ENFORCED_MARK = "🔒"
LOCK_HOURS = 24
UNLOCK_COST = 100
UNLOCK_HOURS = 1
SERVER = "https://ntfy.sh"


def status(save: dict, now: datetime) -> dict:
    over = save.get("override_until")
    if over and datetime.fromisoformat(over) > now:
        return {"locked": False, "reasons": [], "override": True}
    reasons = []
    for p in save.get("penalty_box", []):
        if p.get("served") or not p.get("enforced"):
            continue
        if now - datetime.fromisoformat(p["created"]) < timedelta(hours=LOCK_HOURS):
            reasons.append(f"{p['consequence']} (missed: {p['task']})")
    if save.get("timer") and save.get("settings", {}).get("focus_lock", True):
        reasons.append("Focus session running")
    return {"locked": bool(reasons), "reasons": reasons, "override": False}


def message(st: dict) -> str:
    return ("LOCKED: " + " | ".join(st["reasons"]))[:400] if st["locked"] else "OPEN"


def topic(base: str | None) -> str | None:
    return f"{base}-lock" if base else None


def publish(base_topic: str | None, st: dict) -> bool:
    t = topic(base_topic)
    if not t:
        return False
    try:
        return requests.post(f"{SERVER}/{t}", data=message(st).encode(), timeout=10).status_code < 300
    except requests.RequestException:
        return False
