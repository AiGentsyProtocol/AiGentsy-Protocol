"""
Anchor receipt verification — verify RFC 3161 STH anchor receipts offline.

Checks that an anchor receipt's sth_digest matches the canonical STH JSON,
confirming the receipt correctly references the claimed signed tree head.
The opaque TSR payload is not parsed — verify it with `openssl ts -verify`.

Usage:
    from aigentsy_verify import verify_anchor_receipt

    ok, details = verify_anchor_receipt(receipt)
    print(ok)       # True/False
    print(details)  # {"sth_digest_match": True, ...}
"""

import hashlib
import json
from typing import Any, Dict, Tuple


def _canonical_sth_json(sth: Dict[str, Any]) -> str:
    """Canonical JSON of an STH for digest computation (matches runtime)."""
    return json.dumps(sth, sort_keys=True, separators=(",", ":"))


def verify_anchor_receipt(receipt: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Verify an STH anchor receipt's integrity offline.

    Checks:
    1. sth_digest matches SHA-256 of the canonical STH JSON in the receipt
    2. Required fields are present
    3. tsa_status was "granted"

    Does NOT verify the opaque TSR payload — use `openssl ts -verify` for that.

    Args:
        receipt: Anchor receipt dict (from /protocol/merkle/anchors)

    Returns:
        Tuple of (passed: bool, details: dict)
    """
    details: Dict[str, Any] = {
        "sth_digest_match": False,
        "fields_present": False,
        "tsa_granted": False,
        "errors": [],
    }

    # Check required fields
    required = [
        "receipt_version", "anchor_id", "sth", "sth_digest",
        "sth_digest_algorithm", "anchor_method", "tsa_url",
        "tsa_status", "anchored_at",
    ]
    missing = [f for f in required if f not in receipt]
    if missing:
        details["errors"].append(f"Missing fields: {missing}")
        return False, details

    sth_fields = ["tree_size", "root_hash", "timestamp", "signature"]
    sth = receipt.get("sth", {})
    missing_sth = [f for f in sth_fields if f not in sth]
    if missing_sth:
        details["errors"].append(f"Missing STH fields: {missing_sth}")
        return False, details

    details["fields_present"] = True

    # Check digest algorithm
    if receipt.get("sth_digest_algorithm") != "SHA-256":
        details["errors"].append(
            f"Unsupported digest algorithm: {receipt.get('sth_digest_algorithm')}"
        )
        return False, details

    # Verify sth_digest matches canonical STH JSON
    canonical = _canonical_sth_json(sth)
    computed_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    claimed_digest = receipt.get("sth_digest", "")

    details["computed_digest"] = computed_digest
    details["claimed_digest"] = claimed_digest

    if computed_digest == claimed_digest:
        details["sth_digest_match"] = True
    else:
        details["errors"].append(
            f"STH digest mismatch: computed={computed_digest[:16]}... "
            f"claimed={claimed_digest[:16]}..."
        )
        return False, details

    # Check TSA status
    tsa_status = receipt.get("tsa_status", "")
    if tsa_status == "granted":
        details["tsa_granted"] = True
    else:
        details["errors"].append(f"TSA status is '{tsa_status}', not 'granted'")
        return False, details

    # Check TSR payload exists
    tsr = receipt.get("tsr_base64")
    details["tsr_present"] = bool(tsr)
    if not tsr:
        details["errors"].append("tsr_base64 is empty — cannot verify externally")
        # Still pass — the digest is correct, TSR just wasn't stored
        # (This shouldn't happen in practice)

    details["anchor_id"] = receipt.get("anchor_id", "")
    details["anchor_method"] = receipt.get("anchor_method", "")
    details["anchored_at"] = receipt.get("anchored_at", "")

    return True, details
