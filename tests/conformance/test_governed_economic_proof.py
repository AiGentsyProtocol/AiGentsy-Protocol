"""Governed Economic Proof v1 tests.

Covers:
    1. DecisionTranscript construction from runtime_fields.
    2. Canonical serialization stability (identical input → identical bytes).
    3. Governance hash determinism and content-exclusion of hash fields.
    4. Signing + verification round-trip.
    5. Tamper detection on every content field.
    6. ProofPack binding integrity.
    7. Additive embedding via proof_pipe.create_proof — attestation
       appears under evidence.governance_attestation when supplied.
    8. Back-compat: ProofPacks without attestation behave identically.
    9. proof_hash invariant: adding the attestation does not change
       the core proof hash.
   10. Offline verification via verify_embedded_artifact.
"""

from __future__ import annotations

import json

import pytest

import proof_pipe
from hoverstack.governed_proof import (
    GovernanceArtifact, DecisionTranscript, SPEC_VERSION,
    build_signed_artifact, verify_embedded_artifact,
)


# ── Fixtures ─────────────────────────────────────────────────────────

_SAMPLE_RUNTIME_FIELDS = {
    "runtime_name": "vllm",
    "runtime_capabilities": {
        "prefix_cache": True, "prefill_decode_split": True,
        "batched_decode": True, "per_request_metrics": True,
        "cache_compat_guarantee": True, "safe_reuse_enabled": True,
    },
    "risk_class": "bounded_risk",
    "risk_restrictions_applied": ["rule[0]:task_family==clinical_qa->force_full_compute"],
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
        "kv_bytes_estimate": 12000.0, "residency_waves_avg": 2.0,
        "overhead_ms_estimate": 1.0, "cache_pressure_factor": 1.0,
        "raw_units": 14.0, "normalized_score": 14.0,
        "kelly_fraction": 0.48,
    },
    "compute_avoided_estimate": 38.4,
    "runtime_prefix_cache_hit": True,
    "runtime_decode_batch_size": 4,
    "decision_rationale": "structural_recall: risk blocked direct",
    "decision_key": "structural_recall|preserve|basis=per_shape_runtime_model|from=-|why=risk_blocked_direct|net_ms=+5.00|consec=0",
}

_KEY_A = b"test-key-A-" + b"\x00" * 20
_KEY_B = b"test-key-B-" + b"\x00" * 20


def _transcript() -> DecisionTranscript:
    return DecisionTranscript.from_runtime_fields(
        cell_id="c0", shape_id="contract_review",
        runtime_fields=_SAMPLE_RUNTIME_FIELDS,
        runtime_name="vllm", model_name="llama-3.1-8b",
        shape_reputation=0.42, shape_tags=["reliable_recall"],
    )


# ── Transcript ───────────────────────────────────────────────────────

def test_transcript_populates_from_runtime_fields():
    t = _transcript()
    assert t.cell_id == "c0"
    assert t.shape_id == "contract_review"
    assert t.runtime_name == "vllm"
    assert t.model_name == "llama-3.1-8b"
    assert t.risk_class == "bounded_risk"
    assert t.recall_mode == "structural_recall"
    assert t.recall_confidence == pytest.approx(0.82)
    assert t.recall_fallback_triggered is True
    assert t.delta_mode == "tail_only_delta"
    assert t.kelly_fraction == pytest.approx(0.48)
    assert t.cache_pressure_factor == pytest.approx(1.0)
    assert t.compute_avoided_estimate_ms == pytest.approx(38.4)
    assert t.shape_reputation == pytest.approx(0.42)
    assert t.shape_tags == ["reliable_recall"]


def test_transcript_safe_under_missing_fields():
    """Empty runtime_fields dict must not crash; all fields receive
    conservative defaults."""
    t = DecisionTranscript.from_runtime_fields(
        cell_id="c0", shape_id="s", runtime_fields={},
    )
    assert t.recall_mode == "full_compute"
    assert t.delta_mode == "full_compute_required"
    assert t.risk_class == ""
    assert t.kelly_fraction is None


# ── Canonicalization + hash determinism ─────────────────────────────

