# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-28

First public release. Distributed on PyPI as `airflow-atc`; the command is `atc`.

### Added

- **Terminal control tower for Airflow 3.** A Textual TUI for environments that are not
  reachable from a browser — inside a private Kubernetes cluster, or on AWS MWAA with no
  public webserver.
- **The connection path is always on screen.** `k8s ▸ cluster ▸ namespace ▸ :port ● 78ms
  v3.1.0` sits above everything, so you always know which environment you are pointed at.
- **Kubernetes provider** with a self-healing `kubectl port-forward`, a JWT minted from a
  cluster secret and renewed at expiry − 60s, and a PVC fallback for missing task logs.
- **MWAA provider** with two auth strategies — `mwaa:InvokeRestApi` first, falling back to
  `CreateWebLoginToken` on a permissions gap — selected automatically or pinned per profile.
- **One tab per environment**, each with its own connection, watch list and cursor. Tabs
  connect lazily, so startup never dials every configured profile.
- **A starred watch list** rather than a full DAG list, kept per profile in
  `~/.config/atc/favorites.json`.
- **An empty task log is reported as a finding**, not as a blank pane.
- **Read-only profiles** are marked `⊘` on the tab and refuse the trigger key outright.
- **`atc configure`**, a discovery wizard for kubectl contexts, AWS profiles and MWAA
  environments.
- **`atc --fake`**, a deterministic fake environment that needs no credentials and drives
  the whole test suite.

[Unreleased]: https://github.com/CloudsDocker/atc/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/CloudsDocker/atc/releases/tag/v0.1.0
