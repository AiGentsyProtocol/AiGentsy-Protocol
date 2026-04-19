"""Trust / Reputation Profile v1.

Sixth institutional primitive in AiGentsy Stack. A signed, portable,
evidence-backed profile that summarizes an agent's accumulated trust
across governed compute, authority compliance, coordination, proof
completion, acceptance, and value release.

AUDIT RESULT — WHAT WAS REUSED:
    The existing AiGentsy codebase already contains:
      - OCS engine (brain_overlay/ocs.py): 0-100 score with 5-tier system.
      - W3C VC attestation (protocol/reputation_attestation.py): signed
        portable credential with ed25519.
      - Acceptance gate records (protocol/acceptance_gate.py): auditable
        accept/reject decisions.
      - Dispute arbitration (protocol/dispute_arbitration.py): outcome
        history.
      - Agent registry (protocol/agent_registry.py): OCS + tier + stats.

    This module WRAPS the existing OCS score into a richer, work-class-
    specific, evidence-referenced trust profile that carries negative
    signals alongside positives. It does NOT replace or duplicate OCS.

Stack primitives:
    HoverStack           — compute governance
    Mandate Graph        — authority
    Coordination Graph   — obligations & dependency
    Value Flow Graph     — value allocation & release conditions
    Trust Profile        — accumulated reliability & trust posture
    ProofPack / GEP      — work proof / acceptance / downstream gating

v1 claim:
    "This agent has demonstrated these trust signals from these evidence
    sources. The profile is signed and portable."

v1 non-claims:
    - Does NOT replace OCS as the canonical numeric score.
    - Does NOT implement social reputation or gamification.
    - Does NOT require blockchain or network for verification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


SPEC_VERSION = "trust_profile/v1"

_EXCLUDE_FROM_HASH = frozenset({"profile_hash", "signature"})


# ── Shared signing ──────────────────────────────────────────────────

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


def _load_ed25519_private():
    from hoverstack.governed_proof import _load_ed25519_private_key
    return _load_ed25519_private_key()

def _ed25519_pub_hex(pk=None):
    from hoverstack.governed_proof import _ed25519_public_key_hex
    return _ed25519_public_key_hex(pk)

def _load_hmac_key():
    from hoverstack.governed_proof import _load_hmac_key as _lhk
    return _lhk()


# ── Trust signal categories ─────────────────────────────────────────

SIGNAL_CATEGORIES = frozenset({
    "governed_compute_reliability",
    "authority_compliance",
    "coordination_reliability",
    "proof_completion_reliability",
    "acceptance_reliability",
    "dispute_frequency",
    "release_reliability",
    "delegation_reliability",
    "refusal_quality",
})


@dataclass
class TrustSignal:
    """One evidence-backed trust dimension."""
    category: str = ""                       # from SIGNAL_CATEGORIES
    score: float = 0.0                       # 0-1 normalized; >0.5 = positive
    sample_count: int = 0                    # how many observations
    source_refs: List[str] = field(default_factory=list)  # deal_ids / mandate_ids / etc.
    work_class: str = ""                     # if per-work-class; empty = global
    last_updated: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkClassStrength:
    """Per-work-class trust summary."""
    work_class: str = ""
    composite_score: float = 0.0             # 0-1
    total_completions: int = 0
    total_acceptances: int = 0
    total_disputes: int = 0
    reliability_rate: float = 0.0            # acceptances / completions

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Schema ───────────────────────────────────────────────────────────

@dataclass
class TrustProfile:
    """Signed, portable, evidence-backed trust artifact.

    Embeds inside ProofPack at evidence.trust_profile.
    """
    spec_version: str = SPEC_VERSION
    profile_id: str = ""
    created_at: str = ""
    subject_agent: str = ""
    issuer: str = ""
    policy_version: str = ""

    # From the existing OCS engine (reused, not replaced).
    ocs_score: float = 0.0                   # 0-100; from brain_overlay/ocs.py
    ocs_tier: str = ""                       # elite/trusted/standard/probation/restricted

    # Structured trust signals — richer than OCS alone.
    trust_signals: List[TrustSignal] = field(default_factory=list)
    work_class_strengths: List[WorkClassStrength] = field(default_factory=list)

    # Negative signals (explicit — not buried inside a blended score).
    dispute_count: int = 0
    failed_acceptance_count: int = 0
    release_failure_count: int = 0
    coordination_failure_count: int = 0
    delegation_violation_count: int = 0

    # Evidence linkage.
    total_proofs_completed: int = 0
    total_mandates_complied: int = 0
    total_coordination_nodes_completed: int = 0
    total_value_released: float = 0.0
    sample_source_refs: List[str] = field(default_factory=list)

    # Signing
    algorithm: str = "ed25519"
    public_key: str = ""
    profile_hash: str = ""
    signature: str = ""

    # ── Serialization ────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _content_bytes(self) -> bytes:
        d = self.to_dict()
        for k in _EXCLUDE_FROM_HASH:
            d.pop(k, None)
        return _canonical_json_bytes(d)

    def compute_profile_hash(self) -> str:
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
        self.profile_hash = self.compute_profile_hash()
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.signature = pk.sign(
                self.profile_hash.encode("utf-8")).hex()
        else:
            key = signing_key or _load_hmac_key()
            self.signature = hmac.new(
                key, self.profile_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()

    def verify_signature(self, *, ed25519_public_key: Any = None,
                          signing_key: Optional[bytes] = None) -> bool:
        expected = self.compute_profile_hash()
        if not hmac.compare_digest(expected, self.profile_hash or ""):
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
                          self.profile_hash.encode("utf-8"))
                return True
            except Exception:
                return False
        else:
            key = signing_key or _load_hmac_key()
            expected_sig = hmac.new(
                key, self.profile_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_sig, self.signature or "")

    # ── Construction ─────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        subject_agent: str,
        issuer: str,
        *,
        ocs_score: float = 0.0,
        ocs_tier: str = "",
        trust_signals: Optional[List[TrustSignal]] = None,
        work_class_strengths: Optional[List[WorkClassStrength]] = None,
        dispute_count: int = 0,
        failed_acceptance_count: int = 0,
        release_failure_count: int = 0,
        coordination_failure_count: int = 0,
        delegation_violation_count: int = 0,
        total_proofs_completed: int = 0,
        total_mandates_complied: int = 0,
        total_coordination_nodes_completed: int = 0,
        total_value_released: float = 0.0,
        sample_source_refs: Optional[List[str]] = None,
        policy_version: str = "",
    ) -> "TrustProfile":
        return cls(
            profile_id=f"tp_{uuid4().hex[:16]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            subject_agent=subject_agent,
            issuer=issuer,
            policy_version=policy_version,
            ocs_score=ocs_score,
            ocs_tier=ocs_tier,
            trust_signals=list(trust_signals or []),
            work_class_strengths=list(work_class_strengths or []),
            dispute_count=dispute_count,
            failed_acceptance_count=failed_acceptance_count,
            release_failure_count=release_failure_count,
            coordination_failure_count=coordination_failure_count,
            delegation_violation_count=delegation_violation_count,
            total_proofs_completed=total_proofs_completed,
            total_mandates_complied=total_mandates_complied,
            total_coordination_nodes_completed=total_coordination_nodes_completed,
            total_value_released=total_value_released,
            sample_source_refs=list(sample_source_refs or []),
        )

    # ── Evaluation ───────────────────────────────────────────────────

    def positive_signals(self) -> List[TrustSignal]:
        return [s for s in self.trust_signals if s.score > 0.5]

    def negative_signals(self) -> List[TrustSignal]:
        return [s for s in self.trust_signals if s.score <= 0.5 and s.sample_count > 0]

    def strongest_work_classes(self, k: int = 3) -> List[WorkClassStrength]:
        return sorted(self.work_class_strengths,
                       key=lambda w: w.composite_score, reverse=True)[:k]

    def weakest_work_classes(self, k: int = 3) -> List[WorkClassStrength]:
        return sorted(self.work_class_strengths,
                       key=lambda w: w.composite_score)[:k]

    def negative_signal_count(self) -> int:
        return (self.dispute_count + self.failed_acceptance_count
                + self.release_failure_count + self.coordination_failure_count
                + self.delegation_violation_count)

    def evidence_backed(self) -> bool:
        """True if the profile has real evidence, not just zeros."""
        return (self.total_proofs_completed > 0
                or self.total_mandates_complied > 0
                or any(s.sample_count > 0 for s in self.trust_signals))

    def summary(self) -> Dict[str, Any]:
        """Compact operator-facing summary."""
        return {
            "subject_agent": self.subject_agent,
            "ocs_score": self.ocs_score,
            "ocs_tier": self.ocs_tier,
            "positive_signals": len(self.positive_signals()),
            "negative_signals": len(self.negative_signals()),
            "negative_signal_count": self.negative_signal_count(),
            "total_proofs_completed": self.total_proofs_completed,
            "evidence_backed": self.evidence_backed(),
            "strongest_work_classes": [
                w.work_class for w in self.strongest_work_classes(3)],
        }


# ── Verification ────────────────────────────────────────────────────

def verify_embedded_trust_profile(
    profile_dict: Dict[str, Any],
    *,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    signals_raw = profile_dict.get("trust_signals", [])
    signals = [TrustSignal(**{k: v for k, v in s.items()
                               if k in TrustSignal.__dataclass_fields__})
               for s in signals_raw]
    wcs_raw = profile_dict.get("work_class_strengths", [])
    wcs = [WorkClassStrength(**{k: v for k, v in w.items()
                                  if k in WorkClassStrength.__dataclass_fields__})
           for w in wcs_raw]
    prof = TrustProfile(**{
        k: (signals if k == "trust_signals"
            else wcs if k == "work_class_strengths"
            else v)
        for k, v in profile_dict.items()
        if k in TrustProfile.__dataclass_fields__
    })
    errors: List[str] = []
    sig_ok = prof.verify_signature(
        ed25519_public_key=ed25519_public_key,
        signing_key=signing_key,
    )
    if not sig_ok:
        errors.append("profile signature or hash does not match content")
    return {
        "signature_valid": sig_ok,
        "spec_version": prof.spec_version,
        "algorithm": prof.algorithm,
        "ocs_score": prof.ocs_score,
        "ocs_tier": prof.ocs_tier,
        "evidence_backed": prof.evidence_backed(),
        "errors": errors,
    }
