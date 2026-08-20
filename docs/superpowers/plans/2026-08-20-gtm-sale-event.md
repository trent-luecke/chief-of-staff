# GTM Sale Event Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Sales Tracker sheet into the event-sourced deal store as a new `sale` DealEvent kind, folding matched sales into `won` deals (close_date, deal_value) that flow to OMS unchanged.

**Architecture:** Mirror the existing demo pipeline exactly — `read sheet → normalize into DealEvents → append to deal_events.jsonl → deal_fold → push_deals`. A new reader (`lib/sales_sheet.py`) and normalizer (`normalize_sale_events`) feed the append log; `deal_fold` gains a `sale` branch; `refresh_deal_store` gains a non-fatal sale-sync block. No OMS change (it already carries `close_date`/`outcome`/`deal_value`/`review`).

**Tech Stack:** Python 3, `googleapiclient` (Sheets v4), pytest. Existing modules: `lib/deal_events.py`, `lib/deal_normalize.py`, `lib/deal_fold.py`, `lib/deal_sync.py`, `lib/email_norm.py`, `lib/google_auth.py`.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-20-gtm-sale-event-design.md` is authoritative.
- **Append-only, email-keyed, idempotent:** sales become `DealEvent(kind="sale")`; dedup by `event_id`. Re-reading the same sheet must be a no-op.
- **Enum values:** `outcome ∈ {open, won, lost}`; `stage ∈ {demoed, in_trial, won, lost}`. A sale sets `outcome="won"`, `stage="won"`.
- **Precedence:** a terminal `status=lost` event beats a sale. Resolution order: `lost` > `sale`(won) > `open`.
- **Email keying:** `normalize_email` lowercases, strips `+tags`, and returns `None` for blank/malformed/`@teambuildr.com` addresses. A row whose email normalizes to `None` is skipped.
- **Scope:** read only the **current-month tab** named `"{Month} {Year}"` (e.g. `August 2026`); `August 2026` is the earliest tab with an email column. Missing tab → no-op.
- **Non-fatal:** any sheet/parse/auth failure is logged and swallowed; the rest of the deal refresh still runs.
- **Sheet id:** `config["meeting_prep"]["sheets"]["sales_spreadsheet_id"]` (`1pOUxLMX2H48miMvEbgqOXq1C0VHkGm-XXW2VCodQfU0`).
- **Sheet layout:** row 1 = column headers (`Date`, `Total Sale`, `Customer Name`, `Customer Email`, `Salesperson`); rows 2→`Bundle Sales` header = OS-only (`source="os_only"`); `Bundle Sales`→`Trent TB Sales` header = bundle (`source="bundle"`); stop at `Trent TB Sales`.

---

### Task 1: Sale-row parsing helpers

**Files:**
- Modify: `lib/deal_normalize.py` (add helpers at top, after imports)
- Test: `tests/test_deal_normalize.py` (add tests)

**Interfaces:**
- Produces: `parse_money(raw: str | None) -> float | None`, `parse_close_date(raw: str | None) -> str | None` (ISO `YYYY-MM-DD` or `None`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_deal_normalize.py`:

```python
from lib.deal_normalize import parse_money, parse_close_date


def test_parse_money_strips_currency_and_commas():
    assert parse_money("$1,200") == 1200.0
    assert parse_money("1200") == 1200.0
    assert parse_money(" $3,499.50 ") == 3499.50


def test_parse_money_blank_or_bad_is_none():
    assert parse_money("") is None
    assert parse_money(None) is None
    assert parse_money("N/A") is None


def test_parse_close_date_accepts_slash_and_iso():
    assert parse_close_date("8/18/2026") == "2026-08-18"
    assert parse_close_date("2026-08-18") == "2026-08-18"


def test_parse_close_date_blank_or_bad_is_none():
    assert parse_close_date("") is None
    assert parse_close_date(None) is None
    assert parse_close_date("not a date") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_deal_normalize.py -k "parse_money or parse_close_date" -v`
Expected: FAIL with `ImportError: cannot import name 'parse_money'`

