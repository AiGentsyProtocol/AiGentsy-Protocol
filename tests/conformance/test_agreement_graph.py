"""Agreement / Contract Graph v1 tests."""

from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
import pytest

import proof_pipe
from protocol.agreement_graph import (
    AgreementNode, AgreementGraph, AgreementEvaluation,
    evaluate_agreement, verify_embedded_agreement_graph, SPEC_VERSION,
)
from protocol.capability_resource_graph import ResourceNode, CapabilityResourceGraph
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
        AgreementNode(
            agreement_id="svc_1", agreement_type="service_agreement",
            status="active",
            resolved_intent_refs=["offer_1", "req_1"],
            counterparty_refs=["agent_A", "agent_B"],
            work_classes=["contract_review"],
            sla_terms={"delivery_hours": 48, "quality_threshold": 0.8},
            proof_requirements=["completion_photo"],
            acceptance_requirements=["human_review"],
            value_term_refs=["vfg_claim_1"],
            rights_granted=["proof_create", "settlement_request"],
            constraints_accepted=["max_amount_usd<=5000"],
            revocation_conditions=["mutual_30d_notice"],
        ),
    ]


def _signed_graph():
    g = AgreementGraph.create(
        issuer="platform",
        counterparties=["agent_A", "agent_B"],
        agreement_nodes=_nodes())
    g.sign()
    return g


# ── Creation ─────────────────────────────────────────────────────────

def test_create():
    g = AgreementGraph.create(issuer="p",
                                counterparties=["a", "b"],
                                agreement_nodes=_nodes())
    assert g.agreement_graph_id.startswith("ag_")
    assert g.spec_version == SPEC_VERSION
    assert len(g.agreement_nodes) == 1
    assert set(g.counterparties) == {"a", "b"}


# ── Hash ────────────────────────────────────────────────────────────

def test_hash_deterministic():
    n = [AgreementNode(agreement_id="x")]
    g1 = AgreementGraph.create(issuer="p", counterparties=["a"],
                                  agreement_nodes=n)
    g2 = AgreementGraph.create(issuer="p", counterparties=["a"],
                                  agreement_nodes=n)
    g1.agreement_graph_id = g2.agreement_graph_id = "FIXED"
    g1.created_at = g2.created_at = "FIXED"
    assert g1.compute_agreement_graph_hash() == g2.compute_agreement_graph_hash()


def test_hash_excludes_sig():
    g = _signed_graph()
    h = g.compute_agreement_graph_hash()
    g.agreement_graph_hash = "x"
    g.signature = "x"
    assert g.compute_agreement_graph_hash() == h


def test_hash_changes():
    g = _signed_graph()
    h1 = g.compute_agreement_graph_hash()
    g.issuer = "different"
    assert g.compute_agreement_graph_hash() != h1


# ── Signing ─────────────────────────────────────────────────────────

def test_sign_verify():
    g = _signed_graph()
    assert g.algorithm == "ed25519"
    assert g.verify_signature() is True


def test_tamper():
    g = _signed_graph()
    g.counterparties = ["tampered"]
    assert g.verify_signature() is False


def test_public_key_verification():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    g = _signed_graph()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(g.public_key))
    assert g.verify_signature(ed25519_public_key=pub) is True


# ── Evaluation ──────────────────────────────────────────────────────

def test_eval_valid_agreement():
    g = _signed_graph()
    r = evaluate_agreement(
        g, "svc_1",
        acting_counterparty="agent_A",
        resolved_intents={"offer_1", "req_1"},
        available_mandates={"proof_create", "settlement_request"},
    )
    assert r.valid is True


def test_eval_counterparty_not_in_agreement():
    g = _signed_graph()
    r = evaluate_agreement(
        g, "svc_1", acting_counterparty="agent_C",
        resolved_intents={"offer_1", "req_1"},
        available_mandates={"proof_create", "settlement_request"},
    )
    assert r.valid is False
    assert any("counterparty_not_in_agreement" in f for f in r.checks_failed)


