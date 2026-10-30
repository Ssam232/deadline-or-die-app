"""
🛡️ Damage limiter: bad days sting, but they can't spiral.

Built on the same levers that keep people hooked, pointed at you, on purpose:
  • Hard cap (stops the "what-the-hell" effect): involuntary penalties in any 24 h can't exceed the cap.
  • Held, not gone (loss aversion as a carrot): anything over the cap is HELD. Finish one proof-backed task within
    36 h and it's cancelled; ignore it and it lands later (still capped). A loss you can still prevent pulls you back;
    a loss that's already gone pushes you away.
  • Comeback bounty (fresh-start effect): the day after a bad day, your first finish wins back half of it.
  • Streak shield (sunk-cost protection): every 7-day streak earns a shield (max 2) that saves the streak from one
    zero day, so one miss doesn't wipe weeks of momentum.
  • Recovery fuel: while you're in debt, finishes pay +25%, so the way out is visible and short.
Voluntary spending (upgrades, races, the Lounge, extensions, pauses) is never capped or held.
"""
from __future__ import annotations

from datetime import datetime, timedelta

PENALTY_MARKS = ("💀 ", "🚦 Missed qualifying", "🔁 Missed daily")
BASE_CAP = 60
HOLD_HOURS = 36
BAD_DAY = 40             # charged this much in a day → tomorrow is a comeback day
COMEBACK_SHARE = 0.5
COMEBACK_MAX = 40
RECOVERY_BONUS = 0.25
SHIELD_EVERY = 7
SHIELD_MAX = 2


def is_penalty(reason: str) -> bool:
    return reason.startswith(PENALTY_MARKS)


def cap(save: dict) -> int:
    import daily
    return min(100, BASE_CAP + 10 * (daily.level(save) - 1))


def _dt(s: str, tz) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=tz)


def charged_since(save: dict, since: datetime) -> int:
    return -sum(e["delta"] for e in save.get("ledger", [])
                if e["delta"] < 0 and is_penalty(e["reason"]) and _dt(e["ts"], since.tzinfo) >= since)


def absorb(save: dict, amount: int, reason: str, now: datetime) -> int:
    """How much of a penalty to actually charge now; the rest is held."""
    room = max(0, cap(save) - charged_since(save, now - timedelta(hours=24)))
    charge = min(amount, room)
    if amount > charge:
        save.setdefault("held", []).append({"amount": amount - charge, "reason": reason, "at": now.isoformat(),
                                            "until": (now + timedelta(hours=HOLD_HOURS)).isoformat()})
    return charge


def held_total(save: dict) -> int:
    return sum(h["amount"] for h in save.get("held", []))


def settle(save: dict, now: datetime, bank) -> list[str]:
    """Held penalties nobody came back for land now (through the cap again; whatever doesn't fit is forgiven)."""
    msgs, keep = [], []
    for h in save.get("held", []):
        if _dt(h["until"], now.tzinfo) > now:
            keep.append(h)
            continue
        room = max(0, cap(save) - charged_since(save, now - timedelta(hours=24)))
        hit = min(h["amount"], room)
        if hit:
            save.setdefault("ledger", []).insert(0, {"ts": now.isoformat(), "delta": -hit,
                                                     "reason": f"💀 Held penalty landed ({h['reason'][:40]})"})
            save["coins"] = save.get("coins", 0) - hit
        msgs.append(f"🛡️ A held penalty landed: −{hit}" + (f" (the other {h['amount'] - hit} was forgiven)"
                                                           if h["amount"] > hit else "") + "." if hit else
                    f"🛡️ A held penalty of {h['amount']} was forgiven: today's cap was already reached.")
    save["held"] = keep
    return msgs


def bad_day_loss(save: dict, day) -> int:
    lo = datetime.combine(day, datetime.min.time())
    tot = 0
    for e in save.get("ledger", []):
        if e["delta"] < 0 and is_penalty(e["reason"]):
            ts = datetime.fromisoformat(e["ts"])
            if ts.replace(tzinfo=None) >= lo and ts.date() == day:
                tot -= e["delta"]
    return tot


def comeback_offer(save: dict, now: datetime) -> int:
    """Coins your first finish today wins back (0 = none on offer)."""
    y = now.date() - timedelta(days=1)
    if save.get("comeback_claimed") == now.date().isoformat():
        return 0
    loss = bad_day_loss(save, y)
    return min(COMEBACK_MAX, round(loss * COMEBACK_SHARE)) if loss >= BAD_DAY else 0


def on_finish(save: dict, now: datetime, reward: int, bank) -> list[str]:
    """After a proof-backed finish: cancel held penalties, pay the comeback bounty, add recovery fuel."""
    msgs = []
    if save.get("held"):
        msgs.append(f"🛡️ Comeback: {held_total(save)} in held penalties cancelled.")
        save["held"] = []
    offer = comeback_offer(save, now)
    if offer:
        save["comeback_claimed"] = now.date().isoformat()
        bank(save, offer, "🔥 Comeback bounty")
        msgs.append(f"🔥 Comeback bounty: +{offer} of yesterday back.")
    if save.get("coins", 0) - reward < 0 and reward > 0:
        bonus = max(1, round(reward * RECOVERY_BONUS))
        bank(save, bonus, "🔧 Recovery fuel")
        msgs.append(f"🔧 Recovery fuel +{bonus} (finishes pay +25% while you're in debt).")
    return msgs


def earn_shield(save: dict) -> bool:
    """Call when the day streak grows; every 7 days earns a shield (max 2)."""
    if save.get("day_streak", 0) and save["day_streak"] % SHIELD_EVERY == 0 and save.get("shields", 0) < SHIELD_MAX:
        save["shields"] = save.get("shields", 0) + 1
        return True
    return False


def use_shield(save: dict) -> bool:
    if save.get("shields", 0) > 0 and save.get("day_streak", 0) > 0:
        save["shields"] -= 1
        return True
    return False
