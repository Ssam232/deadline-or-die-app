# 🏁 Deadline or Die

Prove it or pay for it. Every task has a deadline, a reward and a penalty.
Finish → submit proof → coins, XP, a pit crate → upgrade your car → race your procrastination rivals.
Miss → lose coins, wreck the car, lose your streak, feed the rivals, serve your real-world consequence.
Your phone won't let you forget.

```
app.py              Streamlit app (the game)
notion_store.py     Notion backend: save file + synced task table + proof uploads
nag.py              Phone nagger (GitHub Actions, every 10 min when GitHub obliges)
alarms.py           Exact-time alarms queued on ntfy (prayers, deadline countdowns, qualifying, last calls)
notify.py           ntfy push helper
.github/workflows/nag.yml
```

## Setup (~15 min, once)

### 1. Notion (where everything lives)
1. Go to **notion.so/profile/integrations** → **New integration** → name it *Deadline or Die* → type **Internal** → save → copy the **Internal Integration Secret** (`NOTION_TOKEN`).
2. Make an empty Notion page called **Deadline or Die**.
3. On that page: `•••` (top right) → **Connections** → add *Deadline or Die*.
4. Copy the page link (`NOTION_PARENT_PAGE`).

On first launch the app creates three things inside that page:
- **🏁 Deadline or Die — Tasks**: a table synced both ways. Add a row with a **Due** date (and optionally Size + Consequence) and it joins the game. Ticking it Done, moving the date, or deleting the row in Notion gets reverted. Proof only happens in the app.
- **💾 Save file**: your coins, car, streak (don't edit).
- **📣 Nagger**: what's already been pushed to your phone (don't edit).

### 2. Phone (ntfy)
Install **ntfy** (iOS App Store / Google Play) → **+** → subscribe to your topic (`NTFY_TOPIC`).
Anyone who knows the topic name can read it, so keep it long and random.
Android: in ntfy's notification settings, let max-priority alerts pop over and bypass Do Not Disturb if you want it truly in your face.

### 3. GitHub
Push this folder to a **private** repo. Then **Settings → Secrets and variables → Actions → New repository secret** for each of:
`NOTION_TOKEN`, `NOTION_PARENT_PAGE`, `NTFY_TOPIC`, `APP_URL`.
**Actions** tab → *Nag* → **Run workflow** to test. After that it runs on its own every 10 min, but GitHub often skips scheduled runs for hours. So anything time-critical doesn't depend on it: the app queues those alarms on ntfy's server for their exact minute and cancels them the moment they stop applying (see *Exact-time alarms*).

### 4. Streamlit Community Cloud
1. **share.streamlit.io** → sign in with GitHub (allow private repo access) → **Create app** → pick the repo, branch `main`, file `app.py`.
2. **Advanced settings → Secrets**: paste your filled-in `.streamlit/secrets.toml.example`.
3. Deploy. Copy the app URL into the `APP_URL` secret (both on GitHub and in Streamlit secrets).
4. Optional: App settings → Sharing → make it private.
5. On your phone, open the app URL → Share → **Add to Home Screen**.

Note: free Streamlit apps sleep after a few days without visits. The first open after that takes ~30 seconds, and your data is safe in Notion.

