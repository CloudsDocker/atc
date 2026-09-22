"""MWAA provider. Two transports, auto-selected.

  A. mwaa:InvokeRestApi  - AWS API endpoint proxies to the webserver server-side.
                           No token exchange. 10s hard timeout, 6MB response cap.
  B. CreateWebLoginToken - exchange for a web token, POST it to the webserver, use
                           the returned cookie as a Bearer. Needs the webserver
                           hostname to be reachable from here, so it dies on a
                           PRIVATE_ONLY environment outside the VPC.

Measured 2026-09-22 against a real environment:
  - WebserverAccessMode was PUBLIC_ONLY, and the webserver answered from a laptop,
    so B's network requirement was met.
  - A failed with `AccessDeniedException: No Airflow role granted in IAM` - an IAM
    gap, not a network one. It needs airflow:InvokeRestApi on the environment's
    Airflow role ARN.
  - B reached the webserver but 404'd, because that environment runs Airflow 2.11.2
    and /pluginsv2/aws_mwaa/login is the Airflow 3 path.
Whether A works against a PRIVATE_ONLY webserver is therefore still untested.
"""

from __future__ import annotations

import time

import httpx

from ..errors import (AtcError, AuthFailed, CredentialsExpired, NotReachable,
                      ProviderError)
from ..models import ConnectionInfo
from ..provider import RestApiProvider

_EXPIRED_CODES = {
    "ExpiredToken", "ExpiredTokenException", "RequestExpired",
    "InvalidClientTokenId", "UnrecognizedClientException",
}


