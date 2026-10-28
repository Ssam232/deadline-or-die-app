"""
🔒 Deadline or Die — PC enforcer.

While you're LOCKED (a 🔒 consequence is active, or a focus session is running), this closes the games
on your blocklist and tells you why. It reads the lock state your app/nagger broadcast to ntfy, so it
needs no passwords or tokens — just your ntfy topic.

    pip install requests psutil
    python enforcer.py --setup      # enter your ntfy topic, review the blocklist
    python enforcer.py --status     # check what it sees right now
    python enforcer.py --install    # start silently every time you log in (Windows/macOS)
    python enforcer.py --uninstall
    python enforcer.py              # run in the foreground (Ctrl+C to stop)

The emergency unlock lives in the app and costs coins. Killing this program works too — but you'll know.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import requests

CONFIG = Path.home() / ".deadline_or_die_enforcer.json"
SERVER = "https://ntfy.sh"
DEFAULT_BLOCK = [
    # shooters / multiplayer
    "Overwatch.exe", "VALORANT-Win64-Shipping.exe", "cs2.exe", "FortniteClient-Win64-Shipping.exe",
    "RocketLeague.exe", "League of Legends.exe", "LeagueClient.exe", "GTA5.exe", "Minecraft.Windows.exe",
    # sim racing
    "AC2-Win64-Shipping.exe", "acs.exe", "iRacingSim64DX11.exe", "iRacingUI.exe", "AMS2AVX.exe", "AMS2.exe",
    "rFactor2.exe", "Le Mans Ultimate.exe", "F1_24.exe", "F1_25.exe", "forza_gaming.desktop.x64_release_final.exe",
]
POLL_SECONDS = 20
STALE_AFTER = "3h"  # if nothing was broadcast for this long, assume OPEN (fail open, never trap you)


def load() -> dict:
    if not CONFIG.exists():
        sys.exit("Not set up yet — run:  python enforcer.py --setup")
    return json.loads(CONFIG.read_text())


def setup() -> None:
    cur = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    topic = input(f"Your NTFY_TOPIC (the one your phone subscribes to) [{cur.get('topic', '')}]: ").strip() \
        or cur.get("topic", "")
    if not topic:
        sys.exit("A topic is required.")
    block = cur.get("block", DEFAULT_BLOCK)
    print("\nBlocklist (process names):\n  " + "\n  ".join(block))
    extra = input("\nAdd more process names (comma-separated, blank to keep): ").strip()
    if extra:
        block += [x.strip() for x in extra.split(",") if x.strip()]
    CONFIG.write_text(json.dumps({"topic": topic.removesuffix("-lock"), "block": block}, indent=2))
    print(f"\nSaved to {CONFIG}. Tip: open a game, then check Task Manager → Details for its exact .exe name.")


def lock_state(topic: str) -> tuple[bool, str]:
    r = requests.get(f"{SERVER}/{topic}-lock/raw", params={"poll": "1", "since": STALE_AFTER}, timeout=10)
    lines = [ln.strip() for ln in r.text.splitlines() if ln.strip()]
    last = lines[-1] if lines else "OPEN"
    return last.startswith("LOCKED"), last


def popup(text: str) -> None:
    def _show():
        try:
            if platform.system() == "Windows":
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, text, "Deadline or Die 🔒", 0x40030)  # topmost + warning
            elif platform.system() == "Darwin":
                subprocess.run(["osascript", "-e", f'display alert "Deadline or Die 🔒" message {json.dumps(text)}'])
            else:
                print(text)
        except Exception:
            print(text)
    threading.Thread(target=_show, daemon=True).start()


def sweep(block: set[str]) -> list[str]:
    killed = []
    for p in psutil.process_iter(["name"]):
        name = p.info.get("name") or ""
        if name.lower() in block:
            try:
                p.kill()
                killed.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    return killed


def run() -> None:
    cfg = load()
    block = {b.lower() for b in cfg["block"]}
    locked, msg, last_popup = False, "OPEN", 0.0
    print(f"Enforcer running · topic {cfg['topic']}-lock · {len(block)} blocked apps. Ctrl+C to stop.")
    while True:
        try:
            locked, msg = lock_state(cfg["topic"])
        except requests.RequestException:
            pass  # keep the last known state on a network blip
        if locked:
            killed = sweep(block)
            if killed and time.time() - last_popup > 30:
                last_popup = time.time()
                reasons = msg.removeprefix("LOCKED:").strip().replace(" | ", "\n• ")
                popup(f"Closed: {', '.join(sorted(set(killed)))}\n\nYou're locked:\n• {reasons}\n\n"
                      "Finish (or redeem) the task to unlock — or buy an emergency unlock in the app.")
        time.sleep(POLL_SECONDS)


def startup_file() -> Path:
    if platform.system() == "Windows":
        return (Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
                / "DeadlineOrDieEnforcer.vbs")
    return Path.home() / "Library/LaunchAgents/com.deadlineordie.enforcer.plist"


def install() -> None:
    load()
    script = Path(__file__).resolve()
    f = startup_file()
    if platform.system() == "Windows":
        pyw = Path(sys.executable).with_name("pythonw.exe")
        f.write_text(f'CreateObject("WScript.Shell").Run """{pyw}"" ""{script}""", 0, False\n')
        subprocess.Popen([str(pyw), str(script)], creationflags=0x08000000)  # start now, no window
    elif platform.system() == "Darwin":
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.deadlineordie.enforcer</string>
<key>ProgramArguments</key><array><string>{sys.executable}</string><string>{script}</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>""")
        subprocess.run(["launchctl", "load", str(f)])
    else:
        sys.exit("Auto-start supports Windows and macOS. On Linux, add `python enforcer.py` to your session startup.")
    print(f"Installed — the enforcer now starts at login ({f}). It's running now too.")


def uninstall() -> None:
    f = startup_file()
    if platform.system() == "Darwin" and f.exists():
        subprocess.run(["launchctl", "unload", str(f)])
    if f.exists():
        f.unlink()
    print("Removed from startup. (If it's running right now, end 'pythonw' in Task Manager or restart.)")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--setup":
        setup()
    elif arg == "--install":
        install()
    elif arg == "--uninstall":
        uninstall()
    elif arg == "--status":
        c = load()
        print(lock_state(c["topic"])[1])
    else:
        run()
