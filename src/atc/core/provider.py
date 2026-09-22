"""The one contract the TUI knows about. The TUI never imports boto3 or shells out."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Protocol

from .errors import ProviderError, ReadOnly
from .models import ConnectionInfo, DagRun, DagSummary, LogChunk, TaskInstance


class AirflowProvider(Protocol):
    def describe(self) -> ConnectionInfo: ...
    def list_all_dag_ids(self) -> list[str]: ...
    def dag_summaries(self, dag_ids: list[str]) -> list[DagSummary]: ...
    def dag_runs(self, dag_id: str, limit: int = 20) -> list[DagRun]: ...
    def task_instances(self, dag_id: str, run_id: str) -> list[TaskInstance]: ...
    def task_log(self, dag_id: str, run_id: str, task_id: str, try_number: int) -> LogChunk: ...
    def trigger(self, dag_id: str, conf: dict | None = None) -> DagRun: ...
    def close(self) -> None: ...


def _dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class RestApiProvider:
    """Everything above the transport. Subclasses implement `_request` only.

    K8s and MWAA speak the same Airflow 3 REST API (`/api/v2`); they differ purely in
    how a request gets to the webserver. Keeping that seam here is what stops the two
    providers from drifting apart.
    """

    readonly: bool = False
    _MAX_WORKERS = 8

    # --- transport seam -------------------------------------------------
    def _request(self, method: str, path: str, *, params: dict | None = None,
                 json: dict | None = None) -> Any:
        raise NotImplementedError

    # --- DAGs -----------------------------------------------------------
    def list_all_dag_ids(self) -> list[str]:
        """Full paginated sweep. Only the 'add favorite' screen calls this."""
        ids: list[str] = []
        offset = 0
        while True:
            page = self._request("GET", "/api/v2/dags",
                                 params={"limit": 100, "offset": offset})
            dags = page.get("dags", [])
            ids.extend(d["dag_id"] for d in dags)
            offset += len(dags)
            if not dags or offset >= page.get("total_entries", 0):
                break
        return sorted(ids)

    def dag_summaries(self, dag_ids: list[str]) -> list[DagSummary]:
        """Favourites only, fetched concurrently. Cost is O(favourites), not O(env)."""
        if not dag_ids:
            return []
        workers = min(self._MAX_WORKERS, len(dag_ids))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self._one_summary, dag_ids))

    def _one_summary(self, dag_id: str) -> DagSummary:
        # One slow or deleted DAG must not blank the whole screen.
        try:
            meta = self._request("GET", f"/api/v2/dags/{dag_id}")
        except Exception as e:
            return DagSummary(dag_id=dag_id, error=str(e))
        try:
            runs = self.dag_runs(dag_id, limit=20)
        except Exception as e:
            return DagSummary(dag_id=dag_id, error=str(e))
        return DagSummary(
            dag_id=dag_id,
            schedule=meta.get("timetable_summary") or meta.get("schedule_interval") or "",
            is_paused=bool(meta.get("is_paused")),
            recent=runs,
        )

    def dag_runs(self, dag_id: str, limit: int = 20) -> list[DagRun]:
        data = self._request("GET", f"/api/v2/dags/{dag_id}/dagRuns",
                             params={"limit": limit, "order_by": "-start_date"})
        return [
            DagRun(
                dag_id=dag_id,
                run_id=r["dag_run_id"],
                state=r.get("state") or "unknown",
                logical_date=_dt(r.get("logical_date")),
                start_date=_dt(r.get("start_date")),
                end_date=_dt(r.get("end_date")),
                run_type=r.get("run_type", ""),
            )
            for r in data.get("dag_runs", [])
        ]

    def task_instances(self, dag_id: str, run_id: str) -> list[TaskInstance]:
        data = self._request(
            "GET", f"/api/v2/dags/{dag_id}/dagRuns/{run_id}/taskInstances")
        tis = [
            TaskInstance(
                task_id=t["task_id"],
                state=t.get("state"),
                try_number=t.get("try_number") or 1,
                start_date=_dt(t.get("start_date")),
                end_date=_dt(t.get("end_date")),
                duration_s=t.get("duration"),
                operator=t.get("operator") or "",
            )
            for t in data.get("task_instances", [])
        ]
        return sorted(tis, key=lambda t: (t.start_date is None, t.start_date, t.task_id))

    def task_log(self, dag_id: str, run_id: str, task_id: str,
                 try_number: int = 1) -> LogChunk:
        data = self._request(
            "GET",
            f"/api/v2/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}"
            f"/logs/{try_number}",
            params={"full_content": "true"},
        )
        body, notice = _split_log_noise(_flatten_log(data))
        if body.strip():
            return LogChunk(text=body, source="airflow")
        # Airflow 3 answers with a ::group:: metadata block even when it has no log
        # to serve, so "non-empty response" is not the same as "there is a log".
        return LogChunk(text="", source="empty", note=notice or None)

    # --- the one write --------------------------------------------------
    def trigger(self, dag_id: str, conf: dict | None = None) -> DagRun:
        if self.readonly:
            raise ReadOnly("this profile is readonly - trigger is blocked")
        data = self._request("POST", f"/api/v2/dags/{dag_id}/dagRuns",
                             json={"logical_date": None, "conf": conf or {}})
        if not isinstance(data, dict) or "dag_run_id" not in data:
            raise ProviderError(f"unexpected trigger response: {data!r}")
        return DagRun(
            dag_id=dag_id,
            run_id=data["dag_run_id"],
            state=data.get("state") or QUEUED_FALLBACK,
            logical_date=_dt(data.get("logical_date")),
            start_date=_dt(data.get("start_date")),
            run_type=data.get("run_type", "manual"),
        )

    def close(self) -> None:
        pass


QUEUED_FALLBACK = "queued"


def _split_log_noise(text: str) -> tuple[str, str]:
    """Separate real log lines from Airflow's `::group::…::endgroup::` metadata.

    A failed served-log fetch comes back *inside* such a block, which makes the
    response non-empty while containing no log at all.
    """
    body, notice, in_group = [], [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("::group::"):
            in_group = True
            continue
        if stripped.startswith("::endgroup::"):
            in_group = False
            continue
        (notice if in_group else body).append(line)
    return "\n".join(body), " ".join(n.strip() for n in notice if n.strip())


def _flatten_log(data: Any) -> str:
    """Airflow 3 returns structured log JSON; older shapes return a plain string."""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        content = data.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            out = []
            for item in content:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    out.append(item.get("event") or item.get("message") or str(item))
            return "\n".join(out)
    return ""
