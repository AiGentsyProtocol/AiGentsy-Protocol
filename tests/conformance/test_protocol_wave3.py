"""
Protocol Wave 3 Conformance Tests — SLAs, Referrals, Invoicing
================================================================

Run: pytest tests/conformance/test_protocol_wave3.py -v
"""

import json
import os
import shutil
import pytest
from typing import Dict, Any


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path):
    base = str(tmp_path)
    os.environ["SLA_DIR"] = f"{base}/sla"
    os.environ["REFERRAL_DIR"] = f"{base}/ref"
    os.environ["INVOICE_DIR"] = f"{base}/inv"
    os.environ["DISPUTE_ARB_DIR"] = f"{base}/darb"

    import protocol.executable_sla as m1; m1._store = None
    import protocol.referral_graph as m2; m2._store = None
    import protocol.invoice as m3; m3._store = None
    import protocol.dispute_arbitration as m4; m4._store = None
    yield


class TestExecutableSLAs:
    def test_create_sla(self):
        from protocol.executable_sla import get_sla_store
        store = get_sla_store()
        sla = store.create("agent_1", conditions=[
            {"field": "verification_confidence", "op": ">=", "value": 0.8},
        ], guarantees={"delivery_hours": 24})
        assert sla.sla_id.startswith("sla_")
        assert sla.status == "active"
        assert sla.sla_hash and len(sla.sla_hash) == 64

    def test_evaluate_all_pass(self):
        from protocol.executable_sla import get_sla_store, evaluate_sla
        store = get_sla_store()
        sla = store.create("a1", conditions=[
            {"field": "verification_confidence", "op": ">=", "value": 0.8},
        ], auto_settle_on_verify=True)
        result = evaluate_sla(sla, {"verification_confidence": 0.9})
        assert result["outcome"] == "auto_settle"
        assert result["all_conditions_passed"]

    def test_evaluate_condition_fail(self):
        from protocol.executable_sla import get_sla_store, evaluate_sla
        store = get_sla_store()
        sla = store.create("a1", conditions=[
            {"field": "verification_confidence", "op": ">=", "value": 0.9},
        ], breach_action="breach")
        result = evaluate_sla(sla, {"verification_confidence": 0.7})
        assert result["outcome"] == "breach"
        assert not result["all_conditions_passed"]

    def test_guarantee_delivery_hours(self):
        from protocol.executable_sla import get_sla_store, evaluate_sla
        store = get_sla_store()
        sla = store.create("a1", conditions=[], guarantees={"delivery_hours": 24})
        result = evaluate_sla(sla, {
            "deal_created_at": "2026-01-01T00:00:00Z",
            "proof_created_at": "2026-01-01T12:00:00Z",
        })
        assert result["guarantee_results"]["delivery_hours"]["met"]
        assert result["outcome"] == "auto_settle"

    def test_guarantee_delivery_breach(self):
        from protocol.executable_sla import get_sla_store, evaluate_sla
        store = get_sla_store()
        sla = store.create("a1", conditions=[], guarantees={"delivery_hours": 1},
                           breach_action="breach")
        result = evaluate_sla(sla, {
            "deal_created_at": "2026-01-01T00:00:00Z",
            "proof_created_at": "2026-01-01T12:00:00Z",
        })
        assert not result["guarantee_results"]["delivery_hours"]["met"]
        assert result["outcome"] == "breach"

    def test_attach_deal(self):
        from protocol.executable_sla import get_sla_store
        store = get_sla_store()
        sla = store.create("a1", conditions=[])
        assert store.attach_deal(sla.sla_id, "deal_xyz")
        assert store.get_by_deal("deal_xyz").sla_id == sla.sla_id

    def test_sla_hash_deterministic(self):
        from protocol.executable_sla import _compute_sla_hash
        h1 = _compute_sla_hash([{"field": "x", "op": ">=", "value": 1}], {"delivery_hours": 24})
        h2 = _compute_sla_hash([{"field": "x", "op": ">=", "value": 1}], {"delivery_hours": 24})
        assert h1 == h2
        assert len(h1) == 64


