"""
💰 What a task is worth — and how not to cheat it.

value = minutes × RATE × category weight
  Deep work pays most (it's what you avoid). Showing up pays a token (it's baseline).
Anti-inflation rules live in payout() so the app can't be farmed.
"""
from __future__ import annotations

import re

RATE = 0.75  # coins per honest minute at weight 1.0

CATEGORIES = {
    "deep": {"label": "🧠 Deep work", "weight": 1.5,
             "examples": "writing, analysis, coding, studying, lit review, thesis/paper work, lab work",
             "words": r"writ|draft|analy|casper|code|coding|debug|stud|revis|read|paper|thesis|manuscript|methods|results|"
                      r"discussion|intro|abstract|stats|figure|plot|lit review|literature|lab work|experiment|dissect|data|model|"
                      r"essay|chapter|proposal|grant|exam|problem set|pset|casper|mcat|application essay"},
    "pit": {"label": "🔧 Pit checks", "weight": 1.0,
            "examples": "inbox, emails, replies, texts, a call, booking, paying, printing, RSVPs (≤15 min, don't count "
                        "toward qualifying)",
            "words": r"\binbox|\bemails?\b|\be-mails?\b|\breply|\brespond|\btext\b|\btexts?\s|message|\bcall\b|"
                     r"\bbook\b|\bschedule\b|\bpay\b|\bsign\b|\bprint|\bupload|\bregister\b|\border\b|rsvp|"
                     r"\bconfirm|follow[ -]?up|\brenew"},
    "admin": {"label": "📨 Academic admin", "weight": 1.0,
              "examples": "forms, applications, prep for a meeting, organizing files, ethics paperwork",
              "words": r"form|submit|apply|application|prep|organi[sz]e|ethics|paperwork|admin|plan"},
    "health": {"label": "💪 Health & training", "weight": 0.8,
               "examples": "gym, taekwondo, run, meal prep, a real sleep schedule",
               "words": r"gym|lift|workout|training|taekwondo|tkd|go for a run|running|\b5k\b|cardio|stretch|meal prep|swim|walk|practice"},
    "life": {"label": "🧺 Life admin", "weight": 0.5,
             "examples": "haircut, groceries, laundry, dentist, bank, cleaning",
             "words": r"haircut|barber|grocer|laundry|clean|dentist|doctor|bank|car wash|oil change|pharmacy|"
                      r"tidy|dishes|errand|pay bill|rent"},
    "show": {"label": "🪑 Showing up", "weight": 0.3,
             "examples": "meetings, class, seminars, lab meeting, coaching a session",
             "words": r"meeting|class|lecture|seminar|attend|group meeting|lab meeting|office hours|"
                      r"coach|webinar|defen[cs]e|presentation day"},
}
MINUTES = [5, 10, 15, 30, 45, 60, 90, 120, 180, 240]
PIT_DEFAULT = 10             # a pit check's honest default
PIT_MAX = 15                 # chosen longer than this → it's real admin, not a pit check
INBOX_MAX = 10               # checking email/inbox is never more than 10 min
INBOX_RX = re.compile(r"\binbox|(check|clear|go through|answer)\w* (my |the |all )?e-?mails?|e-?mails? check", re.I)
LEAD_VERBS = [  # the first word says what kind of work it is better than any keyword later in the title
    ("admin", r"prep(are)?\b|make slides|slides for|plan\b|organi[sz]e"),
    ("deep", r"read\b|write|draft|analy[sz]e|code\b|debug|study|revise|edit\b|finish (the )?(paper|draft|chapter)"),
    ("pit", r"book|pay|call|e-?mail|reply|respond|text|message|rsvp|confirm|renew|print|sign|order|schedule|"
            r"register|upload|check (my |the )?(inbox|e-?mail)|clear (my |the )?inbox|follow[ -]?up"),
]
DAILY_PAID_MINUTES = 600     # beyond 10 claimed hours a day, tasks pay 25%
INSTANT_WINDOW_MIN = 10      # finished within 10 min of creating it → 25% (log it before you do it)
FILE_REQUIRED_FROM = 90      # tasks of 90+ min need an actual file, not just a link
TIMER_BONUS = 0.15           # +15% when the focus timer logged ≥ half the estimate


