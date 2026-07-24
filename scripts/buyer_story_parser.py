#!/usr/bin/env python3
"""Buyer's-story parser — Avoma transcript → structured buyer's-story card.

Turns a recorded post-signing buyer's-story interview (in Avoma) into a review
draft whose fields map 1:1 to the "🎯 Buyer's Story Interviews" Notion database
(inside TeamBuildr OS HQ → Product & Engineering). You skim/fix the draft, then
the JSON block at the bottom is used to create the Notion entry (via the Notion
MCP in a Claude session — no Notion token needed in this script).

This is a sibling of scripts/interview_parser.py (the JTBD tracker). It reuses
that module's Avoma-fetch machinery and swaps in a buyer's-story extraction
schema + system prompt. The goal (Layer 1 of the buyer's-story program): capture
WHY they bought, what almost stopped them, and their EXACT language — to sharpen
win-theme messaging and build a reference/case-study pipeline.

Commands:
  parse   Fetch an Avoma interview, extract, write a review draft.

Auth: AVOMA_API_KEY + ANTHROPIC_API_KEY (read from .env). No Google/Notion scope
needed — parsing is read-only against Avoma + Anthropic; the Notion write is a
separate, reviewed step.

Examples:
  python3 scripts/buyer_story_parser.py parse --uuid 5835ccc6-df0e-40d6-98ac-59f9fba03deb
  python3 scripts/buyer_story_parser.py parse --date 2026-07-21 --title "Baxter"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Reuse the proven Avoma fetch machinery from the JTBD parser.
from scripts.interview_parser import _fetch_interview, _find_uuid  # noqa: E402

MODEL = "claude-opus-4-8"  # interviews are few and high-value — quality over cost
TRANSCRIPT_CHAR_LIMIT = 60_000

STATE_DIR = PROJECT_ROOT / "data" / "state" / "buyer_stories"

# The Notion database this feeds (Product & Engineering → Buyer's Story Interviews).
NOTION_DB_URL = "https://app.notion.com/p/2e6310527475464caf682de6d415d056"
NOTION_DATA_SOURCE_ID = "afdfc084-80d5-4451-82b6-5f1eb8c467b0"

# Enum values MUST match the Notion select/multi-select options exactly.
SEGMENTS = ["Private gym / performance", "Hybrid clinic-gym", "College / team",
            "CrossFit / group", "Other", "unclear"]
PRODUCTS = ["OS", "Strength", "Both", "unclear"]
DECISION_DRIVERS = ["Consolidation / OS as hub", "Programming depth", "Member app",
                    "Price / value", "Migration ease", "Support / relationship",
                    "Ease of use", "Reputation / referral", "Specific feature"]
REFERENCE = ["Yes", "Maybe", "No", "Not asked"]
CASE_STUDY = ["Strong", "Possible", "No"]


# --------------------------------------------------------------------------
# Buyer's-story extraction
# --------------------------------------------------------------------------

_TOOL = {
    "name": "extract",
    "description": "Extract the buyer's story from a post-signing customer interview transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "account": {"type": "string", "description": "Account / facility / interviewee name."},
            "segment": {"type": "string", "enum": SEGMENTS,
                        "description": "Facility type. Use 'unclear' if not evident from the transcript."},
            "product": {"type": "string", "enum": PRODUCTS,
                        "description": "Which TeamBuildr product they bought: OS (business ops), Strength (programming/AMS), or Both. 'unclear' if not evident."},
            "primary_driver": {"type": "string",
                               "description": "Their single most important reason for buying, in THEIR words (quote or close paraphrase). One sentence."},
            "decision_drivers": {"type": "array", "items": {"type": "string", "enum": DECISION_DRIVERS},
                                 "description": "All factors that genuinely moved the decision. Tag only what the CUSTOMER emphasized, not what the interviewer suggested. Omit any that don't clearly apply."},
            "trigger_event": {"type": "string",
                              "description": "What was going on that made them start looking — the 'why now', in their words."},
            "prior_solution": {"type": "string",
                               "description": "What they used or did before (a competing tool, spreadsheets, a manual process, nothing)."},
            "alternatives_considered": {"type": "string",
                                        "description": "Other tools/vendors they seriously evaluated and why those fell short. 'None named' if they didn't shop around."},
            "near_miss_objection": {"type": "string",
                                    "description": "What almost stopped the deal — the hesitation, risk, or objection they nearly walked on. This is the most valuable field; be specific. 'None surfaced' only if truly none."},
            "deciding_moment": {"type": "string",
                                "description": "The moment or realization that tipped them to yes."},
            "buying_committee": {"type": "string",
                                 "description": "Who else was involved in the decision and what each of them cared about. 'Sole decision-maker' if just them."},
            "killer_quotes": {"type": "array", "items": {"type": "string"},
                              "description": "1-3 verbatim customer lines worth reusing in messaging or a case study. Exact words, no paraphrasing."},
            "reference_willing": {"type": "string", "enum": REFERENCE,
                                  "description": "Did they signal willingness to be a reference? 'Not asked' if the interviewer never raised it (the default — do NOT infer willingness from general enthusiasm)."},
            "case_study_candidate": {"type": "string", "enum": CASE_STUDY,
                                     "description": "Your honest read on case-study potential: 'Strong' = quotable story + clear outcome + enthusiasm; 'Possible' = decent story, needs follow-up; 'No' = thin or reluctant."},
            "product_feature_asks": {"type": "array", "items": {"type": "string"},
                                     "description": "Any product gaps or feature requests they raised in passing. These are NOT buyer's-story fields — they get routed to the OS Feature Requests DB. Empty array if none."},
            "notes": {"type": "string",
                      "description": "A tight 3-5 sentence synthesis of the buyer's story for quick scanning: the before, the turn, and the one thing this account teaches us about who buys and why."},
        },
        "required": ["account", "segment", "product", "primary_driver", "decision_drivers",
                     "trigger_event", "prior_solution", "alternatives_considered",
                     "near_miss_objection", "deciding_moment", "buying_committee",
                     "killer_quotes", "reference_willing", "case_study_candidate",
                     "product_feature_asks", "notes"],
    },
}

_SYSTEM = """You analyze a recorded TeamBuildr *buyer's-story* interview — a short, informal call held ~3-4 weeks after a new customer signed. The seller (Trent, VP of Sales) asks them to tell the story of how they landed on TeamBuildr: what they were wrestling with before, what almost stopped them, and what tipped the decision.

