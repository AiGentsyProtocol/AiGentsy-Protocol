"""Value Flow / Settlement Graph v1 tests."""

from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
import pytest

import proof_pipe
from protocol.value_flow_graph import (
    ValueClaim, ValueFlowGraph, ValueEvaluation,
    evaluate_release, verify_embedded_value_flow_graph, SPEC_VERSION,
)
from protocol.coordination_graph import CommitmentNode, CoordinationGraph
from protocol.mandate_graph import Mandate
from hoverstack.governed_proof import (
    DecisionTranscript, build_signed_artifact, ALG_ED25519,
)


def _claims():
    return [
        ValueClaim(claim_id="root", claim_label="project_total",
                    beneficiary="project_escrow", amount=1000.0,
                    asset_type="USD", status="eligible"),
        ValueClaim(claim_id="split_A", claim_label="agent_1_share",
                    beneficiary="agent_1", amount=600.0,
                    parent_claim_id="root",
                    depends_on_commitments=["draft"],
                    requires_proof_types=["completion_photo"],
                    status="eligible"),
        ValueClaim(claim_id="split_B", claim_label="agent_2_share",
                    beneficiary="agent_2", amount=300.0,
                    parent_claim_id="root",
                    depends_on_commitments=["compliance"],
                    status="eligible"),
        ValueClaim(claim_id="split_C", claim_label="platform_fee",
                    beneficiary="platform", amount=100.0,
                    parent_claim_id="root",
                    depends_on_claims=["split_A", "split_B"],
                    status="pending"),
    ]


def _signed_graph(**kw):
    g = ValueFlowGraph.create(issuer="platform", claims=_claims(), **kw)
    g.sign()
    return g


# ── Creation ─────────────────────────────────────────────────────────

def test_create():
    g = ValueFlowGraph.create(issuer="p", claims=_claims())
    assert g.value_graph_id.startswith("vfg_")
    assert g.spec_version == SPEC_VERSION
    assert len(g.claims) == 4


def test_total_amount():
    g = _signed_graph()
    # Only non-child claims (root has no parent_claim_id).
    assert g.total_amount() == 1000.0


# ── Hash determinism ────────────────────────────────────────────────

def test_hash_deterministic():
    g1 = ValueFlowGraph.create(issuer="p", claims=_claims())
    g2 = ValueFlowGraph.create(issuer="p", claims=_claims())
    g1.value_graph_id = g2.value_graph_id = "FIXED"
    g1.created_at = g2.created_at = "FIXED"
    assert g1.compute_value_graph_hash() == g2.compute_value_graph_hash()


def test_hash_excludes_signature_fields():
    g = _signed_graph()
    h1 = g.compute_value_graph_hash()
    g.value_graph_hash = "x"
    g.signature = "x"
    assert g.compute_value_graph_hash() == h1


def test_hash_changes_on_content():
    g = _signed_graph()
    h1 = g.compute_value_graph_hash()
    g.issuer = "different"
    assert g.compute_value_graph_hash() != h1


# ── Signing ─────────────────────────────────────────────────────────

def test_sign_verify():
    g = _signed_graph()
    assert g.algorithm == "ed25519"
    assert g.verify_signature() is True


def test_tamper():
    g = _signed_graph()
    g.claims[0].amount = 9999.0
    assert g.verify_signature() is False


def test_public_key_verification():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    g = _signed_graph()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(g.public_key))
    assert g.verify_signature(ed25519_public_key=pub) is True


# ── Graph inspection ────────────────────────────────────────────────

def test_root_claims():
    g = _signed_graph()
    roots = g.root_claims()
    assert [c.claim_id for c in roots] == ["root"]


def test_split_children():
    g = _signed_graph()
    kids = g.split_children("root")
    assert {c.claim_id for c in kids} == {"split_A", "split_B", "split_C"}


# ── Release evaluation ──────────────────────────────────────────────

def test_eval_all_conditions_met():
    g = _signed_graph()
    r = evaluate_release(
        g, "split_A", beneficiary="agent_1",
        satisfied_commitments={"draft"},
        available_proofs={"completion_photo"},
    )
    assert r.valid is True


def test_eval_commitment_not_satisfied():
    g = _signed_graph()
    r = evaluate_release(g, "split_A", satisfied_commitments=set())
    assert r.valid is False
    assert any("commitment_not_satisfied" in f for f in r.checks_failed)


def test_eval_proof_missing():
    g = _signed_graph()
    r = evaluate_release(
        g, "split_A", satisfied_commitments={"draft"},
        available_proofs=set(),
    )
    assert r.valid is False
    assert any("proof_missing" in f for f in r.checks_failed)


def test_eval_claim_dep_not_released():
    g = _signed_graph()
    r = evaluate_release(g, "split_C", released_claims=set())
    assert r.valid is False
    assert any("claim_dep_not_released" in f for f in r.checks_failed)


