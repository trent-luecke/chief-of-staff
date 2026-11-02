# OS Quarterly Check-ins: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A draft-only quarterly check-in program. Every active OS account gets a Front email from Trent each quarter offering a 20-minute call or a short survey by account age. Outcomes, scores and risk signals go to a Notion log, and flag rules turn into ready-made follow-up drafts.

**Architecture:** Same pattern as the trial-outreach autopilot. Two in-app claude.ai scheduled tasks, `os-checkins-draft` (weekly) and `os-checkins-log` (weekdays), each fetch a version-controlled runbook from `origin/main` and run it with the Front, HubSpot, Google Drive and Notion connectors. The judgment-free rules (who is due, which version and variant, holds, score flags, Feature Request count updates, account-name matching) live in a small tested Python module with a JSON CLI. The routine calls that CLI rather than re-deriving the rules in prose every run.

**Tech Stack:** Python 3 + pytest (repo conventions: `lib/`, `tests/`, `scripts/`); claude.ai scheduled tasks; Notion MCP; Front / HubSpot / Google Drive connectors; Google Forms; Calendly.

**Spec:** `docs/superpowers/specs/2026-11-02-os-quarterly-checkins-design.md`

## Global Constraints

- **Draft only.** Never send. Every email is a Front draft Trent reviews and sends.
- Drafts are a **new outbound** on channel `cha_30ds1`, with BCC `4238329@bcc.hubspot.com`. Never a reply draft, because reply drafts silently drop the BCC.
- Account list source: Client List sheet `1Rxk54_u3w0Llm78Yqv8e2BaKG9ddG4UzTMEvaTCmgzs`, **Active Customers** tab, read-only. Never write to that sheet.
- **Eligibility:** tenure ≥ 2 months. **Survey version** by tenure: Early = 2 to <6 months, Settled = 6 to <12, Mature = 12+.
- **Cadence:** one check-in per account per 13-week cycle, starting at the account's week 13. **Nudge** once, at +7 days after send. **Silent** at +14 days with no response.
- **Flags:** Low score when a score is ≤ 6. Score drop when a score is ≥ 2 below the account's most recent previous scored check-in.
- **Variants:** Give-first after 1 Silent quarter. Different sender after 2 consecutive Silent quarters.
- **Holds:** no check-in while an account has a non-archived Front support conversation or an open bug. The hold clears 21 days after the last one closes. Same rule after a one-to-one email from Trent in the last 21 days.
- **Behavior Gaps DB** (`cd045eb1-489e-4566-924c-52bae236d36c`): no new column, ever. The Check-ins → Gap relation is **one-way**. The routine never creates Gap entries.
- **Feature Requests** (`collection://ad23d54a-66ac-4f84-9fde-6c4e317892ea`): on linking an account, add it to the relation, append its name to `Requesting Account`, and increment `Amount of Requests`, but **only if the account was not already linked**.
- **Give-first grounding:** every claim in an opener must trace to an item in the account's context packet. With no grounded angle, insert exactly `[PERSONAL OPENER — no grounded angle found]`.
- Avoma is best-effort. If it's unreachable, skip it and say so in the summary. It never blocks a draft.
- No usage-based targeting or scoring. No usage data exists.

## Review Focus

1. **A bad or blank Join Date** in the sheet (text, `⚠ check date`, empty, or a future date). The account is skipped with a reason in the summary, never a crash. → Task 1 tests `test_due_skips_bad_join_date`, `test_due_skips_future_join_date`.
2. **Scores missing from the previous check-in** (last quarter was a call or reply with no survey). Score drop compares against the most recent check-in that *has* scores, and never against null. → Task 1 test `test_score_drop_uses_last_scored_checkin`.
3. **Two survey responses for one account in one cycle.** The latest response wins, and the earlier one isn't double-flagged. → Task 1 test `test_pick_latest_response_per_checkin`.
4. **Sheet name differs from the Notion OS Accounts name** (punctuation, "LLC", "The"). Matching normalizes those, and an unmatched account is reported instead of silently given a new row. → Task 3 test `test_match_normalizes_suffixes_and_articles`, `test_match_reports_unmatched`.
5. **Skipped (deleted draft) inside a Silent streak.** Skipped neither counts as Silent nor breaks the streak's meaning. Two Silents separated only by a Skipped still count as Silent ×2. → Task 1 test `test_variant_skipped_is_transparent`.

