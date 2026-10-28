"""Phone pushes through ntfy (https://ntfy.sh). Install the ntfy app, subscribe to your secret topic."""
from __future__ import annotations

import os

import requests

SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")


def push(topic: str | None, title: str, message: str, priority: int = 3, tags: list[str] | None = None,
         click: str | None = None, server: str = SERVER) -> bool:
    """priority: 1 min · 2 low · 3 default · 4 high · 5 max (long vibration / pop-over on Android)."""
    if not topic:
        return False
    body = {"topic": topic, "title": title, "message": message, "priority": int(priority),
            "tags": tags or [], "markdown": True}
    if click:
        body["click"] = click
        body["actions"] = [{"action": "view", "label": "Open Deadline or Die", "url": click, "clear": True}]
    try:
        r = requests.post(server.rstrip("/"), json=body, timeout=10)
        return r.status_code < 300
    except requests.RequestException:
        return False
