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
FACETS = ("question", "subject", "species", "sex", "type")  # Zotero tags written as "subject:Diet and muscle"
_ORDER = re.compile(r"^Read order:\s*([A-D])(\d+)", re.M | re.I)
_LEFTOVER = re.compile(r"^\s*\((Foundational|Core|Specialized|Niche)\)\s*$", re.I)


class ZoteroError(RuntimeError):
    pass


def _h(key: str) -> dict:
    return {"Zotero-API-Key": key, "Zotero-API-Version": "3"}


def _get(path: str, key: str, params: dict | None = None):
    r = requests.get(API + path, headers=_h(key), params=params or {}, timeout=20)
    if r.status_code != 200:
        raise ZoteroError(f"Zotero {r.status_code}: {r.text[:160]}")
    return r.json()


def _collections(user: str, key: str) -> list[dict]:
    out, start = [], 0
    while True:
        cols = _get(f"/users/{user}/collections", key, {"limit": 100, "start": start})
        out += cols
        if len(cols) < 100:
            return out
        start += 100


def find_collection(user: str, key: str, name: str) -> str | None:
    for c in _collections(user, key):
        if c["data"]["name"].strip().lower() == name.strip().lower():
            return c["key"]
    return None


def status_folders(user: str, key: str, collection: str = "To Read") -> dict | None:
    """The "To Read" collection and the "Read" and "Dropped" folders beside it under the same parent.
    None if the library isn't arranged that way, in which case a paper's status is only its tag."""
    cols = _collections(user, key)
    me = next((c for c in cols if c["data"]["name"].strip().lower() == collection.strip().lower()), None)
    parent = me and me["data"].get("parentCollection")
    if not parent:
        return None
    beside = {c["data"]["name"].strip().lower(): c["key"] for c in cols if c["data"].get("parentCollection") == parent}
    if "read" not in beside or "dropped" not in beside:
        return None
    return {"unread": me["key"], "reading": me["key"], "read": beside["read"], "dropped": beside["dropped"]}


def _status(tags: list[dict]) -> str:
    names = {t.get("tag") for t in tags}
    return next((t for t in (READ_TAG, DROPPED_TAG, READING_TAG) if t in names), "unread")


def _facets(tags: list[dict]) -> dict:
    out = {f: [] for f in FACETS}
    for t in tags:
        name, _, value = (t.get("tag") or "").partition(":")
        if name in out and value.strip():
            out[name].append(value.strip())
    return out


def _folder_items(user: str, key: str, folder: str):
    start = 0
    while True:
        items = _get(f"/users/{user}/collections/{folder}/items/top", key,
                     {"limit": 100, "start": start, "sort": "dateAdded", "direction": "asc"})
        yield from items
        if len(items) < 100:
            return
        start += 100


def reading_list(user: str, key: str, collection: str = "To Read") -> list[dict]:
    """Every paper in the collection in read order, whatever its status. Papers with no order come last, oldest first."""
    ck = find_collection(user, key, collection)
    if not ck:
        raise ZoteroError(f'No Zotero collection called "{collection}".')
    folders = status_folders(user, key, collection)
    keys = list(dict.fromkeys(folders.values())) if folders else [ck]
    out, seen = [], set()
    for it in (it for folder in keys for it in _folder_items(user, key, folder)):
        d = it.get("data", {})
        if d.get("itemType") in SKIP_TYPES or it["key"] in seen:
            continue
        seen.add(it["key"])
        who = who_of(d.get("creators", []))
        m = _ORDER.search(d.get("extra") or "")
        out.append({"key": it["key"], "title": d.get("title") or "(untitled)", "who": who,
                    "year": (d.get("date") or "")[:4], "journal": d.get("publicationTitle") or d.get("websiteTitle") or "",
                    "url": d.get("url") or f"https://www.zotero.org/users/{user}/items/{it['key']}",
                    "status": _status(d.get("tags", [])), "facets": _facets(d.get("tags", [])),
                    "needs_check": any(t.get("tag") == "needs-check" for t in d.get("tags", [])),
                    "order": f"{m[1].upper()}{int(m[2]):02d}" if m else "", "level": LEVELS.get(m[1].upper()) if m else None})
    out.sort(key=lambda p: p["order"] or "~")  # stable: unordered papers keep their oldest-first order at the end
    rank_papers(out)
    return out


