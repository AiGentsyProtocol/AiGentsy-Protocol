"""
aigentsy-verify — Standalone Offline Verification
===================================================

Verify AiGentsy proof bundles and attestations with ZERO dependency
on AiGentsy's runtime. All verification runs locally using published
algorithms and the Ed25519 public key.

Quick start:

    from aigentsy_verify import verify_bundle, verify_attestation

    # Verify a proof bundle
    result = verify_bundle(bundle_json, public_key_base64="...")
    print(result["verified"])  # True/False
    print(result["steps"])     # Per-step results

    # Verify an attestation
    ok = verify_attestation(attestation, signature_b64, public_key_base64="...")
    print(ok)  # True/False

Public key: https://aigentsy-ame-runtime.onrender.com/protocol/merkle/public-key
Bundle spec: https://aigentsy.com/data/proof_bundle_spec.md
Conformance: https://aigentsy.com/data/conformance_vectors.json
"""

__version__ = "1.0.0"

from aigentsy_verify.bundle import verify_bundle, verify_event_chain, compute_bundle_hash
from aigentsy_verify.attestation import verify_attestation
from aigentsy_verify.merkle import verify_inclusion, verify_sth_signature, verify_consistency
from aigentsy_verify.anchor import verify_anchor_receipt
from aigentsy_verify.keys import fetch_public_key, load_public_key_from_file
from aigentsy_verify.session import VerifierSession

__all__ = [
    "verify_bundle",
    "verify_event_chain",
    "compute_bundle_hash",
    "verify_attestation",
    "verify_inclusion",
    "verify_sth_signature",
    "verify_consistency",
    "verify_anchor_receipt",
    "fetch_public_key",
    "load_public_key_from_file",
    "VerifierSession",
]