TeamBuildr sells two products. **OS** is a business-operations platform for gyms/facilities (scheduling, billing, memberships, member app, CRM). **Strength** is programming/athlete-management (AMS). Tag `product` accordingly; if they clearly bought the ops platform, that's OS.

Your job is to reconstruct the BUYING decision, not to review the product or the onboarding. Rules:
- Capture the customer's EXACT language wherever you can — their words are the asset. Never upgrade their phrasing into marketing copy.
- Distinguish what the CUSTOMER raised from what the interviewer put in their mouth. Only credit a decision driver if the customer emphasized it.
- The near-miss objection (what almost stopped the deal) is the highest-value field. Dig for the real hesitation, not a polite non-answer.
- Be conservative and honest on `reference_willing` and `case_study_candidate` — these feed an outbound pipeline, so don't inflate. Default `reference_willing` to 'Not asked' unless the interviewer explicitly asked and the customer answered.
- Route feature requests to `product_feature_asks`; keep them OUT of the buyer's-story narrative fields.

Because the seller is interviewing their own buyer, expect praise to be inflated. Weight concrete, specific statements over general enthusiasm."""


def _extract(rec: dict) -> dict:
    import os
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or sys.exit("ANTHROPIC_API_KEY not set"))
    resp = client.messages.create(
        model=MODEL, max_tokens=2500, system=_SYSTEM,
        tools=[_TOOL], tool_choice={"type": "tool", "name": "extract"},
        messages=[{"role": "user", "content":
                   f"Interview: {rec['subject']}\nParticipants: {', '.join(rec['attendees'])}\n\n"
                   f"Transcript:\n{rec['text'][:TRANSCRIPT_CHAR_LIMIT]}"}],
    )
    out = next((b.input for b in resp.content if b.type == "tool_use"), None)
    if out is None:
        sys.exit("Extraction returned no structured output.")
    return out


# --------------------------------------------------------------------------
# Draft rendering
# --------------------------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "buyer-story").lower()).strip("-")[:50] or "buyer-story"


def _notion_properties(rec: dict, x: dict) -> dict:
    """Build the exact Notion property map for the Buyer's Story data source.

    Enum values that come back 'unclear' are dropped so the Notion field stays
    empty rather than erroring on an unknown option.
    """
    date = (rec.get("start_at") or "")[:10]
    props: dict = {
        "Account": x.get("account") or rec.get("subject") or "Untitled",
        "Stage": "Compiled",
        "Primary Driver": x.get("primary_driver", ""),
        "Decision Drivers": [d for d in x.get("decision_drivers", []) if d in DECISION_DRIVERS],
        "Trigger Event": x.get("trigger_event", ""),
        "Prior Solution": x.get("prior_solution", ""),
        "Alternatives Considered": x.get("alternatives_considered", ""),
        "Near-Miss Objection": x.get("near_miss_objection", ""),
        "Deciding Moment": x.get("deciding_moment", ""),
        "Buying Committee": x.get("buying_committee", ""),
        "Killer Quotes": "\n".join(f'"{q}"' for q in x.get("killer_quotes", [])),
        "Avoma Link": f"https://app.avoma.com/meetings/{rec['uuid']}",
    }
    if date:
        props["date:Interview Date:start"] = date
        props["date:Interview Date:is_datetime"] = 0
    for key, val, allowed in (
        ("Segment", x.get("segment"), SEGMENTS),
        ("Product", x.get("product"), PRODUCTS),
        ("Reference Willing", x.get("reference_willing"), REFERENCE),
        ("Case Study Candidate", x.get("case_study_candidate"), CASE_STUDY),
    ):
        if val in allowed and val != "unclear":
            props[key] = val
    return props


def _render_draft(rec: dict, x: dict) -> str:
    date = (rec.get("start_at") or "")[:10]
    drivers = ", ".join(x.get("decision_drivers") or []) or "(none tagged)"
    quotes_md = "\n".join(f'- "{q}"' for q in x.get("killer_quotes", [])) or "- (none captured)"
    asks = x.get("product_feature_asks") or []
    asks_md = "\n".join(f"- {a}" for a in asks) or "- (none)"
    payload = {
        "notion_data_source_id": NOTION_DATA_SOURCE_ID,
        "notion_properties": _notion_properties(rec, x),
        "product_feature_asks": asks,  # route to OS Feature Requests DB, not this DB
    }
    return f"""# Buyer's Story — {x.get('account')} · {date}
