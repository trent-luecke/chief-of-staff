#!/usr/bin/env python3
"""Economical transcript scanner — find calls matching criteria without
re-processing every transcript through an LLM.

The problem this solves: you want to answer a granular question over many
Avoma calls (e.g. "how many demos asked about integrations, and with which
app?"). Running an LLM over every full transcript is expensive and slow.
This funnels the work in stages so tokens are only spent on calls that
could plausibly match:

  Stage 0  enumerate  List + count meetings in a date window. Establishes the
                      REAL denominator and dumps available meeting fields so we
                      know what's queryable for free. (no tokens, no transcripts)
  Stage 1  fetch      Download + cache each meeting's transcript to disk.
                      (no tokens — Avoma API only; cached so re-runs are free)
  Stage 2  filter     Keyword pre-filter cached transcripts against a lexicon.
                      Narrows the LLM candidate set. (no tokens)
  Stage 3  analyze    Targeted LLM extraction on filtered candidates only,
                      fed keyword-windowed excerpts (not full transcripts).
                      (tokens — but only on survivors, on a cheap model first)

Auth: reads AVOMA_API_KEY (all stages) and ANTHROPIC_API_KEY (stage 3) from
.env or shell env in the project root.

Cache lives in data/state/transcript_scan/ (gitignored machine state), so
fetched transcripts persist across runs and re-scanning a new question is free.

Examples:
  # Stage 0 — how many meetings does Avoma actually have this year?
  python3 scripts/transcript_scan.py enumerate --from 2026-01-01 --to 2026-06-30

  # Stage 1 — cache transcripts for that window
  python3 scripts/transcript_scan.py fetch --from 2026-01-01 --to 2026-06-30

  # Stage 2 — which cached transcripts mention integrations?
  python3 scripts/transcript_scan.py filter --preset integrations

  # Stage 3 — LLM-confirm integration interest on the survivors
  python3 scripts/transcript_scan.py analyze --preset integrations
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_URL = "https://api.avoma.com"
TIMEOUT = 60
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "state" / "transcript_scan"
MEETINGS_CACHE = CACHE_DIR / "meetings.json"
TRANSCRIPTS_DIR = CACHE_DIR / "transcripts"

# Demo reps — calls involving one of these people are sales calls (demo /
# onboarding / follow-up), a useful free proxy when the API has no demo flag.
# Mirrors collectors/avoma.py DEMO_REP_ROSTER.
DEMO_REP_TOKENS = {
    "allwein", "ryan allwein",
    "luke martin", "lmartin",
    "chris reynolds",
    "jeff davidson",
    "trent luecke", "luecke",
}


def _key(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"{name} not found in .env or shell env.")
    return val


def _headers() -> dict:
    return {"Authorization": f"Bearer {_key('AVOMA_API_KEY')}"}


# Avoma rate-limits aggressively and ignores page_size (10/page), so a full-year
# external sweep is 60+ requests. Pace politely and honor 429 Retry-After.
PAGE_DELAY = 0.5       # seconds between successful requests
MAX_RETRIES = 6


def _get_with_retry(url: str, params: dict | None) -> dict:
    delay = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", delay))
            print(f"  ...429 rate-limited, waiting {wait:.0f}s "
                  f"(attempt {attempt}/{MAX_RETRIES})", file=sys.stderr)
            time.sleep(wait)
            delay = min(delay * 2, 60)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()  # exhausted retries — surface the last error
    return {}


def _iso_z(date_str: str, end: bool = False) -> str:
    """Turn YYYY-MM-DD into an ISO 8601 UTC bound."""
    return f"{date_str}T{'23:59:59' if end else '00:00:00'}Z"


# ---------------------------------------------------------------------------
# Stage 0 — enumerate
# ---------------------------------------------------------------------------

def _paginate_meetings(from_date: str, to_date: str, external_only: bool) -> list[dict]:
    """Page through /v1/meetings for the window, returning all raw meeting dicts."""
    params: dict | None = {
        "from_date": from_date,
        "to_date": to_date,
        "page_size": 100,
        "o": "-start_at",
    }
    if external_only:
        params["is_internal"] = "false"

    url: str | None = f"{BASE_URL}/v1/meetings"
    meetings: list[dict] = []
    page = 0
    while url:
        body = _get_with_retry(url, params)
        batch = body.get("results", body if isinstance(body, list) else [])
        meetings.extend(batch)
        page += 1
        if page % 10 == 0:
            print(f"  ...page {page} ({len(meetings)} total)", file=sys.stderr)
        url = body.get("next")
        params = None  # next URL already carries the query string
        if url:
            time.sleep(PAGE_DELAY)
    return meetings


def _attendee_blob(m: dict) -> str:
    return " ".join(
        f"{a.get('name') or ''} {a.get('email') or ''}"
        for a in (m.get("attendees") or [])
    ).lower()


def _involves_demo_rep(m: dict) -> bool:
    blob = _attendee_blob(m)
    return any(tok in blob for tok in DEMO_REP_TOKENS)


def cmd_enumerate(args) -> None:
    from_date = _iso_z(args.from_date)
    to_date = _iso_z(args.to_date, end=True)
    print(f"Enumerating meetings {from_date} .. {to_date}"
          f"{' (external only)' if not args.include_internal else ''}", file=sys.stderr)

    meetings = _paginate_meetings(from_date, to_date, external_only=not args.include_internal)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MEETINGS_CACHE.write_text(json.dumps({
        "from": from_date, "to": to_date,
        "include_internal": args.include_internal,
        "count": len(meetings),
        "meetings": meetings,
    }, indent=2))

    total = len(meetings)
    ready = [m for m in meetings if m.get("transcript_ready")]
    rep_calls = [m for m in meetings if _involves_demo_rep(m)]
    rep_ready = [m for m in rep_calls if m.get("transcript_ready")]
    subj_demo = [m for m in meetings if "demo" in (m.get("subject") or "").lower()]

    # Monthly breakdown of transcript-ready, rep-involved calls (our best free
    # proxy for "demos this year").
    by_month: dict[str, int] = {}
    for m in rep_ready:
        mo = (m.get("start_at") or "")[:7]
        by_month[mo] = by_month.get(mo, 0) + 1

    print("\n" + "=" * 64)
    print(f"  STAGE 0 — meeting enumeration ({args.from_date} .. {args.to_date})")
    print("=" * 64)
    print(f"  Total meetings in window ............... {total}")
    print(f"  Transcript-ready ....................... {len(ready)}")
    print(f"  Involving a demo rep ................... {len(rep_calls)}")
    print(f"  Involving a demo rep + transcript-ready  {len(rep_ready)}")
    print(f'  Subject contains "demo" ................ {len(subj_demo)}')
    print("\n  Rep-involved + ready, by month:")
    for mo in sorted(by_month):
        print(f"    {mo} : {by_month[mo]}")

    # Discovery: what fields does a meeting object actually expose? This tells
    # us what classification signals exist for free (a native type? a template?).
    if meetings:
        print("\n  Available meeting fields (for classification signal discovery):")
        keys = sorted(meetings[0].keys())
        print("    " + ", ".join(keys))
        # Surface any field that smells like a type/category/template/purpose.
        for hint in ("type", "category", "template", "purpose", "outcome", "state"):
            for k in keys:
                if hint in k.lower():
                    # values may be dicts/lists — coerce to a hashable repr
                    sample = {
                        json.dumps(m.get(k), sort_keys=True)
                        for m in meetings if m.get(k) is not None
                    }
                    sample_str = ", ".join(sorted(sample)[:8])
                    print(f"    -> {k} ({len(sample)} distinct): {sample_str}")
    print(f"\n  Raw meeting list cached -> {MEETINGS_CACHE.relative_to(PROJECT_ROOT)}")
    print("=" * 64)


# ---------------------------------------------------------------------------
# Shared: load the cached demo set
# ---------------------------------------------------------------------------

def _load_demos() -> list[dict]:
    """Return transcript-ready type=Demo meetings from the enumerate cache."""
    if not MEETINGS_CACHE.exists():
        sys.exit("No meetings cache. Run `enumerate` first.")
    data = json.loads(MEETINGS_CACHE.read_text())
    demos = []
    for m in data["meetings"]:
        t = m.get("type") or {}
        if isinstance(t, dict) and t.get("label") == "Demo" and m.get("transcript_ready"):
            demos.append(m)
    return demos


def _transcript_path(uuid: str) -> Path:
    return TRANSCRIPTS_DIR / f"{uuid}.json"


# ---------------------------------------------------------------------------
# Stage 1 — fetch + cache transcripts (no tokens)
# ---------------------------------------------------------------------------

def _format_transcript(body: dict | list) -> str:
    """Flatten Avoma's /v1/transcriptions response into labeled dialog text."""
    results = body if isinstance(body, list) else body.get("results", [])
    if not results:
        return ""
    data = results[0]
    speakers = data.get("speakers", [])
    utterances = data.get("transcript", [])
    speaker_map: dict[str, str] = {}
    for s in speakers:
        sid = str(s.get("id") or s.get("speaker_id", ""))
        name = s.get("name") or s.get("email", "Unknown")
        prefix = "Rep" if s.get("is_rep") else "Prospect"
        speaker_map[sid] = f"[{prefix} - {name}]"
    lines = []
    for utt in utterances:
        sid = str(utt.get("speaker_id", ""))
        text = (utt.get("transcript") or "").strip()
        if text:
            lines.append(f"{speaker_map.get(sid, '[Unknown]')}: {text}")
    return "\n".join(lines)


