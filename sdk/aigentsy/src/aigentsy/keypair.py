"""
AiGentsy Signing Keypair (Tier 2 Stage 2)
==========================================

CLIENT-SIDE Ed25519 keypair generation for non-custodial per-actor
signing on the AiGentsy protocol.

PRINCIPLE: NON-CUSTODIAL.
  * The keypair is generated ENTIRELY on the developer's machine.
  * The private key NEVER transmits to AiGentsy. The protocol stores
    ONLY the public half via POST /actor/enroll-key.
  * The developer holds the private key. If lost, the developer ROTATES
    (generates a new keypair, enrolls the new public key — auto-revokes
    the old one). AiGentsy CANNOT recover the lost private key. There
    is no recovery path by design.

This module never sends, logs, or persists the private key to anywhere
that touches AiGentsy. The enrollment helper inspects the request body
just before sending and refuses to transmit if any private-key field
is present — a belt-and-suspenders backstop against accidental leaks.

Stage 2 ships this helper. Stage 3 will add an `event_signer` module
that uses the private key to sign events locally before the agent
submits them — Stage 2 does NO event signing.

Usage
-----

    from aigentsy import AiGentsyClient, SigningKeypair

    # 1. Generate the keypair locally — no network call.
    kp = SigningKeypair.generate()

    # 2. Save the private key somewhere YOU control. NOT in AiGentsy.
    kp.save_to_file("~/.aigentsy/keys/my_agent_v1.json")

    # 3. Enroll the PUBLIC key with the protocol — the request carries
    #    only the public half; the private half stays on your disk.
    client = AiGentsyClient(api_key=my_api_key)
    result = client.enroll_signing_key(
        actor_id=my_agent_id,
        public_key_base64=kp.public_key_base64,
    )
    print("key_id:", result["key_id"])

Or in one shot — generate + register agent + enroll in a single call:

    client = AiGentsyClient()
    kp, agent = client.register_with_signing_key(name="my_agent",
                                                 agent_type="general")
    kp.save_to_file("~/.aigentsy/keys/" + agent["agent_id"] + ".json")
"""
from __future__ import annotations

import base64
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


__all__ = [
    "SigningKeypair",
    "NON_CUSTODIAL_NOTICE",
]


# Plain-English notice that the SDK prints when a keypair is generated.
# This is intentionally verbose — developers must understand the
# non-custodial contract before using Stage 3+ event signing.
NON_CUSTODIAL_NOTICE = """\
AiGentsy non-custodial signing keypair generated.

  YOU HOLD THE PRIVATE KEY. AiGentsy does not.
  - The private key never transmits to AiGentsy. Enrollment sends
    only the public half.
  - If you lose this private key, you ROTATE — generate a new
    keypair, enroll the new public key. AiGentsy cannot recover or
    re-issue your lost key. There is no recovery path by design.
  - Store the private key on a filesystem only you control. Do not
    paste it into chat, log files, error reporters, or screenshots.

  This is the same property as an SSH private key or a wallet
  seed phrase — your custody, your responsibility.
"""


# Names of fields that MUST NEVER appear in any HTTP body sent to
# AiGentsy. Mirrors the server-side FORBIDDEN_PRIVATE_KEY_FIELDS guard
# (protocol/actor_registry.py:FORBIDDEN_PRIVATE_KEY_FIELDS) so a leak
# is caught client-side BEFORE the request is even constructed.
FORBIDDEN_PRIVATE_KEY_FIELDS = frozenset({
    "private_key", "secret_key", "private_key_pem",
    "private_key_base64", "secret_key_base64", "signing_key",
    "priv", "sk",
})


