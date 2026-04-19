"""
Tests for aigentsy-verify standalone verification package.

Uses known test vectors to verify all algorithms match the runtime exactly.
"""

import hashlib
import json
import os
import sys
import tempfile

import pytest

# Add src to path for testing without install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aigentsy_verify.merkle import (
    rfc6962_leaf_hash,
    rfc6962_node_hash,
    leaf_hash_hex,
    node_hash_hex,
    verify_inclusion,
    verify_consistency,
)
from aigentsy_verify.anchor import verify_anchor_receipt
from aigentsy_verify.bundle import (
    compute_bundle_hash,
    verify_event_chain,
    verify_bundle,
)
from aigentsy_verify.attestation import (
    verify_attestation,
    compute_attestation_hash,
)
from aigentsy_verify.keys import load_public_key_from_file


# ── RFC 6962 Hash Tests ──


class TestRFC6962Hashes:
    """Verify RFC 6962 domain-separated hash functions."""

    def test_leaf_hash_prefix(self):
        """Leaf hash uses 0x00 prefix."""
        data = b"test leaf"
        expected = hashlib.sha256(b"\x00" + data).digest()
        assert rfc6962_leaf_hash(data) == expected

    def test_node_hash_prefix(self):
        """Node hash uses 0x01 prefix."""
        left = b"\x00" * 32
        right = b"\xff" * 32
        expected = hashlib.sha256(b"\x01" + left + right).digest()
        assert rfc6962_node_hash(left, right) == expected

    def test_leaf_hash_hex(self):
        """leaf_hash_hex returns hex string."""
        result = leaf_hash_hex(b"hello")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex

    def test_node_hash_hex(self):
        """node_hash_hex works with hex inputs."""
        left_hex = "aa" * 32
        right_hex = "bb" * 32
        result = node_hash_hex(left_hex, right_hex)
        assert isinstance(result, str)
        assert len(result) == 64

    def test_leaf_vs_node_differ(self):
        """Leaf and node hashes of the same data must differ (domain separation)."""
        data = b"\x00" * 32
        leaf = rfc6962_leaf_hash(data)
        node = rfc6962_node_hash(data, data)
        assert leaf != node


# ── Merkle Inclusion Proof Tests ──


class TestMerkleInclusion:
    """Verify RFC 6962 inclusion proof verification."""

    def test_single_leaf_tree(self):
        """Tree of size 1: no proof needed, leaf is root."""
        leaf = leaf_hash_hex(b"only leaf")
        assert verify_inclusion(leaf, 0, 1, [], leaf) is True

    def test_single_leaf_wrong_root(self):
        """Tree of size 1: wrong root fails."""
        leaf = leaf_hash_hex(b"only leaf")
        assert verify_inclusion(leaf, 0, 1, [], "wrong" * 8) is False

    def test_two_leaf_tree(self):
        """Tree of size 2: verify leaf 0 with leaf 1 as proof."""
        leaf0 = leaf_hash_hex(b"leaf0")
        leaf1 = leaf_hash_hex(b"leaf1")
        root = node_hash_hex(leaf0, leaf1)
        assert verify_inclusion(leaf0, 0, 2, [leaf1], root) is True
        assert verify_inclusion(leaf1, 1, 2, [leaf0], root) is True

    def test_two_leaf_wrong_proof(self):
        """Wrong sibling hash fails verification."""
        leaf0 = leaf_hash_hex(b"leaf0")
        leaf1 = leaf_hash_hex(b"leaf1")
        root = node_hash_hex(leaf0, leaf1)
        wrong = "00" * 32
        assert verify_inclusion(leaf0, 0, 2, [wrong], root) is False

    def test_invalid_index(self):
        """Leaf index >= tree size returns False."""
        leaf = leaf_hash_hex(b"x")
        assert verify_inclusion(leaf, 1, 1, [], leaf) is False
        assert verify_inclusion(leaf, 5, 3, [], leaf) is False

    def test_empty_tree(self):
        """Tree size 0 returns False."""
        assert verify_inclusion("aa" * 32, 0, 0, [], "aa" * 32) is False

    def test_four_leaf_tree(self):
        """Tree of size 4: verify each leaf."""
        leaves = [leaf_hash_hex(f"leaf{i}".encode()) for i in range(4)]
        n01 = node_hash_hex(leaves[0], leaves[1])
        n23 = node_hash_hex(leaves[2], leaves[3])
        root = node_hash_hex(n01, n23)

        # leaf 0: proof = [leaf1, n23]
        assert verify_inclusion(leaves[0], 0, 4, [leaves[1], n23], root) is True
        # leaf 1: proof = [leaf0, n23]
        assert verify_inclusion(leaves[1], 1, 4, [leaves[0], n23], root) is True
        # leaf 2: proof = [leaf3, n01]
        assert verify_inclusion(leaves[2], 2, 4, [leaves[3], n01], root) is True
        # leaf 3: proof = [leaf2, n01]
        assert verify_inclusion(leaves[3], 3, 4, [leaves[2], n01], root) is True


