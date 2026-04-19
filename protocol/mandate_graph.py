"""Mandate Graph v1.

The authority layer for AiGentsy Stack. A signed, portable primitive
that proves which agent was allowed to do which work, under what scope,
under what constraints, and with what downstream rights.

Three institutional primitives now coexist:
    HoverStack    — compute governance (how computation was governed)
    Mandate Graph — authority (who was allowed to act, within what limits)
    ProofPack/GEP — work proof / acceptance / downstream gating

v1 claim:
    "This agent was authorized to perform this work, under these
    constraints, by this issuer, and the mandate was valid at the time
    of proof creation."

v1 explicit non-claims:
    - Does NOT prove the work was completed correctly (that's ProofPack).
    - Does NOT prove the compute path was optimal (that's GEP).
    - Does NOT require network for verification (offline-verifiable).
    - Does NOT implement distributed revocation infrastructure.

Signing: ed25519 (primary) or HMAC-SHA256 (fallback). Same key
handling as GEP v1.1 — no new crypto dependencies.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


SPEC_VERSION = "mandate_graph/v1"

_EXCLUDE_FROM_HASH = frozenset({
    "mandate_hash", "signature",
})


# ── Signing primitives (shared with governed_proof) ──────────────────

def _load_ed25519_private():
    from hoverstack.governed_proof import _load_ed25519_private_key
    return _load_ed25519_private_key()

def _ed25519_pub_hex(pk=None):
    from hoverstack.governed_proof import _ed25519_public_key_hex
    return _ed25519_public_key_hex(pk)

def _load_hmac_key():
    from hoverstack.governed_proof import _load_hmac_key as _lhk
    return _lhk()

def _ed25519_ok():
    from hoverstack.governed_proof import _ed25519_available
    return _ed25519_available()


def _canonical_json_bytes(d: Dict[str, Any]) -> bytes:
    def _round(obj):
        if isinstance(obj, float):
            return round(obj, 6)
        if isinstance(obj, dict):
            return {k: _round(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_round(v) for v in obj]
        return obj
    return json.dumps(
        _round(d), sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    ).encode("utf-8")


# ── Schema ───────────────────────────────────────────────────────────

@dataclass
class Mandate:
    """Signed authority for autonomous work.

    Portable. Offline-verifiable. Embeddable inside ProofPack at
    evidence.mandate.
    """
    spec_version: str = SPEC_VERSION
    mandate_id: str = ""
    # Authority chain
    issuer: str = ""                           # who grants the authority
    subject_agent: str = ""                    # who receives the authority
    parent_mandate_id: Optional[str] = None    # delegation chain
    delegation_depth: int = 0                  # 0 = root; increments per hop
    # Temporal bounds
    issued_at: str = ""
    expires_at: str = ""                       # ISO-8601; empty = no expiry
    revoked_at: str = ""                       # ISO-8601; empty = not revoked
    # Scope
    scope: Dict[str, Any] = field(default_factory=dict)
    allowed_actions: List[str] = field(default_factory=list)
    forbidden_actions: List[str] = field(default_factory=list)
    work_class: List[str] = field(default_factory=list)
    # Delegation
    delegation_allowed: bool = False
    max_delegation_depth: int = 0              # 0 = no further delegation
    # Downstream consequence rights
    consequence_rights: List[str] = field(default_factory=list)
    # Proof / acceptance requirements imposed by mandate
    proof_requirements: List[str] = field(default_factory=list)
    acceptance_requirements: List[str] = field(default_factory=list)
    # Policy
    policy_version: str = ""
    # Signing
    algorithm: str = "ed25519"
    public_key: str = ""
    mandate_hash: str = ""
    signature: str = ""

    # ── Serialization ────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _content_bytes(self) -> bytes:
        d = self.to_dict()
        for k in _EXCLUDE_FROM_HASH:
            d.pop(k, None)
        return _canonical_json_bytes(d)

    def compute_mandate_hash(self) -> str:
        return hashlib.sha256(self._content_bytes()).hexdigest()

    # ── Sign / verify ────────────────────────────────────────────────

    def sign(self, *, algorithm: Optional[str] = None,
             ed25519_private_key: Any = None,
             signing_key: Optional[bytes] = None) -> None:
        alg = algorithm or self.algorithm or "ed25519"
        self.algorithm = alg
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.public_key = _ed25519_pub_hex(pk)
        else:
            self.public_key = ""
        self.mandate_hash = self.compute_mandate_hash()
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.signature = pk.sign(
                self.mandate_hash.encode("utf-8")).hex()
        else:
            key = signing_key or _load_hmac_key()
            self.signature = hmac.new(
                key, self.mandate_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()

    def verify_signature(self, *, ed25519_public_key: Any = None,
                          signing_key: Optional[bytes] = None) -> bool:
        expected = self.compute_mandate_hash()
        if not hmac.compare_digest(expected, self.mandate_hash or ""):
            return False
        if self.algorithm == "ed25519":
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                pk = ed25519_public_key
                if pk is None and self.public_key:
                    pk = Ed25519PublicKey.from_public_bytes(
                        bytes.fromhex(self.public_key))
                if pk is None:
                    from hoverstack.governed_proof import _load_ed25519_public_key
                    pk = _load_ed25519_public_key()
                pk.verify(bytes.fromhex(self.signature),
                          self.mandate_hash.encode("utf-8"))
                return True
            except Exception:
                return False
        else:
            key = signing_key or _load_hmac_key()
            expected_sig = hmac.new(
                key, self.mandate_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_sig, self.signature or "")

    # ── Construction helpers ─────────────────────────────────────────

    @classmethod
    def create(
        cls,
        issuer: str,
        subject_agent: str,
        *,
        allowed_actions: Optional[List[str]] = None,
        forbidden_actions: Optional[List[str]] = None,
        work_class: Optional[List[str]] = None,
        scope: Optional[Dict[str, Any]] = None,
        consequence_rights: Optional[List[str]] = None,
        proof_requirements: Optional[List[str]] = None,
        acceptance_requirements: Optional[List[str]] = None,
        delegation_allowed: bool = False,
        max_delegation_depth: int = 0,
        expires_at: str = "",
        policy_version: str = "",
        parent_mandate_id: Optional[str] = None,
        delegation_depth: int = 0,
    ) -> "Mandate":
        return cls(
            mandate_id=f"mnd_{uuid4().hex[:16]}",
            issuer=issuer,
            subject_agent=subject_agent,
            issued_at=datetime.now(timezone.utc).isoformat(),
            expires_at=expires_at,
            scope=scope or {},
            allowed_actions=list(allowed_actions or []),
            forbidden_actions=list(forbidden_actions or []),
            work_class=list(work_class or []),
            consequence_rights=list(consequence_rights or []),
            proof_requirements=list(proof_requirements or []),
            acceptance_requirements=list(acceptance_requirements or []),
            delegation_allowed=delegation_allowed,
            max_delegation_depth=max_delegation_depth,
            policy_version=policy_version,
            parent_mandate_id=parent_mandate_id,
            delegation_depth=delegation_depth,
        )

    def delegate(
        self,
        new_subject: str,
        *,
        narrowed_actions: Optional[List[str]] = None,
        narrowed_work_class: Optional[List[str]] = None,
        expires_at: str = "",
    ) -> "Mandate":
        """Create a child mandate delegating a subset of this mandate's
        authority. The child inherits constraints and can only narrow,
        never widen."""
        if not self.delegation_allowed:
            raise ValueError("delegation not allowed on this mandate")
        if self.delegation_depth >= self.max_delegation_depth:
            raise ValueError(
                f"delegation depth {self.delegation_depth} already at max "
                f"{self.max_delegation_depth}"
            )
        child_actions = narrowed_actions or list(self.allowed_actions)
        for a in child_actions:
            if a not in self.allowed_actions:
                raise ValueError(
                    f"cannot delegate action '{a}' not in parent's "
                    f"allowed_actions {self.allowed_actions}"
                )
        child_work_class = narrowed_work_class or list(self.work_class)
        for wc in child_work_class:
            if wc not in self.work_class:
                raise ValueError(
                    f"cannot delegate work_class '{wc}' not in parent's "
                    f"work_class {self.work_class}"
                )
        child_expires = expires_at or self.expires_at
        return Mandate.create(
            issuer=self.subject_agent,
            subject_agent=new_subject,
            allowed_actions=child_actions,
            forbidden_actions=list(self.forbidden_actions),
            work_class=child_work_class,
            scope=dict(self.scope),
            consequence_rights=list(self.consequence_rights),
            proof_requirements=list(self.proof_requirements),
            acceptance_requirements=list(self.acceptance_requirements),
            delegation_allowed=(self.delegation_depth + 1 < self.max_delegation_depth),
            max_delegation_depth=self.max_delegation_depth,
            parent_mandate_id=self.mandate_id,
            delegation_depth=self.delegation_depth + 1,
            expires_at=child_expires,
            policy_version=self.policy_version,
        )


# ── Mandate Validity Evaluation ──────────────────────────────────────

@dataclass
class MandateEvaluation:
    """Deterministic result of checking a mandate against a request."""
    valid: bool
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_mandate(
    mandate: Mandate,
    *,
    requested_action: str = "",
    requested_work_class: str = "",
    requested_consequence: str = "",
    subject_agent: str = "",
    now_iso: Optional[str] = None,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> MandateEvaluation:
    """Deterministic, auditable mandate validity check.

    Returns MandateEvaluation with explicit passed/failed checks.
    """
    passed: List[str] = []
    failed: List[str] = []
    now = now_iso or datetime.now(timezone.utc).isoformat()

    # 1. Signature
    if mandate.verify_signature(ed25519_public_key=ed25519_public_key,
                                  signing_key=signing_key):
        passed.append("signature_valid")
    else:
        failed.append("signature_invalid")

    # 2. Expiry
    if mandate.expires_at and mandate.expires_at < now:
        failed.append("expired")
    else:
        passed.append("not_expired")

    # 3. Revocation
    if mandate.revoked_at:
        failed.append("revoked")
    else:
        passed.append("not_revoked")

    # 4. Subject match
    if subject_agent:
        if mandate.subject_agent == subject_agent:
            passed.append("subject_matches")
        else:
            failed.append(f"subject_mismatch:{mandate.subject_agent}!={subject_agent}")
    else:
        passed.append("subject_not_checked")

    # 5. Action within scope
    if requested_action:
        if requested_action in mandate.forbidden_actions:
            failed.append(f"action_forbidden:{requested_action}")
        elif mandate.allowed_actions and requested_action not in mandate.allowed_actions:
            failed.append(f"action_not_allowed:{requested_action}")
        else:
            passed.append(f"action_allowed:{requested_action}")
    else:
        passed.append("action_not_checked")

    # 6. Work class
    if requested_work_class:
        if mandate.work_class and requested_work_class not in mandate.work_class:
            failed.append(f"work_class_not_permitted:{requested_work_class}")
        else:
            passed.append(f"work_class_ok:{requested_work_class}")
    else:
        passed.append("work_class_not_checked")

    # 7. Consequence rights
    if requested_consequence:
        if mandate.consequence_rights and requested_consequence not in mandate.consequence_rights:
            failed.append(f"consequence_not_authorized:{requested_consequence}")
        else:
            passed.append(f"consequence_authorized:{requested_consequence}")
    else:
        passed.append("consequence_not_checked")

    valid = len(failed) == 0
    reason = (
        "all checks passed" if valid
        else "; ".join(failed)
    )
    return MandateEvaluation(
        valid=valid, checks_passed=passed,
        checks_failed=failed, reason=reason,
    )


# ── Verification helper ─────────────────────────────────────────────

def verify_embedded_mandate(
    mandate_dict: Dict[str, Any],
    *,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    """Offline verification of a mandate dict read from a ProofPack."""
    errors: List[str] = []
    mandate = Mandate(**{
        k: v for k, v in mandate_dict.items()
        if k in Mandate.__dataclass_fields__
    })
    sig_ok = mandate.verify_signature(
        ed25519_public_key=ed25519_public_key,
        signing_key=signing_key,
    )
    if not sig_ok:
        errors.append("signature or mandate_hash does not match content")
    expired = bool(mandate.expires_at and
                    mandate.expires_at < datetime.now(timezone.utc).isoformat())
    revoked = bool(mandate.revoked_at)
    return {
        "signature_valid": sig_ok,
        "expired": expired,
        "revoked": revoked,
        "spec_version": mandate.spec_version,
        "algorithm": mandate.algorithm,
        "errors": errors,
    }
