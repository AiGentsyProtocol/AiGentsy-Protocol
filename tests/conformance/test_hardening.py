"""
Hardening Conformance Tests — Zenith Upgrades
===============================================

Deterministic hash vector tests for protocol hardening:
  1. Policy hash determinism
  2. Fee schedule correctness
  3. Ledger dedup key determinism
  4. Verification receipt hash determinism
  5. Line items math invariants
  6. Outbox write idempotency
  7. Job queue dedup
  8. EventStore thread safety (dedup)
"""

import hashlib
import json
import os
import sys
from decimal import Decimal

import pytest

# Load test vectors
_VECTORS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "schemas", "test_vectors.json")
with open(_VECTORS_PATH) as f:
    VECTORS = json.load(f)


class TestPolicyHashVectors:
    """Policy hash = SHA256(json.dumps(predicates, sort_keys=True))[:24]"""

    def test_policy_hash_determinism(self):
        for v in VECTORS.get("policy_hash_vectors", []):
            canonical = json.dumps(v["predicates"], sort_keys=True)
            computed = hashlib.sha256(canonical.encode()).hexdigest()[:24]
            assert computed == v["expected_hash"], (
                f"Policy hash mismatch: {computed} != {v['expected_hash']}"
            )

    def test_policy_hash_stable_across_key_order(self):
        """Predicates with same content in different order should produce same hash."""
        p1 = [{"field": "ocs_min", "op": ">=", "value": 50}]
        p2 = [{"value": 50, "field": "ocs_min", "op": ">="}]
        h1 = hashlib.sha256(json.dumps(p1, sort_keys=True).encode()).hexdigest()[:24]
        h2 = hashlib.sha256(json.dumps(p2, sort_keys=True).encode()).hexdigest()[:24]
        assert h1 == h2


class TestFeeScheduleVectors:
    """Protocol fee = gross * pct + flat."""

    def test_fee_calculation(self):
        for v in VECTORS.get("fee_schedule_vectors", []):
            fee = round(v["gross_amount"] * v["protocol_fee_pct"] + v["protocol_fee_flat"], 2)
            net = round(v["gross_amount"] - fee, 2)
            assert fee == v["expected_fee"], f"Fee: {fee} != {v['expected_fee']}"
            assert net == v["expected_net"], f"Net: {net} != {v['expected_net']}"


class TestDedupKeyVectors:
    """Ledger dedup key = SHA256(canonical JSON)[:24]."""

    def test_dedup_key_determinism(self):
        for v in VECTORS.get("dedup_key_vectors", []):
            m = v["meta"]
            canonical = json.dumps({
                "deal_id": m.get("deal_id", ""),
                "entry_type": v["entry_type"],
                "ref": v["ref"],
                "debit": str(Decimal(v["debit"]).quantize(Decimal("0.01"))),
                "credit": str(Decimal(v["credit"]).quantize(Decimal("0.01"))),
                "currency": m.get("currency", "USD"),
                "counterparty": m.get("from", "") or m.get("to", "") or m.get("counterparty", ""),
                "event_id": m.get("event_id", "") or m.get("tx_id", "") or "",
            }, sort_keys=True)
            computed = hashlib.sha256(canonical.encode()).hexdigest()[:24]
            assert computed == v["expected_hash"], (
                f"Dedup key mismatch: {computed} != {v['expected_hash']}"
            )


class TestReceiptHashVectors:
    """Receipt hash = SHA256(deal_id|proof_hash|provider|verified|confidence)[:24]."""

    def test_receipt_hash_determinism(self):
        for v in VECTORS.get("receipt_hash_vectors", []):
            canonical = f"{v['deal_id']}|{v['proof_hash']}|{v['provider']}|{v['verified']}|{v['confidence']}"
            computed = hashlib.sha256(canonical.encode()).hexdigest()[:24]
            assert computed == v["expected_receipt_hash"], (
                f"Receipt hash mismatch: {computed} != {v['expected_receipt_hash']}"
            )


class TestLineItemsMathVectors:
    """Invariant: gross == platform_fee + protocol_fee + net."""

    def test_splits_sum_to_gross(self):
        for v in VECTORS.get("line_items_math_vectors", []):
            total = v["platform_fee"] + v["protocol_fee"] + v["expected_net"]
            assert abs(total - v["gross"]) < 0.01, (
                f"Splits don't sum: {total} != {v['gross']}"
            )


class TestJobQueueDedup:
    """Job queue dedup: (job_type, deal_id) prevents duplicates."""

    def test_enqueue_dedup(self):
        from protocol.job_queue import JobQueue
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            q = JobQueue(store_dir=tmpdir)
            j1 = q.enqueue("payout", "deal_test_001", {"amount": 100})
            j2 = q.enqueue("payout", "deal_test_001", {"amount": 100})
            assert j1.job_id == j2.job_id, "Same (type, deal_id) should return same job"

    def test_different_types_not_deduped(self):
        from protocol.job_queue import JobQueue
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            q = JobQueue(store_dir=tmpdir)
            j1 = q.enqueue("payout", "deal_test_001")
            j2 = q.enqueue("verify", "deal_test_001")
            assert j1.job_id != j2.job_id


class TestOutboxIdempotency:
    """Outbox → EventStore drain uses event_id dedup."""

    def test_outbox_write_generates_unique_ids(self):
        from protocol.outbox import Outbox
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox = Outbox(store_dir=tmpdir)
            r1 = outbox.write("deal_1", "SETTLED", "agent_1")
            r2 = outbox.write("deal_1", "SETTLED", "agent_1")
            assert r1.outbox_id != r2.outbox_id, "Each write gets unique outbox_id"
            assert r1.event_id != r2.event_id, "Each write gets unique event_id"


class TestEventStoreDedup:
    """EventStore.append() deduplicates by event_id."""

    def test_duplicate_event_id_returns_idempotent(self):
        from protocol.event_store import EventStore
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(store_dir=tmpdir)
            r1 = store.append({
                "event_id": "evt_dedup_test_001",
                "event_type": "TEST",
                "deal_id": "deal_dedup_test",
                "actor_id": "test",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "payload": {},
            })
            r2 = store.append({
                "event_id": "evt_dedup_test_001",
                "event_type": "TEST",
                "deal_id": "deal_dedup_test",
                "actor_id": "test",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "payload": {},
            })
            assert r2.get("_idempotent") is True
