"""Drives the real app headless. Catches the compose/binding breakage that unit
tests on pure functions never see."""

import json

import pytest

from textual.widgets import DataTable

from atc.core.providers.fake import FakeProvider
from atc.tui.app import AtcApp, DagsScreen, PickList, ProfilePane, RunsScreen

pytestmark = pytest.mark.asyncio


@pytest.fixture
def cfgdir(tmp_path, monkeypatch):
    monkeypatch.setenv("ATC_CONFIG_DIR", str(tmp_path))
    return tmp_path


async def test_empty_watchlist_tells_you_what_to_press(cfgdir):
    app = AtcApp(FakeProvider(), "fake")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DagsScreen)
        assert "press [a]" in screen.pane.status_text
        # regression: Static parses "[a]" as Rich markup and swallows it unless
        # markup=False - the text must actually reach the screen, not just the
        # Python string in status_text
        status_widget = screen.pane.query_one(".status")
        assert "[a]" in status_widget.render().plain


async def test_dynamic_text_with_brackets_is_not_eaten_by_markup(cfgdir):
    """Error strings routinely contain brackets (`[Errno 61] ...`); Static must
    show them literally rather than parsing them as style tags."""
    from atc.tui.render import connection_line

    app = AtcApp(FakeProvider(), "fake")
    async with app.run_test() as pilot:
        await pilot.pause()
        pane = app.screen.pane
        pane._set_status("✗ [Errno 61] Connection refused - retry [x] or [esc]")
        await pilot.pause()
        rendered = pane.query_one(".status").render().plain
        assert "[Errno 61] Connection refused" in rendered
        assert "[x]" in rendered and "[esc]" in rendered


async def test_watchlist_renders_only_favourites(cfgdir):
    (cfgdir / "favorites.json").write_text(json.dumps(
        {"fake": ["ingest_orders_to_warehouse", "vendor_feed_import"]}))
    app = AtcApp(FakeProvider(), "fake")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        table = app.screen.pane.query_one(DataTable)
        assert table.row_count == 2          # not the 8 DAGs the environment has
        status = app.screen.pane.status_text
        assert "failing: vendor_feed_import" in status


async def test_add_screen_lists_everything_and_starring_persists(cfgdir):
    app = AtcApp(FakeProvider(), "fake")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, PickList)
        assert len(app.screen.items) == 8

        app.screen.dismiss("refresh_finance_marts")
        await pilot.pause()
        await pilot.pause()

    assert json.loads((cfgdir / "favorites.json").read_text()) == {
        "fake": ["refresh_finance_marts"]}


async def test_drill_in_shows_runs_and_tasks(cfgdir):
    (cfgdir / "favorites.json").write_text(json.dumps({"fake": ["vendor_feed_import"]}))
    app = AtcApp(FakeProvider(), "fake")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        app.screen.action_drill()
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, RunsScreen)
        assert app.screen.profile_name == "fake"
        assert app.screen.query_one("#runs").row_count == 20
        assert app.screen.query_one("#tasks").row_count == 5


async def test_readonly_profile_refuses_to_trigger(cfgdir):
    (cfgdir / "favorites.json").write_text(json.dumps({"prd": ["export_daily_metrics"]}))
    provider = FakeProvider()
    provider.readonly = True
    base = provider.describe

    def readonly_describe():
        info = base()
        return type(info)(kind=info.kind, hops=info.hops,
                          airflow_version=info.airflow_version,
                          latency_ms=info.latency_ms, readonly=True)

    provider.describe = readonly_describe
    app = AtcApp(provider, "prd")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert "readonly" in app.screen.pane.status_text
