"""Open the app's sign-in page so Streamlit Cloud doesn't put it to sleep (it sleeps after ~12 h without a visit,
and waking it makes the first login of the day crawl). If it's already asleep, press the wake button.
Only the password page is loaded: no key, no game data. Logs say awake/woken, nothing else."""
import os
import sys
import time

from playwright.sync_api import sync_playwright

url = (os.getenv("APP_URL") or "").split("?")[0]
if not url:
    print("::notice title=keep awake::no APP_URL secret, skipped")
    sys.exit(0)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page()
    p.goto(url, wait_until="domcontentloaded", timeout=90_000)
    woke = False
    for _ in range(3):
        btn = p.get_by_role("button", name="Yes, get this app back up!")
        if btn.count():
            btn.first.click()
            woke = True
            break
        time.sleep(3)
    ok, t0 = False, time.time()
    while time.time() - t0 < 180 and not ok:  # wait for the app itself (it runs in a frame) to draw anything of ours
        for f in p.frames:
            try:
                if f.locator("text=DEADLINE").count() or f.locator("input[type=password]").count():
                    ok = True
                    break
            except Exception:  # noqa: BLE001
                pass
        time.sleep(3)
    print(f"::notice title=keep awake::{'woke it up' if woke else 'was awake'} · "
          f"{'app answered' if ok else 'no answer yet'} in {time.time() - t0:.0f}s")
    b.close()
