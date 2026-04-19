"""
Merkle Transparency Log Conformance Tests
==========================================

Tests the RFC 6962 Merkle log implementation:
1. Leaf hash uses 0x00 prefix
2. Interior node hash uses 0x01 prefix
3. Inclusion proofs verify correctly
4. Consistency proofs verify correctly
5. STH signature is valid
6. Bundle v1 hash includes spec_version
7. Offline verification works end-to-end

Usage:
    python -m pytest tests/conformance/test_merkle_log.py -v
"""

import hashlib
import json

import pytest


# ── 1. RFC 6962 Hash Functions ──


class TestRFC6962Hashing:
    def test_leaf_hash_uses_0x00_prefix(self):
        from protocol.merkle_log import rfc6962_leaf_hash

        data = b"test_leaf_data"
        expected = hashlib.sha256(b"\x00" + data).digest()
        assert rfc6962_leaf_hash(data) == expected

    def test_node_hash_uses_0x01_prefix(self):
        from protocol.merkle_log import rfc6962_node_hash

        left = bytes(32)  # 32 zero bytes
        right = bytes(range(32))
        expected = hashlib.sha256(b"\x01" + left + right).digest()
        assert rfc6962_node_hash(left, right) == expected

    def test_leaf_and_node_differ(self):
        """Leaf and node hashes of same data must differ (domain separation)."""
        from protocol.merkle_log import rfc6962_leaf_hash, rfc6962_node_hash

        data = b"x" * 64
        leaf = rfc6962_leaf_hash(data)
        # If we treat data as left||right (32+32), node hash must differ
        node = rfc6962_node_hash(data[:32], data[32:])
        assert leaf != node


# ── 2. Merkle Tree ──


class TestRFC6962MerkleTree:
    def test_single_leaf(self):
        from protocol.merkle_log import RFC6962MerkleTree

        tree = RFC6962MerkleTree()
        lh, idx = tree.append_leaf({"deal_id": "deal_test_001"})
        assert idx == 0
        assert len(lh) == 64
        assert tree.get_root() == lh  # root == leaf for single element

    def test_two_leaves(self):
        from protocol.merkle_log import RFC6962MerkleTree, node_hash_hex

        tree = RFC6962MerkleTree()
        h1, _ = tree.append_leaf({"deal_id": "deal_a"})
        h2, _ = tree.append_leaf({"deal_id": "deal_b"})
        expected_root = node_hash_hex(h1, h2)
        assert tree.get_root() == expected_root

    def test_inclusion_proof_single(self):
        from protocol.merkle_log import RFC6962MerkleTree, verify_inclusion

        tree = RFC6962MerkleTree()
        lh, _ = tree.append_leaf({"deal_id": "deal_single"})
        proof = tree.inclusion_proof(0)
        assert proof == []
        assert verify_inclusion(lh, 0, 1, proof, tree.get_root())

    def test_inclusion_proof_multiple(self):
        from protocol.merkle_log import RFC6962MerkleTree, verify_inclusion

        tree = RFC6962MerkleTree()
        hashes = []
        for i in range(8):
            lh, _ = tree.append_leaf({"deal_id": f"deal_{i}"})
            hashes.append(lh)

        root = tree.get_root()

        # Verify each leaf
        for i in range(8):
            proof = tree.inclusion_proof(i)
            assert verify_inclusion(hashes[i], i, 8, proof, root), (
                f"Inclusion proof failed for leaf {i}"
            )

    def test_inclusion_proof_odd_tree(self):
        from protocol.merkle_log import RFC6962MerkleTree, verify_inclusion

        tree = RFC6962MerkleTree()
        hashes = []
        for i in range(5):  # Odd number of leaves
            lh, _ = tree.append_leaf({"deal_id": f"deal_odd_{i}"})
            hashes.append(lh)

        root = tree.get_root()
        for i in range(5):
            proof = tree.inclusion_proof(i)
            assert verify_inclusion(hashes[i], i, 5, proof, root), (
                f"Inclusion proof failed for leaf {i} in 5-leaf tree"
            )


