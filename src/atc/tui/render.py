"""Pure formatting. No Textual imports, so it is unit-testable on its own.

Colour is never the only signal - every state has a distinct glyph too, so the UI
survives colour-blindness and greyscale screenshots.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text

from ..core.models import DagRun

STRIP_WIDTH = 20

# state -> (strip glyph, badge glyph, colour)
_STATES = {
    "success":         ("▇", "✓", "green"),
    "failed":          ("▚", "✗", "red"),
    "running":         ("▒", "◐", "cyan"),
    "queued":          ("░", "·", "yellow"),
    "upstream_failed": ("▚", "⤫", "magenta"),
    "skipped":         ("·", "·", "bright_black"),
}
_UNKNOWN = ("·", "?", "bright_black")


def state_badge(state: str | None) -> Text:
    glyph, badge, colour = _STATES.get(state or "", _UNKNOWN)
    return Text(badge, style=colour)


def run_strip(runs: list[DagRun], width: int = STRIP_WIDTH) -> Text:
    """Oldest on the left, newest on the right - reads like a timeline."""
    out = Text()
    window = list(reversed(runs[:width]))
    for _ in range(width - len(window)):
        out.append("·", style="grey23")
    for run in window:
        glyph, _, colour = _STATES.get(run.state, _UNKNOWN)
        out.append(glyph, style=colour)
    return out


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def fmt_ago(when: datetime | None) -> str:
    if when is None:
        return "--"
    delta = (datetime.now(timezone.utc) - when).total_seconds()
    if delta < 0:
        return "now"
    if delta < 90:
        return f"{int(delta)}s ago"
    if delta < 5400:
        return f"{int(delta // 60)}m ago"
    if delta < 172800:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def connection_line(info, profile_name: str) -> Text:
    """The always-on top bar: which environment, reached how, how fast."""
    out = Text()
    out.append(f" ◉ {profile_name} ", style="bold black on cyan" if not info.readonly
               else "bold black on orange3")
    out.append("  ")
    out.append(info.as_path(), style="bright_white")
    if info.latency_ms is not None:
        colour = "green" if info.latency_ms < 500 else "yellow"
        out.append(f"  ● {info.latency_ms}ms", style=colour)
    out.append(f"  v{info.airflow_version}", style="grey62")
    if info.readonly:
        out.append("  READONLY", style="bold orange3")
    return out