---

## File structure

- `lib/checkins.py` holds the pure rules: due-ness, version, variant, holds, score flags, response picking, and Feature Request count updates. No I/O.
- `lib/account_match.py` holds account-name normalization and matching. It is used by the Feature Request backfill and by response→account matching.
- `scripts/checkins.py` is the JSON-in/JSON-out CLI over both modules. The runbook invokes it.
- `tests/test_checkins.py` and `tests/test_account_match.py` hold the tests.
- `docs/runbooks/os-quarterly-checkins-runbook.md` is the single source of the routine's behavior, plus an email-copy appendix.
- `docs/runbooks/os-checkins-fr-backfill.md` is the one-time backfill procedure and its review list.

---

### Task 1: Check-in rules module (`lib/checkins.py`)

**Files:**
- Create: `lib/checkins.py`
- Test: `tests/test_checkins.py`

**Interfaces:**
- Produces (all pure; dates are `datetime.date`):
  - `parse_join_date(raw: str) -> date | None`. Accepts `M/D/YYYY` and ISO. Returns None for anything else.
  - `tenure_months(join: date, today: date) -> int`. Whole months, the same as Sheets `DATEDIF(...,"m")`.
  - `survey_version(tenure: int) -> str | None`. Returns `"Early" | "Settled" | "Mature"`, or None when under 2 months.
  - `hold_until(support: list[dict], today: date) -> date | None`. Each item is `{"open": bool, "closed_on": date | None}`, covering support conversations, open bugs, and Trent's one-to-one emails (as `open=False, closed_on=sent_date`). Returns `date.max` if any item is open, otherwise the max `closed_on` + 21 days if that's after `today`, otherwise None.
  - `is_due(join: date | None, week_monday: date, last_checkin_on: date | None, hold: date | None) -> tuple[bool, str]`. Returns `(due, reason)`. Reasons: `"bad_join_date" | "future_join_date" | "too_new" | "held" | "recent_checkin" | "not_slot_week" | "due"`.
  - `choose_variant(prior_outcomes: list[str]) -> str`. Takes prior quarters' outcomes, oldest to newest, and returns `"Standard" | "Give-first" | "Different sender"`.
  - `score_flags(current: dict, history: list[dict]) -> list[str]`. `current` and the history items have keys `platform` and `support` (int | None). History runs oldest to newest. Returns a subset of `["Low score", "Score drop"]`.
  - `pick_latest_response(responses: list[dict]) -> dict | None`. Items have `submitted_at` (ISO str). Returns the newest.
  - `fr_link_update(linked: list[str], text: str, count: float | None, account: str) -> dict`. Returns `{"changed": bool, "linked": [...], "text": str, "count": float}`.

**Rules the tests pin:**
- `weeks = (week_monday - join).days // 7`. Not due if `weeks < 13` (`too_new`; this also covers the 2-month eligibility). Due if no check-in in the last 70 days *and* (`weeks % 13 == 0`, or `last_checkin_on` is None or more than 91 days before `week_monday`, meaning catch-up after a hold or a newly eligible account). Otherwise `not_slot_week`.
- A hold (`hold` not None and `hold > week_monday`) returns `held` before the slot check.
- `choose_variant`: drop `"Skipped"` entries. If the last two remaining are both `"Silent"`, return Different sender. If the last one is `"Silent"`, return Give-first. Otherwise Standard. Ignore in-flight outcomes (`"Drafted"` / `"Sent"`).

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date, timedelta
from lib.checkins import (parse_join_date, tenure_months, survey_version, hold_until,
                          is_due, choose_variant, score_flags, pick_latest_response, fr_link_update)