def cmd_fetch(args) -> None:
    demos = _load_demos()
    if args.limit:
        demos = demos[: args.limit]
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    fetched = skipped = empty = 0
    for i, m in enumerate(demos, 1):
        uuid = m.get("uuid")
        path = _transcript_path(uuid)
        if path.exists() and not args.refresh:
            skipped += 1
            continue
        try:
            body = _get_with_retry(f"{BASE_URL}/v1/transcriptions", {"meeting_uuid": uuid})
        except Exception as e:
            print(f"  ! {uuid}: {e}", file=sys.stderr)
            continue
        text = _format_transcript(body)
        if not text:
            empty += 1
        path.write_text(json.dumps({
            "uuid": uuid,
            "subject": m.get("subject"),
            "start_at": m.get("start_at"),
            "participants": [
                (a.get("name") or a.get("email")) for a in (m.get("attendees") or [])
                if a.get("name") or a.get("email")
            ],
            "text": text,
        }))
        fetched += 1
        if i % 25 == 0:
            print(f"  ...{i}/{len(demos)} (fetched {fetched}, cached-skip {skipped})", file=sys.stderr)
        time.sleep(PAGE_DELAY)
    print(f"\nStage 1 done: {fetched} fetched, {skipped} already cached, "
          f"{empty} had no transcript text. Cache: {TRANSCRIPTS_DIR.relative_to(PROJECT_ROOT)}")


