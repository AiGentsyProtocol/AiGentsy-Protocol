"""Consequence / State-Change Graph v1 tests."""

from __future__ import annotations
import json
import pytest

import proof_pipe
from protocol.consequence_graph import (
    ConsequenceNode, ConsequenceGraph, ConsequenceEvaluation,
    evaluate_consequence, verify_embedded_consequence_graph, SPEC_VERSION,
)
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
        ConsequenceNode(
            consequence_id="settle", consequence_type="settlement_request",
            status="pending",
            required_proof_refs=["proof_A"],
            required_acceptance_state="accepted",
            allowed_triggering_agent="agent_1",
            unlocks_next=["release_output"],
        ),
        ConsequenceNode(
            consequence_id="release_output", consequence_type="release",
            status="pending",
            blocked_by=["settle"],
            required_coordination_state="completed",
        ),
        ConsequenceNode(
            consequence_id="escalate_if_fail", consequence_type="escalation",
            status="pending",
            escalation_target="admin",
        ),
    ]


def _signed_graph():
    g = ConsequenceGraph.create(
        issuer="platform", subject_agent="agent_1",
        consequence_nodes=_nodes())
    g.sign()
    return g


# ── Creation ─────────────────────────────────────────────────────────

def test_create():
    g = ConsequenceGraph.create(issuer="p", subject_agent="a",
                                  consequence_nodes=_nodes())
    assert g.consequence_graph_id.startswith("csg_")
    assert g.spec_version == SPEC_VERSION
    assert len(g.consequence_nodes) == 3


# ── Hash ────────────────────────────────────────────────────────────

def test_hash_deterministic():
    g1 = ConsequenceGraph.create(issuer="p", subject_agent="a",
                                   consequence_nodes=_nodes())
    g2 = ConsequenceGraph.create(issuer="p", subject_agent="a",
                                   consequence_nodes=_nodes())
    g1.consequence_graph_id = g2.consequence_graph_id = "FIXED"
    g1.created_at = g2.created_at = "FIXED"
    assert g1.compute_consequence_graph_hash() == g2.compute_consequence_graph_hash()


def test_hash_excludes_sig():
    g = _signed_graph()
    h = g.compute_consequence_graph_hash()
    g.consequence_graph_hash = "x"
    g.signature = "x"
    assert g.compute_consequence_graph_hash() == h


def test_hash_changes():
    g = _signed_graph()
    h1 = g.compute_consequence_graph_hash()
    g.issuer = "different"
    assert g.compute_consequence_graph_hash() != h1


# ── Signing ─────────────────────────────────────────────────────────

def test_sign_verify():
    g = _signed_graph()
    assert g.algorithm == "ed25519"
    assert g.verify_signature() is True


def test_tamper():
    g = _signed_graph()
    g.consequence_nodes[0].status = "completed"
    assert g.verify_signature() is False


def test_public_key_verification():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    g = _signed_graph()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(g.public_key))
    assert g.verify_signature(ed25519_public_key=pub) is True


# ── Evaluation ──────────────────────────────────────────────────────

def test_eval_all_conditions_met():
    g = _signed_graph()
    r = evaluate_consequence(
        g, "settle", acting_agent="agent_1",
        satisfied_proofs={"proof_A"},
        accepted_deals={"accepted"},
    )
    assert r.valid is True


def test_eval_proof_not_satisfied():
    g = _signed_graph()
    r = evaluate_consequence(g, "settle", satisfied_proofs=set())
    assert r.valid is False
    assert any("proof_not_satisfied" in f for f in r.checks_failed)


def test_eval_acceptance_not_met():
    g = _signed_graph()
    r = evaluate_consequence(
        g, "settle", satisfied_proofs={"proof_A"},
        accepted_deals=set(),
    )
    assert r.valid is False
    assert "acceptance_not_met" in r.checks_failed


def test_eval_blocked_by():
    g = _signed_graph()
    r = evaluate_consequence(
        g, "release_output",
        satisfied_coordination={"completed"},
    )
    assert r.valid is False
    assert any("blocked_by:settle" in f for f in r.checks_failed)


