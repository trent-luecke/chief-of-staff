# lib/account_match.py
"""Match free-text account names (Feature Requests "Requesting Account",
survey "Account" answers) to canonical OS account names."""
import re
from difflib import SequenceMatcher

UNCERTAIN_FLOOR = 0.75
_SUFFIXES = ("llc", "inc", "ltd", "co")
_SPLIT = re.compile(r"\s*(?:,|;|/|\n|\band\b)\s*", re.I)


def normalize_name(name):
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    words = s.split()
    if words and words[0] == "the":
        words = words[1:]
    while words and words[-1] in _SUFFIXES:
        words = words[:-1]
    return " ".join(words)


def _score(n, a):
    if a == n:
        return 1.0
    nt, at = n.split(), a.split()
    if nt and at[:len(nt)] == nt:  # "Full Throttle" → "Full Throttle Fitness & Performance"
        return 0.95
    if nt and set(nt) <= set(at):  # "Ryan Boylen" → "Sthenos Athletics (Ryan Boylen)"
        return 0.9
    return SequenceMatcher(None, n, a).ratio()


def _best(part, accounts):
    """(score, account, ambiguous) — ambiguous when another account ties the top score."""
    n = normalize_name(part)
    scored = sorted(((_score(n, normalize_name(a)), a) for a in accounts), reverse=True)
    if not scored:
        return 0.0, None, False
    top = scored[0]
    ambiguous = len(scored) > 1 and scored[1][0] == top[0] and top[0] < 1.0
    return top[0], top[1], ambiguous


def match_accounts(raw, accounts, threshold=0.88):
    raw = (raw or "").strip()
    out = {"matched": [], "uncertain": [], "unmatched": []}
    if not raw:
        return out
    parts = [p for p in _SPLIT.split(raw) if p.strip()]
    # Only split when every part stands on its own; "Beyond Our Best, LLC" stays whole.
    if len(parts) > 1 and not all(_best(p, accounts)[0] >= threshold for p in parts):
        whole = _best(raw, accounts)
        if whole[0] >= UNCERTAIN_FLOOR or len(parts) == 1:
            parts = [raw]
    for part in parts:
        score, acct, ambiguous = _best(part, accounts)
        hit = {"input": part.strip(), "account": acct, "score": round(score, 3)}
        if score >= threshold and not ambiguous:
            out["matched"].append(hit)
        elif score >= UNCERTAIN_FLOOR:
            out["uncertain"].append(hit)
        else:
            out["unmatched"].append(part.strip())
    return out