### Run locally instead
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill in, or leave Notion out to save to data/
streamlit run app.py
```

## The phone ladder
| When | Push | Priority |
|---|---|---|
| 8 AM daily | Briefing: next 48h, coins, streak, danger-day warning on Tue/Wed | normal |
| ≤ 24h | ⏱️ heads-up | normal |
| ≤ 6h | 🟡 "Open it. Work 10 minutes." | high |
| ≤ 2h | 🔴 Red zone: what you'll lose + your consequence. **Repeats hourly.** | max |
| ≤ 30m | ☠️ Final warning. **Repeats every 25 min.** Breaks quiet hours. | max |
| Missed | 💀 DNF + rival taunt + redemption window. Breaks quiet hours. | max |
| 8 PM | 🌙 "Nothing finished today" (only if true) | high |
| 2+ idle days | 🟫 "Your car is rusting" | high |
| You finish | 🏁 Checkered flag + crate result, sent by the app | normal / high on rare drops |

Quiet hours are 11 PM–7 AM (`QUIET_HOURS` in the workflow). Only final warnings and DNFs break through.

## 🚦 Daily qualifying (no empty days)
| | |
|---|---|
| Mission | Every day, lock in 1–3 things you'll finish **today** before the cutoff (default 11 AM, Settings). On time = +15 fuel. |
| Start time | You say when you'll start; the phone fires "LIGHTS OUT" at that time if nothing's done. |
| Missed cutoff | −20 coins, rivals faster, and the **safety car** assigns: 30 min focused work, proof by 6 PM. |
| Zero day | Nothing finished by midnight → −40 coins, −10% car, day streak dies. |
| Pit stop | 1 per week for sick/rest days, plus any standing rest weekdays you set. |
| Comeback rule | Back after a long gap? At most 3 zero days are charged; the rest are forgiven. |

## ⚡ Zero-friction entry
- **Quick add** (top of the app): type it like a text — `email walter re surgery dates 15m by 3pm`, `write discussion 1.5h tomorrow`, `gym 60m tonight`. Time, deadline and category are worked out for you.
- **Templates:** one tap for inbox, 300 words, a paper, data analysis, gym, an errand.
- **🎲 Just tell me what to do:** picks your best next task (mission → soonest due → quick wins) and starts the focus timer on it.

## 🎡 Picking times
Every time field is a scroll wheel (hour · minute · AM/PM, like an iPhone alarm). Start times are one tap: **I'll start in Now · 30m · 1h · 2h · 3h**, or 🎡 to pick an exact time. The start time is what lands your task on the output board (Fortuna).

## 🔁 Dailies (low gain, high penalty)
Self-entered habits that must happen every day: 💧 water ×8, 🕌 prayers ×5, 🦷 brushing ×2, or your own. Tap **+1** each time (↩ undoes). Hit the count → **🏆 Claim** a small reward and grow its 🔥 streak; every 7 days in a row pays a +15 bonus. Miss it → a **big penalty at midnight**. The game sets the values from how many times a day it has to happen: 1× +5/−45 · 2× +5/−40 · 3× +6/−35 · 5× +5/−25 · 8× +6/−20. They break even around a 90% hit rate (easing to ~76% for 8×), so consistent = slowly richer, sloppy = poorer. Missed dailies cost at most 60 in one day, and the day you add one is free. Dailies never touch your Notion boards. Rules: removing a daily only takes effect tomorrow (today still counts), pit-stop days skip them, and after a long absence at most 3 days are charged. Your phone nags at 8 PM and 10:30 PM if any are still open.

**⏰ Exact-time alarms.** Whenever something changes, the app works out every alarm for today and tomorrow and queues it on ntfy with a delivery time: deadline countdowns (6h, 2h, 1h, 30 min, 10 min; the early ones skip quiet hours), qualifying (60/30/10 min before cutoff), the zero-day ladder (6 PM, 8 PM, 9:30 PM), dailies last calls (8 PM, 10:30 PM) and prayers. Finish the task, lock in, log the prayer or finish your dailies and the queued alarms are cancelled before they buzz. The nagger re-syncs the same alarms as a backup, and a repeat queue just replaces the old one, so nothing double-buzzes.

**🕌 Prayer times.** A daily with "pray" in its name (the 🕌 Prayers preset) follows the real prayer windows, computed in the app (no API): Fajr → sunrise, Dhuhr → Asr, Asr → Maghrib, Maghrib → Isha, Isha → 11:30 PM. Its row shows the current prayer and when it ends, and the manage panel shows today's timetable plus the method (ISNA default) and Asr school (Standard / Hanafi). Each +1 counts as the next prayer in order, so 1/5 at Asr means you're behind. Until it's logged, each prayer has alarms queued: when the window opens, 45 min left, then max priority at 20 and 10 min left, and a "window closed" ping. They fire on the minute, ignore quiet hours on purpose, and are cancelled as soon as you tap +1 (↩ brings them back).

## 💰 What tasks are worth
Value = **honest minutes × category**: 🧠 Deep work ×1.5 · 📨 Academic admin ×1.0 · 💪 Health ×0.8 · 🧺 Life admin ×0.5 · 🪑 Showing up ×0.3.
Anti-inflation: tasks finished within 10 min of creating pay 25% · over 10 claimed hours/day pays 25% · 90+ min tasks need a real file · ⏱️ timer-verified work pays +15%.

## ⏱️ Focus timer · 📜 Weekly contracts · 🎰 Paddock Lounge
- Timer: pick a task, 25/50/60/90/120 min of work, log it. Counts toward contracts and the +15% verified bonus.
- Start a timer on any open task, or pick **✏️ New task…** and type what you're doing (blank = "Focus session"): it becomes a task due tonight and the timer is its proof.
- Running timer: a little circuit. Your car laps it as you work (the trail is time done, teal marks are pit windows between stints), pulls into the 🔧 pit box on breaks, stops under a 🟡 yellow flag with hazards blinking when paused, and parks on the 🏁 line when the session is complete (overtime counts up in red). **⏸️ Pause** costs 2, 4, 6… coins per pause, paused time doesn't count, and a pause over 20 min ends the session (logging what you did). **☕ Skip break** jumps to the next work block.
- 🍅 Breaks: pick **25/5 pomodoro**, **50/10**, or a custom *break at N min* interval (remembered). The clock turns blue on breaks and beeps at each switch; only work minutes are logged, so breaks never pad the receipt.
- Contracts: 3 rotating weekly challenges, big payouts.
- Lounge: blackjack + snake eyes. Opens after you finish a task worth 1h+ or run a single 1h focus block that day — and all day on weekends; max bet 50, 15 hands/day, closes at +200 or −300. House edge ~6% (blackjack) / ~17% (dice).

## 🎉 Live events
0–2 random events a day (10 AM–8 PM), pushed to your phone: ⚡ double coins & XP (3h) · 🎁 supply drop (free crate, 2h) · 🎯 bounty (+75 for a deep-work finish, 4h) · 🔧 pit crew (free +30% repair).

## 🗓️ Your DECK 12 boards (input + output)
Settings → 🔎 Find my boards, then pick a role for each:
- **📥 Input** (e.g. Assignments): **strictly read-only** — nothing is ever written to it. Cards from today + the next 7 days (recurring weekday cards marked 🔁) become one-tap mission suggestions, and one-off events can be turned into goals.
- **📤 Output** (e.g. Fortuna, your daily schedule): **write-only**. Every task lands on it as a 🏁 card on the day/time it's *set to happen* — a board card's time, your mission laid out from "I'll START at", "gym **at** 6pm" in quick add, a prep step's day, or when you actually start the timer — and, if none of those, **when it was assigned**. Cards move if rescheduled, turn ✅ when done, and go to Notion's trash once their day is over. Nothing is ever read back from the output board, so anything else you put there stays out of the game.

## 🗓️ Events → goals (conference, talk, exam, submission)
🎯 Goals → *Prep for an upcoming event*: pick anything on your board in the next 60 days (or type one). It becomes a goal with a prep plan worked **backwards from the date** — e.g. a conference poster: story → figures → draft → supervisor feedback → revise → order print → practice pitch → pack. Squeezed automatically if the event is close; edit or untick any step. Each step is a real deadline (proof, coins, penalties) that fills the goal's bar, lands on your board as a 🏁 card within 7 days, and shows as a countdown on the Today card and in the morning push ("behind!" if prep is lagging). Or let the prep **feed into a bigger goal** you already have.

## 📊 Stats → the engine
The 📊 Stats tab shows finishes, on-time rate, focus hours, hours by category, finishes per week, minutes by hour of day and a weekday × hour heatmap. From your history (up to yesterday, after 5 active days) the engine works out your **peak hours** and **dead zones** (inside your working day, but no work happening) and uses them:
- ⏱️ focus challenges and ⚡ live events are up to 4× likelier to land in dead zones, and 💡 phone suggestions aim there too;
- ☀️ the morning briefing lands an hour before you usually start;
- 🎲 *Just tell me what to do* hands you deep work in peak hours and quick wins outside them.

## 🔒 Consequences that actually bite
Pick **🔒 Games locked on PC + phone until it's done** as a task's consequence (it's the default). Miss it and you're LOCKED until you finish it late (🩹 redeem) or 24h pass. A running focus session also locks (toggle in Settings). 🆘 Emergency unlock in the app: 1 hour for 100 coins (more at higher levels).

The lock state is broadcast to your ntfy topic + `-lock`. Two things read it:

**PC enforcer** (closes Overwatch, sim racing titles, etc. while locked)
```
pip install requests psutil
python enforcer/enforcer.py --setup     # paste your NTFY_TOPIC, review the blocklist
python enforcer/enforcer.py --status    # sanity check
python enforcer/enforcer.py --install   # runs silently at every login
```
**iPhone Shortcut** (kicks you out of a game app while locked) — Shortcuts → Automation → + → **App** → pick the game(s) → **Is Opened** → **Run Immediately**, then add these actions:
1. **Get Contents of URL** → `https://ntfy.sh/<YOUR_NTFY_TOPIC>-lock/raw?poll=1&since=3h`
2. **Split Text** by *New Lines* → **Get Item from List** → *Last Item*
3. **If** *Item from List* **begins with** `LOCKED` →
   **Show Alert** (*Item from List*) → **Go to Home Screen** → **Open URLs** (your app link)
