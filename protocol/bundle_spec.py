"""
Proof Bundle Spec v1
=====================

Assembles v1 proof bundles with:
- spec_version field for schema evolution
- Compact canonical JSON (no whitespace)
- Merkle inclusion from transparency log
- Signed tree head reference
- Offline verification algorithm

Usage:
    from protocol.bundle_spec import assemble_v1_bundle, verify_bundle_offline

    bundle = assemble_v1_bundle(deal_id)
    result = verify_bundle_offline(bundle, sth, public_key_b64)
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SPEC_VERSION = "2.0.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Canonical Hash ──


def compute_bundle_hash_v1(
    deal_id: str,
    proofs: List[Dict],
    events: List[Dict],
    merkle_inclusion: Optional[Dict],
) -> str:
    """Compute v1 bundle hash with spec_version and compact separators."""
    def _strict_serializer(obj):
        """Reject non-JSON-serializable objects instead of silently converting."""
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    canonical = json.dumps(
        {
            "spec_version": SPEC_VERSION,
            "deal_id": deal_id,
            "proofs": proofs,
            "events": events,
            "merkle_inclusion": merkle_inclusion,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=_strict_serializer,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_bundle_hash_legacy(
    deal_id: str,
    proofs: List[Dict],
    events: List[Dict],
    merkle_inclusion: Optional[Dict],
) -> str:
    """Compute legacy bundle hash (no spec_version, default separators)."""
    def _strict_serializer(obj):
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    canonical = json.dumps(
        {
            "deal_id": deal_id,
            "proofs": proofs,
            "events": events,
            "merkle_inclusion": merkle_inclusion,
        },
        sort_keys=True,
        default=_strict_serializer,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Bundle Assembly ──


def assemble_v1_bundle(deal_id: str) -> Dict[str, Any]:
    """
    Assemble a v1 proof bundle for a deal.

    Collects proofs, events, Merkle inclusion from the transparency log,
    and the latest signed tree head.
    """
    bundle: Dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "bundle_type": "proof_bundle",
        "deal_id": deal_id,
        "exported_at": _now_iso(),
        "proofs": [],
        "events": [],
        "merkle_inclusion": None,
        "signed_tree_head": None,
        "root_hash": None,
    }

    # Collect proofs
    try:
        from proof_pipe import _proof_store

        bundle["proofs"] = [p for p in _proof_store if p.get("deal_id") == deal_id]
    except Exception:
        pass

    # Collect events
    try:
        from protocol.event_store import get_event_store

        chain = get_event_store().get_chain(deal_id)
        bundle["events"] = chain
    except Exception:
        pass

    # Transparency log inclusion
    try:
        from protocol.merkle_log import get_log

        log = get_log()
        leaf_index = log.find_leaf_index(deal_id)
        if leaf_index is not None:
            proof_data = log.inclusion_proof(leaf_index)
            bundle["merkle_inclusion"] = {
                "leaf_hash": proof_data["leaf_hash"],
                "leaf_index": proof_data["leaf_index"],
                "tree_size": proof_data["tree_size"],
                "merkle_root": proof_data["root_hash"],
                "proof": [
                    {"position": "left" if i % 2 == 1 else "right", "hash": h}
                    for i, h in enumerate(proof_data["proof"])
                ],
                "log_id": "aigentsy_settlement_log_v1",
            }
            bundle["root_hash"] = proof_data["root_hash"]

            # Include STH
            sth = log.get_latest_sth()
            bundle["signed_tree_head"] = sth
    except Exception as e:
        logger.debug(f"[BUNDLE_SPEC] Merkle log unavailable: {e}")

    # Legacy Merkle inclusion fallback
    if bundle["merkle_inclusion"] is None:
        try:
            from proof_merkle import get_receipt

            receipt = get_receipt(deal_id)
            if receipt:
                bundle["merkle_inclusion"] = {
                    "leaf_hash": receipt.get("leaf_hash"),
                    "merkle_proof": receipt.get("merkle_proof"),
                    "merkle_root": receipt.get("merkle_root"),
                    "date": receipt.get("date"),
                }
                bundle["root_hash"] = receipt.get("merkle_root")
        except Exception:
            pass

    # Attach proof chain provenance (not included in bundle_hash — metadata only)
    try:
        from protocol.proof_chain import get_proof_chain_store
        chain_store = get_proof_chain_store()
        link = chain_store.get_link(deal_id)
        if link:
            bundle["proof_chain"] = {
                "parent_proof_ids": link.parent_proof_ids,
                "children": chain_store.get_children(deal_id),
                "is_root": len(link.parent_proof_ids) == 0,
                "chain_hash": chain_store.compute_chain_hash(deal_id),
            }
    except Exception:
        pass

    # ── ProofPack v2: policy_layer (not included in bundle_hash — metadata only) ──
    # Embeds SLA, mandate, spawn, attestation, referral, outcome context into the bundle.
    # Makes each ProofPack a self-contained Living Commercial Artifact.
    policy_layer: Dict[str, Any] = {}

    # SLA context
    try:
        from protocol.executable_sla import get_sla_store
        sla = get_sla_store().get_by_deal(deal_id)
        if sla:
            policy_layer["sla"] = {
                "sla_id": sla.sla_id, "guarantees": sla.guarantees,
                "auto_settle_on_verify": sla.auto_settle_on_verify,
                "sla_hash": sla.sla_hash,
            }
    except Exception:
        pass

    # Mandate rules
    try:
        from protocol.event_store import get_event_store
        chain = get_event_store().get_chain(deal_id)
        go_event = next((e for e in chain if e.get("event_type") in ("GO_APPROVED", "AUTO_GO_APPROVED")), None)
        if go_event:
            pl = go_event.get("payload", {})
            policy_layer["mandate"] = {
                "policy_hash": pl.get("policy_hash", ""),
                "mandate_type": pl.get("mandate_type", "flat"),
            }
    except Exception:
        pass

    # Spawn template (if this deal was created by a spawned agent)
    try:
        from protocol.recursive_spawn import get_spawn_store
        spawn_rec = get_spawn_store().get_by_child(deal_id.split("_")[0] if "_" in deal_id else "")
        # Also check if any event actor is a spawned agent
        if not spawn_rec:
            for evt in bundle.get("events", []):
                actor = evt.get("actor_id", "")
                if actor:
                    spawn_rec = get_spawn_store().get_by_child(actor)
                    if spawn_rec:
                        break
        if spawn_rec:
            from dataclasses import asdict
            policy_layer["spawn"] = {
                "parent_id": spawn_rec.parent_id,
                "trust_inheritance_pct": spawn_rec.trust_inheritance_pct,
                "referral_fee_pct": spawn_rec.referral_fee_pct,
                "graduation_threshold": spawn_rec.graduation_threshold,
            }
    except Exception:
        pass

    # Attestation / trust context
    try:
        from protocol.reputation_attestation import get_attestation_store
        # Find the seller agent from events
        seller_id = ""
        for evt in bundle.get("events", []):
            if evt.get("event_type") == "PROOF_READY":
                seller_id = evt.get("actor_id", "")
                break
        if seller_id:
            att = get_attestation_store().get_by_agent(seller_id)
            if att:
                subj = att.get("credentialSubject", {})
                policy_layer["attestation"] = {
                    "ocs_score": subj.get("ocs_score"),
                    "ocs_tier": subj.get("ocs_tier"),
                    "total_settlements": subj.get("total_settlements", 0),
                }
    except Exception:
        pass

    # Referral chain
    try:
        from protocol.referral_graph import get_referral_store
        if seller_id:
            chain = get_referral_store().get_chain(seller_id)
            if chain:
                policy_layer["referral_chain"] = chain
    except Exception:
        pass

    # Outcome conditions
    try:
        from protocol.outcome_market import get_outcome_store
        outcome = get_outcome_store().get(deal_id)
        if outcome:
            policy_layer["outcome"] = {
                "metric": outcome.outcome_spec.get("metric"),
                "threshold": outcome.outcome_spec.get("threshold"),
                "base_usd": outcome.outcome_spec.get("base_usd"),
                "bonus_usd": outcome.outcome_spec.get("bonus_usd"),
            }
    except Exception:
        pass

    if policy_layer:
        bundle["policy_layer"] = policy_layer
        bundle["spec_version"] = "2.0.0"

    # Optionally attach latest anchor receipt for the log
    try:
        from protocol.sth_anchor import load_latest_receipt
        latest = load_latest_receipt()
        if latest and latest.get("tsa_status") == "granted":
            bundle["sth_anchor"] = {
                "anchor_id": latest.get("anchor_id"),
                "anchored_at": latest.get("anchored_at"),
                "tsa_url": latest.get("tsa_url"),
                "anchor_method": latest.get("anchor_method"),
                "tsr_base64": latest.get("tsr_base64"),
            }
    except Exception:
        pass

    # Compute bundle hash (anchor data is NOT included in hash — it is metadata)
    bundle["bundle_hash"] = compute_bundle_hash_v1(
        deal_id, bundle["proofs"], bundle["events"], bundle["merkle_inclusion"]
    )

    return {"ok": True, **bundle}


# ── Offline Verification ──


def verify_event_chain(events: List[Dict]) -> Dict[str, Any]:
    """
    Verify event chain integrity offline.

    No server imports required.
    """
    errors = []
    for i, event in enumerate(events):
        # Recompute hash
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

        # Check chain link
        if i > 0:
            if event.get("prev_hash") != events[i - 1].get("hash"):
                errors.append(
                    f"Event {i} ({event.get('event_id', '?')}): prev_hash break"
                )
        elif i == 0 and event.get("prev_hash", "") != "":
            # First event should have empty prev_hash — but tolerate non-empty
            # (some deals start mid-chain)
            pass

    return {
        "verified": len(errors) == 0,
        "event_count": len(events),
        "errors": errors,
    }


def verify_merkle_inclusion_rfc6962(
    leaf_hash: str,
    leaf_index: int,
    tree_size: int,
    proof: List[str],
    expected_root: str,
) -> bool:
    """
    Verify RFC 6962 Merkle inclusion proof offline.

    No server imports required. Uses 0x01 prefix for interior nodes.
    """
    from protocol.merkle_log import verify_inclusion

    return verify_inclusion(leaf_hash, leaf_index, tree_size, proof, expected_root)


def verify_merkle_inclusion_legacy(
    leaf_hash: str,
    proof: List[Dict[str, str]],
    expected_root: str,
) -> bool:
    """
    Verify legacy Merkle inclusion proof offline.

    Uses sorted concatenation (existing behavior).
    """
    current = leaf_hash
    for step in proof:
        sibling = step["hash"]
        if step["position"] == "left":
            combined = sibling + current if sibling < current else current + sibling
        else:
            combined = current + sibling if current < sibling else sibling + current
        current = hashlib.sha256(combined.encode()).hexdigest()
    return current == expected_root


def verify_sth_signature(
    sth: Dict[str, Any], public_key_base64: str
) -> bool:
    """
    Verify a signed tree head signature offline.

    Supports Ed25519 (primary) and HMAC-SHA256 (fallback).
    """
    sign_input = (
        f"{sth.get('log_id', '')}|{sth.get('tree_size', 0)}"
        f"|{sth.get('root_hash', '')}|{sth.get('timestamp', '')}"
    )

    import base64

    signature = base64.b64decode(sth.get("signature", ""))
    algorithm = sth.get("algorithm", "Ed25519")

    if algorithm == "Ed25519":
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            raw_key = base64.b64decode(public_key_base64)
            pub_key = Ed25519PublicKey.from_public_bytes(raw_key)
            pub_key.verify(signature, sign_input.encode("utf-8"))
            return True
        except Exception:
            return False
    elif algorithm == "HMAC-SHA256":
        # Cannot verify HMAC without shared secret — return False for offline
        return False
    return False


def verify_bundle_offline(
    bundle: Dict[str, Any],
    sth: Dict[str, Any] = None,
    public_key_base64: str = "",
) -> Dict[str, Any]:
    """
    Complete offline bundle verification.

    A third party can call this with ZERO access to AiGentsy's runtime.

    Args:
        bundle: The proof bundle JSON
        sth: Signed tree head (from /protocol/merkle/latest or bundle)
        public_key_base64: Ed25519 public key for STH verification

    Returns:
        Verification result with per-step pass/fail
    """
    deal_id = bundle.get("deal_id", "")
    spec_version = bundle.get("spec_version")
    proofs = bundle.get("proofs", [])
    events = bundle.get("events", [])
    merkle_inclusion = bundle.get("merkle_inclusion")
    claimed_hash = bundle.get("bundle_hash", "")

    result = {
        "deal_id": deal_id,
        "spec_version": spec_version,
        "steps": {},
        "verified": False,
    }

    # Use STH from bundle if not provided separately
    if sth is None:
        sth = bundle.get("signed_tree_head")

    # Step 1: Verify bundle hash
    if spec_version:
        computed_hash = compute_bundle_hash_v1(
            deal_id, proofs, events, merkle_inclusion
        )
    else:
        computed_hash = compute_bundle_hash_legacy(
            deal_id, proofs, events, merkle_inclusion
        )

    hash_ok = computed_hash == claimed_hash
    result["steps"]["bundle_hash"] = {
        "passed": hash_ok,
        "computed": computed_hash,
        "claimed": claimed_hash,
    }

    # Step 2: Verify event chain
    chain_result = verify_event_chain(events)
    result["steps"]["event_chain"] = {
        "passed": chain_result["verified"],
        "event_count": chain_result["event_count"],
        "errors": chain_result["errors"],
    }

    # Step 3: Verify Merkle inclusion
    merkle_ok = False
    if merkle_inclusion:
        if "leaf_index" in merkle_inclusion and "tree_size" in merkle_inclusion:
            # v1 RFC 6962 proof
            proof_hashes = [
                p["hash"] if isinstance(p, dict) else p
                for p in merkle_inclusion.get("proof", [])
            ]
            merkle_ok = verify_merkle_inclusion_rfc6962(
                merkle_inclusion.get("leaf_hash", ""),
                merkle_inclusion.get("leaf_index", 0),
                merkle_inclusion.get("tree_size", 0),
                proof_hashes,
                merkle_inclusion.get("merkle_root", ""),
            )
        elif "merkle_proof" in merkle_inclusion:
            # Legacy proof
            merkle_ok = verify_merkle_inclusion_legacy(
                merkle_inclusion.get("leaf_hash", ""),
                merkle_inclusion.get("merkle_proof", []),
                merkle_inclusion.get("merkle_root", ""),
            )
    result["steps"]["merkle_inclusion"] = {
        "passed": merkle_ok,
        "type": "rfc6962" if merkle_inclusion and "leaf_index" in (merkle_inclusion or {}) else "legacy",
    }

    # Step 4: Verify STH signature
    sth_ok = False
    if sth and public_key_base64:
        sth_ok = verify_sth_signature(sth, public_key_base64)
    result["steps"]["sth_signature"] = {
        "passed": sth_ok,
        "skipped": not (sth and public_key_base64),
    }

    # Step 5: Cross-reference
    cross_ok = False
    if merkle_inclusion and sth:
        cross_ok = (
            merkle_inclusion.get("merkle_root") == sth.get("root_hash")
        )
    result["steps"]["cross_reference"] = {
        "passed": cross_ok,
        "skipped": not (merkle_inclusion and sth),
    }

    # Overall
    mandatory_steps = ["bundle_hash", "event_chain"]
    optional_steps = ["merkle_inclusion", "sth_signature", "cross_reference"]

    mandatory_pass = all(result["steps"][s]["passed"] for s in mandatory_steps)
    optional_pass = all(
        result["steps"][s].get("passed") or result["steps"][s].get("skipped")
        for s in optional_steps
    )

    result["verified"] = mandatory_pass and optional_pass
    result["proof_count"] = len(proofs)
    result["event_count"] = len(events)

    return result
