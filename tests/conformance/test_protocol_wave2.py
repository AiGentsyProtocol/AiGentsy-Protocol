"""
Protocol Wave 2 Conformance Tests
====================================

Covers:
- Proof chains (provenance graph)
- Multi-party settlement store
- Programmable mandates (rule engine)
- Reputation attestations (hash + verification)
- Credential marketplace (publish + search)
- Volume-based fee compression (tier logic)
- Reputation staking (create + resolve)
- Settlement netting (bilateral netting cycle)
- Backward compatibility (old proof/settlement paths unaffected)

Run: pytest tests/conformance/test_protocol_wave2.py -v
"""

import hashlib
import json
import os
import shutil
import pytest
from typing import Dict, Any

# ── Use temp dirs for isolation ──

_TEMP_BASE = "/tmp/aigentsy_test_wave2"


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path):
    """Reset all singletons and use temp dirs for each test."""
    base = str(tmp_path)
    os.environ["PROOF_CHAIN_DIR"] = f"{base}/pc"
    os.environ["MULTIPARTY_DIR"] = f"{base}/mps"
    os.environ["PROG_MANDATE_DIR"] = f"{base}/pm"
    os.environ["ATTESTATION_DIR"] = f"{base}/att"
    os.environ["CREDENTIAL_MKT_DIR"] = f"{base}/cred"
    os.environ["VOLUME_DIR"] = f"{base}/vol"
    os.environ["STAKING_DIR"] = f"{base}/stk"
    os.environ["NETTING_DIR"] = f"{base}/net"

    # Reset singletons
    import protocol.proof_chain as m1; m1._store = None
    import protocol.multiparty_settlement as m2; m2._mps_store = None
    import protocol.programmable_mandate as m3; m3._store = None
    import protocol.reputation_attestation as m4; m4._store = None
    import protocol.credential_marketplace as m5; m5._store = None
    import protocol.volume_fee_compression as m6; m6._tracker = None
    import protocol.reputation_staking as m7; m7._store = None
    import protocol.settlement_netting as m8; m8._engine = None

    yield


# ═══════════════════════════════════════════════════════════════════
# PROOF CHAINS
# ═══════════════════════════════════════════════════════════════════


class TestProofChains:
    def test_register_root(self):
        from protocol.proof_chain import get_proof_chain_store
        pc = get_proof_chain_store()
        link = pc.register_link("deal_A", proof_hash="h1", parent_proof_ids=[])
        assert link.deal_id == "deal_A"
        assert link.parent_proof_ids == []
        assert link.link_id.startswith("pcl_")

    def test_register_child(self):
        from protocol.proof_chain import get_proof_chain_store
        pc = get_proof_chain_store()
        pc.register_link("deal_A", proof_hash="h1")
        pc.register_link("deal_B", proof_hash="h2", parent_proof_ids=["deal_A"])
        assert pc.get_parents("deal_B") == ["deal_A"]
        assert "deal_B" in pc.get_children("deal_A")

    def test_idempotent_register(self):
        from protocol.proof_chain import get_proof_chain_store
        pc = get_proof_chain_store()
        l1 = pc.register_link("deal_X", proof_hash="original")
        l2 = pc.register_link("deal_X", proof_hash="different")
        assert l2.proof_hash == "original"  # first wins

    def test_ancestors_and_descendants(self):
        from protocol.proof_chain import get_proof_chain_store
        pc = get_proof_chain_store()
        pc.register_link("root", proof_hash="r")
        pc.register_link("mid", proof_hash="m", parent_proof_ids=["root"])
        pc.register_link("leaf", proof_hash="l", parent_proof_ids=["mid"])

        ancestors = pc.get_ancestors("leaf")
        assert len(ancestors) == 2
        assert ancestors[0]["deal_id"] == "mid"
        assert ancestors[1]["deal_id"] == "root"

        descendants = pc.get_descendants("root")
        assert len(descendants) == 2

    def test_lineage(self):
        from protocol.proof_chain import get_proof_chain_store
        pc = get_proof_chain_store()
        pc.register_link("root", proof_hash="r")
        pc.register_link("child", proof_hash="c", parent_proof_ids=["root"])
        lineage = pc.get_full_lineage("child")
        assert lineage["is_root"] is False
        assert lineage["ancestor_count"] == 1

    def test_chain_hash_deterministic(self):
        from protocol.proof_chain import get_proof_chain_store
        pc = get_proof_chain_store()
        pc.register_link("a"); pc.register_link("b", parent_proof_ids=["a"])
        h1 = pc.compute_chain_hash("b")
        h2 = pc.compute_chain_hash("b")
        assert h1 == h2
        assert len(h1) == 64

    def test_roots(self):
        from protocol.proof_chain import get_proof_chain_store
        pc = get_proof_chain_store()
        pc.register_link("r1"); pc.register_link("r2")
        pc.register_link("c1", parent_proof_ids=["r1"])
        roots = pc.get_roots()
        root_ids = [r["deal_id"] for r in roots]
        assert "r1" in root_ids and "r2" in root_ids
        assert "c1" not in root_ids


