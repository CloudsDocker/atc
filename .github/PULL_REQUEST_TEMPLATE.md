## What changed

<!-- One or two sentences. -->

## Why

<!-- The problem this solves. -->

## Checklist

- [ ] `uv run pytest -q` passes
- [ ] No test needs AWS, a cluster, `kubectl`, or the network (extend `FakeProvider` instead)
- [ ] Layer direction still holds: `tui → core → providers`
- [ ] Any new DAG/run state has a distinct glyph in `render.py`, not just a colour
- [ ] No second remote-write path added, and the `trigger()` gate is untouched