# ---------------------------------------------------------------------------
# Stage 2 — keyword pre-filter (no tokens)
# ---------------------------------------------------------------------------

# High-recall lexicon: generic integration verbs/nouns + named apps prospects
# in the gym/strength space commonly ask to connect. Stage 3 is the precision
# gate, so this errs toward catching everything.
INTEGRATION_LEXICON = {
    "generic": [
        "integrat", "integration", "api", "webhook", "zapier", "middleware",
        "sync with", "syncs with", "syncing", "connect to", "connect with",
        "connects to", "talk to", "talks to", "push data", "pull data",
        "export to", "import from", "single sign", "sso", "embed",
    ],
    "apps": [
        "stripe", "quickbooks", "xero", "mindbody", "pike13", "wodify",
        "gymmaster", "glofox", "pushpress", "abc financial", "abc fitness",
        "kisi", "brivo", "openpath", "google calendar", "gcal", "outlook",
        "squarespace", "wix", "shopify", "wordpress", "hubspot", "salesforce",
        "mailchimp", "activecampaign", "twilio", "slack", "zoom", "docusign",
        "trainheroic", "trainerize", "kilo", "chalkit", "sugarwod", "btwb",
        "hudl", "catapult", "vald", "kabata", "teamworks", "dragonfly",
        "google sheets", "zapier", "make.com", "plaid", "gusto",
    ],
}
_ALL_TERMS = INTEGRATION_LEXICON["generic"] + INTEGRATION_LEXICON["apps"]


