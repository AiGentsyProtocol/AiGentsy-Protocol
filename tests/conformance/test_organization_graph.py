"""Swarm / Organization Graph v1 tests."""

from __future__ import annotations
import json
import pytest

import proof_pipe
from protocol.organization_graph import (
    MemberNode, RoleNode, OrganizationGraph, MembershipEvaluation,
    evaluate_membership, verify_embedded_organization_graph, SPEC_VERSION,
)
from protocol.agreement_graph import AgreementNode, AgreementGraph
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


def _roles():
    return [
        RoleNode(role_id="lead", role_label="Lead Agent",
                  role_scope=["contract_review"],
                  authority_bounds=["max_amount_usd<=10000"],
                  rights=["proof_create", "settlement_request", "spawn"]),
        RoleNode(role_id="specialist", role_label="Specialist",
                  role_scope=["compliance"],
                  rights=["proof_create"]),
    ]


def _members():
    return [
        MemberNode(member_id="m1", agent_ref="agent_A",
                    membership_status="active", joined_at="2026-01-01T00:00:00Z",
                    role_refs=["lead"],
                    mandate_refs=["mnd_abc"], trust_refs=["tp_1"]),
        MemberNode(member_id="m2", agent_ref="agent_B",
                    membership_status="active", joined_at="2026-02-01T00:00:00Z",
                    role_refs=["specialist"]),
        MemberNode(member_id="m3", agent_ref="agent_C",
                    membership_status="suspended", suspended_at="2026-03-01T00:00:00Z"),
    ]


def _signed_graph(**kw):
    g = OrganizationGraph.create(
        issuer="platform", organization_id="venture_alpha",
        organization_type="venture",
        member_nodes=_members(), role_nodes=_roles(), **kw)
    g.sign()
    return g


# ── Creation ─────────────────────────────────────────────────────────

def test_create():
    g = OrganizationGraph.create(
        issuer="p", organization_id="v1",
        organization_type="team",
        member_nodes=_members(), role_nodes=_roles())
    assert g.organization_graph_id.startswith("org_")
    assert g.spec_version == SPEC_VERSION
    assert len(g.member_nodes) == 3
    assert len(g.role_nodes) == 2


# ── Hash ────────────────────────────────────────────────────────────

def test_hash_deterministic():
    g1 = OrganizationGraph.create(issuer="p", organization_id="v1",
                                    organization_type="team",
                                    member_nodes=[], role_nodes=[])
    g2 = OrganizationGraph.create(issuer="p", organization_id="v1",
                                    organization_type="team",
                                    member_nodes=[], role_nodes=[])
    g1.organization_graph_id = g2.organization_graph_id = "FIXED"
    g1.created_at = g2.created_at = "FIXED"
    assert g1.compute_organization_graph_hash() == g2.compute_organization_graph_hash()


def test_hash_excludes_sig():
    g = _signed_graph()
    h = g.compute_organization_graph_hash()
    g.organization_graph_hash = "x"
    g.signature = "x"
    assert g.compute_organization_graph_hash() == h


def test_hash_changes():
    g = _signed_graph()
    h1 = g.compute_organization_graph_hash()
    g.organization_id = "different"
    assert g.compute_organization_graph_hash() != h1


# ── Signing ─────────────────────────────────────────────────────────

def test_sign_verify():
    g = _signed_graph()
    assert g.algorithm == "ed25519"
    assert g.verify_signature() is True


def test_tamper():
    g = _signed_graph()
    g.member_nodes[0].agent_ref = "tampered"
    assert g.verify_signature() is False


def test_public_key_verification():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    g = _signed_graph()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(g.public_key))
    assert g.verify_signature(ed25519_public_key=pub) is True


# ── Graph inspection ────────────────────────────────────────────────

def test_active_members():
    g = _signed_graph()
    assert len(g.active_members()) == 2

def test_suspended_members():
    g = _signed_graph()
    assert len(g.suspended_members()) == 1

def test_members_with_role():
    g = _signed_graph()
    leads = g.members_with_role("lead")
    assert len(leads) == 1
    assert leads[0].agent_ref == "agent_A"


# ── Membership evaluation ──────────────────────────────────────────

def test_eval_active_member():
    g = _signed_graph()
    r = evaluate_membership(g, "agent_A", requested_role="lead")
    assert r.valid is True
    assert "membership_active" in r.checks_passed
    assert "role_assigned:lead" in r.checks_passed


def test_eval_suspended_member():
    g = _signed_graph()
    r = evaluate_membership(g, "agent_C")
    assert r.valid is False
    assert "membership_suspended" in r.checks_failed


def test_eval_not_a_member():
    g = _signed_graph()
    r = evaluate_membership(g, "agent_X")
    assert r.valid is False
    assert any("agent_not_member" in f for f in r.checks_failed)


def test_eval_role_not_assigned():
    g = _signed_graph()
    r = evaluate_membership(g, "agent_B", requested_role="lead")
    assert r.valid is False
    assert "role_not_assigned:lead" in r.checks_failed


def test_eval_dissolved_org():
    g = _signed_graph(organization_status="dissolved")
    r = evaluate_membership(g, "agent_A")
    assert r.valid is False
    assert "organization_dissolved" in r.checks_failed


# ── ProofPack embedding ────────────────────────────────────────────

def test_proofpack_without_org():
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_no_org",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "organization_graph" not in ev


def test_proofpack_embeds_org():
    g = _signed_graph()
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_with_org_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        organization_graph=g.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert "organization_graph" in ev


def test_all_twelve_primitives_coexist():
    org = _signed_graph()
    ag = AgreementGraph.create(issuer="p", counterparties=["a"],
        agreement_nodes=[AgreementNode(agreement_id="a1", status="active")])
    ag.sign()
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
        agent_username="t", deal_id="deal_12prim_1",
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
        organization_graph=org.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert set(ev.keys()) == {
        "hoverstamp", "governance_attestation", "mandate",
        "coordination_graph", "value_flow_graph", "trust_profile",
        "lineage_graph", "offer_intent_graph", "consequence_graph",
        "capability_resource_graph", "agreement_graph",
        "organization_graph",
    }


def test_proof_hash_invariant():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_org_hash_inv",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    g = _signed_graph()
    with_org = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_org_hash_inv",
        proof_data=base["proof"]["proof_data"],
        organization_graph=g.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_org["proof"]["proof_hash"]


# ── Offline verification ────────────────────────────────────────────

def test_verify_positive():
    g = _signed_graph()
    r = verify_embedded_organization_graph(g.to_dict())
    assert r["signature_valid"] is True
    assert r["organization_id"] == "venture_alpha"
    assert r["member_count"] == 3
    assert r["active_members"] == 2


def test_verify_tampered():
    g = _signed_graph()
    d = g.to_dict()
    d["organization_id"] = "tampered"
    r = verify_embedded_organization_graph(d)
    assert r["signature_valid"] is False


def test_json_roundtrip():
    g = _signed_graph()
    wire = json.loads(json.dumps(g.to_dict()))
    r = verify_embedded_organization_graph(wire)
    assert r["signature_valid"] is True
