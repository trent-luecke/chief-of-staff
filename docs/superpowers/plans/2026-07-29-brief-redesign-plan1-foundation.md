# Brief Redesign — Plan 1: Identity Resolution + Attendee Auto-Provisioning

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a shared identity-resolution module and an attendee auto-provisioning step so that every external attendee on today's small meetings has a registry "home" before the post-call transcript is processed.

**Architecture:** Consolidate the find-by-email / find-by-name / slug / stub-id logic currently duplicated across five files into one `lib/identity.py`. Build `processors/attendee_provisioner.py` on top of it to create stub people records for unresolved external attendees, writing to the git-anchored `data/people_registry.json` via `registry_storage(config)` (LocalStorage on the working tree — never R2). A thin CLI (`scripts/provision_today_attendees.py`) makes the whole thing independently runnable against the real calendar.

**Tech Stack:** Python 3, pytest, rapidfuzz (`fuzz.token_sort_ratio`), Google Calendar API (via existing `collectors/calendar.py`), `lib.storage.LocalStorage`.

## Global Constraints

- **Registry access:** the people registry is git-anchored on `origin/main`. Runtime jobs MUST read/write it via `lib.storage.registry_storage(config)` (returns `LocalStorage(base_dir=config.get("data_dir","data"))`), NEVER via `build_storage` (R2). Registry file key: `"people_registry.json"`.
- **Registry schema (v1):** `{"version": int, "people": [ {person} ]}`. Person record fields: `id` (str, slug), `canonical_name` (str), `aliases` (list[str], mix of names + emails), `email` (str, may be `""`), `type` (str ∈ {internal, lead, unknown, partner}), `pipeline_record` (str|null), `people_file` (str|null), `created` (ISO date str), `last_seen` (ISO date str). Auto-created stubs additionally carry `provenance` (str).
- **Fuzzy match threshold:** `FUZZY_THRESHOLD = 85` using `rapidfuzz.fuzz.token_sort_ratio` (matches every existing resolver).
- **Internal domain source:** `config["demo_scan"]["internal_domains"]`, default `["teambuildr.com"]`.
- **Provisioning guards:** skip internal attendees; skip any event with **6 or more** attendees (only events with ≤5 attendees provision).
- **No auto-merge:** resolution finds an existing person or returns `None`. It never silently merges a fuzzy match into an existing record.
- **Test style:** pytest, run from repo root. Use `tmp_path` for filesystem, `unittest.mock.patch` on the module-local `_build_service` seam for Google calls (see `tests/test_calendar.py`). No `conftest.py`.
- **Commits:** frequent, one per task. This plan does NOT modify `.github/workflows/brief.yml` or wire provisioning into the brief pipeline — that is Plan 2's job.

---

## File Structure

- **Create `lib/identity.py`** — the shared resolver. Pure functions + registry load helper. No side effects except through a passed-in `storage`.
- **Modify `collectors/calendar.py`** — add `attendee_details: list[dict]` to `CalendarEvent` and populate attendee display names in the single parse loop (`fetch_today_events`, which the other two fetchers delegate to).
- **Create `processors/attendee_provisioner.py`** — `classify_attendees`, `stubs_for_events` (pure), `provision_from_events` (I/O wrapper).
- **Create `scripts/provision_today_attendees.py`** — thin CLI entrypoint for standalone runs + verification.
- **Create tests:** `tests/test_identity.py`, extend `tests/test_calendar.py`, `tests/test_attendee_provisioner.py`.

---

## Task 1: Shared identity-resolution module (`lib/identity.py`)

**Files:**
- Create: `lib/identity.py`
- Test: `tests/test_identity.py`

