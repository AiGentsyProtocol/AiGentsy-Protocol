"""
Portable Outcome Attestation verification.

Verifies Ed25519-signed attestations from AiGentsy's attestation endpoint.
All functions are standalone — no AiGentsy runtime imports.
"""

import base64
import hashlib
import json
from typing import Any, Dict


def verify_attestation(
    attestation: Dict[str, Any],
    signature_base64: str,
    public_key_base64: str,
    algorithm: str = "Ed25519",
) -> bool:
    """
    Verify an Ed25519-signed outcome attestation offline.

    The attestation is signed over its canonical JSON representation
    (sorted keys, compact separators).

    Args:
        attestation: The attestation payload dict (from response["attestation"])
        signature_base64: Base64-encoded signature (from response["signature"])
        public_key_base64: Base64-encoded Ed25519 public key.
            Obtain from https://aigentsy.com/data/log_public_key.json
        algorithm: Signing algorithm (default "Ed25519")

    Returns:
        True if the signature is valid

    Example:
        import json, urllib.request
        from aigentsy_verify import verify_attestation, fetch_public_key

        # Fetch attestation
        resp = json.loads(urllib.request.urlopen(
            "https://aigentsy-ame-runtime.onrender.com/protocol/agents/AGENT_ID/attestation"
        ).read())

        # Fetch public key
        pub_key = fetch_public_key()

        # Verify
        ok = verify_attestation(
            resp["attestation"],
            resp["signature"],
            pub_key,
        )
    """
    if algorithm != "Ed25519":
        return False

    canonical = json.dumps(attestation, sort_keys=True, separators=(",", ":"))

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        signature = base64.b64decode(signature_base64)
        raw_key = base64.b64decode(public_key_base64)
        pub_key = Ed25519PublicKey.from_public_bytes(raw_key)
        pub_key.verify(signature, canonical.encode("utf-8"))
        return True
    except Exception:
        return False


def compute_attestation_hash(attestation: Dict[str, Any]) -> str:
    """Compute SHA-256 hash of attestation canonical JSON."""
    canonical = json.dumps(attestation, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
