"""Tests for profile management modal: list, add, clone (sibling), edit, delete, switch."""

from pathlib import Path
import pytest
from textual.widgets import DataTable, Input, TabbedContent

from atc.config import load, save_profile
from atc.core.providers.fake import FakeProvider
from atc.tui.app import AtcApp, DagsScreen
from atc.tui.profile_manager import ProfileEditModal, ProfileManagerModal

pytestmark = pytest.mark.asyncio


@pytest.fixture
def cfgdir(tmp_path, monkeypatch):
    monkeypatch.setenv("ATC_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _setup_config(cfg_path: Path):
    save_profile(
        "dev06",
        {
            "type": "fake",
            "context": "mqu-eks-dev",
            "namespace": "airflow3-dev06",
            "service": "airflow-api-server-cluster-ip-service",
            "port": 8080,
            "secret": "airflow-secret",
        },
        is_default=True,
        path=cfg_path,
    )


async def test_open_profile_manager_and_switch(cfgdir):
    cfg_file = cfgdir / "config.toml"
    _setup_config(cfg_file)
    save_profile(
        "dev01",
        {
            "type": "fake",
            "context": "mqu-eks-dev",
            "namespace": "airflow3-dev01",
        },
        path=cfg_file,
    )

    conf = load(cfg_file)
    app = AtcApp(FakeProvider(), "dev06", config=conf, config_path=cfg_file)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.profile_name == "dev06"

        # Press 'p' to open ProfileManagerModal
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, ProfileManagerModal)

        table = app.screen.query_one("#profile-table", DataTable)
        assert table.row_count == 2

        # Move to dev01 (second row) and press Enter to switch
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()

        # Modal closed, active profile switched to dev01
        assert isinstance(app.screen, DagsScreen)
        assert app.profile_name == "dev01"
        tabs = app.screen.query_one("#profiles", TabbedContent)
        assert tabs.active == "pane_dev01"


async def test_clone_sibling_profile(cfgdir):
    cfg_file = cfgdir / "config.toml"
    _setup_config(cfg_file)
    conf = load(cfg_file)
    app = AtcApp(FakeProvider(), "dev06", config=conf, config_path=cfg_file)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Open ProfileManagerModal
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, ProfileManagerModal)

        # Press 'c' to clone dev06
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ProfileEditModal)

        # Verify smart sibling suggestions: dev06 -> dev01
        name_input = app.screen.query_one("#inp-name", Input)
        assert name_input.value == "dev01"
        ns_input = app.screen.query_one("#inp-ns", Input)
        assert ns_input.value == "airflow3-dev01"

        # Save clone via ctrl+s
        await pilot.press("ctrl+s")
        await pilot.pause()

        # Back in manager, dev01 added
        assert isinstance(app.screen, ProfileManagerModal)
        table = app.screen.query_one("#profile-table", DataTable)
        assert table.row_count == 2

        # Close manager
        await pilot.press("escape")
        await pilot.pause()

        # Both tabs now present in DagsScreen
        assert isinstance(app.screen, DagsScreen)
        tabs = app.screen.query_one("#profiles", TabbedContent)
        assert tabs.tab_count == 2


async def test_add_and_delete_profile(cfgdir):
    cfg_file = cfgdir / "config.toml"
    _setup_config(cfg_file)
    conf = load(cfg_file)
    app = AtcApp(FakeProvider(), "dev06", config=conf, config_path=cfg_file)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        # Press 'a' to add new profile
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, ProfileEditModal)

        app.screen.query_one("#inp-name", Input).value = "dev02"
        app.screen.query_one("#inp-context", Input).value = "mqu-eks-dev"
        app.screen.query_one("#inp-ns", Input).value = "airflow3-dev02"
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, ProfileManagerModal)
        table = app.screen.query_one("#profile-table", DataTable)
        assert table.row_count == 2

        # Now delete dev02
        await pilot.press("down")
        await pilot.press("d")
        await pilot.pause()

        # Confirm modal - click #yes
        await pilot.click("#yes")
        await pilot.pause()

        assert isinstance(app.screen, ProfileManagerModal)
        assert table.row_count == 1


async def test_edit_profile_and_set_default(cfgdir):
    cfg_file = cfgdir / "config.toml"
    _setup_config(cfg_file)
    save_profile(
        "dev01",
        {
            "type": "fake",
            "context": "mqu-eks-dev",
            "namespace": "airflow3-dev01",
        },
        path=cfg_file,
    )
    conf = load(cfg_file)
    app = AtcApp(FakeProvider(), "dev06", config=conf, config_path=cfg_file)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        # Highlight dev01 and set as default via '*'
        await pilot.press("down")
        await pilot.press("asterisk")
        await pilot.pause()

        reloaded = load(cfg_file)
        assert reloaded.default == "dev01"

        # Edit dev01 via 'e'
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, ProfileEditModal)

        app.screen.query_one("#inp-ns", Input).value = "airflow3-dev01-updated"
        await pilot.press("ctrl+s")
        await pilot.pause()

        reloaded = load(cfg_file)
        assert reloaded.profiles["dev01"].options["namespace"] == "airflow3-dev01-updated"
