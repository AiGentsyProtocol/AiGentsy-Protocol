"""Offer / Intent Graph v1 tests."""

from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
import pytest

import proof_pipe
from protocol.offer_intent_graph import (
    IntentNode, OfferIntentGraph, CompatibilityResult,
    evaluate_compatibility, verify_embedded_offer_intent_graph,
    SPEC_VERSION, VALID_INTENT_TYPES, VALID_INTENT_STATUSES,
)
from protocol.lineage_graph import LineageNode, InheritedTrait
from protocol.trust_profile import TrustProfile
from protocol.value_flow_graph import ValueClaim, ValueFlowGraph
from protocol.coordination_graph import CommitmentNode, CoordinationGraph
from protocol.mandate_graph import Mandate
from hoverstack.governed_proof import (
    DecisionTranscript, build_signed_artifact, ALG_ED25519,
)


def _offer():
    return IntentNode(
        intent_id="offer_1", intent_type="offer", status="open",
        work_class=["contract_review", "compliance"],
        offered_capabilities=["legal_analysis", "document_extraction"],
        value_expectation={"min_usd": 100, "max_usd": 5000},
        required_mandate_scope=["proof_create", "settlement_request"],
    )


def _request():
    return IntentNode(
        intent_id="req_1", intent_type="request", status="open",
        work_class=["contract_review"],
        requested_capabilities=["legal_analysis"],
        required_trust_thresholds={"ocs_score": 70.0},
        required_mandate_scope=["proof_create"],
    )


def _signed_graph():
    g = OfferIntentGraph.create(
        issuer="platform", subject_agent="agent_A",
        intent_nodes=[_offer(), _request()],
    )
    g.sign()
    return g


# ── Creation ─────────────────────────────────────────────────────────

def test_create():
    g = OfferIntentGraph.create(issuer="p", subject_agent="a",
                                  intent_nodes=[_offer()])
    assert g.intent_graph_id.startswith("oig_")
    assert g.spec_version == SPEC_VERSION
    assert len(g.intent_nodes) == 1


def test_offers_and_requests():
    g = _signed_graph()
    assert len(g.offers()) == 1
    assert len(g.requests()) == 1
    assert len(g.open_nodes()) == 2


# ── Hash ────────────────────────────────────────────────────────────

def test_hash_deterministic():
    g1 = OfferIntentGraph.create(issuer="p", subject_agent="a",
                                   intent_nodes=[_offer()])
    g2 = OfferIntentGraph.create(issuer="p", subject_agent="a",
                                   intent_nodes=[_offer()])
    g1.intent_graph_id = g2.intent_graph_id = "FIXED"
    g1.created_at = g2.created_at = "FIXED"
    assert g1.compute_intent_graph_hash() == g2.compute_intent_graph_hash()


def test_hash_excludes_sig():
    g = _signed_graph()
    h = g.compute_intent_graph_hash()
    g.intent_graph_hash = "x"
    g.signature = "x"
    assert g.compute_intent_graph_hash() == h


def test_hash_changes():
    g = _signed_graph()
    h1 = g.compute_intent_graph_hash()
    g.subject_agent = "different"
    assert g.compute_intent_graph_hash() != h1


# ── Signing ─────────────────────────────────────────────────────────

def test_sign_verify():
    g = _signed_graph()
    assert g.algorithm == "ed25519"
    assert g.verify_signature() is True


def test_tamper():
    g = _signed_graph()
    g.intent_nodes[0].work_class = ["tampered"]
    assert g.verify_signature() is False


def test_public_key_verification():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    g = _signed_graph()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(g.public_key))
    assert g.verify_signature(ed25519_public_key=pub) is True


# ── Compatibility evaluation ────────────────────────────────────────

def test_compatible_offer_request():
    r = evaluate_compatibility(
        _offer(), _request(),
        offer_agent_trust={"ocs_score": 85.0},
    )
    assert r.compatible is True
    assert "work_class_overlap:contract_review" in r.checks_passed
    assert "capabilities_met:legal_analysis" in r.checks_passed
    assert "trust_met:ocs_score>=70.0" in r.checks_passed


