"""
📓 Your Notion journal (the calendar database you already keep) ↔ the app's evening journal.

  • Template: the evening form follows your journal template (When are you writing this? · What happened today?
    · What bothered you? · How can you make tomorrow better? · What are you grateful for? · Quote/picture/song lyric
    of the day), plus the app's one extra: the win. If you change the template, "Re-read journal template" picks up
    its headings (headings and bold lines only, so a filled-in entry's answers are never read as prompts).
  • Write: each evening entry becomes that day's page in the journal database (title + date), laid out like your
    template: prompt → your answer, plus a small header (mood, energy, focus, finishes). If you already started a page
    for that day yourself, the app adds its section to the end of it instead of making a second page.
  • Edits in the app replace the app's own section; anything you wrote yourself in Notion is never touched.
"""
from __future__ import annotations

import re
from datetime import date

from notion_store import Notion, clean_id, plain, rt

PROMPT_TYPES = ("heading_1", "heading_2", "heading_3")
MAX_PROMPTS = 8
APP_MARK = "📓 Deadline or Die"

# Your journal template's sections (in its order), each mapped to what the app keeps track of.
#   key: (question, hint, words that mean a template heading is asking this)
CORE = {
    "when": ("🕰️ When are you writing this?", "", r"when are you writing|written at|what time"),
    "happened": ("📖 What happened today?", "What happened during the day", r"happen|how was (the|your) day|recap"),
    "win": ("🏁 The win: best thing you got done?", "Even small counts: 'sent the ethics form'",
            r"\bwin\b|went well|accompl|proud|achiev|highlight"),
    "blocker": ("🌧️ What bothered you?", "Why did it bother you? Does it seem true? Are you measuring it by the "
                "right metric?", r"bother|in the way|block|struggl|distract|challeng|upset|frustrat"),
    "tomorrow": ("🌅 How can you make tomorrow better?", "Your first line becomes tomorrow's one thing",
                 r"tomorrow|next day|intention|priorit"),
    "grateful": ("🙏 What are you grateful for?", "One per line: a person, a moment, something small",
                 r"grate|thank|appreciat|bless"),
    "vibe": ("🎵 Quote / picture / song lyric of the day", "Nothing fancy, just a vibe",
             r"quote|lyric|song|picture|vibe"),
    "note": ("📝 Anything else on your mind?", "Optional", r"\belse\b|on your mind|notes?\b|thoughts"),
}
TEMPLATE_ORDER = ["when", "happened", "win", "blocker", "tomorrow", "grateful", "vibe"]  # your journal + the win
MATCH_ORDER = ["when", "tomorrow", "grateful", "vibe", "blocker", "win", "happened", "note"]  # most specific first
AUTO = {"when"}   # the app fills these in itself (the time you saved it)


def _txt(b: dict) -> str:
    t = b.get("type", "")
    return plain((b.get(t) or {}).get("rich_text")).strip()


def _is_prompt(b: dict) -> bool:
    t, text = b.get("type", ""), _txt(b)
    if not text or len(text) > 140 or text.startswith(APP_MARK):
        return False
    if t in PROMPT_TYPES:
        return True
    if t in ("paragraph", "callout", "quote", "toggle"):
        rts = (b.get(t) or {}).get("rich_text") or []
        bold = rts and all((r.get("annotations") or {}).get("bold") for r in rts if (r.get("plain_text") or "").strip())
        return bool(bold)  # never plain lines: in a filled-in entry those are your answers
    return False


def detect(n: Notion, db_id: str) -> dict:
    db = n.req("GET", f"/databases/{clean_id(db_id)}")
    m = {"db": db["id"], "name": plain(db.get("title")) or "(untitled)", "title": None, "date": None,
         "mood": None, "mood_type": None}
    for name, p in db.get("properties", {}).items():
        t = p.get("type")
        if t == "title":
            m["title"] = name
        elif t == "date" and not m["date"]:
            m["date"] = name
        elif re.search(r"mood|feel", name, re.I) and t in ("select", "number", "rich_text") and not m["mood"]:
            m["mood"], m["mood_type"] = name, t
    return m


def read_prompts(n: Notion, m: dict) -> list[str]:
    """Prompts from your newest journal entry that isn't the app's own."""
    body = {"page_size": 10, "sorts": ([{"property": m["date"], "direction": "descending"}] if m["date"]
                                       else [{"timestamp": "created_time", "direction": "descending"}])}
    for page in n.req("POST", f"/databases/{m['db']}/query", json=body).get("results", [])[:6]:
        out = []
        for b in n.children(page["id"]):
            if _txt(b).startswith(APP_MARK):
                break  # the app's section starts here: don't learn from our own output
            if _is_prompt(b):
                p = re.sub(r"\s+", " ", _txt(b)).strip(" :")
                if p and p not in out:
                    out.append(p)
        if out:
            return out[:MAX_PROMPTS]
    return []


def core_of(prompt: str) -> str | None:
    for k in MATCH_ORDER:
        if re.search(CORE[k][2], prompt, re.I):
            return k
    return None


def merged_questions(prompts: list[str]) -> list[tuple[str, str, str]]:
    """[(key, question, hint)] to ask tonight: your template's sections in its order and words, plus the win
    (it feeds the weekly recap) if the template doesn't already ask it. Auto-filled sections ("when are you
    writing this?") aren't asked. Never the same thing twice."""
    out, covered = [], set()
    for p in prompts or [CORE[k][0] for k in TEMPLATE_ORDER]:
        k = core_of(p)
        if k in AUTO:
            covered.add(k)
            continue
        if k and k not in covered:
            covered.add(k)
            out.append((k, CORE[k][0] if not prompts else _emoji(k) + " " + p, CORE[k][1]))
        elif not k:
            out.append(("t:" + re.sub(r"[^a-z0-9]+", "-", p.lower()).strip("-")[:40], p, ""))
    if "win" not in covered:
        at = next((i + 1 for i, (k, _, _) in enumerate(out) if k == "happened"), len(out))
        out.insert(at, ("win", CORE["win"][0], CORE["win"][1]))
    return out


