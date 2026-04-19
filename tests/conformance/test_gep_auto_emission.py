"""Governed Economic Proof auto-emission tests.

Verifies the caller-side automatic emission path in the real
/protocol/proof-pack export flow. Tests use proof_pipe.create_proof
directly (same code path as the FastAPI route handler).

Activation model (v1.2+):
    On by default when a hoverstamp is present.
    Set HOVERSTACK_GEP_AUTO_EMIT=0 to opt out.

The emission logic lives in proof_pipe.py create_proof()
— NOT in any HoverStack plane module.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

import proof_pipe
from hoverstack.governed_proof import (
    ALG_ED25519, ALG_HMAC_SHA256, DecisionTranscript,
    build_signed_artifact, verify_embedded_artifact,
    _ed25519_available,
)


_SAMPLE_HOVERSTAMP = {
    "cell_id": "auto_test_c0",
    "shape_id": "contract_review",
    "runtime_name": "vllm",
    "runtime_model": "llama-3.1-8b",
    "runtime_capabilities": {"safe_reuse_enabled": True},
    "risk_class": "low_risk",
    "risk_restrictions_applied": [],
    "recall_mode": "structural_recall",
    "recall_confidence": 0.82,
    "recall_prior_basis": "per_shape_runtime_model",
    "recall_fallback_triggered": True,
    "recall_fallback_reason": "risk_blocked_direct",
    "delta_mode": "tail_only_delta",
    "delta_size_estimate": 0.1,
    "delta_fallback_triggered": False,
    "preservation_prior_basis": "per_shape_runtime_model",
    "carry_cost_decomposition": {
        "kelly_fraction": 0.42, "cache_pressure_factor": 1.0,
    },
    "compute_avoided_estimate": 38.4,
    "decision_rationale": "structural_recall: risk blocked direct",
    "decision_key": "structural_recall|preserve|basis=per_shape_runtime_model",
}


import random as _rng

def _proof_with_hs(hoverstamp=None, governance_attestation=None):
    """Create a proof via proof_pipe (same path as the route handler).
    Uses a random deal_id to avoid idempotency-cache collisions across tests."""
    return proof_pipe.create_proof(
        proof_type="completion_photo",
        source="manual",
        agent_username="auto_emit_test",
        deal_id=f"deal_auto_{_rng.randint(0, 2**64)}",
        proof_data={
            "photo_url": "https://aigentsy.com/proof",
            "timestamp": "2026-04-16T00:00:00Z",
            "location": "remote",
            "vertical": "marketing",
        },
        hoverstamp=hoverstamp,
        governance_attestation=governance_attestation,
    )


# ══════════════════════════════════════════════════════════════════════
#   AUTO-EMISSION ON BY DEFAULT (v1.2+)
# ══════════════════════════════════════════════════════════════════════

def test_auto_emission_on_by_default_when_hoverstamp_present():
    """Default (no env var set): hoverstamp present → governance
    attestation IS emitted automatically."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HOVERSTACK_GEP_AUTO_EMIT", None)
        res = _proof_with_hs(hoverstamp=_SAMPLE_HOVERSTAMP)
    ev = res["proof"].get("evidence", {})
    assert "governance_attestation" in ev
    ga = ev["governance_attestation"]
    assert ga["governance_hash"]
    assert ga["signature"]


def test_opt_out_disables_auto_emission():
    """HOVERSTACK_GEP_AUTO_EMIT=0 → no attestation even with hoverstamp."""
    with patch.dict(os.environ, {"HOVERSTACK_GEP_AUTO_EMIT": "0"}):
        res = _proof_with_hs(hoverstamp=_SAMPLE_HOVERSTAMP)
    ev = res["proof"].get("evidence", {})
    assert "governance_attestation" not in ev