# ── Bundle Hash Tests ──


class TestBundleHash:
    """Verify bundle hash computation."""

    def test_v1_hash_deterministic(self):
        """Same inputs produce same hash."""
        h1 = compute_bundle_hash("deal_1", [], [], None)
        h2 = compute_bundle_hash("deal_1", [], [], None)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_deals_different_hashes(self):
        """Different deal_id produces different hash."""
        h1 = compute_bundle_hash("deal_1", [], [], None)
        h2 = compute_bundle_hash("deal_2", [], [], None)
        assert h1 != h2

    def test_v1_uses_compact_separators(self):
        """V1 bundle hash uses compact JSON separators."""
        # Compute expected directly
        canonical = json.dumps(
            {
                "spec_version": "1.0.0",
                "deal_id": "test",
                "proofs": [],
                "events": [],
                "merkle_inclusion": None,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        result = compute_bundle_hash("test", [], [], None, spec_version="1.0.0")
        assert result == expected

    def test_legacy_hash_no_spec_version(self):
        """Legacy bundle hash omits spec_version."""
        canonical = json.dumps(
            {
                "deal_id": "legacy",
                "proofs": [],
                "events": [],
                "merkle_inclusion": None,
            },
            sort_keys=True,
            default=str,
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        result = compute_bundle_hash("legacy", [], [], None, spec_version="")
        assert result == expected


# ── Event Chain Tests ──


class TestEventChain:
    """Verify event chain integrity checking."""

    def _make_event(self, event_id, deal_id, prev_hash=""):
        """Create a properly hashed event."""
        event = {
            "event_id": event_id,
            "event_type": "TEST",
            "deal_id": deal_id,
            "actor_id": "agent_1",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {},
            "prev_hash": prev_hash,
        }
        canonical = json.dumps(
            {
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "deal_id": event["deal_id"],
                "actor_id": event["actor_id"],
                "timestamp": event["timestamp"],
                "payload": event["payload"],
                "prev_hash": event["prev_hash"],
            },
            sort_keys=True,
        )
        event["hash"] = hashlib.sha256(canonical.encode()).hexdigest()
        return event

    def test_single_event_valid(self):
        """Single event with correct hash passes."""
        e = self._make_event("e1", "deal_1")
        result = verify_event_chain([e])
        assert result["verified"] is True
        assert result["event_count"] == 1

    def test_chain_of_three(self):
        """Three properly linked events pass."""
        e1 = self._make_event("e1", "deal_1")
        e2 = self._make_event("e2", "deal_1", prev_hash=e1["hash"])
        e3 = self._make_event("e3", "deal_1", prev_hash=e2["hash"])
        result = verify_event_chain([e1, e2, e3])
        assert result["verified"] is True
        assert result["event_count"] == 3

    def test_broken_hash(self):
        """Tampered hash detected."""
        e = self._make_event("e1", "deal_1")
        e["hash"] = "tampered" + e["hash"][8:]
        result = verify_event_chain([e])
        assert result["verified"] is False
        assert len(result["errors"]) > 0

    def test_broken_chain(self):
        """Broken prev_hash link detected."""
        e1 = self._make_event("e1", "deal_1")
        e2 = self._make_event("e2", "deal_1", prev_hash="wrong_hash")
        result = verify_event_chain([e1, e2])
        assert result["verified"] is False

    def test_empty_chain(self):
        """Empty event list passes (no events to verify)."""
        result = verify_event_chain([])
        assert result["verified"] is True
        assert result["event_count"] == 0


# ── Full Bundle Verification Tests ──


class TestVerifyBundle:
    """End-to-end 5-step bundle verification."""

    def _make_bundle(self):
        """Create a minimal valid bundle for testing."""
        events = []
        e = {
            "event_id": "e1",
            "event_type": "DEAL_CREATED",
            "deal_id": "deal_test",
            "actor_id": "agent_1",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"amount": 100},
            "prev_hash": "",
        }
        canonical = json.dumps(
            {k: e[k] for k in ["event_id", "event_type", "deal_id", "actor_id", "timestamp", "payload", "prev_hash"]},
            sort_keys=True,
        )
        e["hash"] = hashlib.sha256(canonical.encode()).hexdigest()
        events.append(e)

        proofs = [{"proof_type": "screenshot", "url": "https://example.com/proof.png"}]

        bundle_hash = compute_bundle_hash(
            "deal_test", proofs, events, None, spec_version="1.0.0"
        )

        return {
            "spec_version": "1.0.0",
            "deal_id": "deal_test",
            "proofs": proofs,
            "events": events,
            "merkle_inclusion": None,
            "bundle_hash": bundle_hash,
        }

    def test_valid_bundle_passes(self):
        """Valid bundle passes steps 1-2, skips 3-5."""
        bundle = self._make_bundle()
        result = verify_bundle(bundle)
        assert result["verified"] is True
        assert result["steps"]["bundle_hash"]["passed"] is True
        assert result["steps"]["event_chain"]["passed"] is True
        assert result["steps"]["merkle_inclusion"]["skipped"] is True
        assert result["steps"]["sth_signature"]["skipped"] is True
        assert result["steps"]["cross_reference"]["skipped"] is True

    def test_tampered_bundle_fails(self):
        """Tampered event data fails bundle hash."""
        bundle = self._make_bundle()
        bundle["events"][0]["payload"]["amount"] = 999  # tamper
        result = verify_bundle(bundle)
        assert result["verified"] is False
        assert result["steps"]["bundle_hash"]["passed"] is False

    def test_result_structure(self):
        """Result contains all expected fields."""
        bundle = self._make_bundle()
        result = verify_bundle(bundle)
        assert "deal_id" in result
        assert "spec_version" in result
        assert "proof_count" in result
        assert "event_count" in result
        assert set(result["steps"].keys()) == {
            "bundle_hash",
            "event_chain",
            "merkle_inclusion",
            "sth_signature",
            "cross_reference",
        }


# ── Attestation Tests ──


class TestAttestation:
    """Verify attestation hash and signature verification."""

    def test_attestation_hash_deterministic(self):
        """Same attestation produces same hash."""
        att = {"agent_id": "a1", "score": 95, "tier": "gold"}
        h1 = compute_attestation_hash(att)
        h2 = compute_attestation_hash(att)
        assert h1 == h2

    def test_attestation_hash_matches_canonical(self):
        """Hash matches manual canonical JSON computation."""
        att = {"b": 2, "a": 1}
        canonical = json.dumps(att, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert compute_attestation_hash(att) == expected

    def test_verify_attestation_with_ed25519(self):
        """End-to-end sign + verify with real Ed25519 key pair."""
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                PublicFormat,
            )
            import base64
        except ImportError:
            pytest.skip("cryptography not installed")

        # Generate test key pair
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        pub_b64 = base64.b64encode(
            public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        ).decode()

        # Create and sign attestation
        attestation = {"agent_id": "test_agent", "score": 88, "tier": "silver"}
        canonical = json.dumps(attestation, sort_keys=True, separators=(",", ":"))
        signature = private_key.sign(canonical.encode("utf-8"))
        sig_b64 = base64.b64encode(signature).decode()

        # Verify
        assert verify_attestation(attestation, sig_b64, pub_b64) is True

    def test_verify_attestation_wrong_key(self):
        """Wrong public key fails verification."""
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                PublicFormat,
            )
            import base64
        except ImportError:
            pytest.skip("cryptography not installed")

        # Sign with key1, verify with key2
        key1 = Ed25519PrivateKey.generate()
        key2 = Ed25519PrivateKey.generate()
        pub2_b64 = base64.b64encode(
            key2.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ).decode()

        attestation = {"test": True}
        canonical = json.dumps(attestation, sort_keys=True, separators=(",", ":"))
        sig = base64.b64encode(key1.sign(canonical.encode("utf-8"))).decode()

        assert verify_attestation(attestation, sig, pub2_b64) is False

    def test_verify_attestation_wrong_algorithm(self):
        """Non-Ed25519 algorithm returns False."""
        assert verify_attestation({}, "sig", "key", algorithm="RSA") is False


# ── Key Loading Tests ──


class TestKeys:
    """Test public key loading from file."""

    def test_load_from_file(self):
        """Load key from valid JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"public_key_base64": "test_key_123"}, f)
            path = f.name

        try:
            key = load_public_key_from_file(path)
            assert key == "test_key_123"
        finally:
            os.unlink(path)

    def test_load_from_file_missing(self):
        """Missing file raises RuntimeError."""
        with pytest.raises(RuntimeError, match="Failed to load"):
            load_public_key_from_file("/nonexistent/path.json")

    def test_load_from_file_empty_key(self):
        """Empty key raises RuntimeError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"public_key_base64": ""}, f)
            path = f.name

        try:
            with pytest.raises(RuntimeError, match="empty"):
                load_public_key_from_file(path)
        finally:
            os.unlink(path)


