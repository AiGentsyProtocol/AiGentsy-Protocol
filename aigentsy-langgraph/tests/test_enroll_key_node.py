"""enroll_key_node — non-custodial Ed25519 enrollment.

The load-bearing checks:
  * the wire body carries the PUBLIC half only;
  * the private half is on the resulting SigningKeypair object (which
    lives only in-process unless the caller saves it explicitly);
  * the body is screened by _assert_no_private_material before send;
  * the [signed] extra is required — missing cryptography gives an
    actionable error message.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
import tempfile

import pytest

from aigentsy_langgraph import enroll_key_node
from aigentsy_langgraph.keypair import (
    FORBIDDEN_PRIVATE_KEY_FIELDS,
    SigningKeypair,
)


CRYPTOGRAPHY_AVAILABLE = True
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: F401
        Ed25519PrivateKey,
    )
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_enroll_requires_agent_id_and_api_key():
    with pytest.raises(ValueError, match="agent_id is required"):
        run(enroll_key_node({"api_key": "k"}))
    with pytest.raises(ValueError, match="api_key is required"):
        run(enroll_key_node({"agent_id": "a"}))


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_enroll_happy_path_returns_keypair_and_key_id(mock_backend):
    captured = {}

    def handler(method, path, body):
        if path == "/actor/enroll-key":
            captured["body"] = body
            captured["headers"] = "X-API-Key"  # captured by transport
            return 200, {"ok": True, "key_id": "key_abc123",
                          "public_key_base64": body["public_key_base64"]}
        return 404, {"detail": "x"}

    mock_backend.set_handler(handler)
    out = run(enroll_key_node({
        "agent_id": "agent_test_X",
        "api_key": "real_key_X",
        "print_keypair_notice": False,
    }))

    assert out["signing_mode"] == "enrolled_locally"
    assert out["key_id"] == "key_abc123"
    assert isinstance(out["keypair"], SigningKeypair)
    assert out["keypair"].algorithm == "Ed25519"
    assert out["public_key_base64"]

    # ── WIRE-LEVEL INVARIANTS ──
    body = captured["body"]
    # 1. Public half present in the body
    assert body["public_key_base64"]
    # 2. Body has no private-key-shaped fields (recursive)
    serialized = json.dumps(body)
    for forbidden in FORBIDDEN_PRIVATE_KEY_FIELDS:
        assert forbidden not in serialized, (
            f"FORBIDDEN field {forbidden!r} appeared in wire body: "
            f"{body}"
        )
    # 3. The private key value MUST NOT appear anywhere in the body
    assert out["keypair"].private_key_base64 not in serialized, (
        "private key half found in wire body — non-custodial violation"
    )


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_enroll_with_keypair_path_saves_0600(mock_backend):
    mock_backend.set_handler(lambda m, p, b: (
        200, {"ok": True, "key_id": "key_X",
              "public_key_base64": b.get("public_key_base64", "")},
    ))
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "agent_test.json")
        out = run(enroll_key_node({
            "agent_id": "agent_X", "api_key": "k",
            "keypair_path": path, "print_keypair_notice": False,
        }))
        assert out["keypair_path"] == os.path.realpath(path)
        assert os.path.exists(path)
        if os.name == "posix":
            mode = stat.S_IMODE(os.stat(path).st_mode)
            assert mode & 0o077 == 0, (
                f"file perms {oct(mode)} leak access beyond owner"
            )
        # The saved file has BOTH halves (it's the user's filesystem,
        # they hold the key) — verify load_from_file restores them.
        loaded = SigningKeypair.load_from_file(path)
        assert loaded.public_key_base64 == out["keypair"].public_key_base64


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_enroll_failure_returns_structured_error(mock_backend):
    mock_backend.set_handler(lambda m, p, b: (
        401, {"detail": "Invalid API key"}
    ))
    out = run(enroll_key_node({
        "agent_id": "agent_X", "api_key": "wrong_key",
        "print_keypair_notice": False,
    }))
    assert out["ok"] is False
    assert out["error"] == "enrollment_failed"
    assert out["signing_mode"] == "enrollment_failed"
    assert "401" in out["detail"] or "Invalid" in out["detail"]


def test_enroll_without_cryptography_actionable_error(
    monkeypatch, mock_backend,
):
    """Plain install (no [signed] extra) → enroll_key_node fails with
    a clear hint, not a swallowed traceback."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("cryptography"):
            raise ImportError("no cryptography in plain install")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="signed"):
        run(enroll_key_node({"agent_id": "a", "api_key": "k"}))
