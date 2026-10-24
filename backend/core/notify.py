"""macOS notifications and the proxy -> API event ping (all local)."""

import shutil
import subprocess

import httpx

API = "http://127.0.0.1:8000"
DASHBOARD = API + "/#queue"


def mask(span: str) -> str:
    span = span.strip()
    return span[:4] + "•" * min(8, max(3, len(span) - 4)) if len(span) > 4 else "•••"


def macos(title: str, message: str):
    if shutil.which("terminal-notifier"):
        cmd = ["terminal-notifier", "-title", title, "-message", message, "-open", DASHBOARD, "-sound", "Basso"]
    else:
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        cmd = ["osascript", "-e", f'display notification "{esc(message)}" with title "{esc(title)}" sound name "Basso"']
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def describe(event: dict) -> str:
    bad = [f for f in event["findings"] if not f.get("allowed") and f.get("is_sensitive")]
    if not bad:
        return event.get("error") or "model unavailable"
    return ", ".join(f'{f["category"]}: {mask(f["span"])}' for f in bad[:3])


def event_alert(event: dict):
    host, tier = event["host"], event["tier"]
    if tier == "BLOCK":
        macos(f"DLP: заблокировано → {host}", describe(event))
    else:
        macos(f"DLP: на проверке у security → {host}", describe(event))


async def ping_api(event_id: str):
    try:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as c:
            await c.post(f"{API}/internal/event", json={"id": event_id})
    except httpx.HTTPError:
        pass  # dashboard not running: event is still in SQLite
