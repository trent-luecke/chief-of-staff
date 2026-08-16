"""Per-platform teardown: scrape + grounded Claude analysis."""
import hashlib
import logging
import re
from urllib.parse import urlparse

from . import discovery

log = logging.getLogger(__name__)

# Path keywords ranked by teardown value; a sub-page's score is the highest
# tier whose keyword appears in its URL path. Score 0 → not scraped.
_PATH_KEYWORDS = {
    "pricing": 3, "plan": 3, "cost": 3,
    "feature": 2, "product": 2, "tour": 2, "how-it-works": 2,
    "platform": 2, "solution": 2, "demo": 2,
    "about": 1,
}

ANALYSIS_MODEL = "claude-opus-4-8"

ANALYSIS_SYSTEM = """You are a competitive-intelligence analyst producing a teardown of an \
emerging fitness-business / gym-management / online-coaching software platform for the VP of \
Sales at TeamBuildr OS. Your job is feature idea-mining.

You are given (a) the platform's scraped marketing pages and (b) a GROUNDING PROFILE of \
TeamBuildr OS (its strengths, gaps, market fit, JTBD, and two tagging schemes).

Rules — read carefully:
- Assign every OS-relevance tag and JTBD verdict ONLY by looking up against the GROUNDING \
PROFILE text. NEVER invent OS strategy, roadmap, or positioning. If something does not map \
cleanly, tag it "❓ Your call".
- Lean by default: a missing feature is "🎯 Real gap" ONLY if it hits real ICP pain named in \
the grounding. Bells-and-whistles OS deliberately skipped → "🚫 Out of scope".
- Competitor AI features → "🎯 Real gap" tagged "in progress" (never a blind-spot alarm).
- For JTBD: read the platform's own JTBD from its copy, then pick exactly one verdict \
(📣 Positioning gap / 🎯 Real job gap / ➖ Different job). If 📣, quote the platform's exact \
positioning line.
- Also set is_platform: true if the scraped pages are an actual fitness-business / gym-management \
/ online-coaching SOFTWARE PRODUCT's OWN site (its homepage, product, or pricing pages — a \
company that sells or offers the software); false if the pages are a review article, "best-of"/ \
"top-N" listicle, news story, market-research report, app directory/marketplace, blog post, or \
forum thread. Judge ONLY from the page content in front of you — NOT from whether you recognize \
the brand. Many real products here are small, new, and unknown, so an unfamiliar name is NOT \
evidence against being a platform.

Call the `emit_teardown` tool with your analysis. Do not write any prose outside the tool call."""

TEARDOWN_TOOL = {
    "name": "emit_teardown",
    "description": "Return the structured competitor teardown.",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "segment": {"type": "string"},
            "standout": {"type": "string"},
            "features": {"type": "array", "items": {"type": "string"}},
            "pricing": {"type": "string"},
            "traction": {"type": "string"},
            "maturity": {"type": "string"},
            "os_takeaways": {"type": "array", "items": {
                "type": "object",
                "properties": {"feature": {"type": "string"}, "tag": {"type": "string"}, "note": {"type": "string"}},
                "required": ["feature", "tag", "note"]}},
            "jtbd": {"type": "object", "properties": {
                "platform_jtbd": {"type": "string"}, "verdict": {"type": "string"},
                "note": {"type": "string"}, "quoted_line": {"type": "string"}},
                "required": ["platform_jtbd", "verdict", "note"]},
            "is_platform": {"type": "boolean"},
        },
        "required": ["description", "segment", "standout", "features", "pricing", "traction", "maturity", "os_takeaways", "jtbd", "is_platform"],
    },
}

# Legacy blind-guess paths, used only as a fallback when the homepage
# exposes no usable links to guide selection.
_FALLBACK_PATHS = ["pricing", "features"]


def _path_score(url: str) -> int:
    path = urlparse(url).path.lower()
    scores = [w for kw, w in _PATH_KEYWORDS.items() if kw in path]
    return max(scores) if scores else 0


def select_subpages(base_url: str, links: list, limit: int = 3) -> list:
    """Pick the most teardown-relevant same-domain sub-pages from a link list.

    Ranks by keyword tier (pricing/plans > features/product/tour > about),
    drops the homepage, off-domain links, and irrelevant paths, dedups on the
    normalized (no trailing slash) URL, and returns at most `limit` URLs.
    """
    base_domain = discovery.extract_domain(base_url)
    home = base_url.rstrip("/")
    seen = set()
    scored = []
    for link in links:
        if discovery.extract_domain(link) != base_domain:
            continue
        norm = link.rstrip("/")
        if norm == home or norm in seen:
            continue
        seen.add(norm)
        score = _path_score(norm)
        if score > 0:
            scored.append((score, norm))
    scored.sort(key=lambda t: (-t[0], t[1]))  # tier desc, then URL for determinism
    return [u for _, u in scored[:limit]]


def content_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def scrape_platform(fc, url: str, max_subpages: int = 3) -> str | None:
    base = url.rstrip("/")
    home, links = fc.scrape_with_links(base + "/")
    if not home:
        return None
    parts = [home]
    subpages = select_subpages(base + "/", links, limit=max_subpages)
    if not subpages:  # homepage exposed no usable links → legacy blind guesses
        subpages = [f"{base}/{p}" for p in _FALLBACK_PATHS]
    for sub in subpages:
        md = fc.scrape(sub)
        if md:
            label = sub[len(base):].strip("/") or "home"
            parts.append(f"\n\n--- /{label} ---\n{md}")
    return "\n".join(parts)


def analyze(candidate: dict, fc, client, grounding_text: str) -> dict | None:
    content = scrape_platform(fc, candidate["url"])
    if not content:
        log.warning(f"scrape failed, skipping: {candidate['domain']}")
        return None

    user = (
        f"PLATFORM: {candidate['name']} ({candidate['url']})\n\n"
        f"=== SCRAPED PAGES ===\n{content[:18000]}\n\n"
        f"=== GROUNDING PROFILE (TeamBuildr OS) ===\n{grounding_text}"
    )
    try:
        resp = client.messages.create(
            model=ANALYSIS_MODEL,
            max_tokens=4096,
            system=ANALYSIS_SYSTEM,
            tools=[TEARDOWN_TOOL],
            tool_choice={"type": "tool", "name": "emit_teardown"},
            messages=[{"role": "user", "content": user}],
        )
        data = None
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "emit_teardown":
                data = block.input
                break
    except Exception as e:
        log.error(f"analysis failed for {candidate['domain']}: {e}")
        return None
    if not isinstance(data, dict):
        log.error(f"analysis returned no tool_use for {candidate['domain']}")
        return None

    data["name"] = candidate["name"]
    data["url"] = candidate["url"]
    data["bucket"] = candidate.get("bucket", "A")
    data["content_hash"] = content_hash(content)
    return data