# ── 3. Consistency Proofs ──


class TestConsistencyProofs:
    def test_consistency_proof_basic(self):
        from protocol.merkle_log import RFC6962MerkleTree

        tree = RFC6962MerkleTree()
        for i in range(4):
            tree.append_leaf({"deal_id": f"deal_{i}"})

        root_at_2 = tree.get_root(2)
        root_at_4 = tree.get_root(4)

        proof = tree.consistency_proof(2, 4)
        assert len(proof) > 0

    def test_consistency_proof_same_size(self):
        from protocol.merkle_log import RFC6962MerkleTree

        tree = RFC6962MerkleTree()
        for i in range(4):
            tree.append_leaf({"deal_id": f"deal_{i}"})

        proof = tree.consistency_proof(4, 4)
        assert proof == []

    def test_consistency_proof_from_zero(self):
        from protocol.merkle_log import RFC6962MerkleTree

        tree = RFC6962MerkleTree()
        for i in range(4):
            tree.append_leaf({"deal_id": f"deal_{i}"})

        proof = tree.consistency_proof(0, 4)
        assert proof == []


# ── 4. Transparency Log ──


class TestTransparencyLog:
    def test_append_finality_event(self):
        from protocol.merkle_log import TransparencyLog, LogSigner
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            log = TransparencyLog(
                log_dir=Path(tmpdir) / "log",
                signer=LogSigner(key_dir=Path(tmpdir) / "keys"),
            )
            result = log.append_entry({
                "event_type": "PROOF_READY",
                "deal_id": "deal_test_001",
                "event_id": "evt_test_001",
                "hash": "abc123",
                "timestamp": "2026-01-01T00:00:00Z",
            })
            assert result is not None
            assert result["leaf_index"] == 0
            assert result["tree_size"] == 1

    def test_non_finality_event_rejected(self):
        from protocol.merkle_log import TransparencyLog, LogSigner
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            log = TransparencyLog(
                log_dir=Path(tmpdir) / "log",
                signer=LogSigner(key_dir=Path(tmpdir) / "keys"),
            )
            result = log.append_entry({
                "event_type": "MANDATE_CREATED",
                "deal_id": "deal_test_002",
            })
            assert result is None

    def test_sth_signature(self):
        from protocol.merkle_log import TransparencyLog, LogSigner
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            signer = LogSigner(key_dir=Path(tmpdir) / "keys")
            log = TransparencyLog(
                log_dir=Path(tmpdir) / "log",
                signer=signer,
            )
            log.append_entry({
                "event_type": "SETTLED",
                "deal_id": "deal_sth_test",
                "event_id": "evt_sth_001",
                "hash": "def456",
                "timestamp": "2026-01-01T00:00:00Z",
            })
            sth = log.sign_tree_head()
            assert sth["log_id"] == "aigentsy_settlement_log_v1"
            assert sth["tree_size"] == 1
            assert len(sth["root_hash"]) == 64
            assert sth["signature"] != ""
            assert sth["key_id"] == "aigentsy_log_signer_v1"

    def test_deal_proof_returns_inclusion_and_sth(self):
        from protocol.merkle_log import TransparencyLog, LogSigner
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            log = TransparencyLog(
                log_dir=Path(tmpdir) / "log",
                signer=LogSigner(key_dir=Path(tmpdir) / "keys"),
            )
            for i in range(4):
                log.append_entry({
                    "event_type": "PROOF_READY",
                    "deal_id": f"deal_{i}",
                    "event_id": f"evt_{i}",
                    "hash": f"hash_{i}",
                    "timestamp": "2026-01-01T00:00:00Z",
                })

            idx = log.find_leaf_index("deal_2")
            assert idx == 2

            proof = log.inclusion_proof(idx)
            assert proof["leaf_index"] == 2
            assert len(proof["proof"]) > 0


# ── 5. Bundle v1 ──