def test_eval_blocker_cleared():
    nodes = _nodes()
    nodes[0].status = "triggered"
    g = ConsequenceGraph.create(issuer="p", subject_agent="a",
                                  consequence_nodes=nodes)
    g.sign()
    r = evaluate_consequence(
        g, "release_output",
        satisfied_coordination={"completed"},
    )
    assert any("blocker_cleared:settle" in c for c in r.checks_passed)


def test_eval_agent_mismatch():
    g = _signed_graph()
    r = evaluate_consequence(
        g, "settle", acting_agent="wrong_agent",
        satisfied_proofs={"proof_A"}, accepted_deals={"accepted"},
    )
    assert r.valid is False
    assert any("triggering_agent_mismatch" in f for f in r.checks_failed)


def test_eval_node_not_found():
    g = _signed_graph()
    r = evaluate_consequence(g, "NONEXISTENT")
    assert r.valid is False
    assert any("consequence_not_found" in f for f in r.checks_failed)


def test_eval_held_node_blocked():
    nodes = _nodes()
    nodes[0].status = "held"
    g = ConsequenceGraph.create(issuer="p", subject_agent="a",
                                  consequence_nodes=nodes)
    g.sign()
    r = evaluate_consequence(g, "settle")
    assert r.valid is False
    assert any("consequence_held" in f for f in r.checks_failed)


def test_eval_coordination_not_met():
    g = _signed_graph()
    nodes = _nodes()
    nodes[0].status = "triggered"
    g = ConsequenceGraph.create(issuer="p", subject_agent="a",
                                  consequence_nodes=nodes)
    g.sign()
    r = evaluate_consequence(
        g, "release_output", satisfied_coordination=set())
    assert r.valid is False
    assert "coordination_not_met" in r.checks_failed


# ── Graph inspection ────────────────────────────────────────────────

def test_pending_triggered_blocked():
    g = _signed_graph()
    assert len(g.pending_nodes()) == 3
    assert len(g.triggered_nodes()) == 0
    assert len(g.blocked_nodes()) == 0


# ── ProofPack embedding ────────────────────────────────────────────

def test_proofpack_without_consequence():
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_no_csg",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "consequence_graph" not in ev


def test_proofpack_embeds_consequence():
    g = _signed_graph()
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_with_csg_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        consequence_graph=g.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert "consequence_graph" in ev


def test_all_nine_primitives_coexist():
    csg = _signed_graph()
    oig = OfferIntentGraph.create(issuer="p", subject_agent="a",
                                    intent_nodes=[IntentNode(intent_id="i1")])
    oig.sign()
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
        agent_username="t", deal_id="deal_9prim_1",
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
    )
    ev = res["proof"]["evidence"]
    assert set(ev.keys()) == {
        "hoverstamp", "governance_attestation", "mandate",
        "coordination_graph", "value_flow_graph", "trust_profile",
        "lineage_graph", "offer_intent_graph", "consequence_graph",
    }


def test_proof_hash_invariant():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_csg_hash_inv",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    g = _signed_graph()
    with_csg = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_csg_hash_inv",
        proof_data=base["proof"]["proof_data"],
        consequence_graph=g.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_csg["proof"]["proof_hash"]


# ── Offline verification ────────────────────────────────────────────

def test_verify_positive():
    g = _signed_graph()
    r = verify_embedded_consequence_graph(g.to_dict())
    assert r["signature_valid"] is True
    assert r["consequence_count"] == 3


def test_verify_tampered():
    g = _signed_graph()
    d = g.to_dict()
    d["issuer"] = "tampered"
    r = verify_embedded_consequence_graph(d)
    assert r["signature_valid"] is False


def test_json_roundtrip():
    g = _signed_graph()
    wire = json.loads(json.dumps(g.to_dict()))
    r = verify_embedded_consequence_graph(wire)
    assert r["signature_valid"] is True
