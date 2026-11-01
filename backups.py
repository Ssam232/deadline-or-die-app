"""
🗄️ Rolling backups of your game save, kept in Notion next to the save itself.

A snapshot is taken (in the background) the first time each day the app is about to settle anything (penalties,
streaks), before a restore/reset, and when you ask for one. The newest KEEP stay; older ones go to Notion's trash.
Each backup is a small page under "🗄️ Backups (auto)" holding the save as JSON, so a lost tick or journal entry
can be brought back from Settings → Backup.
"""
from __future__ import annotations

import json
from datetime import datetime

from notion_store import Notion, clean_id, load_json, plain, save_json, rt

ROOT_TITLE = "🗄️ Backups (auto)"
KEEP = 14


def _root(n: Notion, parent: str) -> str:
    for b in n.children(clean_id(parent)):
        if b.get("type") == "child_page" and (b.get("child_page") or {}).get("title") == ROOT_TITLE:
            return b["id"]
    return n.req("POST", "/pages", json={
        "parent": {"type": "page_id", "page_id": clean_id(parent)}, "icon": {"type": "emoji", "emoji": "🗄️"},
        "properties": {"title": {"title": rt(ROOT_TITLE)}},
        "children": [{"object": "block", "type": "callout", "callout": {
            "rich_text": rt("Automatic copies of your game save. Restore one from the app: Settings → Backup."),
            "icon": {"type": "emoji", "emoji": "ℹ️"}}}]})["id"]


def listing(n: Notion, parent: str) -> list[dict]:
    """Newest first: [{"id", "title"}]."""
    pages = [{"id": b["id"], "title": (b.get("child_page") or {}).get("title", "")}
             for b in n.children(_root(n, parent)) if b.get("type") == "child_page"]
    return sorted(pages, key=lambda p: p["title"], reverse=True)


def snapshot(n: Notion, parent: str, state_json: str, label: str, at: datetime) -> str:
    root = _root(n, parent)
    title = f"{at:%Y-%m-%d %H:%M} · {label}"
    pid = n.req("POST", "/pages", json={"parent": {"type": "page_id", "page_id": root},
                                         "properties": {"title": {"title": rt(title)}}})["id"]
    save_json(n, pid, json.loads(state_json))
    for old in listing(n, parent)[KEEP:]:
        try:
            n.req("PATCH", f"/pages/{old['id']}", json={"archived": True})
        except Exception:  # noqa: BLE001
            pass
    return pid


def load(n: Notion, page_id: str) -> dict | None:
    return load_json(n, page_id)
