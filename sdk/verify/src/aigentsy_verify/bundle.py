"""
Proof Bundle v1 + v3 verification.

All functions are standalone — no AiGentsy runtime imports.
Algorithms match protocol/bundle_spec.py + protocol/signing_schema.py.

Spec dispatch:
  v2 (spec_version="2.0.0"): 5-step verification (bundle_hash, event_chain,
    merkle_inclusion, sth_signature, cross_reference). Byte-identical
    output to 1.3.0's verify_bundle.
  v3 (spec_version="3.0.0"): 5-step + a 6th `actor_signatures` step that
    Ed25519-verifies each event's per-actor signature against the
    bundle's key_directory and enforces validity-at-signing-time.
"""

import base64
import hashlib
import hmac
import json
from typing import Any, Dict, List, Optional

from aigentsy_verify.merkle import verify_inclusion, verify_sth_signature
from aigentsy_verify.merkle import leaf_hash_hex  # PROOF-BINDING-1 (additive)

SPEC_VERSION = "1.0.0"


# ── Canonical bytes the per-actor signature covers ──────────────────
#
# MUST be byte-identical to protocol.signing_schema.canonical_event_for_signing
# so an externally-signed event verifies with this offline package.

_FIELDS_FOR_SIGNING = (
    "event_id", "event_type", "deal_id", "actor_id",
    "timestamp", "payload", "prev_hash",
)


def canonical_event_for_signing(event: Dict[str, Any], key_id: str) -> bytes:
    """Return the EXACT bytes a per-actor signature covers.

    Mirror of protocol.signing_schema.canonical_event_for_signing — same
    byte output for the same input.
    """
    if not isinstance(key_id, str) or not key_id:
        raise ValueError("key_id must be a non-empty string")
    canonical: Dict[str, Any] = {f: event[f] for f in _FIELDS_FOR_SIGNING}
    canonical["payload"]   = event.get("payload", {}) or {}
    canonical["prev_hash"] = event.get("prev_hash", "") or ""
    canonical["key_id"]    = key_id
    return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _iso_le(a: str, b: str) -> bool:
    """Lexicographic ISO 8601 UTC comparison: a <= b. All AiGentsy
    timestamps are UTC ISO 8601, so lex order matches chronological."""
    return (a or "") <= (b or "")


def _key_valid_at(key_entry: Dict[str, Any], event_ts: str) -> bool:
    """A key is valid at `event_ts` iff:
       issued_at <= event_ts   AND   (revoked_at is None  OR  event_ts < revoked_at)
    """
    issued_at  = key_entry.get("issued_at", "")
    revoked_at = key_entry.get("revoked_at")
    if not issued_at:
        return False
    if not _iso_le(issued_at, event_ts):
        return False
    if revoked_at is not None:
        if _iso_le(revoked_at, event_ts):
            # revoked_at <= event_ts → key was already revoked at signing
            return False
    return True


