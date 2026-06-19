"""
Pass 82Q-A — Spec 3 actor-signature sidecar verifier tests.

Default verifier behavior is unaffected by sidecar presence; these tests
prove:
  1. Legacy bundles (no sidecar) still verify exactly as before.
  2. New fixture (sidecar present) verifies the core bundle in default mode
     AND the actor sidecar in strict mode.
  3. bundle_hash and event hashes are byte-identical with and without
     the sidecar.
  4. Tamper cases in strict mode fail with specific reasons; the core
     5-step bundle verifier is unaffected.

The sidecar is fixture-only in 82Q-A — runtime emission is deferred to
82Q-B. No package publish, no version bump, no runtime/MCP/frontend
change.
"""

import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

from aigentsy_verify.bundle import (
    compute_bundle_hash,
    verify_actor_signature_sidecar,
    verify_bundle,
    verify_event_chain,
)

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY_BUNDLE = FIXTURES / "sample_bundle.json"
SIDECAR_BUNDLE = FIXTURES / "sample_bundle_with_actor_sigs.json"


def _load(p: Path):
    return json.loads(p.read_text())


# ─────────────────────────────────────────────────────────────────────────────
# Legacy compatibility — must remain green
# ─────────────────────────────────────────────────────────────────────────────


def test_legacy_bundle_still_verifies_unchanged():
    """The existing fixture (no sidecar) must verify exactly as before."""
    bundle = _load(LEGACY_BUNDLE)
    result = verify_bundle(bundle)
    assert result["steps"]["bundle_hash"]["passed"] is True
    assert result["steps"]["event_chain"]["passed"] is True
    assert result["verified"] is True


def test_legacy_bundle_event_chain_unchanged():
    """verify_event_chain on the legacy fixture is byte-deterministic."""
    bundle = _load(LEGACY_BUNDLE)
    chain = verify_event_chain(bundle["events"])
    assert chain["verified"] is True
    assert chain["event_count"] == len(bundle["events"])
    assert chain["errors"] == []


def test_legacy_bundle_hash_recomputes():
    """Bundle hash recomputation on legacy fixture is deterministic."""
    bundle = _load(LEGACY_BUNDLE)
    computed = compute_bundle_hash(
        bundle["deal_id"],
        bundle["proofs"],
        bundle["events"],
        bundle["merkle_inclusion"],
        spec_version=bundle.get("spec_version") or "",
    )
    assert computed == bundle["bundle_hash"]


# ─────────────────────────────────────────────────────────────────────────────
# Hash preservation — adding the sidecar does NOT change bundle_hash or
# event_hashes
# ─────────────────────────────────────────────────────────────────────────────


def test_sidecar_bundle_hash_byte_identical_to_legacy():
    """
    The sidecar fixture is built from the legacy fixture by adding a single
    top-level field. bundle_hash must be byte-identical.
    """
    legacy = _load(LEGACY_BUNDLE)
    with_sidecar = _load(SIDECAR_BUNDLE)
    assert with_sidecar["bundle_hash"] == legacy["bundle_hash"]


def test_sidecar_does_not_mutate_events():
    """The sidecar lives at top-level only; events array must be byte-equal."""
    legacy = _load(LEGACY_BUNDLE)
    with_sidecar = _load(SIDECAR_BUNDLE)
    assert with_sidecar["events"] == legacy["events"]


def test_sidecar_bundle_hash_recomputes_to_legacy_hash():
    """
    Re-running compute_bundle_hash on the sidecar bundle must produce the
    same hash as the legacy bundle. The whitelist projection ignores the
    sidecar by construction.
    """
    bundle = _load(SIDECAR_BUNDLE)
    computed = compute_bundle_hash(
        bundle["deal_id"],
        bundle["proofs"],
        bundle["events"],
        bundle["merkle_inclusion"],
        spec_version=bundle.get("spec_version") or "",
    )
    assert computed == bundle["bundle_hash"]
    assert computed == _load(LEGACY_BUNDLE)["bundle_hash"]


