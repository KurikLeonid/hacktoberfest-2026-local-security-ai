"""SQLite storage for events and the labelled dataset. Shared by proxy and API processes."""

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .policies import ROOT

DB_PATH = Path(os.environ.get("DLP_DB", ROOT / "data" / "dlp.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    host TEXT NOT NULL,
    path TEXT NOT NULL,
    adapter TEXT NOT NULL,
    text TEXT NOT NULL,
    tier TEXT NOT NULL,          -- ALLOW | REVIEW | BLOCK
    score REAL NOT NULL,
    findings TEXT NOT NULL,      -- JSON list
    status TEXT NOT NULL,        -- allowed | pending | blocked | approved | rejected | expired
    error TEXT,
    latency_ms INTEGER,
    decided_at REAL
);
CREATE INDEX IF NOT EXISTS events_created ON events(created_at);
CREATE TABLE IF NOT EXISTS dataset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    span TEXT,
    category TEXT NOT NULL,
    label TEXT NOT NULL CHECK (label IN ('sensitive', 'not_sensitive')),
    source TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS dataset_cat ON dataset(category, label);
"""


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as c:
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(events)")}
        if "purpose" not in cols:  # added in stage 2: work / non-work judgement
            c.execute("ALTER TABLE events ADD COLUMN purpose TEXT")


def _event(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["findings"] = json.loads(d["findings"])
    d["purpose"] = json.loads(d["purpose"]) if d.get("purpose") else None
    return d


# --- events -----------------------------------------------------------------

def insert_event(*, host, path, adapter, text, tier, score, findings, status, error=None, latency_ms=None, purpose=None) -> dict:
    ev = dict(
        id=uuid.uuid4().hex[:12], created_at=time.time(), host=host, path=path, adapter=adapter,
        text=text, tier=tier, score=score, findings=json.dumps(findings, ensure_ascii=False),
        status=status, error=error, latency_ms=latency_ms, decided_at=None,
        purpose=json.dumps(purpose, ensure_ascii=False) if purpose else None,
    )
    with connect() as c:
        c.execute(f"INSERT INTO events ({','.join(ev)}) VALUES ({','.join('?' * len(ev))})", list(ev.values()))
    return get_event(ev["id"])


def get_event(event_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    return _event(row) if row else None


def list_events(statuses: list[str] | None = None, limit: int = 200) -> list[dict]:
    q, args = "SELECT * FROM events", []
    if statuses:
        q += f" WHERE status IN ({','.join('?' * len(statuses))})"
        args += statuses
    q += " ORDER BY created_at DESC LIMIT ?"
    with connect() as c:
        return [_event(r) for r in c.execute(q, [*args, limit])]


def set_status(event_id: str, status: str, only_if: str | None = None) -> bool:
    q, args = "UPDATE events SET status=?, decided_at=? WHERE id=?", [status, time.time(), event_id]
    if only_if:
        q += " AND status=?"
        args.append(only_if)
    with connect() as c:
        return c.execute(q, args).rowcount > 0


def purpose_stats(since: float) -> dict:
    """Share of non-work requests per domain and top non-work topics since a timestamp."""
    with connect() as c:
        rows = c.execute("SELECT host, purpose FROM events WHERE created_at>=? AND purpose IS NOT NULL", (since,)).fetchall()
    by_host: dict[str, dict] = {}
    topics: dict[str, int] = {}
    for r in rows:
        p = json.loads(r["purpose"])
        h = by_host.setdefault(r["host"], {"host": r["host"], "total": 0, "non_work": 0})
        h["total"] += 1
        if not p.get("work", True):
            h["non_work"] += 1
            t = (p.get("topic") or "other").lower()
            topics[t] = topics.get(t, 0) + 1
    top = sorted(topics.items(), key=lambda x: -x[1])[:8]
    return {"domains": sorted(by_host.values(), key=lambda h: -h["total"]), "topics": [{"topic": t, "n": n} for t, n in top]}


# --- dataset ----------------------------------------------------------------

def add_examples(rows: list[dict], source: str) -> int:
    now = time.time()
    vals = [
        (r["text"], r.get("span"), r["category"], r["label"], r.get("source") or source, now)
        for r in rows
        if r.get("text") and r.get("category") and r.get("label") in ("sensitive", "not_sensitive")
    ]
    with connect() as c:
        c.executemany(
            "INSERT INTO dataset (text, span, category, label, source, created_at) VALUES (?,?,?,?,?,?)", vals
        )
    return len(vals)


def examples_for(category: str, k_each: int = 3, sources: str = "all") -> list[dict]:
    """Few-shot examples for a category: security decisions first, then random others, per label.
    sources="hf" restricts to imported HF rows (eval isolation)."""
    out = []
    src = "AND source LIKE 'hf:%'" if sources == "hf" else ""
    with connect() as c:
        for label in ("sensitive", "not_sensitive"):
            rows = c.execute(
                f"""SELECT text, span, category, label, source FROM dataset
                   WHERE category=? AND label=? {src}
                   ORDER BY (source='security') DESC, CASE WHEN source='security' THEN -created_at ELSE random() END
                   LIMIT ?""",
                (category, label, k_each),
            ).fetchall()
            out += [dict(r) for r in rows]
    return out


def list_dataset(limit: int = 500, offset: int = 0, category: str | None = None) -> tuple[list[dict], int]:
    where, args = ("WHERE category=?", [category]) if category else ("", [])
    with connect() as c:
        total = c.execute(f"SELECT COUNT(*) FROM dataset {where}", args).fetchone()[0]
        rows = c.execute(
            f"SELECT * FROM dataset {where} ORDER BY id DESC LIMIT ? OFFSET ?", [*args, limit, offset]
        ).fetchall()
    return [dict(r) for r in rows], total


def dataset_stats() -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT category, label, source, COUNT(*) n FROM dataset GROUP BY category, label, source"
        ).fetchall()
    return [dict(r) for r in rows]


def all_dataset() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM dataset ORDER BY id")]


def clear_dataset(source_prefix: str | None = None) -> int:
    with connect() as c:
        if source_prefix:
            return c.execute("DELETE FROM dataset WHERE source LIKE ?", (source_prefix + "%",)).rowcount
        return c.execute("DELETE FROM dataset").rowcount