def test_eval_intent_not_resolved():
    g = _signed_graph()
    r = evaluate_agreement(g, "svc_1", resolved_intents=set())
    assert r.valid is False
    assert any("intent_not_resolved" in f for f in r.checks_failed)


def test_eval_mandate_missing():
    g = _signed_graph()
    r = evaluate_agreement(
        g, "svc_1",
        resolved_intents={"offer_1", "req_1"},
        available_mandates=set(),
    )
    assert r.valid is False
    assert any("mandate_missing" in f for f in r.checks_failed)


def test_eval_expired():
    nodes = _nodes()
    nodes[0].expires_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    g = AgreementGraph.create(issuer="p", counterparties=["a", "b"],
                                agreement_nodes=nodes)
    g.sign()
    r = evaluate_agreement(g, "svc_1")
    assert r.valid is False
    assert "agreement_expired" in r.checks_failed


def test_eval_revoked():
    nodes = _nodes()
    nodes[0].status = "revoked"
    g = AgreementGraph.create(issuer="p", counterparties=["a", "b"],
                                agreement_nodes=nodes)
    g.sign()
    r = evaluate_agreement(g, "svc_1")
    assert r.valid is False
    assert "agreement_revoked" in r.checks_failed


def test_eval_draft():
    nodes = _nodes()
    nodes[0].status = "draft"
    g = AgreementGraph.create(issuer="p", counterparties=["a", "b"],
                                agreement_nodes=nodes)
    g.sign()
    r = evaluate_agreement(g, "svc_1")
    assert r.valid is False
    assert "agreement_still_draft" in r.checks_failed


def test_eval_not_found():
    g = _signed_graph()
    r = evaluate_agreement(g, "NONEXISTENT")
    assert r.valid is False
    assert any("agreement_not_found" in f for f in r.checks_failed)


# ── Graph inspection ────────────────────────────────────────────────

def test_active_agreements():
    g = _signed_graph()
    assert len(g.active_agreements()) == 1


def test_expired_or_revoked():
    g = _signed_graph()
    assert len(g.expired_or_revoked()) == 0


# ── ProofPack embedding ────────────────────────────────────────────

def test_proofpack_without_agreement():
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_no_ag",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "agreement_graph" not in ev


def test_proofpack_embeds_agreement():
    g = _signed_graph()
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_with_ag_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        agreement_graph=g.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert "agreement_graph" in ev


def test_all_eleven_primitives_coexist():
    ag = _signed_graph()
    crg = CapabilityResourceGraph.create(issuer="p", subject_agent="a",
        resource_nodes=[ResourceNode(resource_id="r1")])
    crg.sign()
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
        agent_username="t", deal_id="deal_11prim_1",
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
        agreement_graph=ag.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert set(ev.keys()) == {
        "hoverstamp", "governance_attestation", "mandate",
        "coordination_graph", "value_flow_graph", "trust_profile",
        "lineage_graph", "offer_intent_graph", "consequence_graph",
        "capability_resource_graph", "agreement_graph",
    }


def test_proof_hash_invariant():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_ag_hash_inv",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    g = _signed_graph()
    with_ag = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_ag_hash_inv",
        proof_data=base["proof"]["proof_data"],
        agreement_graph=g.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_ag["proof"]["proof_hash"]


# ── Offline verification ────────────────────────────────────────────

def test_verify_positive():
    g = _signed_graph()
    r = verify_embedded_agreement_graph(g.to_dict())
    assert r["signature_valid"] is True
    assert r["agreement_count"] == 1
    assert r["active"] == 1
    assert "agent_A" in r["counterparties"]


def test_verify_tampered():
    g = _signed_graph()
    d = g.to_dict()
    d["issuer"] = "tampered"
    r = verify_embedded_agreement_graph(d)
    assert r["signature_valid"] is False


def test_json_roundtrip():
    g = _signed_graph()
    wire = json.loads(json.dumps(g.to_dict()))
    r = verify_embedded_agreement_graph(wire)
    assert r["signature_valid"] is True
