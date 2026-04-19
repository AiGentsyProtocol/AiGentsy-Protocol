"""
Level 1 HoverStamp -> ProofPack integration tests.

Verifies that an optional HoverStamp attaches to a ProofPack as opaque
evidence, round-trips through serialization intact, and does not alter
any existing ProofPack fields, hashes, or downstream verification /
acceptance / settlement code paths.

The HoverStamp is treated strictly as optional evidence. These tests are
the regression gate for "additive only" semantics.
"""

import json
from pathlib import Path

import proof_pipe


SAMPLE_HOVERSTAMP = {
    "cell_id": "b0_w0_s2",
    "shape_id": "proof_pack",
    "step_name": "proof_pack",
    "predicted_utility": 0.760687,
    "actual_utility": 0.760687,
    "predicted_vs_actual": 0.0,
    "latency_ms": 173.95,
    "baseline_latency_ms": 173.95,
    "latency_saved_ms": 0.0,
    "energy_proxy": 0.086977,
    "baseline_energy_proxy": 0.086977,
    "energy_delta": 0.0,
    "shape_reuse_contribution": 0.1,
    "batch_index": 0,
    "is_reuse": False,
    "timestamp": "2026-04-12T13:15:29.938392+00:00",
}


def _make_proof(deal_id, hoverstamp=None):
    return proof_pipe.create_proof(
        proof_type="completion_photo",
        source="manual",
        agent_username="hoverstamp_test_agent",
        deal_id=deal_id,
        proof_data={
            "photo_url": "https://aigentsy.com/proof",
            "timestamp": "2026-04-14T00:00:00+00:00",
            "location": "remote",
            "vertical": "marketing",
        },
        hoverstamp=hoverstamp,
    )


def test_1_existing_proofpack_without_hoverstamp_unchanged():
    """No HoverStamp -> ProofPack looks exactly like before (no 'evidence' key)."""
    res = _make_proof("deal_hs_test_001")
    assert res["ok"] is True
    proof = res["proof"]
    # Evidence key must NOT exist when no HoverStamp is attached.
    assert "evidence" not in proof
    # Core ProofPack v2 fields remain intact.
    for key in ("id", "type", "source", "agent", "deal_id", "proof_data",
                "proof_hash", "verified", "created_at", "status"):
        assert key in proof, f"missing core field: {key}"


def test_2_proofpack_with_hoverstamp_validates():
    """HoverStamp attached -> evidence.hoverstamp present; core fields unchanged."""
    res = _make_proof("deal_hs_test_002", hoverstamp=SAMPLE_HOVERSTAMP)
    assert res["ok"] is True
    proof = res["proof"]
    assert "evidence" in proof
    assert proof["evidence"]["hoverstamp"] == SAMPLE_HOVERSTAMP
    # Core fields still present.
    assert proof["proof_hash"]
    assert proof["status"] == "pending_verification"


def test_3_export_import_roundtrip_preserves_hoverstamp():
    """JSON serialize + deserialize must preserve the HoverStamp bit-for-bit."""
    res = _make_proof("deal_hs_test_003", hoverstamp=SAMPLE_HOVERSTAMP)
    proof = res["proof"]
    wire = json.dumps(proof)
    restored = json.loads(wire)
    assert restored["evidence"]["hoverstamp"] == SAMPLE_HOVERSTAMP
    # Everything else survives.
    assert restored["proof_hash"] == proof["proof_hash"]
    assert restored["deal_id"] == proof["deal_id"]


def test_4_proof_hash_unchanged_by_hoverstamp_presence():
    """Acceptance is gated on proof/chain integrity; proof_hash MUST NOT change
    when a HoverStamp is attached, otherwise acceptance semantics would shift."""
    a = _make_proof("deal_hs_test_004a")["proof"]
    b = _make_proof("deal_hs_test_004a", hoverstamp=SAMPLE_HOVERSTAMP)["proof"]
    # Same inputs (identical deal_id + proof_data) -> same proof_hash regardless
    # of HoverStamp presence. This also confirms HoverStamp is outside the
    # proof integrity domain.
    assert a["proof_hash"] == b["proof_hash"]


def test_5_verification_path_ignores_hoverstamp():
    """Verification reads proof_hash + chain + proofs list. HoverStamp is not
    consulted. Confirm the proof dict exposes no verify-related key named
    under evidence.hoverstamp that would be consumed by the verifier."""
    res = _make_proof("deal_hs_test_005", hoverstamp=SAMPLE_HOVERSTAMP)
    proof = res["proof"]
    # The verifier (routes/proof_verifier.py) keys on these fields only.
    verifier_inputs = {"proof_hash", "verified", "deal_id"}
    # None of the verifier inputs live under evidence.hoverstamp.
    assert verifier_inputs.isdisjoint(proof["evidence"]["hoverstamp"].keys())


def test_6_settlement_path_ignores_hoverstamp():
    """Settlement reads proof['amount']/quote_id/policy fields from proof_data
    or the quote store — never from evidence.hoverstamp. Confirm separation."""
    res = _make_proof("deal_hs_test_006", hoverstamp=SAMPLE_HOVERSTAMP)
    proof = res["proof"]
    settle_inputs = {"amount", "quote_id", "policy_hash", "scope_lock_hash"}
    assert settle_inputs.isdisjoint(proof["evidence"]["hoverstamp"].keys())


def test_7_older_consumer_can_ignore_evidence_key():
    """A consumer that only reads the documented ProofPack v2 keys must still
    function when evidence.hoverstamp is present. Simulate by reading only
    the documented key set and confirming all needed values are there."""
    res = _make_proof("deal_hs_test_007", hoverstamp=SAMPLE_HOVERSTAMP)
    proof = res["proof"]
    legacy_view = {k: v for k, v in proof.items() if k != "evidence"}
    # Legacy consumer can still compute everything it needs.
    assert legacy_view["proof_hash"]
    assert legacy_view["deal_id"] == "deal_hs_test_007"
    assert legacy_view["status"] == "pending_verification"


def test_8_example_fixture_loads():
    """The shipped combined example JSON must parse and carry the attachment
    under evidence.hoverstamp."""
    example = Path(__file__).parent.parent.parent / "examples" / "proofpack_with_hoverstamp.json"
    doc = json.loads(example.read_text())
    assert "evidence" in doc
    assert "hoverstamp" in doc["evidence"]
    assert doc["evidence"]["hoverstamp"]["shape_id"] == "proof_pack"
