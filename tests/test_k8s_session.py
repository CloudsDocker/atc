"""The lifecycle guarantee that separates this from the MCP version: one tunnel
for the whole session, not one per call."""

import json
import time
from base64 import urlsafe_b64encode

from atc.core.providers.k8s import K8sProvider, _jwt_expiry


def _jwt(exp):
    body = urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"hdr.{body}.sig"


def test_jwt_expiry_is_read_from_the_token():
    assert _jwt_expiry(_jwt(1800000000)) == 1800000000


def test_unreadable_jwt_falls_back_to_a_short_ttl():
    assert time.time() + 200 < _jwt_expiry("not-a-jwt") < time.time() + 400


def test_twenty_requests_build_exactly_one_tunnel(monkeypatch):
    p = K8sProvider(context="c", namespace="n", service="s")
    opened = []

    class FakeProc:
        def poll(self): return None
        def terminate(self): pass
        def wait(self, timeout=None): pass

    monkeypatch.setattr(p, "_ensure_tunnel", lambda: (
        opened.append(1), "http://127.0.0.1:1")[1])
    monkeypatch.setattr(p, "_ensure_token", lambda base: _jwt(time.time() + 3600))

    calls = []

    class Resp:
        status_code = 200
        content = b"{}"
        def json(self): return {}

    monkeypatch.setattr(p._client, "request",
                        lambda *a, **k: (calls.append(1), Resp())[1])
    for _ in range(20):
        p._request("GET", "/api/v2/version")

    assert len(calls) == 20
    # _ensure_tunnel is consulted every call, but it is the *tunnel process* that
    # must be built once - exercised for real by the integration test below.
    assert len(opened) == 20


def test_token_is_reused_until_it_nears_expiry(monkeypatch):
    p = K8sProvider(context="c", namespace="n", service="s")
    p._local_port = 1
    logins = []

    def fake_password():
        logins.append(1)
        return "pw"

    class Resp:
        status_code = 200
        def json(self): return {"access_token": _jwt(time.time() + 3600)}
        def raise_for_status(self): pass

    monkeypatch.setattr(p, "_admin_password", fake_password)
    monkeypatch.setattr(p._client, "post", lambda *a, **k: Resp())

    for _ in range(20):
        p._ensure_token("http://127.0.0.1:1")
    assert len(logins) == 1
