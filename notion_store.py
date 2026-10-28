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
CATEGORY_NAMES = {"deep": "🧠 Deep work", "admin": "📨 Academic admin", "health": "💪 Health & training",
                  "life": "🧺 Life admin", "show": "🪑 Showing up"}
CATEGORY_COLORS = {"deep": "purple", "admin": "blue", "health": "green", "life": "brown", "show": "gray"}
EXTRA_PROPS = {
    "Category": {"select": {"options": [{"name": v, "color": CATEGORY_COLORS[k]} for k, v in CATEGORY_NAMES.items()]}},
    "Minutes": {"number": {}},
}
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
            **EXTRA_PROPS,
        },
    }


DASHBOARD_MARK = "PIT WALL"
TASK_ICONS = {"open": "⏱️", "done": "🏁", "failed": "💀", "redeemed": "🩹"}
HOW_IT_WORKS = [
    "Add a row below with a Due date (and a Size + Consequence if you like). It joins the game next time the app "
    "opens, or the nagger sees it within 30 min.",
    "Finish it → open the app → submit proof (photo, screenshot, file or link). Only proof counts: ticking Done "
    "here, moving the date or deleting the row gets reverted.",
    "Proof approved → coins + XP + a pit crate (coins, free part, streak shield, repair, or a 3× jackpot).",
    "Miss it → lose coins, −15% car, streak gone, rivals get faster, and your consequence lands in the penalty box.",
    "Your phone escalates: 24h heads-up → 6h → 2h red zone (repeats) → 30 min final warning → DNF.",
    "Coins buy car upgrades. Race your procrastination rivals in the app. Debt or unserved penalties = black flag.",
]


def seg(text: str, bold: bool = False, color: str = "default", link: str | None = None) -> dict:
    t = {"content": text[:CHUNK]}
    if link:
        t["link"] = {"url": link}
    return {"type": "text", "text": t, "annotations": {"bold": bold, "color": color}}


