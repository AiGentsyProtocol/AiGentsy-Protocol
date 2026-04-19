"""Capability / Resource Graph v1 tests."""

from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
import pytest

import proof_pipe
from protocol.capability_resource_graph import (
    ResourceNode, CapabilityResourceGraph, AvailabilityEvaluation,
    evaluate_availability, verify_embedded_capability_resource_graph,
    SPEC_VERSION,
)
from protocol.consequence_graph import ConsequenceNode, ConsequenceGraph
from protocol.offer_intent_graph import IntentNode, OfferIntentGraph
from protocol.lineage_graph import LineageNode
from protocol.trust_profile import TrustProfile
from protocol.value_flow_graph import ValueClaim, ValueFlowGraph
from protocol.coordination_graph import CommitmentNode, CoordinationGraph
from protocol.mandate_graph import Mandate
from hoverstack.governed_proof import (
    DecisionTranscript, build_signed_artifact, ALG_ED25519,
)


def _nodes():
    return [
        ResourceNode(resource_id="legal_analysis", resource_type="capability",
                      status="available", capability_label="Legal Analysis",
                      capacity_total=10.0, capacity_available=7.0,
                      usable_for_work_classes=["contract_review", "compliance"],
                      required_trust_threshold=50.0),
        ResourceNode(resource_id="daily_budget", resource_type="budget",
                      status="available", capability_label="Daily Spend",
                      budget_available=2500.0,
                      required_authority_scope=["settlement_request"]),
        ResourceNode(resource_id="stripe_rail", resource_type="rail_access",
                      status="available", capability_label="Stripe Payout",
                      usable_for_work_classes=["contract_review"]),
        ResourceNode(resource_id="expired_tool", resource_type="tool_access",
                      status="expired",
                      expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()),
    ]


def _signed_graph():
    g = CapabilityResourceGraph.create(
        issuer="platform", subject_agent="agent_A",
        resource_nodes=_nodes())
    g.sign()
    return g


# ── Creation ─────────────────────────────────────────────────────────

def test_create():
    g = CapabilityResourceGraph.create(issuer="p", subject_agent="a",
                                         resource_nodes=_nodes())
    assert g.resource_graph_id.startswith("crg_")
    assert g.spec_version == SPEC_VERSION
    assert len(g.resource_nodes) == 4


# ── Hash ────────────────────────────────────────────────────────────

def test_hash_deterministic():
    n = [ResourceNode(resource_id="x", resource_type="capability")]
    g1 = CapabilityResourceGraph.create(issuer="p", subject_agent="a",
                                          resource_nodes=n)
    g2 = CapabilityResourceGraph.create(issuer="p", subject_agent="a",
                                          resource_nodes=n)
    g1.resource_graph_id = g2.resource_graph_id = "FIXED"
    g1.created_at = g2.created_at = "FIXED"
    assert g1.compute_resource_graph_hash() == g2.compute_resource_graph_hash()


def test_hash_excludes_sig():
    g = _signed_graph()
    h = g.compute_resource_graph_hash()
    g.resource_graph_hash = "x"
    g.signature = "x"
    assert g.compute_resource_graph_hash() == h


def test_hash_changes():
    g = _signed_graph()
    h1 = g.compute_resource_graph_hash()
    g.issuer = "different"
    assert g.compute_resource_graph_hash() != h1


# ── Signing ─────────────────────────────────────────────────────────

def test_sign_verify():
    g = _signed_graph()
    assert g.algorithm == "ed25519"
    assert g.verify_signature() is True


def test_tamper():
    g = _signed_graph()
    g.resource_nodes[0].capacity_available = 999.0
    assert g.verify_signature() is False


def test_public_key_verification():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    g = _signed_graph()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(g.public_key))
    assert g.verify_signature(ed25519_public_key=pub) is True


# ── Graph inspection ────────────────────────────────────────────────

def test_available_nodes():
    g = _signed_graph()
    assert len(g.available_nodes()) == 3


def test_blocked_expired_nodes():
    g = _signed_graph()
    assert len(g.blocked_nodes()) == 1


def test_capabilities_for_work_class():
    g = _signed_graph()
    caps = g.capabilities_for_work_class("contract_review")
    ids = {n.resource_id for n in caps}
    assert "legal_analysis" in ids
    assert "stripe_rail" in ids


# ── Availability evaluation ─────────────────────────────────────────

def test_eval_available_capability():
    g = _signed_graph()
    r = evaluate_availability(
        g, "legal_analysis",
        requested_work_class="contract_review",
        requesting_agent_trust=75.0,
    )
    assert r.usable is True


