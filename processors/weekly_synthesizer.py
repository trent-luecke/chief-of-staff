import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from processors.state import load_snapshot


@dataclass
class WeeklySynthesis:
    executive_summary: str
    patterns: list[str] = field(default_factory=list)
    resolved_this_week: list[str] = field(default_factory=list)
    carry_forwards: list[str] = field(default_factory=list)
    meta_observation: str = ""


def _load_week_observations(obs_file: str, run_date: date) -> list[dict]:
    cutoff = run_date - timedelta(days=7)
    observations = []
    try:
        with open(obs_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    obs_date = date.fromisoformat(obs.get("date", "2000-01-01"))
                    if cutoff <= obs_date <= run_date:  # upper bound excludes future-dated observations
                        observations.append(obs)
                except (json.JSONDecodeError, ValueError):
                    continue
    except FileNotFoundError:
        pass
    return observations


def _load_week_state_delta(state_dir: str, run_date: date) -> tuple[int, int]:
    """Returns (resolved_count, still_open_count) comparing start-of-week to end-of-week snapshots."""
    start_date = run_date - timedelta(days=7)
    start_snap = load_snapshot(start_date, state_dir)
    end_snap = load_snapshot(run_date, state_dir)
    if not start_snap or not end_snap:
        return 0, 0
    start_ids = set(start_snap.open_email_thread_ids)
    end_ids = set(end_snap.open_email_thread_ids)
    resolved_count = len(start_ids - end_ids)
    still_open_count = len(start_ids & end_ids)
    return resolved_count, still_open_count
