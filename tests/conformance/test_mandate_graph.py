"""Mandate Graph v1 tests.

Covers:
    1. Mandate creation.
    2. Canonical serialization + hash determinism.
    3. Ed25519 signing and verification.
    4. Mandate validity evaluation (all 7 checks).
    5. Expiry handling.
    6. Revocation handling.
    7. Scope / action enforcement.
    8. Delegation allowed / denied.
    9. Parent-child chain constraints (narrowing only).
   10. ProofPack embedding + coexistence with GEP + hoverstamp.
   11. Backward compatibility (no mandate = old behavior).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

import proof_pipe
from protocol.mandate_graph import (
    Mandate, MandateEvaluation, evaluate_mandate,
    verify_embedded_mandate, SPEC_VERSION,
)


# ── Creation ─────────────────────────────────────────────────────────

def test_create_populates_required_fields():
    m = Mandate.create(
        issuer="platform",
        subject_agent="agent_A",
        allowed_actions=["proof_create", "settlement_request"],
        work_class=["contract_review"],
    )
    assert m.mandate_id.startswith("mnd_")
    assert m.issuer == "platform"
    assert m.subject_agent == "agent_A"
    assert m.spec_version == SPEC_VERSION
    assert m.issued_at
    assert "proof_create" in m.allowed_actions


# ── Serialization + hash determinism ────────────────────────────────

def test_hash_deterministic_across_builds():
    m1 = Mandate.create(issuer="p", subject_agent="a")
    m2 = Mandate.create(issuer="p", subject_agent="a")
    m1.mandate_id = m2.mandate_id = "FIXED"
    m1.issued_at = m2.issued_at = "FIXED"
    assert m1.compute_mandate_hash() == m2.compute_mandate_hash()


def test_hash_excludes_signature_fields():
    m = Mandate.create(issuer="p", subject_agent="a")
    h1 = m.compute_mandate_hash()
    m.mandate_hash = "tampered"
    m.signature = "tampered"
    h2 = m.compute_mandate_hash()
    assert h1 == h2


def test_hash_changes_when_content_changes():
    m = Mandate.create(issuer="p", subject_agent="a")
    h1 = m.compute_mandate_hash()
    m.issuer = "different"
    assert m.compute_mandate_hash() != h1


# ── Ed25519 signing ─────────────────────────────────────────────────

def test_sign_verify_round_trip():
    m = Mandate.create(issuer="p", subject_agent="a",
                        allowed_actions=["proof_create"])
    m.sign()
    assert m.algorithm == "ed25519"
    assert m.public_key
    assert m.mandate_hash
    assert m.signature
    assert m.verify_signature() is True


def test_tamper_detection():
    m = Mandate.create(issuer="p", subject_agent="a")
    m.sign()
    assert m.verify_signature() is True
    m.subject_agent = "tampered"
    assert m.verify_signature() is False


def test_public_key_only_verification():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    m = Mandate.create(issuer="p", subject_agent="a")
    m.sign()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(m.public_key))
    assert m.verify_signature(ed25519_public_key=pub) is True


def test_hmac_fallback_signing():
    m = Mandate.create(issuer="p", subject_agent="a")
    key = b"test-hmac-key"
    m.sign(algorithm="hmac-sha256", signing_key=key)
    assert m.algorithm == "hmac-sha256"
    assert m.verify_signature(signing_key=key) is True


# ── Validity evaluation ─────────────────────────────────────────────

def _signed_mandate(**kwargs):
    m = Mandate.create(
        issuer="platform",
        subject_agent="agent_A",
        allowed_actions=["proof_create", "settlement_request"],
        forbidden_actions=["admin_access"],
        work_class=["contract_review", "bom_extract"],
        consequence_rights=["settlement_request", "release"],
        **kwargs,
    )
    m.sign()
    return m


def test_eval_all_checks_pass():
    m = _signed_mandate()
    r = evaluate_mandate(
        m, requested_action="proof_create",
        requested_work_class="contract_review",
        requested_consequence="release",
        subject_agent="agent_A",
    )
    assert r.valid is True
    assert "signature_valid" in r.checks_passed
    assert not r.checks_failed


def test_eval_forbidden_action_fails():
    m = _signed_mandate()
    r = evaluate_mandate(m, requested_action="admin_access")
    assert r.valid is False
    assert any("action_forbidden" in f for f in r.checks_failed)


def test_eval_action_not_in_allowed_fails():
    m = _signed_mandate()
    r = evaluate_mandate(m, requested_action="delete_everything")
    assert r.valid is False
    assert any("action_not_allowed" in f for f in r.checks_failed)


def test_eval_work_class_not_permitted():
    m = _signed_mandate()
    r = evaluate_mandate(m, requested_work_class="unknown_class")
    assert r.valid is False
    assert any("work_class_not_permitted" in f for f in r.checks_failed)


def test_eval_consequence_not_authorized():
    m = _signed_mandate()
    r = evaluate_mandate(m, requested_consequence="fund_withdrawal")
    assert r.valid is False
    assert any("consequence_not_authorized" in f for f in r.checks_failed)


def test_eval_subject_mismatch():
    m = _signed_mandate()
    r = evaluate_mandate(m, subject_agent="agent_B")
    assert r.valid is False
    assert any("subject_mismatch" in f for f in r.checks_failed)


# ── Expiry ──────────────────────────────────────────────────────────

def test_eval_expired_mandate_fails():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    m = _signed_mandate(expires_at=past)
    r = evaluate_mandate(m)
    assert r.valid is False
    assert "expired" in r.checks_failed


def test_eval_not_expired():
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    m = _signed_mandate(expires_at=future)
    r = evaluate_mandate(m)
    assert r.valid is True


# ── Revocation ──────────────────────────────────────────────────────

def test_eval_revoked_mandate_fails():
    m = _signed_mandate()
    m.revoked_at = datetime.now(timezone.utc).isoformat()
    m.sign()
    r = evaluate_mandate(m)
    assert r.valid is False
    assert "revoked" in r.checks_failed


# ── Delegation ──────────────────────────────────────────────────────

def test_delegation_succeeds_when_allowed():
    parent = _signed_mandate(delegation_allowed=True, max_delegation_depth=2)
    child = parent.delegate("agent_B", narrowed_actions=["proof_create"])
    assert child.parent_mandate_id == parent.mandate_id
    assert child.delegation_depth == 1
    assert child.issuer == "agent_A"
    assert child.subject_agent == "agent_B"
    assert child.allowed_actions == ["proof_create"]


def test_delegation_fails_when_not_allowed():
    parent = _signed_mandate(delegation_allowed=False)
    with pytest.raises(ValueError, match="not allowed"):
        parent.delegate("agent_B")


def test_delegation_fails_at_max_depth():
    """When delegation_depth reaches max_delegation_depth, the child's
    delegation_allowed is set to False by the delegate() factory."""
    parent = _signed_mandate(delegation_allowed=True, max_delegation_depth=1)
    child = parent.delegate("agent_B")
    assert child.delegation_allowed is False
    with pytest.raises(ValueError, match="not allowed"):
        child.delegate("agent_C")


def test_delegation_cannot_widen_actions():
    parent = _signed_mandate(delegation_allowed=True, max_delegation_depth=2)
    with pytest.raises(ValueError, match="not in parent"):
        parent.delegate("agent_B", narrowed_actions=["admin_access"])


def test_delegation_cannot_widen_work_class():
    parent = _signed_mandate(delegation_allowed=True, max_delegation_depth=2)
    with pytest.raises(ValueError, match="not in parent"):
        parent.delegate("agent_B", narrowed_work_class=["unknown"])


def test_delegation_chain_narrows():
    root = _signed_mandate(delegation_allowed=True, max_delegation_depth=3)
    level1 = root.delegate("B", narrowed_actions=["proof_create"])
    level1.sign()
    assert level1.delegation_depth == 1
    level1.delegation_allowed = True
    level2 = level1.delegate("C")
    assert level2.delegation_depth == 2
    assert level2.allowed_actions == ["proof_create"]


# ── ProofPack embedding ────────────────────────────────────────────

def test_proofpack_without_mandate():
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_no_mandate",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "mandate" not in ev


def test_proofpack_embeds_mandate():
    m = _signed_mandate()
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_with_mandate_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        mandate=m.to_dict(),
    )
    ev = res["proof"].get("evidence", {})
    assert "mandate" in ev
    assert ev["mandate"]["mandate_id"] == m.mandate_id


def test_mandate_coexists_with_gep_and_hoverstamp():
    from hoverstack.governed_proof import (
        DecisionTranscript, build_signed_artifact, ALG_ED25519,
    )
    m = _signed_mandate()
    t = DecisionTranscript(cell_id="c", shape_id="s")
    ga = build_signed_artifact(t, algorithm=ALG_ED25519)
    hs = {"cell_id": "c", "shape_id": "s", "runtime_name": "vllm"}
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_coexist_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        hoverstamp=hs,
        governance_attestation=ga.to_dict(),
        mandate=m.to_dict(),
    )
    ev = res["proof"].get("evidence", {})
    assert "hoverstamp" in ev
    assert "governance_attestation" in ev
    assert "mandate" in ev


def test_proof_hash_invariant_to_mandate():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_hash_inv_mandate",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    m = _signed_mandate()
    with_m = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_hash_inv_mandate",
        proof_data=base["proof"]["proof_data"],
        mandate=m.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_m["proof"]["proof_hash"]


# ── Offline verification helper ─────────────────────────────────────

def test_verify_embedded_mandate_positive():
    m = _signed_mandate()
    report = verify_embedded_mandate(m.to_dict())
    assert report["signature_valid"] is True
    assert report["expired"] is False
    assert report["revoked"] is False


def test_verify_embedded_mandate_tampered():
    m = _signed_mandate()
    d = m.to_dict()
    d["issuer"] = "tampered"
    report = verify_embedded_mandate(d)
    assert report["signature_valid"] is False


def test_json_roundtrip():
    m = _signed_mandate()
    wire = json.loads(json.dumps(m.to_dict()))
    report = verify_embedded_mandate(wire)
    assert report["signature_valid"] is True
