"""In-memory provider. Powers the test suite, CI, and the demo GIF.

Deliberately uses invented DAG and environment names: this is the only provider that
appears in screenshots, so nothing real ever leaks into the README.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from ..models import ConnectionInfo, DagRun, DagSummary, LogChunk, TaskInstance

_DAGS = {
    "ingest_orders_to_warehouse": "@hourly",
    "sync_customers_to_crm": "0 2 * * *",
    "refresh_finance_marts": "@daily",
    "export_daily_metrics": "@daily",
    "reconcile_payments": "*/30 * * * *",
    "archive_cold_storage": "@weekly",
    "rebuild_search_index": "@daily",
    "vendor_feed_import": "@hourly",
}
_TASKS = ["extract", "validate", "transform", "load", "notify"]


class FakeProvider:
    def __init__(self, seed: int = 7, fail_dag: str = "vendor_feed_import",
                 readonly: bool = False):
        self.readonly = readonly
        self._rng = random.Random(seed)
        self._fail_dag = fail_dag
        self._triggered: list[DagRun] = []

    def describe(self) -> ConnectionInfo:
        return ConnectionInfo(kind="fake", hops=["demo-cluster", "airflow-demo", ":0"],
                              airflow_version="3.1.0", latency_ms=12,
                              readonly=self.readonly)

    def list_all_dag_ids(self) -> list[str]:
        return sorted(_DAGS)

    def dag_summaries(self, dag_ids: list[str]) -> list[DagSummary]:
        return [
            DagSummary(dag_id=d, schedule=_DAGS.get(d, "@daily"),
                       recent=self.dag_runs(d))
            for d in dag_ids
        ]

    def dag_runs(self, dag_id: str, limit: int = 20) -> list[DagRun]:
        rng = random.Random(f"{dag_id}")
        now = datetime.now(timezone.utc)
        runs = []
        for i in range(limit):
            start = now - timedelta(hours=i + 1)
            failed = dag_id == self._fail_dag and i in (0, 7)
            dur = rng.uniform(60, 900)
            runs.append(DagRun(
                dag_id=dag_id,
                run_id=f"scheduled__{start:%Y-%m-%dT%H:%M:%S}+00:00",
                state="failed" if failed else "success",
                logical_date=start, start_date=start,
                end_date=start + timedelta(seconds=dur),
                run_type="scheduled",
            ))
        return self._triggered_for(dag_id) + runs

    def _triggered_for(self, dag_id: str) -> list[DagRun]:
        return [r for r in self._triggered if r.dag_id == dag_id]

    def task_instances(self, dag_id: str, run_id: str) -> list[TaskInstance]:
        rng = random.Random(run_id)
        failing = dag_id == self._fail_dag and "failed" in self._state_of(dag_id, run_id)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        out = []
        for i, t in enumerate(_TASKS):
            dur = rng.uniform(5, 200)
            if failing and i == 2:
                state = "failed"
            elif failing and i > 2:
                state = "upstream_failed"
            else:
                state = "success"
            out.append(TaskInstance(
                task_id=t, state=state, try_number=2 if state == "failed" else 1,
                start_date=start + timedelta(seconds=i * 60),
                end_date=start + timedelta(seconds=i * 60 + dur),
                duration_s=dur, operator="PythonOperator"))
        return out

    def _state_of(self, dag_id: str, run_id: str) -> str:
        for r in self.dag_runs(dag_id):
            if r.run_id == run_id:
                return r.state
        return "success"

    def task_log(self, dag_id, run_id, task_id, try_number=1) -> LogChunk:
        # `transform` returns nothing on purpose: it is how the §5.2 empty-log hint
        # gets exercised without needing a real SIGKILLed worker.
        if task_id == "transform" and dag_id == self._fail_dag:
            return LogChunk(text="", source="empty")
        lines = [
            f"[2026-09-22 01:0{i}:00] {{taskinstance.py}} INFO - {task_id}: step {i} ok"
            for i in range(1, 12)
        ]
        return LogChunk(text="\n".join(lines), source="airflow")

    def trigger(self, dag_id: str, conf: dict | None = None) -> DagRun:
        now = datetime.now(timezone.utc)
        run = DagRun(dag_id=dag_id, run_id=f"manual__{now:%Y-%m-%dT%H:%M:%S}+00:00",
                     state="queued", logical_date=now, start_date=now, run_type="manual")
        self._triggered.insert(0, run)
        return run

    def close(self) -> None:
        pass
