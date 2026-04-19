"""Conformance tests for pre-approval attestation."""

import os
import tempfile

import pytest


@pytest.fixture
def emitter():
    from hoverstack.pre_approval import PreApprovalEmitter
    tmp = tempfile.mktemp(suffix=".json")
    e = PreApprovalEmitter(path=tmp)
    yield e
    if os.path.exists(tmp):
        os.unlink(tmp)


def test_emit_and_lookup(emitter):
    mandate = {"mandate_id": "m1", "allowed_actions": ["execute"], "work_class": ["marketing"]}
    policy = {"policy_hash": "ph1", "policy_version": "v1"}
    result = emitter.emit_pre_approval(mandate, "agent_a", policy)
    assert result["attestation_type"] == "pre_approval"
    assert result["mandate_id"] == "m1"
    assert result["agent_id"] == "agent_a"
    assert result["attestation_hash"]

    lookup = emitter.lookup("m1", "agent_a", "ph1")
    assert lookup is not None
    assert lookup.attestation_hash == result["attestation_hash"]


def test_policy_invalidation(emitter):
    mandate = {"mandate_id": "m1"}
    emitter.emit_pre_approval(mandate, "agent_a", {"policy_hash": "ph1"})
    emitter.emit_pre_approval(mandate, "agent_b", {"policy_hash": "ph2"})

    count = emitter.invalidate_by_policy("ph1")
    assert count == 1
    assert emitter.lookup("m1", "agent_a", "ph1") is None
    assert emitter.lookup("m1", "agent_b", "ph2") is not None


def test_mandate_invalidation(emitter):
    emitter.emit_pre_approval({"mandate_id": "m1"}, "agent_a", {"policy_hash": "ph1"})
    emitter.emit_pre_approval({"mandate_id": "m2"}, "agent_a", {"policy_hash": "ph1"})

    count = emitter.invalidate_by_mandate("m1")
    assert count == 1
    assert emitter.lookup("m1", "agent_a", "ph1") is None
    assert emitter.lookup("m2", "agent_a", "ph1") is not None


def test_pre_approval_has_signature(emitter):
    """Pre-approval attestation is signed (Ed25519 if available)."""
    result = emitter.emit_pre_approval(
        {"mandate_id": "m1"}, "agent_a", {"policy_hash": "ph1"}
    )
    # Signature should be present if cryptography is installed
    try:
        from hoverstack.governed_proof import _ed25519_available
        if _ed25519_available():
            assert result["signature"], "Signature should be present with Ed25519"
    except ImportError:
        pass


def test_missing_pre_approval_does_not_block():
    """No pre-approval → compute proceeds normally (pre-approval is optional)."""
    from hoverstack.pre_approval import PreApprovalEmitter
    tmp = tempfile.mktemp(suffix=".json")
    try:
        e = PreApprovalEmitter(path=tmp)
        lookup = e.lookup("nonexistent", "agent_x", "policy_x")
        assert lookup is None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_pre_approval_metadata_fields(emitter):
    result = emitter.emit_pre_approval(
        {"mandate_id": "m1", "allowed_actions": ["execute", "deliver"],
         "work_class": ["marketing"], "consequence_rights": ["settlement_request"]},
        "agent_a",
        {"policy_hash": "ph1"},
    )
    assert result["mandate_id"] == "m1"
    assert result["agent_id"] == "agent_a"
    assert result["policy_version"] == "ph1"
    assert result["expires_on"] == "policy_change | mandate_revision | explicit_revocation"
    assert result["authorization_scope"]["allowed_actions"] == ["execute", "deliver"]
    assert result["authorized_at"]


def test_persistence_roundtrip():
    from hoverstack.pre_approval import PreApprovalEmitter
    tmp = tempfile.mktemp(suffix=".json")
    try:
        e1 = PreApprovalEmitter(path=tmp)
        e1.emit_pre_approval({"mandate_id": "m1"}, "agent_a", {"policy_hash": "ph1"})
        e2 = PreApprovalEmitter(path=tmp)
        assert e2.lookup("m1", "agent_a", "ph1") is not None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
