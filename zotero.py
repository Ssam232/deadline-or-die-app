"""
📄 Zotero reading list — papers from your "To Read" collection become one-tap deep-work tasks, and the Reading list tab
tracks each one as to read, reading, read or dropped. Zotero holds that status as a tag, so it stays your record.

Needs ZOTERO_USER_ID + ZOTERO_API_KEY (zotero.org/settings/keys — give the key library read access,
plus write access if you want finished papers tagged "read" automatically).
"""
from __future__ import annotations

import os
import re

import requests

API = os.getenv("ZOTERO_API_BASE", "https://api.zotero.org")
READ_TAG = "read"
READING_TAG = "reading"
DROPPED_TAG = "dropped"
STATUS_TAGS = (READ_TAG, READING_TAG, DROPPED_TAG)
SKIP_TYPES = {"attachment", "note", "annotation"}
LEVELS = {"A": "Foundational", "B": "Core", "C": "Specialized", "D": "Niche"}
_ORDER = re.compile(r"^Read order:\s*([A-D])(\d+)", re.M | re.I)


class ZoteroError(RuntimeError):
    pass


def _h(key: str) -> dict:
    return {"Zotero-API-Key": key, "Zotero-API-Version": "3"}


def _get(path: str, key: str, params: dict | None = None):
    r = requests.get(API + path, headers=_h(key), params=params or {}, timeout=20)
    if r.status_code != 200:
        raise ZoteroError(f"Zotero {r.status_code}: {r.text[:160]}")
    return r.json()


def find_collection(user: str, key: str, name: str) -> str | None:
    start = 0
    while True:
        cols = _get(f"/users/{user}/collections", key, {"limit": 100, "start": start})
        for c in cols:
            if c["data"]["name"].strip().lower() == name.strip().lower():
                return c["key"]
        if len(cols) < 100:
            return None
        start += 100


def _status(tags: list[dict]) -> str:
    names = {t.get("tag") for t in tags}
    return next((t for t in (READ_TAG, DROPPED_TAG, READING_TAG) if t in names), "unread")


def reading_list(user: str, key: str, collection: str = "To Read") -> list[dict]:
    """Every paper in the collection in read order, whatever its status. Papers with no order come last, oldest first."""
    ck = find_collection(user, key, collection)
    if not ck:
        raise ZoteroError(f'No Zotero collection called "{collection}".')
    out, start = [], 0
    while True:
        items = _get(f"/users/{user}/collections/{ck}/items/top", key,
                     {"limit": 100, "start": start, "sort": "dateAdded", "direction": "asc"})
        for it in items:
            d = it.get("data", {})
            if d.get("itemType") in SKIP_TYPES:
                continue
            authors = [c.get("lastName") or c.get("name", "") for c in d.get("creators", []) if c.get("creatorType") == "author"]
            who = (authors[0] + (" et al." if len(authors) > 1 else "")) if authors else ""
            m = _ORDER.search(d.get("extra") or "")
            out.append({"key": it["key"], "title": d.get("title") or "(untitled)", "who": who,
                        "year": (d.get("date") or "")[:4], "journal": d.get("publicationTitle") or d.get("websiteTitle") or "",
                        "url": d.get("url") or f"https://www.zotero.org/users/{user}/items/{it['key']}",
                        "status": _status(d.get("tags", [])),
                        "order": f"{m[1].upper()}{int(m[2]):02d}" if m else "", "level": LEVELS.get(m[1].upper()) if m else None})
        if len(items) < 100:
            break
        start += 100
    out.sort(key=lambda p: p["order"] or "~")  # stable: unordered papers keep their oldest-first order at the end
    return out


def to_read(user: str, key: str, collection: str = "To Read", limit: int = 50) -> list[dict]:
    """What's still ahead of you, in read order. Papers you've read or dropped stay out of suggestions."""
    return [p for p in reading_list(user, key, collection) if p["status"] in ("unread", READING_TAG)][:limit]


def label(p: dict) -> str:
    meta = ", ".join(x for x in (p["who"], p["year"]) if x)
    return p["title"][:90] + (f" ({meta})" if meta else "")


def set_status(user: str, key: str, item_key: str, status: str) -> None:
    """Sets one paper to unread, reading, read or dropped. Only the status tags change. Needs a key with write access."""
    if status not in ("unread", *STATUS_TAGS):
        raise ValueError(status)
    for attempt in (1, 2):
        r = requests.get(f"{API}/users/{user}/items/{item_key}", headers=_h(key), timeout=20)
        if r.status_code != 200:
            raise ZoteroError(f"Zotero {r.status_code}")
        it = r.json()
        old = it["data"].get("tags", [])
        tags = [t for t in old if t.get("tag") not in STATUS_TAGS] + ([{"tag": status}] if status != "unread" else [])
        if tags == old:
            return
        r = requests.patch(f"{API}/users/{user}/items/{item_key}",
                           headers={**_h(key), "If-Unmodified-Since-Version": str(it["version"])},
                           json={"tags": tags}, timeout=20)
        if r.status_code in (200, 204):
            return
        if r.status_code != 412 or attempt == 2:  # 412: it changed in Zotero since we read it, so read it again once
            detail = "the key needs write access" if r.status_code == 403 else r.text[:120]
            raise ZoteroError(f"Zotero couldn't save that ({r.status_code}): {detail}")


def mark_read(user: str, key: str, item_key: str) -> None:
    """Best-effort: needs a key with write access."""
    set_status(user, key, item_key, READ_TAG)


def health(user: str, key: str, collection: str = "To Read") -> str:
    """One line for the health check: is the key valid and for this user, can it write (to tag papers read), is the
    reading-list collection there, how many papers. Counts only."""
    user = str(user).strip()
    if not user.isdigit():
        return "ZOTERO_USER_ID isn't a number: use the numeric userID from zotero.org/settings/keys, not the username"
    r = requests.get(f"{API}/keys/current", headers=_h(key.strip()), timeout=20)
    if r.status_code != 200:
        return f"API key rejected (HTTP {r.status_code}): check ZOTERO_API_KEY"
    k = r.json()
    if str(k.get("userID")) != user:
        return "key works but belongs to a different user than ZOTERO_USER_ID"
    lib = ((k.get("access") or {}).get("user") or {})
    parts = ["key ok", "read " + ("yes" if lib.get("library") else "NO"),
             "write " + ("yes" if lib.get("write") else "no (papers can't be tagged read)")]
    try:
        papers = to_read(user, key.strip(), collection, limit=100)
        parts.append(f'"{collection}" found · {len(papers)} paper(s)')
    except ZoteroError as e:
        parts.append(str(e))
    return " · ".join(parts)
