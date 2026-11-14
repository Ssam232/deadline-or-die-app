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
import re
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
    "medic": {
        "name": "Noor", "role": "Team medic & physio", "price": 900, "perk": "−25% repair costs",
        "skin": "#a8714f", "hair": "#2a2140", "style": "hijab", "shirt": "#e9edf2", "gear": "stetho",
        "bio": "Ten years as an ER nurse, then she got hooked on endurance racing. Runs marathons. Treats sleep like a training session.",
        "quirk": "Always has electrolyte tablets on her and will judge how much water you drank.",
        "likes": "Eight hours of sleep, long runs at sunrise, people who take breaks before they break.",
        "catch": "Rest is part of the work.",
    },
    "dj": {
        "name": "Kai", "role": "Radio & hype", "price": 700, "perk": "+1 race a day",
        "skin": "#5b3a29", "hair": "#141414", "style": "locs", "shirt": "#7b2ff7", "gear": "headphones",
        "bio": "Produces beats between races and runs the team radio. Has a playlist for every mood, including 'tax season'.",
        "quirk": "Narrates everything like a race commentator. Including you making coffee.",
        "likes": "Bass you can feel, crowds, finishing a track at 2 AM (he's working on that).",
        "catch": "And they're off!",
    },
    "chef": {
        "name": "Inês", "role": "Hospitality & team cook", "price": 650, "perk": "Dailies pay +25%",
        "skin": "#e8b98f", "hair": "#5a3418", "style": "long", "shirt": "#ff7a45", "gear": "apron",
        "bio": "Cooked in her grandmother's restaurant in Porto before cooking for race teams. Grows her own herbs in the paddock.",
        "quirk": "Will not let anyone work on an empty stomach. Has never once been argued with successfully.",
        "likes": "Slow Sunday cooking, fresh basil, the small habits that hold a day together.",
        "catch": "Eat first. Then conquer.",
    },
    "artist": {
        "name": "Yuki", "role": "Livery designer", "price": 750, "perk": "−25% on paint & kits",
        "skin": "#f3d2b3", "hair": "#1c1c2e", "style": "bangs", "shirt": "#ff4f9a", "gear": "pencil",
        "bio": "Illustrator who sketches every car she sees. Designed liveries for a junior team, then for you. Fills a sketchbook a month.",
        "quirk": "Doodles your car on whatever's nearby: napkins, whiteboards, the back of your to-do list.",
        "likes": "Manga, bold colour, the sketch you do every day even when it's bad.",
        "catch": "Make it yours.",
    },
    "spotter": {
        "name": "Mateo", "role": "Spotter", "price": 850, "perk": "+10% XP on every finish",
        "skin": "#b98760", "hair": "#2b1d14", "style": "curly", "shirt": "#3fae5a", "gear": "binoculars",
        "bio": "Rock climber and birdwatcher. Spends hours waiting for one good sighting and calls it a great day.",
        "quirk": "Keeps a notebook of every bird he's seen at every track. Has opinions about the crows at Bow River.",
        "likes": "Patience, early mornings, the summit after the slow part.",
        "catch": "Clear ahead. Go.",
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

STORIES.update({
    "medic": [
        "Night shifts taught me something: nobody burns out from one hard night. It's the hundred nights with no rest in between.",
        "I ran my first marathon at 31. I walked half of it. I still finished. That's the only part anyone remembers.",
        "I left the ER because I wanted to help people before things went wrong, not after. That's what a good routine is.",
        "When I see your journal filled in, I relax a bit. It means you're checking in with yourself.",
        "You'd make a good endurance athlete. You keep going when it's boring. That's the whole sport.",
    ],
    "dj": [
        "I made my first beat on a school laptop with the sound off so I wouldn't get caught. Finished it anyway.",
        "Every track I've finished was worse than the one in my head. Finished beats unfinished, every time.",
        "My mom drove a bus for twenty years and still sang every morning. That's where I got the hype from.",
        "I used to wait for inspiration. Then I learned you just open the laptop and it shows up halfway through.",
        "If I ever play a big show, your race intro is going in the set. Don't tell anyone.",
    ],
    "chef": [
        "My grandmother cooked the same soup every Sunday for fifty years. People came from three towns over. Consistency is a flavour.",
        "First kitchen I worked, I burned the rice three days running. The chef made me cook it again every time. Now it's perfect.",
        "A good meal is mostly prep. Chopping onions isn't glamorous. Neither are dailies. Both matter.",
        "I plant basil every spring, even the years it doesn't come up. You don't skip planting because of last year.",
        "When you hit all your dailies, I make the good bread. You've never noticed. That's fine. I notice.",
    ],
    "artist": [
        "I drew every day for a year when I was fifteen. Most of it was bad. Day 300 was the first one I was proud of.",
        "My first livery design got rejected. I kept the sketch. It's on my wall so I remember what 'not yet' looks like.",
        "People think talent is the thing. It's the sketchbook. Fill the sketchbook.",
        "I draw your car after every race. The ones after bad races are my favourites. The lines are angrier.",
        "One day I want to see a whole grid wearing colours I made. Until then, you're my gallery.",
    ],
    "spotter": [
        "My first big climb, I turned back two hundred metres from the top. Went back the next year. The summit was the same; I wasn't.",
        "I once waited six hours for an owl. It showed up for eleven seconds. Best day of that year.",
        "On a wall, you never look at the summit. You look at the next hold. That's all I'm doing on the radio.",
        "Birds come back to the same places every year, same time, no fuss. That's what reliable looks like.",
        "I've spotted for faster drivers. Not for one who keeps showing up like you do. I'm glad I'm here.",
    ],
})

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
    "medic": [
        (lambda x: x["hour"] >= 23 or x["hour"] < 4, ["It's late. Last task, then sleep. Your brain files today's work while you sleep.",
                                                      "Doctor's orders: wrap it up. Tomorrow-you needs that sleep."]),
        (lambda x: x["focus"] >= 90, ["{focus} minutes. Stand up, drink water, look at something far away. Then go again.",
                                      "Big stint. Take the break the timer gives you, it's not optional."]),
        (lambda x: x["zero_yday"], ["Rough day yesterday? Happens. Start small today. A five-minute task counts.",
                                    "Yesterday's done. Today's a new shift."]),
        (lambda x: x["journaled"], ["You checked in with yourself today. That's good medicine.",
                                    "Journal's in. I sleep better when you do that."]),
        (lambda x: True, ["Rest is part of the work.", "Have you had water today? Honest answer.",
                          "Steady pace beats sprint-and-crash."]),
    ],
    "dj": [
        (lambda x: x["won"], ["AND THE WINNER IS {name}! I've already made the replay into a beat.",
                              "Victory lap! Somebody cue the anthem!"]),
        (lambda x: x["focus"] >= 60, ["{focus} minutes on the board! The crowd goes wild!",
                                      "This is a certified locked-in session. I'm narrating it."]),
        (lambda x: not x["qualified"], ["The grid's waiting, the crowd's waiting, I'm waiting. Lock it in!",
                                        "Mission board's empty. My commentary needs material, {name}."]),
        (lambda x: x["focus"] == 0 and x["hour"] >= 14, ["Crowd's getting restless. Give them a stint. Twenty-five minutes, go!",
                                                         "Dead air on the radio. Start the timer and give me something to call."]),
        (lambda x: True, ["And they're off!", "New playlist just dropped: 'focus mode, no skips'.",
                          "Every legend has a training montage. This is yours."]),
    ],
    "chef": [
        (lambda x: x["hour"] < 10, ["Morning! Did you eat? Real food, not coffee.",
                                    "Breakfast first. Deadlines second. Trust me."]),
        (lambda x: x["done"] >= 3, ["{done} done! That deserves a proper dinner tonight.",
                                    "Look at you go. I'm making the good bread."]),
        (lambda x: x["hour"] >= 12 and x["hour"] < 14, ["Lunch. Away from the screen. Fifteen minutes. Then back to it.",
                                                        "It's lunchtime. The work will still be there, I promise."]),
        (lambda x: x["streak"] >= 7, ["{streak} days. That's like a good stock: nothing fancy, just time.",
                                      "{streak} days in a row. Small things every day, that's the recipe."]),
        (lambda x: True, ["Eat first. Then conquer.", "Little habits are the salt. You don't notice them until they're missing.",
                          "Slow and steady cooks it right."]),
    ],
    "artist": [
        (lambda x: x["won"], ["I'm drawing this one. Victory sketch, bold colours.",
                              "Winner's livery idea: gold pinstripe. Thoughts?"]),
        (lambda x: x["focus"] > 0 and x["focus"] < 25, ["A rough sketch is still a sketch. Keep going.",
                                                        "First lines are always messy. Draw the next one."]),
        (lambda x: x["coins_n"] > 1500, ["You've got {coins} coins and the same paint job. Let me cook.",
                                         "That bank balance could be a whole new look, just saying."]),
        (lambda x: not x["done"] and x["hour"] >= 16, ["Blank page all day? Just make one mark. Anything.",
                                                       "Nothing finished yet. Pick the smallest one and ink it."]),
        (lambda x: True, ["Make it yours.", "Fill the sketchbook. Even the bad pages.",
                          "Done is a style too."]),
    ],
    "spotter": [
        (lambda x: x["streak"] >= 5, ["{streak} days. Like a bird that comes back every spring. Steady.",
                                      "Clear ahead. {streak} days and the road's open."]),
        (lambda x: x["focus"] >= 60, ["Good line. Keep it there.", "{focus} minutes: you're on the wall and climbing well."]),
        (lambda x: x["hour"] < 8, ["Best sightings are early. You're up. Use it.",
                                   "Dawn. Quietest part of the day. Good time for hard things."]),
        (lambda x: not x["qualified"], ["Next hold, not the summit. What's the first task?",
                                        "Can't spot a line if there's no line. Pick today's route."]),
        (lambda x: True, ["Clear ahead. Go.", "Patience isn't waiting. It's staying on it.",
                          "Eyes on the next hold."]),
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
    ("medic", "dj", lambda x: x["hour"] >= 23 or x["hour"] < 4, "Kai, turn it down. Some of us want them asleep.",
     "Fine. Lo-fi only after midnight. That's my compromise."),
    ("chef", "engineer", lambda x: x["hour"] >= 12 and x["hour"] < 14, "Dot, you're eating lunch. Notebook down.",
     "I'm logging what I eat. It's research, Inês."),
    ("artist", "engineer", lambda x: x["done"] >= 2, "I drew your car in the margin of Dot's notebook again.",
     "It's a nice drawing. It's also over my data, Yuki."),
    ("spotter", "strategist", lambda x: not x["qualified"], "Route's not picked yet, Ash.",
     "Then what's the first hold, Mateo? Ask them."),
    ("dj", "tires", lambda x: x["focus"] >= 60, "Rook, describe the tyres for the listeners.",
     "Warm. Happy. Like the driver. Stop pointing that mic at me."),
    ("chef", "medic", lambda x: True, "Did they eat?", "Did they drink water? Let's ask both."),
    ("artist", "chief", lambda x: x["won"], "Can I put a trophy decal on the car?",
     "One. Small. And they earned it, so yes."),
    ("engineer", "chief", lambda x: True, "Mags, what's the one rule?",
     "Show up. The rest is details, Dot."),
]


# Moments: what each of them says when something specific is going on. ctx["event"] picks the set:
#   bailout (you bailed today) · rest (rest / pit stop day) · t_start (timer just started) · t_mid (mid-stint)
#   t_end (last 5 minutes) · t_break (on a break) · paused (timer paused)
EVENTS = {
    "chief": {
        "bailout": ["You called it. That's allowed. Rest properly and we go again tomorrow.",
                    "Bailing isn't quitting. Quitting is not coming back. See you tomorrow."],
        "rest": ["Rest day. Even the car gets a day off the track.", "No racing today. Recharge. That's an order."],
        "t_start": ["Clock's running. Phone face-down. Let's work.", "Lights out. Nothing else exists for a while."],
        "t_mid": ["Steady. You're right where you should be.", "Middle of the stint. This is where it's won."],
        "t_end": ["Last few minutes. Bring it home clean.", "Final lap. Don't lift now."],
        "t_break": ["Box, box. Stand up, stretch, back on time.", "Break means break. Away from the screen."],
        "paused": ["Clock's stopped. Every minute paused is a minute owed.", "Paused. Sort it and get back out there."],
    },
    "tires": {
        "bailout": ["Tyres need cooling sometimes. Today's a cool-down lap.", "Off day. The rubber will still be here."],
        "rest": ["Tyre blankets on. Rest day.", "No laps today. Let everything cool down properly."],
        "t_start": ["Cold tyres. First few minutes feel slow. Push through.", "Out lap. Build the heat."],
        "t_mid": ["Tyres are in the window now. Feel that grip?", "Perfect temperature. Keep it here."],
        "t_end": ["Tyres are going off, but you're nearly done. Hold on.", "Last minutes. Squeeze what's left."],
        "t_break": ["Pit stop. Fresh rubber, fresh head.", "Quick break. Don't let the tyres go cold."],
        "paused": ["Tyres are cooling while we sit here...", "Every second paused, they lose heat. Just saying."],
    },
    "engineer": {
        "bailout": ["Bailout logged. Not as a failure. As data. Tomorrow's line starts fresh.",
                    "One rest point in the graph. It's fine. Patterns are what matter."],
        "rest": ["Rest day logged. Recovery shows up in next week's numbers.", "No sessions planned. Good: rest is a variable too."],
        "t_start": ["Recording. Every minute from here goes in the notebook.", "Session started. I've opened a new page."],
        "t_mid": ["Data looks good. Consistent pace.", "Halfway point. Numbers are clean."],
        "t_end": ["Almost a full session. I'll log it in pen.", "Few minutes left. Finish clean, the data loves a clean finish."],
        "t_break": ["Break logged. Recovery is part of the dataset.", "Rest interval. Hydrate, I'm graphing it."],
        "paused": ["Paused. I've stopped the graph. It looks lonely.", "The line's flat while you're paused. Just noting it."],
    },
    "strategist": {
        "bailout": ["Retreat isn't defeat. What's tomorrow's first move?", "Today's a sacrifice. Make it worth something tomorrow."],
        "rest": ["Rest is a move too. A good one.", "No pieces moving today. Think about next week instead."],
        "t_start": ["Opening move made. Now just play.", "The hardest move was starting. Done."],
        "t_mid": ["Middlegame. Stay patient.", "You're ahead of where you'd be if you hadn't started. Obviously."],
        "t_end": ["Endgame. Don't blunder now.", "Few minutes left. Close it out."],
        "t_break": ["Break. What's the next move after this?", "Use the break to pick the next task. Then rest."],
        "paused": ["Paused. Is this a plan, or a distraction?", "What's the reason for the pause? Honest answer."],
    },
    "medic": {
        "bailout": ["Good call. Rest is treatment too. Sleep early tonight.", "Bailing out to recover is smart, not weak. Hydrate."],
        "rest": ["Rest day. Eat well, sleep well, move a little.", "Recovery day. Your brain consolidates while you rest."],
        "t_start": ["Water nearby? Good. Off you go.", "Posture check: shoulders down. Now work."],
        "t_mid": ["Blink. Unclench your jaw. Keep going.", "You're doing well. Remember to breathe."],
        "t_end": ["Almost there. Finish, then stretch.", "Last stretch. Literally stretch after this."],
        "t_break": ["Look out a window. Twenty seconds at something far away.", "Stand up. Walk around. Doctor's orders."],
        "paused": ["Pausing's fine if you need it. Just come back.", "Are you okay? Take what you need, then return."],
    },
    "dj": {
        "bailout": ["Tonight's set is lo-fi and chill. Tomorrow we turn it back up.", "Skipping a show doesn't end the tour."],
        "rest": ["Off-day playlist: slow jams only.", "No live set today. Recharging the speakers."],
        "t_start": ["And the session is LIVE!", "Drop the beat. Focus mode, no skips."],
        "t_mid": ["We're in the groove now!", "This is the part of the track where it all comes together."],
        "t_end": ["Final chorus! Bring it home!", "Last few bars. Big finish!"],
        "t_break": ["Intermission! Grab a drink, back for the second half.", "Halftime show is you stretching. Go."],
        "paused": ["Dead air! The listeners are confused!", "Record scratch. Why'd we stop?"],
    },
    "chef": {
        "bailout": ["Bailout day. Make yourself something warm and go to bed early.", "Some days you just need soup. Today's one."],
        "rest": ["Rest day. Cook something slow. Enjoy it.", "Day off. Eat with people you like."],
        "t_start": ["Water and a snack by your side? Good, now go.", "Mise en place done. Start cooking."],
        "t_mid": ["Simmering nicely. Don't touch the heat.", "It's coming together. Keep stirring."],
        "t_end": ["Almost ready to plate. Don't rush the end.", "Nearly done. I'll put the kettle on."],
        "t_break": ["Break! Eat something. A real something.", "Snack time. Fruit counts. Chips also count, I'm not judging."],
        "paused": ["Pot's off the heat. Don't let it go cold.", "Pausing the recipe halfway never ends well. Back to it."],
    },
    "artist": {
        "bailout": ["Some days the sketchbook stays closed. That's okay. Doodle something for fun.",
                    "Bailout day. Draw anything, just for you, no deadline."],
        "rest": ["Rest day. Fill up on inspiration: go look at something beautiful.", "Off day. Doodle, don't design."],
        "t_start": ["First lines down. Don't erase, keep going.", "Blank page conquered. Keep drawing."],
        "t_mid": ["Shapes are forming. Trust the process.", "Messy middle. Every good piece has one."],
        "t_end": ["Inking time. Finish the lines.", "Almost done. Sign it."],
        "t_break": ["Break! Step back and look at it with fresh eyes.", "Stretch your hands. Artists get cramps too."],
        "paused": ["Pencil down? Don't leave the sketch half-finished.", "Paused. The idea's still warm, come back soon."],
    },
    "spotter": {
        "bailout": ["Not every day's a summit day. Weather's bad, we come back.", "Turning back is a skill. See you at base camp."],
        "rest": ["Rest day at base camp. The mountain will wait.", "No climbing today. Watch the birds."],
        "t_start": ["On belay. Climb when ready.", "First hold. Good. Next one."],
        "t_mid": ["Good rhythm. Hold, move, hold.", "Halfway up. Don't look down, look at the next hold."],
        "t_end": ["Summit's right there. Last few moves.", "Top-out in a few minutes. Steady hands."],
        "t_break": ["Ledge rest. Shake out your arms.", "Good spot to rest. Enjoy the view a second."],
        "paused": ["Hanging on the rope. That's fine, just don't stay too long.", "Paused on the wall. Breathe, then climb."],
    },
}

# Now and then, instead of advice: just them being them.
QUIPS = {
    "chief": ["I once timed my own wedding. Ran four minutes over. Still annoyed.",
              "Rook asked me if I ever take a day off. I said I'll consider it in 2037.",
              "My stopwatch has a name. No, I'm not telling you."],
    "tires": ["I can hear a tyre's pressure by flicking it. Party trick, wasted on parties.",
              "Kai keeps sampling the tyre squeal for his beats. I want royalties.",
              "Hot take: the best smell in the world is fresh rubber. I will not be taking questions."],
    "engineer": ["I made a graph of how many graphs I make. It's trending up.",
                 "Yuki drew a racecar on my data again. It's honestly a good drawing.",
                 "My cat's name is Standard Deviation. Dev for short."],
    "strategist": ["I lost to a nine-year-old at chess once. On purpose. Mostly.",
                   "Have you ever noticed I never answer a question directly? Interesting, isn't it?",
                   "Mags thinks I'm overthinking. I've thought about that a lot."],
    "medic": ["Kai says 'water is just boring juice'. I'm drafting a formal response.",
              "I've run 14 marathons and still trip on the paddock cables. Every week.",
              "Ines keeps feeding me pastries. As your medic: excellent choice."],
    "dj": ["I made a remix of the pit lane radio. It's a banger. Mags banned it.",
           "My playlist titled 'Deadline Panic' has 300 songs. Make of that what you will.",
           "I narrated Dot opening a spreadsheet once. Best commentary of my career."],
    "chef": ["I put Mateo's bird seeds in a granola by accident. He said it was the best one yet.",
             "If you're hungry, you're not lazy. You're hungry. Eat.",
             "My grandmother would say you look thin. You don't. She says that to everyone."],
    "artist": ["I designed a livery with 40 colours once. The team said 'maybe two'. We compromised on 39.",
               "I've drawn Mags twelve times. She hasn't noticed. Or she's pretending.",
               "Your car is my muse. Don't let it go to its head."],
    "spotter": ["Saw a hawk at turn 3 today. Faster on the corners than you, no offence.",
                "I've named every crow at Bow River. Mavis is my favourite. She's a menace.",
                "Climbing tip: if you're scared, look at your hands. Works for emails too."],
}


def bond(days: int) -> tuple[int, str, int | None]:
    """(level index, name, days to the next level or None)."""
    lvl = max(i for i, (d, _) in enumerate(BOND_LEVELS) if days >= d)
    nxt = BOND_LEVELS[lvl + 1][0] - days if lvl + 1 < len(BOND_LEVELS) else None
    return lvl, BOND_LEVELS[lvl][1], nxt


def stories(key: str, days: int, hired=None) -> list[str]:
    """The stories they've told you so far (one per bond level reached), skipping any about crew you haven't met."""
    return [x for x in STORIES[key] if known(x, hired)][:bond(days)[0]]


def _pick(variants: list[str], salt: str) -> str:
    return variants[int(hashlib.sha1(salt.encode()).hexdigest(), 16) % len(variants)]


_NAMES = {"Mags": "chief", "Rook": "tires", "Dot": "engineer", "Ash": "strategist", "Noor": "medic", "Kai": "dj",
          "Inês": "chef", "Ines": "chef", "Yuki": "artist", "Mateo": "spotter"}
_NAME_RE = re.compile(r"\b(" + "|".join(_NAMES) + r")\b")


def known(text: str, hired) -> bool:
    """Only mention crew you've actually hired (no 'who's Yuki?')."""
    if hired is None:
        return True
    return all(_NAMES[m] in hired for m in _NAME_RE.findall(text))


def _fit(variants: list[str], hired) -> list[str]:
    return [v for v in variants if known(v, hired)]


def line(key: str, ctx: dict, salt: str = "") -> str:
    """What they say right now: the moment first (bailout, rest, a running timer), otherwise now and then a joke,
    otherwise their read on your day. Rotates every 3 hours (every few minutes while a timer runs)."""
    ev, hired = ctx.get("event"), ctx.get("hired")
    if ev and _fit(EVENTS.get(key, {}).get(ev, []), hired):
        return _pick(_fit(EVENTS[key][ev], hired), f"{key}{salt}{ev}{ctx.get('slot', 0)}").format(**ctx)
    quips = _fit(QUIPS[key], hired)
    if quips and int(hashlib.sha1(f"q{key}{salt}{ctx.get('hour', 0) // 3}".encode()).hexdigest(), 16) % 4 == 0:
        return _pick(quips, f"{key}{salt}{ctx.get('hour', 0)}")
    for cond, variants in LINES[key]:
        try:
            if cond(ctx) and _fit(variants, hired):
                return _pick(_fit(variants, hired), f"{key}{salt}{ctx.get('hour', 0) // 3}").format(**ctx)
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
    return face_svg(CREW.get(key) or CAST[key], size, mood)


def face_svg(c: dict, size: int = 64, mood: str = "ok") -> str:
    hair = {
        "bun": f"<circle cx='32' cy='12' r='7' fill='{c['hair']}'/><path d='M14 30 Q14 14 32 14 Q50 14 50 30 L50 24 Q46 18 32 18 Q18 18 14 24 Z' fill='{c['hair']}'/>",
        "buzz": f"<path d='M15 28 Q15 13 32 13 Q49 13 49 28 Q46 19 32 19 Q18 19 15 28 Z' fill='{c['hair']}'/>",
        "bob": f"<path d='M13 36 Q11 12 32 12 Q53 12 51 36 L47 36 Q48 20 32 19 Q16 20 17 36 Z' fill='{c['hair']}'/>",
        "swept": f"<path d='M14 28 Q16 10 36 12 Q52 14 50 30 Q44 16 30 20 Q20 22 14 28 Z' fill='{c['hair']}'/>",
        "hijab": f"<path d='M12 44 Q8 12 32 10 Q56 12 52 44 Q50 50 44 52 L44 34 Q44 18 32 18 Q20 18 20 34 L20 52 Q14 50 12 44 Z' fill='{c['hair']}'/>"
                 f"<path d='M20 48 Q32 58 44 48 L44 56 Q32 62 20 56 Z' fill='{c['hair']}'/>",
        "locs": f"<path d='M14 30 Q14 12 32 12 Q50 12 50 30 Q46 18 32 18 Q18 18 14 30 Z' fill='{c['hair']}'/>"
                + "".join(f"<rect x='{x}' y='22' width='3.2' height='{h}' rx='1.6' fill='{c['hair']}'/>"
                          for x, h in ((13, 22), (17, 26), (44, 26), (48, 22))),
        "long": f"<path d='M13 50 Q9 14 32 11 Q55 14 51 50 L46 50 Q48 22 32 19 Q16 22 18 50 Z' fill='{c['hair']}'/>",
        "bangs": f"<path d='M13 40 Q11 11 32 11 Q53 11 51 40 L48 40 Q48 24 44 24 L20 24 Q16 24 16 40 Z' fill='{c['hair']}'/>",
        "pomp": f"<path d='M14 30 Q12 6 34 6 Q54 8 50 30 Q48 16 34 16 Q20 16 14 30 Z' fill='{c['hair']}'/>"
                f"<path d='M22 42 Q32 47 42 42' stroke='{c['hair']}' stroke-width='2.4' fill='none'/>",
        "curly": "".join(f"<circle cx='{x}' cy='{y}' r='5' fill='{c['hair']}'/>" for x, y in
                         ((18, 22), (24, 16), (32, 14), (40, 16), (46, 22), (16, 29), (48, 29)))
                 + f"<path d='M22 42 Q32 52 42 42 Q42 50 32 51 Q22 50 22 42 Z' fill='{c['hair']}' opacity='.85'/>",
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
        "stetho": "<path d='M24 50 Q24 58 32 58 Q40 58 40 50' stroke='#3a3f4b' stroke-width='2' fill='none'/>"
                  "<circle cx='32' cy='59' r='2.6' fill='#9aa0aa'/>",
        "headphones": "<path d='M13 32 Q13 9 32 9 Q51 9 51 32' stroke='#e6e6e6' stroke-width='3.2' fill='none'/>"
                      "<rect x='9' y='27' width='8' height='12' rx='4' fill='#7b2ff7'/><rect x='47' y='27' width='8' height='12' rx='4' fill='#7b2ff7'/>",
        "apron": "<path d='M22 50 L42 50 L44 64 L20 64 Z' fill='#f6f1e7'/><path d='M24 50 Q32 46 40 50' stroke='#f6f1e7' stroke-width='1.5' fill='none'/>",
        "pencil": "<rect x='44' y='12' width='3' height='16' rx='1' fill='#f5c518' transform='rotate(25 45 20)'/>"
                  "<circle cx='22' cy='37' r='2.2' fill='#ff9db8' opacity='.7'/><circle cx='42' cy='37' r='2.2' fill='#ff9db8' opacity='.7'/>",
        "mic": "<rect x='44' y='38' width='7' height='11' rx='3.5' fill='#c9ccd2'/><rect x='46' y='49' width='3' height='12' fill='#1b1f27'/>"
               "<path d='M23 52 L32 57 L41 52' stroke='#f5c518' stroke-width='2' fill='none'/>",
        "clipboard": "<rect x='40' y='44' width='15' height='19' rx='2' fill='#c8a46a'/><rect x='42' y='48' width='11' height='13' fill='#f6f1e7'/>"
                     "<rect x='44' y='42' width='7' height='4' rx='1' fill='#8b909c'/>"
                     "<circle cx='26' cy='32' r='5' stroke='#1b1f27' stroke-width='1.6' fill='none'/><circle cx='38' cy='32' r='5' stroke='#1b1f27' stroke-width='1.6' fill='none'/>"
                     "<path d='M31 32 L33 32' stroke='#1b1f27' stroke-width='1.6'/>",
        "binoculars": "<rect x='22' y='51' width='8' height='9' rx='2.5' fill='#1b1f27'/><rect x='34' y='51' width='8' height='9' rx='2.5' fill='#1b1f27'/>"
                      "<rect x='29' y='53' width='6' height='3' fill='#1b1f27'/>",
    }[c["gear"]]
    return (f"<svg viewBox='0 0 64 64' width='{size}' height='{size}' xmlns='http://www.w3.org/2000/svg'>"
            f"<circle cx='32' cy='32' r='31' fill='#1b2030' stroke='{c['shirt']}' stroke-width='2'/>"
            f"<path d='M10 64 Q12 48 32 48 Q52 48 54 64 Z' fill='{c['shirt']}'/>"
            f"<rect x='28' y='42' width='8' height='8' fill='{c['skin']}'/>"
            f"<ellipse cx='32' cy='31' rx='15' ry='17' fill='{c['skin']}'/>"
            f"{hair}{brows}<circle cx='26' cy='32' r='1.8' fill='#14171d'/><circle cx='38' cy='32' r='1.8' fill='#14171d'/>"
            f"<path d='{mouth}' stroke='#14171d' stroke-width='2' fill='none' stroke-linecap='round'/>{gear}</svg>")


# ── The regulars: not crew you hire, just people who are always around ──
CAST = {
    "announcer": {"name": "\"Voice\" Valenti", "role": "Race-day announcer", "skin": "#d9a27a", "hair": "#1a1a1a",
                  "style": "pomp", "shirt": "#e10600", "gear": "mic",
                  "bio": "Has announced every grid for 30 years. Has never once used an indoor voice."},
    "marshal": {"name": "Marshal Pearl", "role": "Dailies marshal", "skin": "#c98e6b", "hair": "#b9b9c0",
                "style": "bun", "shirt": "#f5c518", "gear": "clipboard",
                "bio": "Retired school hall monitor. Now she watches your dailies. Clipboard, whistle, no excuses, "
                       "secretly very proud of you."},
}

# Valenti calls the focus challenges: ctx = {live, label, left, claimed, next_at}
ANNOUNCER = {
    "live": ["LADIES AND GENTLEMEN, A CHALLENGE HAS APPEARED! {left} on the clock! WHO WANTS IT?!",
             "IT'S HAPPENING, FOLKS! {left} left to get rolling! I haven't been this excited since breakfast!",
             "BREAKING NEWS FROM THE PADDOCK: the gates are open! The crowd is on its feet! (The crowd is me.)",
             "{left} TO GO! Somebody hold my microphone, I'm getting emotional!",
             "A double-or-nothing moment, folks! Well, double-or-regular. Still! {left}!"],
    "claimed": ["WHAT A SESSION! CHALLENGE CLAIMED! I'm going to need a minute. And a lozenge.",
                "UNBELIEVABLE SCENES! Challenge done! Someone get this driver a trophy! Or at least a snack!",
                "AND THAT'S HOW IT'S DONE! Mark it in the history books! Small books! But books!"],
    "quiet": ["Quiet on the track right now. Surprise challenges buzz your phone. I'll be warming up my voice.",
              "No challenge live. I'm doing my vocal exercises. MEE-MAY-MAH. Sorry.",
              "Between challenges, folks. Start a session anyway: the timer doesn't need my permission. (It does like it.)"],
}

# Pearl watches the dailies: ctx = {done, total, hour, stake, best, best_streak, rest}
MARSHAL = [
    (lambda x: x["rest"], ["Free day on the board. Clipboard's down. Don't get used to it.",
                           "Off duty today. I'm doing a crossword. Do yours anyway if you like; I'll pretend not to look."]),
    (lambda x: x["total"] and x["done"] == x["total"], ["All {total} done. I'm putting a gold star on my clipboard. Don't tell anyone.",
                                                       "Full marks. In thirty years of hall monitoring, I've rarely said that. Well done.",
                                                       "Everything ticked. I may have smiled. You didn't see it."]),
    (lambda x: x["hour"] >= 21 and x["done"] < x["total"], ["It's past nine and I see {left} left. My whistle is ready. Please don't make me use it.",
                                                           "Clock's ticking, {left} to go, −{stake} at midnight. I'll wait. I'm very good at waiting.",
                                                           "Late shift. {left} left. I've seen students finish essays in less time. Go."]),
    (lambda x: x["best_streak"] >= 5 and x["done"] < x["total"], ["{best} is on a {best_streak}-day streak. I'd hate to write 'reset' on my clipboard. Hate it.",
                                                                 "Don't break {best}'s {best_streak}-day streak. I've grown attached. Professionally."]),
    (lambda x: x["done"] == 0 and x["hour"] < 12, ["Morning. Clipboard's clean. Let's keep it that way: tick one off early.",
                                                   "Roll call: 0 of {total}. That's fine for now. 'For now' is doing a lot of work there."]),
    (lambda x: x["done"] == 0, ["0 of {total}. I'm not angry. I'm just writing things down.",
                                "Nothing ticked yet. I've confiscated better excuses than whatever you're about to say."]),
    (lambda x: True, ["{done} of {total}. Steady. I like steady.", "{done} down, {left} to go. Hallway's clear, keep walking. No running.",
                      "Halfway-ish. I've made a note. A positive note, for once."]),
]


def cast_line(who: str, ctx: dict, salt: str = "") -> str:
    if who == "announcer":
        k = "claimed" if ctx.get("claimed") else "live" if ctx.get("live") else "quiet"
        return _pick(ANNOUNCER[k], f"ann{salt}{k}").format(**ctx)
    for cond, variants in MARSHAL:
        try:
            if cond(ctx):
                return _pick(variants, f"pearl{salt}").format(**ctx)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    return ""


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
