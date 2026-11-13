"""
🧑‍🔧 Your pit crew, and the words on the wall. No Streamlit imports.

Hire them once (Garage → Crew) and they stay: each has a permanent perk, a face, and something to say about how
your day is going. They live on Today so you see them every time you open the app.

Quotes are public-domain: classical authors in old translations (Seneca, tr. Gummere 1917; Marcus Aurelius and
Epictetus, tr. George Long; Lao Tzu, tr. Legge) and 19th / early-20th-century speakers and writers.
"""
from __future__ import annotations

import hashlib
from datetime import date

CREW = {
    "chief": {"name": "Mags", "role": "Crew chief", "price": 1200, "perk": "+5% on every race prize",
              "skin": "#c68a5a", "hair": "#2b1a12", "style": "bun", "shirt": "#c8102e", "gear": "headset"},
    "tires": {"name": "Rook", "role": "Tyre specialist", "price": 800, "perk": "−30% running costs",
              "skin": "#8d5a3b", "hair": "#111111", "style": "buzz", "shirt": "#2a6cff", "gear": "cap"},
    "engineer": {"name": "Dot", "role": "Race engineer", "price": 900, "perk": "−30% car wear per race",
                 "skin": "#f0c9a5", "hair": "#a0522d", "style": "bob", "shirt": "#2ec4b6", "gear": "glasses"},
    "strategist": {"name": "Ash", "role": "Strategist", "price": 1000, "perk": "+3 car rating every race",
                   "skin": "#e0ac7e", "hair": "#4a4a4a", "style": "swept", "shirt": "#f5c518", "gear": "tablet"},
}


def avatar_svg(key: str, size: int = 64, mood: str = "ok") -> str:
    """An original little portrait: face, hair, team shirt and one signature piece of kit."""
    c = CREW[key]
    hair = {
        "bun": f"<circle cx='32' cy='12' r='7' fill='{c['hair']}'/><path d='M14 30 Q14 14 32 14 Q50 14 50 30 L50 24 Q46 18 32 18 Q18 18 14 24 Z' fill='{c['hair']}'/>",
        "buzz": f"<path d='M15 28 Q15 13 32 13 Q49 13 49 28 Q46 19 32 19 Q18 19 15 28 Z' fill='{c['hair']}'/>",
        "bob": f"<path d='M13 36 Q11 12 32 12 Q53 12 51 36 L47 36 Q48 20 32 19 Q16 20 17 36 Z' fill='{c['hair']}'/>",
        "swept": f"<path d='M14 28 Q16 10 36 12 Q52 14 50 30 Q44 16 30 20 Q20 22 14 28 Z' fill='{c['hair']}'/>",
    }[c["style"]]
    mouth = {"ok": "M26 41 Q32 46 38 41", "worried": "M26 44 Q32 40 38 44", "fired": "M25 40 Q32 48 39 40"}[mood]
    gear = {
        "headset": "<path d='M14 30 Q14 10 32 10 Q50 10 50 30' stroke='#1b1f27' stroke-width='3' fill='none'/>"
                   "<rect x='10' y='27' width='7' height='11' rx='3' fill='#1b1f27'/><rect x='47' y='27' width='7' height='11' rx='3' fill='#1b1f27'/>"
                   "<path d='M13 37 Q16 46 26 45' stroke='#1b1f27' stroke-width='2' fill='none'/>",
        "cap": f"<path d='M14 24 Q16 10 32 10 Q48 10 50 24 Z' fill='{c['shirt']}'/><rect x='30' y='21' width='26' height='5' rx='2.5' fill='{c['shirt']}'/>",
        "glasses": "<circle cx='26' cy='32' r='5' stroke='#1b1f27' stroke-width='2' fill='none'/><circle cx='38' cy='32' r='5' stroke='#1b1f27' stroke-width='2' fill='none'/>"
                   "<path d='M31 32 L33 32' stroke='#1b1f27' stroke-width='2'/>",
        "tablet": "<rect x='42' y='46' width='14' height='16' rx='2' fill='#1b1f27' stroke='#9aa0aa' stroke-width='1'/>"
                  "<rect x='44' y='48' width='10' height='9' fill='#6a8dff'/>",
    }[c["gear"]]
    return (f"<svg viewBox='0 0 64 64' width='{size}' height='{size}' xmlns='http://www.w3.org/2000/svg'>"
            f"<circle cx='32' cy='32' r='31' fill='#1b2030' stroke='{c['shirt']}' stroke-width='2'/>"
            f"<path d='M10 64 Q12 48 32 48 Q52 48 54 64 Z' fill='{c['shirt']}'/>"
            f"<rect x='28' y='42' width='8' height='8' fill='{c['skin']}'/>"
            f"<ellipse cx='32' cy='31' rx='15' ry='17' fill='{c['skin']}'/>"
            f"{hair}<circle cx='26' cy='32' r='1.8' fill='#14171d'/><circle cx='38' cy='32' r='1.8' fill='#14171d'/>"
            f"<path d='{mouth}' stroke='#14171d' stroke-width='2' fill='none' stroke-linecap='round'/>{gear}</svg>")


