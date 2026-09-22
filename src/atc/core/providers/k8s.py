"""K8s provider: one long-lived port-forward + a cached JWT, for the whole app session.

Ported from mq-ops/airflow.py, with the lifecycle inverted. That code opens a tunnel
per call, which is right for a stateless MCP tool and fatal for a TUI that refreshes
every few seconds (~2s of tunnel setup per refresh). Here the tunnel is built once and
self-heals; the JWT is renewed 60s before it expires.
"""

from __future__ import annotations

import base64
import binascii
import json
import socket
import subprocess
import time

import httpx

from ..errors import AuthFailed, CredentialsExpired, NotReachable, ProviderError
from ..models import ConnectionInfo, LogChunk
from ..provider import RestApiProvider

_TOKEN_SKEW_S = 60


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _jwt_expiry(token: str) -> float:
    """Read `exp` out of the JWT without verifying it - we only need the clock, and
    the server is the one enforcing validity."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, KeyError, ValueError, binascii.Error):
        return time.time() + 300      # unreadable -> re-auth in 5 minutes


class K8sProvider(RestApiProvider):
    def __init__(self, *, context: str, namespace: str, service: str,
                 port: int = 8080, secret: str = "airflow-secret",
                 secret_key: str = "airflow_admin_password", username: str = "admin",
                 scheduler_deploy: str = "airflow-scheduler-deployment",
                 log_root: str = "/airflow-logs/logs",
                 readonly: bool = False, timeout: float = 15.0):
        self.context = context
        self.namespace = namespace
        self.service = service
        self.port = port
        self.secret = secret
        self.secret_key = secret_key
        self.username = username
        self.scheduler_deploy = scheduler_deploy
        self.log_root = log_root
        self.readonly = readonly
        self.timeout = timeout

        self._proc: subprocess.Popen | None = None
        self._local_port: int | None = None
        self._token: str | None = None
        self._token_exp: float = 0.0
        self._client = httpx.Client(timeout=timeout)
        self._last_latency_ms: int | None = None
        self._version = "?"

    # --- tunnel ---------------------------------------------------------
    def _tunnel_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _ensure_tunnel(self) -> str:
        if self._tunnel_alive():
            return f"http://127.0.0.1:{self._local_port}"

        self._drop_tunnel()
        port = _free_port()
        cmd = [
            "kubectl", "port-forward",
            "--context", self.context,
            "-n", self.namespace,
            f"svc/{self.service}",
            f"{port}:{self.port}",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise NotReachable("kubectl not found on PATH") from None

        deadline = time.time() + 20
        while time.time() < deadline:
            if self._proc.poll() is not None:
                err = (self._proc.stderr.read() or b"").decode(errors="replace").strip()
                self._drop_tunnel()
                raise self._tunnel_error(err)
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    self._local_port = port
                    # a fresh tunnel means any cached token is bound to a dead socket
                    self._token = None
                    return f"http://127.0.0.1:{port}"
            except OSError:
                time.sleep(0.25)

        self._drop_tunnel()
        raise NotReachable(
            f"port-forward to {self.context}/{self.namespace} did not come up in 20s")

    def _tunnel_error(self, stderr: str) -> Exception:
        low = stderr.lower()
        if "credentials" in low or "unauthorized" in low or "expired" in low:
            return CredentialsExpired(
                f"kubectl cannot authenticate to {self.context} - refresh your cluster "
                f"credentials, then retry ({stderr})")
        if "context" in low and "does not exist" in low:
            return ProviderError(f"kubectl context {self.context!r} does not exist")
        return NotReachable(f"port-forward failed: {stderr or 'no output'}")

    def _drop_tunnel(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._local_port = None
        self._token = None

    # --- auth -----------------------------------------------------------
    def _kubectl(self, args: list[str], timeout: float = 30) -> str:
        proc = subprocess.run(
            ["kubectl", "--context", self.context, "-n", self.namespace, *args],
            capture_output=True, timeout=timeout)
        if proc.returncode != 0:
            raise self._tunnel_error(proc.stderr.decode(errors="replace").strip())
        return proc.stdout.decode(errors="replace")

    def _admin_password(self) -> str:
        raw = self._kubectl(
            ["get", "secret", self.secret, "-o",
             f"jsonpath={{.data.{self.secret_key}}}"]).strip()
        if not raw:
            raise AuthFailed(
                f"secret {self.secret}/{self.secret_key} is empty in {self.namespace}")
        return base64.b64decode(raw).decode()

    def _ensure_token(self, base_url: str) -> str:
        if self._token and time.time() < self._token_exp - _TOKEN_SKEW_S:
            return self._token
        resp = self._client.post(
            f"{base_url}/auth/token",
            json={"username": self.username, "password": self._admin_password()})
        if resp.status_code in (401, 403):
            raise AuthFailed(f"Airflow rejected the admin login ({resp.status_code})")
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        self._token_exp = _jwt_expiry(self._token)
        return self._token

    # --- transport ------------------------------------------------------
    def _request(self, method, path, *, params=None, json=None):
        for attempt in (1, 2):
            base_url = self._ensure_tunnel()
            token = self._ensure_token(base_url)
            started = time.perf_counter()
            try:
                resp = self._client.request(
                    method, f"{base_url}{path}", params=params, json=json,
                    headers={"Authorization": f"Bearer {token}",
                             "Accept": "application/json"})
            except httpx.TransportError:
                # tunnel died mid-flight; rebuild once, then give up honestly
                self._drop_tunnel()
                if attempt == 2:
                    raise NotReachable(
                        f"lost the port-forward to {self.namespace} and could not "
                        f"re-establish it") from None
                continue

            self._last_latency_ms = int((time.perf_counter() - started) * 1000)
            if resp.status_code == 401 and attempt == 1:
                self._token = None      # token expired early; one clean retry
                continue
            return self._decode(resp, method, path)

    def _decode(self, resp: httpx.Response, method: str, path: str):
        if resp.status_code == 404:
            raise ProviderError(f"not found: {path}")
        if resp.status_code in (401, 403):
            raise AuthFailed(f"Airflow rejected {method} {path} ({resp.status_code})")
        if resp.status_code >= 400:
            raise ProviderError(
                f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # --- overrides ------------------------------------------------------
    def describe(self) -> ConnectionInfo:
        if self._version == "?":
            try:
                self._version = (self._request("GET", "/api/v2/version") or {}).get(
                    "version", "?")
            except Exception:
                pass
        port = f":{self._local_port}" if self._local_port else "…"
        return ConnectionInfo(
            kind="k8s",
            hops=[self.context, self.namespace, port],
            airflow_version=self._version,
            latency_ms=self._last_latency_ms,
            readonly=self.readonly,
        )

    def task_log(self, dag_id, run_id, task_id, try_number=1) -> LogChunk:
        """API first; fall back to reading the scheduler's log PVC.

        On this cluster the REST log endpoint is unreliable while the file on the PVC
        is not, so the fallback is the difference between a usable log screen and an
        empty one. An empty result from *both* is the real §5.2 signal.
        """
        chunk = super().task_log(dag_id, run_id, task_id, try_number)
        if chunk.text.strip():
            return chunk
        return self._log_from_pvc(dag_id, run_id, task_id, try_number)

    def _log_from_pvc(self, dag_id, run_id, task_id, try_number) -> LogChunk:
        path = (f"{self.log_root}/dag_id={dag_id}/run_id={run_id}"
                f"/task_id={task_id}/attempt={try_number}.log")
        try:
            out = self._kubectl(
                ["exec", f"deploy/{self.scheduler_deploy}", "--", "sh", "-c",
                 f'[ -f "{path}" ] && cat "{path}" || true'], timeout=45)
        except Exception as e:
            return LogChunk(text="", source="empty", note=f"PVC read failed: {e}")
        if out.strip():
            return LogChunk(text=out, source="pvc")
        return LogChunk(text="", source="empty",
                        note=f"no log file on the scheduler PVC either ({path})")

    def close(self) -> None:
        self._drop_tunnel()
        self._client.close()
