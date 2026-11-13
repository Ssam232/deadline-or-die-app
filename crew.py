"""
🧑‍🔧 Your pit crew, and the words on the wall. No Streamlit imports.

Hire them once (Garage → Crew) and they stay. Each has a permanent perk, a face, a voice of their own, and opinions
about how your day is going. They notice things (a race, a flake, a streak, a long stint), they talk to each other,
and the longer they're with you the more they tell you about themselves (bond levels unlock their stories).

All characters are original. Quotes are public-domain: classical authors in old translations (Seneca, tr. Gummere
1917; Marcus Aurelius and Epictetus, tr. George Long; Lao Tzu, tr. Legge) and 19th / early-20th-century writers.
"""
from __future__ import annotations

import hashlib
from datetime import date

CREW = {
    "chief": {
        "name": "Mags", "role": "Crew chief", "price": 1200, "perk": "+5% on every race prize",
        "skin": "#c68a5a", "hair": "#2b1a12", "style": "bun", "shirt": "#c8102e", "gear": "headset",
        "bio": "Ran pit lanes for twenty years before she ran one for you. Doesn't raise her voice. Doesn't have to.",
        "quirk": "Keeps a stopwatch on her at all times, even at dinner.",
        "likes": "Early starts, clean pit stops, people who do what they said.",
        "catch": "We do what we said.",
    },
    "tires": {
        "name": "Rook", "role": "Tyre specialist", "price": 800, "perk": "−30% running costs",
        "skin": "#8d5a3b", "hair": "#111111", "style": "buzz", "shirt": "#2a6cff", "gear": "cap",
        "bio": "Grew up in his uncle's tyre shop. Talks about rubber the way other people talk about music.",
        "quirk": "Can tell you the temperature of anything by touching it. Is usually right.",
        "likes": "Warm tyres, cold drinks, long stints without a break.",
        "catch": "Heat in the tyres, heat in the work.",
    },
    "engineer": {
        "name": "Dot", "role": "Race engineer", "price": 900, "perk": "−30% car wear per race",
        "skin": "#f0c9a5", "hair": "#a0522d", "style": "bob", "shirt": "#2ec4b6", "gear": "glasses",
        "bio": "Left a PhD to come race. Still writes everything in a notebook and graphs it before bed.",
        "quirk": "Names every spreadsheet after a planet. Your season is 'Neptune'.",
        "likes": "Data, small gains, people who log their time honestly.",
        "catch": "If it isn't logged, it didn't happen.",
    },
    "strategist": {
        "name": "Ash", "role": "Strategist", "price": 1000, "perk": "+3 car rating every race",
        "skin": "#e0ac7e", "hair": "#4a4a4a", "style": "swept", "shirt": "#f5c518", "gear": "tablet",
        "bio": "Former chess coach. Thinks three moves ahead and quietly enjoys it when you prove him wrong.",
        "quirk": "Answers questions with questions. Drives everyone mad. Is usually right.",
        "likes": "A plan written down, a plan followed, the undercut.",
        "catch": "What's the next move?",
    },
}

BOND_LEVELS = [(0, "New"), (3, "Getting to know you"), (7, "Trusts you"), (14, "In your corner"),
               (30, "Ride or die"), (60, "Family")]

# Unlocked one per bond level: the more days together, the more they tell you.
STORIES = {
    "chief": [
        "First race I ever ran, our driver flaked on the morning warm-up. We lost by a tenth. I've never forgiven a no-show since.",
        "People think pressure is the enemy. It isn't. Pressure is just the job showing you it matters.",
        "I've worked with faster drivers than you. Not many who came back the day after a bad one. That counts for more.",
        "My dad fixed buses. Same route, every day, forty years. He never missed a shift. That's who I think of when I see your streak.",
        "You know why I stayed? You keep showing up. That's all a crew ever asks.",
    ],
    "tires": [
        "My uncle said a tyre tells you everything: how you drove, how you braked, whether you were scared. People are the same.",
        "I failed my first certification. Twice. The third time I studied in the shop every night after close. Passed top of the class.",
        "Cold tyres feel terrible for the first lap. Then they come in. Starting a hard task is the exact same feeling.",
        "I don't really like racing, if I'm honest. I like being good at something. Racing just happens to be the thing.",
        "You're the reason I don't miss the shop anymore.",
    ],
    "engineer": [
        "I quit my PhD in year three. Not because it was hard. Because I stopped showing up, and then it was too late to start again. Don't do that.",
        "My notebook has every session you've logged. Some of them are short. I still write them down. Short counts.",
        "I graph your focus time every Sunday. You don't need to see the line go up every week. You need to see it not stop.",
        "I named your season after Neptune because it takes forever to go around the sun. And it still does it.",
        "When I left the lab I thought I'd failed at research. You're doing research. I'm just glad I get to watch.",
    ],
    "strategist": [
        "In chess, the player who plans loses to the player who plans and then sits down. Most people never sit down.",
        "I coached a kid who was brilliant and lazy. And another who was average and stubborn. Guess which one made master.",
        "The best strategy I know: decide the night before, so the morning version of you doesn't get a vote.",
        "I'm not here because you're fast. I'm here because you're interesting to bet on.",
        "Next move? Same as yesterday. Show up. It's the move nobody sees coming.",
    ],
}

