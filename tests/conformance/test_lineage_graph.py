"""Lineage / Offspring Graph v1 tests."""

from __future__ import annotations
import json
import pytest

import proof_pipe
from protocol.lineage_graph import (
    LineageNode, InheritedTrait, LineageEconomicLink,
    verify_embedded_lineage, SPEC_VERSION, VALID_DESCENT_TYPES,
)
from protocol.trust_profile import TrustProfile, TrustSignal
from protocol.value_flow_graph import ValueClaim, ValueFlowGraph
from protocol.coordination_graph import CommitmentNode, CoordinationGraph
from protocol.mandate_graph import Mandate
from hoverstack.governed_proof import (
    DecisionTranscript, build_signed_artifact, ALG_ED25519,
)


def _root():
    return LineageNode.create(
        issuer="platform",
        subject_agent="agent_A",
        parent_agent="platform",
        descent_type="template_instantiation",
        generation=0,
        inherited_traits=[
            InheritedTrait(trait_name="ocs_inheritance", trait_value=50.0,
                            inherited=True, source="recursive_spawn"),
        ],
        inherited_rights=["proof_create", "settlement_request", "spawn"],
        retained_constraints=["max_amount_usd<=5000"],
        lineage_economic_links=[
            LineageEconomicLink(link_type="royalty", beneficiary="platform",
                                  share=0.30, generation=0),
        ],
        source_refs=["spawn_record_001"],
        spawn_mandate_id="mnd_abc123",
    )


def _signed_root():
    n = _root()
    n.sign()
    return n


# ── Creation ─────────────────────────────────────────────────────────

def test_create():
    n = _root()
    assert n.lineage_id.startswith("lin_")
    assert n.spec_version == SPEC_VERSION
    assert n.descent_type == "template_instantiation"
    assert n.generation == 0


def test_descent_types_bounded():
    for dt in VALID_DESCENT_TYPES:
        n = LineageNode.create(issuer="p", subject_agent="a",
                                parent_agent="p", descent_type=dt)
        assert n.descent_type == dt


# ── Hash ────────────────────────────────────────────────────────────

def test_hash_deterministic():
    n1 = _root()
    n2 = _root()
    n1.lineage_id = n2.lineage_id = "FIXED"
    n1.created_at = n2.created_at = "FIXED"
    assert n1.compute_lineage_hash() == n2.compute_lineage_hash()


def test_hash_excludes_sig():
    n = _signed_root()
    h = n.compute_lineage_hash()
    n.lineage_hash = "x"
    n.signature = "x"
    assert n.compute_lineage_hash() == h


def test_hash_changes_on_content():
    n = _signed_root()
    h1 = n.compute_lineage_hash()
    n.subject_agent = "different"
    assert n.compute_lineage_hash() != h1


# ── Signing ─────────────────────────────────────────────────────────

def test_sign_verify():
    n = _signed_root()
    assert n.algorithm == "ed25519"
    assert n.verify_signature() is True


def test_tamper():
    n = _signed_root()
    n.parent_agent = "tampered"
    assert n.verify_signature() is False


def test_public_key_verification():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    n = _signed_root()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(n.public_key))
    assert n.verify_signature(ed25519_public_key=pub) is True


# ── Inheritance / spawn_child ───────────────────────────────────────

def test_spawn_child_carries_forward():
    root = _signed_root()
    child = root.spawn_child("agent_B", descent_type="clone")
    assert child.parent_agent == "agent_A"
    assert child.parent_lineage_id == root.lineage_id
    assert child.generation == 1
    assert child.descent_type == "clone"
    assert root.lineage_id in child.ancestor_chain


def test_spawn_child_inherits_constraints():
    root = _signed_root()
    child = root.spawn_child("agent_B", new_constraints=["region=US"])
    assert "max_amount_usd<=5000" in child.retained_constraints
    assert "region=US" in child.new_constraints


