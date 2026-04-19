import csv
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


@dataclass
class GymScoutLead:
    date_found: str
    gym_name: str
    owner_name: str
    location: str
    category: str
    match: str  # "yes" or "maybe"
    reason: str


def fetch_recent_leads(csv_path: str, lookback_days: int = 7) -> list[GymScoutLead]:
    """Return yes/maybe matches logged within the last N days."""
    path = Path(csv_path).expanduser()
    if not path.exists():
        return []

    cutoff = date.today() - timedelta(days=lookback_days)
    leads = []

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("match") not in ("yes", "maybe"):
                    continue
                try:
                    found_date = date.fromisoformat(row.get("date_found", ""))
                except ValueError:
                    continue
                if found_date < cutoff:
                    continue
                leads.append(GymScoutLead(
                    date_found=row.get("date_found", ""),
                    gym_name=row.get("gym_name", ""),
                    owner_name=row.get("owner_name", ""),
                    location=row.get("location", ""),
                    category=row.get("category", ""),
                    match=row.get("match", ""),
                    reason=row.get("reason", ""),
                ))
    except (csv.Error, IOError):
        return []

    return leads
