"""Two-stage sensitive data classifier on a local Gemma model via Ollama.

1. detect:  model extracts sensitive spans with a category
2. filter:  drop findings whose category the destination domain allows
3. verify:  model re-judges remaining findings against dataset examples of the same category
4. score:   max confidence among confirmed violations -> ALLOW / REVIEW / BLOCK
Any model failure raises ClassifierError; callers treat it as BLOCK (fail-closed).
"""

import asyncio
import json
import os
import sys
import time

import httpx

from . import policies, store

def _load_env():
    """Read backend/.env (gitignored) without overriding real environment variables."""
    path = policies.ROOT / "backend" / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
# "ollama" (local Gemma, the product) or "gemini" (TEMPORARY cloud stand-in for development only)
PROVIDER = os.environ.get("DLP_LLM_PROVIDER", "ollama")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
MAX_CHARS = 4000


def runtime_model(pol: "policies.Policies") -> dict:
    if PROVIDER == "gemini":
        return {"provider": "gemini", "model": GEMINI_MODEL, "local": False}
    return {"provider": "ollama", "model": pol.llm, "local": True}

CATEGORY_HELP = {
    "pii": "personal data of a real person: full names with contact info, emails, phone numbers, home addresses, passport/SSN/ID numbers, dates of birth",
    "credentials": "secrets that grant access: API keys, tokens, passwords, private keys, connection strings with passwords",
    "financial": "card numbers, bank accounts, IBANs, salaries, non-public revenue or financial figures",
    "customer_data": "data about the company's customers: customer lists, contracts, support tickets, usage data tied to a customer",
    "source_code": "proprietary source code, configs, internal API schemas",
    "internal_docs": "internal non-public documents: strategy, roadmaps, incident reports, internal meeting notes",
}


class ClassifierError(Exception):
    pass


DETECT_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "span": {"type": "string"},
                    "category": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["span", "category", "reason"],
            },
        }
    },
    "required": ["findings"],
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "is_sensitive": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "is_sensitive", "confidence", "reason"],
            },
        }
    },
    "required": ["verdicts"],
}


async def _chat(client: httpx.AsyncClient, model: str, system: str, user: str, schema: dict) -> dict:
    if PROVIDER == "gemini":
        return await _chat_gemini(client, system, user, schema)
    r = await client.post(
        f"{OLLAMA}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": 0},
        },
    )
    if r.status_code != 200:
        raise ClassifierError(f"ollama {r.status_code}: {r.text[:200]}")
    try:
        return json.loads(r.json()["message"]["content"])
    except (KeyError, json.JSONDecodeError) as e:
        raise ClassifierError(f"bad model output: {e}") from e


async def _chat_gemini(client: httpx.AsyncClient, system: str, user: str, schema: dict) -> dict:
    r = await client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "")},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        },
    )
    if r.status_code != 200:
        raise ClassifierError(f"gemini {r.status_code}: {r.text[:200]}")
    try:
        return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise ClassifierError(f"bad model output: {e}") from e


def _categories_block(cats: list[str]) -> str:
    return "\n".join(f"- {c}: {CATEGORY_HELP.get(c, c)}" for c in cats)


async def detect(client, model, text: str, cats: list[str]) -> list[dict]:
    system = (
        "You are a data loss prevention detector. Find every fragment of the user's outgoing message "
        "that contains sensitive data. Categories:\n" + _categories_block(cats) + "\n"
        "Rules: copy each span EXACTLY as it appears in the message (short, only the sensitive part). "
        "Ignore obviously fake placeholders like 'your-api-key', 'xxx', 'example.com' and generic questions. "
        "If nothing is sensitive return an empty list."
    )
    out = await _chat(client, model, system, f"MESSAGE:\n{text}", DETECT_SCHEMA)
    findings = []
    for f in out.get("findings", []):
        if f.get("category") in cats and f.get("span"):
            findings.append({"span": f["span"], "category": f["category"], "reason": f.get("reason", "")})
    return findings


