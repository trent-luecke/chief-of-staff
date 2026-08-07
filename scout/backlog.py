"""Candidate backlog data layer: JSONL load/save, dedup, selection."""
import json
from pathlib import Path


def new_candidate(domain, name, url, bucket, source, discovered_at, seed=False) -> dict:
    return {
        "domain": domain,
        "name": name,
        "url": url,
        "bucket": bucket,
        "source": source,
        "discovered_at": discovered_at,
        "novelty_score": 0.0,
        "icp_relevance": 0.0,
        "covered": False,
        "covered_at": None,
        "content_hash": None,
        "seed": seed,
    }


def load(path: Path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def save(records: list, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def has_domain(records: list, domain: str) -> bool:
    return any(r["domain"] == domain for r in records)


def add(records: list, cand: dict) -> bool:
    if has_domain(records, cand["domain"]):
        return False
    records.append(cand)
    return True


def mark_covered(records: list, domain: str, content_hash: str, covered_at: str) -> None:
    for r in records:
        if r["domain"] == domain:
            r["covered"] = True
            r["content_hash"] = content_hash
            r["covered_at"] = covered_at


def select_uncovered(records: list, n: int) -> list:
    uncovered = [r for r in records if not r.get("covered")]
    seeds = [r for r in uncovered if r.get("seed")]
    seeds.sort(key=lambda r: r.get("discovered_at", ""))          # oldest seed first
    rest = [r for r in uncovered if not r.get("seed")]
    rest.sort(key=lambda r: r.get("novelty_score", 0) + r.get("icp_relevance", 0), reverse=True)
    return (seeds + rest)[:n]