- [ ] **Step 3: Write minimal implementation**

Add to `lib/deal_normalize.py` (after the existing imports at the top):

```python
from datetime import datetime

_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y")


def parse_money(raw: str | None) -> float | None:
    """'$1,200' -> 1200.0; blank/non-numeric -> None."""
    if raw is None:
        return None
    s = str(raw).strip().replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_close_date(raw: str | None) -> str | None:
    """Tolerant close-date parse to ISO 'YYYY-MM-DD'; unparseable -> None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_deal_normalize.py -k "parse_money or parse_close_date" -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/deal_normalize.py tests/test_deal_normalize.py
git commit -m "feat: add money/date parsing helpers for sale rows"
```

---

### Task 2: `normalize_sale_events`

**Files:**
- Modify: `lib/deal_normalize.py` (add function)
- Test: `tests/test_deal_normalize.py` (add tests)

**Interfaces:**
- Consumes: `parse_money`, `parse_close_date` (Task 1); `normalize_email` (`lib/email_norm`); `DealEvent`, `make_event_id` (`lib/deal_events`).
- Produces: `normalize_sale_events(rows: list[dict]) -> list[DealEvent]`. Input row dict keys: `date, total_sale, customer_name, customer_email, salesperson, source`. Output events have `kind="sale"`, `timestamp=<ISO close date>`, `payload={"deal_value": float | None}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_deal_normalize.py`:

```python
from lib.deal_normalize import normalize_sale_events


def _row(email="jane@acme.com", date="8/18/2026", total="$1,200",
         name="Acme", rep="Luke Martin", source="os_only"):
    return {"date": date, "total_sale": total, "customer_name": name,
            "customer_email": email, "salesperson": rep, "source": source}


def test_normalize_sale_event_basic():
    evs = normalize_sale_events([_row()])
    assert len(evs) == 1
    e = evs[0]
    assert e.kind == "sale"
    assert e.email == "jane@acme.com"
    assert e.timestamp == "2026-08-18"
    assert e.rep == "Luke Martin"
    assert e.account_name == "Acme"
    assert e.source == "os_only"
    assert e.payload["deal_value"] == 1200.0


def test_normalize_sale_skips_internal_and_blank_email():
    rows = [_row(email="rep@teambuildr.com"), _row(email=""), _row(email="nope")]
    assert normalize_sale_events(rows) == []


def test_normalize_sale_skips_row_without_date():
    assert normalize_sale_events([_row(date="")]) == []


def test_normalize_sale_event_id_is_stable_and_content_based():
    a = normalize_sale_events([_row()])[0]
    b = normalize_sale_events([_row()])[0]
    assert a.event_id == b.event_id
    # editing the amount changes the id (new event; fold later-wins handles it)
    c = normalize_sale_events([_row(total="$1,300")])[0]
    assert c.event_id != a.event_id


def test_normalize_sale_bundle_source_and_null_value():
    e = normalize_sale_events([_row(total="", source="bundle")])[0]
    assert e.source == "bundle"
    assert e.payload["deal_value"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_deal_normalize.py -k "normalize_sale" -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_sale_events'`

- [ ] **Step 3: Write minimal implementation**

Add to `lib/deal_normalize.py` (after `normalize_demo_events`):

```python
def normalize_sale_events(rows: list[dict]) -> list[DealEvent]:
    """Turn Sales Tracker rows into email-keyed `sale` DealEvents. Rows without
    a valid external email or a parseable close date are skipped."""
    events: list[DealEvent] = []
    for r in rows:
        raw_email = r.get("customer_email", "") or ""
        email = normalize_email(raw_email)
        if not email:
            continue
        close = parse_close_date(r.get("date"))
        if not close:
            continue
        total_raw = r.get("total_sale", "") or ""
        value = parse_money(total_raw)
        native_id = f"{close}|{email}|{total_raw}"
        events.append(DealEvent(
            event_id=make_event_id("sale", native_id, email),
            email=email,
            email_raw=raw_email,
            kind="sale",
            timestamp=close,
            account_name=r.get("customer_name", "") or "",
            rep=r.get("salesperson", "") or "",
            source=r.get("source", "") or "",
            payload={"deal_value": value},
        ))
    return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_deal_normalize.py -k "normalize_sale" -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/deal_normalize.py tests/test_deal_normalize.py
git commit -m "feat: normalize Sales Tracker rows into sale DealEvents"
```