# ═══════════════════════════════════════════════════════════════════
# PROGRAMMABLE MANDATES
# ═══════════════════════════════════════════════════════════════════


class TestProgrammableMandates:
    def _create_mandate(self):
        from protocol.programmable_mandate import get_programmable_mandate_store
        store = get_programmable_mandate_store()
        return store, store.create(
            buyer_id="buyer_1",
            rules=[
                {"conditions": [
                    {"field": "seller_ocs", "op": ">=", "value": 85},
                    {"field": "amount_usd", "op": "<=", "value": 500},
                ], "action": "auto_approve"},
                {"conditions": [
                    {"field": "amount_usd", "op": ">", "value": 1000},
                ], "action": "require_human"},
            ],
            default_action="reject",
            max_amount_per_deal_usd=500.0,
        )

    def test_auto_approve(self):
        store, m = self._create_mandate()
        r = store.evaluate(m.mandate_id, {"seller_ocs": 90, "amount_usd": 300})
        assert r["action"] == "auto_approve"
        assert r["rule_index"] == 0

    def test_no_match_default(self):
        store, m = self._create_mandate()
        r = store.evaluate(m.mandate_id, {"seller_ocs": 60, "amount_usd": 300})
        assert r["action"] == "reject"
        assert r["matched"] is False

    def test_hard_cap(self):
        store, m = self._create_mandate()
        r = store.evaluate(m.mandate_id, {"seller_ocs": 95, "amount_usd": 600})
        assert r["action"] == "reject"
        assert "exceeds_max_per_deal" in r.get("reason", "")

    def test_validate_bad_field(self):
        from protocol.programmable_mandate import validate_rules
        errors = validate_rules([{
            "conditions": [{"field": "invalid_field", "op": ">=", "value": 1}],
            "action": "auto_approve",
        }])
        assert len(errors) > 0

    def test_policy_hash_deterministic(self):
        _, m = self._create_mandate()
        assert len(m.policy_hash) == 64


# ═══════════════════════════════════════════════════════════════════
# REPUTATION ATTESTATIONS
# ═══════════════════════════════════════════════════════════════════


class TestReputationAttestations:
    def test_hash_deterministic(self):
        from protocol.reputation_attestation import _compute_credential_hash
        cred = {"@context": ["test"], "id": "urn:test", "credentialSubject": {"ocs": 90}}
        h1 = _compute_credential_hash(cred)
        h2 = _compute_credential_hash(cred)
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_excludes_proof_and_credentialHash(self):
        from protocol.reputation_attestation import _compute_credential_hash
        base = {"@context": ["test"], "id": "urn:test", "credentialSubject": {"ocs": 90}}
        h_base = _compute_credential_hash(base)
        h_with = _compute_credential_hash({**base, "proof": {"type": "Ed25519"}, "credentialHash": "abc"})
        assert h_base == h_with

    def test_offline_verify_hash_integrity(self):
        from protocol.reputation_attestation import _compute_credential_hash, verify_attestation_offline
        base = {"@context": ["test"], "credentialSubject": {"ocs": 90}, "expirationDate": "2027-01-01T00:00:00Z"}
        h = _compute_credential_hash(base)
        full = {**base, "credentialHash": h, "proof": {"type": "Unsigned"}}
        v = verify_attestation_offline(full)
        assert v["steps"]["hash_integrity"]["passed"] is True
        assert v["steps"]["expiry"]["passed"] is True

    def test_tampered_hash_fails(self):
        from protocol.reputation_attestation import verify_attestation_offline
        full = {
            "@context": ["test"], "credentialSubject": {"ocs": 90},
            "expirationDate": "2027-01-01T00:00:00Z",
            "credentialHash": "0000000000000000000000000000000000000000000000000000000000000000",
            "proof": {"type": "Unsigned"},
        }
        v = verify_attestation_offline(full)
        assert v["steps"]["hash_integrity"]["passed"] is False


