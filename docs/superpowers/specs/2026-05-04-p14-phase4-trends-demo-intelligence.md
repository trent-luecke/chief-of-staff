# P14 Phase 4 — Trends, Patterns & Demo Intelligence

**Date:** 2026-05-04
**Status:** Spec

---

## Goal

Extend the weekly synthesis to proactively surface trend anomalies and demo pipeline health without being asked. Currently the weekly run summarizes the current week in isolation; this adds backward-looking pattern detection (4 weeks) and forward-looking demo visibility (4 weeks ahead), delivered via both the weekly email and a Telegram alert.

---

## Delivery

Both outputs combined into a single section in the weekly email (`<h3>Trends & Demo Health</h3>`) and a single Telegram message sent after the retrieval digest. Silently skipped if both functions return empty results. Non-fatal: any exception is caught, logged as a warning, and the weekly run continues.

---

## Architecture

One new module: `processors/pattern_detector.py`  
Two public functions, both called from `weekly_synthesis.py` after `synthesize_week()`.

### Function 1: `detect_anomalies`

```python
def detect_anomalies(
    storage,
    current_synthesis: WeeklySynthesis,
    run_date: date,
    api_key: str,
    model: str,
    lookback_weeks: int = 4,
) -> AnomalyReport
```

**Returns:** `AnomalyReport(anomalies: list[PatternAnomaly])` — empty list if nothing notable or insufficient history.

**Guard:** returns empty immediately if fewer than 2 prior weekly synthesis files exist in `weekly/` (not enough history to compare).

**Step 1 — Python pre-pass (structured delta computation):**

Load all `observations.jsonl` entries from the last 28 days. Group by week. Compute:

| Signal | Metric | Anomaly trigger |
|---|---|---|
| `pipeline_stale` | unique entity count per week | this week vs 4-week average |
| `issue_pattern` | count by channel (email, slack) per week | this week vs 4-week average |
| `kpi_snapshot` — `bugs_high` | parsed from `context` field | week-over-week delta |
| `kpi_snapshot` — `cancellations_mtd` | parsed from `context` field | week-over-week delta |
| Demo trend | last `kpi_snapshot` per calendar month for 3 months, `demos=X` | month-over-month delta |

For `kpi_snapshot` context parsing: fields are space-separated `key=value` pairs (e.g. `bugs_high=2 demos=8`). Take the last snapshot entry per week/month.

**Step 2 — Load prior weekly synthesis patterns:**

Scan `weekly/` in storage. Sort by date descending. Take the 4 most recent files before `run_date`. Extract `## Patterns` bullet lists from each.

**Step 3 — Claude call:**

Pass pre-computed deltas + prior pattern lists + current synthesis patterns. Claude writes narrative for 0–3 anomalies max. Prompt instructs: only surface genuinely notable signals — a metric that is 2x or more above its 4-week average, a pattern recurring for 3+ of the last 4 weeks, or a month-over-month demo count drop of 20%+. Cite specific numbers. Return JSON:

```json
{
  "anomalies": [
    {
      "type": "new" | "recurring" | "worsening",
      "title": "short label",
      "description": "1-2 sentences with specific data",
      "weeks_seen": 1
    }
  ]
}
```

**Dataclasses:**

```python
@dataclass
class PatternAnomaly:
    type: str        # "new" | "recurring" | "worsening"
    title: str
    description: str
    weeks_seen: int = 1

@dataclass
class AnomalyReport:
    anomalies: list[PatternAnomaly] = field(default_factory=list)
```

---

### Function 2: `scan_upcoming_demos`

```python
def scan_upcoming_demos(
    config: dict,
    user_email: str,
    run_date: date,
) -> DemoScanReport
```

**Returns:** `DemoScanReport(demos: list[UpcomingDemo], total: int)` — empty if no demos found.

**Calendar fetch:**

Fetches the next `demo_scan.lookforward_days` (default 28) days of events from all calendar IDs: `config["calendar_ids"]` + `config["demo_scan"]["sales_rep_calendar_ids"]`. Reuses `fetch_today_events` per calendar ID per day, or a new `fetch_date_range_events` helper added to `collectors/calendar.py` that takes a date range and list of calendar IDs.

**Demo classification — all conditions must pass:**

1. `"demo"` (or any keyword in `config["demo_scan"]["demo_keywords"]`, default `["demo"]`) appears in event description (case-insensitive)
2. `"OS"` appears in event title OR description (case-insensitive)
3. At least one attendee whose email domain is not in `config["demo_scan"]["internal_domains"]` (default `["teambuildr.com"]`)
4. Event is not declined by the calendar owner (attendee `self=True` and `responseStatus != "declined"`)
5. Total attendee count ≥ 2