def test_no_work_class_overlap():
    offer = _offer()
    offer.work_class = ["data_extraction"]
    r = evaluate_compatibility(offer, _request())
    assert r.compatible is False
    assert "no_work_class_overlap" in r.checks_failed


def test_capabilities_unmet():
    req = _request()
    req.requested_capabilities = ["quantum_computing"]
    r = evaluate_compatibility(_offer(), req)
    assert r.compatible is False
    assert any("capabilities_unmet" in f for f in r.checks_failed)


def test_trust_below_threshold():
    r = evaluate_compatibility(
        _offer(), _request(),
        offer_agent_trust={"ocs_score": 50.0},
    )
    assert r.compatible is False
    assert any("trust_below" in f for f in r.checks_failed)


def test_expired_offer_fails():
    offer = _offer()
    offer.expires_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = evaluate_compatibility(offer, _request())
    assert r.compatible is False
    assert "offer_expired" in r.checks_failed


def test_withdrawn_request_fails():
    req = _request()
    req.withdrawn_at = datetime.now(timezone.utc).isoformat()
    r = evaluate_compatibility(_offer(), req)
    assert r.compatible is False
    assert "request_withdrawn" in r.checks_failed


def test_mandate_scope_compatible():
    r = evaluate_compatibility(_offer(), _request())
    assert any("mandate_scope" in c for c in r.checks_passed)


def test_mandate_scope_incompatible():
    offer = _offer()
    offer.required_mandate_scope = ["read_only"]
    req = _request()
    req.required_mandate_scope = ["proof_create", "settlement_request"]
    r = evaluate_compatibility(offer, req)
    assert "mandate_scope_incompatible" in r.checks_failed


def test_unconstrained_work_class():
    offer = _offer()
    offer.work_class = []
    req = _request()
    req.work_class = []
    r = evaluate_compatibility(offer, req, offer_agent_trust={"ocs_score": 80})
    assert "work_class_unconstrained" in r.checks_passed


# ── ProofPack embedding ────────────────────────────────────────────

def test_proofpack_without_intent():
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_no_oig",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "offer_intent_graph" not in ev


def test_proofpack_embeds_intent():
    g = _signed_graph()
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_with_oig_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        offer_intent_graph=g.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert "offer_intent_graph" in ev


def test_all_eight_primitives_coexist():
    oig = _signed_graph()
    lin = LineageNode.create(issuer="p", subject_agent="a", parent_agent="p")
    lin.sign()
    tp = TrustProfile.create(subject_agent="a", issuer="p", ocs_score=80.0)
    tp.sign()
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
        agent_username="t", deal_id="deal_8prim_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        hoverstamp=hs,
        governance_attestation=ga.to_dict(),
        mandate=m.to_dict(),
        coordination_graph=cg.to_dict(),
        value_flow_graph=vfg.to_dict(),
        trust_profile=tp.to_dict(),
        lineage_graph=lin.to_dict(),
        offer_intent_graph=oig.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert set(ev.keys()) == {
        "hoverstamp", "governance_attestation", "mandate",
        "coordination_graph", "value_flow_graph", "trust_profile",
        "lineage_graph", "offer_intent_graph",
    }


def test_proof_hash_invariant():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_oig_hash_inv",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    g = _signed_graph()
    with_oig = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_oig_hash_inv",
        proof_data=base["proof"]["proof_data"],
        offer_intent_graph=g.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_oig["proof"]["proof_hash"]


# ── Offline verification ────────────────────────────────────────────

def test_verify_positive():
    g = _signed_graph()
    r = verify_embedded_offer_intent_graph(g.to_dict())
    assert r["signature_valid"] is True
    assert r["offers"] == 1
    assert r["requests"] == 1


def test_verify_tampered():
    g = _signed_graph()
    d = g.to_dict()
    d["subject_agent"] = "tampered"
    r = verify_embedded_offer_intent_graph(d)
    assert r["signature_valid"] is False


def test_json_roundtrip():
    g = _signed_graph()
    wire = json.loads(json.dumps(g.to_dict()))
    r = verify_embedded_offer_intent_graph(wire)
    assert r["signature_valid"] is True