def _keyword_hits(text: str) -> list[dict]:
    """Return per-term hit info: {term, count, first_line} for matched terms."""
    lower = text.lower()
    lines = text.split("\n")
    hits = []
    for term in _ALL_TERMS:
        c = lower.count(term)
        if c:
            first_line = next((i for i, ln in enumerate(lines) if term in ln.lower()), -1)
            hits.append({"term": term, "count": c, "first_line": first_line})
    return hits


def cmd_filter(args) -> None:
    cached = sorted(TRANSCRIPTS_DIR.glob("*.json"))
    if not cached:
        sys.exit("No cached transcripts. Run `fetch` first.")
    candidates, term_tally = [], {}
    for p in cached:
        rec = json.loads(p.read_text())
        hits = _keyword_hits(rec.get("text") or "")
        if hits:
            candidates.append({"uuid": rec["uuid"], "subject": rec["subject"],
                               "hits": hits})
            for h in hits:
                term_tally[h["term"]] = term_tally.get(h["term"], 0) + 1
    (CACHE_DIR / "candidates.json").write_text(json.dumps(candidates, indent=2))
    print(f"\nStage 2: {len(candidates)}/{len(cached)} cached demos mention an "
          f"integration term.")
    print("  Top terms:")
    for term, n in sorted(term_tally.items(), key=lambda x: -x[1])[:20]:
        print(f"    {n:4}  {term}")
    print(f"  Candidate list -> {(CACHE_DIR / 'candidates.json').relative_to(PROJECT_ROOT)}")


# ---------------------------------------------------------------------------
# Stage 3 — targeted LLM extraction (tokens)
# ---------------------------------------------------------------------------

PRICING = {  # $/1M tokens (input, output)
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-8": (5.0, 25.0),
}
TRANSCRIPT_CHAR_LIMIT = 28_000  # ~7k tokens

_TOOL_INTEGRATION = {
    "name": "extract",
    "description": "Record whether this demo prospect showed OS interest and asked about integrations.",
    "input_schema": {
        "type": "object",
        "properties": {
            "os_interest": {
                "type": "boolean",
                "description": (
                    "True ONLY if the prospect engaged with TeamBuildr OS specifically "
                    "(business operations: scheduling, billing, memberships, CRM) — asked "
                    "about OS features, pricing, or a business-ops need. False if the call "
                    "was only about Strength (workout programming) or AMS (athlete wellness), "
                    "or if OS was never genuinely discussed."
                ),
            },
            "os_evidence": {"type": "string", "description": "One-line basis for os_interest (quote or paraphrase). Empty if false."},
            "integration_ask": {
                "type": "boolean",
                "description": (
                    "True ONLY if the PROSPECT (not the rep) asks about, requests, or raises "
                    "wanting to connect TeamBuildr to a SEPARATE third-party software product "
                    "(integration, API, sync, Zapier, webhook, import/export to a named external tool). "
                    "Set FALSE when: (a) the REP proactively describes an integration the prospect "
                    "never asked for; (b) the discussion is about Stripe as the payment processor — "
                    "Stripe is TeamBuildr OS's BUILT-IN/native payment processor, so asking how "
                    "payments work, merchant fees, or moving cards into OS is NOT an integration ask. "
                    "Count payments ONLY if the prospect wants to connect a DIFFERENT external "
                    "payment system instead of the native Stripe."
                ),
            },
            "initiated_by": {
                "type": "string",
                "enum": ["prospect", "rep", "unclear", "none"],
                "description": "Who raised the integration topic. 'prospect' if the prospect asked; 'rep' if the rep volunteered it; 'none' if no integration discussed.",
            },
            "apps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Third-party apps the PROSPECT wants to connect (exclude Stripe when it's just the native payment processor). Empty if none.",
            },
            "integration_quote": {"type": "string", "description": "Verbatim quote of the prospect's integration ask. Empty if integration_ask is false."},
        },
        "required": ["os_interest", "os_evidence", "integration_ask", "initiated_by", "apps", "integration_quote"],
    },
}

