"""Discovery: web-search seeds + best-effort Meta Ad Library -> scored backlog."""
import json
import logging
import re
from urllib.parse import urlparse

from . import backlog

log = logging.getLogger(__name__)

SCORE_MODEL = "claude-haiku-4-5-20251001"

SCORE_SYSTEM = (
    "You score a fitness-business software platform as a candidate for a weekly "
    "competitor teardown aimed at an S&C / gym-management product (TeamBuildr OS). "
    "Return ONLY a JSON object: {\"novelty\": <0-1>, \"icp\": <0-1>}. "
    "novelty = how unusual/distinctive its approach is vs. the boilerplate CRM category. "
    "icp = relevance to gym/studio management or online fitness coaching (1=core, 0=unrelated)."
)


def extract_domain(url: str) -> str:
    host = urlparse(url if "//" in url else "https://" + url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_excluded(domain: str, exclude: list) -> bool:
    return any(term in domain for term in exclude)


def _guess_bucket(text: str) -> str:
    t = (text or "").lower()
    online = any(w in t for w in ("online coach", "coaching platform", "client app", "programming for coaches"))
    return "B" if online else "A"


def score_candidate(client, name, url, snippet, grounding_text) -> tuple:
    user = (
        f"Platform: {name}\nURL: {url}\n"
        f"Snippet: {(snippet or '')[:1500]}\n\n"
        f"Grounding (our product context):\n{grounding_text[:2000]}"
    )
    try:
        resp = client.messages.create(
            model=SCORE_MODEL,
            max_tokens=128,
            system=SCORE_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group(0) if match else raw)
        return float(data.get("novelty", 0.0)), float(data.get("icp", 0.0))
    except Exception as e:
        log.warning(f"score_candidate failed for {name}: {e}")
        return (0.0, 0.0)


def run_discovery(cfg, records, fc, client, grounding_text, today) -> int:
    exclude = cfg.get("exclude_domains", [])
    limit = cfg.get("search_limit", 8)
    added = 0
    for query in cfg.get("search_queries", []):
        for r in fc.search(query, limit=limit):
            domain = extract_domain(r["url"])
            if not domain or is_excluded(domain, exclude) or backlog.has_domain(records, domain):
                continue
            name = (r.get("title") or domain).split("|")[0].split("-")[0].strip()
            nov, icp = score_candidate(client, name, r["url"], r.get("markdown", ""), grounding_text)
            cand = backlog.new_candidate(
                domain, name, r["url"], _guess_bucket(r.get("markdown", "")),
                "websearch", today,
            )
            cand["novelty_score"], cand["icp_relevance"] = nov, icp
            if backlog.add(records, cand):
                added += 1
                log.info(f"discovered: {domain} (nov={nov}, icp={icp})")
    return added


def meta_ad_library_boost(cfg, records, fc, today) -> int:
    """Best-effort: scrape the public Ad Library search UI for advertiser domains.
    Any failure returns 0 and never propagates — this must not block delivery."""
    added = 0
    try:
        for query in cfg.get("meta_ad_library_queries", []):
            url = ("https://www.facebook.com/ads/library/?active_status=active"
                   f"&ad_type=all&country=US&q={query.replace(' ', '%20')}&media_type=all")
            md = fc.scrape(url)
            if not md:
                continue
            for m in re.findall(r"https?://[^\s)\]]+", md):
                domain = extract_domain(m)
                if (domain and "facebook" not in domain and "fbcdn" not in domain
                        and not is_excluded(domain, cfg.get("exclude_domains", []))
                        and not backlog.has_domain(records, domain)):
                    cand = backlog.new_candidate(domain, domain.split(".")[0], m, "A",
                                                 "meta_ad_library", today)
                    if backlog.add(records, cand):
                        added += 1
    except Exception as e:
        log.warning(f"meta_ad_library_boost skipped: {e}")
        return added
    return added