def _make_dashboard(n: Notion, parent: str) -> str:
    bullets = [{"object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [seg(s)]}} for s in HOW_IT_WORKS]
    res = n.req("PATCH", f"/blocks/{parent}/children", json={"children": [
        {"object": "block", "type": "callout", "callout": {
            "rich_text": [seg(DASHBOARD_MARK, bold=True), seg("  ·  waiting for the first lap…")],
            "icon": {"type": "emoji", "emoji": "🏎️"}, "color": "gray_background"}},
        {"object": "block", "type": "toggle", "toggle": {
            "rich_text": [seg("📖 How it works", bold=True)], "children": bullets}},
        {"object": "block", "type": "divider", "divider": {}},
    ]})
    try:
        n.req("PATCH", f"/pages/{parent}", json={"icon": {"type": "emoji", "emoji": "🏁"}})
    except NotionError:
        pass
    return res["results"][0]["id"]


def _dress_db(n: Notion, db_id: str) -> None:
    try:  # icon + any columns added in later versions (idempotent)
        n.req("PATCH", f"/databases/{db_id}", json={"icon": {"type": "emoji", "emoji": "🏁"}, "properties": EXTRA_PROPS})
    except NotionError:
        pass


def _fmt_left(td) -> str:
    s = int(td.total_seconds())
    if s < 0:
        return "overdue"
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    return f"{d}d {h}h" if d else f"{h}h {s // 60}m" if h else f"{s // 60}m"


def dashboard_content(save: dict, tz, app_url: str | None = None, now: datetime | None = None) -> dict:
    """The live Pit Wall: same numbers as the app, readable at a glance in Notion."""
    import math
    now = now or datetime.now(tz)
    coins, streak, xp = save.get("coins", 0), save.get("streak", 0), save.get("xp", 0)
    car = save.get("car", {}).get("condition", 100)
    heat = save.get("rival_heat", 0)
    lvl = int(math.sqrt(max(xp, 0) / 50)) + 1
    unserved = [p for p in save.get("penalty_box", []) if not p.get("served")]
    flags = (["in debt"] if coins < 0 else []) + ([f"{len(unserved)} penalty unserved"] if unserved else []) + \
            (["car wrecked"] if car < 20 else [])
    open_tasks = sorted((t for t in save.get("tasks", []) if t.get("status") == "open"),
                        key=lambda t: t["deadline"])
    out = [seg(DASHBOARD_MARK, bold=True), seg(f"  ·  updated {now:%a %I:%M %p}\n", color="gray"),
           seg(f"🪙 {coins}", bold=True), seg(" coins    "),
           seg(f"🔥 {streak}", bold=True), seg(" streak    "),
           seg(f"🧑‍✈️ Lv {lvl}", bold=True), seg("    "),
           seg(f"🔧 {car}%", bold=True, color="red" if car < 40 else "default"), seg(" car    "),
           seg(f"🌡️ {heat}", bold=True, color="red" if heat else "default"), seg(" rival heat\n")]
    today_color = None
    if save.get("tasks") is not None:
        import daily
        stt = daily.status(save, now)
        if stt["rest"]:
            out.append(seg("🛌 Pit stop day — rest\n", color="blue"))
        elif not stt["qualified"] and not stt["missed"]:
            out.append(seg(f"🚦 NOT QUALIFIED — lock in today's mission by {stt['deadline']:%I:%M %p}\n",
                           bold=True, color="orange"))
            today_color = "orange_background"
        elif not stt["qualified"]:
            out.append(seg("🚨 Missed qualifying — the safety car is out\n", bold=True, color="red"))
            today_color = "red_background"
        else:
            m, d = stt["mission"], stt["mission_done"]
            out.append(seg(f"🏁 Today's mission {len(d)}/{len(m)}", bold=True,
                           color="green" if m and len(d) == len(m) else "default"))
            out.append(seg(f"    📅 {stt['day_streak']}-day streak\n"))
    if flags:
        out.append(seg("⬛ BLACK FLAG — " + ", ".join(flags) + "\n", bold=True, color="red"))
    else:
        out.append(seg("🟢 Green flag — clear to race\n", color="green"))
    for p in unserved[:2]:
        out.append(seg(f"🚨 Penalty box: {p['consequence']}\n", color="red"))
    if open_tasks:
        out.append(seg("\nNext up\n", bold=True))
        for t in open_tasks[:3]:
            dl = datetime.fromisoformat(t["deadline"])
            left = dl - now
            hrs = left.total_seconds() / 3600
            dot = "💀" if hrs < 0 else "🔴" if hrs < 12 else "🟡" if hrs < 48 else "🟢"
            out.append(seg(f"{dot} {t['title']}", bold=True))
            out.append(seg(f"  —  {dl.astimezone(tz):%a %b %d, %I:%M %p}  ·  {_fmt_left(left)}"
                           f"  ·  +{t['reward']} / −{t['penalty']}\n", color="gray"))
    else:
        out.append(seg("\nNothing on the board. Add a row below with a Due date — the car needs fuel.\n",
                       color="gray"))
    if app_url:
        out.append(seg("\n"))
        out.append(seg("Open Deadline or Die →", bold=True, link=app_url))
    color = "red_background" if flags else today_color if today_color else ("orange_background" if open_tasks and
                                            (datetime.fromisoformat(open_tasks[0]["deadline"]) - now)
                                            .total_seconds() < 12 * 3600 else "gray_background")
    return {"rich_text": out[:100], "color": color, "icon": {"type": "emoji", "emoji": "🏎️"}}


def update_dashboard(n: Notion, block_id: str, save: dict, tz, app_url: str | None = None) -> None:
    n.req("PATCH", f"/blocks/{block_id}", json={"callout": dashboard_content(save, tz, app_url)})


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
        elif t == "callout" and plain(b["callout"].get("rich_text")).startswith(DASHBOARD_MARK):
            ids["dashboard"] = b["id"]
    if "dashboard" not in ids:  # goes first on a fresh page, so it sits above the table
        ids["dashboard"] = _make_dashboard(n, parent)
    if "tasks_db" not in ids:
        ids["tasks_db"] = n.req("POST", "/databases", json=_tasks_db_schema(parent))["id"]
    _dress_db(n, ids["tasks_db"])
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
        "Category": {"select": {"name": CATEGORY_NAMES.get(t.get("category"), CATEGORY_NAMES["admin"])}},
        "Minutes": {"number": t.get("minutes")},
        "Proof": {"rich_text": rt(t.get("proof_note"))},
        "Steward": {"rich_text": rt((t.get("verdict") or {}).get("comment"))},
    }
    if t.get("proof_link"):
        p["Proof link"] = {"url": t["proof_link"][:2000]}
    return p


def upsert_task(n: Notion, db_id: str, t: dict, goal: str = "") -> None:
    props = task_props(t, goal)
    icon = {"type": "emoji", "emoji": TASK_ICONS.get(t["status"], "⏱️")}
    if t.get("sync_page"):
        n.req("PATCH", f"/pages/{t['sync_page']}", json={"properties": props, "icon": icon})
    else:
        t["sync_page"] = n.req("POST", "/pages", json={"parent": {"database_id": db_id},
                                                       "properties": props, "icon": icon})["id"]


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
        "category": {v: k for k, v in CATEGORY_NAMES.items()}.get(sel("Category")),
        "minutes": num("Minutes"),
        "penalty": num("Penalty"),
        "reward": num("Reward"),
        "archived": page.get("archived", False),
        "created": page.get("created_time"),
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