_Avoma: {rec['uuid']} · Segment: {x.get('segment')} · Product: {x.get('product')}_

## Synthesis
{x.get('notes','')}

**Primary driver (their words).** {x.get('primary_driver','')}

**Decision drivers.** {drivers}

**Trigger / why now.** {x.get('trigger_event','')}

**Before TeamBuildr.** {x.get('prior_solution','')}

**Alternatives considered.** {x.get('alternatives_considered','')}

**Near-miss objection (what almost stopped it).** {x.get('near_miss_objection','')}

**Deciding moment.** {x.get('deciding_moment','')}

**Buying committee.** {x.get('buying_committee','')}

## Killer quotes
{quotes_md}

## Reference / case-study read
- Reference willing: **{x.get('reference_willing','')}**
- Case-study candidate: **{x.get('case_study_candidate','')}**

## Product / feature asks → route to OS Feature Requests DB
{asks_md}

---
<!-- Review/fix the fields above. To file this in Notion, create a page in the
     Buyer's Story data source ({NOTION_DATA_SOURCE_ID}) using notion_properties
     below (via the Notion MCP). The feature asks go to the Feature Requests DB,
     NOT this one. -->
## NOTION PAYLOAD
```json
{json.dumps(payload, indent=2, ensure_ascii=False)}
```
"""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cmd_parse(args) -> None:
    uuid = args.uuid or _find_uuid(args.date, args.title)
    print(f"Fetching Avoma interview {uuid}...", file=sys.stderr)
    rec = _fetch_interview(uuid)
    print(f"Extracting buyer's story on {MODEL}...", file=sys.stderr)
    x = _extract(rec)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    draft_path = STATE_DIR / f"{_slug(x.get('account') or rec['subject'])}.draft.md"
    draft_path.write_text(_render_draft(rec, x))
    print(f"\nDraft written -> {draft_path.relative_to(PROJECT_ROOT)}")
    print(f"Review it, then file it in Notion: {NOTION_DB_URL}")


def main() -> None:
    p = argparse.ArgumentParser(description="Buyer's-story parser: Avoma interview → Notion-ready card.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("parse", help="Fetch an Avoma interview and write a review draft.")
    pp.add_argument("--uuid", help="Avoma meeting UUID.")
    pp.add_argument("--date", help="Local day YYYY-MM-DD (with --title) to locate the interview.")
    pp.add_argument("--title", help="Title substring to locate the interview.")
    pp.set_defaults(func=cmd_parse)

    args = p.parse_args()
    if args.cmd == "parse" and not args.uuid and not args.date:
        sys.exit("parse needs --uuid, or --date (+ optional --title).")
    args.func(args)


if __name__ == "__main__":
    main()
