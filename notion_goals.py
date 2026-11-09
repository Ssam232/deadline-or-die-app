"""
🎯 Goals in Notion: a read-only mirror of the roadmap. No Streamlit imports.

Under the app's Notion page:
  🎯 Goals
    🎯 <goal>              one page per goal
      ## <stage>           every stage is a heading (sub-stages read "Parent › Child")
        ### <block>        every block is a sub-heading, with its date / deadline / status under it

The app owns these pages and rewrites a goal's page whenever that goal changes, so edits made there
are overwritten. Blocks are never read back.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

import roadmap as R
from notion_store import Notion, NotionError, clean_id, rt

ROOT_TITLE = "🎯 Goals"
NOTE = "Mirrored from Deadline or Die: each goal's stages are headings, its blocks sub-headings. " \
       "The app rewrites these pages when a goal changes, so edit goals in the app."
BATCH = 90


def _txt(s: str, color: str = "default", strike: bool = False, bold: bool = False) -> list:
    return [{"type": "text", "text": {"content": s[:1990]},
             "annotations": {"color": color, "strikethrough": strike, "bold": bold}}]


def _b(kind: str, rich: list, **extra) -> dict:
    return {"object": "block", "type": kind, kind: {"rich_text": rich, **extra}}


def _stage_order(g: dict) -> list[tuple[dict, str]]:
    """Depth-first: each stage followed by its sub-stages, labelled with its path."""
    out, by = [], {n["id"]: n for n in R.stages(g)}

    def walk(parent, path):
        for n in R.children(g, parent):
            if n["id"] in seen:
                continue
            seen.add(n["id"])
            label = " › ".join(path + [n["title"]])
            out.append((n, label))
            walk(n["id"], path + [n["title"]])
    seen: set = set()
    walk(None, [])
    out += [(n, n["title"]) for n in R.stages(g) if n["id"] not in seen and n.get("parent") not in by]
    return out


def _when(t: dict, tz) -> datetime:
    return R.block_at(t, tz) or datetime.fromisoformat(t.get("own_deadline") or t["deadline"])


NOTE_EMOJI = {"yellow": "📝", "blue": "💙", "green": "💚", "pink": "🩷", "grey": "🗒️"}


def _notes_on(g: dict, target: str) -> list[dict]:
    return [_b("callout", _txt(n["text"].strip()), icon={"type": "emoji", "emoji": NOTE_EMOJI.get(n.get("color"), "📝")})
            for n in R.notes(g) if (n.get("on") or "goal") == target]


def _block_lines(t: dict, tz, today: date, g: dict | None = None) -> list[dict]:
    st_ = t["status"]
    done = st_ in R.DONE
    icon = "✅ " if done else "💀 " if st_ == "failed" else ""
    out = [_b("heading_3", _txt(icon + t["title"], "gray" if done or st_ == "failed" else "default", strike=done))]
    line = R._fmt_block(t, tz)
    if st_ == "open":
        line += " · " + R._to_go(t, datetime.combine(today, datetime.min.time(), tz))
    else:
        line += " · " + {"done": "done", "redeemed": "redeemed", "failed": "missed"}.get(st_, st_)
    out.append(_b("paragraph", _txt(line, "gray")))
    if (t.get("details") or "").strip():
        out.append(_b("paragraph", _txt(t["details"].strip())))
    if g:
        out += _notes_on(g, "t_" + t["id"])
    return out


def goal_blocks(g: dict, tasks: list[dict], tz, today: date) -> list[dict]:
    gts = R.goal_tasks(g, tasks)
    d_all, n_all = R.progress(gts)
    head = f"{d_all}/{n_all} blocks done"
    if g.get("target"):
        tgt = date.fromisoformat(g["target"])
        head += f" · target {tgt:%a %b} {tgt.day}, {tgt.year}"
        if not g.get("claimed"):
            head += f" · {R.days_to_go(tgt, today)}"
    out = [_b("callout", _txt(head, bold=True), icon={"type": "emoji", "emoji": "🏆" if g.get("claimed") else "🏁"})]
    if (g.get("why") or "").strip():
        out.append(_b("quote", _txt("Why: " + g["why"].strip())))
    placed = {"goal"} | {"s_" + n["id"] for n in R.stages(g)} | {"t_" + t["id"] for t in gts}
    out += _notes_on(g, "goal") + [x for n in R.notes(g) if (n.get("on") or "goal") not in placed
                                   for x in _notes_on({"notes": [dict(n, on="goal")]}, "goal")]
    key = lambda t: _when(t, tz)  # noqa: E731
    known = {n["id"] for n in R.stages(g)}
    loose = sorted((t for t in gts if t.get("node") not in known), key=key)
    for n, label in _stage_order(g):
        mine = sorted((t for t in gts if t.get("node") == n["id"]), key=key)
        d, tot = R.progress(R.stage_tasks(g, tasks, n["id"]))
        full = tot and d == tot
        out.append(_b("heading_2", _txt(("✅ " if full else "") + label)))
        out.append(_b("paragraph", _txt(f"{d}/{tot} done" if tot else "No blocks yet", "gray")))
        out += _notes_on(g, "s_" + n["id"])
        for t in mine:
            out += _block_lines(t, tz, today, g)
    if loose:
        out.append(_b("heading_2", _txt("Straight to the goal" if R.stages(g) else "Blocks")))
        for t in loose:
            out += _block_lines(t, tz, today, g)
    if not gts and not R.stages(g) and not R.notes(g):
        out.append(_b("paragraph", _txt("No stages or blocks yet.", "gray")))
    return out


def _title(g: dict) -> str:
    return ("🏆 " if g.get("claimed") else "") + g["title"]


def sig(g: dict, tasks: list[dict], tz, today: date) -> str:
    body = json.dumps([_title(g), goal_blocks(g, tasks, tz, today)], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(body.encode()).hexdigest()[:16]


def wanted(goals: list[dict], tasks: list[dict], tz, today: date) -> dict:
    return {g["id"]: sig(g, tasks, tz, today) for g in goals}


def _pages(n: Notion, parent: str) -> dict:
    return {clean_id(b["id"]): (b.get("child_page") or {}).get("title", "")
            for b in n.children(parent) if b.get("type") == "child_page"}


def _root(n: Notion, parent: str, known: str | None) -> str:
    parent = clean_id(parent)
    pages = _pages(n, parent)
    if known and clean_id(known) in pages:
        return known
    for pid, title in pages.items():
        if title == ROOT_TITLE:
            return pid
    return n.req("POST", "/pages", json={
        "parent": {"type": "page_id", "page_id": parent}, "icon": {"type": "emoji", "emoji": "🎯"},
        "properties": {"title": {"title": rt(ROOT_TITLE)}},
        "children": [_b("callout", _txt(NOTE), icon={"type": "emoji", "emoji": "🔁"})]})["id"]


def _rewrite(n: Notion, page: str, blocks: list[dict]) -> None:
    for b in n.children(page):
        try:
            n.req("DELETE", f"/blocks/{b['id']}")
        except NotionError as e:
            if "404" not in str(e):
                raise
    for i in range(0, len(blocks), BATCH):
        n.req("PATCH", f"/blocks/{page}/children", json={"children": blocks[i:i + BATCH]})


def sync(n: Notion, parent: str, goals: list[dict], tasks: list[dict], known: dict, tz, today: date) -> dict:
    """Bring the 🎯 Goals pages in line with the app. `known` = {"_root": id, gid: {"page", "sig"}};
    returns the new map. Only goals whose content changed are rewritten."""
    known = dict(known or {})
    root = known["_root"] = _root(n, parent, known.get("_root"))
    pages = _pages(n, root)
    by_title = {t: pid for pid, t in pages.items()}
    live = set()
    for g in goals:
        gid, s = g["id"], sig(g, tasks, tz, today)
        live.add(gid)
        k = known.get(gid) or {}
        page = k.get("page") if k.get("page") and clean_id(k["page"]) in pages else None
        if page and k.get("sig") == s:
            continue
        title = _title(g)
        if not page:
            page = by_title.get(title) or by_title.get(g["title"])
        if page:
            n.req("PATCH", f"/pages/{page}", json={"properties": {"title": {"title": rt(title)}},
                                                    "icon": {"type": "emoji", "emoji": "🏆" if g.get("claimed") else "🎯"}})
        else:
            page = n.req("POST", "/pages", json={
                "parent": {"type": "page_id", "page_id": root},
                "icon": {"type": "emoji", "emoji": "🏆" if g.get("claimed") else "🎯"},
                "properties": {"title": {"title": rt(title)}}})["id"]
            pages[clean_id(page)] = title
        _rewrite(n, page, goal_blocks(g, tasks, tz, today))
        known[gid] = {"page": page, "sig": s}
    for gid in [k for k in known if k != "_root" and k not in live]:  # goal deleted in the app → its page goes
        page = (known.pop(gid) or {}).get("page")
        if page and clean_id(page) in pages:
            try:
                n.req("PATCH", f"/pages/{page}", json={"archived": True})
            except NotionError:
                pass
    return known
