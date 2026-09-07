"""Shared test fixtures for the aigentsy-langgraph 0.3.0 test suite.

All tests are hermetic — no network. Real HTTP traffic is intercepted
by httpx.MockTransport. The mock transport stands in for the live
backend and records every outgoing request so tests can assert what
the adapter actually sent (especially the wire-level non-custodial
guard: nothing private-key-shaped ever leaves the process).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

import httpx
import pytest

import aigentsy_langgraph
from aigentsy_langgraph.client import AsyncAiGentsyClient


class MockBackend:
    """Records every request and replies via a user-supplied handler.

    The handler is a callable ``(method, path, body) -> (status_code,
    response_body_dict)``. Tests register a handler that simulates the
    live backend's response shapes (200/409/404/422/500). The captured
    request log is inspectable for wire-level assertions."""

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        self._handler: Callable[[str, str, Dict], Any] = self._default

    def _default(self, method, path, body):
        return 404, {"detail": f"no handler for {method} {path}"}

    def set_handler(self, handler):
        self._handler = handler

    def transport_handler(self, request: httpx.Request) -> httpx.Response:
        body: Dict[str, Any] = {}
        if request.content:
            try:
                body = json.loads(request.content.decode("utf-8"))
            except Exception:
                body = {"_raw_text": request.content.decode("utf-8",
                                                            errors="replace")}
        self.requests.append({
            "method": request.method,
            "path": request.url.path,
            "headers": dict(request.headers),
            "body": body,
        })
        status, resp = self._handler(request.method, request.url.path, body)
        return httpx.Response(status, json=resp)

    @property
    def sent_bodies(self) -> List[Dict[str, Any]]:
        return [r["body"] for r in self.requests]


@pytest.fixture
def mock_backend(monkeypatch):
    """Patches AsyncAiGentsyClient to use a MockTransport — every node
    that constructs its own client in the test ends up routed here.

    Returns a MockBackend instance the test can configure."""
    backend = MockBackend()
    orig_init = AsyncAiGentsyClient.__init__

    def patched_init(self, base_url="https://example.test",
                     api_key=None, **kwargs):
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self._base,
            transport=httpx.MockTransport(backend.transport_handler),
            timeout=10.0,
        )

    monkeypatch.setattr(AsyncAiGentsyClient, "__init__", patched_init)
    yield backend
    monkeypatch.setattr(AsyncAiGentsyClient, "__init__", orig_init)