# ── Consistency Proof Tests ──


class TestConsistency:
    """Verify RFC 6962 consistency proof verification."""

    def test_empty_to_any(self):
        """Empty tree (size 0) is consistent with anything."""
        assert verify_consistency(0, 5, "", "abc", []) is True

    def test_same_size_same_root(self):
        """Same size, same root, no proof needed."""
        root = leaf_hash_hex(b"x")
        assert verify_consistency(1, 1, root, root, []) is True

    def test_same_size_different_root(self):
        """Same size but different root fails."""
        r1 = leaf_hash_hex(b"a")
        r2 = leaf_hash_hex(b"b")
        assert verify_consistency(1, 1, r1, r2, []) is False

    def test_old_greater_than_new(self):
        """old_size > new_size always fails."""
        assert verify_consistency(5, 3, "aa" * 32, "bb" * 32, []) is False

    def test_two_leaf_consistency(self):
        """Tree grows from 1 leaf to 2 leaves."""
        leaf0 = leaf_hash_hex(b"leaf0")
        leaf1 = leaf_hash_hex(b"leaf1")
        root2 = node_hash_hex(leaf0, leaf1)
        # old_size=1 (power of 2), proof = [leaf1]
        assert verify_consistency(1, 2, leaf0, root2, [leaf1]) is True

    def test_two_leaf_wrong_proof(self):
        """Wrong consistency proof fails."""
        leaf0 = leaf_hash_hex(b"leaf0")
        leaf1 = leaf_hash_hex(b"leaf1")
        root2 = node_hash_hex(leaf0, leaf1)
        wrong = "00" * 32
        assert verify_consistency(1, 2, leaf0, root2, [wrong]) is False

    def test_negative_sizes(self):
        """Negative sizes fail."""
        assert verify_consistency(-1, 5, "", "", []) is False
        assert verify_consistency(1, -1, "", "", []) is False


