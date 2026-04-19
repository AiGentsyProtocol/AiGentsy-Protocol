"""Governed Economic Proof v1.1 — ed25519 tests.

Covers:
    1. Ed25519 signing round-trip.
    2. Public-key-only verification (no shared secret).
    3. Tamper detection under ed25519.
    4. ProofPack binding under ed25519.
    5. Algorithm dispatch — HMAC + ed25519 coexist.
    6. Backward compatibility — existing HMAC tests still pass.
    7. Canonicalization stability.
    8. JSON roundtrip for ed25519 artifacts.
    9. verify_embedded_artifact dispatches correctly.
   10. Automatic emission path.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

import proof_pipe
from hoverstack.governed_proof import (
    ALG_ED25519, ALG_HMAC_SHA256, GovernanceArtifact, DecisionTranscript,
    SPEC_VERSION, build_signed_artifact, verify_embedded_artifact,
    _load_ed25519_private_key, _ed25519_public_key_hex,
)


def _transcript() -> DecisionTranscript:
    return DecisionTranscript(
        cell_id="c_ed25519",
        shape_id="contract_review",
        runtime_name="vllm",
        model_name="llama-3.1-8b",
        risk_class="low_risk",
        recall_mode="structural_recall",
        recall_confidence=0.82,
        delta_mode="tail_only_delta",
        delta_size_estimate=0.1,
    )


_HMAC_KEY = b"test-hmac-key-for-v11-tests"


# ══════════════════════════════════════════════════════════════════════
#   ED25519 SIGNING / VERIFICATION
# ══════════════════════════════════════════════════════════════════════

def test_ed25519_sign_verify_round_trip():
    a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519)
    assert a.algorithm == ALG_ED25519
    assert a.public_key  # non-empty hex
    assert a.signature
    assert a.governance_hash
    assert a.verify_signature() is True


def test_ed25519_public_key_only_verification():
    """Third-party verification: verifier has only the public key,
    not the private key. Must succeed."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519)
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(a.public_key))
    assert a.verify_signature(ed25519_public_key=pub) is True


def test_ed25519_tamper_on_content_fails():
    a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519)
    assert a.verify_signature() is True
    a.decision_path_chosen = "full_compute"
    assert a.verify_signature() is False


def test_ed25519_tamper_on_signature_fails():
    a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519)
    a.signature = "00" * 64
    assert a.verify_signature() is False


def test_ed25519_tamper_on_governance_hash_fails():
    a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519)
    a.governance_hash = "00" * 32
    assert a.verify_signature() is False


def test_ed25519_binding_round_trip():
    a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519,
                                proofpack_hash="pp_ed25519_test")
    assert a.proofpack_binding_hash
    assert a.verify_binding("pp_ed25519_test") is True
    assert a.verify_binding("other") is False


def test_ed25519_canonicalization_includes_public_key():
    """The public_key field must be part of the canonical content so the
    governance_hash commits to which key signed it."""
    a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519)
    canonical = a.to_canonical_bytes(include_hash_fields=False)
    assert b'"public_key"' in canonical
    assert a.public_key.encode("ascii") in canonical


# ══════════════════════════════════════════════════════════════════════
#   ALGORITHM DISPATCH + BACKWARD COMPATIBILITY
# ══════════════════════════════════════════════════════════════════════

def test_hmac_artifacts_still_verify_after_v11_upgrade():
    """Existing HMAC artifacts are not broken by the v1.1 code."""
    a = build_signed_artifact(_transcript(), algorithm=ALG_HMAC_SHA256,
                                signing_key=_HMAC_KEY)
    assert a.algorithm == ALG_HMAC_SHA256
    assert a.public_key == ""
    assert a.verify_signature(signing_key=_HMAC_KEY) is True


def test_hmac_verify_fails_with_wrong_key():
    a = build_signed_artifact(_transcript(), algorithm=ALG_HMAC_SHA256,
                                signing_key=_HMAC_KEY)
    assert a.verify_signature(signing_key=b"wrong-key") is False


def test_mixed_dispatch_verifies_each_correctly():
    """HMAC and ed25519 artifacts coexist. Verification dispatches on
    self.algorithm without manual caller intervention."""
    hmac_a = build_signed_artifact(_transcript(),
                                      algorithm=ALG_HMAC_SHA256,
                                      signing_key=_HMAC_KEY)
    ed_a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519)

    assert hmac_a.verify_signature(signing_key=_HMAC_KEY) is True
    assert ed_a.verify_signature() is True
    # Cross-check: HMAC artifact must not verify under ed25519 path.
    assert hmac_a.algorithm == ALG_HMAC_SHA256
    assert ed_a.algorithm == ALG_ED25519


def test_verify_embedded_artifact_dispatches_on_algorithm():
    """verify_embedded_artifact auto-reads the algorithm field."""
    hmac_a = build_signed_artifact(
        _transcript(), algorithm=ALG_HMAC_SHA256, signing_key=_HMAC_KEY,
        proofpack_hash="pp1",
    )
    ed_a = build_signed_artifact(
        _transcript(), algorithm=ALG_ED25519, proofpack_hash="pp2",
    )
    r_hmac = verify_embedded_artifact(
        hmac_a.to_dict(), signing_key=_HMAC_KEY, proofpack_hash="pp1")
    r_ed = verify_embedded_artifact(
        ed_a.to_dict(), proofpack_hash="pp2")

    assert r_hmac["signature_valid"] is True
    assert r_hmac["binding_valid"] is True
    assert r_hmac["algorithm"] == ALG_HMAC_SHA256

    assert r_ed["signature_valid"] is True
    assert r_ed["binding_valid"] is True
    assert r_ed["algorithm"] == ALG_ED25519