def _emoji(k: str) -> str:
    return CORE[k][0].split(" ", 1)[0]


# ── writing the day ──
def _para(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(text)}}


def _h3(text: str) -> dict:
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": rt(text)}}


def blocks_for(entry: dict, questions: list[tuple[str, str, str]], header: str, when: str = "") -> list[dict]:
    out = [{"object": "block", "type": "divider", "divider": {}},
           {"object": "block", "type": "callout", "callout": {"rich_text": rt(f"{APP_MARK} · {header}"),
                                                             "icon": {"type": "emoji", "emoji": "📓"}}}]
    if when:
        out += [_h3(CORE["when"][0]), _para(when)]
    for k, q, _ in questions:
        a = (entry.get(k) or "").strip()
        if not a:
            continue
        out.append(_h3(q))
        lines = [x.strip(" -•") for x in a.splitlines() if x.strip()]
        if len(lines) > 1:
            out += [{"object": "block", "type": "bulleted_list_item",
                     "bulleted_list_item": {"rich_text": rt(x)}} for x in lines]
        else:
            out.append(_para(a))
    return out


def _page_props(m: dict, d: date, mood_word: str) -> dict:
    props = {m["title"]: {"title": rt(f"{d:%a %b} {d.day}")}}
    if m["date"]:
        props[m["date"]] = {"date": {"start": d.isoformat()}}
    if m["mood"] and mood_word:
        props[m["mood"]] = ({"select": {"name": mood_word}} if m["mood_type"] == "select" else
                            {"rich_text": rt(mood_word)} if m["mood_type"] == "rich_text" else {})
        if not props[m["mood"]]:
            props.pop(m["mood"])
    return props


def find_day(n: Notion, m: dict, d: date) -> str | None:
    if not m["date"]:
        return None
    res = n.req("POST", f"/databases/{m['db']}/query",
                json={"filter": {"property": m["date"], "date": {"equals": d.isoformat()}}, "page_size": 5})
    return (res.get("results") or [{}])[0].get("id")


def write_day(n: Notion, m: dict, d: date, pm: dict, questions, header: str, mood_word: str = "",
              when: str = "") -> dict:
    """Create / update the day's entry. Returns the sync fields to keep on pm (page id + the app's block ids)."""
    page = pm.get("notion_page")
    if page:  # replace the app's previous section, leave everything else alone
        for bid in pm.get("notion_blocks") or []:
            try:
                n.req("DELETE", f"/blocks/{bid}")
            except Exception:  # noqa: BLE001 — already gone is fine
                pass
    else:
        page = find_day(n, m, d)
        if not page:
            page = n.req("POST", "/pages", json={"parent": {"database_id": m["db"]},
                                                 "properties": _page_props(m, d, mood_word),
                                                 "icon": {"type": "emoji", "emoji": "📓"}})["id"]
    blocks = blocks_for(pm, questions, header, when)
    res = n.req("PATCH", f"/blocks/{page}/children", json={"children": blocks})
    return {"notion_page": page, "notion_blocks": [b["id"] for b in res.get("results", [])]}


def read_entries(n: Notion, m: dict, since: date, skip_edited: dict | None = None) -> list[dict]:
    """Day pages you wrote straight into the Notion journal (on/after `since`): your answers under each prompt,
    matched to the app's questions. Stops at the app's own section. `skip_edited` {page id: last_edited_time}
    skips pages unchanged since the last import. Returns [{date, page, edited, created, answers, mood_word}]."""
    if not m["date"]:
        return []
    out, skip_edited = [], skip_edited or {}
    body = {"filter": {"property": m["date"], "date": {"on_or_after": since.isoformat()}}, "page_size": 20}
    for page in n.req("POST", f"/databases/{m['db']}/query", json=body).get("results", []):
        start = ((page.get("properties", {}).get(m["date"]) or {}).get("date") or {}).get("start")
        if not start or skip_edited.get(page["id"]) == page.get("last_edited_time"):
            continue
        answers, cur, extra = {}, None, []
        for b in n.children(page["id"]):
            text = _txt(b)
            if text.startswith(APP_MARK):
                break  # the app's own section: not yours
            if _is_prompt(b):
                cur = core_of(text) or ("note:" + re.sub(r"\s+", " ", text).strip(" :"))
                continue
            if not text:
                continue
            if cur and not cur.startswith("note:"):
                answers[cur] = (answers.get(cur, "") + "\n" + text).strip()
            else:
                extra.append((f"{cur[5:]}: " if cur else "") + text)
        if extra:
            answers["note"] = (answers.get("note", "") + "\n" + "\n".join(extra)).strip()
        answers.pop("when", None)
        if sum(len(v) for v in answers.values()) < 15:
            continue  # an empty template, not an entry
        mood_word = ""
        if m["mood"]:
            p = page["properties"].get(m["mood"]) or {}
            mood_word = ((p.get("select") or {}).get("name") or plain(p.get("rich_text")) or
                         (str(p.get("number")) if p.get("number") is not None else "")).strip().lower()
        out.append({"date": date.fromisoformat(start[:10]), "page": page["id"], "edited": page.get("last_edited_time"),
                    "created": page.get("created_time"), "answers": answers, "mood_word": mood_word})
    return out