# Lines: (condition, variants). The first matching condition wins; the variant rotates through the day.
# ctx: name, qualified, focus, done, streak, flaked, flaked_what, slices_short, won, raced, race_pos, race_track,
#      coins, hour, wd, attended, journaled, zero_yday, bond
LINES = {
    "chief": [
        (lambda x: x["flaked"], [
            "You missed {flaked_what}. No call, no message. That's not who we are.",
            "{flaked_what}. We had you down. You didn't come. Next time, you're there or you tell us.",
        ]),
        (lambda x: x["attended"], [
            "Saw you made {attended}. That's the job. Well done.",
            "{attended}: you said you'd be there and you were. That's everything.",
        ]),
        (lambda x: not x["qualified"] and x["hour"] < 12, [
            "Grid forms at noon. Lock it in and let's go to work.",
            "No mission yet. Write it down. Then we race.",
            "Morning, {name}. What are we doing today? Put it on the board.",
        ]),
        (lambda x: x["won"], ["That's a W. Enjoy it for an hour, then back to the shop.",
                              "Win at {race_track}. I'll allow one smile."]),
        (lambda x: x["streak"] >= 7, ["{streak} days straight. This is what a program looks like.",
                                      "{streak} days. Don't get comfortable. Get consistent."]),
        (lambda x: x["focus"] >= 120, ["Two hours on the clock already. That's a racer's day.",
                                       "Big day, {name}. Don't let it make tomorrow optional."]),
        (lambda x: x["focus"] == 0 and x["hour"] >= 15, ["Nothing on the clock and it's after three. One stint. Now.",
                                                         "Afternoon and the timer's still cold. Twenty-five minutes. Go."]),
        (lambda x: x["hour"] >= 23 or x["hour"] < 4, ["It's late. Finish the one thing, journal, sleep. In that order.",
                                                      "Night shift again? Make it count, then go to bed."]),
        (lambda x: True, ["Talent's common. Showing up every day isn't.", "We do what we said.",
                          "Steady hands, {name}. One thing at a time."]),
    ],
    "tires": [
        (lambda x: x["slices_short"], ["Slice is still short. Rubber doesn't warm itself up.",
                                       "That slice won't finish itself. Go put the minutes in."]),
        (lambda x: x["raced"] and not x["won"], ["P{race_pos} at {race_track}. Tyres went off, or you did? Either way, we go again.",
                                                 "Didn't win. Rubber's still on the car. That's what matters."]),
        (lambda x: x["focus"] >= 60, ["Tyres are in the window. Keep the pace up.",
                                      "{focus} minutes in. Now we're cooking.", "Heat in the tyres, heat in the work."]),
        (lambda x: 0 < x["focus"] < 25, ["First lap's always ugly. Second one's better. Go again.",
                                         "Tyres aren't warm yet. Another stint and they'll come in."]),
        (lambda x: x["hour"] >= 22 and not x["done"], ["Late and nothing done. Smallest task, then sleep.",
                                                        "Cold night, cold tyres. One small lap before bed."]),
        (lambda x: True, ["Grip comes from heat, heat comes from laps. Do the laps.",
                          "You warm up by starting. Not before.", "Feels slow at first. Always does."]),
    ],
    "engineer": [
        (lambda x: x["zero_yday"], ["Yesterday's line is flat. Today it doesn't have to be. Even ten minutes shows up on the graph.",
                                    "Zero yesterday. That's one data point, not a trend. Don't make it a trend."]),
        (lambda x: x["done"] >= 3, ["{done} finishes today. The data looks clean.",
                                    "{done} done. I'm writing this one in pen."]),
        (lambda x: 0 < x["focus"] < 30, ["{focus} min so far. One more stint and the numbers start meaning something.",
                                         "{focus} minutes logged. Short counts. Logged counts more."]),
        (lambda x: x["journaled"], ["You journaled. Good. Future you will want that data.",
                                    "Journal's in. That's the most underrated habit you've got."]),
        (lambda x: x["coins_n"] > 1500, ["We're sitting on {coins} coins. Money in the bank doesn't make the car faster.",
                                         "{coins} coins idle. That's a performance problem, technically."]),
        (lambda x: True, ["If it isn't logged, it didn't happen.", "Small gains, every session. That's the whole secret.",
                          "I don't need a big day. I need a day."]),
    ],
    "strategist": [
        (lambda x: not x["qualified"], ["No plan, no race. What's the one thing?",
                                        "What would the version of you who already finished today have started with?",
                                        "What's the next move?"]),
        (lambda x: x["streak"] and x["streak"] % 5 == 0, ["{streak}-day streak. Don't protect it. Extend it.",
                                                          "{streak}. A nice round number to break? Or to beat?"]),
        (lambda x: x["hour"] < 10, ["Early start is a free lap on everyone else.",
                                    "You're up before your excuses are. Use it."]),
        (lambda x: x["hour"] >= 20 and not x["journaled"], ["Want to win tomorrow? Decide it tonight. Journal, then sleep.",
                                                            "Tomorrow's first move. Have you picked it?"]),
        (lambda x: x["wd"] == 6, ["Sunday. Grand Prix day. Did you earn your ticket?",
                                  "Sunday: plan the week before it plans you."]),
        (lambda x: True, ["Win the next ten minutes. Then do it again.", "What's the next move?",
                          "Boring and consistent beats brilliant and absent. Every time."]),
    ],
}