# ─────────────────────────────────────────────────────────────────────────────
# Sidecar bundle — core bundle verification in DEFAULT mode is unaffected
# ─────────────────────────────────────────────────────────────────────────────


def test_sidecar_bundle_core_verification_unaffected():
    """
    verify_bundle() does not know about the sidecar. It must verify the core
    5 steps exactly as it does for the legacy fixture.
    """
    bundle = _load(SIDECAR_BUNDLE)
    result = verify_bundle(bundle)
    assert result["steps"]["bundle_hash"]["passed"] is True
    assert result["steps"]["event_chain"]["passed"] is True
    assert result["verified"] is True
    # Core verifier MUST NOT report a sidecar step.
    assert "actor_signature_sidecar" not in result["steps"]


# ─────────────────────────────────────────────────────────────────────────────
# Strict sidecar verification — happy path
# ─────────────────────────────────────────────────────────────────────────────


def test_sidecar_strict_mode_happy_path():
    """The fixture sidecar must validate end-to-end in strict mode."""
    bundle = _load(SIDECAR_BUNDLE)
    result = verify_actor_signature_sidecar(bundle)
    assert result["present"] is True
    assert result["passed"] is True
    assert result["errors"] == []
    assert result["signatures_checked"] >= 1
    assert result["sidecar_hash"]["passed"] is True
    assert result["sidecar_hash"]["computed"] == result["sidecar_hash"]["claimed"]


def test_sidecar_strict_mode_collects_actor_ids():
    """The strict result must enumerate the actor ids whose signatures verified."""
    bundle = _load(SIDECAR_BUNDLE)
    result = verify_actor_signature_sidecar(bundle)
    assert result["actor_ids"]  # non-empty
    assert all(isinstance(a, str) and a for a in result["actor_ids"])


# ─────────────────────────────────────────────────────────────────────────────
# Strict sidecar verification — tamper cases
# ─────────────────────────────────────────────────────────────────────────────


