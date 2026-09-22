"""MWAA provider. The valuable behaviour here is diagnosis: every failure must name
a cause the user can act on, because none of them are visible from the Airflow UI."""

import pytest

from atc.core.errors import AuthFailed, CredentialsExpired, ProviderError
from atc.core.providers.mwaa import MwaaProvider


class _FakeBoto:
    def __init__(self, version="3.1.0", mode="PUBLIC_ONLY"):
        self.version, self.mode = version, mode
        self.calls = []

    def get_environment(self, Name):
        self.calls.append("get_environment")
        return {"Environment": {"AirflowVersion": self.version,
                                "WebserverAccessMode": self.mode,
                                "WebserverUrl": "host.example",
                                "Status": "AVAILABLE"}}


def _provider(version="3.1.0", mode="PUBLIC_ONLY"):
    p = MwaaProvider(environment="env-x", region="ap-southeast-2", aws_profile="prof")
    p._mwaa = _FakeBoto(version, mode)
    return p


def test_airflow_2_environment_is_refused_with_its_version_named():
    """Regression: an Airflow 2 environment used to surface as a bare 404 from the
    Airflow 3 login path, which points the reader at the wrong problem entirely."""
    p = _provider(version="2.11.2")
    with pytest.raises(ProviderError) as e:
        p.list_all_dag_ids()
    assert "2.11.2" in str(e.value)
    assert "Airflow 3" in str(e.value)


def test_connection_bar_reports_version_and_access_mode_without_the_airflow_api():
    """describe() must work even when the Airflow API itself is unreachable - the
    facts come from the AWS control plane, not from the webserver."""
    info = _provider(version="2.11.2", mode="PRIVATE_ONLY").describe()
    assert info.airflow_version == "2.11.2"
    assert "private" in info.hops


def test_environment_facts_are_fetched_once():
    p = _provider()
    p.describe(); p.describe(); p._facts()
    assert p._mwaa.calls == ["get_environment"]


@pytest.mark.parametrize("code,expected,needle", [
    ("ExpiredTokenException", CredentialsExpired, "saml2aws login --profile prof"),
    ("AccessDeniedException", AuthFailed, "airflow:InvokeRestApi"),
    ("ResourceNotFoundException", ProviderError, "aws mwaa list-environments"),
])
def test_aws_errors_become_actionable_instructions(code, expected, needle):
    from botocore.exceptions import ClientError

    p = MwaaProvider(environment="env-x", region="ap-southeast-2", aws_profile="prof")
    err = ClientError({"Error": {"Code": code, "Message": "nope"}}, "GetEnvironment")
    wrapped = p._wrap_aws(err)
    assert isinstance(wrapped, expected)
    assert needle in str(wrapped)
