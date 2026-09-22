"""Tabbed profile switching.

The guarantee worth protecting here is that opening the app does not connect to
every configured environment - only to the tab you are actually looking at.
"""

import json

import pytest
from textual.widgets import TabbedContent

from atc.config import Config, Profile
from atc.core.providers.fake import FakeProvider
from atc.tui.app import AtcApp, ProfilePane, _pane_id

pytestmark = pytest.mark.asyncio


def _config(*names, readonly=()):
    return Config(default=names[0], profiles={
        n: Profile(name=n, type="fake", readonly=n in readonly, options={"type": "fake"})
        for n in names
    })


@pytest.fixture
def cfgdir(tmp_path, monkeypatch):
    monkeypatch.setenv("ATC_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _app(*names, readonly=()):
    conf = _config(*names, readonly=readonly)
    return AtcApp(FakeProvider(), names[0], config=conf)


async def test_one_tab_per_profile(cfgdir):
    app = _app("dev", "staging", "sit")
    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.screen.query_one("#profiles", TabbedContent)
        panes = app.screen.query(ProfilePane)
        assert [p.profile_name for p in panes] == ["dev", "staging", "sit"]
        assert tabs.active == _pane_id("dev")


async def test_tab_key_cycles_and_wraps(cfgdir):
    app = _app("dev", "staging", "sit")
    async with app.run_test() as pilot:
        await pilot.pause()
        seen = []
        for _ in range(4):
            await pilot.press("tab")
            await pilot.pause()
            seen.append(app.profile_name)
        assert seen == ["staging", "sit", "dev", "staging"]

        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.profile_name == "dev"


async def test_digit_jumps_straight_to_a_profile(cfgdir):
    app = _app("dev", "staging", "sit")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        assert app.profile_name == "sit"
        # a digit past the end must do nothing rather than blow up
        await pilot.press("9")
        await pilot.pause()
        assert app.profile_name == "sit"


async def test_only_the_visited_profiles_ever_connect(cfgdir):
    """Textual mounts every pane at startup, so this is the guarantee that stops
    the app opening a tunnel into every environment the moment you launch it."""
    app = _app("dev", "staging", "sit")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert set(app._providers) == {"dev"}

        await pilot.press("tab")
        await pilot.pause()
        await pilot.pause()
        assert set(app._providers) == {"dev", "staging"}
        assert "sit" not in app._providers      # never visited, never connected


async def test_tabbing_back_reuses_the_same_provider(cfgdir):
    """A k8s provider owns a port-forward; rebuilding it on every tab switch is
    exactly the ~2s cost the tabbed layout exists to avoid."""
    app = _app("dev", "staging")
    async with app.run_test() as pilot:
        await pilot.pause()
        first = app.provider_for("dev")
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert app.profile_name == "dev"
        assert app.provider_for("dev") is first


async def test_each_tab_keeps_its_own_watch_list(cfgdir):
    (cfgdir / "favorites.json").write_text(json.dumps({
        "dev": ["ingest_orders_to_warehouse"],
        "staging": ["sync_customers_to_crm", "refresh_finance_marts"],
    }))
    app = _app("dev", "staging")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert app.screen.pane.query_one("DataTable").row_count == 1

        await pilot.press("tab")
        for _ in range(4):
            await pilot.pause()
        assert app.screen.pane.profile_name == "staging"
        assert app.screen.pane.query_one("DataTable").row_count == 2


async def test_readonly_profiles_are_flagged_on_the_tab(cfgdir):
    app = _app("dev", "prod", readonly=("prod",))
    async with app.run_test() as pilot:
        await pilot.pause()
        labels = [str(t.label) for t in app.screen.query("Tab")]
        assert "dev" in labels
        assert any("prod ⊘" in lbl for lbl in labels)


async def test_drill_in_stays_on_the_tab_it_came_from(cfgdir):
    (cfgdir / "favorites.json").write_text(json.dumps(
        {"staging": ["vendor_feed_import"]}))
    app = _app("dev", "staging")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        for _ in range(4):
            await pilot.pause()
        app.screen.action_drill()
        for _ in range(3):
            await pilot.pause()
        assert app.screen.profile_name == "staging"
        assert app.screen.dag_id == "vendor_feed_import"
