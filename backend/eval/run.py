"""Eval harness: run the classifier over eval/cases.yaml and write a per-model report.

uv run python -m eval.run --provider gemini --runs 1
uv run python -m eval.run --provider ollama --model gemma4:e4b --runs 3 --timeout 60
uv run python -m eval.run --report-only

Isolated from the product: calls the classifier directly, never writes events or dataset rows.
"""

import argparse
import asyncio
import dataclasses
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path

import yaml

from core import classifier, policies, store

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPORT = policies.ROOT / "docs" / "EVAL.md"
STOPPED = {"REVIEW", "BLOCK"}


def outcome(expect: str, got: str) -> str:
    """ok | leak | false_block | soft"""
    if expect == "ALLOW":
        return "ok" if got == "ALLOW" else "false_block"
    if got == "ALLOW":
        return "leak"
    if expect == "STOP" or expect == got:
        return "ok"
    return "soft"  # REVIEW <-> BLOCK


BARE_SCHEMA = {
    "type": "object",
    "properties": {"safe": {"type": "boolean"}, "confidence": {"type": "number"}},
    "required": ["safe", "confidence"],
}


async def classify_bare(text, host, pol):
    """Baseline: the same model with no DLP layer (no categories, whitelist, examples or calibration)."""
    import httpx

    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=pol.model_timeout_s, trust_env=False) as client:
        out = await classifier._chat(
            client, pol.llm,
            "You protect company data. Decide if the user's message can be safely sent to the website below.",
            f"WEBSITE: {host}\nMESSAGE:\n{text}", BARE_SCHEMA, stage="baseline",
        )
    return {"tier": "ALLOW" if out.get("safe") else "BLOCK", "score": float(out.get("confidence", 0)),
            "findings": [], "purpose": None, "latency_ms": int((time.monotonic() - t0) * 1000)}


async def classify_retrying(text, host, pol, examples, retries=4):
    for attempt in range(retries):
        try:
            if examples == "bare":
                return await classify_bare(text, host, pol), None
            return await classifier.classify(text, host, pol, examples=examples), None
        except classifier.ClassifierError as e:
            msg = str(e)
            transient = any(s in msg for s in ("429", "503", "high demand", "unreachable"))
            if not transient or attempt == retries - 1:
                return None, msg
            await asyncio.sleep(20 * (attempt + 1))


async def run(args):
    store.init()
    cases = yaml.safe_load((HERE / "cases.yaml").read_text())
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in keep or c["group"] in keep]
    classifier.PROVIDER = args.provider
    pol = policies.load()
    if args.provider == "gemini":
        classifier.GEMINI_MODEL = args.model or classifier.GEMINI_MODEL
        model = classifier.GEMINI_MODEL
    else:
        model = args.model or pol.llm
    pol = dataclasses.replace(pol, llm=model, model_timeout_s=args.timeout or pol.model_timeout_s)
    min_gap = 2 * 60 / args.rpm if args.rpm else 0  # up to 2 model calls per classification

    rows, total = [], sum(len(c["expect"]) for c in cases) * args.runs
    started = time.time()
    for run_i in range(args.runs):
        for c in cases:
            for host, expect in c["expect"].items():
                t0 = time.monotonic()
                res, err = await classify_retrying(c["text"], host, pol, args.examples)
                got = res["tier"] if res else "BLOCK"  # fail-closed, as in the proxy
                found = sorted({f["category"] for f in (res or {}).get("findings", []) if not f["allowed"] and f.get("is_sensitive")})
                purpose = (res or {}).get("purpose") or {}
                row = {
                    "run": run_i, "id": c["id"], "group": c["group"], "lang": c["lang"], "host": host,
                    "expect": expect, "got": got, "outcome": outcome(expect, got),
                    "score": res["score"] if res else None, "found": found, "want": c.get("categories", []),
                    "purpose_expect": c.get("purpose"),
                    "purpose_got": None if not purpose else ("work" if purpose["work"] else "non_work"),
                    "topic": purpose.get("topic"), "latency_ms": res["latency_ms"] if res else None, "error": err,
                    "findings": [
                        {k: f.get(k) for k in ("category", "span", "allowed", "is_sensitive", "confidence")}
                        for f in (res or {}).get("findings", [])
                    ],
                }
                rows.append(row)
                mark = {"ok": "✓", "leak": "LEAK", "false_block": "FALSE-BLOCK", "soft": "soft"}[row["outcome"]]
                print(f"[{len(rows)}/{total}] {c['id']:<24} {host:<12} want {expect:<6} got {got:<6} {mark}"
                      f"{' ERR ' + err[:60] if err else ''}", flush=True)
                wait = min_gap - (time.monotonic() - t0)
                if wait > 0:
                    await asyncio.sleep(wait)

    RESULTS.mkdir(exist_ok=True)
    meta = {"provider": args.provider, "model": model, "examples": args.examples, "runs": args.runs,
            "subset": len(cases) if args.only else None,
            "timeout_s": pol.model_timeout_s, "thresholds": {"review": pol.review, "block": pol.block},
            "started": started, "duration_s": round(time.time() - started)}
    out = RESULTS / f"{args.provider}-{model.replace(':', '_')}-{args.examples}-{int(started)}.json"
    out.write_text(json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False, indent=1))
    print(f"\nsaved {out.relative_to(policies.ROOT)}")