_SYSTEM_INTEGRATION = """\
You analyze TeamBuildr sales-demo transcripts. TeamBuildr sells three products:
- Strength: workout/training program software for coaches and athletes
- AMS: athlete wellness, readiness, and data tracking
- OS (TeamBuildr OS): business-operations platform for gyms/facilities — scheduling, billing, memberships, CRM

Call the extract tool. Be strict on both fields:
- os_interest: true ONLY for genuine engagement with OS (business operations), not Strength/AMS alone.
- integration_ask: true ONLY when the PROSPECT THEMSELVES raises connecting TeamBuildr to a separate \
third-party app. A rep proactively pitching an integration does NOT count. Critically, Stripe is OS's \
BUILT-IN payment processor — treating Stripe payments, fees, or card migration as an "integration" is a \
common mistake; do NOT count it unless the prospect explicitly wants a DIFFERENT external payment system. \
When in doubt about who raised it, set initiated_by to 'unclear' and integration_ask to false."""


# --- workflow-builder preset: the productized Opus scorer ------------------
# Recall lexicon that pulls a transcript into the Opus candidate set. Specific
# named platforms + Zapier only — generic words ("automat", "workflow", "crm")
# are too noisy; the integration pre-pass's flagged calls cover generic asks.
PULL_TERMS = [
    "zapier", "make.com", "webhook",
    "hubspot", "salesforce", "gohighlevel", "go high level", "go highlevel", "pipedrive",
    "mindbody", "vagaro", "pushpress", "push press", "glofox", "gymmaster", "gymdesk",
    "wellness living", "wellnessliving", "classpass", "quickbooks", "xero",
    "gusto", "calendly", "acuity", "squarespace", "shopify",
    "jotform", "docusign", "eventbrite", "kajabi",
]

_TOOL_WORKFLOW = {
    "name": "extract",
    "description": "Classify a TeamBuildr OS demo for Workflow-Builder-relevant integration demand.",
    "input_schema": {
        "type": "object",
        "properties": {
            "os_interest": {"type": "boolean", "description": "True only if the prospect genuinely engaged with TeamBuildr OS (business operations: scheduling, billing, memberships, CRM), not just Strength/AMS."},
            "qualifies": {"type": "boolean", "description": "True ONLY if the PROSPECT (not the rep) asked about Zapier-style automation OR connecting a CRM / business-process platform. See exclusions in the system prompt."},
            "category": {"type": "string", "enum": ["zapier_automation", "crm", "business_process", "excluded_native", "excluded_hardware", "excluded_internal", "other", "none"], "description": "Primary classification of the integration discussion."},
            "zapier_mentioned": {"type": "boolean", "description": "True if Zapier / Make.com / generic no-code automation was specifically discussed."},
            "zapier_workflow_described": {"type": "boolean", "description": "True if the prospect described a SPECIFIC workflow/scenario they want to automate."},
            "workflow_scenario": {"type": "string", "description": "The specific automation workflow the prospect described, in their words or a tight paraphrase. Empty if none."},
            "qualifying_apps": {"type": "array", "items": {"type": "string"}, "description": "CRM/business-process apps the prospect wants to connect. EXCLUDE Stripe, Mailchimp, and all sports-science hardware/wearables."},
            "initiated_by": {"type": "string", "enum": ["prospect", "rep", "unclear", "none"]},
            "quote": {"type": "string", "description": "Verbatim quote of the prospect's qualifying ask. Empty if qualifies is false."},
        },
        "required": ["os_interest", "qualifies", "category", "zapier_mentioned", "zapier_workflow_described", "workflow_scenario", "qualifying_apps", "initiated_by", "quote"],
    },
}