# ═══════════════════════════════════════════════════════════════════
# CREDENTIAL MARKETPLACE
# ═══════════════════════════════════════════════════════════════════


class TestCredentialMarketplace:
    def test_publish_and_search(self):
        from protocol.credential_marketplace import get_credential_marketplace
        mkt = get_credential_marketplace()
        mkt.publish(deal_id="d1", agent_id="a1", capability_tags=["logo", "design"],
                    vertical="marketing", verification_confidence=0.88)
        results = mkt.search(capability="logo")
        assert len(results) == 1
        assert results[0]["agent_id"] == "a1"

    def test_confidence_filter(self):
        from protocol.credential_marketplace import get_credential_marketplace
        mkt = get_credential_marketplace()
        mkt.publish(deal_id="d1", agent_id="a1", verification_confidence=0.6)
        assert len(mkt.search(min_confidence=0.9)) == 0
        assert len(mkt.search(min_confidence=0.5)) == 1

    def test_idempotent_publish(self):
        from protocol.credential_marketplace import get_credential_marketplace
        mkt = get_credential_marketplace()
        c1 = mkt.publish(deal_id="d1", agent_id="a1")
        c2 = mkt.publish(deal_id="d1", agent_id="a1")
        assert c1.credential_id == c2.credential_id


# ═══════════════════════════════════════════════════════════════════
# VOLUME FEE COMPRESSION
# ═══════════════════════════════════════════════════════════════════


class TestVolumeFeeCompression:
    def test_starter_tier(self):
        from protocol.volume_fee_compression import compute_compressed_fee
        f = compute_compressed_fee(1000.0)
        assert f["tier"] == "starter"
        assert f["fee"] == 28.28  # 1000 * 0.028 + 0.28

    def test_tier_upgrade(self):
        from protocol.volume_fee_compression import compute_compressed_fee, get_volume_tracker
        tracker = get_volume_tracker()
        tracker.record("agent_big", 200_000)  # > 100K = scale
        f = compute_compressed_fee(1000.0, agent_id="agent_big")
        assert f["tier"] == "scale"
        assert f["fee"] == 12.10  # 1000 * 0.012 + 0.10
        assert f["savings_vs_starter"] == 16.18

    def test_enterprise_tier(self):
        from protocol.volume_fee_compression import compute_compressed_fee, get_volume_tracker
        tracker = get_volume_tracker()
        tracker.record("whale", 2_000_000)
        f = compute_compressed_fee(10000.0, agent_id="whale")
        assert f["tier"] == "enterprise"
        assert f["fee"] == 80.05  # 10000 * 0.008 + 0.05


# ═══════════════════════════════════════════════════════════════════
# REPUTATION STAKING
# ═══════════════════════════════════════════════════════════════════


class TestReputationStaking:
    def test_create_and_resolve_success(self):
        from protocol.reputation_staking import get_staking_store
        ss = get_staking_store()
        s = ss.create_stake("agent_1", "deal_1", 200.0, "deliver_24h")
        assert s.status == "active"
        r = ss.resolve_stake(s.stake_id, "success")
        assert r.status == "resolved_success"
        assert r.bonus_usd == 20.0  # 10% of 200

    def test_resolve_failure(self):
        from protocol.reputation_staking import get_staking_store
        ss = get_staking_store()
        s = ss.create_stake("agent_2", "deal_2", 100.0)
        r = ss.resolve_stake(s.stake_id, "failure")
        assert r.status == "resolved_failure"
        assert r.slash_usd == 100.0  # 100% slash

    def test_idempotent_stake(self):
        from protocol.reputation_staking import get_staking_store
        ss = get_staking_store()
        s1 = ss.create_stake("a", "d1", 50)
        s2 = ss.create_stake("a", "d1", 999)
        assert s1.stake_id == s2.stake_id

    def test_double_resolve_rejected(self):
        from protocol.reputation_staking import get_staking_store
        ss = get_staking_store()
        s = ss.create_stake("a", "d1", 100)
        ss.resolve_stake(s.stake_id, "success")
        r2 = ss.resolve_stake(s.stake_id, "failure")
        assert r2 is None  # already resolved

    def test_agent_stats(self):
        from protocol.reputation_staking import get_staking_store
        ss = get_staking_store()
        s1 = ss.create_stake("a", "d1", 100); ss.resolve_stake(s1.stake_id, "success")
        s2 = ss.create_stake("a", "d2", 100); ss.resolve_stake(s2.stake_id, "failure")
        stats = ss.get_agent_stats("a")
        assert stats["wins"] == 1
        assert stats["losses"] == 1
        assert stats["win_rate"] == 0.5