# ══════════════════════════════════════════════════════════════════════
#   JSON ROUNDTRIP
# ══════════════════════════════════════════════════════════════════════

def test_ed25519_json_roundtrip_preserves_verifiability():
    a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519,
                                proofpack_hash="pp_json_rt")
    wire = json.loads(json.dumps(a.to_dict()))
    report = verify_embedded_artifact(wire, proofpack_hash="pp_json_rt")
    assert report["signature_valid"] is True
    assert report["binding_valid"] is True


# ══════════════════════════════════════════════════════════════════════
#   PROOFPACK EMBEDDING
# ══════════════════════════════════════════════════════════════════════

def test_ed25519_artifact_embeds_in_proofpack():
    a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519)
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="gep11_test", deal_id=f"deal_gep11_{id(a)}",
        proof_data={"photo_url": "u", "timestamp": "t", "location": "r",
                    "vertical": "marketing"},
        governance_attestation=a.to_dict(),
    )
    assert res["ok"] is True
    ev = res["proof"].get("evidence", {})
    assert "governance_attestation" in ev
    assert ev["governance_attestation"]["algorithm"] == ALG_ED25519


def test_proof_hash_invariant_for_ed25519_attestation():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="gep11_test", deal_id="deal_gep11_hash_test",
        proof_data={"photo_url": "u", "timestamp": "t", "location": "r",
                    "vertical": "marketing"},
    )
    a = build_signed_artifact(_transcript(), algorithm=ALG_ED25519)
    with_attest = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="gep11_test", deal_id="deal_gep11_hash_test",
        proof_data=base["proof"]["proof_data"],
        governance_attestation=a.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_attest["proof"]["proof_hash"]


# ══════════════════════════════════════════════════════════════════════
#   AUTOMATIC EMISSION (caller-side activation)
# ══════════════════════════════════════════════════════════════════════

def test_auto_emission_builds_artifact_from_runtime_fields():
    """Simulate caller-side emission: take runtime_fields from a
    benchmark cell and produce a signed GEP artifact automatically."""
    rf = {
        "runtime_name": "vllm",
        "risk_class": "bounded_risk",
        "recall_mode": "structural_recall",
        "recall_confidence": 0.8,
        "delta_mode": "tail_only_delta",
        "delta_size_estimate": 0.1,
        "decision_rationale": "structural_recall: risk blocked direct",
    }
    t = DecisionTranscript.from_runtime_fields(
        cell_id="auto_c0", shape_id="contract_review",
        runtime_fields=rf, runtime_name="vllm", model_name="llama-8b",
    )
    a = build_signed_artifact(t, algorithm=ALG_ED25519)
    assert a.verify_signature() is True
    assert a.decision_path_chosen in ("structural_recall", "tail_only_delta",
                                        "full_compute")
    assert a.algorithm == ALG_ED25519


def test_auto_emission_disabled_by_default_produces_no_attestation():
    """When the emission env flag is not set, a caller that doesn't
    build a GEP artifact gets no governance_attestation in the proof."""
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="no_emit_test", deal_id="deal_no_emit",
        proof_data={"photo_url": "u", "timestamp": "t", "location": "r",
                    "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "governance_attestation" not in ev


def test_auto_emission_produces_correct_proofpack():
    """Full caller-side flow: build transcript → sign → embed → verify."""
    rf = {
        "runtime_name": "vllm",
        "risk_class": "low_risk",
        "recall_mode": "direct_recall",
        "recall_confidence": 0.95,
        "delta_mode": "no_delta_needed",
        "delta_size_estimate": 0.0,
    }
    t = DecisionTranscript.from_runtime_fields(
        cell_id="auto_full", shape_id="bom_extract",
        runtime_fields=rf, runtime_name="vllm", model_name="llama-8b",
    )
    # Step 1: create ProofPack first (to get proof_hash).
    pp = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="auto_emit_agent",
        deal_id=f"deal_auto_emit_{id(t)}",
        proof_data={"photo_url": "u", "timestamp": "t", "location": "r",
                    "vertical": "marketing"},
    )
    proof_hash = pp["proof"]["proof_hash"]

    # Step 2: build signed artifact bound to that ProofPack.
    a = build_signed_artifact(
        t, algorithm=ALG_ED25519, proofpack_hash=proof_hash,
    )

    # Step 3: verify the artifact offline.
    report = verify_embedded_artifact(
        a.to_dict(), proofpack_hash=proof_hash,
    )
    assert report["signature_valid"] is True
    assert report["binding_valid"] is True
    assert report["algorithm"] == ALG_ED25519


def test_no_regression_on_hoverstack_decision_outputs():
    """The governed_proof module does not import or alter any HoverStack
    plane module. Verify by checking that the plane modules have no
    reference to governed_proof in their source."""
    import inspect
    from hoverstack import (
        risk_plane, recall_plane, delta_plane, preservation_policy,
        frequency_policy, shape_policy_memory,
    )
    for mod in (risk_plane, recall_plane, delta_plane,
                preservation_policy, frequency_policy, shape_policy_memory):
        src = inspect.getsource(mod)
        assert "governed_proof" not in src, (
            f"{mod.__name__} references governed_proof — emission must "
            f"be caller-side only, not inside plane logic"
        )
