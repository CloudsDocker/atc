"""Modal dialogs used across the TUI: confirmations and item pickers."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView


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

    BINDINGS = [
        Binding("escape", "dismiss_none", "back"),
        Binding("down", "cursor_down", "down", show=False),
        Binding("up", "cursor_up", "up", show=False),
    ]

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
        if view.children:
            view.index = 0

    @on(Input.Changed, "#filter")
    def _refilter(self, event: Input.Changed) -> None:
        self._fill(event.value)

    @on(Input.Submitted, "#filter")
    def _submit(self) -> None:
        view = self.query_one("#picker", ListView)
        item = view.highlighted_child or (view.children[0] if view.children else None)
        if item and getattr(item, "name", None):
            self.dismiss(item.name)

    @on(ListView.Selected)
    def _picked(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.name)

    def action_cursor_down(self) -> None:
        self.query_one("#picker", ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#picker", ListView).action_cursor_up()

    def action_dismiss_none(self) -> None:
        self.dismiss(None)