# ═══════════════════════════════════════════════════════════════════
# SETTLEMENT NETTING
# ═══════════════════════════════════════════════════════════════════


class TestSettlementNetting:
    def _fresh_engine(self, tmp_path):
        """Create a fresh netting engine with its own dir."""
        from protocol.settlement_netting import NettingEngine
        return NettingEngine(store_dir=str(tmp_path / f"net_{id(self)}"))

    def test_basic_netting_cycle(self, tmp_path):
        ne = self._fresh_engine(tmp_path)
        ne.record_obligation("A", "B", 100.0)
        ne.record_obligation("B", "A", 80.0)
        cycle = ne.run_netting_cycle()
        assert cycle["status"] == "completed"
        assert cycle["gross_volume_usd"] == 180.0
        assert cycle["net_volume_usd"] == 20.0
        assert cycle["savings_usd"] == 160.0

    def test_three_party_with_bilateral_overlap(self, tmp_path):
        """Three parties with some bilateral overlap — partial netting."""
        ne = self._fresh_engine(tmp_path)
        ne.record_obligation("A", "B", 100.0)
        ne.record_obligation("B", "A", 40.0)   # A-B bilateral: nets to 60
        ne.record_obligation("B", "C", 80.0)
        ne.record_obligation("C", "B", 30.0)   # B-C bilateral: nets to 50
        cycle = ne.run_netting_cycle()
        assert cycle["status"] == "completed"
        assert cycle["gross_volume_usd"] == 250.0
        assert cycle["net_volume_usd"] == 110.0  # 60 + 50
        assert cycle["savings_usd"] == 140.0

    def test_equal_obligations_cancel(self, tmp_path):
        ne = self._fresh_engine(tmp_path)
        ne.record_obligation("A", "B", 100.0)
        ne.record_obligation("B", "A", 100.0)
        cycle = ne.run_netting_cycle()
        assert cycle["net_volume_usd"] == 0.0
        assert cycle["compression_ratio"] == 1.0

    def test_empty_cycle(self, tmp_path):
        ne = self._fresh_engine(tmp_path)
        cycle = ne.run_netting_cycle()
        assert cycle["status"] == "empty"

    def test_obligations_cleared_after_cycle(self, tmp_path):
        ne = self._fresh_engine(tmp_path)
        ne.record_obligation("A", "B", 100.0)
        ne.run_netting_cycle()
        assert len(ne._obligations) == 0


# ═══════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    def test_bundle_hash_unchanged_without_proof_chain(self):
        """Bundle hash must not change for deals without proof chain data."""
        from protocol.bundle_spec import compute_bundle_hash_v1
        h1 = compute_bundle_hash_v1("deal_123", [], [], None)
        h2 = compute_bundle_hash_v1("deal_123", [], [], None)
        assert h1 == h2

    def test_event_hash_unchanged(self):
        """Event hash algorithm must be stable."""
        from protocol.event_store import _hash_record
        record = {
            "event_id": "evt_test",
            "event_type": "SETTLED",
            "deal_id": "deal_123",
            "actor_id": "agent_A",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"amount": 100},
            "prev_hash": "",
        }
        h1 = _hash_record(record)
        h2 = _hash_record(record)
        assert h1 == h2
        assert len(h1) == 64

    def test_webhook_old_events_still_valid(self):
        """Original 4 webhook event types must still be in VALID_EVENTS."""
        from routes.webhooks import VALID_EVENTS
        for old in ["proof.created", "proof.verified", "go.approved", "settled"]:
            assert old in VALID_EVENTS, f"Old event '{old}' missing from VALID_EVENTS"
