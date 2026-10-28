"""
🗓️ Event → goal. A conference, talk, exam or submission on your board becomes a long-term goal with a prep plan
that works backwards from the date. Every prep step is a normal task (proof, coins, penalties) linked to the goal,
so finishing steps fills the goal's progress bar.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

# (days before the event, step, honest minutes, category)
KINDS = {
    "poster": ("🖼️ Conference poster", [
        (-21, "Pick the story: title, 3 key findings, figure list", 60, "deep"),
        (-17, "Make the figures", 120, "deep"),
        (-13, "Draft the poster: layout + text", 120, "deep"),
        (-10, "Send the draft to your supervisor for feedback", 15, "admin"),
        (-7, "Revise from feedback", 90, "deep"),
        (-5, "Final check + order the print", 30, "admin"),
        (-3, "Practice the 2-minute pitch out loud ×3", 30, "deep"),
        (-1, "Pick up the print, pack the tube, plan the trip", 30, "life"),
    ]),
    "talk": ("🎤 Talk / presentation", [
        (-14, "Outline: the one message + slide list", 45, "deep"),
        (-10, "Build the slides", 120, "deep"),
        (-7, "Send slides for feedback", 15, "admin"),
        (-5, "Revise the slides", 60, "deep"),
        (-3, "Full timed run-through", 45, "deep"),
        (-1, "Final run-through + backup copy on a USB", 30, "deep"),
    ]),
    "exam": ("📝 Exam / test", [
        (-14, "Topic list + gather materials", 45, "deep"),
        (-11, "Study block 1", 90, "deep"),
        (-8, "Study block 2", 90, "deep"),
        (-5, "Practice questions / past paper", 90, "deep"),
        (-3, "Review weak spots", 60, "deep"),
        (-1, "Light review + pack what you need", 30, "life"),
    ]),
    "submission": ("📤 Submission / application", [
        (-14, "Requirements checklist + outline", 45, "deep"),
        (-10, "First full draft", 120, "deep"),
        (-7, "Send the draft for feedback", 15, "admin"),
        (-4, "Revise", 90, "deep"),
        (-2, "Proofread + format", 45, "deep"),
        (-1, "Submit it (screenshot the confirmation)", 15, "admin"),
    ]),
    "generic": ("📌 Something else", [
        (-10, "Define what done looks like + list the steps", 30, "deep"),
        (-6, "First big chunk of the work", 90, "deep"),
        (-3, "Second chunk", 90, "deep"),
        (-1, "Final prep", 30, "life"),
    ]),
}

_GUESS = [
    ("poster", r"poster|conference|symposium|congress|research day|summit|\bconf\b|annual meeting|\bcsb\b|\bsfn\b"),
    ("talk", r"\btalk\b|present|seminar|defen[cs]e|pitch|lecture|journal club|lab meeting"),
    ("exam", r"exam|midterm|final|quiz|\btest\b|mcat|casper"),
    ("submission", r"deadline|\bdue\b|submit|application|abstract|grant|proposal|manuscript|report|assignment"),
]


def guess_kind(title: str) -> str:
    low = title.lower()
    return next((k for k, rx in _GUESS if re.search(rx, low)), "generic")


def plan(kind: str, event: date, today: date, label: str = "") -> list[dict]:
    """Steps with due dates working back from the event. Squeezed proportionally if the event is close."""
    steps = KINDS.get(kind, KINDS["generic"])[1]
    span = max(-off for off, *_ in steps)
    last = max(today, event - timedelta(days=1))
    room = (last - today).days
    tag = f" — {label[:40]}" if label else ""
    out = []
    for off, title, mins, cat in steps:
        if room >= span - 1:
            due = event + timedelta(days=off)
        else:  # not enough runway: keep the order, compress the gaps
            frac = (span + off) / (span - 1) if span > 1 else 1.0
            due = today + timedelta(days=round(frac * room))
        out.append({"title": title + tag, "due": due, "minutes": mins, "category": cat})
    return out