4. **End If**

## 📄 Zotero reading list
Settings → add `ZOTERO_USER_ID` + `ZOTERO_API_KEY` (zotero.org/settings/keys; give the key write access so finished papers get tagged `read`). Papers in your "To Read" collection show up as one-tap 45-min deep-work tasks, and in the 2 daily 🎯 suggestion pushes. Add the same two values as GitHub Actions secrets for the pushes.

## 📱 No password every time
Log in once per browser and it remembers the device (a year-long key in a cookie + local storage), so any link, a notification tap or the app waking from sleep goes straight in. A Home Screen web app counts as its own browser on iPhone, so log in there once too. Changing `APP_PASSWORD` logs every device out. Notifications sent by the app already carry the `?k=…` key; for the GitHub nagger's taps, put the Settings → 📱 Remember-me link in its `APP_URL` secret.

## ⏱️ Focus challenges & session loot
**⏱️ Focus challenges:** 1–3 a day, e.g. *start a 60-min session in the next 2 hours → this session counts ⚡ double* — the task you focused on pays 2× coins & XP when you finish it (90-min challenges add a crate). They're a surprise: no schedule anywhere — your phone pings the moment a window opens (seeded from your private topic, so even the code can't spoil it). Plus every full 25+ min session rolls a small random drop (3/day). As you level up, penalties grow (up to 2×) and your daily mission must total 30 → 60 minutes.