def _verify_one_actor_signature(
    event: Dict[str, Any],
    key_directory: Dict[str, Any],
) -> Dict[str, Any]:
    eid = event.get("event_id", "")
    et = event.get("event_type", "")
    sig = event.get("actor_signature")
    if not isinstance(sig, dict) or not sig.get("signature"):
        return {
            "event_id": eid, "event_type": et, "key_id": None,
            "result": "attribution-only",
            "reason": "no actor_signature on this event",
        }

    key_id = sig.get("key_id") or event.get("key_id") or ""
    sig_b64 = sig.get("signature", "")
    if not key_id:
        return {
            "event_id": eid, "event_type": et, "key_id": None,
            "result": "FAIL", "reason": "actor_signature missing key_id",
        }

    key_entry = (key_directory or {}).get(key_id)
    if not key_entry:
        return {
            "event_id": eid, "event_type": et, "key_id": key_id,
            "result": "FAIL",
            "reason": f"key_id {key_id!r} not in bundle.key_directory",
        }

    if not _key_valid_at(key_entry, event.get("timestamp", "")):
        return {
            "event_id": eid, "event_type": et, "key_id": key_id,
            "result": "FAIL",
            "reason": (
                f"key {key_id!r} not valid at event timestamp "
                f"(issued_at={key_entry.get('issued_at','')}, "
                f"revoked_at={key_entry.get('revoked_at')}, "
                f"event_ts={event.get('timestamp','')})"
            ),
        }

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        return {
            "event_id": eid, "event_type": et, "key_id": key_id,
            "result": "FAIL", "reason": "cryptography package not installed",
        }

    try:
        pub_raw = base64.b64decode(key_entry["public_key_base64"], validate=True)
        if len(pub_raw) != 32:
            raise ValueError(f"public key must be 32 bytes; got {len(pub_raw)}")
        pub = Ed25519PublicKey.from_public_bytes(pub_raw)
        msg = canonical_event_for_signing(event, key_id)
        sig_raw = base64.b64decode(sig_b64, validate=True)
        pub.verify(sig_raw, msg)
    except InvalidSignature:
        return {
            "event_id": eid, "event_type": et, "key_id": key_id,
            "result": "FAIL", "reason": "Ed25519 signature does not verify",
        }
    except Exception as e:
        return {
            "event_id": eid, "event_type": et, "key_id": key_id,
            "result": "FAIL", "reason": f"verify error: {e}",
        }

    # ── Actor/key binding (substitution-attack prevention at verify time) ──
    # canonical_event_for_signing already includes actor_id + key_id in the
    # signed bytes, so a signature cannot be forged across (actor_id,
    # key_id) pairs at the SIGNING side. But the verifier must also
    # confirm that the directory says this key belongs to the actor the
    # event claims — otherwise an attacker who controls key K_B could
    # sign an event claiming actor_id=A using key_id=K_B and the
    # signature would verify cryptographically against K_B's pubkey.
    # By checking key_directory[K_B].actor_id == event.actor_id we
    # close the loop.
    dir_actor_id = key_entry.get("actor_id", "")
    event_actor_id = event.get("actor_id", "")
    if dir_actor_id and event_actor_id and dir_actor_id != event_actor_id:
        return {
            "event_id": eid, "event_type": et, "key_id": key_id,
            "result": "FAIL",
            "reason": (
                f"actor/key mismatch: key {key_id!r} is registered to "
                f"actor {dir_actor_id!r} but the event claims actor "
                f"{event_actor_id!r}. The signature verifies "
                f"cryptographically against the key but the binding "
                f"is wrong (substitution attempt)."
            ),
        }

    return {
        "event_id": eid, "event_type": et, "key_id": key_id,
        "result": "PASS", "reason": "",
    }