_SYSTEM_WORKFLOW = """You analyze TeamBuildr sales-demo transcripts to size demand for a planned OS Workflow Builder (a Claude-built, native automation/integration layer that would replace Zapier inside TeamBuildr OS).

TeamBuildr OS is a business-operations platform for gyms/facilities (scheduling, billing, memberships, CRM). Strength and AMS are its other products (workout programming; athlete wellness).

Call the extract tool. qualifies = TRUE only when the PROSPECT THEMSELVES asks about either:
  (A) Zapier / Make.com / generic no-code automation or webhooks/API connecting OS to other tools, OR
  (B) connecting a CRM or business-process platform (GoHighLevel, HubSpot, Salesforce, Pipedrive, Vagaro, Mindbody used as a management/CRM/booking platform, or scheduling/booking/POS/accounting tools like Calendly, Square, QuickBooks).

qualifies = FALSE (use the matching excluded_* category) for ALL of these:
  - Stripe — OS's BUILT-IN payment processor, not a third-party integration.
  - Mailchimp — a NATIVE OS email integration, not a third-party ask.
  - Sports-science hardware/wearables/athlete-tracking: force plates, VBT devices, timing gates, GPS/tracking, wearables (Vault, Vald, ForceDecks, Smartspeed, Catapult, Whoop, Perch, Proteus, Tendo, Output, Enode, Hawken, Bridge Athletic, Kabata, Garmin, Apple Watch/Health, InBody).
  - TeamBuildr's own Strength/AMS products (internal, not third-party).
  - The REP proactively pitching an integration the prospect never asked about.

When unsure who raised it, set initiated_by='unclear' and qualifies=false. Be conservative — this number goes in a pitch deck."""


def _analyze_one(client, model, system, tool, rec) -> dict | None:
    text = (rec.get("text") or "").strip()
    if not text:
        return None
    try:
        resp = client.messages.create(
            model=model, max_tokens=1200, system=system,
            tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content":
                       f"Demo title: {rec.get('subject')}\n\nTranscript:\n{text[:TRANSCRIPT_CHAR_LIMIT]}"}],
        )
        out = next((b.input for b in resp.content if b.type == "tool_use"), None)
        if out is None:
            return None
        return {
            "uuid": rec["uuid"], "subject": rec.get("subject"),
            "start_at": rec.get("start_at"), "participants": rec.get("participants"),
            **out,
            "_in_tokens": resp.usage.input_tokens,
            "_out_tokens": resp.usage.output_tokens,
        }
    except Exception as e:
        print(f"  ! {rec['uuid']}: {e}", file=sys.stderr)
        return None


# ---- candidate strategies (which cached demos a preset scores) ----

def _candidates_all(recs: list[dict]) -> list[dict]:
    """Every cached demo — needed to recover the OS denominator."""
    return recs


