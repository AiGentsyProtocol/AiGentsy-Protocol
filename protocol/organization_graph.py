"""Swarm / Organization Graph v1.

Twelfth institutional primitive in AiGentsy Stack. Models durable
multi-agent organizations: which agents belong, what roles they hold,
what membership rules apply, and how collective identity persists
across many transactions.

AUDIT RESULT — WHAT WAS REUSED:
    csuite_base.py / csuite_orchestrator.py — 4-agent C-suite structure
      (CEO/CFO/CMO/COO) with role-based operations per SKU.
    ai_family_brain.py — multi-model collective with specialization,
      cross-pollination, shared memory.
    metabridge.py — JV team assembly with role-based revenue splits
      (lead 40%, specialist 30%, support 20%, advisor 10%).
    protocol/recursive_spawn.py — hierarchical parent-child spawning
      with OCS inheritance and tier-capped permissions.
    partner_mesh.py / partner_mesh_oem.py — 4-tier partner membership
      with commission tiers and auto-JV triggers.

    This module wraps these into a portable, signed, inspectable
    organization artifact. It does NOT replace them.

Stack primitives (twelve).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


SPEC_VERSION = "organization_graph/v1"

_EXCLUDE_FROM_HASH = frozenset({"organization_graph_hash", "signature"})

VALID_ORG_TYPES = frozenset({
    "swarm", "team", "venture", "realm", "cluster", "cell",
})

VALID_MEMBER_STATUSES = frozenset({
    "active", "pending", "suspended", "exited",
})

VALID_ORG_STATUSES = frozenset({
    "forming", "active", "dormant", "dissolved",
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
class RoleNode:
    """One organizational role."""
    role_id: str = ""
    role_label: str = ""
    role_scope: List[str] = field(default_factory=list)
    authority_bounds: List[str] = field(default_factory=list)
    obligations: List[str] = field(default_factory=list)
    rights: List[str] = field(default_factory=list)
    assignment_rules: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemberNode:
    """One member of the organization."""
    member_id: str = ""
    agent_ref: str = ""
    membership_status: str = "active"
    joined_at: str = ""
    left_at: str = ""
    suspended_at: str = ""
    role_refs: List[str] = field(default_factory=list)
    mandate_refs: List[str] = field(default_factory=list)
    capability_refs: List[str] = field(default_factory=list)
    trust_refs: List[str] = field(default_factory=list)
    lineage_refs: List[str] = field(default_factory=list)
    source_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrganizationGraph:
    """Signed, portable organizational-structure artifact.

    Embeds inside ProofPack at evidence.organization_graph.
    """
    spec_version: str = SPEC_VERSION
    organization_graph_id: str = ""
    created_at: str = ""
    issuer: str = ""
    organization_id: str = ""
    organization_type: str = "team"
    organization_status: str = "active"
    policy_version: str = ""
    member_nodes: List[MemberNode] = field(default_factory=list)
    role_nodes: List[RoleNode] = field(default_factory=list)

    algorithm: str = "ed25519"
    public_key: str = ""
    organization_graph_hash: str = ""
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _content_bytes(self) -> bytes:
        d = self.to_dict()
        for k in _EXCLUDE_FROM_HASH:
            d.pop(k, None)
        return _canonical_json_bytes(d)

    def compute_organization_graph_hash(self) -> str:
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
        self.organization_graph_hash = self.compute_organization_graph_hash()
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.signature = pk.sign(
                self.organization_graph_hash.encode("utf-8")).hex()
        else:
            key = signing_key or _load_hmac_key()
            self.signature = hmac.new(
                key, self.organization_graph_hash.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

    def verify_signature(self, *, ed25519_public_key: Any = None,
                          signing_key: Optional[bytes] = None) -> bool:
        expected = self.compute_organization_graph_hash()
        if not hmac.compare_digest(expected,
                                     self.organization_graph_hash or ""):
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
                          self.organization_graph_hash.encode("utf-8"))
                return True
            except Exception:
                return False
        else:
            key = signing_key or _load_hmac_key()
            expected_sig = hmac.new(
                key, self.organization_graph_hash.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_sig, self.signature or "")

    @classmethod
    def create(
        cls,
        issuer: str,
        organization_id: str,
        organization_type: str,
        member_nodes: List[MemberNode],
        role_nodes: Optional[List[RoleNode]] = None,
        *,
        organization_status: str = "active",
        policy_version: str = "",
    ) -> "OrganizationGraph":
        return cls(
            organization_graph_id=f"org_{uuid4().hex[:16]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            issuer=issuer,
            organization_id=organization_id,
            organization_type=organization_type,
            organization_status=organization_status,
            policy_version=policy_version,
            member_nodes=list(member_nodes),
            role_nodes=list(role_nodes or []),
        )

    def active_members(self) -> List[MemberNode]:
        return [m for m in self.member_nodes
                if m.membership_status == "active"]

    def suspended_members(self) -> List[MemberNode]:
        return [m for m in self.member_nodes
                if m.membership_status == "suspended"]

    def members_with_role(self, role_id: str) -> List[MemberNode]:
        return [m for m in self.member_nodes
                if role_id in m.role_refs and m.membership_status == "active"]


# ── Membership / role evaluation ────────────────────────────────────

@dataclass
class MembershipEvaluation:
    valid: bool
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_membership(
    graph: OrganizationGraph,
    agent_ref: str,
    *,
    requested_role: str = "",
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> MembershipEvaluation:
    """Deterministic membership/role validity check."""
    passed: List[str] = []
    failed: List[str] = []

    # 1. Signature
    if graph.verify_signature(ed25519_public_key=ed25519_public_key,
                                signing_key=signing_key):
        passed.append("graph_signature_valid")
    else:
        failed.append("graph_signature_invalid")

    # 2. Organization status
    if graph.organization_status in ("dissolved",):
        failed.append("organization_dissolved")
    elif graph.organization_status == "dormant":
        failed.append("organization_dormant")
    else:
        passed.append(f"org_status_ok:{graph.organization_status}")

    # 3. Member exists + active
    member = next((m for m in graph.member_nodes
                    if m.agent_ref == agent_ref), None)
    if not member:
        failed.append(f"agent_not_member:{agent_ref}")
        return MembershipEvaluation(
            valid=False, checks_passed=passed,
            checks_failed=failed, reason="; ".join(failed))

    passed.append(f"member_found:{member.member_id}")

    if member.membership_status == "active":
        passed.append("membership_active")
    elif member.membership_status == "suspended":
        failed.append("membership_suspended")
    elif member.membership_status == "exited":
        failed.append("membership_exited")
    elif member.membership_status == "pending":
        failed.append("membership_pending")
    else:
        failed.append(f"membership_unknown_status:{member.membership_status}")

    # 4. Role check
    if requested_role:
        if requested_role in member.role_refs:
            passed.append(f"role_assigned:{requested_role}")
        else:
            failed.append(f"role_not_assigned:{requested_role}")

    valid = len(failed) == 0
    return MembershipEvaluation(
        valid=valid, checks_passed=passed,
        checks_failed=failed,
        reason="membership valid" if valid else "; ".join(failed),
    )


# ── Verification ────────────────────────────────────────────────────

def verify_embedded_organization_graph(
    graph_dict: Dict[str, Any],
    *,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    members_raw = graph_dict.get("member_nodes", [])
    members = [MemberNode(**{k: v for k, v in m.items()
                               if k in MemberNode.__dataclass_fields__})
               for m in members_raw]
    roles_raw = graph_dict.get("role_nodes", [])
    roles = [RoleNode(**{k: v for k, v in r.items()
                           if k in RoleNode.__dataclass_fields__})
             for r in roles_raw]
    g = OrganizationGraph(**{
        k: (members if k == "member_nodes"
            else roles if k == "role_nodes"
            else v)
        for k, v in graph_dict.items()
        if k in OrganizationGraph.__dataclass_fields__
    })
    errors: List[str] = []
    sig_ok = g.verify_signature(
        ed25519_public_key=ed25519_public_key,
        signing_key=signing_key,
    )
    if not sig_ok:
        errors.append("organization graph signature or hash mismatch")
    return {
        "signature_valid": sig_ok,
        "spec_version": g.spec_version,
        "algorithm": g.algorithm,
        "organization_id": g.organization_id,
        "organization_type": g.organization_type,
        "organization_status": g.organization_status,
        "member_count": len(g.member_nodes),
        "active_members": len(g.active_members()),
        "role_count": len(g.role_nodes),
        "errors": errors,
    }
