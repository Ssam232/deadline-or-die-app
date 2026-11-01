"""
🕐 The app's time zone, safe against stale time-zone data.

Alberta stays on UTC-6 all year from Nov 2026 (no more clock change). Newer tz data knows that; an older copy on a
server would still roll Edmonton back to UTC-7 at 2 AM on Nov 1 and put every deadline, prayer time and reminder an
hour off. So: prefer the bundled `tzdata` package, check what it says about January, and if it still thinks Alberta
changes clocks, use America/Regina (UTC-6 all year, identical from now on).
"""
from __future__ import annotations

import os
import zoneinfo
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def _zone(name: str) -> ZoneInfo:
    try:  # the pip tzdata package is kept current; the server's own copy may not be
        import importlib.resources as ir
        if ir.files("tzdata").joinpath("zoneinfo", *name.split("/")).is_file():
            with ir.files("tzdata").joinpath("zoneinfo", *name.split("/")).open("rb") as f:
                return ZoneInfo.from_file(f, key=name)
    except Exception:  # noqa: BLE001
        pass
    return ZoneInfo(name)


def app_tz() -> ZoneInfo:
    name = os.getenv("DOD_TZ", "America/Edmonton")
    z = _zone(name)
    if name == "America/Edmonton":
        jan = datetime(datetime.now().year + 1, 1, 15, 12, tzinfo=z).utcoffset()
        if jan != timedelta(hours=-6):  # stale data: still thinks Alberta falls back to UTC-7
            return _zone("America/Regina")
    return z


TZ = app_tz()