def _candidates_workflow_union(recs: list[dict]) -> list[dict]:
    """Union of the integration pre-pass's flagged demos and PULL_TERMS hits.

    High recall on Zapier/CRM/business-process without paying Opus on all demos.
    Run `analyze --preset integration` first for the flagged half; without it,
    recall falls back to keyword hits only (and we warn)."""
    flagged: set[str] = set()
    ipath = CACHE_DIR / "analysis_integration.json"
    if ipath.exists():
        flagged = {r["uuid"] for r in json.loads(ipath.read_text()) if r.get("integration_ask")}
    else:
        print("  (no integration pre-pass found — recall is keyword-only. For best "
              "recall run `analyze --preset integration` first.)", file=sys.stderr)
    keep = set(flagged)
    for r in recs:
        if any(t in (r.get("text") or "").lower() for t in PULL_TERMS):
            keep.add(r["uuid"])
    return [r for r in recs if r["uuid"] in keep]


# ---- per-preset summaries (printed after a run) ----

def _summarize_integration(results: list[dict]) -> None:
    os_yes = [r for r in results if r.get("os_interest")]
    integ = [r for r in results if r.get("integration_ask")]
    both = [r for r in results if r.get("os_interest") and r.get("integration_ask")]
    apps: dict[str, int] = {}
    for r in integ:
        for a in (r.get("apps") or []):
            apps[a.strip().lower()] = apps.get(a.strip().lower(), 0) + 1
    print(f"  OS-interested (criterion 1) ............ {len(os_yes)}")
    print(f"  Asked about integrations (criterion 2) . {len(integ)}")
    print(f"  BOTH — OS + integration ask ............ {len(both)}")
    print("\n  Apps prospects named:")
    for a, n in sorted(apps.items(), key=lambda x: -x[1])[:25]:
        print(f"    {n:3}  {a}")


def _summarize_workflow(results: list[dict]) -> None:
    from collections import Counter
    os_yes = [r for r in results if r.get("os_interest")]
    q = [r for r in results if r.get("os_interest") and r.get("qualifies")]
    zap = [r for r in q if r.get("zapier_mentioned")]
    zap_wf = [r for r in q if r.get("zapier_workflow_described")]
    cats = Counter(r.get("category") for r in q)
    apps: dict[str, int] = {}
    for r in q:
        for a in (r.get("qualifying_apps") or []):
            apps[a.strip().lower()] = apps.get(a.strip().lower(), 0) + 1
    print(f"  OS-interested in this set .............. {len(os_yes)}")
    print(f"  QUALIFY (OS + Zapier/CRM/biz-process) .. {len(q)}   <-- the number")
    print(f"     ...mentioned Zapier/automation ...... {len(zap)}")
    print(f"     ...described a specific workflow .... {len(zap_wf)}")
    print(f"  category split: {dict(cats)}")
    print("\n  CRM/business-process apps prospects asked to connect:")
    for a, n in sorted(apps.items(), key=lambda x: -x[1])[:25]:
        print(f"    {n:3}  {a}")
    print("\n  Qualifying demos with a described workflow:")
    for r in sorted([x for x in q if x.get("zapier_workflow_described")],
                    key=lambda r: r.get("start_at") or ""):
        print(f"    {(r.get('start_at') or '')[:10]}  {(r.get('subject') or '')[:40]:40}"
              f"  -> {(r.get('workflow_scenario') or '')[:80]}")


PRESETS = {
    "integration": {
        "model": "claude-haiku-4-5",
        "system": _SYSTEM_INTEGRATION, "tool": _TOOL_INTEGRATION,
        "candidates": _candidates_all, "summarize": _summarize_integration,
        "desc": "Broad: prospect-initiated third-party integration ask, all demos (Haiku). Also yields the OS denominator.",
    },
    "workflow-builder": {
        "model": "claude-opus-4-8",
        "system": _SYSTEM_WORKFLOW, "tool": _TOOL_WORKFLOW,
        "candidates": _candidates_workflow_union, "summarize": _summarize_workflow,
        "desc": "Strict: Zapier/CRM/business-process demand for the OS Workflow Builder, keyword+flag union (Opus). Excludes native Stripe/Mailchimp + sports hardware.",
    },
}