---

### Task 3: Sheet reader `lib/sales_sheet.py`

**Files:**
- Create: `lib/sales_sheet.py`
- Test: `tests/test_sales_sheet.py` (create)

**Interfaces:**
- Produces:
  - `_split_sections(values: list[list]) -> list[dict]` — pure; maps row-1 headers to fields, splits OS-only/bundle by label rows, stops at `Trent TB Sales`. Row dict keys: `date, total_sale, customer_name, customer_email, salesperson, source`.
  - `fetch_sale_rows(config: dict, today: str, service=None) -> list[dict]` — resolves current-month tab, reads via Sheets, returns `_split_sections(values)`; missing sheet id or API error → `[]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sales_sheet.py`:

```python
from lib.sales_sheet import _split_sections, fetch_sale_rows

HEADER = ["Date", "", "", "Total Sale", "Customer Name", "Customer Email", "Salesperson"]


def _data(date, total, name, email, rep):
    return [date, "", "", total, name, email, rep]


def test_split_sections_os_only_and_bundle():
    values = [
        HEADER,
        _data("8/1/2026", "$1,000", "Acme", "a@acme.com", "Luke Martin"),
        _data("8/2/2026", "$2,000", "Beta", "b@beta.com", "Ryan Allwein"),
        ["Bundle Sales"],
        _data("8/3/2026", "$5,000", "Gamma", "g@gamma.com", "Luke Martin"),
        ["Trent TB Sales"],
        _data("8/4/2026", "$9,999", "Ignore", "x@ignore.com", "Trent"),
    ]
    rows = _split_sections(values)
    assert [r["source"] for r in rows] == ["os_only", "os_only", "bundle"]
    assert rows[0]["customer_email"] == "a@acme.com"
    assert rows[2]["customer_name"] == "Gamma"
    assert all(r["customer_email"] != "x@ignore.com" for r in rows)  # below Trent TB stop


def test_split_sections_skips_blank_rows_and_handles_growth():
    values = [
        HEADER,
        _data("8/1/2026", "$1,000", "Acme", "a@acme.com", "Luke Martin"),
        ["", "", "", "", "", "", ""],
        _data("8/2/2026", "$2,000", "Beta", "b@beta.com", "Ryan Allwein"),
        ["Bundle Sales"],
        _data("8/3/2026", "$5,000", "Gamma", "g@gamma.com", "Luke Martin"),
    ]
    rows = _split_sections(values)
    assert len(rows) == 3
    assert [r["source"] for r in rows] == ["os_only", "os_only", "bundle"]


def test_split_sections_empty():
    assert _split_sections([]) == []


class _FakeService:
    def __init__(self, values):
        self._values = values

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range):
        self.last_range = range
        return self

    def execute(self):
        return {"values": self._values}


def test_fetch_sale_rows_resolves_current_month_tab():
    cfg = {"meeting_prep": {"sheets": {"sales_spreadsheet_id": "SID"}}}
    svc = _FakeService([HEADER, _data("8/1/2026", "$1,000", "Acme", "a@acme.com", "Luke")])
    rows = fetch_sale_rows(cfg, "2026-08-20", service=svc)
    assert svc.last_range.startswith("'August 2026'!")
    assert rows[0]["customer_email"] == "a@acme.com"


def test_fetch_sale_rows_missing_id_returns_empty():
    assert fetch_sale_rows({}, "2026-08-20", service=object()) == []


def test_fetch_sale_rows_api_error_returns_empty():
    class _Boom:
        def spreadsheets(self):
            raise RuntimeError("no such tab")
    cfg = {"meeting_prep": {"sheets": {"sales_spreadsheet_id": "SID"}}}
    assert fetch_sale_rows(cfg, "2026-08-20", service=_Boom()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sales_sheet.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.sales_sheet'`

