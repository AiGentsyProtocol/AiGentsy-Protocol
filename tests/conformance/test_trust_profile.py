"""Trust / Reputation Profile v1 tests."""

from __future__ import annotations
import json
import pytest

import proof_pipe
from protocol.trust_profile import (
    TrustProfile, TrustSignal, WorkClassStrength,
    verify_embedded_trust_profile, SPEC_VERSION, SIGNAL_CATEGORIES,
)
from protocol.value_flow_graph import ValueClaim, ValueFlowGraph
from protocol.coordination_graph import CommitmentNode, CoordinationGraph
from protocol.mandate_graph import Mandate
from hoverstack.governed_proof import (
    DecisionTranscript, build_signed_artifact, ALG_ED25519,
)


def _profile(**kw):
    return TrustProfile.create(
        subject_agent="agent_A", issuer="platform",
        ocs_score=82.0, ocs_tier="trusted",
        trust_signals=[
            TrustSignal(category="proof_completion_reliability",
                         score=0.92, sample_count=50,
                         source_refs=["deal_1", "deal_2"],
                         work_class="contract_review"),
            TrustSignal(category="dispute_frequency",
                         score=0.15, sample_count=10),
            TrustSignal(category="coordination_reliability",
                         score=0.88, sample_count=20),
        ],
        work_class_strengths=[
            WorkClassStrength(work_class="contract_review",
                               composite_score=0.91,
                               total_completions=40,
                               total_acceptances=38,
                               total_disputes=1,
                               reliability_rate=0.95),
            WorkClassStrength(work_class="clinical_qa",
                               composite_score=0.55,
                               total_completions=5,
                               total_acceptances=3,
                               total_disputes=1,
                               reliability_rate=0.6),
        ],
        dispute_count=2,
        failed_acceptance_count=1,
        total_proofs_completed=50,
        total_mandates_complied=45,
        total_value_released=12500.0,
        sample_source_refs=["deal_1", "deal_2", "deal_3"],
        **kw,
    )


def _signed_profile(**kw):
    p = _profile(**kw)
    p.sign()
    return p


# ── Creation ─────────────────────────────────────────────────────────

def test_create():
    p = _profile()
    assert p.profile_id.startswith("tp_")
    assert p.spec_version == SPEC_VERSION
    assert p.ocs_score == 82.0
    assert p.ocs_tier == "trusted"
    assert len(p.trust_signals) == 3


# ── Hash ────────────────────────────────────────────────────────────

def test_hash_deterministic():
    p1 = _profile()
    p2 = _profile()
    p1.profile_id = p2.profile_id = "FIXED"
    p1.created_at = p2.created_at = "FIXED"
    assert p1.compute_profile_hash() == p2.compute_profile_hash()


def test_hash_excludes_sig_fields():
    p = _signed_profile()
    h1 = p.compute_profile_hash()
    p.profile_hash = "x"
    p.signature = "x"
    assert p.compute_profile_hash() == h1


def test_hash_changes_on_content():
    p = _signed_profile()
    h1 = p.compute_profile_hash()
    p.ocs_score = 99.0
    assert p.compute_profile_hash() != h1


# ── Signing ─────────────────────────────────────────────────────────

def test_sign_verify():
    p = _signed_profile()
    assert p.algorithm == "ed25519"
    assert p.verify_signature() is True


def test_tamper():
    p = _signed_profile()
    p.ocs_score = 0.0
    assert p.verify_signature() is False


def test_public_key_verification():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    p = _signed_profile()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(p.public_key))
    assert p.verify_signature(ed25519_public_key=pub) is True


# ── Evaluation ──────────────────────────────────────────────────────

def test_positive_signals():
    p = _profile()
    pos = p.positive_signals()
    assert len(pos) == 2  # proof_completion (0.92) + coordination (0.88)
    assert all(s.score > 0.5 for s in pos)


