"""Offer / Intent Graph v1.

Eighth institutional primitive in AiGentsy Stack. Models pre-commitment
transaction intent: what an agent offers, what it seeks, what counterpart
constraints apply, and how matches are structurally validated before
commitments form.

AUDIT RESULT — WHAT WAS REUSED:
    intent_exchange.py              — publish/bid/award auction with
      auto-scoring (price 70% + speed 30%). Intent schema reused.
    protocol/sla_marketplace.py     — ServiceOffering registry with
      search by vertical, OCS, SLA, quality thresholds.
    dealgraph.py                    — deal state from PROPOSED→COMPLETED
      with revenue splits. State-machine pattern reused.
    routing/inventory_fit.py        — offer packs + capacity + skill
      matching. Compatibility scoring pattern reused.

    This module wraps these into a portable, signed, inspectable intent
    artifact. It does NOT replace them.

Stack primitives (eight):
    HoverStack, Mandate, Coordination, Value Flow, Trust Profile,
    Lineage, Offer/Intent, ProofPack/GEP.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


SPEC_VERSION = "offer_intent_graph/v1"

_EXCLUDE_FROM_HASH = frozenset({"intent_graph_hash", "signature"})

VALID_INTENT_TYPES = frozenset({
    "offer", "request", "open_need", "partner_seek",
    "delegation_seek", "resource_offer", "resource_request",
})

VALID_INTENT_STATUSES = frozenset({
    "open", "matched", "withdrawn", "expired", "fulfilled", "blocked",
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
class IntentNode:
    """One offer or request in the intent graph."""
    intent_id: str = ""
    intent_type: str = "offer"
    status: str = "open"
    work_class: List[str] = field(default_factory=list)
    offered_capabilities: List[str] = field(default_factory=list)
    requested_capabilities: List[str] = field(default_factory=list)
    required_counterparty_traits: Dict[str, Any] = field(default_factory=dict)
    required_mandate_scope: List[str] = field(default_factory=list)
    required_trust_thresholds: Dict[str, float] = field(default_factory=dict)
    value_expectation: Dict[str, Any] = field(default_factory=dict)
    coordination_preconditions: List[str] = field(default_factory=list)
    expires_at: str = ""
    withdrawn_at: str = ""
    matched_to: str = ""
    source_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OfferIntentGraph:
    """Signed, portable pre-commitment intent artifact.

    Embeds inside ProofPack at evidence.offer_intent_graph.
    """
    spec_version: str = SPEC_VERSION
    intent_graph_id: str = ""
    created_at: str = ""
    issuer: str = ""
    subject_agent: str = ""
    policy_version: str = ""
    intent_nodes: List[IntentNode] = field(default_factory=list)

    algorithm: str = "ed25519"
    public_key: str = ""
    intent_graph_hash: str = ""
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _content_bytes(self) -> bytes:
        d = self.to_dict()
        for k in _EXCLUDE_FROM_HASH:
            d.pop(k, None)
        return _canonical_json_bytes(d)

    def compute_intent_graph_hash(self) -> str:
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
        self.intent_graph_hash = self.compute_intent_graph_hash()
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.signature = pk.sign(
                self.intent_graph_hash.encode("utf-8")).hex()
        else:
            key = signing_key or _load_hmac_key()
            self.signature = hmac.new(
                key, self.intent_graph_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()

    def verify_signature(self, *, ed25519_public_key: Any = None,
                          signing_key: Optional[bytes] = None) -> bool:
        expected = self.compute_intent_graph_hash()
        if not hmac.compare_digest(expected, self.intent_graph_hash or ""):
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
                          self.intent_graph_hash.encode("utf-8"))
                return True
            except Exception:
                return False
        else:
            key = signing_key or _load_hmac_key()
            expected_sig = hmac.new(
                key, self.intent_graph_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_sig, self.signature or "")

    @classmethod
    def create(
        cls,
        issuer: str,
        subject_agent: str,
        intent_nodes: List[IntentNode],
        *,
        policy_version: str = "",
    ) -> "OfferIntentGraph":
        return cls(
            intent_graph_id=f"oig_{uuid4().hex[:16]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            issuer=issuer,
            subject_agent=subject_agent,
            policy_version=policy_version,
            intent_nodes=list(intent_nodes),
        )

    def offers(self) -> List[IntentNode]:
        return [n for n in self.intent_nodes
                if n.intent_type in ("offer", "resource_offer")]

    def requests(self) -> List[IntentNode]:
        return [n for n in self.intent_nodes
                if n.intent_type in ("request", "open_need", "resource_request",
                                      "partner_seek", "delegation_seek")]

    def open_nodes(self) -> List[IntentNode]:
        return [n for n in self.intent_nodes if n.status == "open"]


# ── Compatibility evaluation ────────────────────────────────────────

@dataclass
class CompatibilityResult:
    compatible: bool
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_compatibility(
    offer_node: IntentNode,
    request_node: IntentNode,
    *,
    offer_agent_trust: Optional[Dict[str, Any]] = None,
    request_agent_trust: Optional[Dict[str, Any]] = None,
) -> CompatibilityResult:
    """Deterministic structural compatibility check between an offer
    and a request node.

    Inspired by routing/inventory_fit.py capability matching and
    intent_exchange.py bid scoring.
    """
    passed: List[str] = []
    failed: List[str] = []
    offer_agent_trust = offer_agent_trust or {}
    request_agent_trust = request_agent_trust or {}

    # 1. Both must be open.
    if offer_node.status != "open":
        failed.append(f"offer_not_open:{offer_node.status}")
    else:
        passed.append("offer_open")
    if request_node.status != "open":
        failed.append(f"request_not_open:{request_node.status}")
    else:
        passed.append("request_open")

    # 2. Work class overlap.
    if offer_node.work_class and request_node.work_class:
        overlap = set(offer_node.work_class) & set(request_node.work_class)
        if overlap:
            passed.append(f"work_class_overlap:{','.join(sorted(overlap))}")
        else:
            failed.append("no_work_class_overlap")
    else:
        passed.append("work_class_unconstrained")

    # 3. Capability match: offer's capabilities satisfy request's needs.
    if request_node.requested_capabilities:
        offered = set(offer_node.offered_capabilities)
        needed = set(request_node.requested_capabilities)
        met = offered & needed
        unmet = needed - offered
        if unmet:
            failed.append(f"capabilities_unmet:{','.join(sorted(unmet))}")
        else:
            passed.append(f"capabilities_met:{','.join(sorted(met))}")
    else:
        passed.append("no_capabilities_required")

    # 4. Trust thresholds: request requires offer agent to meet thresholds.
    for key, threshold in request_node.required_trust_thresholds.items():
        actual = offer_agent_trust.get(key, 0.0)
        if actual >= threshold:
            passed.append(f"trust_met:{key}>={threshold}")
        else:
            failed.append(f"trust_below:{key}={actual}<{threshold}")

    # 5. Mandate scope compatibility.
    if request_node.required_mandate_scope:
        if offer_node.required_mandate_scope:
            scope_ok = set(request_node.required_mandate_scope).issubset(
                set(offer_node.required_mandate_scope))
            if scope_ok:
                passed.append("mandate_scope_compatible")
            else:
                failed.append("mandate_scope_incompatible")
        else:
            passed.append("mandate_scope_unconstrained_by_offer")

    # 6. Not expired.
    now = datetime.now(timezone.utc).isoformat()
    for label, node in [("offer", offer_node), ("request", request_node)]:
        if node.expires_at and node.expires_at < now:
            failed.append(f"{label}_expired")
        if node.withdrawn_at:
            failed.append(f"{label}_withdrawn")

    compatible = len(failed) == 0
    return CompatibilityResult(
        compatible=compatible, checks_passed=passed,
        checks_failed=failed,
        reason="structurally compatible" if compatible else "; ".join(failed),
    )


# ── Verification ────────────────────────────────────────────────────

def verify_embedded_offer_intent_graph(
    graph_dict: Dict[str, Any],
    *,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    nodes_raw = graph_dict.get("intent_nodes", [])
    nodes = [IntentNode(**{k: v for k, v in n.items()
                            if k in IntentNode.__dataclass_fields__})
             for n in nodes_raw]
    g = OfferIntentGraph(**{
        k: (nodes if k == "intent_nodes" else v)
        for k, v in graph_dict.items()
        if k in OfferIntentGraph.__dataclass_fields__
    })
    errors: List[str] = []
    sig_ok = g.verify_signature(
        ed25519_public_key=ed25519_public_key,
        signing_key=signing_key,
    )
    if not sig_ok:
        errors.append("intent graph signature or hash does not match content")
    return {
        "signature_valid": sig_ok,
        "spec_version": g.spec_version,
        "algorithm": g.algorithm,
        "intent_count": len(g.intent_nodes),
        "offers": len(g.offers()),
        "requests": len(g.requests()),
        "open": len(g.open_nodes()),
        "errors": errors,
    }