# What they say. ctx keys: name, qualified, focus, done, streak, flaked, slices_short, won, coins, hour, days
LINES = {
    "chief": [
        (lambda x: x["flaked"], "{name}. You didn't show and you didn't call. That's not who we are. Next one, you're there."),
        (lambda x: not x["qualified"] and x["hour"] < 12, "Grid forms at noon. Lock it in and let's go to work."),
        (lambda x: x["won"], "That's a W. Enjoy it for an hour, then back to the shop."),
        (lambda x: x["streak"] >= 7, "{streak} days straight. This is what a program looks like."),
        (lambda x: x["focus"] >= 120, "Two hours on the clock already. That's a racer's day."),
        (lambda x: x["focus"] == 0 and x["hour"] >= 15, "Nothing on the clock and it's after three. One stint. Now."),
        (lambda x: True, "Talent's common. Showing up every day isn't. Be uncommon."),
    ],
    "tires": [
        (lambda x: x["slices_short"], "Slice is still short. Rubber doesn't warm itself up, go put the minutes in."),
        (lambda x: x["focus"] >= 60, "Tyres are in the window. Keep the pace up."),
        (lambda x: x["hour"] >= 22 and not x["done"], "Late and nothing done. Smallest task, then sleep."),
        (lambda x: True, "Grip comes from heat, heat comes from laps. Do the laps."),
    ],
    "engineer": [
        (lambda x: x["done"] >= 3, "{done} finishes today. The data looks clean."),
        (lambda x: x["focus"] > 0 and x["focus"] < 30, "{focus} min so far. One more stint and the numbers start meaning something."),
        (lambda x: x["coins"] > 1500, "We're sitting on {coins} coins. Money in the bank doesn't make the car faster."),
        (lambda x: True, "Small gains, every session. That's the whole secret."),
    ],
    "strategist": [
        (lambda x: not x["qualified"], "No plan, no race. Pick the one thing, then the next."),
        (lambda x: x["streak"] and x["streak"] % 5 == 0, "{streak}-day streak. Don't protect it. Extend it."),
        (lambda x: x["hour"] < 10, "Early start is a free lap on everyone else."),
        (lambda x: True, "Win the next ten minutes. Then do it again."),
    ],
}


def line(key: str, ctx: dict) -> str:
    for cond, text in LINES[key]:
        try:
            if cond(ctx):
                return text.format(**ctx)
        except (KeyError, TypeError):
            continue
    return ""


def mood(ctx: dict) -> str:
    return "worried" if ctx.get("flaked") or (ctx.get("focus", 0) == 0 and ctx.get("hour", 0) >= 15) else \
        "fired" if ctx.get("won") or ctx.get("focus", 0) >= 120 else "ok"


QUOTES = [
    ("While we are postponing, life speeds by.", "Seneca"),
    ("Hold every hour in your grasp.", "Seneca"),
    ("If there is no struggle, there is no progress.", "Frederick Douglass"),
    ("No great thing is produced suddenly, since not even the bunch of grapes or the fig is.", "Epictetus"),
    ("First say to yourself what you would be; and then do what you have to do.", "Epictetus"),
    ("That which is a hindrance is made a furtherance to an act; and that which is an obstacle on the road helps "
     "us on this road.", "Marcus Aurelius"),
    ("No longer talk at all about the kind of man that a good man ought to be, but be such.", "Marcus Aurelius"),
    ("The journey of a thousand li commenced with a single step.", "Lao Tzu"),
    ("Lost time is never found again.", "Benjamin Franklin"),
    ("You may delay, but time will not.", "Benjamin Franklin"),
    ("Genius is one per cent inspiration and ninety-nine per cent perspiration.", "Thomas Edison"),
    ("Success is to be measured not so much by the position that one has reached in life as by the obstacles "
     "which he has overcome while trying to succeed.", "Booker T. Washington"),
    ("The credit belongs to the man who is actually in the arena.", "Theodore Roosevelt"),
    ("Dripping water hollows a stone.", "Ovid"),
    ("Fall seven times, stand up eight.", "Japanese proverb"),
    ("The beginning is half of the whole.", "Greek proverb, via Aristotle"),
]


def quote_of_day(d: date, salt: str = "") -> tuple[str, str]:
    i = int(hashlib.sha1(f"{d.isoformat()}{salt}".encode()).hexdigest(), 16) % len(QUOTES)
    return QUOTES[i]
