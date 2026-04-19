"""Value Flow / Settlement Graph v1.

Fifth institutional primitive in AiGentsy Stack. Models how value is
apportioned across coordinated work: who is entitled to what, under
what conditions, after which proofs/acceptances, with what splits,
holds, and contingencies.

Stack primitives:
    HoverStack           — compute governance
    Mandate Graph        — authority
    Coordination Graph   — multi-agent obligations & dependency
    Value Flow Graph     — value allocation & release conditions
    ProofPack / GEP      — work proof / acceptance / downstream gating

v1 claim:
    "These value claims are structured, their conditions are recorded,
    and their eligibility/release states are inspectable and verifiable."

v1 non-claims:
    - Does NOT price work (pricing is upstream).
    - Does NOT custody funds (custody is the payment layer's job).
    - Does NOT implement a marketplace, exchange, or investment vehicle.
    - Does NOT require blockchain or network for verification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


SPEC_VERSION = "value_flow_graph/v1"

_EXCLUDE_FROM_HASH = frozenset({"value_graph_hash", "signature"})

VALID_CLAIM_STATUSES = frozenset({
    "pending", "held", "eligible", "released",
    "completed", "disputed", "reverted", "failed",
})


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


# ── Schema ───────────────────────────────────────────────────────────

@dataclass
class ValueClaim:
    """One economic entitlement in the value flow graph."""
    claim_id: str = ""
    claim_label: str = ""
    beneficiary: str = ""
    source_commitment_id: str = ""
    required_mandate_id: str = ""
    amount: float = 0.0
    share: float = 0.0                         # 0-1 fractional share
    asset_type: str = "USD"
    status: str = "pending"
    depends_on_claims: List[str] = field(default_factory=list)
    depends_on_commitments: List[str] = field(default_factory=list)
    requires_acceptance: bool = False
    requires_proof_types: List[str] = field(default_factory=list)
    release_conditions: List[str] = field(default_factory=list)
    hold_reason: str = ""
    dispute_state: str = ""
    reversion_target: str = ""
    unlocks_downstream_value: List[str] = field(default_factory=list)
    deadline: str = ""
    parent_claim_id: str = ""                  # for split children

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValueFlowGraph:
    """Signed, portable value-allocation artifact.

    Embeds inside ProofPack at evidence.value_flow_graph.
    """
    spec_version: str = SPEC_VERSION
    value_graph_id: str = ""
    created_at: str = ""
    issuer: str = ""
    policy_version: str = ""
    claims: List[ValueClaim] = field(default_factory=list)

    # Signing
    algorithm: str = "ed25519"
    public_key: str = ""
    value_graph_hash: str = ""
    signature: str = ""

    # ── Serialization ────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _content_bytes(self) -> bytes:
        d = self.to_dict()
        for k in _EXCLUDE_FROM_HASH:
            d.pop(k, None)
        return _canonical_json_bytes(d)

    def compute_value_graph_hash(self) -> str:
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
        self.value_graph_hash = self.compute_value_graph_hash()
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.signature = pk.sign(
                self.value_graph_hash.encode("utf-8")).hex()
        else:
            key = signing_key or _load_hmac_key()
            self.signature = hmac.new(
                key, self.value_graph_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()

    def verify_signature(self, *, ed25519_public_key: Any = None,
                          signing_key: Optional[bytes] = None) -> bool:
        expected = self.compute_value_graph_hash()
        if not hmac.compare_digest(expected, self.value_graph_hash or ""):
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
                          self.value_graph_hash.encode("utf-8"))
                return True
            except Exception:
                return False
        else:
            key = signing_key or _load_hmac_key()
            expected_sig = hmac.new(
                key, self.value_graph_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_sig, self.signature or "")

    # ── Construction ─────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        issuer: str,
        claims: List[ValueClaim],
        *,
        policy_version: str = "",
    ) -> "ValueFlowGraph":
        return cls(
            value_graph_id=f"vfg_{uuid4().hex[:16]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            issuer=issuer,
            policy_version=policy_version,
            claims=list(claims),
        )

    # ── Graph inspection ─────────────────────────────────────────────

    def _claim_map(self) -> Dict[str, ValueClaim]:
        return {c.claim_id: c for c in self.claims}

    def root_claims(self) -> List[ValueClaim]:
        return [c for c in self.claims
                if not c.depends_on_claims and not c.parent_claim_id]

    def split_children(self, parent_claim_id: str) -> List[ValueClaim]:
        return [c for c in self.claims
                if c.parent_claim_id == parent_claim_id]

    def total_amount(self) -> float:
        return sum(c.amount for c in self.claims if not c.parent_claim_id)

    def total_released(self) -> float:
        return sum(c.amount for c in self.claims if c.status == "released")

    def total_held(self) -> float:
        return sum(c.amount for c in self.claims if c.status == "held")


# ── Value Validity Evaluation ────────────────────────────────────────

@dataclass
class ValueEvaluation:
    valid: bool
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_release(
    graph: ValueFlowGraph,
    claim_id: str,
    *,
    beneficiary: str = "",
    satisfied_commitments: Optional[Set[str]] = None,
    accepted_commitments: Optional[Set[str]] = None,
    available_proofs: Optional[Set[str]] = None,
    released_claims: Optional[Set[str]] = None,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> ValueEvaluation:
    """Evaluate whether a value claim is eligible for release.

    Deterministic and auditable.
    """
    passed: List[str] = []
    failed: List[str] = []
    satisfied_commitments = satisfied_commitments or set()
    accepted_commitments = accepted_commitments or set()
    available_proofs = available_proofs or set()
    released_claims = released_claims or set()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Signature
    if graph.verify_signature(ed25519_public_key=ed25519_public_key,
                                signing_key=signing_key):
        passed.append("graph_signature_valid")
    else:
        failed.append("graph_signature_invalid")

    # 2. Claim exists
    cmap = graph._claim_map()
    claim = cmap.get(claim_id)
    if not claim:
        failed.append(f"claim_not_found:{claim_id}")
        return ValueEvaluation(
            valid=False, checks_passed=passed,
            checks_failed=failed, reason="; ".join(failed))
    passed.append(f"claim_exists:{claim_id}")

    # 3. Beneficiary
    if beneficiary:
        if claim.beneficiary == beneficiary:
            passed.append("beneficiary_matches")
        else:
            failed.append(f"beneficiary_mismatch:{claim.beneficiary}!={beneficiary}")

    # 4. Status checks
    if claim.status == "disputed":
        failed.append("claim_disputed")
    elif claim.status == "reverted":
        failed.append("claim_reverted")
    elif claim.status == "failed":
        failed.append("claim_failed")
    elif claim.status in ("released", "completed"):
        passed.append(f"already_{claim.status}")
    else:
        passed.append(f"status_ok:{claim.status}")

    # 5. Deadline
    if claim.deadline and claim.deadline < now:
        failed.append("claim_expired")
    else:
        passed.append("not_expired")

    # 6. Hold
    if claim.status == "held" and claim.hold_reason:
        failed.append(f"held:{claim.hold_reason}")

    # 7. Claim dependencies
    for dep_id in claim.depends_on_claims:
        dep = cmap.get(dep_id)
        if dep and dep.status in ("released", "completed"):
            passed.append(f"claim_dep_satisfied:{dep_id}")
        elif dep_id in released_claims:
            passed.append(f"claim_dep_satisfied_external:{dep_id}")
        else:
            failed.append(f"claim_dep_not_released:{dep_id}")

    # 8. Commitment dependencies
    for cmt_id in claim.depends_on_commitments:
        if cmt_id in satisfied_commitments or cmt_id in accepted_commitments:
            passed.append(f"commitment_satisfied:{cmt_id}")
        else:
            failed.append(f"commitment_not_satisfied:{cmt_id}")

    # 9. Required proofs
    for pt in claim.requires_proof_types:
        if pt in available_proofs:
            passed.append(f"proof_available:{pt}")
        else:
            failed.append(f"proof_missing:{pt}")

    # 10. Required acceptance
    if claim.requires_acceptance:
        acceptance_sources = {claim_id, claim.source_commitment_id} | set(claim.depends_on_commitments)
        if acceptance_sources & accepted_commitments:
            passed.append("acceptance_met")
        else:
            failed.append("acceptance_not_met")

    valid = len(failed) == 0
    return ValueEvaluation(
        valid=valid, checks_passed=passed,
        checks_failed=failed,
        reason="all checks passed" if valid else "; ".join(failed),
    )


# ── Verification ────────────────────────────────────────────────────

def verify_embedded_value_flow_graph(
    graph_dict: Dict[str, Any],
    *,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    errors: List[str] = []
    claims_raw = graph_dict.get("claims", [])
    nodes = [ValueClaim(**{k: v for k, v in c.items()
                            if k in ValueClaim.__dataclass_fields__})
             for c in claims_raw]
    g = ValueFlowGraph(**{
        k: (nodes if k == "claims" else v)
        for k, v in graph_dict.items()
        if k in ValueFlowGraph.__dataclass_fields__
    })
    sig_ok = g.verify_signature(
        ed25519_public_key=ed25519_public_key,
        signing_key=signing_key,
    )
    if not sig_ok:
        errors.append("value graph signature or hash does not match content")
    return {
        "signature_valid": sig_ok,
        "spec_version": g.spec_version,
        "algorithm": g.algorithm,
        "claim_count": len(g.claims),
        "total_amount": g.total_amount(),
        "total_released": g.total_released(),
        "total_held": g.total_held(),
        "errors": errors,
    }
