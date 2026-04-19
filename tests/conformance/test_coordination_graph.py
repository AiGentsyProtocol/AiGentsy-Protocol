"""Coordination Graph v1 tests."""

from __future__ import annotations
import json
import pytest

import proof_pipe
from protocol.coordination_graph import (
    CommitmentNode, CoordinationGraph, CoordinationEvaluation,
    evaluate_transition, verify_embedded_coordination_graph, SPEC_VERSION,
)
from hoverstack.governed_proof import (
    DecisionTranscript, build_signed_artifact, ALG_ED25519,
)
from protocol.mandate_graph import Mandate


def _nodes():
    return [
        CommitmentNode(commitment_id="A", work_label="research",
                        responsible_agent="agent_1", work_class="research",
                        status="completed", parallelizable=True),
        CommitmentNode(commitment_id="B", work_label="draft",
                        responsible_agent="agent_2", work_class="draft",
                        depends_on=["A"], parallelizable=True,
                        joint_completion_group="review_gate",
                        required_proof_types=["completion_photo"],
                        unlocks_consequences=["release"]),
        CommitmentNode(commitment_id="C", work_label="compliance",
                        responsible_agent="agent_3", work_class="compliance",
                        depends_on=["A"], parallelizable=True,
                        joint_completion_group="review_gate",
                        status="completed"),
        CommitmentNode(commitment_id="D", work_label="final_review",
                        responsible_agent="agent_1", work_class="review",
                        depends_on=["B", "C"],
                        unlocks_consequences=["settlement_request"]),
    ]


def _signed_graph(**kw):
    g = CoordinationGraph.create(issuer="platform", commitments=_nodes(), **kw)
    g.sign()
    return g


# ── Creation ─────────────────────────────────────────────────────────

def test_create_populates_fields():
    g = CoordinationGraph.create(issuer="p", commitments=_nodes())
    assert g.graph_id.startswith("cg_")
    assert g.spec_version == SPEC_VERSION
    assert len(g.commitments) == 4


# ── Hash determinism ────────────────────────────────────────────────

def test_hash_deterministic():
    g1 = CoordinationGraph.create(issuer="p", commitments=_nodes())
    g2 = CoordinationGraph.create(issuer="p", commitments=_nodes())
    g1.graph_id = g2.graph_id = "FIXED"
    g1.created_at = g2.created_at = "FIXED"
    assert g1.compute_graph_hash() == g2.compute_graph_hash()


def test_hash_excludes_signature_fields():
    g = _signed_graph()
    h1 = g.compute_graph_hash()
    g.graph_hash = "tampered"
    g.signature = "tampered"
    assert g.compute_graph_hash() == h1


def test_hash_changes_on_content_change():
    g = _signed_graph()
    h1 = g.compute_graph_hash()
    g.issuer = "different"
    assert g.compute_graph_hash() != h1


# ── Signing ─────────────────────────────────────────────────────────

def test_sign_verify_round_trip():
    g = _signed_graph()
    assert g.algorithm == "ed25519"
    assert g.public_key
    assert g.verify_signature() is True


def test_tamper_detection():
    g = _signed_graph()
    g.commitments[0].work_label = "tampered"
    assert g.verify_signature() is False


def test_public_key_only_verification():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    g = _signed_graph()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(g.public_key))
    assert g.verify_signature(ed25519_public_key=pub) is True


# ── Graph inspection ────────────────────────────────────────────────

def test_root_commitments():
    g = _signed_graph()
    roots = g.root_commitments()
    assert [n.commitment_id for n in roots] == ["A"]


def test_leaf_commitments():
    g = _signed_graph()
    leaves = g.leaf_commitments()
    assert "D" in [n.commitment_id for n in leaves]


def test_dependency_chain():
    g = _signed_graph()
    chain = g.dependency_chain("D")
    assert chain[0] == "A"
    assert chain[-1] == "D"


def test_joint_group_members():
    g = _signed_graph()
    members = g.joint_group_members("review_gate")
    ids = {n.commitment_id for n in members}
    assert ids == {"B", "C"}


# ── Transition evaluation ──────────────────────────────────────────

def test_eval_all_deps_satisfied():
    """Set B to in_progress before signing so the signature is valid
    when the evaluator checks it."""
    nodes = _nodes()
    nodes[1].status = "in_progress"  # B
    g = CoordinationGraph.create(issuer="platform", commitments=nodes)
    g.sign()
    r = evaluate_transition(
        g, "B", new_status="completed", acting_agent="agent_2",
        available_proofs={"completion_photo"},
    )
    assert r.valid is True
    assert "graph_signature_valid" in r.checks_passed


