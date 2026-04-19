"""Capability / Resource Graph v1.

Tenth institutional primitive in AiGentsy Stack. Models what
capabilities, tools, inventories, budgets, rails, and operational
capacity an agent or swarm has available under current constraints.

AUDIT RESULT — WHAT WAS REUSED:
    routing/inventory_fit.py         — OfferPack + has_capacity() +
      skill-based matching + capacity tracking.
    agent_registry.py                — Capability enums, verification
      gates, capability-indexed discovery.
    agent_spending.py                — Daily budget enforcement,
      check_spending_capacity(), autonomy-level caps.
    protocol/provider_capabilities.py — Rail/provider selection by
      capabilities, fees, regions.
    allocation/r3_allocator.py       — Runway-aware budget allocation.
    protocol/credential_marketplace.py — Proof-backed credential index.

    This module wraps these into a portable, signed, inspectable
    resource artifact. It does NOT replace them.

Stack primitives (ten).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


SPEC_VERSION = "capability_resource_graph/v1"

_EXCLUDE_FROM_HASH = frozenset({"resource_graph_hash", "signature"})

VALID_RESOURCE_TYPES = frozenset({
    "capability", "tool_access", "inventory", "budget",
    "rail_access", "license_unlock", "resource_pool", "runtime_capacity",
})

VALID_RESOURCE_STATUSES = frozenset({
    "available", "limited", "exhausted", "blocked", "expired", "revoked",
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
class ResourceNode:
    """One capability or resource in the graph."""
    resource_id: str = ""
    resource_type: str = "capability"
    status: str = "available"
    capability_label: str = ""
    availability_state: str = "ready"
    capacity_total: float = 0.0
    capacity_available: float = 0.0
    budget_available: float = 0.0
    inventory_quantity: int = 0
    required_authority_scope: List[str] = field(default_factory=list)
    required_trust_threshold: float = 0.0
    usable_for_work_classes: List[str] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)
    expires_at: str = ""
    source_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityResourceGraph:
    """Signed, portable capability/resource artifact.

    Embeds inside ProofPack at evidence.capability_resource_graph.
    """
    spec_version: str = SPEC_VERSION
    resource_graph_id: str = ""
    created_at: str = ""
    issuer: str = ""
    subject_agent: str = ""
    policy_version: str = ""
    resource_nodes: List[ResourceNode] = field(default_factory=list)

    algorithm: str = "ed25519"
    public_key: str = ""
    resource_graph_hash: str = ""
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _content_bytes(self) -> bytes:
        d = self.to_dict()
        for k in _EXCLUDE_FROM_HASH:
            d.pop(k, None)
        return _canonical_json_bytes(d)

    def compute_resource_graph_hash(self) -> str:
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
        self.resource_graph_hash = self.compute_resource_graph_hash()
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.signature = pk.sign(
                self.resource_graph_hash.encode("utf-8")).hex()
        else:
            key = signing_key or _load_hmac_key()
            self.signature = hmac.new(
                key, self.resource_graph_hash.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

    def verify_signature(self, *, ed25519_public_key: Any = None,
                          signing_key: Optional[bytes] = None) -> bool:
        expected = self.compute_resource_graph_hash()
        if not hmac.compare_digest(expected, self.resource_graph_hash or ""):
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
                          self.resource_graph_hash.encode("utf-8"))
                return True
            except Exception:
                return False
        else:
            key = signing_key or _load_hmac_key()
            expected_sig = hmac.new(
                key, self.resource_graph_hash.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_sig, self.signature or "")

    @classmethod
    def create(
        cls,
        issuer: str,
        subject_agent: str,
        resource_nodes: List[ResourceNode],
        *,
        policy_version: str = "",
    ) -> "CapabilityResourceGraph":
        return cls(
            resource_graph_id=f"crg_{uuid4().hex[:16]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            issuer=issuer,
            subject_agent=subject_agent,
            policy_version=policy_version,
            resource_nodes=list(resource_nodes),
        )

    def available_nodes(self) -> List[ResourceNode]:
        return [n for n in self.resource_nodes
                if n.status in ("available", "limited")]

    def exhausted_nodes(self) -> List[ResourceNode]:
        return [n for n in self.resource_nodes
                if n.status == "exhausted"]

    def blocked_nodes(self) -> List[ResourceNode]:
        return [n for n in self.resource_nodes
                if n.status in ("blocked", "expired", "revoked")]

    def capabilities_for_work_class(self, work_class: str) -> List[ResourceNode]:
        return [n for n in self.resource_nodes
                if work_class in n.usable_for_work_classes
                and n.status in ("available", "limited")]


# ── Availability evaluation ─────────────────────────────────────────

@dataclass
class AvailabilityEvaluation:
    usable: bool
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_availability(
    graph: CapabilityResourceGraph,
    resource_id: str,
    *,
    requested_work_class: str = "",
    requesting_agent_trust: float = 0.0,
    requesting_agent_scope: Optional[Set[str]] = None,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> AvailabilityEvaluation:
    """Deterministic evaluation of whether a resource is usable."""
    passed: List[str] = []
    failed: List[str] = []
    requesting_agent_scope = requesting_agent_scope or set()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Signature
    if graph.verify_signature(ed25519_public_key=ed25519_public_key,
                                signing_key=signing_key):
        passed.append("graph_signature_valid")
    else:
        failed.append("graph_signature_invalid")

    # 2. Node exists
    nmap = {n.resource_id: n for n in graph.resource_nodes}
    node = nmap.get(resource_id)
    if not node:
        failed.append(f"resource_not_found:{resource_id}")
        return AvailabilityEvaluation(
            usable=False, checks_passed=passed,
            checks_failed=failed, reason="; ".join(failed))
    passed.append(f"resource_exists:{resource_id}")

    # 3. Status
    if node.status in ("blocked", "expired", "revoked"):
        failed.append(f"resource_{node.status}")
    elif node.status == "exhausted":
        failed.append("resource_exhausted")
    else:
        passed.append(f"status_ok:{node.status}")

    # 4. Expiry
    if node.expires_at and node.expires_at < now:
        failed.append("resource_expired")
    else:
        passed.append("not_expired")

    # 5. Capacity
    if node.capacity_total > 0 and node.capacity_available <= 0:
        failed.append("capacity_exhausted")
    elif node.capacity_total > 0:
        passed.append(f"capacity_available:{node.capacity_available}/{node.capacity_total}")

    # 6. Budget
    if node.resource_type == "budget" and node.budget_available <= 0:
        failed.append("budget_exhausted")
    elif node.resource_type == "budget":
        passed.append(f"budget_available:{node.budget_available}")

    # 7. Work class
    if requested_work_class:
        if node.usable_for_work_classes and requested_work_class not in node.usable_for_work_classes:
            failed.append(f"work_class_not_supported:{requested_work_class}")
        else:
            passed.append(f"work_class_ok:{requested_work_class}")

    # 8. Trust threshold
    if node.required_trust_threshold > 0:
        if requesting_agent_trust >= node.required_trust_threshold:
            passed.append(f"trust_met:{requesting_agent_trust}>={node.required_trust_threshold}")
        else:
            failed.append(f"trust_below:{requesting_agent_trust}<{node.required_trust_threshold}")

    # 9. Authority scope
    if node.required_authority_scope:
        if set(node.required_authority_scope).issubset(requesting_agent_scope):
            passed.append("authority_scope_met")
        else:
            failed.append("authority_scope_insufficient")

    # 10. Blocked-by
    for blocker in node.blocked_by:
        blocker_node = nmap.get(blocker)
        if blocker_node and blocker_node.status in ("available", "limited"):
            passed.append(f"blocker_cleared:{blocker}")
        else:
            failed.append(f"blocked_by:{blocker}")

    usable = len(failed) == 0
    return AvailabilityEvaluation(
        usable=usable, checks_passed=passed,
        checks_failed=failed,
        reason="resource usable" if usable else "; ".join(failed),
    )


# ── Verification ────────────────────────────────────────────────────

def verify_embedded_capability_resource_graph(
    graph_dict: Dict[str, Any],
    *,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    nodes_raw = graph_dict.get("resource_nodes", [])
    nodes = [ResourceNode(**{k: v for k, v in n.items()
                               if k in ResourceNode.__dataclass_fields__})
             for n in nodes_raw]
    g = CapabilityResourceGraph(**{
        k: (nodes if k == "resource_nodes" else v)
        for k, v in graph_dict.items()
        if k in CapabilityResourceGraph.__dataclass_fields__
    })
    errors: List[str] = []
    sig_ok = g.verify_signature(
        ed25519_public_key=ed25519_public_key,
        signing_key=signing_key,
    )
    if not sig_ok:
        errors.append("capability resource graph signature or hash mismatch")
    return {
        "signature_valid": sig_ok,
        "spec_version": g.spec_version,
        "algorithm": g.algorithm,
        "resource_count": len(g.resource_nodes),
        "available": len(g.available_nodes()),
        "exhausted": len(g.exhausted_nodes()),
        "blocked": len(g.blocked_nodes()),
        "errors": errors,
    }
