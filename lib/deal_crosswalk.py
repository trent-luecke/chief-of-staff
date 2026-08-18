"""email <-> account_name crosswalk (derived + manual overrides)."""
from __future__ import annotations

_KEY = "deal_crosswalk.json"


def domain_to_name(email: str) -> str:
    if "@" not in email:
        return ""
    domain = email.split("@", 1)[1]
    core = domain.split(".")[0] if "." in domain else domain
    return core.replace("-", " ").replace("_", " ").title()


def load_crosswalk(storage, key: str = _KEY) -> dict[str, str]:
    return storage.read_json(key, default={}) or {}