MON = date(2026, 11, 2)  # a Monday

def test_parse_join_date_formats():
    assert parse_join_date("2/21/2024") == date(2024, 2, 21)
    assert parse_join_date("2024-02-21") == date(2024, 2, 21)
    assert parse_join_date("⚠ check date") is None
    assert parse_join_date("") is None

def test_survey_version_buckets():
    assert survey_version(1) is None
    assert survey_version(2) == "Early"
    assert survey_version(5) == "Early"
    assert survey_version(6) == "Settled"
    assert survey_version(11) == "Settled"
    assert survey_version(12) == "Mature"
    assert survey_version(41) == "Mature"

def test_due_on_slot_week():
    join = date(2026, 11, 2) - timedelta(weeks=26)
    assert is_due(join, MON, None, None) == (True, "due")

def test_not_due_off_slot_with_recent_checkin():
    join = MON - timedelta(weeks=27)
    assert is_due(join, MON, date(2026, 10, 1), None) == (False, "recent_checkin")

def test_due_skips_bad_join_date():
    assert is_due(None, MON, None, None) == (False, "bad_join_date")

def test_due_skips_future_join_date():
    assert is_due(date(2026, 12, 1), MON, None, None) == (False, "future_join_date")

def test_too_new():
    assert is_due(date(2026, 9, 1), MON, None, None) == (False, "too_new")

def test_catch_up_after_hold():
    join = MON - timedelta(weeks=30)   # off-slot
    assert is_due(join, MON, date(2026, 5, 1), None) == (True, "due")

def test_held_blocks():
    join = MON - timedelta(weeks=26)
    assert is_due(join, MON, None, date(2026, 11, 20)) == (False, "held")

def test_hold_until_rules():
    assert hold_until([{"open": True, "closed_on": None}], MON) == date.max
    assert hold_until([{"open": False, "closed_on": date(2026, 10, 20)}], MON) == date(2026, 11, 10)
    assert hold_until([{"open": False, "closed_on": date(2026, 9, 1)}], MON) is None
    assert hold_until([], MON) is None

def test_variant_progression():
    assert choose_variant([]) == "Standard"
    assert choose_variant(["Survey answered"]) == "Standard"
    assert choose_variant(["Survey answered", "Silent"]) == "Give-first"
    assert choose_variant(["Silent", "Silent"]) == "Different sender"

def test_variant_skipped_is_transparent():
    assert choose_variant(["Silent", "Skipped", "Silent"]) == "Different sender"
    assert choose_variant(["Silent", "Skipped"]) == "Give-first"

def test_low_score_and_drop():
    hist = [{"platform": 9, "support": 8}]
    assert score_flags({"platform": 6, "support": 8}, hist) == ["Low score", "Score drop"]
    assert score_flags({"platform": 8, "support": 8}, hist) == []
    assert score_flags({"platform": 7, "support": 6}, hist) == ["Low score", "Score drop"]

def test_score_drop_uses_last_scored_checkin():
    hist = [{"platform": 9, "support": 9}, {"platform": None, "support": None}]
    assert score_flags({"platform": 7, "support": 9}, hist) == ["Score drop"]
    assert score_flags({"platform": 7, "support": 7}, []) == []

def test_pick_latest_response_per_checkin():
    r = pick_latest_response([{"submitted_at": "2026-11-03T10:00:00"},
                              {"submitted_at": "2026-11-05T09:00:00"}])
    assert r["submitted_at"] == "2026-11-05T09:00:00"
    assert pick_latest_response([]) is None