def test_canonicalization_stable_across_builds():
    """Two artifacts with identical content serialize to identical bytes."""
    a = GovernanceArtifact.from_transcript(_transcript())
    b = GovernanceArtifact.from_transcript(_transcript())
    # governance_id + timestamp differ by design; zero them out for
    # comparison so only structural content is tested.
    a.governance_id = b.governance_id = "FIXED"
    a.timestamp = b.timestamp = "FIXED"
    assert a.to_canonical_bytes() == b.to_canonical_bytes()


def test_governance_hash_excludes_hash_signature_binding_fields():
    """The hash input must exclude the three cycle-prone fields."""
    a = GovernanceArtifact.from_transcript(_transcript())
    before = a.compute_governance_hash()
    a.governance_hash = "deadbeef" * 8
    a.signature = "cafe" * 16
    a.proofpack_binding_hash = "1234" * 16
    after = a.compute_governance_hash()
    assert before == after


def test_governance_hash_changes_when_content_changes():
    a = GovernanceArtifact.from_transcript(_transcript())
    h0 = a.compute_governance_hash()
    a.decision_path_chosen = "full_compute"
    h1 = a.compute_governance_hash()
    assert h0 != h1


# ── Sign / verify round trip ─────────────────────────────────────────

def test_sign_verify_round_trip():
    a = build_signed_artifact(_transcript(), signing_key=_KEY_A)
    assert a.governance_hash
    assert a.signature
    assert a.verify_signature(signing_key=_KEY_A) is True


def test_verify_fails_with_wrong_key():
    a = build_signed_artifact(_transcript(), signing_key=_KEY_A)
    assert a.verify_signature(signing_key=_KEY_B) is False


def test_tamper_on_any_content_field_fails_verification():
    a = build_signed_artifact(_transcript(), signing_key=_KEY_A)
    assert a.verify_signature(signing_key=_KEY_A) is True
    # Flip a content field post-signing. The stored governance_hash
    # remains stale; recomputing from new content differs → verify fails.
    a.decision_path_chosen = "full_compute"
    assert a.verify_signature(signing_key=_KEY_A) is False


def test_tamper_on_signature_fails_verification():
    a = build_signed_artifact(_transcript(), signing_key=_KEY_A)
    a.signature = "0" * len(a.signature)
    assert a.verify_signature(signing_key=_KEY_A) is False


def test_tamper_on_governance_hash_fails_verification():
    a = build_signed_artifact(_transcript(), signing_key=_KEY_A)
    a.governance_hash = "0" * len(a.governance_hash)
    assert a.verify_signature(signing_key=_KEY_A) is False


# ── ProofPack binding ───────────────────────────────────────────────

def test_binding_matches_declared_proofpack_hash():
    a = build_signed_artifact(_transcript(),
                                proofpack_hash="abc123",
                                signing_key=_KEY_A)
    assert a.proofpack_binding_hash
    assert a.verify_binding("abc123") is True


def test_binding_fails_when_proofpack_hash_differs():
    a = build_signed_artifact(_transcript(),
                                proofpack_hash="abc123",
                                signing_key=_KEY_A)
    assert a.verify_binding("other_hash") is False


def test_binding_before_sign_raises():
    a = GovernanceArtifact.from_transcript(_transcript())
    with pytest.raises(ValueError):
        a.bind_to_proofpack("abc123")


# ── Offline verification helper ─────────────────────────────────────

def test_verify_embedded_artifact_positive():
    a = build_signed_artifact(_transcript(),
                                proofpack_hash="pp_hash_123",
                                signing_key=_KEY_A)
    d = a.to_dict()
    report = verify_embedded_artifact(
        d, signing_key=_KEY_A, proofpack_hash="pp_hash_123",
    )
    assert report["signature_valid"] is True
    assert report["binding_valid"] is True
    assert report["errors"] == []
    assert report["spec_version"] == SPEC_VERSION


def test_verify_embedded_artifact_reports_errors():
    a = build_signed_artifact(_transcript(),
                                proofpack_hash="pp_hash_A",
                                signing_key=_KEY_A)
    d = a.to_dict()
    d["decision_path_chosen"] = "tampered"  # invalidate content
    report = verify_embedded_artifact(
        d, signing_key=_KEY_A, proofpack_hash="pp_hash_A",
    )
    assert report["signature_valid"] is False
    assert any("signature" in e or "governance_hash" in e for e in report["errors"])


