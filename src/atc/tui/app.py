"""Textual front end. Knows only AirflowProvider - never boto3, never kubectl.

Every backend call runs in a thread worker: providers are blocking by design (they
shell out and hold sockets), and the UI must stay responsive while a tunnel comes up.
"""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import (Button, DataTable, Footer, Input, Label, ListItem,
                             ListView, Static, TabbedContent, TabPane)

from .. import favorites
from ..core.errors import AtcError, ReadOnly
from ..core.models import DagSummary
from .render import (STRIP_WIDTH, connection_line, fmt_ago, fmt_duration,
                     run_strip, state_badge)

CSS = """
Screen { background: $surface; }
TabbedContent { height: 1fr; }
ProfilePane { height: 1fr; }
/* one pane per profile means these cannot be ids - each pane has its own */
.connbar, #connbar { height: 1; background: $panel; color: $text; }
.status,  #status  { height: 1; color: $text-muted; padding: 0 1; }
DataTable { height: 1fr; }
DataTable > .datatable--cursor { background: $accent 40%; }
#title { height: 1; padding: 0 1; color: $text-muted; }
.modal { align: center middle; }
.modal-box {
    width: 70; height: auto; max-height: 80%;
    border: round $accent; background: $panel; padding: 1 2;
}
#logview { height: 1fr; padding: 0 1; }
#empty-hint { padding: 1 2; color: $warning; }
"""


def _pane_id(profile_name: str) -> str:
    """Textual ids must be identifier-safe; profile names are not (`prd-v3`)."""
    safe = "".join(c if c.isalnum() else "_" for c in profile_name)
    return f"pane_{safe}"


class ConnBar(Static):
    """Always on top. Which environment, reached how, how fast - a safety rail as
    much as a status line."""

    def show(self, info, profile_name: str) -> None:
        self.update(connection_line(info, profile_name))


