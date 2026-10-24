"""Policy file loading, validation and hot reload."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = Path(os.environ.get("DLP_POLICIES", ROOT / "policies.yaml"))


@dataclass
class Policies:
    categories: list[str]
    never_allowed: list[str]
    review: float
    block: float
    review_timeout_s: int
    model_timeout_s: int
    llm: str
    fallback: str
    inspect_domains: list[str]
    domains: dict[str, list[str]]
    skip_paths: list[str]
    min_text_chars: int
    raw: dict = field(repr=False, default_factory=dict)

    def match_domain(self, host: str, domains: list[str]) -> str | None:
        host = host.lower().rstrip(".")
        for d in domains:
            if host == d or host.endswith("." + d):
                return d
        return None

    def is_inspected(self, host: str) -> bool:
        return self.match_domain(host, self.inspect_domains) is not None

    def allowed_categories(self, host: str) -> set[str]:
        d = self.match_domain(host, list(self.domains))
        allowed = set(self.domains.get(d, [])) if d else set()
        return allowed - set(self.never_allowed)

    def should_skip(self, path: str) -> bool:
        return any(re.search(p, path) for p in self.skip_paths)

    def tier(self, score: float) -> str:
        if score >= self.block:
            return "BLOCK"
        if score >= self.review:
            return "REVIEW"
        return "ALLOW"


def parse(raw: dict) -> Policies:
    cats = raw.get("categories") or []
    if not cats:
        raise ValueError("categories must not be empty")
    domains = raw.get("domains") or {}
    for d, allowed in domains.items():
        unknown = set(allowed or []) - set(cats)
        if unknown:
            raise ValueError(f"domain {d}: unknown categories {sorted(unknown)}")
    th = raw.get("thresholds") or {}
    review, block = float(th.get("review", 0.5)), float(th.get("block", 0.85))
    if not 0 <= review <= block <= 1:
        raise ValueError("thresholds must satisfy 0 <= review <= block <= 1")
    for p in raw.get("skip_paths") or []:
        re.compile(p)
    models = raw.get("models") or {}
    return Policies(
        categories=cats,
        never_allowed=raw.get("never_allowed") or [],
        review=review,
        block=block,
        review_timeout_s=int(raw.get("review_timeout_s", 60)),
        model_timeout_s=int(raw.get("model_timeout_s", 15)),
        llm=models.get("llm", "gemma4:e4b"),
        fallback=models.get("fallback", "gemma4:e2b"),
        inspect_domains=raw.get("inspect_domains") or [],
        domains={d: list(a or []) for d, a in domains.items()},
        skip_paths=raw.get("skip_paths") or [],
        min_text_chars=int(raw.get("min_text_chars", 12)),
        raw=raw,
    )


def parse_yaml(text: str) -> Policies:
    return parse(yaml.safe_load(text) or {})


_cache: tuple[float, Policies] | None = None


def load() -> Policies:
    """Return current policies, re-reading the file when its mtime changes."""
    global _cache
    mtime = POLICY_PATH.stat().st_mtime
    if _cache is None or _cache[0] != mtime:
        _cache = (mtime, parse_yaml(POLICY_PATH.read_text()))
    return _cache[1]


def save_yaml(text: str) -> Policies:
    pol = parse_yaml(text)  # validate before writing
    POLICY_PATH.write_text(text)
    return pol


def save(raw: dict) -> Policies:
    pol = parse(raw)
    POLICY_PATH.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
    return pol
