import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

_OBS_KEY = "memory/observations.jsonl"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PatternAnomaly:
    type: str       # "new" | "recurring" | "worsening"
    title: str
    description: str
    weeks_seen: int = 1


@dataclass
class AnomalyReport:
    anomalies: list[PatternAnomaly] = field(default_factory=list)


@dataclass
class UpcomingDemo:
    date: date
    title: str
    attendee_emails: list[str]
    lead_name: Optional[str]      # None = not in pipeline
    pipeline_stage: Optional[str]


@dataclass
class DemoScanReport:
    demos: list[UpcomingDemo] = field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _parse_kpi_context(context: str) -> dict[str, int]:
    result = {}
    for token in context.split():
        if "=" in token:
            k, _, v = token.partition("=")
            try:
                result[k] = int(v)
            except ValueError:
                pass
    return result


def _extract_patterns_section(content: str) -> list[str]:
    lines = content.splitlines()
    in_patterns = False
    bullets = []
    for line in lines:
        if line.strip() == "## Patterns":
            in_patterns = True
            continue
        if in_patterns:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                bullets.append(line[2:].strip())
    return bullets


def _week_bucket(obs_date: date, run_date: date) -> Optional[int]:
    delta = (run_date - obs_date).days
    if 0 <= delta < 7:
        return 0
    if 7 <= delta < 14:
        return 1
    if 14 <= delta < 21:
        return 2
    if 21 <= delta < 28:
        return 3
    return None
