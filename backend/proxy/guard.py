"""mitmproxy addon: classify outgoing requests and ALLOW / hold for REVIEW / BLOCK them.

Run: uv run mitmdump -s proxy/guard.py --listen-host 127.0.0.1 -p 8080
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mitmproxy import ctx, http  # noqa: E402

from core import classifier, notify, policies, store  # noqa: E402
from proxy import adapters  # noqa: E402

log = logging.getLogger("dlp")
METHODS = {"POST", "PUT", "PATCH"}


def allow_hosts_regex(domains: list[str]) -> list[str]:
    return [rf"(^|\.){re.escape(d)}(:\d+)?$" for d in domains]


def deny(flow: http.HTTPFlow, event: dict, reason: str):
    flow.response = http.Response.make(
        403,
        json.dumps(
            {
                "error": {"message": f"Blocked by Local DLP Guard: {reason}", "type": "dlp_blocked"},
                "dlp": {"event_id": event["id"], "tier": event["tier"], "score": event["score"]},
            },
            ensure_ascii=False,
        ),
        {"Content-Type": "application/json", "X-DLP-Event": event["id"]},
    )


class Guard:
    def running(self):
        store.init()
        pol = policies.load()
        # decrypt TLS only for inspected domains, everything else is passed through untouched
        ctx.options.update(allow_hosts=allow_hosts_regex(pol.inspect_domains))
        log.info(f"DLP guard running, inspecting {pol.inspect_domains}, model {pol.llm}")
        asyncio.get_running_loop().create_task(classifier.warmup(pol))

    async def request(self, flow: http.HTTPFlow):
        req = flow.request
        if req.method not in METHODS or not req.raw_content:
            return
        pol = policies.load()
        host = req.pretty_host
        site = pol.match_domain(host, pol.inspect_domains)
        if not site or pol.should_skip(req.path):
            return
        extracted = adapters.extract(site, req.path, req.raw_content, req.headers.get("content-type", ""))
        if not extracted:
            return
        adapter, text = extracted
        if len(text.strip()) < pol.min_text_chars:
            return

        try:
            res = await classifier.classify(text, host, pol)
            error = None
        except classifier.ClassifierError as e:
            res = {"tier": "BLOCK", "score": 1.0, "findings": [], "purpose": None, "latency_ms": None}
            error = str(e)
        tier = res["tier"]
        status = {"ALLOW": "allowed", "REVIEW": "pending", "BLOCK": "blocked"}[tier]
        event = store.insert_event(
            host=host, path=req.path, adapter=adapter, text=text[: classifier.MAX_CHARS], tier=tier,
            score=res["score"], findings=res["findings"], status=status, error=error, latency_ms=res["latency_ms"],
            purpose=res["purpose"],
        )
        log.info(f"[{tier}] {host}{req.path[:60]} score={res['score']} {res['latency_ms'] or '-'}ms {error or ''}")
        if tier == "ALLOW":
            await notify.ping_api(event["id"])
            return

        notify.event_alert(event)
        await notify.ping_api(event["id"])
        if tier == "BLOCK":
            deny(flow, event, notify.describe(event))
            return

        # REVIEW: hold the request until security decides or the timeout expires
        loop = asyncio.get_running_loop()
        deadline = loop.time() + pol.review_timeout_s
        while loop.time() < deadline:
            await asyncio.sleep(0.5)
            cur = store.get_event(event["id"])
            if cur["status"] == "approved":
                log.info(f"[APPROVED] {event['id']}")
                return
            if cur["status"] == "rejected":
                deny(flow, cur, "rejected by security")
                return
        store.set_status(event["id"], "expired", only_if="pending")
        await notify.ping_api(event["id"])
        deny(flow, event, "no security decision in time")


addons = [Guard()]
