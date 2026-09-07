"""accept_node / reject_node — attribution AND signed paths.

Covers the rigid prompt's invariants:

  * happy attribution-only: canonical ACCEPTED/REJECTED produced,
    signing_mode="attribution_only", reason verbatim;
  * happy signed: keypair-holding actor sends prepare→sign→submit,
    backend returns the appended signed event, signing_mode="signed";
  * Option-3 block: signed-path 4xx → structured backend_error,
    NEVER swallowed into ok=true;
  * reject reason REQUIRED (raises ValueError on empty);
  * all of 401/403/404/409/422/500 surface as structured envelopes;
  * tenant scoping: the api_key flows through unchanged on every call.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest

from aigentsy_langgraph import accept_node, reject_node
from aigentsy_langgraph.nodes import _decide_via_node  # noqa: F401


CRYPTOGRAPHY_AVAILABLE = True
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey,
    )
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


# ── Backend response builders ─────────────────────────────────────────


def _accept_response(acceptance_id="acc_test_X", reason=""):
    return {
        "ok": True,
        "acceptance": {
            "acceptance_id": acceptance_id, "deal_id": "deal_X",
            "status": "accepted", "decision": "accept",
            "reason": reason, "checks_passed": [], "checks_failed": [],
            "downstream_action": "settle",
            "downstream_triggered": True,
        },
        "downstream_triggered": True,
    }


def _reject_response(acceptance_id="acc_test_X", reason=""):
    return {
        "ok": True,
        "acceptance": {
            "acceptance_id": acceptance_id, "deal_id": "deal_X",
            "status": "rejected", "decision": "reject",
            "reason": reason, "checks_passed": [], "checks_failed": [],
        },
    }


def _existing_acceptance(acceptance_id="acc_existing_555"):
    return lambda method, path, body: (
        200,
        {"ok": True, "acceptance": {"acceptance_id": acceptance_id,
                                     "deal_id": "deal_X",
                                     "state": "pending"}},
    )


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Required-arg validation ──────────────────────────────────────────


def test_accept_requires_deal_id():
    with pytest.raises(ValueError, match="deal_id is required"):
        run(accept_node({"api_key": "k"}))


def test_accept_requires_api_key():
    with pytest.raises(ValueError, match="api_key is required"):
        run(accept_node({"deal_id": "d"}))


def test_reject_requires_deal_id():
    with pytest.raises(ValueError, match="deal_id is required"):
        run(reject_node({"reason": "r", "api_key": "k"}))


def test_reject_requires_reason():
    """The load-bearing reject invariant — reason MUST be supplied."""
    with pytest.raises(ValueError, match="reason is required"):
        run(reject_node({"deal_id": "d", "api_key": "k"}))


def test_reject_requires_api_key():
    with pytest.raises(ValueError, match="api_key is required"):
        run(reject_node({"deal_id": "d", "reason": "r"}))


# ── Attribution-only happy path ──────────────────────────────────────


def test_accept_attribution_happy_path(mock_backend):
    accept_calls = []

    def handler(method, path, body):
        if method == "GET" and path.startswith("/protocol/acceptance/deal/"):
            return 200, {"ok": True,
                          "acceptance": {"acceptance_id": "acc_777",
                                         "deal_id": "deal_X",
                                         "state": "pending"}}
        if path == "/protocol/acceptance/acc_777/accept":
            accept_calls.append(body)
            return 200, _accept_response("acc_777", body.get("reason", ""))
        return 404, {"detail": "unhandled"}

    mock_backend.set_handler(handler)
    out = run(accept_node({
        "deal_id": "deal_X",
        "api_key": "real_buyer_key",
        "reason": "ship it",
    }))

    assert out["ok"] is True
    assert out["decision"] == "accept"
    assert out["acceptance_id"] == "acc_777"
    assert out["reason"] == "ship it"
    assert out["signing_mode"] == "attribution_only"
    assert out["acceptance"]["reason"] == "ship it"
    # The backend body carried the reason verbatim
    assert accept_calls[0]["reason"] == "ship it"
    assert accept_calls[0]["decision"] == "accept"


def test_reject_attribution_happy_path_reason_verbatim(mock_backend):
    body_captured = {}

    def handler(method, path, body):
        if method == "GET" and path.startswith("/protocol/acceptance/deal/"):
            return 200, {"ok": True,
                          "acceptance": {"acceptance_id": "acc_R",
                                         "deal_id": "deal_X",
                                         "state": "pending"}}
        if path == "/protocol/acceptance/acc_R/reject":
            body_captured.update(body)
            return 200, _reject_response("acc_R", body.get("reason", ""))
        return 404, {"detail": "unhandled"}

    mock_backend.set_handler(handler)
    REASON = "scope drift on the deliverable"
    out = run(reject_node({
        "deal_id": "deal_X",
        "api_key": "real_buyer_key",
        "reason": REASON,
    }))

    assert out["ok"] is True
    assert out["decision"] == "reject"
    assert out["reason"] == REASON
    assert out["signing_mode"] == "attribution_only"
    assert out["acceptance"]["reason"] == REASON
    # Wire body carried it verbatim — load-bearing
    assert body_captured["reason"] == REASON
    assert body_captured["decision"] == "reject"


def test_auto_submit_when_no_acceptance(mock_backend):
    ops = []

    def handler(method, path, body):
        ops.append((method, path))
        if method == "GET" and path.startswith("/protocol/acceptance/deal/"):
            return 200, {"ok": True, "acceptance": None,
                          "message": "No acceptance gate for this deal"}
        if path == "/protocol/acceptance/submit":
            return 200, {"ok": True,
                          "acceptance": {"acceptance_id": "acc_NEW",
                                         "deal_id": "deal_X",
                                         "state": "pending"}}
        if path == "/protocol/acceptance/acc_NEW/accept":
            return 200, _accept_response("acc_NEW", body.get("reason", ""))
        return 404, {"detail": "unhandled"}

    mock_backend.set_handler(handler)
    out = run(accept_node({"deal_id": "deal_X", "api_key": "k",
                           "reason": "ok"}))
    assert out["ok"] is True
    assert out["acceptance_id"] == "acc_NEW"
    # Exactly three calls in the right order
    paths = [op[1] for op in ops]
    assert paths == [
        "/protocol/acceptance/deal/deal_X",
        "/protocol/acceptance/submit",
        "/protocol/acceptance/acc_NEW/accept",
    ]


def test_auto_submit_false_returns_clean_envelope(mock_backend):
    def handler(method, path, body):
        if method == "GET" and path.startswith("/protocol/acceptance/deal/"):
            return 200, {"ok": True, "acceptance": None}
        return 404, {"detail": "unhandled"}

    mock_backend.set_handler(handler)
    out = run(accept_node({
        "deal_id": "deal_X", "api_key": "k", "reason": "r",
        "auto_submit": False,
    }))
    assert out["ok"] is False
    assert out["error"] == "no_pending_acceptance"
    assert "auto_submit=True" in out["detail"]


def test_api_key_flows_to_every_backend_call_unchanged(mock_backend):
    mock_backend.set_handler(_existing_acceptance("acc_X"))

    def handler(method, path, body):
        if method == "GET" and path.startswith("/protocol/acceptance/deal/"):
            return 200, {"ok": True,
                          "acceptance": {"acceptance_id": "acc_X",
                                         "state": "pending"}}
        if path == "/protocol/acceptance/acc_X/accept":
            return 200, _accept_response("acc_X")
        return 404, {"detail": "x"}

    mock_backend.set_handler(handler)
    run(accept_node({"deal_id": "deal_X", "api_key": "key_SPECIFIC_xyz"}))
    # Inspect every recorded request: the accept post must carry the
    # api_key header verbatim. (Lookup is unauthenticated read by
    # design.)
    accept_reqs = [r for r in mock_backend.requests
                   if r["path"] == "/protocol/acceptance/acc_X/accept"]
    assert accept_reqs, "no accept request recorded"
    assert accept_reqs[0]["headers"].get("x-api-key") == "key_SPECIFIC_xyz"


# ── Honest failure surfacing — 401/403/404/409/422/500 ──────────────


@pytest.mark.parametrize("status, body", [
    (401, {"detail": "Invalid API key"}),
    (403, {"detail": "forbidden: api_key does not own this scope"}),
    (404, {"detail": "Acceptance record not found or already decided"}),
    (409, {"detail": "deal_in_invalid_state"}),
    (422, {"detail": "Use /reject for rejection"}),
    (451, {"detail": "option_3_block",
            "reason": "actor has enrolled key; signed path required"}),
    (500, {"detail": "internal_error"}),
])
def test_accept_surfaces_backend_errors_honestly(
    mock_backend, status, body,
):
    def handler(method, path, body_):
        if method == "GET" and path.startswith("/protocol/acceptance/deal/"):
            return 200, {"ok": True,
                          "acceptance": {"acceptance_id": "acc_X",
                                         "state": "pending"}}
        if path == "/protocol/acceptance/acc_X/accept":
            return status, body
        return 500, {"detail": "unhandled"}

    mock_backend.set_handler(handler)
    out = run(accept_node({"deal_id": "deal_X", "api_key": "k",
                           "reason": "ok"}))
    assert out["ok"] is False, (
        f"status {status} was swallowed into ok=true"
    )
    assert out["error"] == "backend_error"
    assert out["status_code"] == status
    assert out["detail"] == body
    assert out["decision"] == "accept"
    assert out["deal_id"] == "deal_X"


def test_reject_403_tenant_failure_surfaced(mock_backend):
    """The G1 binding guard's 403 must come through the MCP-style
    envelope unchanged; the node must not rewrite it as a success."""
    def handler(method, path, body):
        if method == "GET" and path.startswith("/protocol/acceptance/deal/"):
            return 200, {"ok": True,
                          "acceptance": {"acceptance_id": "acc_X",
                                         "state": "pending"}}
        if path == "/protocol/acceptance/acc_X/reject":
            return 403, {"detail": "forbidden"}
        return 500, {"detail": "x"}

    mock_backend.set_handler(handler)
    out = run(reject_node({"deal_id": "deal_X", "api_key": "wrong_key",
                           "reason": "r"}))
    assert out["ok"] is False
    assert out["status_code"] == 403
    assert out["detail"] == {"detail": "forbidden"}
    assert out["decision"] == "reject"


# ── Option-3 signed path ────────────────────────────────────────────


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_signed_accept_round_trip(mock_backend):
    """Keypair-bearing actor → /protocol/event/prepare → local sign
    → /protocol/event/submit → adapter returns the signed event with
    signing_mode='signed'."""
    from aigentsy_langgraph.keypair import SigningKeypair

    kp = SigningKeypair.generate(print_notice=False)
    pub_raw = base64.b64decode(kp.public_key_base64)

    sent_bodies = {}

    def handler(method, path, body):
        if method == "GET" and path.startswith("/protocol/acceptance/deal/"):
            return 200, {"ok": True,
                          "acceptance": {"acceptance_id": "acc_S",
                                         "deal_id": "deal_X",
                                         "state": "pending"}}
        if path == "/protocol/event/prepare":
            sent_bodies["prepare"] = body
            canonical = json.dumps(body, sort_keys=True,
                                    separators=(",", ":")).encode()
            return 200, {
                "ok": True,
                "token": "tok_abc123",
                "canonical_bytes_b64": base64.b64encode(canonical).decode(),
            }
        if path == "/protocol/event/submit":
            sent_bodies["submit"] = body
            # Verify the signature here for full end-to-end correctness.
            canonical = json.dumps(sent_bodies["prepare"], sort_keys=True,
                                    separators=(",", ":")).encode()
            sig_b64 = body["actor_signature"]["signature"]
            sig = base64.b64decode(sig_b64)
            Ed25519PublicKey.from_public_bytes(pub_raw).verify(
                sig, canonical,
            )  # raises if invalid — proves the signature is real
            return 200, {
                "ok": True,
                "event": {
                    "event_id": "evt_signed_001",
                    "event_type": "ACCEPTED",
                    "actor_id": body["actor_signature"]["actor_id"],
                    "actor_signature": body["actor_signature"],
                    "payload": sent_bodies["prepare"]["payload"],
                    "source": "acceptance_gate",
                },
            }
        return 500, {"detail": "unhandled " + path}

    mock_backend.set_handler(handler)
    out = run(accept_node({
        "deal_id": "deal_X",
        "api_key": "real_buyer_key",
        "agent_id": "agent_buyer_001",
        "reason": "signed accept",
        "keypair": kp,
        "key_id": "key_buyer_001",
    }))

    assert out["ok"] is True
    assert out["signing_mode"] == "signed"
    assert "accepted_event" in out
    assert out["accepted_event"]["event_type"] == "ACCEPTED"
    assert out["accepted_event"]["actor_id"] == "agent_buyer_001"
    assert out["accepted_event"]["payload"]["reason"] == "signed accept"
    # The wire body carries ONLY the signature, never the private key.
    assert "private_key_base64" not in json.dumps(sent_bodies["prepare"])
    assert "private_key_base64" not in json.dumps(sent_bodies["submit"])


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_signed_reject_round_trip(mock_backend):
    from aigentsy_langgraph.keypair import SigningKeypair
    kp = SigningKeypair.generate(print_notice=False)

    def handler(method, path, body):
        if method == "GET" and path.startswith("/protocol/acceptance/deal/"):
            return 200, {"ok": True,
                          "acceptance": {"acceptance_id": "acc_SR",
                                         "deal_id": "deal_X",
                                         "state": "pending"}}
        if path == "/protocol/event/prepare":
            canonical = json.dumps(body, sort_keys=True,
                                    separators=(",", ":")).encode()
            return 200, {
                "ok": True, "token": "tok",
                "canonical_bytes_b64": base64.b64encode(canonical).decode(),
            }
        if path == "/protocol/event/submit":
            return 200, {"ok": True, "event": {
                "event_id": "evt_signed_R", "event_type": "REJECTED",
                "actor_id": body["actor_signature"]["actor_id"],
                "actor_signature": body["actor_signature"],
                "payload": {"reason": "tier-2 reject reason"},
            }}
        return 500, {"detail": "unhandled"}

    mock_backend.set_handler(handler)
    out = run(reject_node({
        "deal_id": "deal_X",
        "api_key": "real_reviewer_key",
        "agent_id": "agent_reviewer_002",
        "reason": "tier-2 reject reason",
        "keypair": kp,
        "key_id": "key_reviewer_002",
    }))
    assert out["ok"] is True
    assert out["signing_mode"] == "signed"
    assert out["rejected_event"]["event_type"] == "REJECTED"
    assert out["rejected_event"]["payload"]["reason"] == "tier-2 reject reason"


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_option3_block_signed_path_fail_surfaced(mock_backend):
    """Branch 3: keypair present BUT the signed call fails (e.g.
    actor-key mismatch). The structured backend_error MUST come back
    with signing_mode='signed_block'; the adapter must NOT silently
    fall through to attribution-only."""
    from aigentsy_langgraph.keypair import SigningKeypair
    kp = SigningKeypair.generate(print_notice=False)

    def handler(method, path, body):
        if method == "GET" and path.startswith("/protocol/acceptance/deal/"):
            return 200, {"ok": True,
                          "acceptance": {"acceptance_id": "acc_BLOCK",
                                         "state": "pending"}}
        if path == "/protocol/event/prepare":
            return 422, {"detail": "actor_key_mismatch",
                          "reason": "key_id does not match actor_id"}
        return 500, {"detail": "unhandled"}

    mock_backend.set_handler(handler)
    out = run(accept_node({
        "deal_id": "deal_X",
        "api_key": "k",
        "agent_id": "agent_wrong_pair",
        "keypair": kp,
        "key_id": "key_owned_by_someone_else",
    }))
    assert out["ok"] is False
    assert out["error"] == "backend_error"
    assert out["status_code"] == 422
    assert out["signing_mode"] == "signed_block", (
        "Option-3 block MUST carry signing_mode='signed_block' so "
        "consumers can distinguish it from attribution-only failure"
    )
    assert out["detail"] == {"detail": "actor_key_mismatch",
                              "reason": "key_id does not match actor_id"}
