"""Extract the user-authored text from outgoing requests.

Known AI chat sites get a dedicated adapter that reads only the prompt endpoint, so telemetry
and other API calls on those hosts are ignored. Other inspected hosts use the generic adapter.
"""

import json
import re
from urllib.parse import parse_qsl


def _json(body: bytes):
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None


def chatgpt(path: str, body: bytes) -> str | None:
    # POST /backend-api/conversation or /backend-api/f/conversation
    if not re.match(r"^/backend-api/(f/)?conversation/?(\?|$)", path):
        return None
    data = _json(body)
    if not isinstance(data, dict):
        return None
    texts = []
    for m in data.get("messages") or []:
        if (m.get("author") or {}).get("role") != "user":
            continue
        for p in (m.get("content") or {}).get("parts") or []:
            if isinstance(p, str):
                texts.append(p)
            elif isinstance(p, dict) and isinstance(p.get("text"), str):
                texts.append(p["text"])
    return "\n".join(texts) or None


def claude(path: str, body: bytes) -> str | None:
    # POST /api/organizations/<org>/chat_conversations/<id>/completion (also retry_completion)
    if not re.match(r"^/api/organizations/[^/]+/chat_conversations/[^/]+/(retry_)?completion", path):
        return None
    data = _json(body)
    if not isinstance(data, dict):
        return None
    texts = [data.get("prompt") or ""]
    for a in data.get("attachments") or []:
        if isinstance(a, dict) and a.get("extracted_content"):
            texts.append(a["extracted_content"])
    return "\n".join(t for t in texts if t) or None


def _strings(obj, out: list[str]):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _strings(v, out)


def generic(path: str, body: bytes, content_type: str) -> str | None:
    ct = content_type.lower()
    if "json" in ct:
        data = _json(body)
        if data is None:
            return None
        out: list[str] = []
        _strings(data, out)
        return "\n".join(s for s in out if len(s) > 3) or None
    if "x-www-form-urlencoded" in ct:
        return "\n".join(v for _, v in parse_qsl(body.decode("utf-8", "replace"))) or None
    if ct.startswith("text/") or not ct:
        return body.decode("utf-8", "replace") or None
    return None  # binary uploads are out of scope


ADAPTERS = {"chatgpt.com": ("chatgpt", chatgpt), "claude.ai": ("claude", claude)}


def extract(site: str | None, path: str, body: bytes, content_type: str) -> tuple[str, str] | None:
    """site is the matched inspect domain. Returns (adapter_name, text) or None if nothing to check."""
    if site in ADAPTERS:
        name, fn = ADAPTERS[site]
        text = fn(path, body)
        return (name, text) if text else None
    text = generic(path, body, content_type)
    return ("generic", text) if text else None
