"""Connection profiles. Hand-edited, read-only to the program.

Favourites deliberately live elsewhere (favorites.py) - this file has comments worth
keeping, and a program that rewrites TOML destroys them.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .core.errors import AtcError


def config_dir() -> Path:
    return Path(os.environ.get("ATC_CONFIG_DIR") or Path.home() / ".config" / "atc")


def config_path() -> Path:
    return config_dir() / "config.toml"


@dataclass
class Profile:
    name: str
    type: str
    readonly: bool = False
    options: dict = field(default_factory=dict)

    def build(self):
        opts = dict(self.options)
        opts.pop("type", None)
        opts.pop("readonly", None)
        if self.type == "k8s":
            from .core.providers.k8s import K8sProvider
            return K8sProvider(readonly=self.readonly, **opts)
        if self.type == "mwaa":
            from .core.providers.mwaa import MwaaProvider
            opts.pop("airflow", None)
            return MwaaProvider(readonly=self.readonly, **opts)
        if self.type == "fake":
            from .core.providers.fake import FakeProvider
            return FakeProvider(readonly=self.readonly)
        raise AtcError(f"profile {self.name!r}: unknown type {self.type!r}")


@dataclass
class Config:
    default: str | None
    profiles: dict[str, Profile]

    def get(self, name: str | None) -> Profile:
        key = name or self.default
        if key is None:
            raise AtcError("no profile given and no `default` set in config.toml")
        if key not in self.profiles:
            known = ", ".join(sorted(self.profiles)) or "(none)"
            raise AtcError(f"unknown profile {key!r}. Configured: {known}")
        return self.profiles[key]


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        raise AtcError(
            f"no config at {path}\n"
            f"Copy config.example.toml there and fill in your environments, "
            f"or run `atc --fake` to try the UI with no backend.")
    raw = tomllib.loads(path.read_text())
    profiles = {
        name: Profile(name=name, type=body.get("type", ""),
                      readonly=bool(body.get("readonly", False)), options=body)
        for name, body in (raw.get("profiles") or {}).items()
    }
    if not profiles:
        raise AtcError(f"{path} defines no [profiles.*]")
    return Config(default=raw.get("default"), profiles=profiles)