def test_eval_claim_dep_satisfied():
    g = _signed_graph()
    r = evaluate_release(
        g, "split_C", released_claims={"split_A", "split_B"},
    )
    assert r.valid is True


def test_eval_beneficiary_mismatch():
    g = _signed_graph()
    r = evaluate_release(g, "split_A", beneficiary="wrong_agent",
                          satisfied_commitments={"draft"},
                          available_proofs={"completion_photo"})
    assert r.valid is False
    assert any("beneficiary_mismatch" in f for f in r.checks_failed)


def test_eval_disputed_claim():
    claims = _claims()
    claims[1].status = "disputed"
    claims[1].dispute_state = "under_review"
    g = ValueFlowGraph.create(issuer="p", claims=claims)
    g.sign()
    r = evaluate_release(g, "split_A", satisfied_commitments={"draft"},
                          available_proofs={"completion_photo"})
    assert r.valid is False
    assert "claim_disputed" in r.checks_failed


def test_eval_held_claim():
    claims = _claims()
    claims[1].status = "held"
    claims[1].hold_reason = "pending_review"
    g = ValueFlowGraph.create(issuer="p", claims=claims)
    g.sign()
    r = evaluate_release(g, "split_A", satisfied_commitments={"draft"},
                          available_proofs={"completion_photo"})
    assert r.valid is False
    assert any("held:" in f for f in r.checks_failed)


def test_eval_expired_claim():
    claims = _claims()
    claims[1].deadline = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    g = ValueFlowGraph.create(issuer="p", claims=claims)
    g.sign()
    r = evaluate_release(g, "split_A")
    assert r.valid is False
    assert "claim_expired" in r.checks_failed


def test_eval_claim_not_found():
    g = _signed_graph()
    r = evaluate_release(g, "NONEXISTENT")
    assert r.valid is False
    assert any("claim_not_found" in f for f in r.checks_failed)


def test_eval_requires_acceptance():
    claims = _claims()
    claims[1].requires_acceptance = True
    g = ValueFlowGraph.create(issuer="p", claims=claims)
    g.sign()
    r = evaluate_release(
        g, "split_A", satisfied_commitments={"draft"},
        available_proofs={"completion_photo"},
        accepted_commitments=set(),
    )
    assert r.valid is False
    assert "acceptance_not_met" in r.checks_failed

    r2 = evaluate_release(
        g, "split_A", satisfied_commitments={"draft"},
        available_proofs={"completion_photo"},
        accepted_commitments={"draft"},
    )
    assert r2.valid is True


# ── ProofPack embedding ────────────────────────────────────────────

def test_proofpack_without_value_graph():
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_no_vfg",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    ev = res["proof"].get("evidence", {})
    assert "value_flow_graph" not in ev


def test_proofpack_embeds_value_graph():
    g = _signed_graph()
    res = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_with_vfg_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        value_flow_graph=g.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert "value_flow_graph" in ev
    assert ev["value_flow_graph"]["value_graph_id"] == g.value_graph_id


def test_all_five_primitives_coexist():
    vfg = _signed_graph()
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
        agent_username="t", deal_id="deal_5prim_1",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
        hoverstamp=hs,
        governance_attestation=ga.to_dict(),
        mandate=m.to_dict(),
        coordination_graph=cg.to_dict(),
        value_flow_graph=vfg.to_dict(),
    )
    ev = res["proof"]["evidence"]
    assert set(ev.keys()) == {
        "hoverstamp", "governance_attestation", "mandate",
        "coordination_graph", "value_flow_graph",
    }


def test_proof_hash_invariant():
    base = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_vfg_hash_inv",
        proof_data={"photo_url": "u", "timestamp": "t",
                    "location": "r", "vertical": "marketing"},
    )
    g = _signed_graph()
    with_vfg = proof_pipe.create_proof(
        proof_type="completion_photo", source="manual",
        agent_username="t", deal_id="deal_vfg_hash_inv",
        proof_data=base["proof"]["proof_data"],
        value_flow_graph=g.to_dict(),
    )
    assert base["proof"]["proof_hash"] == with_vfg["proof"]["proof_hash"]


# ── Offline verification ────────────────────────────────────────────

def test_verify_embedded_positive():
    g = _signed_graph()
    r = verify_embedded_value_flow_graph(g.to_dict())
    assert r["signature_valid"] is True
    assert r["claim_count"] == 4
    assert r["total_amount"] == 1000.0


def test_verify_embedded_tampered():
    g = _signed_graph()
    d = g.to_dict()
    d["issuer"] = "tampered"
    r = verify_embedded_value_flow_graph(d)
    assert r["signature_valid"] is False


def test_json_roundtrip():
    g = _signed_graph()
    wire = json.loads(json.dumps(g.to_dict()))
    r = verify_embedded_value_flow_graph(wire)
    assert r["signature_valid"] is True