# --- report -----------------------------------------------------------------------------------------

def summarize(data: dict) -> dict:
    rows = data["rows"]
    n = len(rows)
    count = lambda o: sum(r["outcome"] == o for r in rows)
    lat = sorted(r["latency_ms"] for r in rows if r["latency_ms"] is not None)
    want = [(r, c) for r in rows for c in r["want"]]
    purpose = [r for r in rows if r["purpose_got"]]
    by_case = defaultdict(set)
    for r in rows:
        by_case[(r["id"], r["host"])].add(r["got"])
    return {
        "n": n,
        "accuracy": sum(r["outcome"] == "ok" for r in rows) / n,
        "leaks": count("leak"),
        "false_blocks": count("false_block"),
        "soft": count("soft"),
        "errors": sum(bool(r["error"]) for r in rows),
        "recall": sum(c in r["found"] for r, c in want) / len(want) if want else 1,
        "purpose_acc": sum(r["purpose_got"] == r["purpose_expect"] for r in purpose) / len(purpose) if purpose else 0,
        "p50": statistics.median(lat) if lat else None,
        "p95": lat[int(len(lat) * 0.95) - 1] if lat else None,
        "unstable": sorted(f"{i}@{h}" for (i, h), tiers in by_case.items() if len(tiers) > 1),
    }