async def verify(client, model, text: str, findings: list[dict], host: str) -> list[dict]:
    blocks = []
    for cat in sorted({f["category"] for f in findings}):
        ex = store.examples_for(cat)
        lines = [
            f'  [{e["label"]}] "{(e["span"] or e["text"])[:200]}"' + (f' (context: "{e["text"][:160]}")' if e["span"] else "")
            for e in ex
        ]
        blocks.append(f"Category {cat}: {CATEGORY_HELP.get(cat, cat)}\nLabelled examples:\n" + ("\n".join(lines) or "  (none)"))
    items = "\n".join(f'{i}. [{f["category"]}] "{f["span"]}" — detector said: {f["reason"]}' for i, f in enumerate(findings))
    system = (
        "You are a strict but precise data loss prevention reviewer. A detector flagged fragments of a message "
        f"that a user is about to send to {host}, which is NOT allowed to receive these categories. "
        "For each finding decide whether it is really sensitive, using the labelled examples to calibrate "
        "(examples labelled not_sensitive show look-alikes that are safe). Give confidence 0..1 that the "
        "finding is truly sensitive data that must not leave the company. Calibrate:\n"
        "- 0.9-1.0: unambiguous and directly harmful: real secrets/keys/passwords, card or account numbers, "
        "government IDs, a real person's contact details together with their name.\n"
        "- 0.5-0.85: probably sensitive but needs a human: company source code, internal documents, customer "
        "names without identifiers, business logic. A person must judge context.\n"
        "- below 0.5: placeholders, public/generic code, well-known facts, data that only looks sensitive.\n\n"
        + "\n\n".join(blocks)
    )
    user = f"MESSAGE:\n{text}\n\nFINDINGS:\n{items}"
    out = await _chat(client, model, system, user, VERIFY_SCHEMA)
    by_id = {v.get("id"): v for v in out.get("verdicts", [])}
    for i, f in enumerate(findings):
        v = by_id.get(i)
        if v is None:  # model skipped it: keep as uncertain
            f.update(is_sensitive=True, confidence=0.6, verify_reason="no verdict from verifier")
        else:
            f.update(
                is_sensitive=bool(v["is_sensitive"]),
                confidence=max(0.0, min(1.0, float(v["confidence"]))),
                verify_reason=v.get("reason", ""),
            )
    return findings


def _locate(text: str, findings: list[dict]):
    for f in findings:
        i = text.find(f["span"])
        if i < 0:
            i = text.lower().find(f["span"].lower())
        f["start"], f["end"] = (i, i + len(f["span"])) if i >= 0 else (None, None)


async def classify(text: str, host: str, pol: policies.Policies | None = None) -> dict:
    """Returns {tier, score, findings, latency_ms}. Raises ClassifierError on model failure/timeout."""
    pol = pol or policies.load()
    text = text[:MAX_CHARS]
    t0 = time.monotonic()

    async def run():
        # trust_env=False: never route model calls through the (system) proxy we are part of
        async with httpx.AsyncClient(timeout=pol.model_timeout_s, trust_env=False) as client:
            findings = await detect(client, pol.llm, text, pol.categories)
            allowed = pol.allowed_categories(host)
            for f in findings:
                f["allowed"] = f["category"] in allowed
            violations = [f for f in findings if not f["allowed"]]
            if violations:
                await verify(client, pol.llm, text, violations, host)
            return findings

    try:
        findings = await asyncio.wait_for(run(), timeout=pol.model_timeout_s)
    except asyncio.TimeoutError as e:
        raise ClassifierError(f"model timeout > {pol.model_timeout_s}s") from e
    except httpx.HTTPError as e:
        raise ClassifierError(f"{PROVIDER} unreachable: {e}") from e

    _locate(text, findings)
    score = max((f["confidence"] for f in findings if not f["allowed"] and f.get("is_sensitive")), default=0.0)
    return {
        "tier": pol.tier(score),
        "score": round(score, 3),
        "findings": findings,
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }


if __name__ == "__main__":
    # uv run python -m core.classifier "text" --domain chatgpt.com
    args = sys.argv[1:]
    host = "chatgpt.com"
    if "--domain" in args:
        i = args.index("--domain")
        host = args[i + 1]
        del args[i : i + 2]
    store.init()
    res = asyncio.run(classify(" ".join(args) or sys.stdin.read(), host))
    print(json.dumps(res, ensure_ascii=False, indent=2))
