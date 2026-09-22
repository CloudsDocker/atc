# Contributing to atc

Thanks for looking. atc is small on purpose, and the bar for new code is "does this
make the connection path clearer or the blast radius smaller" rather than "does this
add a feature".

## Setup

```bash
git clone https://github.com/CloudsDocker/atc.git
cd atc
uv sync --extra dev
uv run pytest -q
```

If you do not use [uv](https://docs.astral.sh/uv/):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## The one rule that matters: tests never touch a real environment

Every test in the suite — including the headless TUI tests — runs against
[`FakeProvider`](src/atc/core/providers/fake.py). No AWS credentials, no cluster, no
network, no `kubectl`. This is possible because everything the UI needs is behind the
eight-method [`AirflowProvider`](src/atc/core/provider.py) protocol:

```python
class AirflowProvider(Protocol):
    def describe(self) -> ConnectionInfo: ...
    def list_all_dag_ids(self) -> list[str]: ...
    def dag_summaries(self, dag_ids: list[str]) -> list[DagSummary]: ...
    def dag_runs(self, dag_id: str, limit: int = 20) -> list[DagRun]: ...
    def task_instances(self, dag_id: str, run_id: str) -> list[TaskInstance]: ...
    def task_log(self, dag_id, run_id, task_id, try_number) -> LogChunk: ...
    def trigger(self, dag_id: str, conf: dict | None = None) -> DagRun: ...
    def close(self) -> None: ...
```

If a change you are making cannot be tested through that protocol, that is usually a
signal the change is in the wrong layer. Raise it in the PR rather than reaching for
mocks of `boto3` or `subprocess`.

## Where things live

| Layer | Path | Rule |
|---|---|---|
| Transport | `src/atc/core/providers/` | Knows about kubectl, boto3, HTTP. Knows nothing about the UI. |
| Models | `src/atc/core/models.py` | Plain frozen dataclasses. No provider-specific fields. |
| Formatting | `src/atc/tui/render.py` | Pure functions, no Textual imports, unit-testable on its own. |
| Screens | `src/atc/tui/app.py` | Textual widgets and keybindings. No HTTP. |

## Conventions

- **Colour is never the only signal.** Every state has a distinct glyph as well, so the
  UI survives colour-blindness and greyscale screenshots. If you add a state, add a glyph.
- **No secrets in config.** k8s passwords are read from the cluster secret at runtime;
  AWS goes through the normal credential chain. Nothing that looks like a credential
  belongs in `config.toml`.
- **New writes need a confirmation and a `readonly` check.** Today there is exactly one
  write path (trigger). Adding a second is a design discussion before it is a PR.
- Match the existing style. The codebase leans on `from __future__ import annotations`,
  frozen dataclasses and short modules.

## Pull requests

1. Open an issue first for anything beyond a bug fix — it saves you writing code that
   does not fit the scope.
2. One concern per PR.
3. `uv run pytest -q` must pass. CI runs the same suite on Python 3.11, 3.12 and 3.13.
4. If you change behaviour that the README describes, update the README in the same PR.
   `README_zh.md` is a mirror; update it too, or say in the PR that you could not and it
   will be handled.

## Reporting security issues

Please do not open a public issue. Use
[GitHub's private advisory form](https://github.com/CloudsDocker/atc/security/advisories/new).