def guess_category(title: str) -> str:
    t = title.lower().strip()
    for key, rx in LEAD_VERBS:
        if re.match(rx, t):
            return key
    for key in ("show", "life", "health", "pit", "admin", "deep"):  # specific → general
        if re.search(CATEGORIES[key]["words"], t):
            return key
    return "admin"


def honest(title: str, category: str, minutes: int | None, chosen: bool = False) -> tuple[str, int]:
    """(category, minutes) without inflation. Pit checks default to 10 min, inbox/email caps at 10, and a quick item
    you deliberately size past 15 min is filed as admin instead (so a real 30-min call still counts as work)."""
    m = int(minutes or (PIT_DEFAULT if category == "pit" else 30))
    if category == "pit":
        if INBOX_RX.search(title or ""):
            return "pit", min(m, INBOX_MAX)
        if chosen and m > PIT_MAX:
            return "admin", m
        return "pit", min(m, PIT_MAX)
    return category, m


def counts_for_qualifying(t: dict) -> bool:
    """Pit checks are real but small — they don't count toward the mission's minimum honest minutes."""
    return t.get("category") != "pit"


def size_label(minutes: int) -> str:
    return "Quick" if minutes <= 30 else "Medium" if minutes <= 90 else "Big" if minutes <= 180 else "Boss"


def minutes_for_size(size: str | None) -> int:
    return {"Quick": 30, "Medium": 60, "Big": 120, "Boss": 240}.get(size or "", 60)


def value(category: str, minutes: int) -> dict:
    w = CATEGORIES.get(category, CATEGORIES["admin"])["weight"]
    reward = max(3, round(minutes * RATE * w))
    return {"reward": reward, "penalty": max(5, round(reward * 0.75)), "xp": max(2, round(minutes / 2 * w))}


def payout(base: int, t: dict, created, completed, paid_minutes_today: int, timed_minutes: float) -> tuple[float, list[str]]:
    """Multiplier on the reward plus human-readable reasons."""
    mult, why = 1.0, []
    est = t.get("minutes") or minutes_for_size(t.get("difficulty"))
    if (completed - created).total_seconds() < INSTANT_WINDOW_MIN * 60 and timed_minutes < est / 2:
        mult *= 0.25
        why.append("−75% logged-after-the-fact (add tasks *before* you do them)")
    if paid_minutes_today >= DAILY_PAID_MINUTES:
        mult *= 0.25
        why.append("−75% over today's 10h claimed-work cap")
    if timed_minutes >= est / 2:
        mult *= 1 + TIMER_BONUS
        why.append(f"+{int(TIMER_BONUS * 100)}% timer-verified ({int(timed_minutes)} min)")
    return mult, why


def guide_markdown() -> str:
    rows = "\n".join(
        f"| {c['label']} | ×{c['weight']} | {value(k, 60)['reward']} | {c['examples']} |"
        for k, c in CATEGORIES.items())
    return f"""**Value = minutes × category.** Be honest about minutes — the timer will show the truth.

| Category | Weight | 60 min pays | Examples |
|---|---|---|---|
{rows}

**Worth entering?** If it's something you'd *avoid* or *forget*, yes. Haircut: yes, but it pays like a haircut.
A meeting you'd attend anyway: only if you tend to skip or be late. Leisure (gaming, manga): never — that's what coins *buy*.

**Anti-inflation rules**
- Add it **before** you do it: finishing within {INSTANT_WINDOW_MIN} min of creating pays 25% (unless the timer ran).
- Over {DAILY_PAID_MINUTES // 60}h of claimed work in a day → extra tasks pay 25%.
- {FILE_REQUIRED_FROM}+ min tasks need a real file as proof (screenshot, doc, photo of the page).
- Size and category are locked once created. Missing still costs 75% of the value.
- Run the ⏱️ focus timer on it for **+{int(TIMER_BONUS * 100)}%** — it's your receipt.
"""
