"""
Proof Bundle v1 verification.

All functions are standalone — no AiGentsy runtime imports.
Algorithms match protocol/bundle_spec.py exactly.

Pass 82Q-A — Optional Spec 3 actor-signature sidecar verification.
Default verifier behavior is unchanged. The sidecar is a top-level
`actor_signature_sidecar` field that legacy verifiers silently ignore;
strict callers may opt into per-actor Ed25519 signature validation via
`verify_actor_signature_sidecar()`.
"""

import base64
import hashlib
import json
from typing import Any, Dict, List, Optional

from aigentsy_verify.merkle import verify_inclusion, verify_sth_signature

SPEC_VERSION = "1.0.0"

# Pass 82Q-A — sidecar canonical payload field order. Mirrors
# runtime/protocol/signing_schema.py:canonical_event_for_signing
# (7 _hash_record fields + key_id). sort_keys=True, compact separators.
ACTOR_SIDECAR_CANONICAL_KEYS = (
    "event_id",
    "event_type",
    "deal_id",
    "actor_id",
    "timestamp",
    "payload",
    "prev_hash",
    "key_id",
)


def compute_bundle_hash(
    deal_id: str,
    proofs: List[Dict],
    events: List[Dict],
    merkle_inclusion: Optional[Dict],
    spec_version: str = SPEC_VERSION,
) -> str:
    """
    Compute the SHA-256 bundle hash.

    For v1 bundles (spec_version present):
        Canonical JSON with sort_keys=True, separators=(",", ":"), includes spec_version

    For legacy bundles (no spec_version):
        Canonical JSON with sort_keys=True, default separators
    """
    if spec_version:
        canonical = json.dumps(
            {
                "spec_version": spec_version,
                "deal_id": deal_id,
                "proofs": proofs,
                "events": events,
                "merkle_inclusion": merkle_inclusion,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    else:
        canonical = json.dumps(
            {
                "deal_id": deal_id,
                "proofs": proofs,
                "events": events,
                "merkle_inclusion": merkle_inclusion,
            },
            sort_keys=True,
            default=str,
        )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_event_chain(events: List[Dict]) -> Dict[str, Any]:
    """
    Verify event chain integrity offline.

    Each event's hash is recomputed from its canonical fields.
    Each event's prev_hash must match the preceding event's hash.

    Returns:
        {"verified": bool, "event_count": int, "errors": list}
    """
    errors = []
    for i, event in enumerate(events):
        canonical = json.dumps(
            {
                "event_id": event.get("event_id", ""),
                "event_type": event.get("event_type", ""),
                "deal_id": event.get("deal_id", ""),
                "actor_id": event.get("actor_id", ""),
                "timestamp": event.get("timestamp", ""),
                "payload": event.get("payload", {}),
                "prev_hash": event.get("prev_hash", ""),
            },
            sort_keys=True,
        )
        expected_hash = hashlib.sha256(canonical.encode()).hexdigest()
        if event.get("hash") != expected_hash:
            errors.append(f"Event {i} ({event.get('event_id', '?')}): hash mismatch")

        if i > 0:
            if event.get("prev_hash") != events[i - 1].get("hash"):
                errors.append(
                    f"Event {i} ({event.get('event_id', '?')}): prev_hash break"
                )

    return {
        "verified": len(errors) == 0,
        "event_count": len(events),
        "errors": errors,
    }


def verify_bundle(
    bundle: Dict[str, Any],
    public_key_base64: str = "",
    sth: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Complete 5-step offline bundle verification.

    A third party can call this with ZERO access to AiGentsy's runtime.

    Args:
        bundle: The proof bundle JSON (dict)
        public_key_base64: Ed25519 public key (base64) for STH verification.
            Obtain from https://aigentsy.com/data/log_public_key.json
        sth: Signed tree head (optional — uses bundle's STH if not provided)

    Returns:
        Verification result with per-step pass/fail:
        {
            "verified": bool,       # Overall result
            "deal_id": str,
            "spec_version": str,
            "proof_count": int,
            "event_count": int,
            "steps": {
                "bundle_hash": {"passed": bool, ...},
                "event_chain": {"passed": bool, ...},
                "merkle_inclusion": {"passed": bool, ...},
                "sth_signature": {"passed": bool, ...},
                "cross_reference": {"passed": bool, ...},
            }
        }
    """
    deal_id = bundle.get("deal_id", "")
    spec_version = bundle.get("spec_version")
    proofs = bundle.get("proofs", [])
    events = bundle.get("events", [])
    merkle_inclusion = bundle.get("merkle_inclusion")
    claimed_hash = bundle.get("bundle_hash", "")

    result: Dict[str, Any] = {
        "deal_id": deal_id,
        "spec_version": spec_version,
        "steps": {},
        "verified": False,
    }

    if sth is None:
        sth = bundle.get("signed_tree_head")

    # Step 1: Bundle hash
    computed_hash = compute_bundle_hash(
        deal_id, proofs, events, merkle_inclusion,
        spec_version=spec_version or "",
    )
    hash_ok = computed_hash == claimed_hash
    result["steps"]["bundle_hash"] = {
        "passed": hash_ok,
        "computed": computed_hash,
        "claimed": claimed_hash,
    }

    # Step 2: Event chain
    chain_result = verify_event_chain(events)
    result["steps"]["event_chain"] = {
        "passed": chain_result["verified"],
        "event_count": chain_result["event_count"],
        "errors": chain_result["errors"],
    }

    # Step 3: Merkle inclusion
    merkle_ok = False
    merkle_type = "none"
    if merkle_inclusion and "leaf_index" in merkle_inclusion and "tree_size" in merkle_inclusion:
        merkle_type = "rfc6962"
        proof_hashes = [
            p["hash"] if isinstance(p, dict) else p
            for p in merkle_inclusion.get("proof", [])
        ]
        merkle_ok = verify_inclusion(
            merkle_inclusion.get("leaf_hash", ""),
            merkle_inclusion.get("leaf_index", 0),
            merkle_inclusion.get("tree_size", 0),
            proof_hashes,
            merkle_inclusion.get("merkle_root", ""),
        )
    result["steps"]["merkle_inclusion"] = {
        "passed": merkle_ok,
        "type": merkle_type,
        "skipped": not merkle_inclusion,
    }

    # Step 4: STH signature
    sth_ok = False
    sth_skipped = not (sth and public_key_base64)
    if sth and public_key_base64:
        sth_ok = verify_sth_signature(sth, public_key_base64)
    result["steps"]["sth_signature"] = {
        "passed": sth_ok,
        "skipped": sth_skipped,
    }

    # Step 5: Cross-reference
    cross_ok = False
    cross_skipped = not (merkle_inclusion and sth)
    if merkle_inclusion and sth:
        cross_ok = merkle_inclusion.get("merkle_root") == sth.get("root_hash")
    result["steps"]["cross_reference"] = {
        "passed": cross_ok,
        "skipped": cross_skipped,
    }

    # Overall verdict
    mandatory_pass = all(
        result["steps"][s]["passed"] for s in ["bundle_hash", "event_chain"]
    )
    optional_pass = all(
        result["steps"][s].get("passed") or result["steps"][s].get("skipped")
        for s in ["merkle_inclusion", "sth_signature", "cross_reference"]
    )
    result["verified"] = mandatory_pass and optional_pass
    result["proof_count"] = len(proofs)
    result["event_count"] = len(events)

    skipped = [s for s in result["steps"] if result["steps"][s].get("skipped")]
    result["steps_run"] = len(result["steps"]) - len(skipped)
    result["steps_skipped"] = len(skipped)
    result["verification_level"] = "full" if not skipped else "offline"

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Pass 82Q-A — Optional Spec 3 actor-signature sidecar verification.
#
# Design notes:
#  * The sidecar lives at top-level `actor_signature_sidecar`. Legacy
#    verifiers ignore unknown top-level fields, and the bundle_hash
#    projection whitelists only {spec_version, deal_id, proofs, events,
#    merkle_inclusion} — so adding or removing the sidecar does NOT
#    change bundle_hash.
#  * Per-actor signatures are keyed by the existing event `hash` field
#    (the 7-field SHA-256 from verify_event_chain).
#  * Each signature signs the canonical 8-field projection mirroring
#    runtime/protocol/signing_schema.py::canonical_event_for_signing
#    (7 _hash_record fields + key_id), sort_keys=True, compact separators.
#  * Strict-mode failure modes are SEPARATE from the core 5-step verifier
#    result — verify_bundle() is unaffected by sidecar state by default.
# ─────────────────────────────────────────────────────────────────────────────


def _canonical_signed_payload(event: Dict[str, Any], key_id: str) -> bytes:
    """Build the canonical signed payload for one event + key_id binding."""
    obj = {
        "event_id":   event.get("event_id", ""),
        "event_type": event.get("event_type", ""),
        "deal_id":    event.get("deal_id", ""),
        "actor_id":   event.get("actor_id", ""),
        "timestamp":  event.get("timestamp", ""),
        "payload":    event.get("payload", {}),
        "prev_hash":  event.get("prev_hash", ""),
        "key_id":     key_id,
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _compute_sidecar_hash(sidecar: Dict[str, Any]) -> str:
    """SHA-256 of the canonical sidecar payload, excluding the hash itself."""
    payload = {k: v for k, v in sidecar.items() if k != "sidecar_hash"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def verify_actor_signature_sidecar(
    bundle: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate an optional `actor_signature_sidecar` attached to a bundle.

    This function is SEPARATE from verify_bundle(). The default 5-step
    bundle verification is unaffected. Callers that want strict per-actor
    signature checking call this in addition to verify_bundle().

    Returns a dict shaped like the per-step results in verify_bundle()'s
    `steps` block:

        {
            "passed": bool,        # overall sidecar verdict
            "present": bool,       # sidecar present in bundle?
            "errors": [str, ...],  # specific failure reasons
            "signatures_checked": int,
            "sidecar_hash": {"computed": str, "claimed": str, "passed": bool},
            "events_signed": int,
            "events_total": int,
            "actor_ids": [str, ...],
        }

    Failure modes (when sidecar IS present):
      * sidecar_hash mismatch
      * any signature does not verify
      * any signature keyed by an event_hash that does not appear in the chain
      * any signature missing required fields
      * unsupported signature_alg / canonicalization
      * altered actor_id, key_id, public_key, or signature bytes
    """
    sidecar = bundle.get("actor_signature_sidecar")
    if not sidecar:
        return {
            "passed": False,
            "present": False,
            "errors": [],
            "signatures_checked": 0,
            "events_signed": 0,
            "events_total": len(bundle.get("events", [])),
            "actor_ids": [],
        }

    errors: List[str] = []

    # Algorithm + canonicalization gate
    alg = sidecar.get("signature_alg", "")
    canon = sidecar.get("canonicalization", "")
    if alg != "Ed25519":
        errors.append(f"unsupported signature_alg: {alg!r}")
    if canon != "canonical_event_for_signing_v1":
        errors.append(f"unsupported canonicalization: {canon!r}")

    # Sidecar hash check
    claimed_hash = sidecar.get("sidecar_hash", "")
    computed_hash = _compute_sidecar_hash(sidecar)
    sidecar_hash_ok = claimed_hash == computed_hash
    if not sidecar_hash_ok:
        errors.append("sidecar_hash mismatch")

    # Lazy import — only required when sidecar is actually present and being
    # validated. Keeps the default verifier dependency-light for legacy paths.
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as e:  # pragma: no cover — environment-specific
        return {
            "passed": False,
            "present": True,
            "errors": [f"cryptography module unavailable: {e}"],
            "signatures_checked": 0,
            "events_signed": 0,
            "events_total": len(bundle.get("events", [])),
            "actor_ids": [],
        }

    events = bundle.get("events", [])
    events_by_hash = {e.get("hash", ""): e for e in events}
    signatures_by_event_hash = sidecar.get("signatures_by_event_hash", {}) or {}

    checked = 0
    actor_ids = set()
    for event_hash, sig_entries in signatures_by_event_hash.items():
        if event_hash not in events_by_hash:
            errors.append(f"signed event_hash {event_hash[:16]}... not in chain")
            continue
        event = events_by_hash[event_hash]
        for i, entry in enumerate(sig_entries):
            checked += 1
            actor_id = entry.get("actor_id", "")
            key_id = entry.get("key_id", "")
            pub_b64 = entry.get("public_key_base64", "")
            sig_b64 = entry.get("signature_base64", "")
            if not (actor_id and key_id and pub_b64 and sig_b64):
                errors.append(
                    f"signature {i} on {event_hash[:16]}...: missing required field"
                )
                continue
            actor_ids.add(actor_id)
            try:
                pub_raw = base64.b64decode(pub_b64)
                sig_raw = base64.b64decode(sig_b64)
                pubkey = Ed25519PublicKey.from_public_bytes(pub_raw)
                canonical = _canonical_signed_payload(event, key_id)
                pubkey.verify(sig_raw, canonical)
            except InvalidSignature:
                errors.append(
                    f"signature {i} on {event_hash[:16]}... by {actor_id} "
                    f"(key_id={key_id}): InvalidSignature"
                )
            except Exception as e:
                errors.append(
                    f"signature {i} on {event_hash[:16]}... by {actor_id}: "
                    f"{type(e).__name__}: {e}"
                )

    overall = (not errors) and sidecar_hash_ok and checked > 0

    return {
        "passed": overall,
        "present": True,
        "errors": errors,
        "signatures_checked": checked,
        "sidecar_hash": {
            "computed": computed_hash,
            "claimed": claimed_hash,
            "passed": sidecar_hash_ok,
        },
        "events_signed": len(signatures_by_event_hash),
        "events_total": len(events),
        "actor_ids": sorted(actor_ids),
    }