- [ ] **Step 3: Write minimal implementation**

Create `lib/sales_sheet.py`:

```python
"""Read the current-month tab of the Sales Tracker sheet into raw sale rows.

Two in-scope sections delimited by label rows: OS-only (rows after the column
header, source="os_only") and bundle (after a "Bundle Sales" label,
source="bundle"). Everything at/after a "Trent TB Sales" label is ignored.
Column positions are resolved by header name, not letter.
"""
from __future__ import annotations

from datetime import date

_HEADER_FIELDS = {
    "date": "date",
    "total sale": "total_sale",
    "customer name": "customer_name",
    "customer email": "customer_email",
    "salesperson": "salesperson",
}
_BUNDLE_HEADER = "bundle sales"
_STOP_HEADER = "trent tb sales"


def _split_sections(values: list[list]) -> list[dict]:
    if not values:
        return []
    header = values[0]
    col_field: dict[int, str] = {}
    for idx, cell in enumerate(header):
        key = str(cell).strip().lower()
        if key in _HEADER_FIELDS:
            col_field[idx] = _HEADER_FIELDS[key]

    rows: list[dict] = []
    section = "os_only"
    for raw in values[1:]:
        joined = " ".join(str(c).strip().lower() for c in raw if str(c).strip())
        if _STOP_HEADER in joined:
            break
        if _BUNDLE_HEADER in joined:
            section = "bundle"
            continue
        rec = {
            field: (str(raw[idx]).strip() if idx < len(raw) and raw[idx] is not None else "")
            for idx, field in col_field.items()
        }
        if not rec.get("customer_email") and not rec.get("date"):
            continue  # blank / non-data row
        rec["source"] = section
        rows.append(rec)
    return rows


def fetch_sale_rows(config: dict, today: str, service=None) -> list[dict]:
    sid = (
        config.get("meeting_prep", {})
        .get("sheets", {})
        .get("sales_spreadsheet_id", "")
    )
    if not sid:
        return []
    tab = date.fromisoformat(today[:10]).strftime("%B %Y")
    try:
        if service is None:
            from lib.google_auth import build_sheets_service
            service = build_sheets_service()
        resp = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sid, range=f"'{tab}'!A1:G200")
            .execute()
        )
    except Exception:
        return []
    return _split_sections(resp.get("values", []))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sales_sheet.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/sales_sheet.py tests/test_sales_sheet.py
git commit -m "feat: read Sales Tracker current-month tab into sale rows"
```

---

### Task 4: Fold `sale` events into `won` deals

**Files:**
- Modify: `lib/deal_fold.py` (`build_deals`)
- Test: `tests/test_deal_fold.py` (add tests)

**Interfaces:**
- Consumes: `DealEvent` with `kind="sale"`, `timestamp=<ISO date>`, `payload={"deal_value": float|None}`, `source` (Task 2).
- Produces: folded `Deal` with `outcome="won"`, `stage="won"`, `close_date`, `deal_value`, `source`, and `review={"needs": True, "kind": "unmatched_sale", ...}` when the deal is sale-only.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_deal_fold.py` (the file already imports `DealEvent`, `build_deals`, and defines `_demo`/`TODAY`):

```python
def _sale(email, ts, value=1200.0, source="os_only"):
    return DealEvent(event_id=f"sale-{email}-{ts}-{value}", email=email, email_raw="",
                     kind="sale", timestamp=ts, rep="Luke Martin", source=source,
                     payload={"deal_value": value})


def test_sale_matched_to_demo_folds_to_won():
    events = [_demo("a", "jane@acme.com", "2026-08-01T00:00:00Z", ["jane@acme.com"]),
              _sale("jane@acme.com", "2026-08-15")]
    d = build_deals(events, {}, TODAY)["jane@acme.com"]
    assert d.outcome == "won" and d.stage == "won"
    assert d.close_date == "2026-08-15"
    assert d.deal_value == 1200.0
    assert d.source == "os_only"
    assert d.review.get("needs") is False