def rank_papers(papers: list[dict]) -> None:
    """Absolute rank (1 = read next) for papers still ahead; read and dropped papers get None. No AI, recomputed on
    every load, so it moves as you read: what you're reading now comes first, levels keep foundational → niche, and
    inside a level a paper whose questions you've read least about moves up (ties keep the A01-style read order)."""
    done = {}
    for p in papers:
        if p["status"] == READ_TAG:
            for q in p["facets"]["question"]:
                done[q] = done.get(q, 0) + 1
    ahead = [p for p in papers if p["status"] in ("unread", READING_TAG)]
    ahead.sort(key=lambda p: (p["status"] != READING_TAG, p["order"][:1] or "~",
                              min((done.get(q, 0) for q in p["facets"]["question"]), default=9999), p["order"] or "~"))
    for p in papers:
        p["rank"] = None
    for n, p in enumerate(ahead, 1):
        p["rank"] = n


def to_read(user: str, key: str, collection: str = "To Read", limit: int = 50) -> list[dict]:
    """What's still ahead of you, in read order. Papers you've read or dropped stay out of suggestions."""
    return sorted((p for p in reading_list(user, key, collection) if p["rank"]), key=lambda p: p["rank"])[:limit]


def who_of(creators: list[dict]) -> str:
    """'Smith et al.' (or 'Smith' for one author). Falls back to any creator when none is tagged as an author."""
    people = [c for c in creators if c.get("creatorType") == "author"] or list(creators)
    names = [(c.get("lastName") or c.get("name") or "").strip() for c in people]
    names = [x for x in names if x]
    return (names[0] + (" et al." if len(names) > 1 else "")) if names else ""


def label(p: dict) -> str:
    meta = ", ".join(x for x in (p["who"], p["year"]) if x)
    return p["title"][:90] + (f" ({meta})" if meta else "")


def set_status(user: str, key: str, item_key: str, status: str, collection: str = "To Read") -> None:
    """Sets one paper to unread, reading, read or dropped: changes its status tag and moves it to the matching
    folder (To Read, Read or Dropped), leaving its other tags and collections alone. Needs a key with write access."""
    if status not in ("unread", *STATUS_TAGS):
        raise ValueError(status)
    folders = status_folders(user, key, collection)
    for attempt in (1, 2):
        r = requests.get(f"{API}/users/{user}/items/{item_key}", headers=_h(key), timeout=20)
        if r.status_code != 200:
            raise ZoteroError(f"Zotero {r.status_code}")
        it = r.json()
        old = it["data"].get("tags", [])
        tags = [t for t in old if t.get("tag") not in STATUS_TAGS] + ([{"tag": status}] if status != "unread" else [])
        body = {"tags": tags}
        if folders:
            colls = it["data"].get("collections", [])
            moved = [c for c in colls if c not in folders.values()] + [folders[status]]
            if set(moved) != set(colls):
                body["collections"] = moved
        if tags == old and "collections" not in body:
            return
        r = requests.patch(f"{API}/users/{user}/items/{item_key}",
                           headers={**_h(key), "If-Unmodified-Since-Version": str(it["version"])},
                           json=body, timeout=20)
        if r.status_code in (200, 204):
            return
        if r.status_code != 412 or attempt == 2:  # 412: it changed in Zotero since we read it, so read it again once
            detail = "the key needs write access" if r.status_code == 403 else r.text[:120]
            raise ZoteroError(f"Zotero couldn't save that ({r.status_code}): {detail}")


def set_order(user: str, key: str, item_key: str, level: str, num: int) -> str:
    """Writes 'Read order: A03' into the paper's Extra field (replacing any old one, keeping the rest). Needs write
    access. Returns the new order label."""
    r = requests.get(f"{API}/users/{user}/items/{item_key}", headers=_h(key), timeout=20)
    if r.status_code != 200:
        raise ZoteroError(f"Zotero {r.status_code}")
    it = r.json()
    lab = f"{level.upper()}{int(num):02d}"
    extra = "\n".join(ln for ln in (it["data"].get("extra") or "").splitlines()
                      if ln.strip() and not _ORDER.match(ln) and not _LEFTOVER.match(ln))
    extra = (f"Read order: {lab}\n" + extra).strip("\n")
    r = requests.patch(f"{API}/users/{user}/items/{item_key}",
                       headers={**_h(key), "If-Unmodified-Since-Version": str(it["version"])},
                       json={"extra": extra}, timeout=20)
    if r.status_code not in (200, 204):
        raise ZoteroError(f"Zotero {r.status_code}: needs a key with write access")
    return lab


def mark_read(user: str, key: str, item_key: str, collection: str = "To Read") -> None:
    """Best-effort: needs a key with write access."""
    set_status(user, key, item_key, READ_TAG, collection)


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
