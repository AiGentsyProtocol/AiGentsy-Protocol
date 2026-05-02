"""
Proof Bundle v1 verification.

All functions are standalone — no AiGentsy runtime imports.
Algorithms match protocol/bundle_spec.py exactly.
"""

import hashlib
import json
from typing import Any, Dict, List, Optional

from aigentsy_verify.merkle import verify_inclusion, verify_sth_signature

SPEC_VERSION = "1.0.0"


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