def test_eval_exhausted_capacity():
    nodes = _nodes()
    nodes[0].capacity_available = 0.0
    g = CapabilityResourceGraph.create(issuer="p", subject_agent="a",
                                         resource_nodes=nodes)
    g.sign()
    r = evaluate_availability(g, "legal_analysis")
    assert r.usable is False
    assert "capacity_exhausted" in r.checks_failed


def test_eval_budget_exhausted():
    nodes = _nodes()
    nodes[1].budget_available = 0.0
    g = CapabilityResourceGraph.create(issuer="p", subject_agent="a",
                                         resource_nodes=nodes)
    g.sign()
    r = evaluate_availability(g, "daily_budget")
    assert r.usable is False
    assert "budget_exhausted" in r.checks_failed


def test_eval_trust_below():
    g = _signed_graph()
    r = evaluate_availability(
        g, "legal_analysis", requesting_agent_trust=30.0)
    assert r.usable is False
    assert any("trust_below" in f for f in r.checks_failed)


def test_eval_authority_scope_insufficient():
    g = _signed_graph()
    r = evaluate_availability(
        g, "daily_budget", requesting_agent_scope=set())
    assert r.usable is False
    assert "authority_scope_insufficient" in r.checks_failed


def test_eval_authority_scope_met():
    g = _signed_graph()
    r = evaluate_availability(
        g, "daily_budget",
        requesting_agent_scope={"settlement_request", "proof_create"})
    assert r.usable is True


def test_eval_work_class_not_supported():
    g = _signed_graph()
    r = evaluate_availability(
        g, "legal_analysis",
        requested_work_class="quantum_physics",
        requesting_agent_trust=90.0)
    assert r.usable is False
    assert any("work_class_not_supported" in f for f in r.checks_failed)


def test_eval_expired_resource():
    g = _signed_graph()
    r = evaluate_availability(g, "expired_tool")
    assert r.usable is False
    assert any("resource_expired" in f for f in r.checks_failed)


def test_eval_not_found():
    g = _signed_graph()
    r = evaluate_availability(g, "NONEXISTENT")
    assert r.usable is False
    assert any("resource_not_found" in f for f in r.checks_failed)


# ── ProofPack embedding ────────────────────────────────────────────

def test_proofpack_without_resource_graph():
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_no_crg",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "capability_resource_graph" not in ev


def test_proofpack_embeds_resource_graph():
    g = _signed_graph()
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_with_crg_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        capability_resource_graph=g.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert "capability_resource_graph" in ev


def test_all_ten_primitives_coexist():
    crg = _signed_graph()
    csg = ConsequenceGraph.create(issuer="p", subject_agent="a",
        consequence_nodes=[ConsequenceNode(consequence_id="c1")])
    csg.sign()
    oig = OfferIntentGraph.create(issuer="p", subject_agent="a",
        intent_nodes=[IntentNode(intent_id="i1")])
    oig.sign()
    lin = LineageNode.create(issuer="p", subject_agent="a", parent_agent="p")
    lin.sign()
    tp = TrustProfile.create(subject_agent="a", issuer="p", ocs_score=80.0)
    tp.sign()
    vfg = ValueFlowGraph.create(issuer="p", claims=[
        ValueClaim(claim_id="v1", beneficiary="a", amount=100.0)])
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
        agent_username="t", deal_id="deal_10prim_1",
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
        consequence_graph=csg.to_dict(),
        capability_resource_graph=crg.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert set(ev.keys()) == {
        "hoverstamp", "governance_attestation", "mandate",
        "coordination_graph", "value_flow_graph", "trust_profile",
        "lineage_graph", "offer_intent_graph", "consequence_graph",
        "capability_resource_graph",
    }


def test_proof_hash_invariant():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_crg_hash_inv",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    g = _signed_graph()
    with_crg = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_crg_hash_inv",
        proof_data=base["proof"]["proof_data"],
        capability_resource_graph=g.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_crg["proof"]["proof_hash"]


# ── Offline verification ────────────────────────────────────────────

def test_verify_positive():
    g = _signed_graph()
    r = verify_embedded_capability_resource_graph(g.to_dict())
    assert r["signature_valid"] is True
    assert r["resource_count"] == 4
    assert r["available"] == 3


def test_verify_tampered():
    g = _signed_graph()
    d = g.to_dict()
    d["issuer"] = "tampered"
    r = verify_embedded_capability_resource_graph(d)
    assert r["signature_valid"] is False


def test_json_roundtrip():
    g = _signed_graph()
    wire = json.loads(json.dumps(g.to_dict()))
    r = verify_embedded_capability_resource_graph(wire)
    assert r["signature_valid"] is True