class TestReferralGraph:
    def test_register_link(self):
        from protocol.referral_graph import get_referral_store
        store = get_referral_store()
        link = store.register_link("agent_A", "agent_B")
        assert link.link_id.startswith("ref_")
        assert link.referrer_agent_id == "agent_A"

    def test_idempotent_register(self):
        from protocol.referral_graph import get_referral_store
        store = get_referral_store()
        l1 = store.register_link("A", "B")
        l2 = store.register_link("C", "B")  # B already referred
        assert l1.link_id == l2.link_id

    def test_self_referral_rejected(self):
        from protocol.referral_graph import get_referral_store
        store = get_referral_store()
        with pytest.raises(ValueError):
            store.register_link("A", "A")

    def test_chain_walk(self):
        from protocol.referral_graph import get_referral_store
        store = get_referral_store()
        store.register_link("A", "B")
        store.register_link("B", "C")
        store.register_link("C", "D")
        chain = store.get_chain("D")
        assert chain == ["C", "B", "A"]

    def test_chain_max_depth(self):
        from protocol.referral_graph import get_referral_store, MAX_CHAIN_DEPTH
        store = get_referral_store()
        agents = [f"agent_{i}" for i in range(10)]
        for i in range(len(agents) - 1):
            store.register_link(agents[i], agents[i + 1])
        chain = store.get_chain(agents[-1])
        assert len(chain) <= MAX_CHAIN_DEPTH

    def test_record_attribution(self):
        from protocol.referral_graph import get_referral_store, REFERRAL_SHARE_PCT
        store = get_referral_store()
        store.register_link("A", "B")
        attr = store.record_attribution("deal_1", "B", 1000.0)
        assert attr is not None
        assert attr.referral_amount_usd == round(1000 * REFERRAL_SHARE_PCT, 2)
        assert attr.referrer_chain == ["A"]

    def test_no_referrer_returns_none(self):
        from protocol.referral_graph import get_referral_store
        store = get_referral_store()
        attr = store.record_attribution("deal_1", "nobody", 1000.0)
        assert attr is None

    def test_stats(self):
        from protocol.referral_graph import get_referral_store
        store = get_referral_store()
        store.register_link("X", "Y")
        store.record_attribution("d_stats", "Y", 1000.0)
        stats = store.get_stats("X")
        assert stats["total_referrals"] == 1
        assert stats["total_referral_revenue_usd"] > 0


class TestInvoicing:
    def test_create_invoice(self):
        from protocol.invoice import get_invoice_store
        store = get_invoice_store()
        inv = store.create(deal_id="deal_inv_1", issuer_name="Seller", buyer_name="Buyer",
                           subtotal_usd=100, total_usd=100, protocol_fee_usd=3.08)
        assert inv.invoice_id.startswith("inv_")
        assert inv.invoice_number.startswith("AIG-")
        assert inv.status == "issued"

    def test_idempotent_per_deal(self):
        from protocol.invoice import get_invoice_store
        store = get_invoice_store()
        i1 = store.create(deal_id="deal_dup", issuer_name="S", subtotal_usd=50, total_usd=50)
        i2 = store.create(deal_id="deal_dup", issuer_name="Different")
        assert i1.invoice_id == i2.invoice_id

    def test_get_by_deal(self):
        from protocol.invoice import get_invoice_store
        store = get_invoice_store()
        store.create(deal_id="deal_lookup", subtotal_usd=100, total_usd=100)
        inv = store.get_by_deal("deal_lookup")
        assert inv is not None
        assert inv.deal_id == "deal_lookup"

    def test_invoice_has_proof_url(self):
        from protocol.invoice import get_invoice_store
        store = get_invoice_store()
        inv = store.create(deal_id="deal_proof", proof_url="https://example.com/proof/deal_proof",
                           subtotal_usd=100, total_usd=100)
        assert "proof" in inv.proof_url