def test_unmatched_sale_is_won_and_flagged_for_review():
    d = build_deals([_sale("ghost@nowhere.com", "2026-08-15")], {}, TODAY)["ghost@nowhere.com"]
    assert d.outcome == "won" and d.stage == "won"
    assert d.review.get("needs") is True
    assert d.review.get("kind") == "unmatched_sale"


def test_lost_beats_sale():
    lost = DealEvent(event_id="s1", email="jane@acme.com", email_raw="", kind="status",
                     timestamp="2026-08-20T00:00:00Z", payload={"status": "lost"})
    events = [_demo("a", "jane@acme.com", "2026-08-01T00:00:00Z", ["jane@acme.com"]),
              _sale("jane@acme.com", "2026-08-15"), lost]
    d = build_deals(events, {}, TODAY)["jane@acme.com"]
    assert d.outcome == "lost" and d.stage == "lost"


def test_later_sale_wins_on_correction():
    events = [_demo("a", "jane@acme.com", "2026-08-01T00:00:00Z", ["jane@acme.com"]),
              _sale("jane@acme.com", "2026-08-15", value=1200.0),
              _sale("jane@acme.com", "2026-08-16", value=1500.0)]
    d = build_deals(events, {}, TODAY)["jane@acme.com"]
    assert d.close_date == "2026-08-16"
    assert d.deal_value == 1500.0


def test_sale_only_deal_has_no_cycle_start():
    d = build_deals([_sale("ghost@nowhere.com", "2026-08-15")], {}, TODAY)["ghost@nowhere.com"]
    assert d.cycle_start is None  # excluded from cycle-velocity, still a won count
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_deal_fold.py -k "sale or lost_beats" -v`
Expected: FAIL — `test_sale_matched_to_demo_folds_to_won` fails on `outcome == "won"` (currently `has_real` sets it to `open`/`demoed`).

- [ ] **Step 3: Write minimal implementation**

In `lib/deal_fold.py`, inside `build_deals`:

(a) Add two locals with the other init vars (near `seed_value = None`):

```python
        has_sale = False
        sale_source = ""
```

(b) Add a `sale` branch inside the per-event `for e in evs:` loop (alongside the other `if e.kind == ...` blocks, e.g. after the `seed` block):

```python
            if e.kind == "sale":
                p = _payload(e)
                if e.timestamp:
                    d.close_date = e.timestamp        # evs sorted → later sale wins
                if p.get("deal_value") is not None:
                    d.deal_value = p["deal_value"]
                if e.source:
                    sale_source = e.source
                has_sale = True
```

(c) Insert a `won` branch into the outcome/stage resolution — it MUST come before `elif has_real:`:

```python
        has_real = any(e.kind in ("demo", "trial", "sale") for e in evs)
        if d.outcome == "lost":                 # explicit status=lost event — terminal
            d.stage = "lost"
            d.lost_reason = lost_reason
        elif has_sale:                          # a sale closes the deal — won
            d.outcome = "won"
            d.stage = "won"
            if sale_source:
                d.source = sale_source
        elif has_real:                          # real demo/trial drives stage
            d.outcome = "open"
            d.stage = "demoed"
        elif seed_stage or seed_outcome:
            d.outcome = seed_outcome or "open"
            d.stage = seed_stage or "demoed"
        else:
            d.outcome = "open"
            d.stage = "demoed"
```

(d) Compute the sale-only flag (after the `has_real` line is fine; place it just before the review block, near `effective_start`):

```python
        sale_only = has_sale and not any(e.kind in ("demo", "trial", "seed") for e in evs)
```

(e) Add an `unmatched_sale` branch to the review block — after the `ambiguous` branch, before `snoozed`:

```python
        elif sale_only:
            d.review = {"needs": True, "kind": "unmatched_sale", "reason": "sale_no_demo",
                        "proposed": {"email": email, "account_name": d.account_name, "rep": d.rep}}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_deal_fold.py -v`
Expected: PASS (existing fold tests + the 5 new ones).

- [ ] **Step 5: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "feat: fold sale events into won deals + flag unmatched sales"
```

