"""Plain data carried between providers and the TUI. No provider-specific fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# Airflow states we render. Anything else falls through to "unknown".
SUCCESS = "success"
FAILED = "failed"
RUNNING = "running"
QUEUED = "queued"


@dataclass(frozen=True)
class ConnectionInfo:
    """What the connection bar shows: where we are and how we got there."""

    kind: str                 # "k8s" | "mwaa" | "fake"
    hops: list[str]           # e.g. ["my-cluster", "airflow-ns", ":54312"]
    airflow_version: str
    latency_ms: int | None = None
    readonly: bool = False

    def as_path(self) -> str:
        return f"{self.kind} ▸ " + " ▸ ".join(self.hops)


@dataclass(frozen=True)
class DagRun:
    dag_id: str
    run_id: str
    state: str
    logical_date: datetime | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    run_type: str = ""

    @property
    def duration_s(self) -> float | None:
        if self.start_date is None:
            return None
        end = self.end_date or (datetime.now(timezone.utc) if self.state == RUNNING else None)
        if end is None:
            return None
        return (end - self.start_date).total_seconds()


@dataclass(frozen=True)
class DagSummary:
    dag_id: str
    schedule: str = ""
    is_paused: bool = False
    recent: list[DagRun] = field(default_factory=list)   # newest first
    error: str | None = None      # per-DAG fetch failure; row still renders

    @property
    def last_state(self) -> str | None:
        return self.recent[0].state if self.recent else None

    @property
    def avg_duration_s(self) -> float | None:
        """Mean over successful runs only - failures skew the number and mean nothing."""
        xs = [r.duration_s for r in self.recent if r.state == SUCCESS and r.duration_s]
        return sum(xs) / len(xs) if xs else None


@dataclass(frozen=True)
class TaskInstance:
    task_id: str
    state: str | None
    try_number: int = 1
    start_date: datetime | None = None
    end_date: datetime | None = None
    duration_s: float | None = None
    operator: str = ""


@dataclass(frozen=True)
class LogChunk:
    """`text` empty with `source == "empty"` is the §5.2 case: worker died before writing."""

    text: str
    source: str = "airflow"      # "airflow" | "pvc" | "empty"
    note: str | None = None
