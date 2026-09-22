"""Per-profile watch list, owned and rewritten by the app."""

from __future__ import annotations

import json
from pathlib import Path

from .config import config_dir


def favorites_path() -> Path:
    return config_dir() / "favorites.json"


def _read() -> dict[str, list[str]]:
    path = favorites_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: list(v) for k, v in data.items() if isinstance(v, list)}


def get(profile: str) -> list[str]:
    return _read().get(profile, [])


def toggle(profile: str, dag_id: str) -> list[str]:
    data = _read()
    current = data.get(profile, [])
    if dag_id in current:
        current.remove(dag_id)
    else:
        current.append(dag_id)
    data[profile] = current
    path = favorites_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    return current
