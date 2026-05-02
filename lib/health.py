"""Run health tracking for the morning brief pipeline."""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Status(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class CollectorResult:
    """Outcome of a single collector or sub-step."""
    name: str
    status: str = "ok"           # "ok", "skipped", "error"
    error: str | None = None     # short error message if failed
    item_count: int | None = None
    duration_ms: int | None = None


@dataclass
class StageResult:
    """Outcome of a pipeline stage."""
    name: str   # "collect", "process", "generate_and_deliver"
    status: str = "ok"
    duration_ms: int = 0
    collectors: list[CollectorResult] = field(default_factory=list)


@dataclass
class RunHealth:
    """Full health report for a single run."""
    run_date: str = ""
    run_timestamp: str = ""
    overall_status: str = "ok"   # "ok", "degraded", "failed"
    stages: list[StageResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_duration_ms: int = 0

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def compute_overall_status(self) -> None:
        """Set overall_status based on collector/stage results."""
        has_error = False
        has_failed_stage = False
        for stage in self.stages:
            if stage.status == "failed":
                has_failed_stage = True
            for c in stage.collectors:
                if c.status == "error":
                    has_error = True
        if has_failed_stage:
            self.overall_status = "failed"
        elif has_error:
            self.overall_status = "degraded"
        else:
            self.overall_status = "ok"

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


class _Timer:
    def __init__(self):
        self.start = 0.0
        self.elapsed_ms = 0

    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = int((time.monotonic() - self.start) * 1000)


def timed() -> _Timer:
    """Context manager that records elapsed milliseconds. Read t.elapsed_ms after the with block."""
    return _Timer()