---

### Task 5: Surface `unmatched_sale` in the review queue

**Files:**
- Modify: `lib/deal_fold.py` (`build_deals_to_review`)
- Test: `tests/test_deal_fold.py` (add test)

**Interfaces:**
- Consumes: a `Deal` with `review.kind == "unmatched_sale"` (Task 4).
- Produces: that deal appears in the `identity` queue of `build_deals_to_review`'s output.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_deal_fold.py`:

```python
from lib.deal_fold import build_deals_to_review


def test_unmatched_sale_surfaces_in_identity_queue():
    deals = build_deals([_sale("ghost@nowhere.com", "2026-08-15")], {}, TODAY)
    review = build_deals_to_review(deals)
    keys = [item["deal_key"] for item in review["identity"]]
    assert "ghost@nowhere.com" in keys
    assert review["counts"]["identity"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_deal_fold.py::test_unmatched_sale_surfaces_in_identity_queue -v`
Expected: FAIL — key not in `identity` (only `kind == "ambiguous"` is bucketed today).

- [ ] **Step 3: Write minimal implementation**

In `lib/deal_fold.py`, `build_deals_to_review`, change the identity condition:

```python
        if d.review.get("kind") in ("ambiguous", "unmatched_sale"):
```

(was `== "ambiguous"`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_deal_fold.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "feat: surface unmatched sales in the identity review queue"
```

---

### Task 6: Wire the sale feed into `refresh_deal_store`

**Files:**
- Modify: `lib/deal_sync.py` (`refresh_deal_store` — add `config` param + non-fatal sale block)
- Modify: `scripts/avoma_sync.py:317` (pass `config=config` at the call site)
- Test: `tests/test_deal_sync.py` (add test)

**Interfaces:**
- Consumes: `fetch_sale_rows` (Task 3), `normalize_sale_events` (Task 2).
- Produces: `refresh_deal_store(..., config: dict | None = None)` — when `config` is provided, fetches + normalizes + appends sale events before folding; `config=None` (existing callers/tests) skips the sale block unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_deal_sync.py`:

```python
def test_refresh_ingests_sales_when_config_provided(tmp_path, monkeypatch):
    s = LocalStorage(base_dir=str(tmp_path))
    transcripts = [T("u1", "Demo", "2026-08-01T15:00:00Z", "demo", True, "Luke Martin",
                     [{"name": "Jane", "email": "jane@acme.com"}])]
    monkeypatch.setattr(
        "lib.deal_sync.fetch_sale_rows",
        lambda config, today: [{"date": "8/15/2026", "total_sale": "$1,200",
                                "customer_name": "Acme", "customer_email": "jane@acme.com",
                                "salesperson": "Luke Martin", "source": "os_only"}],
    )
    out = refresh_deal_store(transcripts, s, "2026-08-18", "2026-08-18T00:00:00Z",
                             config={"meeting_prep": {"sheets": {"sales_spreadsheet_id": "SID"}}})
    cache = s.read_json("deal_pipeline_cache.json")
    lead = next(l for l in cache["leads"] if l["email"] == "jane@acme.com")
    assert lead["status"] == "won"
    assert out["appended"] == 2  # 1 demo + 1 sale


def test_refresh_without_config_skips_sales(tmp_path, monkeypatch):
    s = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr("lib.deal_sync.fetch_sale_rows",
                        lambda config, today: (_ for _ in ()).throw(AssertionError("must not fetch")))
    transcripts = [T("u1", "Demo", "2026-08-01T15:00:00Z", "demo", True, "Luke Martin",
                     [{"name": "Jane", "email": "jane@acme.com"}])]
    out = refresh_deal_store(transcripts, s, "2026-08-18", "2026-08-18T00:00:00Z")
    assert out["appended"] == 1  # demo only; sale block not entered
```

Note: `deals_to_pipeline_cache` maps a deal's `stage` to the `status` field — assert `status == "won"`. If the projection uses a different key for stage, adjust the assertion to read that key (check `lib/deal_projection.py`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_deal_sync.py -k "sales or skips_sales" -v`
Expected: FAIL — `refresh_deal_store` has no `config` kwarg (`TypeError: unexpected keyword argument 'config'`).

- [ ] **Step 3: Write minimal implementation**

In `lib/deal_sync.py`:

(a) Extend imports:

```python
import sys
from lib.deal_normalize import normalize_demo_events, normalize_sale_events
from lib.sales_sheet import fetch_sale_rows
```

(b) Add the `config` param and the non-fatal sale block:

```python
def refresh_deal_store(transcripts, storage, today: str, fetched_at: str,
                       stale_days: int = 45, cache_key: str = "deal_pipeline_cache.json",
                       base_url: str = "", password: str = "", config: dict | None = None) -> dict:
    appended = append_events(storage, normalize_demo_events(transcripts))
    if config is not None:
        try:
            sale_rows = fetch_sale_rows(config, today)
            appended += append_events(storage, normalize_sale_events(sale_rows))
        except Exception as e:  # non-fatal: sales never sink the deal refresh
            print(f"⚠️  Sale sync error (non-fatal): {e}", file=sys.stderr)
    events = load_events(storage)
    # ... rest unchanged ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_deal_sync.py -v`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Wire the call site**

In `scripts/avoma_sync.py`, the `refresh_deal_store(...)` call (~line 317) — add `config=config`:

```python
        summary = refresh_deal_store(
            transcripts, dstore, today=today,
            fetched_at=datetime.utcnow().isoformat() + "Z",
            stale_days=stale_days, base_url=base_url, password=password,
            config=config,
        )
```

(Confirm the local variable holding the loaded config dict is named `config` in `avoma_sync.py`; if it differs, pass that name.)

- [ ] **Step 6: Run the full deal suite**

Run: `python3 -m pytest tests/test_deal_sync.py tests/test_deal_fold.py tests/test_deal_normalize.py tests/test_sales_sheet.py -v`
Expected: PASS (all green).

- [ ] **Step 7: Commit**

```bash
git add lib/deal_sync.py scripts/avoma_sync.py tests/test_deal_sync.py
git commit -m "feat: ingest Sales Tracker sales in nightly deal refresh"
```

---

### Task 7: Verify against the real sheet (spec §9 open items)

**Files:** none (verification only; may produce a follow-up fix commit)

- [ ] **Step 1: Confirm the spreadsheet id and date format**

Run a one-off read against the live sheet (Google auth must be configured — `GOOGLE_OAUTH_JSON` in `.env`):

```bash
python3 -c "
import json, os
from dotenv import load_dotenv; load_dotenv()
from lib.google_auth import build_sheets_service
cfg = json.load(open('config.json'))
sid = cfg['meeting_prep']['sheets']['sales_spreadsheet_id']
svc = build_sheets_service()
vals = svc.spreadsheets().values().get(spreadsheetId=sid, range=\"'August 2026'!A1:G30\").execute().get('values', [])
for r in vals[:6]: print(r)
"
```
Expected: row 1 shows the `Date … Total Sale … Customer Name … Customer Email … Salesperson` headers; data rows show the actual `Date` cell format.

- [ ] **Step 2: If the date format isn't already handled, extend `_DATE_FORMATS`**

If column A prints a format not in `("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y")`, add the exact `strptime` format string to `_DATE_FORMATS` in `lib/deal_normalize.py`, add a `parse_close_date` test for it, and re-run `python3 -m pytest tests/test_deal_normalize.py -k parse_close_date -v`.

- [ ] **Step 3: Commit any fix**

```bash
git add lib/deal_normalize.py tests/test_deal_normalize.py
git commit -m "fix: handle real Sales Tracker date format"
```

(If no change was needed, note that verification passed and skip the commit.)