def test_fr_link_update_no_double_count():
    up = fr_link_update([], "FSP", 1, "Gem Sessions")
    assert up == {"changed": True, "linked": ["Gem Sessions"], "text": "FSP, Gem Sessions", "count": 2}
    again = fr_link_update(["Gem Sessions"], "FSP, Gem Sessions", 2, "Gem Sessions")
    assert again["changed"] is False and again["count"] == 2
    assert fr_link_update([], "", None, "FSP")["count"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_checkins.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.checkins'`.

- [ ] **Step 3: Implement the functions in `lib/checkins.py`** with the signatures and rules above. `tenure_months` counts whole months, minus one if the day-of-month hasn't been reached yet.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_checkins.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/checkins.py tests/test_checkins.py
git commit -m "feat(checkins): pure rules for due-ness, version, variant, holds, score flags"
```

---

### Task 2: Account-name matcher (`lib/account_match.py`)

**Files:**
- Create: `lib/account_match.py`
- Test: `tests/test_account_match.py`

**Interfaces:**
- Produces:
  - `normalize_name(name: str) -> str`. Lowercase. Strip punctuation, a leading `the `, and trailing `llc`, `inc`, `ltd`, `co`. Collapse whitespace. `&` becomes `and`.
  - `match_accounts(raw: str, accounts: list[str], threshold: float = 0.88) -> dict`. Splits `raw` on `,`, `;`, `/`, newline, and ` and `, *only when* each part matches an account on its own. Returns `{"matched": [{"input": str, "account": str, "score": float}], "uncertain": [...same shape, score in [0.75, threshold)], "unmatched": [str]}`. Exact normalized equality scores 1.0. Otherwise it uses `difflib.SequenceMatcher` ratio on normalized names.

- [ ] **Step 1: Write the failing tests**

```python
from lib.account_match import normalize_name, match_accounts

ACCTS = ["Beyond Our Best, LLC", "The Athlete Standard", "Country Strong, Inc.", "FSP", "Gem Sessions"]

def test_match_normalizes_suffixes_and_articles():
    assert normalize_name("Beyond Our Best, LLC") == normalize_name("beyond our best")
    assert match_accounts("Athlete Standard", ACCTS)["matched"][0]["account"] == "The Athlete Standard"

def test_match_splits_multi_account_text():
    r = match_accounts("FSP, Gem Sessions", ACCTS)
    assert [m["account"] for m in r["matched"]] == ["FSP", "Gem Sessions"]

def test_match_reports_unmatched():
    r = match_accounts("Totally Unknown Gym", ACCTS)
    assert r["matched"] == [] and r["unmatched"] == ["Totally Unknown Gym"]

def test_match_uncertain_band():
    r = match_accounts("Country Strng", ACCTS)
    assert r["matched"] or r["uncertain"]
    assert r["unmatched"] == []
```

- [ ] **Step 2: Run to verify fail.** Run `python -m pytest tests/test_account_match.py -v`. Expected: ModuleNotFoundError.
- [ ] **Step 3: Implement** with the signatures above. Standard library only (`difflib`, `re`).
- [ ] **Step 4: Run to verify pass.** Run `python -m pytest tests/test_account_match.py -v`. Expected: all PASS.
- [ ] **Step 5: Commit**

```bash
git add lib/account_match.py tests/test_account_match.py
git commit -m "feat(checkins): account-name normalizer + matcher for FR backfill and response joins"
```

---

### Task 3: JSON CLI (`scripts/checkins.py`)

**Files:**
- Create: `scripts/checkins.py`
- Test: `tests/test_checkins_cli.py`

**Interfaces:**
- Consumes: Task 1 and Task 2 functions.
- Produces: `python scripts/checkins.py <cmd>` reads one JSON object on stdin and writes one JSON object to stdout. Exit code 0, or 2 on malformed input with `{"error": str}`.
  - `due`: input `{"week_monday": "YYYY-MM-DD", "accounts": [{"name", "join_date" (raw sheet string), "email", "last_checkin_on"|null, "support": [{"open", "closed_on"|null}], "prior_outcomes": [str]}]}`. Output `{"due": [{"name", "email", "version", "variant", "generic_email": bool}], "skipped": [{"name", "reason"}]}`. `generic_email` is true when the local part is in `info, admin, contact, hello, office, team, support`.
  - `flags`: input `{"current": {"platform", "support"}, "history": [...]}`. Output `{"flags": [str]}`.
  - `latest`: input `{"responses": [...]}`. Output `{"response": {...}|null}`.
  - `fr-link`: input `{"linked", "text", "count", "account"}`. Output: the `fr_link_update` dict.
  - `match`: input `{"raw", "accounts"}`. Output: the `match_accounts` dict.

- [ ] **Step 1: Write the failing tests.** Use `subprocess.run([sys.executable, "scripts/checkins.py", cmd], input=json.dumps(payload), capture_output=True, text=True)`:
  - `test_cli_due_mixes_due_and_skipped`: with week_monday `2026-11-02`, one account joined `5/4/2026` (26 weeks), one joined `⚠ check date`, and one `info@x.com` account joined `5/4/2026`. Assert `[d["name"] for d in due]` holds both 26-week accounts, the second has `generic_email == True`, both have `version == "Early"`, and `skipped == [{"name": <bad one>, "reason": "bad_join_date"}]`.
  - `test_cli_malformed_input_exit_2`: stdin `"not json"` gives returncode 2 and an `"error"` key.
  - `test_cli_flags_roundtrip`: gives `{"flags": ["Low score", "Score drop"]}` for the Task 1 low-score case.
- [ ] **Step 2: Run to verify fail.** Run `python -m pytest tests/test_checkins_cli.py -v`. Expected: FAIL (no such file).
- [ ] **Step 3: Implement `scripts/checkins.py`** with `argparse`, one subcommand per cmd. Insert the repo root on `sys.path` the way existing `scripts/*.py` do.
- [ ] **Step 4: Run the full suite.** Run `python -m pytest tests/test_checkins.py tests/test_account_match.py tests/test_checkins_cli.py -v`. Expected: all PASS.
- [ ] **Step 5: Commit**

```bash
git add scripts/checkins.py tests/test_checkins_cli.py
git commit -m "feat(checkins): JSON CLI the runbook calls for deterministic rules"
```

---

### Task 4: Notion structures (Check-ins DB + Feature Requests relation)

**Files:**
- Create: `docs/runbooks/os-quarterly-checkins-runbook.md` (Config section only for now)

**Interfaces:**
- Produces: the Check-ins data source ID, its view URLs, and the Feature Requests "Requesting Accounts" property. Recorded in the runbook Config.

- [ ] **Step 1: Create "🔁 OS Check-ins"** under the OS Customer Success page (`2b024bca36d7802e960fddfa32efbcd9`) via Notion MCP `notion-create-database`. Use the spec §6 schema exactly, including `Proposed entry` (text) and `Log it` (checkbox).
  - Outcome options: `Drafted, Sent, Call booked, Survey answered, Replied, Silent, Skipped`.
  - Risk signals: `Competitor tool, Workaround, Built own, Score drop, Low score, Silent, Silent ×2`.
  - Version: `Early, Settled, Mature`.
  - Variant: `Standard, Give-first, Different sender`.
  - Follow-up: `None needed, Drafted, Done`.
  - Relations:
    - `Account` → `collection://3d124bca-36d7-8069-a2fa-000b83deae3d`, **two-way**.
    - `Related Feature Request` → `collection://ad23d54a-66ac-4f84-9fde-6c4e317892ea`, **two-way**.
    - `Related Gap` → `collection://cd045eb1-489e-4566-924c-52bae236d36c`, **one-way**.
- [ ] **Step 2: Add `Requesting Accounts`** to Feature Requests via `notion-update-data-source`: a relation → OS Accounts Database, two-way. Leave `Requesting Account` (text) and `Amount of Requests` as they are.
- [ ] **Step 3: Create the four views** from spec §6: Needs attention, This quarter (board by Outcome), At risk, By account.
- [ ] **Step 4: Verify the Gaps DB is untouched.** `notion-fetch` `collection://cd045eb1-489e-4566-924c-52bae236d36c`. Expected: no new property. This is the one-way check. If a reverse property appeared, delete it and re-create `Related Gap` as one-way.
- [ ] **Step 5: Record the IDs** (Check-ins data source, view URLs) in the runbook `## Config`, then commit.

```bash
git add docs/runbooks/os-quarterly-checkins-runbook.md
git commit -m "chore(checkins): Notion check-in log + FR account relation; runbook config"
```

---

### Task 5: Feature Requests backfill (one-time, reviewed)

**Files:**
- Create: `docs/runbooks/os-checkins-fr-backfill.md`

**Interfaces:**
- Consumes: Task 3 `match`, the Task 4 `Requesting Accounts` relation.

- [ ] **Step 1: Pull inputs.** Query every Feature Requests row (`url`, `Request`, `Requesting Account`, `Amount of Requests`) and every OS Accounts row (`url`, `Account Name`, Active *and* Churned).
- [ ] **Step 2: Match.** For each request with non-empty `Requesting Account`, run `scripts/checkins.py match`. Write a review table into `os-checkins-fr-backfill.md` with columns Request | raw text | matched | uncertain | unmatched.
- [ ] **Step 3: Trent reviews the table.** He resolves the uncertain and unmatched rows and marks the table "approved". **Stop here until approved.**
- [ ] **Step 4: Write the relations** for approved matches only (`notion-update-page`, `Requesting Accounts`). Do **not** change `Amount of Requests` or the text during the backfill: those already reflect the historical asks.
- [ ] **Step 5: Verify** with an SQL count of requests with a non-empty relation, compared to the approved-row count. Commit the filled-in doc.

```bash
git add docs/runbooks/os-checkins-fr-backfill.md
git commit -m "chore(checkins): FR→account backfill review + applied"
```

---

### Task 6: Survey forms and Calendly event (Trent, guided)

**Files:**
- Modify: `docs/runbooks/os-quarterly-checkins-runbook.md` (Config: form IDs, prefill URL templates, responses sheet ID, Calendly URL)

- [ ] **Step 1: Trent creates three Google Forms** (Early / Settled / Mature) with the spec §2 questions verbatim.
  - The two 1–10 scores are Linear scale questions.
  - Every form has a first short-answer question, "Account", which is pre-filled.
  - The last question is the optional "Want to hop on a quick call? (Yes/No)".
  - All three forms link to **one** responses spreadsheet.
- [ ] **Step 2: Capture each form's pre-fill URL template** (Form → Get pre-filled link, using `ACCOUNT` as the placeholder value) and the responses sheet ID.
- [ ] **Step 3: Trent creates the Calendly event type** "OS Check-in, 20 min" and gives the URL.
- [ ] **Step 4: Verify the response path.** Submit one test response per form using a pre-filled link for account `TEST`. `read_file_content` on the responses sheet should show three rows with Account = `TEST` and a form/version column. Trent deletes the test rows afterward.
- [ ] **Step 5: Record everything in Config** and commit.

```bash
git add docs/runbooks/os-quarterly-checkins-runbook.md
git commit -m "chore(checkins): survey forms + Calendly config"
```

---

### Task 7: Runbook: draft pass

**Files:**
- Modify: `docs/runbooks/os-quarterly-checkins-runbook.md`

**Interfaces:**
- Consumes: the Task 3 CLI (`due`), Task 4 IDs, Task 6 links.
- Produces: the "Draft pass" section that `os-checkins-draft` executes.

Write these steps. Model the tone on `docs/runbooks/os-trial-outreach-runbook.md`: numbered steps, exact tool names, a hard-rules header.

- [ ] **Step 1: D1 Load accounts.** `read_file_content` on the sheet and take the Active Customers rows (Account Name, Join Date, POC, Email). Match each to an OS Accounts row with `match`. An unmatched account goes in the summary as "not in Notion" and gets no draft.
- [ ] **Step 2: D2 Build holds.**
  - Front `search_conversations` with the POC email: non-archived gives `open=True`, archived gives `closed_on` = last activity.
  - Open Bug Tracker items on the account give `open=True`.
  - Trent's outbound one-to-one emails in the last 21 days, excluding check-in drafts, give `closed_on` = sent date.
- [ ] **Step 3: D3 Due list.** Gather `last_checkin_on` and `prior_outcomes` from Check-ins rows for the account. Call `checkins.py due` with this week's Monday and keep the output verbatim.
- [ ] **Step 4: D4 Context packet** (Give-first and Different sender only). Collect:
  - linked Feature Requests (shipped and open);
  - Front support history, bugs, and prior check-in answers;
  - completed Feature Requests and Knowledge Hub pages from the last 120 days;
  - Avoma, best-effort.

  Pick one angle by the spec's preference order. List every packet item the opener cites. If no angle is grounded, insert the placeholder string from Global Constraints.
- [ ] **Step 5: D5 Draft.** Create the log row first (Outcome = Drafted), then `create_draft` as a new outbound to the POC email.
  - The draft uses the variant's copy from Appendix A and the version's pre-filled form link (URL-encode the account name), plus Calendly. Channel and BCC per Global Constraints.
  - Write the Front link back to the row.
  - Idempotency: skip if a row exists for this account at Drafted or later within 70 days.
- [ ] **Step 6: D6 Nudges.** For rows at Sent where Sent is 7 or more days ago, there is no response, and Nudged is empty: draft the nudge (Appendix A) as a new outbound with BCC, then set Nudged.
- [ ] **Step 7: Appendix A, email copy.** Draft five templates: Standard, Give-first, Different sender, Nudge, and "You asked, it's live". Each runs about 80–120 words, plain, from Trent. Use `{{first_name}}`, `{{facility}}`, `{{opener}}`, `{{call_link}}` and `{{survey_link}}`. No closing line or signature, because channel `cha_30ds1` appends them. **Trent approves the copy before Task 9.**
- [ ] **Step 8: Commit**

```bash
git add docs/runbooks/os-quarterly-checkins-runbook.md
git commit -m "feat(checkins): runbook draft pass + email copy appendix"
```

---

### Task 8: Runbook: log pass and run summary

**Files:**
- Modify: `docs/runbooks/os-quarterly-checkins-runbook.md`

**Interfaces:**
- Consumes: the Task 3 CLI (`flags`, `latest`, `fr-link`, `match`).

- [ ] **Step 1: L1 Sent detection.** For each Drafted row, read the Front conversation.
  - An outbound message exists: set Outcome = Sent and Sent = that date.
  - The draft is gone and nothing was sent: set Outcome = Skipped.
  - The draft is still there after 7 days: list it under "sitting unsent".
- [ ] **Step 2: L2 Responses.** These run in priority order: a booking beats a survey, which beats a reply.
  - **Survey:** read the responses sheet and match `Account` (plus the email fallback) to the row. Pick the latest response per row with `latest`. Write the scores and answers, then set Outcome = Survey answered.
  - **Booking:** HubSpot `MEETING_EVENT` titled with the Calendly event name, for the contact, after Sent. Set Outcome = Call booked.
  - **Reply:** an inbound reply on the Front conversation. Set Outcome = Replied.
- [ ] **Step 3: L3 Flags.**
  - **Scores:** `checkins.py flags`, against the account's prior scored rows. Low score or Score drop leads to a personal reply draft that names the specific low-rated area, with the context packet added as a Front comment. Set Follow-up = Drafted.
  - **Free text:** judge it for `Competitor tool` / `Workaround` / `Built own`, quoting the exact phrase. For Workaround or Built own, write the proposed FR or Gap wording into `Proposed entry`.
  - Never re-add a signal that's already on the row.
- [ ] **Step 4: L4 Silent.** A row at Sent, 14 or more days after Sent, with no response: set Outcome = Silent and add the `Silent` signal. If the account's prior non-Skipped outcome was also Silent, add `Silent ×2`.
- [ ] **Step 5: L5 Confirmed entries.**
  - `Log it` ticked and no `Related Feature Request` yet: find a matching open request (or create one). Apply `fr-link` and write the relation, text and count. Link the check-in row.
  - `Related Gap` pasted by Trent: nothing to do.
- [ ] **Step 6: L6 Shipped requests.** Feature Requests where `Completed/Closed?` turned true and that have `Requesting Accounts`: for each active account not already notified, draft "You asked, it's live". Record it on that account's latest Check-ins row (Follow-up = Drafted, plus a note).
- [ ] **Step 7: Run summary.** Send a Slack DM to Trent, in this order:
  1. at-risk (Silent ×2);
  2. new flags, with quotes;
  3. proposed entries waiting on "Log it";
  4. drafts created (counts by variant);
  5. held accounts;
  6. sitting unsent;
  7. generic emails, unmatched accounts and responses, and Avoma status.

  If Slack is unavailable, put the same block in the task output.
- [ ] **Step 8: Commit**

```bash
git add docs/runbooks/os-quarterly-checkins-runbook.md
git commit -m "feat(checkins): runbook log pass, flag handling, run summary"
```

---

### Task 9: Install, supervised runs, enable schedules

**Files:**
- Runtime: `~/.claude/scheduled-tasks/os-checkins-draft/SKILL.md` and `~/.claude/scheduled-tasks/os-checkins-log/SKILL.md`, created by the tool.
- Modify: runbook header (install and go-live dates).

- [ ] **Step 1: Install both tasks manual-only** (`create_scheduled_task`, no cron). Each prompt is a thin loader that copies the `os-trial-outreach` SKILL.md structure:
  - hard rules: draft only, and STOP if a connector is missing;
  - `git fetch` + `git show origin/main:docs/runbooks/os-quarterly-checkins-runbook.md`, with a local-file fallback;
  - execute the Draft pass (draft task) or the Log pass (log task);
  - end with the summary.
- [ ] **Step 2: Supervised "Run now" of the draft task with Trent present.** Approve the tools: `create_draft`, `add_comment`, the Notion create/update tools, and Slack DM.
  - Inspect each draft before anything is sent: right POC, right version link, Calendly present, BCC present, no leftover `{{...}}`, and every opener citation traces to the packet.
  - Inspect the log rows created.
- [ ] **Step 3: Supervised "Run now" of the log task** after Trent sends one or two drafts. Expected: rows flip to Sent. Submit one test survey response for a sent account: scores land and flags compute. Delete test artifacts afterward.
- [ ] **Step 4: Fix runbook issues** found in Steps 2–3, then commit and re-run until clean.
- [ ] **Step 5: Enable the schedules** with `update_scheduled_task`. Draft task: `45 8 * * 1` (Mon 8:45 CT). Log task: `30 12 * * 1-5`. Verify with `list_scheduled_tasks` (both enabled, with `nextRunAt` set).
- [ ] **Step 6: Record go-live** in the runbook header and commit. Push `main` (routine, per CLAUDE.md).

```bash
git add docs/runbooks/os-quarterly-checkins-runbook.md
git commit -m "feat(checkins): install + enable scheduled tasks"
git push origin main
```

---

## Notes for the executor

- Tasks 1–3 are code with TDD. Tasks 4–9 are connector and runbook work that needs Trent at three gates: Task 5 Step 3 (backfill approval), Task 7 Step 7 (copy approval), and Task 9 Steps 2–3 (supervised runs). Do not pass a gate without him.
- Until Andrea is set up, the "Different sender" variant drafts on Trent's channel with a Front comment saying "hand to Andrea (tea_d12je)". The owner map gets her channel and Calendly once she's ready.
- `tools/server.py` / registry is not involved. Nothing here writes registry stores.