class Confirm(ModalScreen[bool]):
    def __init__(self, question: str, danger: str = "") -> None:
        super().__init__()
        self.question = question
        self.danger = danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(self.question)
            if self.danger:
                yield Label(self.danger, classes="danger")
            with Horizontal():
                yield Button("Confirm", variant="warning", id="yes")
                yield Button("Cancel", variant="primary", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class PickList(ModalScreen[str | None]):
    """Fuzzy-ish picker used for both 'switch profile' and 'add DAG'."""

    BINDINGS = [Binding("escape", "dismiss_none", "back")]

    def __init__(self, title: str, items: list[str], marked: set[str] | None = None):
        super().__init__()
        self.title_text = title
        self.items = items
        self.marked = marked or set()

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(self.title_text, id="title")
            yield Input(placeholder="type to filter…", id="filter")
            yield ListView(id="picker")

    def on_mount(self) -> None:
        self._fill("")
        self.query_one("#filter", Input).focus()

    def _fill(self, needle: str) -> None:
        view = self.query_one("#picker", ListView)
        view.clear()
        needle = needle.lower()
        for name in self.items:
            if needle and needle not in name.lower():
                continue
            mark = "★ " if name in self.marked else "  "
            view.append(ListItem(Label(f"{mark}{name}"), name=name))

    @on(Input.Changed, "#filter")
    def _refilter(self, event: Input.Changed) -> None:
        self._fill(event.value)

    @on(Input.Submitted, "#filter")
    def _submit(self) -> None:
        view = self.query_one("#picker", ListView)
        if view.children:
            view.index = 0
            self.dismiss(view.children[0].name)

    @on(ListView.Selected)
    def _picked(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.name)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class ProfilePane(Vertical):
    """One profile's watch list, with its own connection bar, status and table.

    Each profile keeps its own pane so switching tabs is instant: the table, the
    cursor position and the last fetch are all still there when you come back.
    """

    # everything except the DAG name is fixed-width; the name takes what is left
    _FIXED_COLS = 58

    def __init__(self, profile_name: str) -> None:
        super().__init__()
        self.profile_name = profile_name
        self.loaded = False
        self.status_text = ""

    def compose(self) -> ComposeResult:
        yield ConnBar(classes="connbar")
        yield Static("", classes="status", markup=False)
        yield DataTable(classes="dags", cursor_type="row", zebra_stripes=False)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("DAG", width=max(24, self.app.size.width - self._FIXED_COLS))
        table.add_column("SCHED", width=10)
        table.add_column(f"LAST {STRIP_WIDTH} RUNS", width=STRIP_WIDTH)
        table.add_column("LAST", width=10)
        table.add_column("Ø", width=7)
        # Deliberately no fetch here. Every pane mounts at startup, so loading on
        # mount would open a tunnel and authenticate against *every* configured
        # profile the moment the app starts - including ones that are not set up
        # yet. Panes connect when their tab is first activated instead.

    # --- data -----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Called when this pane's tab is activated. Fetches once, then leaves
        the pane alone - `r` is how you ask for fresh data."""
        if not self.loaded:
            self.loaded = True
            self.reload()

    def reload(self) -> None:
        self._set_status("connecting…" if not self.status_text else "refreshing…")
        self._load()

    @work(thread=True, exclusive=True, group="load")
    def _load(self) -> None:
        app: AtcApp = self.app
        try:
            provider = app.provider_for(self.profile_name)
            info = provider.describe()
            summaries = provider.dag_summaries(app.favorites_for(self.profile_name))
        except AtcError as e:
            self.app.call_from_thread(self._set_status, f"✗ {e}")
            return
        except Exception as e:                       # noqa: BLE001 - surface, never crash
            self.app.call_from_thread(self._set_status, f"✗ {type(e).__name__}: {e}")
            return
        self.app.call_from_thread(self._paint, info, summaries)

    def _paint(self, info, summaries: list[DagSummary]) -> None:
        self.query_one(ConnBar).show(info, self.profile_name)
        table = self.query_one(DataTable)
        table.clear()
        for s in summaries:
            if s.error:
                table.add_row(s.dag_id, "?", f"⚠ {s.error[:18]}", "?", "--",
                              key=s.dag_id)
                continue
            last = s.recent[0] if s.recent else None
            # state badge and recency share a column - at 80 columns there is no
            # room for both, and neither is readable without the other anyway
            when = state_badge(s.last_state).copy()
            when.append(" " + fmt_ago(last.start_date if last else None), style="none")
            table.add_row(
                s.dag_id,
                s.schedule or "--",
                run_strip(s.recent),
                when,
                fmt_duration(s.avg_duration_s),
                key=s.dag_id,
            )
        if not summaries:
            self._set_status("no DAGs watched yet — press [a] to add one")
        else:
            failing = [s.dag_id for s in summaries if s.last_state == "failed"]
            self._set_status(
                f"★ watching {len(summaries)}"
                + (f"   ✗ failing: {', '.join(failing)}" if failing else "   all green"))

    def _set_status(self, msg: str) -> None:
        self.status_text = msg
        self.query_one(".status", Static).update(msg)

    def selected_dag(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)


class DagsScreen(Screen):
    """Main screen: one tab per profile, each showing that profile's watch list.

    A real environment has hundreds of DAGs, so a pane lists only what you starred;
    and a real job spans several environments, so the profiles are tabs rather than
    something you dig out of a picker.
    """

    BINDINGS = [
        Binding("tab", "cycle_profile(1)", "next profile", priority=True),
        Binding("shift+tab", "cycle_profile(-1)", "prev profile", priority=True,
                show=False),
        Binding("a", "add", "add DAG"),
        Binding("f", "unstar", "unstar"),
        Binding("enter", "drill", "runs", priority=True),
        Binding("t", "trigger", "trigger"),
        Binding("r", "refresh", "refresh"),
        Binding("q", "quit", "quit"),
    ] + [
        # digits jump straight to the nth profile; out-of-range ones simply no-op
        Binding(str(n), f"jump_profile({n})", f"profile {n}", show=False)
        for n in range(1, 10)
    ]

    def compose(self) -> ComposeResult:
        with TabbedContent(id="profiles"):
            for name in self.app.profile_names:
                with TabPane(self._tab_label(name), id=_pane_id(name)):
                    yield ProfilePane(name)
        yield Footer()

    def _tab_label(self, name: str) -> str:
        # a readonly environment is worth flagging before you are looking at it,
        # not after you have pressed `t`
        return f"{name} ⊘" if self.app.is_readonly(name) else name

    # --- profile switching -------------------------------------------------
    @property
    def pane(self) -> ProfilePane:
        """The pane the keys act on: whichever tab is in front."""
        tabs = self.query_one("#profiles", TabbedContent)
        return tabs.get_pane(tabs.active).query_one(ProfilePane)

    @on(TabbedContent.TabActivated)
    def _tab_changed(self, event: TabbedContent.TabActivated) -> None:
        pane = event.pane.query_one(ProfilePane)
        self.app.profile_name = pane.profile_name
        pane.ensure_loaded()

    def action_cycle_profile(self, step: int) -> None:
        names = self.app.profile_names
        if len(names) <= 1:
            return
        tabs = self.query_one("#profiles", TabbedContent)
        current = names.index(self.app.profile_name)
        tabs.active = _pane_id(names[(current + step) % len(names)])

    def action_jump_profile(self, index: int) -> None:
        names = self.app.profile_names
        if 1 <= index <= len(names):
            self.query_one("#profiles", TabbedContent).active = _pane_id(names[index - 1])

    # --- data ---------------------------------------------------------------
    def action_refresh(self) -> None:
        self.pane.reload()

    # --- favourites ---------------------------------------------------------
    def action_add(self) -> None:
        pane = self.pane
        pane._set_status("loading full DAG list…")
        self._open_browser(pane)

    @work(thread=True, exclusive=True, group="browse")
    def _open_browser(self, pane: ProfilePane) -> None:
        try:
            ids = self.app.provider_for(pane.profile_name).list_all_dag_ids()
        except Exception as e:                       # noqa: BLE001
            self.app.call_from_thread(pane._set_status, f"✗ {e}")
            return
        self.app.call_from_thread(self._show_browser, pane, ids)

    def _show_browser(self, pane: ProfilePane, ids: list[str]) -> None:
        def picked(dag_id: str | None) -> None:
            if dag_id:
                self.app.toggle_favorite(dag_id, pane.profile_name)
                pane.reload()
            else:
                pane._set_status("")
        self.app.push_screen(
            PickList(f"all DAGs in {pane.profile_name} ({len(ids)}) — "
                     f"enter to star/unstar, esc to go back",
                     ids, marked=set(self.app.favorites_for(pane.profile_name))),
            picked)

    def action_unstar(self) -> None:
        pane = self.pane
        dag_id = pane.selected_dag()
        if dag_id:
            self.app.toggle_favorite(dag_id, pane.profile_name)
            pane.reload()

    # --- navigation ---------------------------------------------------------
    def action_drill(self) -> None:
        pane = self.pane
        dag_id = pane.selected_dag()
        if dag_id:
            self.app.push_screen(RunsScreen(dag_id, pane.profile_name))

    # --- the one write ------------------------------------------------------
    def action_trigger(self) -> None:
        pane = self.pane
        dag_id = pane.selected_dag()
        if not dag_id:
            return
        info = self.app.provider_for(pane.profile_name).describe()
        if info.readonly:
            pane._set_status(
                f"✗ profile {pane.profile_name!r} is readonly — trigger blocked")
            return

        def confirmed(yes: bool) -> None:
            if yes:
                self._do_trigger(pane, dag_id)
        self.app.push_screen(
            Confirm(f"Trigger {dag_id}?", f"on {info.as_path()}"), confirmed)

    @work(thread=True, group="trigger")
    def _do_trigger(self, pane: ProfilePane, dag_id: str) -> None:
        try:
            run = self.app.provider_for(pane.profile_name).trigger(dag_id)
        except ReadOnly as e:
            self.app.call_from_thread(pane._set_status, f"✗ {e}")
            return
        except Exception as e:                       # noqa: BLE001
            self.app.call_from_thread(pane._set_status, f"✗ trigger failed: {e}")
            return
        self.app.call_from_thread(pane._set_status, f"✓ triggered {run.run_id}")
        self.app.call_from_thread(pane.reload)


class RunsScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "back"),
        Binding("enter", "drill", "log", priority=True),
        Binding("r", "reload", "refresh"),
    ]

    def __init__(self, dag_id: str, profile_name: str) -> None:
        super().__init__()
        self.dag_id = dag_id
        self.profile_name = profile_name
        self.run_id: str | None = None
        self.status_text = ""

    @property
    def provider(self):
        return self.app.provider_for(self.profile_name)

    def compose(self) -> ComposeResult:
        yield ConnBar(id="connbar")
        yield Static(f" {self.dag_id}", id="title", markup=False)
        yield DataTable(id="runs", cursor_type="row")
        yield DataTable(id="tasks", cursor_type="row")
        yield Static("", id="status", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        runs = self.query_one("#runs", DataTable)
        runs.add_columns("RUN", "STATE", "STARTED", "TOOK")
        tasks = self.query_one("#tasks", DataTable)
        tasks.add_columns("TASK", "STATE", "TRY", "TOOK")
        self.query_one(ConnBar).show(self.provider.describe(), self.profile_name)
        self.action_reload()

    def action_reload(self) -> None:
        self._load_runs()

    @work(thread=True, exclusive=True, group="runs")
    def _load_runs(self) -> None:
        try:
            runs = self.provider.dag_runs(self.dag_id, limit=20)
        except Exception as e:                       # noqa: BLE001
            self.app.call_from_thread(self._status, f"✗ {e}")
            return
        self.app.call_from_thread(self._paint_runs, runs)

    def _paint_runs(self, runs) -> None:
        table = self.query_one("#runs", DataTable)
        table.clear()
        for r in runs:
            table.add_row(r.run_id[:40], state_badge(r.state), fmt_ago(r.start_date),
                          fmt_duration(r.duration_s), key=r.run_id)
        if runs:
            table.focus()
            self._select_run(runs[0].run_id)

    @on(DataTable.RowHighlighted, "#runs")
    def _run_moved(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value:
            self._select_run(str(event.row_key.value))

    def _select_run(self, run_id: str) -> None:
        self.run_id = run_id
        self._load_tasks(run_id)

    @work(thread=True, exclusive=True, group="tasks")
    def _load_tasks(self, run_id: str) -> None:
        try:
            tis = self.provider.task_instances(self.dag_id, run_id)
        except Exception as e:                       # noqa: BLE001
            self.app.call_from_thread(self._status, f"✗ {e}")
            return
        self.app.call_from_thread(self._paint_tasks, tis)

    def _paint_tasks(self, tis) -> None:
        table = self.query_one("#tasks", DataTable)
        table.clear()
        for t in tis:
            table.add_row(t.task_id, state_badge(t.state), str(t.try_number),
                          fmt_duration(t.duration_s), key=f"{t.task_id}|{t.try_number}")
        self._status(f"{len(tis)} tasks — enter on a task to read its log")

    def _status(self, msg: str) -> None:
        self.status_text = msg
        self.query_one("#status", Static).update(msg)

    def action_drill(self) -> None:
        table = self.query_one("#tasks", DataTable)
        if not self.run_id or table.row_count == 0 or not table.has_focus:
            return
        key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        task_id, try_number = key.rsplit("|", 1)
        self.app.push_screen(
            LogScreen(self.dag_id, self.run_id, task_id, int(try_number),
                      self.profile_name))


class LogScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "back")]

    def __init__(self, dag_id, run_id, task_id, try_number, profile_name) -> None:
        super().__init__()
        self.dag_id, self.run_id = dag_id, run_id
        self.task_id, self.try_number = task_id, try_number
        self.profile_name = profile_name

    def compose(self) -> ComposeResult:
        yield Static(f" {self.dag_id} ▸ {self.task_id} ▸ try {self.try_number}",
                     id="title", markup=False)
        yield Static("loading…", id="logview", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._load()

    @work(thread=True, group="log")
    def _load(self) -> None:
        try:
            chunk = self.app.provider_for(self.profile_name).task_log(
                self.dag_id, self.run_id, self.task_id, self.try_number)
        except Exception as e:                       # noqa: BLE001
            self.app.call_from_thread(
                self.query_one("#logview", Static).update, f"✗ {e}")
            return
        self.app.call_from_thread(self._paint, chunk)

    def _paint(self, chunk) -> None:
        view = self.query_one("#logview", Static)
        if chunk.text.strip():
            view.update(chunk.text)
            return
        # §5.2 - an empty log is itself a finding, not a blank pane.
        view.update(
            "⚠ Airflow returned no task log for this attempt.\n\n"
            "  That usually means the worker process was killed before it could write\n"
            "  anything — an OOM kill, a SIGKILL, or an executor-level crash. The\n"
            "  evidence lives one layer down, in the pod events or CloudWatch, not in\n"
            "  Airflow.\n\n"
            f"  {chunk.note or ''}")


class AtcApp(App):
    CSS = CSS
    TITLE = "atc"

    def __init__(self, provider, profile_name: str, config=None) -> None:
        super().__init__()
        self.profile_name = profile_name
        self.config = config
        # One live provider per profile, built on first visit and kept afterwards.
        # Keeping it is the point: a k8s provider holds an open port-forward and a
        # JWT, so tabbing back to a profile you already opened costs nothing.
        self._providers = {profile_name: provider}

    @property
    def profile_names(self) -> list[str]:
        return list(self.config.profiles) if self.config else [self.profile_name]

    def is_readonly(self, name: str) -> bool:
        if self.config and name in self.config.profiles:
            return self.config.profiles[name].readonly
        return False

    def provider_for(self, name: str):
        """Build on demand. Constructors do no I/O, so this is cheap - the
        connection happens on the first request the pane makes."""
        if name not in self._providers:
            self._providers[name] = self.config.get(name).build()
        return self._providers[name]

    @property
    def provider(self):
        """The active profile's provider, for the drill-in screens."""
        return self.provider_for(self.profile_name)

    def favorites_for(self, name: str) -> list[str]:
        return favorites.get(name)

    @property
    def favorites(self) -> list[str]:
        return self.favorites_for(self.profile_name)

    def on_mount(self) -> None:
        self.push_screen(DagsScreen())

    def toggle_favorite(self, dag_id: str, profile: str | None = None) -> list[str]:
        return favorites.toggle(profile or self.profile_name, dag_id)

    def on_unmount(self) -> None:
        for provider in self._providers.values():
            try:
                provider.close()
            except Exception:                        # noqa: BLE001
                pass