def test_no_auto_emission_when_hoverstamp_absent():
    """No hoverstamp → no attestation regardless of env."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HOVERSTACK_GEP_AUTO_EMIT", None)
        res = _proof_with_hs(hoverstamp=None)
    ev = res["proof"].get("evidence", {})
    assert "governance_attestation" not in ev


# ══════════════════════════════════════════════════════════════════════
#   AUTO-EMISSION ENABLED
# ══════════════════════════════════════════════════════════════════════

def test_auto_emission_when_enabled_and_hoverstamp_present():
    """HOVERSTACK_GEP_AUTO_EMIT=1 + hoverstamp present → governance
    attestation is auto-generated and embedded."""
    with patch.dict(os.environ, {"HOVERSTACK_GEP_AUTO_EMIT": "1"}):
        res = _proof_with_hs(hoverstamp=_SAMPLE_HOVERSTAMP)
    assert res["ok"] is True
    ev = res["proof"].get("evidence", {})
    assert "governance_attestation" in ev
    ga = ev["governance_attestation"]
    assert "governance_hash" in ga
    assert "signature" in ga
    assert ga["governance_hash"]
    assert ga["signature"]


def test_auto_emitted_artifact_uses_ed25519_when_available():
    """When ed25519 is available (cryptography package installed),
    auto-emission should prefer ed25519."""
    if not _ed25519_available():
        pytest.skip("cryptography ed25519 not available")
    with patch.dict(os.environ, {"HOVERSTACK_GEP_AUTO_EMIT": "1"}):
        res = _proof_with_hs(hoverstamp=_SAMPLE_HOVERSTAMP)
    ga = res["proof"]["evidence"]["governance_attestation"]
    assert ga["algorithm"] == ALG_ED25519
    assert ga["public_key"]  # non-empty hex


def test_auto_emitted_artifact_verifies():
    """The auto-generated artifact must verify offline."""
    with patch.dict(os.environ, {"HOVERSTACK_GEP_AUTO_EMIT": "1"}):
        res = _proof_with_hs(hoverstamp=_SAMPLE_HOVERSTAMP)
    ga = res["proof"]["evidence"]["governance_attestation"]
    report = verify_embedded_artifact(ga)
    assert report["signature_valid"] is True
    assert report["errors"] == []


def test_auto_emitted_artifact_preserves_transcript_data():
    """Key fields from the hoverstamp should flow into the artifact."""
    with patch.dict(os.environ, {"HOVERSTACK_GEP_AUTO_EMIT": "1"}):
        res = _proof_with_hs(hoverstamp=_SAMPLE_HOVERSTAMP)
    ga = res["proof"]["evidence"]["governance_attestation"]
    assert ga["runtime_name"] == "vllm"
    assert ga["model_name"] == "llama-3.1-8b"
    assert ga["shape_id"] == "contract_review"
    # Decision should reflect the recall_mode from hoverstamp.
    assert ga["decision_path_chosen"] in (
        "structural_recall", "tail_only_delta", "full_compute"
    )


# ══════════════════════════════════════════════════════════════════════
#   CALLER-PROVIDED ATTESTATION TAKES PRIORITY
# ══════════════════════════════════════════════════════════════════════

def test_explicit_attestation_overrides_auto_emission():
    """If the caller already provides governance_attestation, auto-
    emission must NOT replace it, even when the flag is set."""
    explicit = build_signed_artifact(
        DecisionTranscript(cell_id="explicit", shape_id="explicit_shape"),
        algorithm=ALG_HMAC_SHA256, signing_key=b"explicit-key",
    )
    with patch.dict(os.environ, {"HOVERSTACK_GEP_AUTO_EMIT": "1"}):
        res = _proof_with_hs(
            hoverstamp=_SAMPLE_HOVERSTAMP,
            governance_attestation=explicit.to_dict(),
        )
    ga = res["proof"]["evidence"]["governance_attestation"]
    # The explicit artifact's governance_hash, not an auto-generated one.
    assert ga["governance_hash"] == explicit.governance_hash
    assert ga["shape_id"] == "explicit_shape"


# ══════════════════════════════════════════════════════════════════════
#   ERROR HANDLING
# ══════════════════════════════════════════════════════════════════════

def test_auto_emission_failure_does_not_block_proof_creation():
    """If GEP generation fails, the proof must still be created
    without an attestation."""
    with patch.dict(os.environ, {"HOVERSTACK_GEP_AUTO_EMIT": "1"}):
        with patch("hoverstack.governed_proof.build_signed_artifact",
                    side_effect=RuntimeError("simulated signing failure")):
            res = _proof_with_hs(hoverstamp=_SAMPLE_HOVERSTAMP)
    assert res["ok"] is True
    ev = res["proof"].get("evidence", {})
    # Attestation should NOT be present — the failure was swallowed.
    assert "governance_attestation" not in ev


# ══════════════════════════════════════════════════════════════════════
#   PROOF_HASH INVARIANCE
# ══════════════════════════════════════════════════════════════════════

def test_proof_hash_invariant_with_auto_emission():
    """proof_hash must not change when auto-emission adds an attestation."""
    with patch.dict(os.environ, {"HOVERSTACK_GEP_AUTO_EMIT": "0"}):
        base = _proof_with_hs(hoverstamp=_SAMPLE_HOVERSTAMP)
    with patch.dict(os.environ, {"HOVERSTACK_GEP_AUTO_EMIT": "1"}):
        with_auto = proof_pipe.create_proof(
            proof_type="completion_photo", source="manual",
            agent_username="auto_emit_test",
            deal_id=base["proof"]["deal_id"],
            proof_data=base["proof"]["proof_data"],
            hoverstamp=_SAMPLE_HOVERSTAMP,
        )
    assert base["proof"]["proof_hash"] == with_auto["proof"]["proof_hash"]


# ══════════════════════════════════════════════════════════════════════
#   NO PLANE MODULE DEPENDENCY
# ══════════════════════════════════════════════════════════════════════

def test_plane_modules_do_not_import_governed_proof():
    """Auto-emission is caller-side only. No HoverStack plane module
    may reference governed_proof."""
    import inspect
    from hoverstack import (
        risk_plane, recall_plane, delta_plane, preservation_policy,
        frequency_policy, shape_policy_memory, memory_plane,
    )
    for mod in (risk_plane, recall_plane, delta_plane,
                preservation_policy, frequency_policy,
                shape_policy_memory, memory_plane):
        src = inspect.getsource(mod)
        assert "governed_proof" not in src, (
            f"{mod.__name__} references governed_proof — emission must "
            f"be caller-side only"
        )


# ══════════════════════════════════════════════════════════════════════
#   JSON ROUNDTRIP + END-TO-END VERIFICATION
# ══════════════════════════════════════════════════════════════════════

def test_auto_emitted_artifact_survives_json_roundtrip():
    """Serialize the proof to JSON and back; verify the attestation
    from the deserialized form."""
    with patch.dict(os.environ, {"HOVERSTACK_GEP_AUTO_EMIT": "1"}):
        res = _proof_with_hs(hoverstamp=_SAMPLE_HOVERSTAMP)
    wire = json.loads(json.dumps(res["proof"]["evidence"]["governance_attestation"]))
    report = verify_embedded_artifact(wire)
    assert report["signature_valid"] is True