# Two of them talking (shown when both are hired). (a, b, condition, a says, b says)
BANTER = [
    ("chief", "tires", lambda x: x["focus"] >= 60, "Rook, stop telling them about tyre temperatures.",
     "They're working, Mags. I'm allowed to be proud."),
    ("engineer", "strategist", lambda x: not x["qualified"], "No mission logged yet. I can't graph nothing, Ash.",
     "Then let's give them something to graph. What's the move, {name}?"),
    ("tires", "engineer", lambda x: x["won"], "Did you see the tyre wear on that win? Perfect.",
     "I have it graphed already. It's beautiful. Don't touch my notebook."),
    ("strategist", "chief", lambda x: x["streak"] >= 5, "{streak} days. I had money on four.",
     "You always bet against them, Ash. And you always lose."),
    ("chief", "engineer", lambda x: x["flaked"], "We don't skip things we said we'd be at.",
     "Logged it. Not to punish anyone. Just so we remember."),
    ("tires", "strategist", lambda x: x["hour"] >= 23 or x["hour"] < 4, "Why is everyone still up?",
     "Strategy. Or bad planning. Hard to tell from here."),
    ("engineer", "chief", lambda x: True, "Mags, what's the one rule?",
     "Show up. The rest is details, Dot."),
]


def bond(days: int) -> tuple[int, str, int | None]:
    """(level index, name, days to the next level or None)."""
    lvl = max(i for i, (d, _) in enumerate(BOND_LEVELS) if days >= d)
    nxt = BOND_LEVELS[lvl + 1][0] - days if lvl + 1 < len(BOND_LEVELS) else None
    return lvl, BOND_LEVELS[lvl][1], nxt


def stories(key: str, days: int) -> list[str]:
    """The stories they've told you so far (one per bond level reached)."""
    return STORIES[key][:bond(days)[0]]


def _pick(variants: list[str], salt: str) -> str:
    return variants[int(hashlib.sha1(salt.encode()).hexdigest(), 16) % len(variants)]


def line(key: str, ctx: dict, salt: str = "") -> str:
    """What they say right now. Rotates every 3 hours so it doesn't go stale."""
    for cond, variants in LINES[key]:
        try:
            if cond(ctx):
                return _pick(variants, f"{key}{salt}{ctx.get('hour', 0) // 3}").format(**ctx)
        except (KeyError, TypeError, ValueError):
            continue
    return CREW[key]["catch"]


def banter(hired: list[str], ctx: dict, salt: str = "") -> tuple[str, str, str, str] | None:
    """One exchange between two hired crew, or None."""
    ok = [b for b in BANTER if b[0] in hired and b[1] in hired]
    for a, b_, cond, sa, sb in ok:
        try:
            if cond(ctx) and cond is not BANTER[-1][2]:
                return a, sa.format(**ctx), b_, sb.format(**ctx)
        except (KeyError, TypeError, ValueError):
            continue
    if ok and int(hashlib.sha1(salt.encode()).hexdigest(), 16) % 3 == 0:  # the default one, now and then
        a, b_, _, sa, sb = ok[-1]
        return a, sa.format(**ctx), b_, sb.format(**ctx)
    return None


def mood(ctx: dict) -> str:
    return "worried" if ctx.get("flaked") or (ctx.get("focus", 0) == 0 and ctx.get("hour", 0) >= 15) else \
        "fired" if ctx.get("won") or ctx.get("focus", 0) >= 120 else "ok"


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
    brows = {"ok": "", "worried": "<path d='M22 26 L29 28 M42 26 L35 28' stroke='#14171d' stroke-width='1.6'/>",
             "fired": "<path d='M22 27 Q25.5 24 29 27 M35 27 Q38.5 24 42 27' stroke='#14171d' stroke-width='1.6' fill='none'/>"}[mood]
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
            f"{hair}{brows}<circle cx='26' cy='32' r='1.8' fill='#14171d'/><circle cx='38' cy='32' r='1.8' fill='#14171d'/>"
            f"<path d='{mouth}' stroke='#14171d' stroke-width='2' fill='none' stroke-linecap='round'/>{gear}</svg>")


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