def report():
    latest = {}
    for f in sorted(RESULTS.glob("*.json")):
        d = json.loads(f.read_text())
        m = d["meta"]
        latest[(m["provider"], m["model"], m["examples"], m.get("subset"))] = d  # sorted by name -> last wins
    if not latest:
        print("no results yet")
        return
    pct = lambda x: f"{x * 100:.0f}%"
    ms = lambda x: f"{x / 1000:.1f}s" if x is not None else "—"
    lines = [
        "# Eval: сравнение моделей",
        "",
        "Генерируется `uv run python -m eval.run` (или `--report-only`). Набор кейсов: [`backend/eval/cases.yaml`](../backend/eval/cases.yaml).",
        "Eval изолирован: классификатор вызывается напрямую, события и датасет не меняются.",
        "",
        "- **Утечка**: ждали REVIEW/BLOCK, пришёл ALLOW. Главная метрика, цель 0.",
        "- **Ложный блок**: ждали ALLOW, пришёл REVIEW или BLOCK.",
        "- **Мягкая**: REVIEW вместо BLOCK или наоборот (запрос всё равно остановлен).",
        "- **Полнота**: доля ожидаемых категорий, которые модель нашла как нарушение.",
        "- **Цель**: точность определения «рабочий / нецелевой запрос».",
        "- **Ошибки**: сбои модели или таймауты, в проде это BLOCK (fail-closed).",
        "- **Примеры = bare**: baseline, та же модель без слоя Duh'ot'A (один вопрос «можно ли отправить на домен?»).",
        "",
        "| Модель | Примеры | Кейсов | Прогонов | Проверок | Точность | Утечки | Ложные блоки | Мягкие | Ошибки | Полнота | Цель | p50 | p95 | Нестабильных |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    sums = {}
    for key, d in sorted(latest.items(), key=lambda kv: str(kv[0])):
        s = sums[key] = summarize(d)
        m = d["meta"]
        lines.append(
            f"| {m['provider']} `{m['model']}` | {m['examples']} | {m.get('subset') or 'все'} | {m['runs']} | {s['n']} | {pct(s['accuracy'])} | "
            f"**{s['leaks']}** | {s['false_blocks']} | {s['soft']} | {s['errors']} | {pct(s['recall'])} | "
            f"{pct(s['purpose_acc'])} | {ms(s['p50'])} | {ms(s['p95'])} | {len(s['unstable'])} |"
        )
    for key, d in sorted(latest.items(), key=lambda kv: str(kv[0])):
        m, s = d["meta"], sums[key]
        lines += ["", f"## {m['provider']} `{m['model']}`, примеры: {m['examples']}, кейсов: {m.get('subset') or 'все'}",
                  f"Пороги: REVIEW ≥ {m['thresholds']['review']}, BLOCK ≥ {m['thresholds']['block']}; "
                  f"таймаут {m['timeout_s']} с; длительность {m['duration_s'] // 60} мин.", ""]
        groups = defaultdict(list)
        for r in d["rows"]:
            groups[r["group"]].append(r)
        lines += ["| Группа | Проверок | Верно | Утечки | Ложные блоки | Мягкие |", "|---|---|---|---|---|---|"]
        for g, rs in groups.items():
            c = lambda o: sum(r["outcome"] == o for r in rs)
            lines.append(f"| {g} | {len(rs)} | {c('ok')} | {c('leak')} | {c('false_block')} | {c('soft')} |")
        bad = [r for r in d["rows"] if r["outcome"] != "ok" or (r["purpose_got"] and r["purpose_got"] != r["purpose_expect"])]
        if bad:
            lines += ["", "Ошибки по кейсам:", "", "| Кейс | Домен | Прогон | Ждали | Получили | Score | Нашла | Цель | Примечание |",
                      "|---|---|---|---|---|---|---|---|---|"]
            for r in bad:
                note = r["error"][:60] if r["error"] else r["outcome"]
                purpose = r["purpose_got"] or "—"
                if r["purpose_got"] and r["purpose_got"] != r["purpose_expect"]:
                    purpose = f"**{purpose}** (ждали {r['purpose_expect']})"
                lines.append(f"| {r['id']} | {r['host']} | {r['run']} | {r['expect']} | {r['got']} | {r['score']} | "
                             f"{', '.join(r['found']) or '—'} | {purpose} | {note} |")
        if s["unstable"]:
            lines += ["", "Нестабильные между прогонами: " + ", ".join(f"`{u}`" for u in s["unstable"])]
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"report: {REPORT.relative_to(policies.ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "ollama"], default=classifier.PROVIDER)
    ap.add_argument("--model", help="override model name")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--examples", choices=["hf", "all", "bare"], default="hf",
                    help="bare = baseline: the same model without the DLP layer")
    ap.add_argument("--rpm", type=int, default=0, help="model calls per minute limit (gemini free tier)")
    ap.add_argument("--timeout", type=int, help="override model timeout, seconds")
    ap.add_argument("--only", help="comma-separated case ids or groups")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    if not a.report_only:
        asyncio.run(run(a))
    report()