def test_eval_dep_not_satisfied():
    g = _signed_graph()
    g.commitments[0].status = "pending"  # A not done
    g.sign()
    r = evaluate_transition(g, "B", new_status="in_progress")
    assert r.valid is False
    assert any("dep_not_satisfied:A" in f for f in r.checks_failed)


def test_eval_joint_group_incomplete():
    g = _signed_graph()
    g.commitments[2].status = "in_progress"  # C not completed
    g.sign()
    r = evaluate_transition(g, "B", new_status="completed",
                             available_proofs={"completion_photo"})
    assert any("joint_group_incomplete" in f for f in r.checks_failed)


def test_eval_joint_group_satisfied():
    g = _signed_graph()
    g.commitments[1].status = "completed"  # B
    g.commitments[2].status = "completed"  # C
    g.sign()
    r = evaluate_transition(g, "B", new_status="accepted",
                             available_proofs={"completion_photo"})
    assert any("joint_group_satisfied" in c for c in r.checks_passed)


def test_eval_agent_mismatch():
    g = _signed_graph()
    r = evaluate_transition(g, "B", acting_agent="wrong_agent")
    assert any("agent_mismatch" in f for f in r.checks_failed)


def test_eval_proof_missing():
    g = _signed_graph()
    r = evaluate_transition(g, "B", available_proofs=set())
    assert any("proof_missing" in f for f in r.checks_failed)


def test_eval_node_not_found():
    g = _signed_graph()
    r = evaluate_transition(g, "NONEXISTENT")
    assert r.valid is False
    assert any("commitment_not_found" in f for f in r.checks_failed)


def test_eval_invalid_status():
    g = _signed_graph()
    r = evaluate_transition(g, "A", new_status="deleted")
    assert any("invalid_status" in f for f in r.checks_failed)


# ── Parallel nodes ──────────────────────────────────────────────────

def test_parallel_nodes_can_advance_independently():
    g = _signed_graph()
    # B and C both depend on A (completed). They should evaluate
    # independently.
    rb = evaluate_transition(g, "B", new_status="in_progress",
                              available_proofs={"completion_photo"})
    rc = evaluate_transition(g, "C", new_status="in_progress")
    assert "dep_satisfied:A" in rb.checks_passed
    assert "dep_satisfied:A" in rc.checks_passed


# ── ProofPack embedding ────────────────────────────────────────────

def test_proofpack_without_coordination_graph():
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_no_cg",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "coordination_graph" not in ev


def test_proofpack_embeds_coordination_graph():
    g = _signed_graph()
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_with_cg_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        coordination_graph=g.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert "coordination_graph" in ev
    assert ev["coordination_graph"]["graph_id"] == g.graph_id


def test_all_four_primitives_coexist():
    g = _signed_graph()
    m = Mandate.create(issuer="p", subject_agent="a",
                        allowed_actions=["proof_create"])
    m.sign()
    t = DecisionTranscript(cell_id="c", shape_id="s")
    ga = build_signed_artifact(t, algorithm=ALG_ED25519)
    hs = {"cell_id": "c", "shape_id": "s"}
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_4prim_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        hoverstamp=hs,
        governance_attestation=ga.to_dict(),
        mandate=m.to_dict(),
        coordination_graph=g.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert "hoverstamp" in ev
    assert "governance_attestation" in ev
    assert "mandate" in ev
    assert "coordination_graph" in ev


def test_proof_hash_invariant():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_cg_hash_inv",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    g = _signed_graph()
    with_cg = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_cg_hash_inv",
        proof_data=base["proof"]["proof_data"],
        coordination_graph=g.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_cg["proof"]["proof_hash"]


# ── Offline verification ────────────────────────────────────────────

def test_verify_embedded_positive():
    g = _signed_graph()
    report = verify_embedded_coordination_graph(g.to_dict())
    assert report["signature_valid"] is True
    assert report["commitment_count"] == 4


def test_verify_embedded_tampered():
    g = _signed_graph()
    d = g.to_dict()
    d["issuer"] = "tampered"
    report = verify_embedded_coordination_graph(d)
    assert report["signature_valid"] is False


def test_json_roundtrip():
    g = _signed_graph()
    wire = json.loads(json.dumps(g.to_dict()))
    report = verify_embedded_coordination_graph(wire)
    assert report["signature_valid"] is True
