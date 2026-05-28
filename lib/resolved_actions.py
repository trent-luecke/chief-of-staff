"""Resolved action items store — tracks which call action items Trent has marked done."""

from datetime import date

_STORE_KEY = "state/resolved_actions.json"


def load_all_resolved(storage) -> dict:
    """Returns full store: {person_slug: {name, resolved: [{text, resolved_date, call_title}]}}"""
    return storage.read_json(_STORE_KEY, default={})


def mark_resolved(
    storage,
    person_id: str,
    person_name: str,
    items: list[str],
    call_title: str,
) -> None:
    """Add items to the resolved list for person_id. Deduplicates by text."""
    store = load_all_resolved(storage)
    today = date.today().isoformat()
    entry = store.setdefault(person_id, {"name": person_name, "resolved": []})
    existing_texts = {r["text"] for r in entry["resolved"]}
    for item in items:
        if item not in existing_texts:
            entry["resolved"].append({
                "text": item,
                "resolved_date": today,
                "call_title": call_title,
            })
            existing_texts.add(item)
    storage.write_json(_STORE_KEY, store)


def get_resolved_for_tokens(storage, tokens: list[str]) -> list[dict]:
    """Return all resolved items for any person whose registry slug contains any token."""
    store = load_all_resolved(storage)
    results = []
    for slug, entry in store.items():
        if any(t in slug for t in tokens):
            results.extend(entry.get("resolved", []))
    return results
