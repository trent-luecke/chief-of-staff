"""Discovery: web-search seeds + best-effort Meta Ad Library -> scored backlog."""
import json
import logging
import re
from urllib.parse import urlparse

from . import backlog

log = logging.getLogger(__name__)

_ARTICLE_URL_RE = re.compile(
    r"/(blog|blogs|article|articles|news|guide|guides|resources|review|reviews|"
    r"compare|comparison|vs|best-|top-|how-to)(/|-|$)|/20[12]\d(/|$)", re.I)
_ARTICLE_TITLE_RE = re.compile(
    r"\b(best|top \d|top-\d|review|reviews|vs\.?|versus|alternatives?|roundup|"
    r"guide to|how to|20[12]\d)\b", re.I)


def looks_like_article(url: str, title: str = "") -> bool:
    """Heuristic: does this URL/title read as an article/roundup/review rather
    than a product's own site? Conservative — real platform homepages rarely
    have /blog, a year, or 'best/top/review/vs' in the URL or title."""
    if _ARTICLE_URL_RE.search(url or ""):
        return True
    if _ARTICLE_TITLE_RE.search(title or ""):
        return True
    return False


AGGREGATOR_HOSTS = {
    "producthunt.com", "reddit.com", "facebook.com", "fb.com", "google.com",
    "youtube.com", "twitter.com", "x.com", "linkedin.com", "medium.com",
    "github.com", "wikipedia.org", "apps.apple.com", "play.google.com",
    "g2.com", "capterra.com", "trustpilot.com", "getapp.com", "quora.com",
}

SCORE_MODEL = "claude-haiku-4-5-20251001"

SCORE_SYSTEM = (
    "You score a fitness-business software platform as a candidate for a weekly "
    "competitor teardown aimed at an S&C / gym-management product (TeamBuildr OS). "
    "novelty = how unusual/distinctive its approach is vs. the boilerplate CRM category. "
    "icp = relevance to gym/studio management or online fitness coaching (1=core, 0=unrelated). "
    "Return ONLY a JSON object: "
    "{\"novelty\": <0-1>, \"icp\": <0-1>, \"is_platform\": <true|false>}. "
    "is_platform = true only if the URL is an actual fitness-business software "
    "product's OWN site (homepage, product, or pricing page for a company that "
    "SELLS the software); false if it is a review article, blog post, \"best of\" "
    "roundup, listicle, news story, directory, or any page merely writing ABOUT "
    "such platforms."
)


_MULTI_TLDS = {"co", "com", "org", "net", "gov", "ac", "edu"}


def extract_domain(url: str) -> str:
    host = urlparse(url if "//" in url else "https://" + url).netloc.lower()
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return host
    if parts[-2] in _MULTI_TLDS:
        return ".".join(parts[-3:])   # e.g. foo.co.uk
    return ".".join(parts[-2:])       # collapse subdomains -> registrable domain


def is_excluded(domain: str, exclude: list) -> bool:
    return any(term in domain for term in exclude)


def _guess_bucket(text: str) -> str:
    t = (text or "").lower()
    online = any(w in t for w in ("online coach", "coaching platform", "client app", "programming for coaches"))
    return "B" if online else "A"


def score_candidate(client, name, url, snippet, grounding_text) -> dict:
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
        return {
            "novelty": float(data.get("novelty", 0.0)),
            "icp": float(data.get("icp", 0.0)),
            "is_platform": bool(data.get("is_platform", True)),
        }
    except Exception as e:
        log.warning(f"score_candidate failed for {name}: {e}")
        # default is_platform True so a transient scoring error never silently
        # drops a real platform — it just banks with a low score that won't
        # get selected.
        return {"novelty": 0.0, "icp": 0.0, "is_platform": True}


def run_discovery(cfg, records, fc, client, grounding_text, today) -> int:
    exclude = cfg.get("exclude_domains", [])
    limit = cfg.get("search_limit", 8)
    added = 0
    for query in cfg.get("search_queries", []):
        for r in fc.search(query, limit=limit):
            domain = extract_domain(r["url"])
            if (not domain or domain in AGGREGATOR_HOSTS
                    or is_excluded(domain, exclude) or backlog.has_domain(records, domain)):
                continue
            if looks_like_article(r["url"], r.get("title", "")):
                log.info(f"skipped article: {r['url']}")
                continue
            name = (r.get("title") or domain).split("|")[0].split("-")[0].strip()
            score = score_candidate(client, name, r["url"], r.get("markdown", ""), grounding_text)
            if not score.get("is_platform", True):
                log.info(f"skipped non-platform: {domain}")
                continue
            cand = backlog.new_candidate(
                domain, name, f"https://{domain}/", _guess_bucket(r.get("markdown", "")),
                "websearch", today,
            )
            cand["novelty_score"], cand["icp_relevance"] = score["novelty"], score["icp"]
            if backlog.add(records, cand):
                added += 1
                log.info(f"discovered: {domain} (nov={score['novelty']}, icp={score['icp']})")
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
                        and domain not in AGGREGATOR_HOSTS
                        and not is_excluded(domain, cfg.get("exclude_domains", []))
                        and not backlog.has_domain(records, domain)
                        and not looks_like_article(m, "")):
                    cand = backlog.new_candidate(domain, domain.split(".")[0], f"https://{domain}/", "A",
                                                 "meta_ad_library", today)
                    if backlog.add(records, cand):
                        added += 1
    except Exception as e:
        log.warning(f"meta_ad_library_boost skipped: {e}")
        return added
    return added


def rebuild_backlog(records: list, exclude=None) -> tuple:
    """Deterministic UNCOVERED-backlog cleanup (no API, no brand-name judgment):
    collapse subdomains, drop aggregators/excluded, normalize url to the domain
    homepage, dedup by domain. Covered history untouched. Idempotent.
    Returns (kept_count, dropped_count). (Platform-vs-article is judged later,
    on scraped homepage content, in teardown.analyze.)"""
    exclude = exclude or []
    seen = set()
    kept, dropped = [], 0
    for r in records:
        if r.get("covered"):
            seen.add(r.get("domain"))
    for r in records:
        if r.get("covered"):
            kept.append(r)
            continue
        dom = extract_domain(r.get("url") or f"https://{r.get('domain', '')}/")
        if not dom or dom in AGGREGATOR_HOSTS or is_excluded(dom, exclude) or dom in seen:
            log.info(f"rebuild dropped: {r.get('domain')} -> {dom or '(none)'}")
            dropped += 1
            continue
        r["domain"] = dom
        r["url"] = f"https://{dom}/"
        seen.add(dom)
        kept.append(r)
    records[:] = kept
    return len(kept), dropped


def prune_articles(records: list) -> int:
    """Drop UNCOVERED article-like candidates already in the backlog (cheap,
    no API). Idempotent — safe to run every time. Leaves covered history alone."""
    removed = 0
    keep = []
    for r in records:
        if not r.get("covered") and looks_like_article(r.get("url", ""), r.get("name", "")):
            log.info(f"pruned article-like candidate: {r.get('domain')}")
            removed += 1
            continue
        keep.append(r)
    records[:] = keep
    return removed