def test_negative_signals():
    p = _profile()
    neg = p.negative_signals()
    assert len(neg) == 1  # dispute_frequency (0.15)
    assert neg[0].category == "dispute_frequency"


def test_strongest_work_classes():
    p = _profile()
    strong = p.strongest_work_classes(2)
    assert strong[0].work_class == "contract_review"


def test_weakest_work_classes():
    p = _profile()
    weak = p.weakest_work_classes(2)
    assert weak[0].work_class == "clinical_qa"


def test_negative_signal_count():
    p = _profile()
    assert p.negative_signal_count() == 3  # 2 disputes + 1 failed acceptance


def test_evidence_backed():
    p = _profile()
    assert p.evidence_backed() is True
    empty = TrustProfile.create(subject_agent="a", issuer="p")
    assert empty.evidence_backed() is False


def test_summary():
    p = _profile()
    s = p.summary()
    assert s["ocs_score"] == 82.0
    assert s["positive_signals"] == 2
    assert s["negative_signals"] == 1
    assert s["evidence_backed"] is True
    assert "contract_review" in s["strongest_work_classes"]


# ── Work-class-specific ─────────────────────────────────────────────

def test_work_class_signal_specificity():
    """Signals can be per-work-class."""
    p = _profile()
    wc_signals = [s for s in p.trust_signals if s.work_class]
    assert len(wc_signals) >= 1
    assert wc_signals[0].work_class == "contract_review"


# ── ProofPack embedding ────────────────────────────────────────────

def test_proofpack_without_trust_profile():
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_no_tp",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "trust_profile" not in ev


def test_proofpack_embeds_trust_profile():
    p = _signed_profile()
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_with_tp_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        trust_profile=p.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert "trust_profile" in ev
    assert ev["trust_profile"]["ocs_score"] == 82.0


def test_all_six_primitives_coexist():
    tp = _signed_profile()
    vfg = ValueFlowGraph.create(issuer="p", claims=[
        ValueClaim(claim_id="c1", beneficiary="a", amount=100.0)])
    vfg.sign()
    cg = CoordinationGraph.create(issuer="p", commitments=[
        CommitmentNode(commitment_id="X", responsible_agent="a")])
    cg.sign()
    m = Mandate.create(issuer="p", subject_agent="a",
                        allowed_actions=["proof_create"])
    m.sign()
    t = DecisionTranscript(cell_id="c", shape_id="s")
    ga = build_signed_artifact(t, algorithm=ALG_ED25519)
    hs = {"cell_id": "c", "shape_id": "s"}
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_6prim_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        hoverstamp=hs,
        governance_attestation=ga.to_dict(),
        mandate=m.to_dict(),
        coordination_graph=cg.to_dict(),
        value_flow_graph=vfg.to_dict(),
        trust_profile=tp.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert set(ev.keys()) == {
        "hoverstamp", "governance_attestation", "mandate",
        "coordination_graph", "value_flow_graph", "trust_profile",
    }


def test_proof_hash_invariant():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_tp_hash_inv",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    p = _signed_profile()
    with_tp = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_tp_hash_inv",
        proof_data=base["proof"]["proof_data"],
        trust_profile=p.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_tp["proof"]["proof_hash"]


# ── Offline verification ────────────────────────────────────────────

def test_verify_positive():
    p = _signed_profile()
    r = verify_embedded_trust_profile(p.to_dict())
    assert r["signature_valid"] is True
    assert r["ocs_score"] == 82.0
    assert r["evidence_backed"] is True


def test_verify_tampered():
    p = _signed_profile()
    d = p.to_dict()
    d["ocs_score"] = 0.0
    r = verify_embedded_trust_profile(d)
    assert r["signature_valid"] is False


def test_json_roundtrip():
    p = _signed_profile()
    wire = json.loads(json.dumps(p.to_dict()))
    r = verify_embedded_trust_profile(wire)
    assert r["signature_valid"] is True
