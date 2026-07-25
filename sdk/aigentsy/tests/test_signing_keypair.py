"""Tier 2 Stage 2 — client-side SDK keypair tests.

THE LOAD-BEARING ASSERTION: the private key never appears in any HTTP
body the SDK constructs for the server. Multiple ways:
  - SigningKeypair.to_enrollment_body() returns a dict whose recursive
    keys never match FORBIDDEN_PRIVATE_KEY_FIELDS.
  - _assert_no_private_material refuses to transmit when fed an
    enrollment body that contains a forbidden field.
  - The body the actual client.enroll_signing_key() sends carries only
    public_key_base64 + actor_id + actor_type + key_class.

Non-network: these tests assemble the request bodies and inspect them
without ever hitting the protocol. Server-side hooks are not exercised
here (covered by tests in the ame-runtime repo).
"""
from __future__ import annotations

import base64
import json
import os
import sys

import pytest

# Make the SDK importable from this in-repo source layout
SDK_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(SDK_SRC))

from aigentsy.keypair import (  # noqa: E402
    NON_CUSTODIAL_NOTICE,
    FORBIDDEN_PRIVATE_KEY_FIELDS,
    SigningKeypair,
    _assert_no_private_material,
    public_key_fingerprint,
)


# ── 1. Generation produces a valid Ed25519 keypair ────────────────────────


class TestGenerate:
    def test_generate_returns_keypair_with_both_halves(self):
        kp = SigningKeypair.generate(print_notice=False)
        assert kp.algorithm == "Ed25519"
        assert kp.public_key_base64
        assert kp.private_key_base64
        # Different halves
        assert kp.public_key_base64 != kp.private_key_base64

    def test_public_key_is_32_bytes_raw(self):
        kp = SigningKeypair.generate(print_notice=False)
        raw = base64.b64decode(kp.public_key_base64)
        assert len(raw) == 32, (
            f"Ed25519 raw public key must be 32 bytes; got {len(raw)}"
        )

    def test_private_key_is_32_bytes_raw(self):
        kp = SigningKeypair.generate(print_notice=False)
        raw = base64.b64decode(kp.private_key_base64)
        assert len(raw) == 32, (
            f"Ed25519 raw private key must be 32 bytes; got {len(raw)}"
        )

    def test_generated_keys_are_unique(self):
        a = SigningKeypair.generate(print_notice=False)
        b = SigningKeypair.generate(print_notice=False)
        assert a.public_key_base64 != b.public_key_base64
        assert a.private_key_base64 != b.private_key_base64

    def test_notice_is_explicitly_non_custodial(self):
        # The notice must state the non-custodial property in plain
        # English. If this text is removed, the developer might not
        # realize they hold the private key and treat it like a
        # recoverable credential.
        assert "AiGentsy does not" in NON_CUSTODIAL_NOTICE
        assert "rotate" in NON_CUSTODIAL_NOTICE.lower()
        assert "cannot recover" in NON_CUSTODIAL_NOTICE.lower()


# ── 2. THE LOAD-BEARING ASSERTION ─────────────────────────────────────────


