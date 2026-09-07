"""Non-custodial wire-level invariants.

The rigid prompt's load-bearing rule: ``private keys client-side only;
wire-level guard (no private-key material in any request body — reuse/
mirror the Stage-2 forbidden-fields check)``.

These tests exercise the wire guard directly: every forbidden field
name in the server-mirrored ``FORBIDDEN_PRIVATE_KEY_FIELDS`` set
raises ``ValueError`` on attempt-to-transmit; nested dicts are walked;
case-insensitive matching catches sneaky variants."""
from __future__ import annotations

import json
import os
import stat
import tempfile

import pytest

from aigentsy_langgraph.keypair import (
    FORBIDDEN_PRIVATE_KEY_FIELDS,
    NON_CUSTODIAL_NOTICE,
    SigningKeypair,
    _assert_no_private_material,
)


CRYPTOGRAPHY_AVAILABLE = True
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: F401
        Ed25519PrivateKey,
    )
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


# ── Wire guard ───────────────────────────────────────────────────────


def test_forbidden_fields_match_rich_sdk_contract():
    """Mirrors sdk/aigentsy/src/aigentsy/keypair.py."""
    assert FORBIDDEN_PRIVATE_KEY_FIELDS == frozenset({
        "private_key", "secret_key", "private_key_pem",
        "private_key_base64", "secret_key_base64", "signing_key",
        "priv", "sk",
    })


@pytest.mark.parametrize("field", sorted(FORBIDDEN_PRIVATE_KEY_FIELDS))
def test_top_level_private_field_refused(field):
    body = {field: "leaked"}
    with pytest.raises(ValueError, match="NON-CUSTODIAL VIOLATION"):
        _assert_no_private_material(body, "test body")


@pytest.mark.parametrize("field", sorted(FORBIDDEN_PRIVATE_KEY_FIELDS))
def test_nested_private_field_refused(field):
    body = {"actor_id": "a", "metadata": {"inner": {field: "leaked"}}}
    with pytest.raises(ValueError, match="NON-CUSTODIAL VIOLATION"):
        _assert_no_private_material(body, "test body")


def test_case_insensitive_match():
    """A naively-cased variant must NOT slip through."""
    for variant in ("PRIVATE_KEY", "Private_Key", "PrIvAtE_KeY_BaSe64"):
        with pytest.raises(ValueError):
            _assert_no_private_material({variant: "leaked"})


def test_clean_body_passes():
    """The straightforward enrollment body must pass unchanged."""
    body = {
        "actor_id": "agent_X",
        "actor_type": "agent",
        "public_key_base64": "AAAAaaaaPPPPP",
        "key_class": "production",
    }
    _assert_no_private_material(body)  # no raise


def test_non_dict_payload_is_no_op():
    """The guard skips non-dict roots cleanly (lists, strings)."""
    _assert_no_private_material("not a dict")
    _assert_no_private_material(["list", "of", "things"])
    _assert_no_private_material(None)


# ── SigningKeypair ───────────────────────────────────────────────────


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra (cryptography)")
def test_generate_returns_ed25519_pair():
    import base64
    kp = SigningKeypair.generate(print_notice=False)
    assert kp.algorithm == "Ed25519"
    pub = base64.b64decode(kp.public_key_base64)
    priv = base64.b64decode(kp.private_key_base64)
    assert len(pub) == 32, "Ed25519 public key is 32 bytes"
    assert len(priv) == 32, "Ed25519 private key is 32 bytes"
    assert kp.public_key_base64 != kp.private_key_base64


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_save_to_file_writes_0600():
    kp = SigningKeypair.generate(print_notice=False)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "kp.json")
        kp.save_to_file(path)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        # 0600 — owner-read-write only. (Skipped silently on Windows
        # where chmod has different semantics.)
        if os.name == "posix":
            assert mode & 0o077 == 0, (
                f"file perms {oct(mode)} leak access beyond owner"
            )


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_save_refuses_to_overwrite():
    kp = SigningKeypair.generate(print_notice=False)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "kp.json")
        kp.save_to_file(path)
        with pytest.raises(FileExistsError, match="refusing to overwrite"):
            kp.save_to_file(path)


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_save_and_load_roundtrip():
    kp = SigningKeypair.generate(print_notice=False)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "kp.json")
        kp.save_to_file(path)
        loaded = SigningKeypair.load_from_file(path)
        assert loaded.public_key_base64 == kp.public_key_base64
        assert loaded.private_key_base64 == kp.private_key_base64
        assert loaded.algorithm == kp.algorithm


def test_generate_without_cryptography_gives_actionable_error(
    monkeypatch,
):
    """Plain install (no [signed] extra) must fail with a clear hint."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("cryptography"):
            raise ImportError("no cryptography in plain install")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="aigentsy-langgraph\\[signed\\]"):
        SigningKeypair.generate(print_notice=False)


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_to_enrollment_body_carries_only_public_half():
    """The enrollment body must NEVER contain private material."""
    kp = SigningKeypair.generate(print_notice=False)
    body = kp.to_enrollment_body(actor_id="agent_X")
    assert body["public_key_base64"] == kp.public_key_base64
    serialized = json.dumps(body)
    assert kp.private_key_base64 not in serialized, (
        "private key half MUST NOT appear anywhere in the enrollment body"
    )
    # And the guard pre-screens it cleanly:
    _assert_no_private_material(body)


@pytest.mark.skipif(not CRYPTOGRAPHY_AVAILABLE,
                    reason="requires [signed] extra")
def test_to_enrollment_body_rejects_private_metadata():
    """If a caller naively dumps a key file into metadata, refuse."""
    kp = SigningKeypair.generate(print_notice=False)
    with pytest.raises(ValueError, match="NON-CUSTODIAL VIOLATION"):
        kp.to_enrollment_body(
            actor_id="a",
            metadata={"backup": {"private_key_base64": "leaked"}},
        )


def test_notice_text_is_explicit():
    """The non-custodial contract must read clearly to a developer
    skimming the first run — load-bearing for sober key handling."""
    assert "YOU HOLD THE PRIVATE KEY" in NON_CUSTODIAL_NOTICE
    assert "AiGentsy does not" in NON_CUSTODIAL_NOTICE
    assert "rotate" in NON_CUSTODIAL_NOTICE.lower()