def test_spawn_child_inherits_rights():
    root = _signed_root()
    child = root.spawn_child("agent_B")
    assert set(child.inherited_rights) == set(root.inherited_rights)


def test_spawn_child_cascades_economic_links():
    """Parent's royalty link cascades with incremented generation."""
    root = _signed_root()
    child = root.spawn_child("agent_B")
    cascaded = [l for l in child.lineage_economic_links
                 if l.beneficiary == "platform"]
    assert len(cascaded) == 1
    assert cascaded[0].generation == 1  # was 0 on parent


def test_multi_generation_chain():
    root = _signed_root()
    gen1 = root.spawn_child("agent_B", descent_type="derived_agent")
    gen1.sign()
    gen2 = gen1.spawn_child("agent_C", descent_type="fork")
    assert gen2.generation == 2
    assert len(gen2.ancestor_chain) == 2
    assert gen2.ancestor_chain[0] == root.lineage_id
    assert gen2.ancestor_chain[1] == gen1.lineage_id
    # Royalty cascaded twice.
    platform_links = [l for l in gen2.lineage_economic_links
                       if l.beneficiary == "platform"]
    assert platform_links[0].generation == 2


def test_spawn_child_adds_new_economic_links():
    root = _signed_root()
    child = root.spawn_child("agent_B", lineage_economic_links=[
        LineageEconomicLink(link_type="referral_fee", beneficiary="agent_A",
                              share=0.05, generation=0),
    ])
    types = {l.link_type for l in child.lineage_economic_links}
    assert "royalty" in types
    assert "referral_fee" in types


# ── Mutation ────────────────────────────────────────────────────────

def test_mutated_traits_recorded():
    root = _signed_root()
    child = root.spawn_child("agent_B", mutated_traits=[
        InheritedTrait(trait_name="ocs_inheritance", trait_value=75.0,
                        inherited=True, mutated=True,
                        mutation_description="graduated: OCS cap removed"),
    ])
    assert len(child.mutated_traits) == 1
    assert child.mutated_traits[0].mutated is True


# ── ProofPack embedding ────────────────────────────────────────────

def test_proofpack_without_lineage():
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_no_lin",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "lineage_graph" not in ev


def test_proofpack_embeds_lineage():
    n = _signed_root()
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_with_lin_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        lineage_graph=n.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert "lineage_graph" in ev


def test_all_seven_primitives_coexist():
    lin = _signed_root()
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
        agent_username="t", deal_id="deal_7prim_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        hoverstamp=hs,
        governance_attestation=ga.to_dict(),
        mandate=m.to_dict(),
        coordination_graph=cg.to_dict(),
        value_flow_graph=vfg.to_dict(),
        trust_profile=tp.to_dict(),
        lineage_graph=lin.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert set(ev.keys()) == {
        "hoverstamp", "governance_attestation", "mandate",
        "coordination_graph", "value_flow_graph", "trust_profile",
        "lineage_graph",
    }


def test_proof_hash_invariant():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_lin_hash_inv",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    n = _signed_root()
    with_lin = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_lin_hash_inv",
        proof_data=base["proof"]["proof_data"],
        lineage_graph=n.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_lin["proof"]["proof_hash"]


# ── Offline verification ────────────────────────────────────────────

def test_verify_positive():
    n = _signed_root()
    r = verify_embedded_lineage(n.to_dict())
    assert r["signature_valid"] is True
    assert r["generation"] == 0
    assert r["descent_type"] == "template_instantiation"


def test_verify_tampered():
    n = _signed_root()
    d = n.to_dict()
    d["subject_agent"] = "tampered"
    r = verify_embedded_lineage(d)
    assert r["signature_valid"] is False


def test_json_roundtrip():
    n = _signed_root()
    wire = json.loads(json.dumps(n.to_dict()))
    r = verify_embedded_lineage(wire)
    assert r["signature_valid"] is True
