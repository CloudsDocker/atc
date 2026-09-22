from __future__ import annotations

import argparse
import sys

from .core.errors import AtcError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atc", description="Airflow Traffic Control — a terminal control tower.")
    parser.add_argument("-p", "--profile", help="profile name from config.toml")
    parser.add_argument("--fake", action="store_true",
                        help="run against fake data; needs no AWS, k8s or network")
    parser.add_argument("--config", help="path to config.toml")
    args = parser.parse_args(argv)

    from .tui.app import AtcApp

    if args.fake:
        from .core.providers.fake import FakeProvider
        AtcApp(FakeProvider(), "fake").run()
        return 0

    from pathlib import Path

    from . import config as cfg
    try:
        conf = cfg.load(Path(args.config) if args.config else None)
        profile = conf.get(args.profile)
        provider = profile.build()
    except AtcError as e:
        print(f"atc: {e}", file=sys.stderr)
        return 1

    AtcApp(provider, profile.name, config=conf).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