def verify_actor_signatures(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Verify all per-actor signatures in a 3.0.0 bundle.

    The step PASSES iff every event WITH a signature verifies. Events
    without signatures do NOT cause failure (mixed-bundle support).
    """
    events = bundle.get("events", []) or []
    key_directory = bundle.get("key_directory", {}) or {}
    per_event: List[Dict[str, Any]] = []
    signed_count = 0
    passed_count = 0
    for ev in events:
        r = _verify_one_actor_signature(ev, key_directory)
        per_event.append(r)
        if r["result"] in ("PASS", "FAIL"):
            signed_count += 1
            if r["result"] == "PASS":
                passed_count += 1
    return {
        "passed": signed_count > 0 and passed_count == signed_count,
        "skipped": signed_count == 0,
        "events": per_event,
        "signed_count": signed_count,
        "passed_count": passed_count,
    }


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


def _key_active_at(entry: Dict[str, Any], at_ts: str) -> bool:
    """A key is valid at `at_ts` iff:
        issued_at <= at_ts AND (revoked_at is None OR at_ts < revoked_at)
    AND status == "active".
    """
    if entry.get("status", "") != "active":
        return False
    issued_at = entry.get("issued_at", "")
    revoked_at = entry.get("revoked_at")
    if not issued_at or not _iso_le(issued_at, at_ts or ""):
        return False
    if revoked_at:
        if _iso_le(revoked_at, at_ts or ""):
            return False
    return True


def _lookup_key_in_directory(
    bundle: Dict[str, Any], key_id: str,
) -> Optional[Dict[str, Any]]:
    """Lookup key_id in bundle.key_directory.keys_by_key_id.

    Returns the entry dict or None. Tolerant of absent / malformed
    directory — returns None silently in all such cases.
    """
    if not isinstance(key_id, str) or not key_id:
        return None
    kd = bundle.get("key_directory")
    if not isinstance(kd, dict):
        return None
    keys_by_key_id = kd.get("keys_by_key_id")
    if not isinstance(keys_by_key_id, dict):
        return None
    entry = keys_by_key_id.get(key_id)
    if not isinstance(entry, dict):
        return None
    return entry


# ── Actor-signature sidecar (consolidated from the protocol mirror) ─────
#
# Ported UNCHANGED from the protocol verifier so the runtime release
# authority is the single source for every verifier behavior. Behavior,
# signature, validation semantics and failure modes are byte-preserved;
# this is a consolidation, not a redesign.

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
            # Pass 82Q-D — Strong Level 1 binding result. Absent sidecar
            # implies no binding to check; legacy bundles remain valid.
            "binding_present":   False,
            "binding_verified":  False,
            "binding_source":    "",
            "binding_errors":    [],
            "bindings_checked":  0,
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

    # Pass 82Q-D — Strong Level 1: determine whether a key_directory is
    # attached to the bundle. When present, the directory becomes the
    # canonical source for the verification public key, and each entry
    # must satisfy actor/key binding + validity-window checks.
    directory_present = isinstance(bundle.get("key_directory"), dict) and isinstance(
        bundle.get("key_directory", {}).get("keys_by_key_id"), dict
    )
    binding_errors: List[str] = []
    bindings_checked = 0

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
            signed_at = entry.get("signed_at", "")
            if not (actor_id and key_id and pub_b64 and sig_b64):
                errors.append(
                    f"signature {i} on {event_hash[:16]}...: missing required field"
                )
                continue
            actor_ids.add(actor_id)

            # Pass 82Q-D — When key_directory is present, it is the binding
            # source of truth. We lookup the entry, validate the binding,
            # and then use the directory's public_key_base64 as the canonical
            # key for the Ed25519 verify. When directory is absent, we fall
            # back to the sidecar's self-supplied public_key_base64 (the
            # Pass 82Q-A path) — sidecar.passed can still be True but
            # binding_verified will be False.
            canonical_pub_b64 = pub_b64  # default: sidecar entry's key
            if directory_present:
                bindings_checked += 1
                dir_entry = _lookup_key_in_directory(bundle, key_id)
                if dir_entry is None:
                    binding_errors.append(
                        f"signature {i} on {event_hash[:16]}... by {actor_id}: "
                        f"key_id {key_id!r} not in bundle.key_directory"
                    )
                    # Fall back to sidecar-supplied key for the signature
                    # verify so the failure is attributed to "binding", not
                    # "signature". Sidecar `passed` reflects sig validity;
                    # binding_verified reflects directory binding.
                else:
                    dir_actor_id = dir_entry.get("actor_id", "")
                    dir_public_key = dir_entry.get("public_key_base64", "")
                    dir_status = dir_entry.get("status", "")
                    # Binding check 1: directory's actor_id must match the
                    # SIGNED event's actor_id (not the sidecar metadata).
                    event_actor_id = event.get("actor_id", "")
                    if dir_actor_id and event_actor_id and dir_actor_id != event_actor_id:
                        binding_errors.append(
                            f"signature {i} on {event_hash[:16]}...: "
                            f"actor mismatch — directory says {dir_actor_id!r}, "
                            f"event says {event_actor_id!r}"
                        )
                    # Binding check 2: sidecar entry's public_key must
                    # match the directory's public_key for this key_id.
                    if dir_public_key and pub_b64 and dir_public_key != pub_b64:
                        binding_errors.append(
                            f"signature {i} on {event_hash[:16]}...: "
                            f"public_key mismatch between sidecar and directory"
                        )
                    # Binding check 3: key must be active.
                    if dir_status != "active":
                        binding_errors.append(
                            f"signature {i} on {event_hash[:16]}...: "
                            f"key {key_id!r} status={dir_status!r} is not active"
                        )
                    # Binding check 4: key must have been valid at signed_at.
                    if signed_at and not _key_active_at(dir_entry, signed_at):
                        binding_errors.append(
                            f"signature {i} on {event_hash[:16]}...: "
                            f"key {key_id!r} not valid at signed_at={signed_at!r}"
                        )
                    # Canonical key for the Ed25519 verify is the directory's.
                    if dir_public_key:
                        canonical_pub_b64 = dir_public_key

            try:
                pub_raw = base64.b64decode(canonical_pub_b64)
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
    binding_verified = (
        directory_present
        and bindings_checked > 0
        and not binding_errors
    )

    # Pass 82Q-D — Step 6 binding-fail policy (operator-locked):
    #   * directory absent → binding_verified=False but does NOT fail
    #     the overall sidecar verdict (legacy bundles + bundles emitted
    #     before enrollment was wired stay green if sig is valid).
    #   * directory present + binding errors → overall sidecar fails.
    if directory_present and binding_errors:
        overall = False

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
        # Pass 82Q-D — Strong Level 1 binding result.
        "binding_present":   directory_present,
        "binding_verified":  binding_verified,
        "binding_source":    "bundle_key_directory" if directory_present else "",
        "binding_errors":    binding_errors,
        "bindings_checked":  bindings_checked,
    }


# ── Leaf-to-event binding (PROOF-BINDING-1) ─────────────────────────────
#
# The transparency log hashes a leaf over exactly these five canonical event
# fields (protocol/merkle_log.py, TransparencyLog.append_entry):
#
#     leaf_data = {deal_id, event_type, event_id, event_hash, timestamp}
#     canonical = json.dumps(leaf_data, sort_keys=True, separators=(",", ":"))
#     leaf_hash = rfc6962_leaf_hash(canonical.encode("utf-8"))   # 0x00 prefix
#
# Every field is present on the canonical event, so the leaf is reconstructible
# from the bundle itself — no new bundle field, schema version or exporter
# change. `leaf_hash != event["hash"]` is EXPECTED: the leaf is a
# domain-separated hash OVER those fields, not the event hash itself.

STATUS_BOUND = "bound"
STATUS_ANCHOR_UNBOUND = "anchor_unbound"
STATUS_ANCHOR_AMBIGUOUS = "anchor_ambiguous"
STATUS_NO_ANCHOR_CLAIMED = "no_anchor_claimed"

# DR-2 — consequence-identity equality, reported inside step 5 (never a 6th
# step). A bundle that claims an exact consequence authorization must show the
# dispatched / confirmed / reconciled identity equal to an AUTHORIZED one.
CONSEQUENCE_NONE_CLAIMED = "no_consequence_authorization_claimed"
CONSEQUENCE_BOUND = "consequence_bound"
CONSEQUENCE_NOT_DISPATCHED = "consequence_authorized_not_dispatched"
CONSEQUENCE_MISMATCH = "consequence_identity_mismatch"

# Payload keys that carry a dispatched/observed consequence identity.
_CONSEQUENCE_REF_KEYS = ("consequence_identity_hash", "identity_hash")
# Events that RECORD an authorization (the authority side of the equality).
_CONSEQUENCE_AUTH_TYPES = ("CONSEQUENCE_AUTHORIZED",)


def check_consequence_identity(events):
    """Return (status, authorized_set) for the consequence-identity equality.

    Historical bundles that claim no exact authorization return
    CONSEQUENCE_NONE_CLAIMED and are unaffected — this is what keeps every
    previously valid bundle valid.

    When an authorization IS present, every other event carrying a consequence
    identity must reference one of the AUTHORIZED identities. A dispatched or
    reconciled identity that matches nothing authorized is exactly the term
    substitution this check exists to catch, and it survives a full bundle
    rehash because it is an internal-consistency requirement, not a hash.
    """
    authorized = set()
    referenced = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        payload = e.get("payload")
        if not isinstance(payload, dict):
            continue
        etype = e.get("event_type", "")
        if etype in _CONSEQUENCE_AUTH_TYPES:
            h = payload.get("identity_hash")
            # only an AUTHORIZED decision confers authority
            if isinstance(h, str) and h and payload.get("decision") == "authorized":
                authorized.add(h)
            continue
        for k in _CONSEQUENCE_REF_KEYS:
            v = payload.get(k)
            if isinstance(v, str) and v:
                referenced.append(v)
                break
    if not authorized:
        return (CONSEQUENCE_NONE_CLAIMED, authorized)
    if not referenced:
        # Authorized but not yet dispatched — a legitimate intermediate state,
        # and the shape of every already-issued bundle that recorded an
        # authorization without a subsequent dispatch. Reported, never failed:
        # failing it would retroactively invalidate valid historical bundles.
        return (CONSEQUENCE_NOT_DISPATCHED, authorized)
    for v in referenced:
        if v not in authorized:
            return (CONSEQUENCE_MISMATCH, authorized)
    return (CONSEQUENCE_BOUND, authorized)

_LEAF_FIELDS = ("deal_id", "event_type", "event_id", "event_hash", "timestamp")


def canonical_leaf_data(event):
    """Rebuild the exact leaf preimage for one event, or None if malformed."""
    if not isinstance(event, dict):
        return None
    data = {}
    for field in _LEAF_FIELDS:
        value = event.get("hash") if field == "event_hash" else event.get(field)
        if not isinstance(value, str) or not value:
            return None          # malformed candidate → fail closed
        data[field] = value
    return data


def compute_leaf_hash(event):
    """Domain-separated leaf hash for one event, using the log's algorithm."""
    data = canonical_leaf_data(event)
    if data is None:
        return None
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return leaf_hash_hex(canonical.encode("utf-8"))


def find_bound_leaf_event(events, merkle_inclusion):
    """Bind the claimed leaf to exactly one event in this bundle.

    Returns (status, matched_event_or_None).
    """
    claimed = (merkle_inclusion or {}).get("leaf_hash")
    if not merkle_inclusion or not claimed:
        return STATUS_NO_ANCHOR_CLAIMED, None
    matches = []
    for ev in (events or []):
        lh = compute_leaf_hash(ev)
        if lh is not None and hmac.compare_digest(lh, claimed):
            matches.append(ev)
    if len(matches) == 1:
        return STATUS_BOUND, matches[0]
    if not matches:
        return STATUS_ANCHOR_UNBOUND, None
    return STATUS_ANCHOR_AMBIGUOUS, None


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
    #
    # PROOF-BINDING-1. Steps 3 and 4 prove that SOME leaf is included under a
    # platform-signed root. They do not prove the leaf describes an event in
    # THIS bundle — so an attacker could rewrite events, repair the chain and
    # bundle hash, keep the original proof/STH, and pass every step.
    #
    # Cross-reference is where that is caught, which is what its name has
    # always meant: it now requires the signed root to match AND the proven
    # leaf to correspond to exactly one eligible canonical event presented
    # here. `merkle_inclusion` keeps its purely mathematical meaning.
    cross_ok = False
    cross_skipped = not (merkle_inclusion and sth)
    leaf_binding = STATUS_NO_ANCHOR_CLAIMED
    if merkle_inclusion and sth:
        cross_ok = merkle_inclusion.get("merkle_root") == sth.get("root_hash")
        leaf_binding, _matched = find_bound_leaf_event(events, merkle_inclusion)
        cross_ok = cross_ok and leaf_binding == STATUS_BOUND

    # DR-2 — consequence-identity equality, reported in this same step so the
    # five-step contract is preserved exactly. A bundle claiming an exact
    # consequence authorization must show the dispatched/observed identity
    # equal to an authorized one; a bundle claiming none is unaffected, which
    # keeps every historical bundle valid.
    consequence_binding, _authorized = check_consequence_identity(events)
    if consequence_binding == CONSEQUENCE_MISMATCH:
        cross_ok = False

    result["steps"]["cross_reference"] = {
        "passed": cross_ok,
        "skipped": cross_skipped,
        # in-step diagnostic, same pattern as merkle_inclusion["type"]
        "leaf_binding": leaf_binding,
        "consequence_binding": consequence_binding,
    }

    # ── Spec-version dispatch ──────────────────
    # 2.0.0 → result.steps has the existing 5 keys ONLY (byte-identical to 1.3.0).
    # 3.0.0 → add the 6th `actor_signatures` step. For 2.0.0 bundles this
    # branch is never taken, so the result shape is preserved.
    is_tier2 = spec_version == "3.0.0"
    if is_tier2:
        result["steps"]["actor_signatures"] = verify_actor_signatures(bundle)

    # Overall verdict
    mandatory_pass = all(
        result["steps"][s]["passed"] for s in ["bundle_hash", "event_chain"]
    )
    optional_pass = all(
        result["steps"][s].get("passed") or result["steps"][s].get("skipped")
        for s in ["merkle_inclusion", "sth_signature", "cross_reference"]
    )
    # For 3.0.0 bundles, actor_signatures contributes to verdict in
    # the "optional but if-present-must-pass" position: PASS or
    # skipped (no signed events) is OK; FAIL fails the bundle.
    actor_sig_ok = True
    if is_tier2:
        as_step = result["steps"]["actor_signatures"]
        actor_sig_ok = bool(as_step.get("passed") or as_step.get("skipped"))

    result["verified"] = mandatory_pass and optional_pass and actor_sig_ok
    result["proof_count"] = len(proofs)
    result["event_count"] = len(events)

    skipped = [s for s in result["steps"] if result["steps"][s].get("skipped")]
    result["steps_run"] = len(result["steps"]) - len(skipped)
    result["steps_skipped"] = len(skipped)
    result["verification_level"] = "full" if not skipped else "offline"

    return result


# ── SWARM-B: optional strict swarm-verification profile ──────────────────
#
# Explicit, separately-named profile composed FROM the existing steps.
# `verify_bundle` (the default/legacy profile) is byte-unchanged: 2.0.0
# unsigned bundles keep verifying, and the CLI's --strict keeps its
# STH-only meaning. This profile answers a stronger question the default
# deliberately does not: "does every DESIGNATED swarm event carry a valid,
# temporally-consistent, enrolled-actor signature?" — distinguishing
# bundle INTEGRITY from complete swarm-authentication COVERAGE. It never
# re-runs policy and never claims real-world correctness.
#
# Authority model: the designated event set comes from the LATEST signed
# `swarm_policy` event inside bundle["events"] (covered by bundle_hash and
# its own Ed25519 signature). The runtime's `swarm_enforcement` snapshot
# section is a hash-committed evaluation record — cross-checked when
# present, but never the source of authority.

SWARM_POLICY_VERSION = "swarm_enforcement/v1"


def _normalize_key_directory(kd: Any) -> Dict[str, Any]:
    """Accept both directory shapes: Stage-4 flat {key_id: entry} and the
    82Q-D nested {"keys_by_key_id": {key_id: entry}}."""
    if not isinstance(kd, dict):
        return {}
    nested = kd.get("keys_by_key_id")
    if isinstance(nested, dict):
        return nested
    return kd


def _strict_lifecycle_ok(key_entry: Dict[str, Any]) -> "tuple[bool, str]":
    """§7 malformed-lifecycle rule (strict profile only): a key whose
    status says it is unusable but which carries no revoked_at timestamp
    offers no temporal evidence to bound its validity — fail closed."""
    status = key_entry.get("status", "active") or "active"
    if status != "active" and key_entry.get("revoked_at") is None:
        return False, f"lifecycle malformed: status={status!r} with no revoked_at"
    return True, ""


def _find_swarm_designation(events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in reversed(events or []):
        payload = e.get("payload") or {}
        if isinstance(payload.get("swarm_policy"), dict):
            return e
    return None


def verify_bundle_swarm_strict(
    bundle: Dict[str, Any],
    public_key_base64: str = "",
    sth: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Strict swarm profile: the full default verification PLUS complete
    actor-signature coverage of the designated swarm event set under the
    historical-time key rules.

    Adds two steps to the default result:
      swarm_coverage — designation present+signed, every designated event
                       type present, every instance PASS with strict
                       lifecycle temporal evidence;
      swarm_snapshot — the runtime's hash-committed enforcement snapshot
                       (recomputed hash + designation cross-check) when
                       present; its absence is reported, not fatal.
    `verified` is True only when the default profile AND coverage pass.
    """
    result = verify_bundle(bundle, public_key_base64=public_key_base64, sth=sth)
    result["profile"] = "swarm-strict"
    events = bundle.get("events", []) or []
    kd = _normalize_key_directory(bundle.get("key_directory"))

    coverage: Dict[str, Any] = {
        "passed": False, "skipped": False,
        "designation_event_id": None,
        "required_signed_event_types": [],
        "per_type": {}, "errors": [],
    }

    def _strict_verify_event(ev: Dict[str, Any]) -> "tuple[bool, str]":
        r = _verify_one_actor_signature(ev, kd)
        if r["result"] != "PASS":
            return False, r["reason"] or r["result"]
        entry = kd.get(r["key_id"], {})
        ok, why = _strict_lifecycle_ok(entry)
        if not ok:
            return False, why
        return True, ""

    designation = _find_swarm_designation(events)
    if designation is None:
        coverage["errors"].append("no swarm designation event in bundle events")
    else:
        coverage["designation_event_id"] = designation.get("event_id")
        policy = (designation.get("payload") or {}).get("swarm_policy") or {}
        ok, why = _strict_verify_event(designation)
        if not ok:
            coverage["errors"].append(f"designation event signature: {why}")
        if policy.get("policy_version") != SWARM_POLICY_VERSION:
            coverage["errors"].append(
                f"unsupported policy_version: {policy.get('policy_version')!r}")
        required = policy.get("required_signed_event_types")
        if not isinstance(required, list):
            coverage["errors"].append(
                "designation malformed: required_signed_event_types missing")
            required = []
        coverage["required_signed_event_types"] = list(required)
        for etype in required:
            instances = [e for e in events if e.get("event_type") == etype]
            if not instances:
                coverage["per_type"][etype] = {"present": 0, "passed": 0}
                coverage["errors"].append(f"required event type absent: {etype}")
                continue
            n_pass = 0
            for ev in instances:
                ok, why = _strict_verify_event(ev)
                if ok:
                    n_pass += 1
                else:
                    coverage["errors"].append(
                        f"coverage incomplete for {etype} "
                        f"({ev.get('event_id', '?')}): {why}")
            coverage["per_type"][etype] = {
                "present": len(instances), "passed": n_pass}
    coverage["passed"] = designation is not None and not coverage["errors"]
    result["steps"]["swarm_coverage"] = coverage

    snapshot_step: Dict[str, Any] = {"passed": False, "skipped": False,
                                     "present": False, "errors": []}
    sec = bundle.get("swarm_enforcement")
    if isinstance(sec, dict) and isinstance(sec.get("snapshot"), dict):
        snapshot_step["present"] = True
        snap = sec["snapshot"]
        claimed = sec.get("snapshot_hash", "")
        computed = hashlib.sha256(json.dumps(
            snap, sort_keys=True, separators=(",", ":"), default=str,
        ).encode()).hexdigest()
        if claimed != computed:
            snapshot_step["errors"].append("snapshot_hash mismatch")
        snap_required = ((snap.get("summary") or {})
                         .get("required_signed_event_types"))
        if (designation is not None and isinstance(snap_required, list)
                and sorted(snap_required)
                != sorted(coverage["required_signed_event_types"])):
            snapshot_step["errors"].append(
                "snapshot designation differs from signed designation")
        snapshot_step["passed"] = not snapshot_step["errors"]
    else:
        snapshot_step["skipped"] = True
    result["steps"]["swarm_snapshot"] = snapshot_step

    snapshot_ok = bool(snapshot_step["passed"] or snapshot_step["skipped"])
    result["verified"] = bool(
        result["verified"] and coverage["passed"] and snapshot_ok)
    skipped = [s for s in result["steps"] if result["steps"][s].get("skipped")]
    result["steps_run"] = len(result["steps"]) - len(skipped)
    result["steps_skipped"] = len(skipped)
    return result
