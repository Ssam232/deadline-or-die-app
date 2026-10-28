"""
Notion as Deadline or Die's backend. No Streamlit imports — shared by app.py and nag.py.

Under the page you share with your integration, this creates:
  🏁 Deadline or Die — Tasks       (inline database, synced both ways with the app)
  🏁 Deadline or Die — Save file   (the game's JSON save, stored in code blocks)
  📣 Deadline or Die — Nagger      (the phone nagger's memory of what it already sent)
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime

import requests

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
TASKS_DB_TITLE = "🏁 Deadline or Die — Tasks"
SAVE_PAGE_TITLE = "🏁 Deadline or Die — Save file"
NAG_PAGE_TITLE = "📣 Deadline or Die — Nagger"

STATUS = {"open": "Open", "done": "Done", "failed": "Failed", "redeemed": "Redeemed"}
STATUS_COLORS = {"Open": "blue", "Done": "green", "Failed": "red", "Redeemed": "yellow"}
SIZES = {"Quick": "gray", "Medium": "blue", "Big": "orange", "Boss": "red"}
CHUNK, BLOCK_ITEMS = 2000, 100


class NotionError(RuntimeError):
    pass


def clean_id(s: str) -> str:
    """Accepts a raw ID, a dashed UUID, or a full Notion link like notion.so/My-Page-Title-<32 hex>?v=…"""
    s = (s or "").strip().split("?")[0].split("#")[0]
    dashed = re.findall(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", s)
    if dashed:
        return dashed[-1].replace("-", "")
    m = re.findall(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])", s)
    return m[-1] if m else s


def rt(s) -> list:
    s = "" if s is None else str(s)
    return [{"type": "text", "text": {"content": s[i:i + CHUNK]}} for i in range(0, min(len(s), 6000), CHUNK)]


def plain(items: list) -> str:
    return "".join(x.get("plain_text") or x.get("text", {}).get("content", "") for x in items or [])


class Notion:
    def __init__(self, token: str, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self.h = {"Authorization": f"Bearer {token}", "Notion-Version": VERSION, "Content-Type": "application/json"}

    def req(self, method: str, path: str, **kw) -> dict:
        for attempt in range(4):
            r = self.s.request(method, API + path, headers=self.h, timeout=30, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(float(r.headers.get("Retry-After", 1 + attempt)))
                continue
            if r.status_code >= 400:
                try:
                    msg = r.json().get("message")
                except Exception:
                    msg = r.text[:200]
                raise NotionError(f"Notion {r.status_code}: {msg}")
            return r.json() if r.content else {}
        raise NotionError("Notion is rate-limiting; try again in a minute.")

    def children(self, block_id: str) -> list:
        out, cur = [], None
        while True:
            q = "?page_size=100" + (f"&start_cursor={cur}" if cur else "")
            d = self.req("GET", f"/blocks/{block_id}/children{q}")
            out += d.get("results", [])
            if not d.get("has_more"):
                return out
            cur = d.get("next_cursor")

    def query(self, db_id: str, body: dict | None = None) -> list:
        out, cur = [], None
        while True:
            b = dict(body or {}, page_size=100)
            if cur:
                b["start_cursor"] = cur
            d = self.req("POST", f"/databases/{db_id}/query", json=b)
            out += d.get("results", [])
            if not d.get("has_more"):
                return out
            cur = d.get("next_cursor")


# ─────────────── workspace bootstrap ───────────────
def _tasks_db_schema(parent: str) -> dict:
    return {
        "parent": {"type": "page_id", "page_id": parent},
        "is_inline": True,
        "title": rt(TASKS_DB_TITLE),
        "description": rt("Add a row with a Due date and it joins the game next time the app opens. "
                          "Marking Done here doesn't count — proof happens in the app."),
        "properties": {
            "Name": {"title": {}},
            "Due": {"date": {}},
            "Status": {"select": {"options": [{"name": k, "color": c} for k, c in STATUS_COLORS.items()]}},
            "Size": {"select": {"options": [{"name": k, "color": c} for k, c in SIZES.items()]}},
            "Consequence": {"rich_text": {}},
            "Goal": {"rich_text": {}},
            "Reward": {"number": {}},
            "Penalty": {"number": {}},
            "Proof": {"rich_text": {}},
            "Proof link": {"url": {}},
            "Proof file": {"files": {}},
            "Steward": {"rich_text": {}},
            "App ID": {"rich_text": {}},
        },
    }


def _make_page(n: Notion, parent: str, title: str, emoji: str, note: str) -> str:
    return n.req("POST", "/pages", json={
        "parent": {"type": "page_id", "page_id": parent},
        "icon": {"type": "emoji", "emoji": emoji},
        "properties": {"title": {"title": rt(title)}},
        "children": [{"object": "block", "type": "callout", "callout": {
            "rich_text": rt(note), "icon": {"type": "emoji", "emoji": "⚠️"}}}],
    })["id"]


def ensure_workspace(n: Notion, parent_page: str) -> dict:
    parent = clean_id(parent_page)
    ids = {}
    for b in n.children(parent):
        t = b.get("type")
        title = (b.get(t) or {}).get("title") if t in ("child_database", "child_page") else None
        if t == "child_database" and title == TASKS_DB_TITLE:
            ids["tasks_db"] = b["id"]
        elif t == "child_page" and title == SAVE_PAGE_TITLE:
            ids["save_page"] = b["id"]
        elif t == "child_page" and title == NAG_PAGE_TITLE:
            ids["nag_page"] = b["id"]
    if "tasks_db" not in ids:
        ids["tasks_db"] = n.req("POST", "/databases", json=_tasks_db_schema(parent))["id"]
    if "save_page" not in ids:
        ids["save_page"] = _make_page(n, parent, SAVE_PAGE_TITLE, "💾",
                                      "Game save. Don't edit by hand — the app overwrites it.")
    if "nag_page" not in ids:
        ids["nag_page"] = _make_page(n, parent, NAG_PAGE_TITLE, "📣",
                                     "The phone nagger's memory. Don't edit by hand.")
    return ids


# ─────────────── JSON stored in code blocks ───────────────
def load_json(n: Notion, page_id: str):
    blocks = [b for b in n.children(page_id) if b.get("type") == "code"]
    text = "".join(plain(b["code"]["rich_text"]) for b in blocks)
    return json.loads(text) if text.strip() else None


def save_json(n: Notion, page_id: str, data) -> None:
    text = json.dumps(data, separators=(",", ":"), default=str)
    pieces = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
    groups = [pieces[i:i + BLOCK_ITEMS] for i in range(0, len(pieces), BLOCK_ITEMS)]
    existing = [b for b in n.children(page_id) if b.get("type") == "code"]

    def code(g):
        return {"rich_text": [{"type": "text", "text": {"content": p}} for p in g], "language": "json"}

    for i, g in enumerate(groups):
        if i < len(existing):
            n.req("PATCH", f"/blocks/{existing[i]['id']}", json={"code": code(g)})
        else:
            n.req("PATCH", f"/blocks/{page_id}/children",
                  json={"children": [{"object": "block", "type": "code", "code": code(g)}]})
    for b in existing[len(groups):]:
        n.req("DELETE", f"/blocks/{b['id']}")


# ─────────────── task rows ───────────────
def task_props(t: dict, goal: str = "") -> dict:
    p = {
        "Name": {"title": rt(t["title"])},
        "Due": {"date": {"start": t["deadline"]}},
        "Status": {"select": {"name": STATUS.get(t["status"], "Open")}},
        "Size": {"select": {"name": t["difficulty"]}},
        "Consequence": {"rich_text": rt(t.get("consequence"))},
        "Goal": {"rich_text": rt(goal)},
        "Reward": {"number": t["reward"]},
        "Penalty": {"number": t["penalty"]},
        "App ID": {"rich_text": rt(t["id"])},
        "Proof": {"rich_text": rt(t.get("proof_note"))},
        "Steward": {"rich_text": rt((t.get("verdict") or {}).get("comment"))},
    }
    if t.get("proof_link"):
        p["Proof link"] = {"url": t["proof_link"][:2000]}
    return p


def upsert_task(n: Notion, db_id: str, t: dict, goal: str = "") -> None:
    props = task_props(t, goal)
    if t.get("sync_page"):
        n.req("PATCH", f"/pages/{t['sync_page']}", json={"properties": props})
    else:
        t["sync_page"] = n.req("POST", "/pages", json={"parent": {"database_id": db_id},
                                                       "properties": props})["id"]


def archive_page(n: Notion, page_id: str) -> None:
    n.req("PATCH", f"/pages/{page_id}", json={"archived": True})


def parse_row(page: dict) -> dict:
    pr = page.get("properties", {})

    def sel(name):
        return ((pr.get(name) or {}).get("select") or {}).get("name")

    def txt(name):
        v = pr.get(name) or {}
        return plain(v.get("rich_text") or v.get("title") or [])

    def num(name):
        return (pr.get(name) or {}).get("number")

    return {
        "page_id": page["id"],
        "title": txt("Name").strip(),
        "due": ((pr.get("Due") or {}).get("date") or {}).get("start"),
        "status": sel("Status"),
        "size": sel("Size"),
        "consequence": txt("Consequence").strip(),
        "app_id": txt("App ID").strip(),
        "penalty": num("Penalty"),
        "reward": num("Reward"),
        "archived": page.get("archived", False),
    }


def pull_rows(n: Notion, db_id: str) -> list[dict]:
    return [parse_row(p) for p in n.query(db_id)]


def due_to_dt(due: str, tz) -> datetime:
    """Notion date → aware datetime. Date-only means 11:59 PM that day."""
    if len(due) == 10:
        return datetime.fromisoformat(due + "T23:59:00").replace(tzinfo=tz)
    d = datetime.fromisoformat(due.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=tz)


# ─────────────── proof uploads ───────────────
def upload_proof(n: Notion, page_id: str, filename: str, data: bytes, content_type: str) -> None:
    fu = n.req("POST", "/file_uploads", json={"filename": filename, "content_type": content_type})
    headers = {k: v for k, v in n.h.items() if k != "Content-Type"}
    r = n.s.post(f"{API}/file_uploads/{fu['id']}/send", headers=headers,
                 files={"file": (filename, data, content_type)}, timeout=60)
    if r.status_code >= 400:
        raise NotionError(f"Notion upload {r.status_code}: {r.text[:200]}")
    ref = {"type": "file_upload", "file_upload": {"id": fu["id"]}}
    if content_type.startswith("image/"):
        n.req("PATCH", f"/blocks/{page_id}/children",
              json={"children": [{"object": "block", "type": "image", "image": ref}]})
    else:
        n.req("PATCH", f"/pages/{page_id}",
              json={"properties": {"Proof file": {"files": [dict(ref, name=filename[:100])]}}})