class TestDisputeArbitration:
    def test_open_dispute(self):
        from protocol.dispute_arbitration import get_dispute_arb_store
        store = get_dispute_arb_store()
        d = store.open_dispute("deal_d1", "claimant_1", "respondent_1", "Bad delivery")
        assert d.dispute_id.startswith("dsp_")
        assert d.status == "opened"

    def test_idempotent_open(self):
        from protocol.dispute_arbitration import get_dispute_arb_store
        store = get_dispute_arb_store()
        d1 = store.open_dispute("deal_d2", "c", "r")
        d2 = store.open_dispute("deal_d2", "x", "y")
        assert d1.dispute_id == d2.dispute_id

    def test_submit_evidence(self):
        from protocol.dispute_arbitration import get_dispute_arb_store
        store = get_dispute_arb_store()
        d = store.open_dispute("deal_d3", "c", "r")
        assert store.submit_evidence(d.dispute_id, "c", "https://evidence.com/1", "Screenshot")
        updated = store.get(d.dispute_id)
        assert len(updated.evidence) == 1
        assert updated.status == "evidence_submitted"

    def test_majority_ruling_resolves(self):
        from protocol.dispute_arbitration import get_dispute_arb_store
        store = get_dispute_arb_store()
        d = store.open_dispute("deal_d4", "c", "r")
        store.submit_ruling(d.dispute_id, "arb_1", "claimant_wins", 0.8)
        store.submit_ruling(d.dispute_id, "arb_2", "claimant_wins", 0.6)
        store.submit_ruling(d.dispute_id, "arb_3", "respondent_wins", 0.0)
        updated = store.get(d.dispute_id)
        assert updated.status == "resolved"
        assert updated.resolution == "claimant_wins"
        assert updated.refund_pct == 0.7  # avg of 0.8 and 0.6

    def test_respondent_wins(self):
        from protocol.dispute_arbitration import get_dispute_arb_store
        store = get_dispute_arb_store()
        d = store.open_dispute("deal_d5", "c", "r")
        store.submit_ruling(d.dispute_id, "a1", "respondent_wins", 0.0)
        store.submit_ruling(d.dispute_id, "a2", "respondent_wins", 0.0)
        store.submit_ruling(d.dispute_id, "a3", "claimant_wins", 1.0)
        updated = store.get(d.dispute_id)
        assert updated.resolution == "respondent_wins"
        assert updated.refund_pct == 0.0


class TestFederatedLog:
    def test_witness_registry(self):
        from protocol.federated_log import get_witness_registry
        reg = get_witness_registry()
        witnesses = reg.list_witnesses()
        assert len(witnesses) == 2
        assert witnesses[0]["name"] == "aigentsy_primary"
        assert witnesses[0]["status"] == "active"
        assert witnesses[1]["status"] == "planned"


class TestAgentDirectory:
    def test_build_profile(self):
        from protocol.agent_directory import _build_agent_profile
        profile = _build_agent_profile("nonexistent_agent")
        assert profile["status"] == "unknown"
        assert profile["directory_score"] >= 0


class TestBackwardCompat:
    def test_old_event_hash_stable(self):
        from protocol.event_store import _hash_record
        record = {
            "event_id": "evt_test", "event_type": "SETTLED",
            "deal_id": "deal_123", "actor_id": "agent_A",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"amount": 100}, "prev_hash": "",
        }
        h1 = _hash_record(record)
        h2 = _hash_record(record)
        assert h1 == h2 and len(h1) == 64

    def test_old_bundle_hash_stable(self):
        from protocol.bundle_spec import compute_bundle_hash_v1
        h = compute_bundle_hash_v1("deal_abc", [], [], None)
        assert len(h) == 64
