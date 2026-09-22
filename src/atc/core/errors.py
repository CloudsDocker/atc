"""Error tree. Every one of these must carry an actionable message - the TUI shows
`str(e)` directly to the user, never a botocore or httpx stack trace."""

from __future__ import annotations


class AtcError(Exception):
    """Base. Anything a provider raises that the TUI is expected to display."""


class CredentialsExpired(AtcError):
    """AWS/k8s credentials need a refresh. Message must say the exact command to run."""


class NotReachable(AtcError):
    """Network path to the Airflow webserver does not exist from here."""


class AuthFailed(AtcError):
    """Reached the server, but it rejected us."""


class ReadOnly(AtcError):
    """Write attempted on a profile marked readonly."""


class ProviderError(AtcError):
    """Everything else the backend said no to."""