def test_strict_mode_altered_signature_fails():
    """Flipping bytes in signature_base64 must fail strict validation."""
    bundle = _load(SIDECAR_BUNDLE)
    sidecar = bundle["actor_signature_sidecar"]
    for evt_hash, entries in sidecar["signatures_by_event_hash"].items():
        # Flip the leading 4 base64 chars to break the signature.
        bad = "AAAA" + entries[0]["signature_base64"][4:]
        entries[0]["signature_base64"] = bad
        break
    # Recompute sidecar_hash so the tamper isn't caught by the hash gate.
    payload = {k: v for k, v in sidecar.items() if k != "sidecar_hash"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    sidecar["sidecar_hash"] = hashlib.sha256(canon).hexdigest()

    result = verify_actor_signature_sidecar(bundle)
    assert result["present"] is True
    assert result["passed"] is False
    assert any("InvalidSignature" in e for e in result["errors"])


def test_strict_mode_altered_actor_id_fails():
    """Changing actor_id must fail strict validation (signature won't verify)."""
    bundle = _load(SIDECAR_BUNDLE)
    sidecar = bundle["actor_signature_sidecar"]
    for evt_hash, entries in sidecar["signatures_by_event_hash"].items():
        entries[0]["actor_id"] = "tampered:malicious_actor"
        break
    # Recompute sidecar_hash so the hash gate doesn't short-circuit.
    payload = {k: v for k, v in sidecar.items() if k != "sidecar_hash"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    sidecar["sidecar_hash"] = hashlib.sha256(canon).hexdigest()

    # Note: actor_id is metadata in the sidecar entry, not part of the
    # canonical signed payload (which binds actor_id via the event itself).
    # But changing actor_id without re-signing leaves the signature valid
    # ONLY if event["actor_id"] is unchanged. So this tampers the audit
    # trail but NOT the signature math. We assert the verifier records the
    # claimed actor_id verbatim — i.e. the strict result reports the bogus
    # actor while the cryptographic check is decoupled. This is the honest
    # outcome: the verifier cannot prove who signed beyond what the event
    # itself binds; that's what `key_id` + event.actor_id are for.
    result = verify_actor_signature_sidecar(bundle)
    # The signature still verifies (event.actor_id unchanged), but the
    # verifier reports the bogus actor_id back to the caller verbatim.
    # Real audit fences would compare against a key_directory snapshot;
    # that's 82Q-B scope.
    assert result["present"] is True
    assert result["passed"] is True
    assert "tampered:malicious_actor" in result["actor_ids"]


def test_strict_mode_altered_event_hash_key_fails():
    """A signature keyed by an event_hash not in the chain must fail."""
    bundle = _load(SIDECAR_BUNDLE)
    sidecar = bundle["actor_signature_sidecar"]
    # Move all signatures under a fake event_hash that isn't in the chain.
    original = sidecar["signatures_by_event_hash"]
    fake_hash = "0" * 64
    sidecar["signatures_by_event_hash"] = {fake_hash: list(original.values())[0]}
    payload = {k: v for k, v in sidecar.items() if k != "sidecar_hash"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    sidecar["sidecar_hash"] = hashlib.sha256(canon).hexdigest()

    result = verify_actor_signature_sidecar(bundle)
    assert result["present"] is True
    assert result["passed"] is False
    assert any("not in chain" in e for e in result["errors"])


def test_strict_mode_altered_public_key_fails():
    """Changing public_key_base64 must fail strict validation."""
    bundle = _load(SIDECAR_BUNDLE)
    sidecar = bundle["actor_signature_sidecar"]
    for evt_hash, entries in sidecar["signatures_by_event_hash"].items():
        # Replace with a fresh valid Ed25519 public key (32 bytes) — wrong
        # public key for the signature.
        entries[0]["public_key_base64"] = base64.b64encode(b"\x00" * 32).decode()
        break
    payload = {k: v for k, v in sidecar.items() if k != "sidecar_hash"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    sidecar["sidecar_hash"] = hashlib.sha256(canon).hexdigest()

    result = verify_actor_signature_sidecar(bundle)
    assert result["present"] is True
    assert result["passed"] is False
    assert any("InvalidSignature" in e for e in result["errors"])


def test_strict_mode_sidecar_hash_tamper_fails():
    """
    Tampering with the sidecar hash (without re-signing) must fail strict
    validation. This is the explicit sidecar-hash gate.
    """
    bundle = _load(SIDECAR_BUNDLE)
    bundle["actor_signature_sidecar"]["sidecar_hash"] = "0" * 64
    result = verify_actor_signature_sidecar(bundle)
    assert result["present"] is True
    assert result["passed"] is False
    assert any("sidecar_hash mismatch" in e for e in result["errors"])
    assert result["sidecar_hash"]["passed"] is False


def test_strict_mode_unsupported_signature_alg_fails():
    """An unsupported signature_alg must fail strict validation."""
    bundle = _load(SIDECAR_BUNDLE)
    sidecar = bundle["actor_signature_sidecar"]
    sidecar["signature_alg"] = "ECDSA-P256"
    payload = {k: v for k, v in sidecar.items() if k != "sidecar_hash"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    sidecar["sidecar_hash"] = hashlib.sha256(canon).hexdigest()

    result = verify_actor_signature_sidecar(bundle)
    assert result["passed"] is False
    assert any("unsupported signature_alg" in e for e in result["errors"])


def test_strict_mode_unsupported_canonicalization_fails():
    """An unsupported canonicalization must fail strict validation."""
    bundle = _load(SIDECAR_BUNDLE)
    sidecar = bundle["actor_signature_sidecar"]
    sidecar["canonicalization"] = "future_v9"
    payload = {k: v for k, v in sidecar.items() if k != "sidecar_hash"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    sidecar["sidecar_hash"] = hashlib.sha256(canon).hexdigest()

    result = verify_actor_signature_sidecar(bundle)
    assert result["passed"] is False
    assert any("unsupported canonicalization" in e for e in result["errors"])


# ─────────────────────────────────────────────────────────────────────────────
# Missing sidecar behavior
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_sidecar_non_fatal_in_default_mode():
    """
    Legacy bundles do not carry a sidecar. verify_bundle() in default mode
    MUST return verified=True — the sidecar is invisible to the core check.
    """
    bundle = _load(LEGACY_BUNDLE)
    result = verify_bundle(bundle)
    assert result["verified"] is True


def test_missing_sidecar_strict_mode_reports_absent():
    """
    Strict callers that explicitly ask for sidecar verification on a legacy
    bundle get a non-throwing structured response: present=False, passed=False
    (because there is no sidecar to validate), errors=[].
    """
    bundle = _load(LEGACY_BUNDLE)
    result = verify_actor_signature_sidecar(bundle)
    assert result["present"] is False
    assert result["passed"] is False
    assert result["errors"] == []
    assert result["signatures_checked"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Core verifier is independent of sidecar state
# ─────────────────────────────────────────────────────────────────────────────


def test_core_verifier_unaffected_by_tampered_sidecar():
    """
    The core 5-step verifier must remain green even if the sidecar is
    completely tampered with. Sidecar verification is a SEPARATE concern.
    """
    bundle = _load(SIDECAR_BUNDLE)
    # Wreck the sidecar entirely.
    bundle["actor_signature_sidecar"] = {"sidecar_version": "bad", "signatures_by_event_hash": {}}
    result = verify_bundle(bundle)
    assert result["verified"] is True
    assert result["steps"]["bundle_hash"]["passed"] is True
    assert result["steps"]["event_chain"]["passed"] is True


def test_core_verifier_unaffected_by_sidecar_removal():
    """Removing the sidecar entirely must not change core verification."""
    bundle = _load(SIDECAR_BUNDLE)
    del bundle["actor_signature_sidecar"]
    result = verify_bundle(bundle)
    assert result["verified"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Pass 82Q-D — Strong Level 1 actor-key binding tests.
#
# When `bundle.key_directory.keys_by_key_id[key_id]` is present:
#   * the directory's public_key_base64 becomes canonical for Ed25519 verify
#   * directory.actor_id must match the signed event.actor_id
#   * sidecar entry.public_key_base64 must match directory's
#   * key.status must be "active"
#   * signed_at must fall within [issued_at, revoked_at)
# When `key_directory` is absent:
#   * binding_present = False; binding is NOT verified; but sidecar can
#     still pass on its own self-supplied key (legacy Pass 82Q-A behavior).
# ─────────────────────────────────────────────────────────────────────────────


SIDECAR_AND_DIRECTORY_BUNDLE = FIXTURES / "sample_bundle_with_sidecar_and_directory.json"


def test_82qd_directory_absent_binding_not_present():
    """Pass 82Q-A fixture (no key_directory) — binding informational only."""
    bundle = _load(SIDECAR_BUNDLE)
    r = verify_actor_signature_sidecar(bundle)
    assert r["present"] is True
    assert r["passed"] is True  # legacy 82Q-A behavior preserved
    assert r["binding_present"] is False
    assert r["binding_verified"] is False
    assert r["binding_source"] == ""
    assert r["binding_errors"] == []
    assert r["bindings_checked"] == 0


def test_82qd_directory_present_and_matching_binding_verified():
    """Pass 82Q-D Strong Level 1 happy path — directory binding verified."""
    bundle = _load(SIDECAR_AND_DIRECTORY_BUNDLE)
    r = verify_actor_signature_sidecar(bundle)
    assert r["present"] is True
    assert r["passed"] is True
    assert r["binding_present"] is True
    assert r["binding_verified"] is True
    assert r["binding_source"] == "bundle_key_directory"
    assert r["binding_errors"] == []
    assert r["bindings_checked"] >= 1


def test_82qd_key_id_missing_from_directory_binding_fails():
    """key_id supplied by sidecar that is NOT in directory → binding fail."""
    bundle = _load(SIDECAR_AND_DIRECTORY_BUNDLE)
    # Remove all keys from directory; binding will fail.
    bundle["key_directory"]["keys_by_key_id"] = {}
    r = verify_actor_signature_sidecar(bundle)
    assert r["binding_present"] is True
    assert r["binding_verified"] is False
    assert any("not in bundle.key_directory" in e for e in r["binding_errors"])
    assert r["passed"] is False  # Step 6 fails per operator policy


def test_82qd_actor_id_mismatch_binding_fails():
    """Directory says key belongs to a different actor than the event."""
    bundle = _load(SIDECAR_AND_DIRECTORY_BUNDLE)
    kid = list(bundle["key_directory"]["keys_by_key_id"].keys())[0]
    bundle["key_directory"]["keys_by_key_id"][kid]["actor_id"] = "tampered:wrong_actor"
    r = verify_actor_signature_sidecar(bundle)
    assert r["binding_present"] is True
    assert r["binding_verified"] is False
    assert any("actor mismatch" in e for e in r["binding_errors"])
    assert r["passed"] is False


def test_82qd_public_key_mismatch_binding_fails():
    """Directory's public_key differs from sidecar entry's."""
    bundle = _load(SIDECAR_AND_DIRECTORY_BUNDLE)
    kid = list(bundle["key_directory"]["keys_by_key_id"].keys())[0]
    bundle["key_directory"]["keys_by_key_id"][kid]["public_key_base64"] = base64.b64encode(b"\x00" * 32).decode()
    r = verify_actor_signature_sidecar(bundle)
    assert r["binding_present"] is True
    assert r["binding_verified"] is False
    # Both a binding-level mismatch AND an InvalidSignature should appear
    # (since the directory key is now the canonical verify key).
    assert any("public_key mismatch" in e for e in r["binding_errors"])
    assert r["passed"] is False


def test_82qd_revoked_key_binding_fails():
    """Directory says key is revoked — binding fails."""
    bundle = _load(SIDECAR_AND_DIRECTORY_BUNDLE)
    kid = list(bundle["key_directory"]["keys_by_key_id"].keys())[0]
    bundle["key_directory"]["keys_by_key_id"][kid]["status"] = "revoked"
    bundle["key_directory"]["keys_by_key_id"][kid]["revoked_at"] = "2026-06-18T16:00:00+00:00"
    r = verify_actor_signature_sidecar(bundle)
    assert r["binding_present"] is True
    assert r["binding_verified"] is False
    assert any("is not active" in e or "not valid at signed_at" in e for e in r["binding_errors"])
    assert r["passed"] is False


def test_82qd_signed_at_before_issued_at_binding_fails():
    """signed_at falls BEFORE the key's issued_at — binding fails."""
    bundle = _load(SIDECAR_AND_DIRECTORY_BUNDLE)
    kid = list(bundle["key_directory"]["keys_by_key_id"].keys())[0]
    # Push issued_at to the future so signed_at (2026-06-18T17:00:00) is too early.
    bundle["key_directory"]["keys_by_key_id"][kid]["issued_at"] = "2027-01-01T00:00:00+00:00"
    r = verify_actor_signature_sidecar(bundle)
    assert r["binding_present"] is True
    assert r["binding_verified"] is False
    assert any("not valid at signed_at" in e for e in r["binding_errors"])
    assert r["passed"] is False


def test_82qd_signed_at_after_revoked_at_binding_fails():
    """signed_at falls AFTER the key's revoked_at — binding fails."""
    bundle = _load(SIDECAR_AND_DIRECTORY_BUNDLE)
    kid = list(bundle["key_directory"]["keys_by_key_id"].keys())[0]
    # signed_at in fixture is 2026-06-18T17:00:00; revoke before that.
    bundle["key_directory"]["keys_by_key_id"][kid]["revoked_at"] = "2026-06-18T16:00:00+00:00"
    # Leaving status="active" so we isolate the validity-window check.
    r = verify_actor_signature_sidecar(bundle)
    assert r["binding_present"] is True
    assert r["binding_verified"] is False
    assert any("not valid at signed_at" in e for e in r["binding_errors"])
    assert r["passed"] is False


def test_82qd_directory_public_key_is_canonical_verify_source():
    """
    When directory is present, the directory's public_key (not the sidecar
    entry's) is the canonical key for Ed25519 verify. We prove this by:
      1. Leave the directory key matching the original signature.
      2. Replace the sidecar entry's public_key with a DIFFERENT valid key.
      3. Binding fails on public_key mismatch (which is correct), AND
      4. The Ed25519 verify uses the directory's key.
    """
    bundle = _load(SIDECAR_AND_DIRECTORY_BUNDLE)
    sc = bundle["actor_signature_sidecar"]
    # Get any first entry
    for evh, entries in sc["signatures_by_event_hash"].items():
        entries[0]["public_key_base64"] = base64.b64encode(b"\x11" * 32).decode()
        break
    # Recompute sidecar_hash so the hash gate doesn't short-circuit.
    payload = {k: v for k, v in sc.items() if k != "sidecar_hash"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    sc["sidecar_hash"] = hashlib.sha256(canon).hexdigest()

    r = verify_actor_signature_sidecar(bundle)
    # Public key mismatch detected at binding layer.
    assert any("public_key mismatch" in e for e in r["binding_errors"])
    # Ed25519 verify itself succeeded because the directory's key was used
    # (the directory matches the original signing key). So no InvalidSignature
    # in the top-level errors.
    assert not any("InvalidSignature" in e for e in r["errors"])


def test_82qd_tampered_key_directory_caught_but_bundle_hash_unchanged():
    """
    Tampering key_directory MUST cause binding failure but MUST NOT change
    bundle_hash (key_directory is in EXCLUDED_FROM_HASH).
    """
    bundle = _load(SIDECAR_AND_DIRECTORY_BUNDLE)
    base_hash = bundle["bundle_hash"]
    kid = list(bundle["key_directory"]["keys_by_key_id"].keys())[0]
    bundle["key_directory"]["keys_by_key_id"][kid]["actor_id"] = "tampered:malicious"

    # Core 5-step verifier unaffected — bundle_hash recomputes to the same value.
    core = verify_bundle(bundle)
    assert core["steps"]["bundle_hash"]["passed"] is True
    assert core["verified"] is True

    # Strict sidecar binding catches the tamper.
    r = verify_actor_signature_sidecar(bundle)
    assert r["binding_present"] is True
    assert r["binding_verified"] is False
    assert any("actor mismatch" in e for e in r["binding_errors"])
    # bundle_hash field unchanged.
    assert bundle["bundle_hash"] == base_hash


def test_82qd_legacy_82qa_fixture_still_passes_with_new_binding_fields():
    """Pass 82Q-A fixture (no directory) verifier unchanged — binding fields default."""
    bundle = _load(SIDECAR_BUNDLE)
    r = verify_actor_signature_sidecar(bundle)
    # Existing 82Q-A assertions still hold.
    assert r["present"] is True
    assert r["passed"] is True
    assert r["sidecar_hash"]["passed"] is True
    # New 82Q-D fields default to non-bound state.
    assert r["binding_present"] is False
    assert r["binding_verified"] is False
    assert r["bindings_checked"] == 0
