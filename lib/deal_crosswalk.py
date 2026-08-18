"""email <-> account_name crosswalk (derived + manual overrides)."""
from __future__ import annotations

_KEY = "deal_crosswalk.json"

# Personal / free-email providers: a real person, but the domain carries no
# company identity, so no account name can be derived from it.
FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com",
    "outlook.com", "live.com", "msn.com", "icloud.com", "me.com", "mac.com",
    "aol.com", "proton.me", "protonmail.com", "gmx.com", "zoho.com",
}


def domain_to_name(email: str) -> str:
    if "@" not in email:
        return ""
    domain = email.split("@", 1)[1].lower()
    if domain in FREE_EMAIL_DOMAINS:
        return ""  # no derivable account — a human names it via the crosswalk
    core = domain.split(".")[0] if "." in domain else domain
    return core.replace("-", " ").replace("_", " ").title()


def load_crosswalk(storage, key: str = _KEY) -> dict[str, str]:
    return storage.read_json(key, default={}) or {}