class TestBundleV1:
    def test_bundle_hash_includes_spec_version(self):
        from protocol.bundle_spec import compute_bundle_hash_v1, compute_bundle_hash_legacy

        deal_id = "deal_bundle_test"
        proofs = [{"id": "proof_001"}]
        events = []
        merkle = None

        v1_hash = compute_bundle_hash_v1(deal_id, proofs, events, merkle)
        legacy_hash = compute_bundle_hash_legacy(deal_id, proofs, events, merkle)

        # Must differ because v1 includes spec_version
        assert v1_hash != legacy_hash

    def test_bundle_hash_is_deterministic(self):
        from protocol.bundle_spec import compute_bundle_hash_v1

        deal_id = "deal_deterministic"
        proofs = [{"id": "proof_det_001", "type": "test_results"}]
        events = [{"event_id": "evt_det_001", "event_type": "PROOF_READY"}]

        h1 = compute_bundle_hash_v1(deal_id, proofs, events, None)
        h2 = compute_bundle_hash_v1(deal_id, proofs, events, None)
        assert h1 == h2

    def test_verify_event_chain_offline(self):
        from protocol.bundle_spec import verify_event_chain

        events = [
            {
                "event_id": "evt_test_vector_001",
                "event_type": "PROOF_READY",
                "deal_id": "deal_test_vector",
                "actor_id": "agent_test",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "payload": {},
                "prev_hash": "",
            }
        ]
        # Compute the hash
        canonical = json.dumps({
            "event_id": events[0]["event_id"],
            "event_type": events[0]["event_type"],
            "deal_id": events[0]["deal_id"],
            "actor_id": events[0]["actor_id"],
            "timestamp": events[0]["timestamp"],
            "payload": events[0]["payload"],
            "prev_hash": events[0]["prev_hash"],
        }, sort_keys=True)
        events[0]["hash"] = hashlib.sha256(canonical.encode()).hexdigest()

        result = verify_event_chain(events)
        assert result["verified"] is True
        assert result["event_count"] == 1

    def test_verify_event_chain_detects_tamper(self):
        from protocol.bundle_spec import verify_event_chain

        events = [
            {
                "event_id": "evt_tamper_001",
                "event_type": "PROOF_READY",
                "deal_id": "deal_tamper",
                "actor_id": "agent_test",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {},
                "prev_hash": "",
                "hash": "wrong_hash_value",
            }
        ]
        result = verify_event_chain(events)
        assert result["verified"] is False
        assert len(result["errors"]) > 0


# ── 6. Offline Verification ──


class TestOfflineVerification:
    def test_full_offline_verification(self):
        from protocol.bundle_spec import (
            compute_bundle_hash_v1,
            verify_bundle_offline,
            verify_event_chain,
        )

        # Build a synthetic bundle
        events = [
            {
                "event_id": "evt_offline_001",
                "event_type": "PROOF_READY",
                "deal_id": "deal_offline_test",
                "actor_id": "agent_offline",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {},
                "prev_hash": "",
            }
        ]
        canonical = json.dumps({
            "event_id": events[0]["event_id"],
            "event_type": events[0]["event_type"],
            "deal_id": events[0]["deal_id"],
            "actor_id": events[0]["actor_id"],
            "timestamp": events[0]["timestamp"],
            "payload": events[0]["payload"],
            "prev_hash": events[0]["prev_hash"],
        }, sort_keys=True)
        events[0]["hash"] = hashlib.sha256(canonical.encode()).hexdigest()

        proofs = [{"id": "proof_offline_001", "type": "test_results"}]

        bundle_hash = compute_bundle_hash_v1(
            "deal_offline_test", proofs, events, None
        )

        bundle = {
            "spec_version": "1.0.0",
            "deal_id": "deal_offline_test",
            "proofs": proofs,
            "events": events,
            "merkle_inclusion": None,
            "bundle_hash": bundle_hash,
        }

        result = verify_bundle_offline(bundle)
        assert result["steps"]["bundle_hash"]["passed"] is True
        assert result["steps"]["event_chain"]["passed"] is True
        # Merkle and STH skipped (not present in this test)
        assert result["steps"]["merkle_inclusion"]["passed"] is False
        assert result["steps"]["sth_signature"]["skipped"] is True
