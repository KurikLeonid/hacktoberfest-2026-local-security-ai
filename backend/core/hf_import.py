"""One-time import of public Hugging Face datasets into the local dataset table.

Only the download talks to the internet; the data is stored locally and nothing is ever sent out.
"""

import ast
import csv
import io
import json
import random

import httpx

from . import store

GRETEL = "gretelai/gretel-pii-masking-en-v1"
SECRETS = "nisaefendioglu/synthetic-sensitive-data-in-source-code-n300"

SOURCES = {
    GRETEL: "PII and financial entities in realistic documents (apache-2.0)",
    SECRETS: "Secrets in source code + clean code + hard negatives (MIT)",
}

GRETEL_MAP = {
    **dict.fromkeys(
        ["name", "first_name", "last_name", "email", "phone_number", "address", "street_address", "ssn",
         "date_of_birth", "medical_record_number", "biometric_identifier", "license_plate",
         "certificate_license_number", "user_name"],
        ("pii", "sensitive"),
    ),
    **dict.fromkeys(["credit_card_number", "account_number", "bank_routing_number", "cvv", "iban"], ("financial", "sensitive")),
    **dict.fromkeys(["customer_id"], ("customer_data", "sensitive")),
    # look-alikes that are harmless on their own: hard negatives
    **dict.fromkeys(["date", "time", "country", "city", "company_name", "url"], ("pii", "not_sensitive")),
}


def _context(text: str, span: str, width: int = 160) -> str:
    i = text.find(span)
    if i < 0:
        return text[: width * 2]
    return text[max(0, i - width) : i + len(span) + width]


def import_gretel(client: httpx.Client, n_docs: int = 150) -> list[dict]:
    rows = []
    for offset in range(0, n_docs, 100):
        r = client.get(
            "https://datasets-server.huggingface.co/rows",
            params={"dataset": GRETEL, "config": "default", "split": "train", "offset": offset,
                    "length": min(100, n_docs - offset)},
        )
        r.raise_for_status()
        rows += [x["row"] for x in r.json()["rows"]]
    out = []
    for row in rows:
        ents = row["entities"]
        ents = ast.literal_eval(ents) if isinstance(ents, str) else ents
        taken = 0
        for e in ents:
            mapped = next((GRETEL_MAP[t] for t in e.get("types", []) if t in GRETEL_MAP), None)
            if not mapped or taken >= 3:
                continue
            cat, label = mapped
            out.append({"text": _context(row["text"], e["entity"]), "span": e["entity"], "category": cat, "label": label})
            taken += 1
    return out


def _csv(client: httpx.Client, path: str) -> list[dict]:
    r = client.get(f"https://huggingface.co/datasets/{SECRETS}/resolve/main/{path}", follow_redirects=True)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def import_secrets(client: httpx.Client, n_each: int = 100) -> list[dict]:
    rnd = random.Random(7)
    out = []
    pos = _csv(client, "synthetic_sensitive_data_in_source_code_n300.csv")
    for r in rnd.sample(pos, min(n_each, len(pos))):
        code = r["code_text"].replace("\\n", "\n")
        out.append({"text": code, "span": None, "category": "credentials", "label": "sensitive"})
    for path in ("extensions/clean_code_snippets_n300.csv", "extensions/hard_negatives_n300.csv"):
        neg = _csv(client, path)
        for r in rnd.sample(neg, min(n_each // 2, len(neg))):
            out.append({"text": r["code_text"], "span": None, "category": "credentials", "label": "not_sensitive"})
    return out


def import_hf(dataset_id: str) -> int:
    with httpx.Client(timeout=60) as client:
        if dataset_id == GRETEL:
            rows = import_gretel(client)
        elif dataset_id == SECRETS:
            rows = import_secrets(client)
        else:
            raise ValueError(f"no mapper for {dataset_id}; supported: {list(SOURCES)}")
    store.clear_dataset(f"hf:{dataset_id}")  # re-import replaces, does not duplicate
    return store.add_examples(rows, f"hf:{dataset_id}")


# --- user uploads & export --------------------------------------------------

def parse_upload(filename: str, data: bytes) -> list[dict]:
    """JSONL or CSV with columns text, category, label and optional span."""
    text = data.decode("utf-8-sig")
    if filename.lower().endswith(".csv"):
        rows = list(csv.DictReader(io.StringIO(text)))
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    for r in rows:
        if not r.get("span"):
            r["span"] = None
    return rows


def export_lora() -> str:
    """Chat-format JSONL for LoRA fine-tuning (e.g. Unsloth / HF TRL SFTTrainer)."""
    lines = []
    for r in store.all_dataset():
        frag = r["span"] or r["text"]
        lines.append(json.dumps({
            "messages": [
                {"role": "system", "content": "Classify whether the fragment is sensitive data that must not leave the company."},
                {"role": "user", "content": f"Category: {r['category']}\nContext: {r['text']}\nFragment: {frag}"},
                {"role": "assistant", "content": json.dumps({"is_sensitive": r["label"] == "sensitive"})},
            ],
            "source": r["source"],
        }, ensure_ascii=False))
    return "\n".join(lines) + "\n"