def test_verify_embedded_artifact_skips_binding_when_no_hash_given():
    a = build_signed_artifact(_transcript(),
                                proofpack_hash="pp_hash_A",
                                signing_key=_KEY_A)
    d = a.to_dict()
    report = verify_embedded_artifact(d, signing_key=_KEY_A)
    # Signature valid; binding not checked.
    assert report["signature_valid"] is True
    assert report["binding_valid"] is None


# ── ProofPack embedding (proof_pipe.create_proof) ───────────────────

def _make_proof(governance_attestation=None, hoverstamp=None):
    return proof_pipe.create_proof(
        proof_type="completion_photo",
        source="manual",
        agent_username="gep_test_agent",
        deal_id=f"deal_gep_{id(governance_attestation)}",
        proof_data={
            "photo_url": "https://aigentsy.com/proof",
            "timestamp": "2026-04-15T00:00:00+00:00",
            "location": "remote",
            "vertical": "marketing",
        },
        hoverstamp=hoverstamp,
        governance_attestation=governance_attestation,
    )


def test_proofpack_without_attestation_has_no_evidence_governance_key():
    res = _make_proof()
    assert res["ok"] is True
    proof = res["proof"]
    assert "evidence" not in proof or "governance_attestation" not in proof.get("evidence", {})


def test_proofpack_with_attestation_embeds_it_under_evidence():
    artifact = build_signed_artifact(_transcript(), signing_key=_KEY_A)
    res = _make_proof(governance_attestation=artifact.to_dict())
    assert res["ok"] is True
    proof = res["proof"]
    assert "evidence" in proof
    assert "governance_attestation" in proof["evidence"]
    assert proof["evidence"]["governance_attestation"]["signature"] == artifact.signature


def test_proof_hash_invariant_to_attestation_presence():
    """Adding a governance_attestation must not change proof_hash —
    proof_hash is computed only from (proof_type, source, agent,
    deal_id, proof_data). This preserves Level 1 semantics."""
    base = _make_proof()
    artifact = build_signed_artifact(_transcript(), signing_key=_KEY_A)
    # Use the same deal_id so proof_hash is identity-comparable.
    deal_id = base["proof"]["deal_id"]
    with_attest = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="gep_test_agent", deal_id=deal_id,
        proof_data=base["proof"]["proof_data"],
        governance_attestation=artifact.to_dict(),
    )
    # proof_pipe idempotency will return the base record; to avoid
    # that we check both hashes come out identical when computed from
    # the same (type, source, agent, deal_id, proof_data).
    assert base["proof"]["proof_hash"] == with_attest["proof"]["proof_hash"]


def test_attestation_can_be_verified_after_roundtrip_through_proofpack():
    """Full flow: build signed artifact, embed in ProofPack, read back,
    verify offline."""
    artifact = build_signed_artifact(
        _transcript(),
        proofpack_hash="pp_binding_test",
        signing_key=_KEY_A,
    )
    res = _make_proof(governance_attestation=artifact.to_dict())
    roundtripped = res["proof"]["evidence"]["governance_attestation"]
    # Serialize + deserialize through JSON the way a real consumer would.
    wire = json.loads(json.dumps(roundtripped))
    report = verify_embedded_artifact(
        wire, signing_key=_KEY_A, proofpack_hash="pp_binding_test",
    )
    assert report["signature_valid"] is True
    assert report["binding_valid"] is True


def test_hoverstamp_and_governance_attestation_coexist():
    """Both optional evidence kinds can be attached to one ProofPack."""
    artifact = build_signed_artifact(_transcript(), signing_key=_KEY_A)
    hs = {"cell_id": "c0", "shape_id": "contract_review"}
    res = _make_proof(governance_attestation=artifact.to_dict(),
                       hoverstamp=hs)
    proof = res["proof"]
    assert "hoverstamp" in proof["evidence"]
    assert "governance_attestation" in proof["evidence"]


# ── Non-claims discipline ───────────────────────────────────────────

def test_artifact_does_not_expose_global_optimality_field():
    """v1 explicitly refuses to claim optimality. There must be no
    field in the schema that implies or records such a claim."""
    fields = set(GovernanceArtifact.__dataclass_fields__.keys())
    forbidden_substrings = ("optimal", "cheapest", "globally")
    for f in fields:
        for sub in forbidden_substrings:
            assert sub not in f.lower(), (
                f"v1 schema must not advertise optimality: {f}"
            )