def cmd_analyze(args) -> None:
    import concurrent.futures as cf

    preset = PRESETS.get(args.preset)
    if preset is None:
        sys.exit(f"Unknown preset '{args.preset}'. Options: {', '.join(PRESETS)}")
    model = args.model or preset["model"]

    cached = sorted(TRANSCRIPTS_DIR.glob("*.json"))
    if not cached:
        sys.exit("No cached transcripts. Run `fetch` first.")
    recs = [json.loads(p.read_text()) for p in cached]
    recs = [r for r in recs if (r.get("text") or "").strip()]
    recs = preset["candidates"](recs)
    if args.limit:
        recs = recs[: args.limit]

    chars = sum(min(len(r["text"]), TRANSCRIPT_CHAR_LIMIT) for r in recs)
    pin, pout = PRICING.get(model, (0, 0))
    est = (chars / 4 + len(recs) * 450) / 1e6 * pin + len(recs) * 250 / 1e6 * pout
    print(f"\npreset '{args.preset}' · model {model} · {len(recs)} demos to analyze "
          f"· est ~${est:.2f}", file=sys.stderr)
    if args.dry_run:
        print("(dry run — no API calls made)", file=sys.stderr)
        return

    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")
    client = anthropic.Anthropic(api_key=_key("ANTHROPIC_API_KEY"))
    results = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_analyze_one, client, model, preset["system"], preset["tool"], r)
                for r in recs]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            r = fut.result()
            if r:
                results.append(r)
            if i % 25 == 0:
                print(f"  ...{i}/{len(recs)}", file=sys.stderr)

    out_path = CACHE_DIR / f"analysis_{args.preset}.json"
    out_path.write_text(json.dumps(results, indent=2))

    in_tok = sum(r.get("_in_tokens", 0) for r in results)
    out_tok = sum(r.get("_out_tokens", 0) for r in results)
    cost = in_tok / 1e6 * pin + out_tok / 1e6 * pout
    print("\n" + "=" * 64)
    print(f"  {args.preset.upper()} — {len(results)} demos analyzed on {model}")
    print("=" * 64)
    preset["summarize"](results)
    print(f"\n  Tokens: {in_tok:,} in / {out_tok:,} out  ~= ${cost:.2f}")
    print(f"  Results -> {out_path.relative_to(PROJECT_ROOT)}")
    print("=" * 64)


def main() -> None:
    p = argparse.ArgumentParser(description="Economical staged transcript scanner.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("enumerate", help="Stage 0: list + count meetings in a window.")
    pe.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    pe.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    pe.add_argument("--include-internal", action="store_true",
                    help="Include internal meetings (default: external only).")
    pe.set_defaults(func=cmd_enumerate)

    pf = sub.add_parser("fetch", help="Stage 1: download + cache demo transcripts.")
    pf.add_argument("--limit", type=int, help="Only fetch the first N demos (testing).")
    pf.add_argument("--refresh", action="store_true", help="Re-fetch even if cached.")
    pf.set_defaults(func=cmd_fetch)

    pfi = sub.add_parser("filter", help="Stage 2: keyword pre-filter cached transcripts.")
    pfi.set_defaults(func=cmd_filter)

    pa = sub.add_parser("analyze", help="Stage 3: LLM extraction on cached transcripts.")
    pa.add_argument("--preset", default="integration", choices=list(PRESETS),
                    help="Scan preset: 'integration' (broad, Haiku, all demos) or "
                         "'workflow-builder' (Zapier/CRM demand, Opus, union). Default: integration.")
    pa.add_argument("--model", default=None, help="Override the preset's default model.")
    pa.add_argument("--dry-run", action="store_true",
                    help="Print preset, candidate count, and cost estimate without calling the API.")
    pa.add_argument("--workers", type=int, default=6, help="Concurrent API calls (default 6).")
    pa.add_argument("--limit", type=int, help="Only analyze the first N (testing).")
    pa.set_defaults(func=cmd_analyze)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