class TestPrivateKeyNeverInRequestBody:
    """The enrollment-body builder must NEVER include any private-key
    field. The defensive walker catches accidental leaks BEFORE the
    request reaches the wire."""

    def test_to_enrollment_body_carries_only_public_half(self):
        kp = SigningKeypair.generate(print_notice=False)
        body = kp.to_enrollment_body(actor_id="agent_x")
        assert "public_key_base64" in body
        assert body["public_key_base64"] == kp.public_key_base64
        # No private-key field — checked literally
        for fld in FORBIDDEN_PRIVATE_KEY_FIELDS:
            assert fld not in body, f"forbidden field {fld!r} in enrollment body"
        # And not at any nested level
        _assert_no_private_material(body, "enrollment body")

    def test_assert_no_private_material_catches_leak(self):
        body = {
            "actor_id": "agent_x",
            "public_key_base64": "ok",
            "private_key_base64": "OOPS_LEAK",  # ← would be exfil
        }
        with pytest.raises(ValueError, match="NON-CUSTODIAL VIOLATION"):
            _assert_no_private_material(body, "test")

    def test_assert_no_private_material_catches_nested_leak(self):
        body = {
            "actor_id": "agent_x",
            "metadata": {"signing_key": "x"},
        }
        with pytest.raises(ValueError, match="NON-CUSTODIAL VIOLATION"):
            _assert_no_private_material(body, "test")

    def test_assert_catches_every_forbidden_variant(self):
        for variant in FORBIDDEN_PRIVATE_KEY_FIELDS:
            body = {"actor_id": "x", variant: "x"}
            with pytest.raises(ValueError, match="NON-CUSTODIAL VIOLATION"):
                _assert_no_private_material(body, variant)

    def test_assert_case_insensitive(self):
        body = {"PRIVATE_KEY": "x", "actor_id": "y"}
        with pytest.raises(ValueError, match="NON-CUSTODIAL VIOLATION"):
            _assert_no_private_material(body, "case")

    def test_metadata_with_private_key_refused_in_builder(self):
        kp = SigningKeypair.generate(print_notice=False)
        with pytest.raises(ValueError, match="NON-CUSTODIAL VIOLATION"):
            kp.to_enrollment_body(
                actor_id="agent_x",
                metadata={"private_key": "DO_NOT_SEND"},
            )

    def test_json_serialized_body_has_no_private_key_substring(self):
        """Even at the wire level: the JSON-encoded body has no
        private_key_base64 substring (or any forbidden field's name)."""
        kp = SigningKeypair.generate(print_notice=False)
        body = kp.to_enrollment_body(actor_id="agent_x")
        wire = json.dumps(body)
        for fld in FORBIDDEN_PRIVATE_KEY_FIELDS:
            assert fld not in wire, (
                f"forbidden substring {fld!r} appeared in JSON-encoded "
                f"wire body — this would leak the private key over HTTP"
            )


# ── 3. File persistence (developer's own filesystem) ─────────────────────


class TestSaveAndLoadFile:
    def test_save_and_load_roundtrip(self, tmp_path):
        kp = SigningKeypair.generate(print_notice=False)
        path = tmp_path / "keys" / "agent_x_v1.json"
        kp.save_to_file(path)
        loaded = SigningKeypair.load_from_file(path)
        assert loaded.public_key_base64 == kp.public_key_base64
        assert loaded.private_key_base64 == kp.private_key_base64
        assert loaded.algorithm == "Ed25519"

    def test_save_writes_owner_only_perms(self, tmp_path):
        if os.name == "nt":
            pytest.skip("file mode bits not meaningful on Windows")
        kp = SigningKeypair.generate(print_notice=False)
        path = tmp_path / "k.json"
        kp.save_to_file(path)
        mode = os.stat(path).st_mode & 0o777
        # Owner read+write only. NOT group/other readable.
        assert mode == 0o600, f"expected 0o600 perms; got {oct(mode)}"

    def test_save_refuses_to_overwrite(self, tmp_path):
        kp = SigningKeypair.generate(print_notice=False)
        path = tmp_path / "k.json"
        kp.save_to_file(path)
        kp2 = SigningKeypair.generate(print_notice=False)
        with pytest.raises(FileExistsError, match="refusing to overwrite"):
            kp2.save_to_file(path)

    def test_save_writes_notice_field(self, tmp_path):
        """The saved keyfile carries an explicit non-custodial notice so
        a developer who finds it on disk later knows what it is."""
        kp = SigningKeypair.generate(print_notice=False)
        path = tmp_path / "k.json"
        kp.save_to_file(path)
        data = json.loads(path.read_text())
        assert "_notice" in data
        assert "non-custodial" in data["_notice"].lower()

    def test_load_rejects_non_ed25519(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({
            "algorithm": "RSA",
            "public_key_base64": "x",
            "private_key_base64": "y",
        }))
        with pytest.raises(ValueError, match="unsupported algorithm"):
            SigningKeypair.load_from_file(path)


# ── 4. Public-key fingerprint (UX helper) ──────────────────────────────


class TestFingerprint:
    def test_fingerprint_truncates_with_ellipsis(self):
        fp = public_key_fingerprint("ABCDEFGHIJKLMNOP", n=4)
        assert fp == "ABCD…"

    def test_fingerprint_empty(self):
        assert public_key_fingerprint("") == "…"
        assert public_key_fingerprint(None) == "…"
