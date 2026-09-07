"""outcome_receipt_node — the three response states (200/409/404) all
surface as structured outputs, no exceptions on the empty-state path."""
from __future__ import annotations

import asyncio

import pytest

from aigentsy_langgraph import outcome_receipt_node


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _signed_receipt_envelope():
    return {
        "ok": True,
        "receipt": {
            "receipt_id": "or_test_id",
            "issued_at": "2026-06-04T18:00:00.000Z",
            "issuer": "aigentsy_settlement_protocol",
            "deal_id": "deal_X",
            "buyer_id": "agent_buyer_99",          # = payer (Stage-7-C)
            "seller_id": "agent_seller_11",        # = performer
            "amount": {"currency": "USD", "net": 100.0,
                        "gross": 105.0, "fees": 5.0},
            "proof_reference": {"proof_hash": "sha256_xxxxxxx"},
            "verification_status": "verified",
            "acceptance_status": "accepted",
            "governed_commercial_proof": True,
            "policy_required_governed_commercial_proof": True,
            "outcome_event": {"event_id": "e1",
                               "event_type": "OUTCOME_RECORDED",
                               "timestamp": "2026-06-04T17:59:00Z",
                               "tx_id": "tx_abc"},
            "settlement_type": "single-party",
        },
        "payload_hash": "ph_xyz", "signature": "sig_xyz",
        "algorithm": "Ed25519", "key_id": "aigentsy_log_signer_v1",
        "public_key_base64": "pub_b64",
        "verify_url": "https://aigentsy-ame-runtime.onrender.com/"
                       "protocol/merkle/public-key",
    }


def test_outcome_receipt_requires_deal_id():
    with pytest.raises(ValueError, match="deal_id is required"):
        run(outcome_receipt_node({}))


def test_outcome_receipt_200_renders_full_envelope(mock_backend):
    env = _signed_receipt_envelope()
    mock_backend.set_handler(lambda m, p, b: (200, env))
    out = run(outcome_receipt_node({"deal_id": "deal_X"}))

    assert out["ok"] is True
    assert out["receipt_state"] == "present"
    assert out["outcome_receipt"]["buyer_id"] == "agent_buyer_99"
    assert out["outcome_receipt"]["seller_id"] == "agent_seller_11"
    # Stage-7-C labeling: the buyer is the payer, NOT the performer.
    assert out["outcome_receipt"]["buyer_id"] != \
        out["outcome_receipt"]["seller_id"]
    assert out["receipt_signature"]["algorithm"] == "Ed25519"
    assert out["receipt_signature"]["key_id"] == "aigentsy_log_signer_v1"
    assert out["verify_url"].endswith("/protocol/merkle/public-key")


def test_outcome_receipt_409_clean_empty_state(mock_backend):
    """409 outcome_not_recorded is a NORMAL state, not an error."""
    body = {
        "detail": {
            "error": "outcome_not_recorded",
            "deal_id": "deal_X",
            "current_state": "PROOF_READY",
        }
    }
    mock_backend.set_handler(lambda m, p, b: (409, body))
    out = run(outcome_receipt_node({"deal_id": "deal_X"}))

    assert out["ok"] is True, (
        "409 outcome_not_recorded is a valid state, not an error"
    )
    assert out["receipt_state"] == "not_yet"
    assert out["current_state"] == "PROOF_READY"
    assert "outcome_receipt" not in out, (
        "no receipt should appear in the not_yet envelope"
    )


def test_outcome_receipt_404_deal_not_found(mock_backend):
    body = {"detail": {"error": "deal_not_found", "deal_id": "nope"}}
    mock_backend.set_handler(lambda m, p, b: (404, body))
    out = run(outcome_receipt_node({"deal_id": "nope"}))
    assert out["ok"] is False
    assert out["receipt_state"] == "deal_not_found"


def test_outcome_receipt_422_surfaces_structured_error(mock_backend):
    mock_backend.set_handler(lambda m, p, b: (
        422, {"detail": {"error": "lifecycle_unavailable"}}
    ))
    out = run(outcome_receipt_node({"deal_id": "deal_X"}))
    assert out["ok"] is False
    assert out["receipt_state"] == "unavailable"
    assert out["status_code"] == 422


def test_outcome_receipt_500_surfaced(mock_backend):
    mock_backend.set_handler(lambda m, p, b: (
        500, {"detail": "receipt_signing_unavailable"}
    ))
    out = run(outcome_receipt_node({"deal_id": "deal_X"}))
    assert out["ok"] is False
    assert out["receipt_state"] == "unavailable"
    assert out["status_code"] == 500
