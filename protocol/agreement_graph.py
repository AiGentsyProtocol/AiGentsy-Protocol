"""Agreement / Contract Graph v1.

Eleventh institutional primitive in AiGentsy Stack. Models explicit
accepted agreements between counterparties: who agreed with whom, on
what terms, under what scope/SLA/value/rights, and what downstream
primitives are authorized because of that agreement.

AUDIT RESULT — WHAT WAS REUSED:
    dealgraph.py                  — deal lifecycle (PROPOSED → COMPLETED)
      with escrow, bonds, IP splits, and JV revenue distribution.
    contracts/sow_generator.py    — SOW milestones + acceptance criteria.
    contracts/legal_terms.py      — structured legal disclosures.
    protocol/executable_sla.py    — programmable SLA commitments.
    protocol/graph_settlement.py  — staged escrow release.
    protocol/acceptance_policy.py — auto-accept rules.
    protocol/dispute_arbitration.py — structured dispute resolution.

    This module wraps these into a portable, signed, inspectable
    agreement artifact. It does NOT replace them.

Stack primitives (eleven).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


SPEC_VERSION = "agreement_graph/v1"

_EXCLUDE_FROM_HASH = frozenset({"agreement_graph_hash", "signature"})

VALID_AGREEMENT_TYPES = frozenset({
    "service_agreement", "delegation_agreement", "resource_access_agreement",
    "sla_agreement", "matched_offer_agreement", "framework_agreement",
})

VALID_AGREEMENT_STATUSES = frozenset({
    "draft", "offered", "accepted", "active",
    "amended", "expired", "revoked", "fulfilled",
})


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


@dataclass
class AgreementNode:
    """One explicit accepted agreement between counterparties."""
    agreement_id: str = ""
    agreement_type: str = "service_agreement"
    status: str = "draft"
    resolved_intent_refs: List[str] = field(default_factory=list)
    counterparty_refs: List[str] = field(default_factory=list)
    scope: Dict[str, Any] = field(default_factory=dict)
    work_classes: List[str] = field(default_factory=list)
    sla_terms: Dict[str, Any] = field(default_factory=dict)
    proof_requirements: List[str] = field(default_factory=list)
    acceptance_requirements: List[str] = field(default_factory=list)
    value_term_refs: List[str] = field(default_factory=list)
    rights_granted: List[str] = field(default_factory=list)
    constraints_accepted: List[str] = field(default_factory=list)
    revocation_conditions: List[str] = field(default_factory=list)
    amendment_refs: List[str] = field(default_factory=list)
    expires_at: str = ""
    source_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgreementGraph:
    """Signed, portable agreement artifact.

    Embeds inside ProofPack at evidence.agreement_graph.
    """
    spec_version: str = SPEC_VERSION
    agreement_graph_id: str = ""
    created_at: str = ""
    issuer: str = ""
    counterparties: List[str] = field(default_factory=list)
    policy_version: str = ""
    agreement_nodes: List[AgreementNode] = field(default_factory=list)

    algorithm: str = "ed25519"
    public_key: str = ""
    agreement_graph_hash: str = ""
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _content_bytes(self) -> bytes:
        d = self.to_dict()
        for k in _EXCLUDE_FROM_HASH:
            d.pop(k, None)
        return _canonical_json_bytes(d)

    def compute_agreement_graph_hash(self) -> str:
        return hashlib.sha256(self._content_bytes()).hexdigest()

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
        self.agreement_graph_hash = self.compute_agreement_graph_hash()
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.signature = pk.sign(
                self.agreement_graph_hash.encode("utf-8")).hex()
        else:
            key = signing_key or _load_hmac_key()
            self.signature = hmac.new(
                key, self.agreement_graph_hash.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

    def verify_signature(self, *, ed25519_public_key: Any = None,
                          signing_key: Optional[bytes] = None) -> bool:
        expected = self.compute_agreement_graph_hash()
        if not hmac.compare_digest(expected,
                                     self.agreement_graph_hash or ""):
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
                          self.agreement_graph_hash.encode("utf-8"))
                return True
            except Exception:
                return False
        else:
            key = signing_key or _load_hmac_key()
            expected_sig = hmac.new(
                key, self.agreement_graph_hash.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_sig, self.signature or "")

    @classmethod
    def create(
        cls,
        issuer: str,
        counterparties: List[str],
        agreement_nodes: List[AgreementNode],
        *,
        policy_version: str = "",
    ) -> "AgreementGraph":
        return cls(
            agreement_graph_id=f"ag_{uuid4().hex[:16]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            issuer=issuer,
            counterparties=list(counterparties),
            policy_version=policy_version,
            agreement_nodes=list(agreement_nodes),
        )

    def active_agreements(self) -> List[AgreementNode]:
        return [n for n in self.agreement_nodes
                if n.status in ("accepted", "active")]

    def expired_or_revoked(self) -> List[AgreementNode]:
        return [n for n in self.agreement_nodes
                if n.status in ("expired", "revoked")]


# ── Agreement validity evaluation ───────────────────────────────────

@dataclass
class AgreementEvaluation:
    valid: bool
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_agreement(
    graph: AgreementGraph,
    agreement_id: str,
    *,
    acting_counterparty: str = "",
    available_mandates: Optional[Set[str]] = None,
    available_trust_scores: Optional[Dict[str, float]] = None,
    available_capabilities: Optional[Set[str]] = None,
    resolved_intents: Optional[Set[str]] = None,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> AgreementEvaluation:
    """Deterministic evaluation of whether an agreement is valid."""
    passed: List[str] = []
    failed: List[str] = []
    available_mandates = available_mandates or set()
    available_trust_scores = available_trust_scores or {}
    available_capabilities = available_capabilities or set()
    resolved_intents = resolved_intents or set()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Signature
    if graph.verify_signature(ed25519_public_key=ed25519_public_key,
                                signing_key=signing_key):
        passed.append("graph_signature_valid")
    else:
        failed.append("graph_signature_invalid")

    # 2. Node exists
    nmap = {n.agreement_id: n for n in graph.agreement_nodes}
    node = nmap.get(agreement_id)
    if not node:
        failed.append(f"agreement_not_found:{agreement_id}")
        return AgreementEvaluation(
            valid=False, checks_passed=passed,
            checks_failed=failed, reason="; ".join(failed))
    passed.append(f"agreement_exists:{agreement_id}")

    # 3. Status
    if node.status in ("revoked", "expired"):
        failed.append(f"agreement_{node.status}")
    elif node.status == "draft":
        failed.append("agreement_still_draft")
    else:
        passed.append(f"status_ok:{node.status}")

    # 4. Expiry
    if node.expires_at and node.expires_at < now:
        failed.append("agreement_expired")
    else:
        passed.append("not_expired")

    # 5. Counterparty
    if acting_counterparty:
        if acting_counterparty in node.counterparty_refs or acting_counterparty in graph.counterparties:
            passed.append("counterparty_valid")
        else:
            failed.append(f"counterparty_not_in_agreement:{acting_counterparty}")

    # 6. Resolved intents
    for ref in node.resolved_intent_refs:
        if ref in resolved_intents:
            passed.append(f"intent_resolved:{ref}")
        else:
            failed.append(f"intent_not_resolved:{ref}")

    # 7. Mandate scope
    if node.rights_granted:
        for right in node.rights_granted:
            if right in available_mandates:
                passed.append(f"mandate_covers:{right}")
            else:
                failed.append(f"mandate_missing:{right}")

    valid = len(failed) == 0
    return AgreementEvaluation(
        valid=valid, checks_passed=passed,
        checks_failed=failed,
        reason="agreement valid" if valid else "; ".join(failed),
    )


# ── Verification ────────────────────────────────────────────────────

def verify_embedded_agreement_graph(
    graph_dict: Dict[str, Any],
    *,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    nodes_raw = graph_dict.get("agreement_nodes", [])
    nodes = [AgreementNode(**{k: v for k, v in n.items()
                                if k in AgreementNode.__dataclass_fields__})
             for n in nodes_raw]
    g = AgreementGraph(**{
        k: (nodes if k == "agreement_nodes" else v)
        for k, v in graph_dict.items()
        if k in AgreementGraph.__dataclass_fields__
    })
    errors: List[str] = []
    sig_ok = g.verify_signature(
        ed25519_public_key=ed25519_public_key,
        signing_key=signing_key,
    )
    if not sig_ok:
        errors.append("agreement graph signature or hash mismatch")
    return {
        "signature_valid": sig_ok,
        "spec_version": g.spec_version,
        "algorithm": g.algorithm,
        "agreement_count": len(g.agreement_nodes),
        "active": len(g.active_agreements()),
        "counterparties": list(g.counterparties),
        "errors": errors,
    }