class MwaaProvider(RestApiProvider):
    def __init__(self, *, environment: str, region: str, aws_profile: str | None = None,
                 strategy: str = "auto", readonly: bool = False, timeout: float = 20.0):
        self.environment = environment
        self.region = region
        self.aws_profile = aws_profile
        self.strategy = strategy
        self.readonly = readonly
        self.timeout = timeout

        self._mwaa = None
        self._active: str | None = None if strategy == "auto" else strategy
        self._client = httpx.Client(timeout=timeout, follow_redirects=False)
        self._web_host: str | None = None
        self._web_token: str | None = None
        self._web_token_exp: float = 0.0
        self._last_latency_ms: int | None = None
        self._env_facts: dict | None = None

    # --- aws ------------------------------------------------------------
    def _boto(self):
        if self._mwaa is None:
            import boto3           # imported lazily so --fake needs no AWS at all
            session = boto3.Session(profile_name=self.aws_profile, region_name=self.region)
            self._mwaa = session.client("mwaa")
        return self._mwaa

    def _wrap_aws(self, e: Exception) -> Exception:
        from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound

        hint = f"saml2aws login --profile {self.aws_profile}" if self.aws_profile else "aws sso login"
        if isinstance(e, ProfileNotFound):
            return CredentialsExpired(f"AWS profile {self.aws_profile!r} is not configured")
        if isinstance(e, NoCredentialsError):
            return CredentialsExpired(f"no AWS credentials - run: {hint}")
        if isinstance(e, ClientError):
            code = e.response.get("Error", {}).get("Code", "")
            if code in _EXPIRED_CODES:
                return CredentialsExpired(f"AWS credentials expired - run: {hint}")
            if code in ("AccessDeniedException", "AccessDenied"):
                return AuthFailed(
                    f"access denied on MWAA {self.environment} - the IAM role needs "
                    f"airflow:InvokeRestApi / airflow:CreateWebLoginToken on "
                    f"arn:aws:airflow:{self.region}:*:role/{self.environment}/Admin")
            if code == "ResourceNotFoundException":
                return ProviderError(
                    f"MWAA environment {self.environment!r} not found in {self.region} "
                    f"- list the real names with: aws mwaa list-environments "
                    f"--profile {self.aws_profile} --region {self.region}")
            return ProviderError(f"MWAA {code}: {e.response.get('Error', {}).get('Message', e)}")
        return ProviderError(str(e))

    def _facts(self) -> dict:
        """`get_environment` is one cheap call that answers the two questions that
        otherwise cost an afternoon of debugging: which Airflow version this is,
        and whether the webserver is reachable from outside the VPC at all."""
        if self._env_facts is None:
            try:
                env = self._boto().get_environment(Name=self.environment)["Environment"]
            except Exception as e:
                raise self._wrap_aws(e) from e
            self._env_facts = {
                "version": env.get("AirflowVersion", "?"),
                "access_mode": env.get("WebserverAccessMode", "?"),
                "hostname": env.get("WebserverUrl", ""),
                "status": env.get("Status", "?"),
            }
        return self._env_facts

    def _guard_version(self) -> None:
        """Fail with the actual reason rather than letting an Airflow 2 environment
        surface as a 404 on an Airflow 3 login path."""
        version = self._facts()["version"]
        if version.startswith("2."):
            raise ProviderError(
                f"MWAA {self.environment} runs Airflow {version}; atc speaks the "
                f"Airflow 3 REST API (/api/v2) only. Point this profile at an "
                f"Airflow 3 environment.")

    # --- strategy A ------------------------------------------------------
    def _via_invoke(self, method, path, params, json):
        kwargs = {"Name": self.environment, "Path": path, "Method": method.upper()}
        if params:
            kwargs["QueryParameters"] = {k: str(v) for k, v in params.items()}
        if json is not None:
            kwargs["Body"] = json
        try:
            resp = self._boto().invoke_rest_api(**kwargs)
        except Exception as e:
            raise self._wrap_aws(e) from e
        status = resp.get("RestApiStatusCode", 200)
        if status == 404:
            raise ProviderError(f"not found: {path}")
        if status >= 400:
            raise ProviderError(f"{method} {path} -> {status}: {resp.get('RestApiResponse')}")
        return resp.get("RestApiResponse") or {}

    # --- strategy B ------------------------------------------------------
    def _ensure_web_session(self) -> tuple[str, str]:
        if self._web_token and time.time() < self._web_token_exp:
            return self._web_host, self._web_token
        try:
            tok = self._boto().create_web_login_token(Name=self.environment)
        except Exception as e:
            raise self._wrap_aws(e) from e

        host = tok["WebServerHostname"]
        # Airflow 3 moved the login path and renamed the cookie; both differ from v2.
        try:
            resp = self._client.post(f"https://{host}/pluginsv2/aws_mwaa/login",
                                     data={"token": tok["WebToken"]})
        except httpx.TransportError as e:
            raise NotReachable(
                f"cannot reach the MWAA webserver {host} - this is what a PRIVATE_ONLY "
                f"webserver looks like from outside the VPC. Check with: aws mwaa "
                f"get-environment --name {self.environment} --query "
                f"Environment.WebserverAccessMode ({e})") from e

        session_token = resp.cookies.get("_token") or resp.cookies.get("session")
        if not session_token:
            raise AuthFailed(
                f"MWAA login returned no session cookie ({resp.status_code}) on "
                f"Airflow {self._facts()['version']} - expected the Airflow 3 login "
                f"path /pluginsv2/aws_mwaa/login to exist")
        self._web_host = host
        self._web_token = session_token
        self._web_token_exp = time.time() + 11 * 3600      # session lives 12h
        return host, session_token

    def _via_web(self, method, path, params, json):
        host, token = self._ensure_web_session()
        try:
            resp = self._client.request(
                method, f"https://{host}{path}", params=params, json=json,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        except httpx.TransportError as e:
            raise NotReachable(f"cannot reach {host}: {e}") from e
        if resp.status_code == 404:
            raise ProviderError(f"not found: {path}")
        if resp.status_code in (401, 403):
            self._web_token = None
            raise AuthFailed(f"MWAA rejected {method} {path} ({resp.status_code})")
        if resp.status_code >= 400:
            raise ProviderError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    # --- transport -------------------------------------------------------
    def _request(self, method, path, *, params=None, json=None):
        self._guard_version()
        started = time.perf_counter()
        try:
            if self._active == "invoke_rest_api":
                return self._via_invoke(method, path, params, json)
            if self._active == "web_login_token":
                return self._via_web(method, path, params, json)

            # auto: probe A once, remember whichever answers
            try:
                out = self._via_invoke(method, path, params, json)
                self._active = "invoke_rest_api"
                return out
            except CredentialsExpired:
                raise                     # re-auth is the fix; B will not help
            except (AuthFailed, NotReachable, ProviderError):
                out = self._via_web(method, path, params, json)
                self._active = "web_login_token"
                return out
        finally:
            self._last_latency_ms = int((time.perf_counter() - started) * 1000)

    def describe(self) -> ConnectionInfo:
        # the version comes from AWS, not from the Airflow API - so the bar still
        # tells you what you are pointed at even when the API itself is unreachable
        try:
            facts = self._facts()
            version, mode = facts["version"], facts["access_mode"]
        except AtcError:
            version, mode = "?", "?"
        return ConnectionInfo(
            kind="mwaa",
            hops=[self.aws_profile or "default", self.environment,
                  mode.lower().replace("_only", ""), self._active or "probing"],
            airflow_version=version,
            latency_ms=self._last_latency_ms,
            readonly=self.readonly,
        )

    def close(self) -> None:
        self._client.close()
