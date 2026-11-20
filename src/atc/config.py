"""Connection profiles.

Read from ~/.config/atc/config.toml, with helper methods to add, update,
and remove profiles in-place while preserving surrounding comments.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


def save_profile(
    name: str,
    data: dict[str, Any],
    is_default: bool = False,
    old_name: str | None = None,
    path: Path | None = None,
) -> Config:
    """Save or update a profile in config.toml, preserving surrounding comments."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if path.exists():
        lines = path.read_text().splitlines()

    target = old_name or name

    # Handle default profile line
    default_pattern = re.compile(r'^\s*default\s*=\s*["\']?([^"\'\s]+)["\']?')
    has_default = any(default_pattern.match(l) for l in lines)
    is_curr_default = False
    for i, l in enumerate(lines):
        m = default_pattern.match(l)
        if m and m.group(1) == target:
            is_curr_default = True
            break

    if is_default or not has_default or (is_curr_default and old_name != name):
        if has_default:
            for i, l in enumerate(lines):
                if default_pattern.match(l):
                    lines[i] = f'default = "{name}"'
                    break
        else:
            lines.insert(0, f'default = "{name}"')
            if len(lines) > 1 and lines[1].strip():
                lines.insert(1, "")

    # Format new profile block
    opts = dict(data)
    ptype = opts.pop("type", "k8s")
    readonly = bool(opts.pop("readonly", False))
    opts.pop("name", None)

    block = [f"[profiles.{name}]", f'type = "{ptype}"']
    if readonly:
        block.append("readonly = true")
    for k, v in sorted(opts.items()):
        if isinstance(v, bool):
            block.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            block.append(f"{k} = {v}")
        else:
            block.append(f'{k} = "{v}"')

    # Replace existing block or append
    header_pattern = re.compile(rf'^\s*\[profiles\.{re.escape(target)}\]\s*$')
    section_pattern = re.compile(r'^\s*\[')

    start_idx = None
    for i, line in enumerate(lines):
        if header_pattern.match(line):
            start_idx = i
            break

    if start_idx is not None:
        end_idx = len(lines)
        for j in range(start_idx + 1, len(lines)):
            if section_pattern.match(lines[j]):
                end_idx = j
                break
        lines[start_idx:end_idx] = block
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block)
        lines.append("")

    path.write_text("\n".join(lines).strip() + "\n")
    return load(path)


def delete_profile(name: str, path: Path | None = None) -> Config:
    """Remove a profile from config.toml."""
    path = path or config_path()
    if not path.exists():
        raise AtcError(f"no config at {path}")

    lines = path.read_text().splitlines()
    header_pattern = re.compile(rf'^\s*\[profiles\.{re.escape(name)}\]\s*$')
    section_pattern = re.compile(r'^\s*\[')

    start_idx = None
    for i, line in enumerate(lines):
        if header_pattern.match(line):
            start_idx = i
            break

    if start_idx is not None:
        end_idx = len(lines)
        for j in range(start_idx + 1, len(lines)):
            if section_pattern.match(lines[j]):
                end_idx = j
                break
        del lines[start_idx:end_idx]

    # Check if we deleted the default profile
    default_pattern = re.compile(r'^\s*default\s*=\s*["\']?([^"\'\s]+)["\']?')
    curr_default = None
    for l in lines:
        m = default_pattern.match(l)
        if m:
            curr_default = m.group(1)
            break

    profile_hdr_pattern = re.compile(r'^\s*\[profiles\.([^\]]+)\]')
    remaining = [
        m.group(1) for l in lines if (m := profile_hdr_pattern.match(l))
    ]

    if curr_default == name:
        if remaining:
            new_def = remaining[0]
            for i, l in enumerate(lines):
                if default_pattern.match(l):
                    lines[i] = f'default = "{new_def}"'
                    break
        else:
            lines = [l for l in lines if not default_pattern.match(l)]

    content = "\n".join(lines).strip()
    path.write_text((content + "\n") if content else "")
    if remaining:
        return load(path)
    return Config(default=None, profiles={})


def set_default_profile(name: str, path: Path | None = None) -> Config:
    """Update default profile pointer in config.toml."""
    path = path or config_path()
    if not path.exists():
        raise AtcError(f"no config at {path}")

    lines = path.read_text().splitlines()
    default_pattern = re.compile(r'^\s*default\s*=')
    found = False
    for i, l in enumerate(lines):
        if default_pattern.match(l):
            lines[i] = f'default = "{name}"'
            found = True
            break
    if not found:
        lines.insert(0, f'default = "{name}"')

    path.write_text("\n".join(lines).strip() + "\n")
    return load(path)
