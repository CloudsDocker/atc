# Security Policy

## Supported versions

atc is pre-1.0. Only the latest released version receives fixes.

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Use GitHub's private reporting instead:
[Report a vulnerability](https://github.com/CloudsDocker/atc/security/advisories/new).

You should get an acknowledgement within 72 hours, and an assessment within a week.

## What is in scope

atc holds short-lived credentials in memory and talks to Airflow environments that are
usually not otherwise reachable, so the interesting classes are:

- Leaking a JWT, an MWAA web-login token or a Kubernetes secret into logs, the UI, or a
  crash trace.
- Reaching an environment other than the one shown in the connection bar — the
  connection path on screen is a safety rail, and a mismatch is a security bug.
- Bypassing the `readonly = true` refusal or the trigger confirmation modal.
- Anything that causes a write against a remote Airflow other than the single
  confirmed `trigger()` call.

## What is not in scope

- `_jwt_expiry()` decoding a JWT payload without verifying its signature. This is
  deliberate: the client needs the clock, not trust. The token is still validated by
  the Airflow API server on every request.
- Credentials you put into `~/.config/atc/config.toml` yourself. atc never asks for a
  password in config; Kubernetes admin passwords are read from a cluster secret at
  runtime and AWS credentials come from the standard chain.
