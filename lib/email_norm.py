"""Normalize a raw email into a deal join key, or None if unusable."""
from __future__ import annotations

_INTERNAL_DOMAIN = "@teambuildr.com"


def normalize_email(raw: str | None) -> str | None:
    if not raw:
        return None
    e = raw.strip().lower()
    if "@" not in e:
        return None
    local, _, domain = e.partition("@")
    local = local.split("+", 1)[0]
    if not local or not domain:
        return None
    norm = f"{local}@{domain}"
    if norm.endswith(_INTERNAL_DOMAIN):
        return None
    return norm
