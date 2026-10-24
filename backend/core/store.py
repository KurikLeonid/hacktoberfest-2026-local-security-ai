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


def _event(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["findings"] = json.loads(d["findings"])
    return d


# --- events -----------------------------------------------------------------

def insert_event(*, host, path, adapter, text, tier, score, findings, status, error=None, latency_ms=None) -> dict:
    ev = dict(
        id=uuid.uuid4().hex[:12], created_at=time.time(), host=host, path=path, adapter=adapter,
        text=text, tier=tier, score=score, findings=json.dumps(findings, ensure_ascii=False),
        status=status, error=error, latency_ms=latency_ms, decided_at=None,
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


def examples_for(category: str, k_each: int = 3) -> list[dict]:
    """Few-shot examples for a category: security decisions first, then random others, per label."""
    out = []
    with connect() as c:
        for label in ("sensitive", "not_sensitive"):
            rows = c.execute(
                """SELECT text, span, category, label, source FROM dataset
                   WHERE category=? AND label=?
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
