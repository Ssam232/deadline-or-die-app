# 🏁 Deadline or Die

Prove it or pay for it. Every task has a deadline, a reward and a penalty.
Finish → submit proof → coins, XP, a pit crate → upgrade your car → race your procrastination rivals.
Miss → lose coins, wreck the car, lose your streak, feed the rivals, serve your real-world consequence.
Your phone won't let you forget.

```
app.py              Streamlit app (the game)
notion_store.py     Notion backend: save file + synced task table + proof uploads
nag.py              Phone nagger (runs in GitHub Actions every 30 min)
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
**Actions** tab → *Nag* → **Run workflow** to test. After that it runs every 30 min on its own (well inside GitHub's free private-repo minutes).

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

## 🏢 The Honda ladder
Civic Si → Integra Type R → S2000 → Civic Type R → NSX → NSX Type S → NSX GT3 Evo. Each needs a driver level and coins (Garage → Showroom). Parts upgrades carry over between cars.

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
