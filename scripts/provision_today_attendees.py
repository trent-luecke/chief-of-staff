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