**Interfaces:**
- Consumes: `rapidfuzz.fuzz`, a `storage` object exposing `read_json(key, default)` (from `lib.storage.LocalStorage`).
- Produces (later tasks + Plans 3/4 rely on these exact signatures):
  - `slugify(name: str) -> str`
  - `unique_id(base: str, existing_ids) -> str`
  - `is_internal(email: str, internal_domains) -> bool`
  - `name_from_email(email: str) -> str`
  - `load_people(storage) -> list[dict]`
  - `build_lookup(people: list[dict]) -> tuple[dict, list]`  (returns `(email_index, alias_list)`)
  - `find_by_email(email: str, email_index: dict) -> Optional[str]`
  - `find_by_name(name: str, alias_list: list, threshold: int = 85) -> tuple[Optional[str], int]`
  - `resolve(name: str, email: str, email_index: dict, alias_list: list, threshold: int = 85) -> Optional[str]`
  - Constants: `FUZZY_THRESHOLD = 85`, `REGISTRY_KEY = "people_registry.json"`

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity.py`:

```python
from lib import identity


def test_slugify_basic():
    assert identity.slugify("Trent Luecke") == "trent-luecke"
    assert identity.slugify("Patrick LaBat — TGMC") == "patrick-labat-tgmc"


def test_unique_id_appends_suffix():
    assert identity.unique_id("jane-smith", set()) == "jane-smith"
    assert identity.unique_id("jane-smith", {"jane-smith"}) == "jane-smith-2"
    assert identity.unique_id("jane-smith", {"jane-smith", "jane-smith-2"}) == "jane-smith-3"


def test_is_internal():
    assert identity.is_internal("q@teambuildr.com", ["teambuildr.com"]) is True
    assert identity.is_internal("lead@acme.com", ["teambuildr.com"]) is False
    assert identity.is_internal("", ["teambuildr.com"]) is False
    assert identity.is_internal("noatsign", ["teambuildr.com"]) is False


def test_name_from_email():
    assert identity.name_from_email("jane.smith@acme.com") == "Jane Smith"
    assert identity.name_from_email("mike_jones@x.io") == "Mike Jones"
    assert identity.name_from_email("bob@x.io") == "Bob"


def _people():
    return [
        {"id": "trent-luecke", "canonical_name": "Trent Luecke",
         "aliases": ["Trent Luecke", "trent@teambuildr.com", "Trent"],
         "email": "trent@teambuildr.com", "type": "internal"},
        {"id": "jane-smith", "canonical_name": "Jane Smith",
         "aliases": ["Jane Smith", "jane@acme.com"],
         "email": "jane@acme.com", "type": "lead"},
    ]


def test_build_lookup_indexes_emails_and_names():
    email_index, alias_list = identity.build_lookup(_people())
    assert email_index["trent@teambuildr.com"] == "trent-luecke"
    assert email_index["jane@acme.com"] == "jane-smith"
    assert ("trent-luecke", "trent") in alias_list


def test_find_by_email_case_insensitive():
    email_index, _ = identity.build_lookup(_people())
    assert identity.find_by_email("JANE@ACME.COM", email_index) == "jane-smith"
    assert identity.find_by_email("nobody@x.io", email_index) is None
    assert identity.find_by_email("", email_index) is None


def test_find_by_name_exact_and_fuzzy_and_miss():
    _, alias_list = identity.build_lookup(_people())
    assert identity.find_by_name("Jane Smith", alias_list)[0] == "jane-smith"
    # fuzzy: minor variation still clears threshold
    assert identity.find_by_name("Jane  Smith", alias_list)[0] == "jane-smith"
    # unrelated name → no match
    assert identity.find_by_name("Zachary Quinto", alias_list)[0] is None


def test_resolve_email_priority_then_name():
    email_index, alias_list = identity.build_lookup(_people())
    # email wins even if name is blank
    assert identity.resolve("", "jane@acme.com", email_index, alias_list) == "jane-smith"
    # falls back to name when email misses
    assert identity.resolve("Jane Smith", "unknown@x.io", email_index, alias_list) == "jane-smith"
    # total miss
    assert identity.resolve("Nobody", "nobody@x.io", email_index, alias_list) is None


