"""Admin / security API: events queue, decisions, SSE, policies and dataset. Bound to 127.0.0.1 only."""

import asyncio
import json
from pathlib import Path

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from core import classifier, hf_import, policies, store

app = FastAPI(title="Local DLP Guard")
store.init()
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

# --- SSE broadcast ------------------------------------------------------------

_subscribers: set[asyncio.Queue] = set()


def broadcast(kind: str, data: dict):
    for q in list(_subscribers):
        q.put_nowait({"event": kind, "data": json.dumps(data, ensure_ascii=False)})


@app.get("/api/stream")
async def stream():
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)

    async def gen():
        try:
            while True:
                yield await q.get()
        finally:
            _subscribers.discard(q)

    return EventSourceResponse(gen(), ping=15)


class Ping(BaseModel):
    id: str


@app.post("/internal/event")
def internal_event(p: Ping):
    ev = store.get_event(p.id)
    if ev:
        broadcast("event", ev)
    return {"ok": True}


# --- events -------------------------------------------------------------------

@app.get("/api/events")
def events(status: str | None = None, limit: int = 200):
    return store.list_events(status.split(",") if status else None, limit)


@app.get("/api/events/{event_id}")
def event(event_id: str):
    ev = store.get_event(event_id)
    if not ev:
        raise HTTPException(404)
    return ev


class Decision(BaseModel):
    decision: str  # approve | reject


@app.post("/api/events/{event_id}/decision")
def decide(event_id: str, d: Decision):
    if d.decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    ev = store.get_event(event_id)
    if not ev:
        raise HTTPException(404)
    if ev["status"] not in ("pending", "blocked", "expired"):
        raise HTTPException(409, f"event already {ev['status']}")
    status = "approved" if d.decision == "approve" else "rejected"
    if not store.set_status(event_id, status, only_if=ev["status"]):
        raise HTTPException(409, "event changed, reload")
    # every judged violation becomes a labelled example for few-shot now and fine-tuning later
    label = "not_sensitive" if status == "approved" else "sensitive"
    rows = [
        {"text": hf_import._context(ev["text"], f["span"]), "span": f["span"], "category": f["category"], "label": label}
        for f in ev["findings"]
        if not f.get("allowed")
    ]
    added = store.add_examples(rows, "security")
    ev = store.get_event(event_id)
    broadcast("event", ev)
    return {"event": ev, "dataset_rows_added": added}


# --- try-it: classify without the proxy (used by the admin UI and demo) -------------

class TryIt(BaseModel):
    text: str
    host: str


@app.post("/api/classify")
async def classify(t: TryIt):
    try:
        return await classifier.classify(t.text, t.host)
    except classifier.ClassifierError as e:
        return {"tier": "BLOCK", "score": 1.0, "findings": [], "error": str(e)}


# --- policies -----------------------------------------------------------------

@app.get("/api/policies")
def get_policies():
    pol = policies.load()
    return {"raw": pol.raw, "yaml": policies.POLICY_PATH.read_text()}


@app.put("/api/policies")
def put_policies(raw: dict):
    old = policies.load().inspect_domains
    try:
        pol = policies.save(raw)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "restart_proxy": pol.inspect_domains != old}


class YamlBody(BaseModel):
    yaml: str


@app.put("/api/policies/yaml")
def put_policies_yaml(b: YamlBody):
    old = policies.load().inspect_domains
    try:
        pol = policies.save_yaml(b.yaml)
    except (ValueError, TypeError, yaml.YAMLError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "restart_proxy": pol.inspect_domains != old}


@app.get("/api/policies/export")
def export_policies():
    return Response(
        policies.POLICY_PATH.read_text(), media_type="application/x-yaml",
        headers={"Content-Disposition": "attachment; filename=policies.yaml"},
    )


# --- dataset ------------------------------------------------------------------

@app.get("/api/dataset")
def dataset(limit: int = 100, offset: int = 0, category: str | None = None):
    rows, total = store.list_dataset(limit, offset, category)
    return {"rows": rows, "total": total, "stats": store.dataset_stats()}


@app.get("/api/dataset/sources")
def dataset_sources():
    return [{"id": k, "description": v} for k, v in hf_import.SOURCES.items()]


class HfImport(BaseModel):
    dataset_id: str


@app.post("/api/dataset/import-hf")
async def import_hf(b: HfImport):
    try:
        n = await asyncio.to_thread(hf_import.import_hf, b.dataset_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # network errors during the one-time download
        raise HTTPException(502, f"download failed: {e}")
    return {"imported": n}


@app.post("/api/dataset/upload")
async def upload(file: UploadFile = File(...)):
    try:
        rows = hf_import.parse_upload(file.filename or "", await file.read())
    except (ValueError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"cannot parse file: {e}")
    cats = set(policies.load().categories)
    bad = [r for r in rows if r.get("category") not in cats]
    if bad:
        raise HTTPException(400, f"{len(bad)} rows have unknown category, e.g. {bad[0].get('category')!r}")
    return {"imported": store.add_examples(rows, f"upload:{file.filename}")}


@app.delete("/api/dataset")
def clear(source: str | None = None):
    return {"deleted": store.clear_dataset(source)}


@app.get("/api/dataset/export")
def export_dataset():
    return PlainTextResponse(
        hf_import.export_lora(), media_type="application/jsonl",
        headers={"Content-Disposition": "attachment; filename=dlp-lora.jsonl"},
    )


# --- SPA ----------------------------------------------------------------------

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
