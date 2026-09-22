# atc — Airflow Traffic Control

A terminal control tower for Airflow environments that sit behind awkward network
paths: inside an EKS cluster, or in a managed service in a private subnet.

```
 dev-k8s  staging  prod ⊘
 ◉ dev-k8s   k8s ▸ demo-cluster ▸ airflow-demo ▸ :54312  ● 78ms  v3.1.0
 ★ watching 3   ✗ failing: vendor_feed_import
 DAG                       SCHED       LAST 20 RUNS          LAST        Ø
 ingest_orders_to_warehou  @hourly     ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇  ✓ 60m ago   8m42s
 sync_customers_to_crm     0 2 * * *   ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇  ✓ 60m ago   9m15s
 vendor_feed_import        @hourly     ▇▇▇▇▇▇▇▇▇▇▇▇▚▇▇▇▇▇▇▚  ✗ 60m ago   7m36s
 tab next profile  a add DAG  f unstar  ⏎ runs  t trigger  r refresh  q quit
```

## Try it with no backend

```bash
uv run atc --fake
```

Fake data, no AWS, no cluster, no network.

## Three things it does differently

**The connection path is always on screen.** Which environment, reached by which
mechanism, at what latency. It is a safety rail — you should never trigger a DAG
without knowing which environment you are pointed at — and it is the whole point of
the tool.

**One tab per environment, `tab` to switch.** Each tab keeps its own connection, its
own watch list and its own cursor position, so flicking between dev and prod is
instant rather than a reconnect. A tab only connects the first time you open it — the
app never dials every environment you configured just because it started. A readonly
environment is marked `⊘` on its tab, before you are looking at it rather than after
you press `t`.

**The main screen is a watch list, not a DAG list.** A real environment has hundreds
of DAGs. Rendering all of them costs one `dagRuns` call each and tells you nothing.
Press `a` to browse the full list and star what you care about; the main screen then
costs O(favourites). Stars live in `~/.config/atc/favorites.json`, per profile.

Keys: `tab` / `shift+tab` cycle environments, `1`–`9` jump straight to one.

**An empty task log is treated as a finding.** When Airflow returns nothing for a
failed task, that usually means the worker was killed before it could write — and the
evidence is one layer down, in pod events or CloudWatch. The log screen says so
instead of showing a blank pane. On Kubernetes it also falls back to reading the log
straight off the scheduler's PVC.

## Configure

```bash
mkdir -p ~/.config/atc && cp config.example.toml ~/.config/atc/config.toml
```

Two profile types:

- `k8s` — opens one `kubectl port-forward` for the whole session, reads the admin
  password from a cluster secret, exchanges it for a JWT and renews it 60s before
  expiry. If the tunnel dies it rebuilds itself.
- `mwaa` — tries `mwaa:InvokeRestApi` first and falls back to the
  `CreateWebLoginToken` → `/pluginsv2/aws_mwaa/login` flow. Credentials come from the
  normal AWS chain; no secrets in the config file.

MWAA environment names follow no pattern across accounts, so write each one out:

```bash
aws mwaa list-environments --profile <profile> --region <region>
```

Mark production profiles `readonly = true` — `t` is then refused outright.

## Scope

Airflow 3 (`/api/v2`) only — an Airflow 2 environment is refused by name rather than
failing obscurely. Read-mostly: the single write is triggering a DAG, behind a
confirmation. Airflow 2 support and the MCP adapter are not in this version.

## Develop

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

The test suite runs entirely on `FakeProvider`, including the headless UI tests — no
credentials required.
