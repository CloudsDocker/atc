from datetime import datetime, timedelta, timezone

import pytest

from atc.core.errors import ReadOnly
from atc.core.models import DagRun, DagSummary
from atc.core.provider import RestApiProvider, _flatten_log
from atc.core.providers.fake import FakeProvider
from atc.tui.render import fmt_duration, run_strip, state_badge

UTC = timezone.utc


def _run(state, dur=60):
    start = datetime(2026, 9, 22, 1, 0, tzinfo=UTC)
    return DagRun("d", f"r-{state}", state, start_date=start,
                  end_date=start + timedelta(seconds=dur))


# --- models ---------------------------------------------------------------
def test_avg_duration_ignores_failures():
    s = DagSummary("d", recent=[_run("failed", 9999), _run("success", 100),
                                _run("success", 200)])
    assert s.avg_duration_s == 150
    assert s.last_state == "failed"


def test_avg_duration_none_when_no_successes():
    assert DagSummary("d", recent=[_run("failed")]).avg_duration_s is None


def test_running_duration_is_measured_against_now():
    start = datetime.now(UTC) - timedelta(seconds=30)
    assert 25 < DagRun("d", "r", "running", start_date=start).duration_s < 60


# --- rendering ------------------------------------------------------------
def test_run_strip_pads_and_orders_newest_last():
    strip = run_strip([_run("failed"), _run("success")], width=5)
    assert strip.cell_len == 5
    assert strip.plain == "···▇▚"        # padded, oldest→newest left→right


def test_states_differ_by_glyph_not_only_colour():
    glyphs = {state_badge(s).plain for s in
              ("success", "failed", "running", "queued", None)}
    assert len(glyphs) == 5


@pytest.mark.parametrize("secs,want", [
    (None, "--"), (45, "45s"), (252, "4m12s"), (7380, "2h03m")])
def test_fmt_duration(secs, want):
    assert fmt_duration(secs) == want


# --- log shapes -----------------------------------------------------------
def test_flatten_log_handles_airflow3_structured_and_plain():
    assert _flatten_log({"content": [{"event": "a"}, {"event": "b"}]}) == "a\nb"
    assert _flatten_log({"content": "plain"}) == "plain"
    assert _flatten_log("raw") == "raw"
    assert _flatten_log({"nope": 1}) == ""


# --- favourites path: cost is O(favourites), not O(environment) -----------
class _Counting(RestApiProvider):
    def __init__(self):
        self.paths = []

    def _request(self, method, path, *, params=None, json=None):
        self.paths.append(path)
        if path.endswith("/dagRuns"):
            return {"dag_runs": [{"dag_run_id": "r1", "state": "success",
                                  "start_date": "2026-09-22T01:00:00Z",
                                  "end_date": "2026-09-22T01:05:00Z"}]}
        if path == "/api/v2/dags":
            return {"dags": [{"dag_id": f"d{i}"} for i in range(300)],
                    "total_entries": 300}
        return {"timetable_summary": "@hourly", "is_paused": False}


def test_dag_summaries_only_touches_the_favourites():
    p = _Counting()
    out = p.dag_summaries(["alpha", "beta"])
    assert [s.dag_id for s in out] == ["alpha", "beta"]
    assert not any(path == "/api/v2/dags" for path in p.paths)
    assert len(p.paths) == 4          # 2 DAGs x (metadata + dagRuns)


def test_one_broken_dag_does_not_blank_the_row():
    class Broken(_Counting):
        def _request(self, method, path, *, params=None, json=None):
            if "boom" in path:
                raise RuntimeError("gone")
            return super()._request(method, path, params=params, json=json)

    out = Broken().dag_summaries(["ok", "boom"])
    assert out[0].error is None and out[1].error == "gone"


def test_readonly_blocks_trigger():
    p = _Counting()
    p.readonly = True
    with pytest.raises(ReadOnly):
        p.trigger("anything")


# --- fake provider --------------------------------------------------------
def test_fake_provider_is_self_contained():
    f = FakeProvider()
    ids = f.list_all_dag_ids()
    assert len(ids) == 8
    summaries = f.dag_summaries(ids[:3])
    assert all(len(s.recent) == 20 for s in summaries)
    run = f.dag_runs("vendor_feed_import")[0]
    assert run.state == "failed"
    assert f.task_log("vendor_feed_import", run.run_id, "transform").source == "empty"


def test_fake_trigger_shows_up_at_the_top():
    f = FakeProvider()
    run = f.trigger("refresh_finance_marts")
    assert f.dag_runs("refresh_finance_marts")[0].run_id == run.run_id


# --- regression: found against a live Airflow 3.3.1, not in review --------
def test_group_metadata_only_response_counts_as_no_log():
    """Airflow 3 wraps a failed served-log fetch in ::group:: markers, so the
    response is non-empty while containing no log. Taking it at face value hides
    the real evidence and skips the PVC fallback."""
    class OnlyNotice(_Counting):
        def _request(self, method, path, *, params=None, json=None):
            return {"content": [
                {"event": "::group::Log message source details"},
                {"event": "Could not read served logs: Hostname not available."},
                {"event": "::endgroup::"}]}

    chunk = OnlyNotice().task_log("d", "r", "t", 1)
    assert chunk.text == ""
    assert chunk.source == "empty"
    assert "Could not read served logs" in chunk.note


def test_real_log_lines_survive_the_group_stripping():
    class WithBoth(_Counting):
        def _request(self, method, path, *, params=None, json=None):
            return {"content": [
                {"event": "::group::Log message source details"},
                {"event": "reading from worker"},
                {"event": "::endgroup::"},
                {"event": "INFO - task started"},
                {"event": "INFO - task finished"}]}

    chunk = WithBoth().task_log("d", "r", "t", 1)
    assert chunk.source == "airflow"
    assert chunk.text == "INFO - task started\nINFO - task finished"
