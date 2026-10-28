"""
🎰 Paddock Lounge — blackjack and snake eyes, as a reward for working, never a way around it.

  • Opens only after you've finished something today, and never under a black flag.
  • Bets capped; the house always has an edge, so it's a coin sink, not a coin farm.
  • Closes for the day once you're +200 up (house limit) or −300 down (stop-loss).
"""
from __future__ import annotations

import random
from datetime import date

MAX_BET = 50
MAX_HANDS = 15
WIN_LIMIT = 200
LOSS_LIMIT = 300
SUITS = "♠♥♦♣"
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
DICE = "⚀⚁⚂⚃⚄⚅"


def day_record(save: dict, today: str) -> dict:
    rec = save.setdefault("lounge", {})
    if rec.get("date") != today:
        rec.clear()
        rec.update({"date": today, "hands": 0, "net": 0})
    return rec


ENTRY_MINUTES = 60  # earn your way in: a finished task worth 1h+, or a single focus block of 1h+


def entry_ticket(save: dict, d: date) -> str | None:
    """Why the door is open today (None = not earned yet). Weekends are free."""
    if d.weekday() >= 5:
        return "🎉 Weekend — the lounge is open."
    iso = d.isoformat()
    for t in save.get("tasks", []):
        if t.get("status") in ("done", "redeemed") and (t.get("completed_at") or "")[:10] == iso \
                and (t.get("minutes") or 0) >= ENTRY_MINUTES:
            return f"🎟️ Earned: you finished *{t['title']}* (1h+ task)."
    for x in save.get("focus_log", []):
        if x.get("date") == iso and x.get("min", 0) >= ENTRY_MINUTES:
            return f"🎟️ Earned: a {int(x['min'])}-min focus block."
    return None


def closed_reason(save: dict, d: date, black_flag: list[str]) -> str | None:
    if black_flag:
        return "Black flag — the lounge doesn't serve drivers in the penalty box."
    if not entry_ticket(save, d):
        return ("The lounge opens after you finish a task worth 1h+ or run a single 1h focus block today. "
                "Weekends it's open all day.")
    rec = day_record(save, d.isoformat())
    if rec["hands"] >= MAX_HANDS:
        return f"That's {MAX_HANDS} hands today. Lounge is closed till tomorrow."
    if rec["net"] >= WIN_LIMIT:
        return f"You're +{rec['net']} today — house limit reached. Walk away a winner."
    if rec["net"] <= -LOSS_LIMIT:
        return f"You're {rec['net']} today — stop-loss hit. Lounge closed till tomorrow."
    return None


# ── blackjack ──
def new_deck(rng: random.Random | None = None) -> list[str]:
    d = [r + s for r in RANKS for s in SUITS]
    (rng or random).shuffle(d)
    return d


def hand_value(cards: list[str]) -> int:
    total, aces = 0, 0
    for c in cards:
        r = c[:-1]
        total += 11 if r == "A" else 10 if r in ("10", "J", "Q", "K") else int(r)
        aces += r == "A"
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards: list[str]) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


def deal(bet: int, rng: random.Random | None = None) -> dict:
    deck = new_deck(rng)
    g = {"deck": deck, "player": [deck.pop(), deck.pop()], "dealer": [deck.pop(), deck.pop()], "bet": bet,
         "over": False, "result": None, "payout": 0}
    if is_blackjack(g["player"]) or is_blackjack(g["dealer"]):
        settle_bj(g)
    return g


def hit(g: dict) -> dict:
    g["player"].append(g["deck"].pop())
    if hand_value(g["player"]) > 21:
        g.update(over=True, result="Bust", payout=0)
    return g


def stand(g: dict) -> dict:
    while hand_value(g["dealer"]) < 17:
        g["dealer"].append(g["deck"].pop())
    return settle_bj(g)


def settle_bj(g: dict) -> dict:
    p, d, bet = hand_value(g["player"]), hand_value(g["dealer"]), g["bet"]
    if is_blackjack(g["player"]) and not is_blackjack(g["dealer"]):
        res, pay = "Blackjack! 3:2", int(bet * 2.5)
    elif is_blackjack(g["dealer"]) and not is_blackjack(g["player"]):
        res, pay = "Dealer blackjack", 0
    elif p > 21:
        res, pay = "Bust", 0
    elif d > 21 or p > d:
        res, pay = "You win", bet * 2
    elif p == d:
        res, pay = "Push", bet
    else:
        res, pay = "Dealer wins", 0
    g.update(over=True, result=res, payout=pay)
    return g


# ── snake eyes ── (a 7 loses every over/under bet → ~17% house edge)
SNAKE_BETS = {
    "under": ("Under 7", 2),
    "over": ("Over 7", 2),
    "seven": ("Exactly 7", 5),
    "snake": ("Snake eyes (1-1)", 30),
}


def roll(rng: random.Random | None = None) -> tuple[int, int]:
    r = rng or random
    return r.randint(1, 6), r.randint(1, 6)


def snake_payout(choice: str, dice: tuple[int, int], bet: int) -> int:
    s = sum(dice)
    won = {"under": s < 7, "over": s > 7, "seven": s == 7, "snake": dice == (1, 1)}[choice]
    return bet * SNAKE_BETS[choice][1] if won else 0
