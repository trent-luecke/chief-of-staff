"""Per-platform teardown: scrape + grounded Claude analysis."""
import hashlib
import logging
import re

log = logging.getLogger(__name__)

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
        },
        "required": ["description", "segment", "standout", "features", "pricing", "traction", "maturity", "os_takeaways", "jtbd"],
    },
}

_PAGE_PATHS = ["", "pricing", "features", "product", "about"]


def content_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def scrape_platform(fc, url: str) -> str | None:
    base = url.rstrip("/")
    home = fc.scrape(base + "/")
    if not home:
        return None
    parts = [home]
    for path in _PAGE_PATHS[1:]:
        md = fc.scrape(f"{base}/{path}")
        if md:
            parts.append(f"\n\n--- /{path} ---\n{md}")
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