## 🏎️ Racing (earned, not farmed)
Races need **tickets**: 1 per proof-backed finish of a 30+ min task + 1 per full focus session (25+ min), max **3 races a day**. It scales: if your car outclasses a track, two fast rivals show up at your pace and prizes shrink (down to ×0.3), so the money is always on the hardest track you can enter. Simulated best-case race income per day: ≈+45 (maxed Civic) → ≈+80 (S2000) → ≈+170 (NSX) → ≈+210 (maxed NSX GT3), versus ≈+5,200/day under the old prize table. A race plays out in real time (≈23 s for a 3-lap sprint up to ≈68 s for 12 laps) and the result, prize and "why" stay hidden until the cars cross the line.

## ⏱️ The timer is proof
Time you log on a task with the focus timer fills its proof note automatically. Once it reaches **80% of the task's honest time**, the timer alone counts as proof: no file or link needed (even in strict mode). Task rows show progress like ⏱️ 32/60m.

## 🏢 The Honda ladder
Civic Si → Integra Type R → S2000 → Civic Type R → NSX → NSX Type S → NSX GT3 Evo. Each needs a driver level and coins (Garage → Showroom). Six upgrade paths (engine, wheels & tires, aero, brakes, forced induction, weight), each with real part names and a 💡 lesson — and each visible on the car. Every chassis has a tuning limit (Civic Si L3 … NSX L5); parts you buy carry over.

## The rules
| Mechanic | What it does |
|---|---|
| Proof | Note + file/link required. Same file can never be reused. Claude steward can reject it. Proof files upload to the Notion row. |
| Rewards | +25% if 24h early (+10% if 6h), +20% on danger days (Tue/Wed), ×streak up to ×2 |
| Pit crate | Every approved proof: coins, free part, streak shield, repair, or 3× jackpot. Rare guaranteed after 6 commons. |
| Miss | −penalty coins, −15% car, streak reset, rival heat +1, your consequence goes to the penalty box |
| Black flag | No racing while in debt, with unserved penalties, or car under 20% |
| Rust | Nothing finished for 2+ days → car loses 4%/day |
| Rival heat | Each miss makes every rival +3 faster. Each finish takes 1 back. |
| Redemption | Finish a missed task within 72h for half the penalty back |
| Extensions | Cost 30% of the penalty and cut the reward 15% (max 2). The only way a deadline moves. |
| Abandon | = taking the penalty (free only for 10 min after creating, for typos) |

Tune the numbers at the top of `app.py` and `nag.py`.
