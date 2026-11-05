"""
📄 Zotero reading list — papers from your "To Read" collection become one-tap deep-work tasks.

Needs ZOTERO_USER_ID + ZOTERO_API_KEY (zotero.org/settings/keys — give the key library read access,
plus write access if you want finished papers tagged "read" automatically).
"""
from __future__ import annotations

import requests

API = "https://api.zotero.org"
READ_TAG = "read"
SKIP_TYPES = {"attachment", "note", "annotation"}


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


def to_read(user: str, key: str, collection: str = "To Read", limit: int = 50) -> list[dict]:
    ck = find_collection(user, key, collection)
    if not ck:
        raise ZoteroError(f'No Zotero collection called "{collection}".')
    items = _get(f"/users/{user}/collections/{ck}/items/top", key, {"limit": limit, "sort": "dateAdded", "direction": "asc"})
    out = []
    for it in items:
        d = it.get("data", {})
        if d.get("itemType") in SKIP_TYPES or any(t.get("tag") == READ_TAG for t in d.get("tags", [])):
            continue
        authors = [c.get("lastName") or c.get("name", "") for c in d.get("creators", []) if c.get("creatorType") == "author"]
        who = (authors[0] + (" et al." if len(authors) > 1 else "")) if authors else ""
        year = (d.get("date") or "")[:4]
        out.append({"key": it["key"], "title": d.get("title") or "(untitled)", "who": who, "year": year,
                    "url": d.get("url") or f"https://www.zotero.org/users/{user}/items/{it['key']}"})
    return out


def label(p: dict) -> str:
    meta = ", ".join(x for x in (p["who"], p["year"]) if x)
    return p["title"][:90] + (f" ({meta})" if meta else "")


def mark_read(user: str, key: str, item_key: str) -> None:
    """Adds the 'read' tag. Best-effort: needs a key with write access."""
    r = requests.get(f"{API}/users/{user}/items/{item_key}", headers=_h(key), timeout=20)
    if r.status_code != 200:
        raise ZoteroError(f"Zotero {r.status_code}")
    it = r.json()
    tags = it["data"].get("tags", [])
    if any(t.get("tag") == READ_TAG for t in tags):
        return
    r = requests.patch(f"{API}/users/{user}/items/{item_key}",
                       headers={**_h(key), "If-Unmodified-Since-Version": str(it["version"])},
                       json={"tags": tags + [{"tag": READ_TAG}]}, timeout=20)
    if r.status_code not in (200, 204):
        raise ZoteroError(f"Zotero tag failed {r.status_code}: {r.text[:120]}")


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