def test_load_people_defaults_empty(tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    assert identity.load_people(storage) == []
    storage.write_json("people_registry.json", {"version": 1, "people": _people()})
    assert len(identity.load_people(storage)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_identity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.identity'` (or `AttributeError`).

- [ ] **Step 3: Write minimal implementation**

Create `lib/identity.py`:

```python
"""Shared identity resolution for the people registry.

Consolidates find-by-email / find-by-name / slug / stub-id logic previously
duplicated across scripts/build_people_registry.py, scripts/resolve_observations.py,
processors/memory_observer.py, processors/avoma_phase1.py and scripts/avoma_per_call.py.

The registry (`data/people_registry.json`) is git-anchored on origin/main and must
be read/written via lib.storage.registry_storage(config) (LocalStorage on the working
tree), NEVER via build_storage (R2).
"""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz

FUZZY_THRESHOLD = 85
REGISTRY_KEY = "people_registry.json"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def unique_id(base: str, existing_ids) -> str:
    existing = set(existing_ids)
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def is_internal(email: str, internal_domains) -> bool:
    e = (email or "").strip().lower()
    if "@" not in e:
        return False
    return any(e.endswith(f"@{d.lower()}") for d in internal_domains)


def name_from_email(email: str) -> str:
    local = (email or "").split("@", 1)[0]
    parts = [p for p in re.split(r"[._-]+", local) if p]
    if not parts:
        return email or ""
    return " ".join(p.capitalize() for p in parts)


def load_people(storage) -> list:
    data = storage.read_json(REGISTRY_KEY, default={"version": 1, "people": []})
    return data.get("people", [])


def build_lookup(people) -> tuple:
    """Return (email_index, alias_list).

    email_index: {email_lower: person_id} from each person's `email` + '@' aliases.
    alias_list: [(person_id, text_lower)] from non-email aliases + canonical_name.
    First writer wins on collisions (setdefault).
    """
    email_index: dict = {}
    alias_list: list = []
    for p in people:
        pid = p["id"]
        primary = (p.get("email") or "").strip().lower()
        if primary:
            email_index.setdefault(primary, pid)
        for alias in p.get("aliases", []):
            a = (alias or "").strip().lower()
            if not a:
                continue
            if "@" in a:
                email_index.setdefault(a, pid)
            else:
                alias_list.append((pid, a))
        cname = (p.get("canonical_name") or "").strip().lower()
        if cname:
            alias_list.append((pid, cname))
    return email_index, alias_list


def find_by_email(email, email_index) -> Optional[str]:
    if not email:
        return None
    return email_index.get(email.strip().lower())


def find_by_name(name, alias_list, threshold: int = FUZZY_THRESHOLD) -> tuple:
    """Return (person_id, score). person_id is None if best score < threshold."""
    if not name:
        return None, 0
    target = name.strip().lower()
    best_id, best_score = None, 0
    for pid, alias in alias_list:
        score = fuzz.token_sort_ratio(target, alias)
        if score > best_score:
            best_id, best_score = pid, score
    if best_score >= threshold:
        return best_id, best_score
    return None, best_score


def resolve(name, email, email_index, alias_list, threshold: int = FUZZY_THRESHOLD) -> Optional[str]:
    """Find-only resolution (never creates). Email exact match wins, then fuzzy name."""
    hit = find_by_email(email, email_index)
    if hit:
        return hit
    pid, _ = find_by_name(name, alias_list, threshold)
    return pid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_identity.py -v`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit**

```bash
git add lib/identity.py tests/test_identity.py
git commit -m "feat(identity): shared people-registry resolver module"
```

---

## Task 2: Retain attendee display names on `CalendarEvent`

**Files:**
- Modify: `collectors/calendar.py:10-18` (dataclass) and `collectors/calendar.py:63-75` (parse loop)
- Test: `tests/test_calendar.py`

**Interfaces:**
- Produces: `CalendarEvent.attendee_details: list[dict]`, each `{"email": str, "name": str}`, excluding the calendar owner (`self`). `attendees: list[str]` (emails) is unchanged for backward compatibility.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_calendar.py` (mirror the existing `_build_service` patch pattern already used in that file):

```python
from unittest.mock import patch, MagicMock
from datetime import date
from collectors.calendar import fetch_today_events

_EVENTS_WITH_NAMES = {
    "items": [
        {
            "id": "evt1",
            "summary": "Acme demo",
            "start": {"dateTime": "2026-07-29T09:00:00-05:00"},
            "end": {"dateTime": "2026-07-29T09:30:00-05:00"},
            "attendees": [
                {"email": "trent@teambuildr.com", "self": True},
                {"email": "jane@acme.com", "displayName": "Jane Smith"},
                {"email": "no-name@acme.com"},
            ],
        }
    ]
}


def test_attendee_details_capture_names_and_exclude_self():
    with patch("collectors.calendar._build_service") as mock:
        service = MagicMock()
        mock.return_value = service
        service.events.return_value.list.return_value.execute.return_value = _EVENTS_WITH_NAMES
        events = fetch_today_events(target_date=date(2026, 7, 29), user_email="trent@teambuildr.com")
    assert len(events) == 1
    ev = events[0]
    # emails list unchanged (owner excluded)
    assert ev.attendees == ["jane@acme.com", "no-name@acme.com"]
    # details carry names; missing displayName -> ""
    assert ev.attendee_details == [
        {"email": "jane@acme.com", "name": "Jane Smith"},
        {"email": "no-name@acme.com", "name": ""},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_calendar.py::test_attendee_details_capture_names_and_exclude_self -v`
Expected: FAIL with `AttributeError: 'CalendarEvent' object has no attribute 'attendee_details'`.

- [ ] **Step 3: Write minimal implementation**

Edit the dataclass in `collectors/calendar.py` (add one field after `attendees`):

```python
@dataclass
class CalendarEvent:
    id: str
    summary: str
    start: datetime
    end: datetime
    description: str = ""
    attendees: list[str] = field(default_factory=list)
    attendee_details: list[dict] = field(default_factory=list)
    declined: bool = False
```

Edit the `CalendarEvent(...)` construction inside `fetch_today_events` (add the `attendee_details` kwarg alongside the existing `attendees` kwarg):

```python
            events.append(
                CalendarEvent(
                    id=item["id"],
                    summary=item.get("summary", "(no title)"),
                    start=parse_dt(start_raw["dateTime"]),
                    end=parse_dt(item["end"]["dateTime"]),
                    description=item.get("description", ""),
                    attendees=[
                        a["email"] for a in raw_attendees if not a.get("self")
                    ],
                    attendee_details=[
                        {"email": a["email"], "name": a.get("displayName", "")}
                        for a in raw_attendees if not a.get("self")
                    ],
                    declined=owner_declined,
                )
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_calendar.py -v`
Expected: PASS (new test + all existing calendar tests still green — the added field is optional and defaults to `[]`).

- [ ] **Step 5: Commit**

```bash
git add collectors/calendar.py tests/test_calendar.py
git commit -m "feat(calendar): retain attendee display names in attendee_details"
```

---

## Task 3: Attendee provisioner (`processors/attendee_provisioner.py`)

**Files:**
- Create: `processors/attendee_provisioner.py`
- Test: `tests/test_attendee_provisioner.py`

**Interfaces:**
- Consumes: `lib.identity` (`build_lookup`, `find_by_email`, `is_internal`, `name_from_email`, `slugify`, `unique_id`, `load_people`, `REGISTRY_KEY`), `CalendarEvent` (fields `attendees`, `attendee_details`, `summary`), a `storage` with `read_json`/`write_json`.
- Produces:
  - `classify_attendees(attendees: list[str], internal_domains: list[str]) -> tuple[list[str], list[str]]` → `(internal_emails, external_emails)`
  - `stubs_for_events(events, people: list[dict], internal_domains: list[str], today: str, max_attendees: int = 6) -> tuple[list[dict], list[dict]]` → `(new_stubs, updated_people)` — PURE, no I/O.
  - `provision_from_events(events, storage, config: dict, today: str) -> list[dict]` → returns `new_stubs`, and writes the merged registry back via `storage.write_json`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_attendee_provisioner.py`:

```python
from collectors.calendar import CalendarEvent
from processors import attendee_provisioner as ap


def _event(eid, summary, details):
    return CalendarEvent(
        id=eid, summary=summary, start=None, end=None,
        attendees=[d["email"] for d in details],
        attendee_details=details,
    )


def test_classify_attendees_splits_by_domain():
    internal, external = ap.classify_attendees(
        ["q@teambuildr.com", "jane@acme.com", "bob@acme.com"], ["teambuildr.com"]
    )
    assert internal == ["q@teambuildr.com"]
    assert external == ["jane@acme.com", "bob@acme.com"]


def test_stubs_created_for_unresolved_external_only():
    people = [{
        "id": "jane-smith", "canonical_name": "Jane Smith",
        "aliases": ["Jane Smith", "jane@acme.com"], "email": "jane@acme.com",
        "type": "lead", "pipeline_record": None, "people_file": None,
        "created": "2026-01-01", "last_seen": "2026-01-01",
    }]
    ev = _event("e1", "Acme demo", [
        {"email": "q@teambuildr.com", "name": "Quinn"},      # internal -> skip
        {"email": "jane@acme.com", "name": "Jane Smith"},    # already known -> skip
        {"email": "mike_jones@acme.com", "name": ""},        # NEW external -> stub
    ])
    new_stubs, updated = ap.stubs_for_events([ev], people, ["teambuildr.com"], "2026-07-29")
    assert len(new_stubs) == 1
    stub = new_stubs[0]
    assert stub["email"] == "mike_jones@acme.com"
    assert stub["canonical_name"] == "Mike Jones"       # derived from email (no displayName)
    assert stub["aliases"] == ["mike_jones@acme.com"]
    assert stub["type"] == "unknown"
    assert stub["created"] == "2026-07-29" and stub["last_seen"] == "2026-07-29"
    assert stub["provenance"] == "auto:calendar 2026-07-29 meeting:Acme demo"
    assert len(updated) == 2  # original + new stub


def test_stub_uses_display_name_when_present():
    ev = _event("e1", "Acme demo", [{"email": "x@acme.com", "name": "Xavier Onassis"}])
    new_stubs, _ = ap.stubs_for_events([ev], [], ["teambuildr.com"], "2026-07-29")
    assert new_stubs[0]["canonical_name"] == "Xavier Onassis"
    assert new_stubs[0]["id"] == "xavier-onassis"


def test_large_meetings_skipped():
    details = [{"email": f"p{i}@acme.com", "name": ""} for i in range(6)]  # 6 attendees
    ev = _event("e1", "Big webinar", details)
    new_stubs, _ = ap.stubs_for_events([ev], [], ["teambuildr.com"], "2026-07-29")
    assert new_stubs == []


def test_dedup_within_run_across_events():
    d = [{"email": "same@acme.com", "name": "Same Person"}]
    evs = [_event("e1", "Call A", d), _event("e2", "Call B", d)]
    new_stubs, _ = ap.stubs_for_events(evs, [], ["teambuildr.com"], "2026-07-29")
    assert len(new_stubs) == 1  # only one stub despite two events


def test_provision_from_events_writes_registry(tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    ev = _event("e1", "Acme demo", [{"email": "jane@acme.com", "name": "Jane Smith"}])
    config = {"demo_scan": {"internal_domains": ["teambuildr.com"]}}
    new_stubs = ap.provision_from_events([ev], storage, config, "2026-07-29")
    assert len(new_stubs) == 1
    saved = storage.read_json("people_registry.json")
    assert saved["version"] == 1
    assert any(p["email"] == "jane@acme.com" for p in saved["people"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_attendee_provisioner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'processors.attendee_provisioner'`.

- [ ] **Step 3: Write minimal implementation**

Create `processors/attendee_provisioner.py`:

```python
"""Auto-provision registry stubs for external attendees of today's small meetings.

For each external attendee on today's calendar who does not already resolve to a
registry person, create a lightweight stub so a home exists before the post-call
transcript is processed. Guards: skip internal attendees; skip events with >= 6
attendees. Writes the git-anchored registry via storage.write_json.
"""
from __future__ import annotations

from typing import Optional

from lib import identity

DEFAULT_INTERNAL_DOMAINS = ["teambuildr.com"]
MAX_ATTENDEES = 6  # events with this many or more are skipped


def classify_attendees(attendees, internal_domains) -> tuple:
    """Return (internal_emails, external_emails)."""
    internal, external = [], []
    for email in attendees:
        if identity.is_internal(email, internal_domains):
            internal.append(email)
        else:
            external.append(email)
    return internal, external


def _display_name(email: str, detail_by_email: dict) -> str:
    name = (detail_by_email.get(email) or "").strip()
    return name if name else identity.name_from_email(email)


def stubs_for_events(events, people, internal_domains, today: str, max_attendees: int = MAX_ATTENDEES) -> tuple:
    """Pure: return (new_stubs, updated_people). Does not touch storage."""
    people = list(people)
    email_index, _ = identity.build_lookup(people)
    existing_ids = {p["id"] for p in people}
    new_stubs: list = []
    created_emails: set = set()

    for ev in events:
        attendees = getattr(ev, "attendees", []) or []
        if len(attendees) >= max_attendees:
            continue
        detail_by_email = {
            d["email"]: d.get("name", "") for d in getattr(ev, "attendee_details", []) or []
        }
        _, external = classify_attendees(attendees, internal_domains)
        for email in external:
            key = email.strip().lower()
            if identity.find_by_email(email, email_index) is not None:
                continue
            if key in created_emails:
                continue
            name = _display_name(email, detail_by_email)
            pid = identity.unique_id(identity.slugify(name) or key, existing_ids)
            stub = {
                "id": pid,
                "canonical_name": name,
                "aliases": [email],
                "email": email,
                "type": "unknown",
                "pipeline_record": None,
                "people_file": None,
                "created": today,
                "last_seen": today,
                "provenance": f"auto:calendar {today} meeting:{ev.summary}",
            }
            new_stubs.append(stub)
            people.append(stub)
            existing_ids.add(pid)
            email_index[key] = pid
            created_emails.add(key)

    return new_stubs, people


def provision_from_events(events, storage, config: dict, today: str) -> list:
    """Load registry, create stubs for unresolved external attendees, write back.

    Returns the list of newly created stub records (may be empty).
    """
    internal_domains = config.get("demo_scan", {}).get("internal_domains", DEFAULT_INTERNAL_DOMAINS)
    data = storage.read_json(identity.REGISTRY_KEY, default={"version": 1, "people": []})
    people = data.get("people", [])
    new_stubs, updated = stubs_for_events(events, people, internal_domains, today)
    if new_stubs:
        data["people"] = updated
        data.setdefault("version", 1)
        storage.write_json(identity.REGISTRY_KEY, data)
    return new_stubs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_attendee_provisioner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add processors/attendee_provisioner.py tests/test_attendee_provisioner.py
git commit -m "feat(provisioner): auto-provision registry stubs for external attendees"
```

---

## Task 4: Standalone CLI entrypoint (`scripts/provision_today_attendees.py`)

**Files:**
- Create: `scripts/provision_today_attendees.py`
- Test: manual run (verification below) — the underlying logic is already covered by Tasks 1–3.

**Interfaces:**
- Consumes: `main.load_config` (config loader), `collectors.calendar.fetch_two_day_events`, `lib.storage.registry_storage`, `processors.attendee_provisioner.provision_from_events`.
- Produces: a `python scripts/provision_today_attendees.py [--dry-run]` command that prints created stubs.

- [ ] **Step 1: Write the implementation**

Create `scripts/provision_today_attendees.py`:

```python
"""Provision registry stubs for today's external meeting attendees.

Standalone runner for Plan 1. Reads today's calendar, creates stub people records
for unresolved external attendees of small (<6-attendee) meetings, and writes them
to the git-anchored people registry via registry_storage(config).

Usage:
    python scripts/provision_today_attendees.py            # write stubs
    python scripts/provision_today_attendees.py --dry-run  # print only, no write
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import load_config  # noqa: E402
from collectors.calendar import fetch_two_day_events  # noqa: E402
from lib.storage import registry_storage  # noqa: E402
from processors import attendee_provisioner as ap  # noqa: E402


def run(dry_run: bool = False) -> list:
    config = load_config()
    user_email = config.get("email", "")
    calendar_ids = config.get("calendar_ids", ["primary"])
    today_events, _tomorrow, failed = fetch_two_day_events(calendar_ids, user_email)
    if failed:
        print("WARNING: calendar fetch failed; provisioning against partial data", flush=True)
    today = date.today().isoformat()

    if dry_run:
        internal_domains = config.get("demo_scan", {}).get("internal_domains", ap.DEFAULT_INTERNAL_DOMAINS)
        storage = registry_storage(config)
        data = storage.read_json(ap.identity.REGISTRY_KEY, default={"version": 1, "people": []})
        stubs, _ = ap.stubs_for_events(today_events, data.get("people", []), internal_domains, today)
    else:
        storage = registry_storage(config)
        stubs = ap.provision_from_events(today_events, storage, config, today)

    if not stubs:
        print("No new attendee stubs to create.")
    else:
        verb = "Would create" if dry_run else "Created"
        print(f"{verb} {len(stubs)} stub(s):")
        for s in stubs:
            print(f"  - {s['canonical_name']} <{s['email']}>  [{s['provenance']}]")
    return stubs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports and runs in dry-run mode**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python scripts/provision_today_attendees.py --dry-run`
Expected: either "No new attendee stubs to create." or a list of `Would create N stub(s):` lines. No traceback. (Requires valid Google credentials in the environment; if calendar auth is unavailable locally, the WARNING line prints and the run still completes without creating stubs.)

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_identity.py tests/test_calendar.py tests/test_attendee_provisioner.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/provision_today_attendees.py
git commit -m "feat(provisioner): standalone CLI to provision today's attendee stubs"
```

---

## Self-Review

**Spec coverage (against `2026-07-29-daily-brief-redesign-design.md` → "Identity Resolution" + "Attendee Auto-Provisioning"):**
- Identity resolution as a named shared component → Task 1 (`lib/identity.py`). ✅
- Match calendar attendee → registry person across name/email variants → `resolve()` (email exact + fuzzy name). ✅
- Dedup before provisioning (no duplicates) → `find_by_email` guard + in-run `created_emails` set (Task 3). ✅
- Stub contents: name, email, company/domain, provenance → stub dict (Task 3). **Note:** "company/domain" and "title if in invite" are NOT populated — the calendar API exposes neither a structured company nor a per-attendee title, and `description` is an unstructured body. Deferred: domain is implicit in the email; company/title enrichment belongs to Plan 3 (external prep) where pipeline/people-file data is joined. Flagged as an intentional scope trim, not a gap.
- Direct stub creation (no pending gate) → `provision_from_events` writes immediately. ✅
- Skip internal teammates → `classify_attendees` + `is_internal`. ✅
- Skip meetings with ≥6 attendees → `max_attendees` guard. ✅
- Provenance tags for prunability → `provenance` field. ✅
- Git-anchored registry via `registry_storage` (not R2) → Task 4 CLI uses `registry_storage(config)`; documented in Global Constraints. ✅

**Placeholder scan:** none — all steps contain runnable code and exact commands.

**Type consistency:** `stubs_for_events` returns `(new_stubs, updated_people)` and `provision_from_events` consumes `new_stubs, updated` in that order; `build_lookup` returns `(email_index, alias_list)` consistently across Tasks 1 and 3; `REGISTRY_KEY` referenced as `identity.REGISTRY_KEY` in Tasks 3 and 4. Consistent.

**Out of scope for Plan 1 (handled later):** wiring provisioning into the brief run and adding the `brief.yml` commit-back (Plan 2); migrating the five existing duplicated resolvers onto `lib/identity.py` (opportunistic future cleanup, not required here); populating stub company/title (Plan 3).
```
