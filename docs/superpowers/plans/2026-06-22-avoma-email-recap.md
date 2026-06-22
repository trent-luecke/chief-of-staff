# Avoma Email Recap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the useless `*Summary*` section in the Avoma Slack output with a prospect-facing recap a rep can paste into a follow-up email, while leaving the internal `summary` field (which feeds the Notion payload) untouched.

**Architecture:** Add a new `email_recap` string field that Claude composes in one shot during the existing `extract_call_analysis` tool call. The Slack message renderer reads `email_recap` (falling back to `summary`) instead of `summary`. No new Python assembly logic; the model writes the full bulleted recap.

**Tech Stack:** Python, Anthropic SDK (tool use), pytest with `unittest.mock`.

## Global Constraints

- Slack header label for the recap section: `📧 *Follow-Up Email Recap*` (verbatim).
- The internal `summary` field keeps its meaning ("2-3 sentence outcome summary") and continues to feed `_build_notion_prompt` — do not change the Notion payload path.
- The recap is a single freeform string composed by Claude — do NOT add structured sub-fields (`price_points`, `follow_up_questions`).
- Recap fallback chain in Slack: `email_recap` → `summary` → `"(no recap)"`.
- `AvomaTranscript` is constructed in TWO places in `collectors/avoma.py` (`fetch_recent_meetings` ~line 365 and `fetch_meeting_by_uuid` ~line 426). Both must set the new field.
- Model id stays as configured (`claude-sonnet-4-6` via `config.json`); do not hardcode a model.

---

### Task 1: Extraction layer — add `email_recap` to schema, dataclass, prompt, and both constructors

**Files:**
- Modify: `collectors/avoma.py` — `_EXTRACT_TOOL` schema (~lines 76-144), `_SYSTEM_PROMPT` (~lines 146-165), `AvomaTranscript` dataclass (~lines 168-185), `_analyze_with_claude` `max_tokens` (~line 247), both `AvomaTranscript(...)` constructors (~lines 365, 426)
- Test: `tests/test_avoma_collector_additions.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `AvomaTranscript.email_recap: str` (defaults to `""`); `_EXTRACT_TOOL` exposes an `email_recap` string property and lists it in `required`; `fetch_meeting_by_uuid` / `fetch_recent_meetings` populate `email_recap` from the tool result via `result.get("email_recap", "")`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_avoma_collector_additions.py`:

```python
def test_email_recap_in_extract_tool_schema():
    from collectors.avoma import _EXTRACT_TOOL
    props = _EXTRACT_TOOL["input_schema"]["properties"]
    assert "email_recap" in props
    assert props["email_recap"]["type"] == "string"
    assert "email_recap" in _EXTRACT_TOOL["input_schema"]["required"]


def test_fetch_meeting_by_uuid_populates_email_recap():
    from collectors.avoma import fetch_meeting_by_uuid

    mock_meeting = _mock_meeting_response()
    mock_analysis = {
        "os_interested": True,
        "call_type": "demo",
        "summary": "Good demo call.",
        "email_recap": "What we covered: scheduling. Open questions: timeline?",
        "features_covered": ["scheduling"],
        "gaps": [],
        "objections": [],
        "buying_signals": [],
        "competitors": [],
        "onboarding_completed": [],
        "onboarding_next_steps": [],
        "action_items": [],
    }

    with patch("collectors.avoma.requests.get") as mock_get, \
         patch("collectors.avoma._fetch_transcript", return_value=([], [{"speaker_id": "1", "transcript": "Hi"}])), \
         patch("collectors.avoma._analyze_with_claude", return_value=mock_analysis):
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_meeting
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        t = fetch_meeting_by_uuid("avoma-key", "anthropic-key", "claude-sonnet-4-6", "test-uuid-1234")

    assert t is not None
    assert t.email_recap == "What we covered: scheduling. Open questions: timeline?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_avoma_collector_additions.py::test_email_recap_in_extract_tool_schema tests/test_avoma_collector_additions.py::test_fetch_meeting_by_uuid_populates_email_recap -v`
Expected: FAIL — `KeyError: 'email_recap'` on the schema test, and `AttributeError`/`TypeError` (no `email_recap` field) on the fetch test.

- [ ] **Step 3: Add the schema property and make it required**

In `collectors/avoma.py`, inside `_EXTRACT_TOOL["input_schema"]["properties"]`, add after the `summary` entry (line 94):

```python
            "email_recap": {
                "type": "string",
                "description": (
                    "A prospect-facing recap the rep can paste into a follow-up email. "
                    "Plain text, scannable, organized as short labeled sections: "
                    "'What we covered' (1-2 lines), 'Features highlighted' (the OS features "
                    "that resonated), 'Pricing discussed' (ONLY if price or tiers came up — "
                    "omit this section entirely otherwise), and 'Open questions' (2-3 "
                    "open-ended questions phrased directly to the prospect). No greeting or "
                    "signature. No internal jargon — do not surface objections/gaps as such; "
                    "reframe concerns as questions where natural."
                ),
            },
```

In the `required` list (lines 136-142), add `"email_recap"` after `"summary"`:

```python
        "required": [
            "os_interested", "call_type", "summary", "email_recap",
            "features_covered", "gaps", "objections",
            "buying_signals", "competitors",
            "onboarding_completed", "onboarding_next_steps",
            "action_items",
        ],
```

- [ ] **Step 4: Add the system-prompt instruction**

In `_SYSTEM_PROMPT`, add a bullet after the `summary` line (line 164), before the closing `\`:

```
- For email_recap: write a recap the rep can paste into a follow-up email to the prospect. Use short labeled sections — "What we covered", "Features highlighted", "Pricing discussed" (include ONLY if price/tiers came up — otherwise omit this section), and "Open questions" (2-3 open-ended questions addressed to the prospect). Plain text, no greeting/signature, no internal jargon; reframe concerns as questions rather than naming objections or gaps.
```

- [ ] **Step 5: Add the dataclass field**

In `AvomaTranscript`, add after the `summary: str = ""` line (line 176):

```python
    email_recap: str = ""
```

- [ ] **Step 6: Populate the field in both constructors**

In `fetch_recent_meetings` (~line 372) and `fetch_meeting_by_uuid` (~line 433), add immediately after the `summary=result.get("summary", ""),` line in each:

```python
                email_recap=result.get("email_recap", ""),
```

(Match the existing indentation of the surrounding kwargs in each constructor — the two sites are indented differently.)

- [ ] **Step 7: Bump `max_tokens`**

In `_analyze_with_claude`, change `max_tokens=1500` (line 247) to:

```python
            max_tokens=2000,
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `pytest tests/test_avoma_collector_additions.py -v`
Expected: PASS (all tests in the file, including the two new ones).

- [ ] **Step 9: Commit**

```bash
git add collectors/avoma.py tests/test_avoma_collector_additions.py
git commit -m "feat: extract prospect-facing email_recap from Avoma transcripts"
```

---

### Task 2: Slack rendering — show the recap in the `📧 *Follow-Up Email Recap*` section

**Files:**
- Modify: `processors/avoma_phase1.py` — `_build_slack_message` summary block (~lines 263-270)
- Test: `tests/test_avoma_phase1.py`

**Interfaces:**
- Consumes: `AvomaTranscript.email_recap` and `AvomaTranscript.summary` from Task 1.
- Produces: `_build_slack_message` emits the literal header `📧 *Follow-Up Email Recap*` followed by `t.email_recap or t.summary or "(no recap)"`; no longer emits the `*Summary*` header.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_avoma_phase1.py`:

```python
def test_build_slack_message_uses_email_recap():
    from processors.avoma_phase1 import _build_slack_message
    t = _fake_transcript()
    t.email_recap = "What we covered: scheduling.\nOpen questions: timeline?"
    people = [{"name": "John Smith", "is_internal": False, "is_new": False}]
    msg, _ = _build_slack_message(t, "Acme Corp", people, "ready to process")
    assert "📧 *Follow-Up Email Recap*" in msg
    assert "What we covered: scheduling." in msg
    assert "*Summary*" not in msg


def test_build_slack_message_falls_back_to_summary():
    from processors.avoma_phase1 import _build_slack_message
    t = _fake_transcript()
    t.email_recap = ""
    t.summary = "Good demo. Strong interest."
    people = [{"name": "John Smith", "is_internal": False, "is_new": False}]
    msg, _ = _build_slack_message(t, "Acme Corp", people, "ready to process")
    assert "📧 *Follow-Up Email Recap*" in msg
    assert "Good demo. Strong interest." in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_avoma_phase1.py::test_build_slack_message_uses_email_recap tests/test_avoma_phase1.py::test_build_slack_message_falls_back_to_summary -v`
Expected: FAIL — assertion error; message still contains `*Summary*` and not the recap header.

- [ ] **Step 3: Update the renderer**

In `processors/avoma_phase1.py`, in `_build_slack_message`, replace the two summary lines in the `lines = [...]` list:

```python
        "*Summary*",
        t.summary or "(no summary)",
```

with:

```python
        "📧 *Follow-Up Email Recap*",
        t.email_recap or t.summary or "(no recap)",
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_avoma_phase1.py -v`
Expected: PASS (all tests in the file, including the two new ones — existing tests assert on "Action Items"/Notion block, which are unchanged).

- [ ] **Step 5: Commit**

```bash
git add processors/avoma_phase1.py tests/test_avoma_phase1.py
git commit -m "feat: render email recap in Avoma Slack output, drop internal summary section"
```

---

## Final verification

- [ ] Run the full Avoma test suite: `pytest tests/ -k avoma -v` — Expected: all pass.

## Self-Review notes

- **Spec coverage:** schema field (Task 1 S3), required (S3), prompt (S4), dataclass (S5), both constructors (S6), max_tokens (S7), Slack header + fallback (Task 2 S3). Notion payload path explicitly unchanged. All spec sections mapped.
- **Type consistency:** `email_recap: str` used identically in dataclass, `result.get("email_recap", "")` in both constructors, and `t.email_recap` in the renderer. Header string `📧 *Follow-Up Email Recap*` identical in plan and tests.