# ── Anchor Receipt Verification Tests ──


class TestAnchorReceipt:
    """Verify anchor receipt integrity checking."""

    def _make_receipt(self, **overrides):
        """Create a valid anchor receipt for testing."""
        sth = {
            "tree_size": 42,
            "root_hash": "abcd" * 16,
            "timestamp": "2026-03-16T19:58:30Z",
            "signature": "c2lnbmF0dXJl",
        }
        canonical = json.dumps(sth, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        receipt = {
            "receipt_version": "1.0.0",
            "anchor_id": "anchor_test_1234",
            "log_id": "aigentsy_settlement_log_v1",
            "key_id": "aigentsy_log_signer_v1",
            "sth": sth,
            "sth_digest": digest,
            "sth_digest_algorithm": "SHA-256",
            "anchor_method": "rfc3161",
            "tsa_url": "https://freetsa.org/tsr",
            "tsa_status": "granted",
            "tsr_base64": "dHNyX2RhdGE=",
            "anchored_at": "2026-03-16T20:00:01Z",
        }
        receipt.update(overrides)
        return receipt

    def test_valid_receipt(self):
        """Valid receipt passes all checks."""
        receipt = self._make_receipt()
        ok, details = verify_anchor_receipt(receipt)
        assert ok is True
        assert details["sth_digest_match"] is True
        assert details["fields_present"] is True
        assert details["tsa_granted"] is True

    def test_missing_field(self):
        """Missing required field fails."""
        receipt = self._make_receipt()
        del receipt["anchor_id"]
        ok, details = verify_anchor_receipt(receipt)
        assert ok is False
        assert any("Missing fields" in e for e in details["errors"])

    def test_missing_sth_field(self):
        """Missing STH sub-field fails."""
        receipt = self._make_receipt()
        del receipt["sth"]["root_hash"]
        ok, details = verify_anchor_receipt(receipt)
        assert ok is False
        assert any("Missing STH fields" in e for e in details["errors"])

    def test_tampered_digest(self):
        """Tampered sth_digest fails."""
        receipt = self._make_receipt()
        receipt["sth_digest"] = "ff" * 32
        ok, details = verify_anchor_receipt(receipt)
        assert ok is False
        assert details["sth_digest_match"] is False

    def test_tampered_sth(self):
        """Modifying STH content causes digest mismatch."""
        receipt = self._make_receipt()
        receipt["sth"]["tree_size"] = 999  # tamper
        ok, details = verify_anchor_receipt(receipt)
        assert ok is False
        assert details["sth_digest_match"] is False

    def test_tsa_error_status(self):
        """TSA status not 'granted' fails."""
        receipt = self._make_receipt(tsa_status="error")
        ok, details = verify_anchor_receipt(receipt)
        assert ok is False
        assert details["tsa_granted"] is False

    def test_wrong_digest_algorithm(self):
        """Unsupported digest algorithm fails."""
        receipt = self._make_receipt(sth_digest_algorithm="MD5")
        ok, details = verify_anchor_receipt(receipt)
        assert ok is False


# ── Sample Fixture Tests ──


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class TestSampleFixtures:
    """Verify sample artifacts pass verification (publish-readiness)."""

    def test_sample_bundle_verifies(self):
        """Sample bundle passes steps 1-2."""
        path = os.path.join(FIXTURES_DIR, "sample_bundle.json")
        if not os.path.exists(path):
            pytest.skip("sample_bundle.json not found")
        with open(path) as f:
            bundle = json.load(f)
        result = verify_bundle(bundle)
        assert result["verified"] is True
        assert result["steps"]["bundle_hash"]["passed"] is True
        assert result["steps"]["event_chain"]["passed"] is True

    def test_sample_attestation_verifies(self):
        """Sample attestation signature is valid."""
        path = os.path.join(FIXTURES_DIR, "sample_attestation.json")
        if not os.path.exists(path):
            pytest.skip("sample_attestation.json not found")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
        except ImportError:
            pytest.skip("cryptography not installed")
        with open(path) as f:
            data = json.load(f)
        ok = verify_attestation(
            data["attestation"],
            data["signature"],
            data["public_key_base64"],
        )
        assert ok is True

    def test_sample_key_loads(self):
        """Sample key file loads correctly."""
        path = os.path.join(FIXTURES_DIR, "sample_key.json")
        if not os.path.exists(path):
            pytest.skip("sample_key.json not found")
        key = load_public_key_from_file(path)
        assert len(key) > 0
        assert key == json.load(open(path))["public_key_base64"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
