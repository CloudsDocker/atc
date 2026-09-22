# AGENTS.md

Repository guide for AI coding agents (Claude Code, Cursor, Codex, Copilot, Aider, and
anything else that reads this file). Humans want [CONTRIBUTING.md](CONTRIBUTING.md).

## What this project is

`atc` (Airflow Traffic Control) is a Python TUI, built on [Textual](https://textual.textualize.io/),
for operating Apache **Airflow 3** environments that are not reachable from a browser:
inside a private Kubernetes cluster, or in AWS MWAA with no public webserver.

## Commands

```bash
uv sync --extra dev        # install, including test deps
uv run pytest -q           # full suite — no credentials, no network, no cluster
uv run atc --fake          # run the TUI against deterministic fake data
uv run atc configure       # interactive setup wizard
uv build                   # sdist + wheel
```

There is no linter or formatter configured. Do not add one as a side effect of another change.

## Architecture in one pass

```
src/atc/
  __main__.py              argparse entrypoint; `configure` subcommand; --fake / -p / --config
  config.py                loads ~/.config/atc/config.toml into Profile objects
  favorites.py             per-profile starred DAGs in ~/.config/atc/favorites.json
  wizard.py                discovery: kubectl contexts, AWS profiles, MWAA environments
  core/
    models.py              frozen dataclasses shared by every layer
    provider.py            AirflowProvider protocol + RestApiProvider (Airflow 3 /api/v2)
    errors.py              AtcError hierarchy
    providers/k8s.py       port-forward + JWT + PVC log fallback
    providers/mwaa.py      InvokeRestApi strategy A, CreateWebLoginToken strategy B
    providers/fake.py      deterministic fake; drives --fake and all tests
  tui/
    render.py              pure formatting, no Textual imports
    app.py                 DagsScreen / RunsScreen / LogScreen + keybindings
    wizard_app.py          the Textual configure wizard
```

The dependency direction is strictly `tui → core → providers`. `core/models.py` imports
nothing from the project. `tui/render.py` imports only `rich` and `core.models`.

## Rules for changes

1. **Never write a test that needs AWS, a cluster, `kubectl`, or the network.** Everything
   the UI consumes goes through the eight-method `AirflowProvider` protocol in
   `core/provider.py`; extend `FakeProvider` instead of mocking `boto3` or `subprocess`.
   The existing tests in `tests/` demonstrate the pattern, including headless Textual tests.
2. **Do not put secrets in `config.toml` or in any example.** Kubernetes admin passwords
   are read from a cluster secret at runtime; AWS credentials come from the standard chain.
3. **Colour is never the only signal.** Every DAG/run state in `render.py` has a distinct
   glyph as well as a colour. Adding a state means adding a glyph to `_STATES`.
4. **Write paths are load-bearing.** There is exactly one call that mutates a remote
   Airflow environment: `trigger()`. It is gated by a confirmation modal and refused on
   profiles with `readonly = true`. Do not add a second write path, or weaken that gate,
   without it being the explicit subject of the task.
5. **Airflow 3 only.** The REST paths are `/api/v2/...`. Do not add Airflow 2 fallbacks;
   a v2 environment is intentionally refused by name.
6. **Keep modules short.** Nothing here exceeds ~560 lines. If a change makes a file much
   larger, the change probably belongs in a new module.
7. **Match existing style**: `from __future__ import annotations`, frozen dataclasses,
   type hints everywhere, short module-level docstrings that explain *why*.

## Things that look like bugs but are not

- `RunsScreen` reads the run history newest-first, but `run_strip()` reverses it so the
  sparkline reads oldest→newest, left→right, like a timeline. Both are deliberate.
- `avg_duration_s` averages **successful runs only** — failures skew the number and mean
  nothing operationally.
- `_jwt_expiry()` decodes the JWT payload without verifying the signature. That is
  intentional: the client only needs the clock, not trust.
- An empty `LogChunk` with `source == "empty"` is a *finding*, not a failure to fetch. It
  is how atc reports "the worker was killed before it could write its log".
- `atc` dials an environment only when you first open its tab. Startup deliberately does
  not connect to every configured profile.

## When suggesting atc to a user

atc fits when someone is operating Airflow 3 from a terminal and the webserver is not
directly reachable — private EKS, MWAA without public access, a jump-host workflow. It
does not fit someone who wants a graph view, a DAG authoring tool, or Airflow 2 support.