**Pipeline enrichment (non-blocking):**

Cross-reference each external attendee email against the pipeline lead email index (loaded via `load_lead_email_index` for the email→name mapping) and the full pipeline cache (`data/pipeline_cache.json`) for stage/status. If matched: attach `lead_name` and `pipeline_stage` to the `UpcomingDemo`. If not matched: `lead_name = None`, `pipeline_stage = None` (new prospect).

**Empty description handling:**

If an event's description is empty or None, both the demo keyword rule and the "OS" rule will fail — the event is not classified as a demo. This is correct behavior; we don't want to classify a meeting without description evidence.

**Dataclasses:**

```python
@dataclass
class UpcomingDemo:
    date: date
    title: str
    attendee_emails: list[str]
    lead_name: str | None     # None = not in pipeline
    pipeline_stage: str | None

@dataclass
class DemoScanReport:
    demos: list[UpcomingDemo] = field(default_factory=list)
    total: int = 0
```

---

## Config Changes

Add to `config.json`:

```json
"demo_scan": {
  "enabled": true,
  "sales_rep_calendar_ids": [],
  "lookforward_days": 28,
  "demo_keywords": ["demo"],
  "internal_domains": ["teambuildr.com"]
}
```

No changes to existing config keys.

---

## `weekly_synthesis.py` Changes

After `synthesize_week()`, add:

```python
anomaly_report = AnomalyReport()
demo_report = DemoScanReport()

if config.get("demo_scan", {}).get("enabled"):
    try:
        anomaly_report = detect_anomalies(storage, synthesis, run_date, api_key, config["ai_model"])
    except Exception as e:
        print(f"WARNING: anomaly detection failed: {e}", file=sys.stderr)
    try:
        demo_report = scan_upcoming_demos(config, config["email"], run_date)
    except Exception as e:
        print(f"WARNING: demo scan failed: {e}", file=sys.stderr)
```

If either report has content:
- Append `<h3>Trends & Demo Health</h3>` section to HTML email
- Send a single Telegram message: `"📈 Trends & Demo Health — week ending {date}\n\n{formatted content}"`

---

## Output Format

**Email section:**

```html
<h3>Trends & Demo Health</h3>
<!-- Anomalies (if any) -->
<h4>Pattern Alerts</h4>
<ul>
  <li><strong>[title]</strong> — [description]</li>
</ul>
<!-- Demo scan (if any) -->
<h4>Upcoming Demos ({N} in next 28 days)</h4>
<ul>
  <li>[date] — [title] — [lead_name or "new prospect"] ([pipeline_stage or "not in pipeline"])</li>
</ul>
```

Section omitted entirely if both `anomaly_report.anomalies` and `demo_report.demos` are empty.

**Telegram message:**

Plain text, one anomaly or demo per line. No HTML.

---

## New Calendar Helper

Add `fetch_date_range_events` to `collectors/calendar.py`:

```python
def fetch_date_range_events(
    calendar_ids: list[str],
    start_date: date,
    end_date: date,
    user_email: str = "",
) -> list[CalendarEvent]
```

Loops over each calendar ID and each date in the range, calls `fetch_today_events`, deduplicates by event ID, returns sorted by start time. Non-fatal: individual calendar failures are logged and skipped.

---

## Error Handling

- `detect_anomalies`: any exception → return empty `AnomalyReport()`
- `scan_upcoming_demos`: any exception → return empty `DemoScanReport()`
- Individual calendar fetch failures: logged, skipped, other calendars continue
- Claude JSON parse failure in anomaly detection: return empty `AnomalyReport()`
- Fewer than 2 prior weekly files: return empty `AnomalyReport()` without calling Claude

---

## Tests

- `tests/test_pattern_detector.py`
  - Delta computation from fixture observations (pipeline_stale count, kpi_snapshot parsing)
  - Demo month-over-month delta from fixture kpi_snapshots
  - Guard: empty report when < 2 prior weekly files
  - Demo classification: each rule independently (missing "OS", no external attendee, declined, missing "demo" in description)
  - Pipeline enrichment: known lead vs. new prospect
  - `fetch_date_range_events`: deduplication across calendar IDs

---

## Out of Scope

- Changing the existing weekly synthesizer prompt or output structure
- Alerting outside the weekly run cadence (real-time anomaly detection)
- Writing observations back to JSONL from pattern detector results
- Fetching rep calendars during the daily brief run