@dataclass
class SigningKeypair:
    """An Ed25519 keypair held by the agent (client-side, non-custodial).

    Fields:
      public_key_base64:  44-char base64 of the raw 32-byte Ed25519 public key
      private_key_base64: 44-char base64 of the raw 32-byte Ed25519 private key
                          — STAYS ON THE DEVELOPER'S MACHINE.
      algorithm:          "Ed25519" (Stage 2; the only supported algorithm)
    """
    public_key_base64: str
    private_key_base64: str
    algorithm: str = "Ed25519"

    # ── Factory ─────────────────────────────────────────────────────────

    @classmethod
    def generate(cls, print_notice: bool = True) -> "SigningKeypair":
        """Generate a fresh Ed25519 keypair locally.

        Prints NON_CUSTODIAL_NOTICE to stdout by default to ensure the
        developer sees the contract every time a key is created.
        Pass print_notice=False to suppress (e.g. in tests).
        """
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                NoEncryption,
                PrivateFormat,
                PublicFormat,
            )
        except ImportError as e:
            raise RuntimeError(
                "SigningKeypair.generate() requires the `cryptography` package. "
                "Install with: pip install cryptography>=41.0"
            ) from e

        priv = Ed25519PrivateKey.generate()
        priv_raw = priv.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        kp = cls(
            public_key_base64=base64.b64encode(pub_raw).decode(),
            private_key_base64=base64.b64encode(priv_raw).decode(),
            algorithm="Ed25519",
        )
        if print_notice:
            print(NON_CUSTODIAL_NOTICE)
        return kp

    # ── Persistence (the developer's own filesystem) ────────────────────

    def save_to_file(self, path) -> Path:
        """Save the keypair (BOTH halves) to a file you control.

        File is written with 0600 permissions (owner read/write only).
        Parent directories are created if needed.

        Refuses to overwrite an existing file — rotation is intentional;
        overwriting silently would lose the previous key.
        """
        p = Path(path).expanduser().resolve()
        if p.exists():
            raise FileExistsError(
                f"refusing to overwrite existing key file at {p}. "
                f"Move or delete it first if rotation is intended."
            )
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "public_key_base64": self.public_key_base64,
            "private_key_base64": self.private_key_base64,
            "algorithm": self.algorithm,
            "_notice": "AiGentsy non-custodial private key. AiGentsy does NOT "
                       "have a copy. Treat like an SSH private key.",
        }
        p.write_text(json.dumps(payload, indent=2))
        try:
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass  # Windows / FS-without-perms — best-effort
        return p

    @classmethod
    def load_from_file(cls, path) -> "SigningKeypair":
        p = Path(path).expanduser().resolve()
        data = json.loads(p.read_text())
        if data.get("algorithm") != "Ed25519":
            raise ValueError(
                f"unsupported algorithm: {data.get('algorithm')!r} "
                f"(only Ed25519 supported in Stage 2)"
            )
        if not data.get("public_key_base64") or not data.get("private_key_base64"):
            raise ValueError(f"keyfile at {p} missing public/private key field")
        return cls(
            public_key_base64=data["public_key_base64"],
            private_key_base64=data["private_key_base64"],
            algorithm="Ed25519",
        )

    # ── Public-half-only view (the only thing that ever leaves the host) ─

    def to_enrollment_body(
        self,
        actor_id: str,
        actor_type: str = "agent",
        key_class: str = "production",
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """Build the JSON body for POST /actor/enroll-key.

        Returns ONLY the public half plus identity metadata. The returned
        dict is sanitized — calling `_assert_no_private_material(body)`
        on it would never raise. The caller can sanity-check this before
        the HTTP call (the SDK enrollment helper does so).
        """
        body = {
            "actor_id": actor_id,
            "actor_type": actor_type,
            "public_key_base64": self.public_key_base64,
            "key_class": key_class,
        }
        if metadata:
            _assert_no_private_material(metadata, "metadata")
            body["metadata"] = metadata
        # Final belt-and-suspenders check before returning
        _assert_no_private_material(body, "enrollment body")
        return body


# ── Defensive helpers ────────────────────────────────────────────────────


def _assert_no_private_material(payload: Dict, context: str = "payload") -> None:
    """Walk a dict and raise if any key matches FORBIDDEN_PRIVATE_KEY_FIELDS
    (case-insensitive). This is the CLIENT-SIDE backstop — a defense in
    depth against an accidental leak BEFORE the request is sent.

    Mirrors the server-side guard in protocol/actor_registry.py.
    """
    if not isinstance(payload, dict):
        return
    for k in payload:
        if k.lower() in FORBIDDEN_PRIVATE_KEY_FIELDS:
            raise ValueError(
                f"NON-CUSTODIAL VIOLATION in {context}: field {k!r} looks "
                f"like a private key. Refusing to transmit. (This is a "
                f"client-side guard; the server enforces the same rule.)"
            )
        v = payload[k]
        if isinstance(v, dict):
            _assert_no_private_material(v, context + "." + k)


def public_key_fingerprint(public_key_base64: str, n: int = 8) -> str:
    """Short fingerprint of a public key (for logs/UX). Just a base64
    truncation — not cryptographic. Safe to display."""
    return (public_key_base64 or "")[:n] + "…"
