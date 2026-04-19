"""Consequence / State-Change Graph v1.

Ninth institutional primitive in AiGentsy Stack. Models what downstream
state changes are authorized, what conditions unlock them, who may
trigger them, and how consequence movement is represented after proof
and acceptance.

AUDIT RESULT — WHAT WAS REUSED:
    protocol/acceptance_gate.py   — gated state changes behind
      accept/reject; downstream_action + downstream_triggered.
    protocol/event_store.py       — hash-chained event ledger with
      stage-based transitions (PROOF_READY → GO_APPROVED → SETTLED).
    protocol/event_bus.py         — pub/sub + webhook dispatch.
    protocol/graph_settlement.py  — per-stage escrow release via
      release_stage().
    routes/proof_verifier.py      — GO button (scope lock → payment →
      GO_APPROVED event).
    protocol/autonomous_commerce.py — zero-touch lifecycle consequence
      (SETTLED → auto-invoice).
    Mandate.consequence_rights + CommitmentNode.unlocks_consequences
      already model what consequences are authorized.

    This module wraps these into a portable, signed, inspectable
    consequence artifact. It does NOT replace them.

Stack primitives (nine).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


SPEC_VERSION = "consequence_graph/v1"

_EXCLUDE_FROM_HASH = frozenset({"consequence_graph_hash", "signature"})

VALID_CONSEQUENCE_TYPES = frozenset({
    "settlement_request", "release", "access_grant", "state_change",
    "downstream_task_start", "escalation", "hold", "reversion",
})

VALID_CONSEQUENCE_STATUSES = frozenset({
    "pending", "eligible", "triggered", "blocked",
    "held", "escalated", "reverted", "completed",
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
class ConsequenceNode:
    """One downstream state change in the consequence graph."""
    consequence_id: str = ""
    consequence_type: str = "state_change"
    status: str = "pending"
    triggering_conditions: List[str] = field(default_factory=list)
    required_proof_refs: List[str] = field(default_factory=list)
    required_acceptance_state: str = ""
    required_value_state: str = ""
    required_mandate_scope: List[str] = field(default_factory=list)
    required_coordination_state: str = ""
    allowed_triggering_agent: str = ""
    blocked_by: List[str] = field(default_factory=list)
    unlocks_next: List[str] = field(default_factory=list)
    reversion_target: str = ""
    escalation_target: str = ""
    source_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConsequenceGraph:
    """Signed, portable consequence artifact.

    Embeds inside ProofPack at evidence.consequence_graph.
    """
    spec_version: str = SPEC_VERSION
    consequence_graph_id: str = ""
    created_at: str = ""
    issuer: str = ""
    subject_agent: str = ""
    policy_version: str = ""
    consequence_nodes: List[ConsequenceNode] = field(default_factory=list)

    algorithm: str = "ed25519"
    public_key: str = ""
    consequence_graph_hash: str = ""
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _content_bytes(self) -> bytes:
        d = self.to_dict()
        for k in _EXCLUDE_FROM_HASH:
            d.pop(k, None)
        return _canonical_json_bytes(d)

    def compute_consequence_graph_hash(self) -> str:
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
        self.consequence_graph_hash = self.compute_consequence_graph_hash()
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.signature = pk.sign(
                self.consequence_graph_hash.encode("utf-8")).hex()
        else:
            key = signing_key or _load_hmac_key()
            self.signature = hmac.new(
                key, self.consequence_graph_hash.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

    def verify_signature(self, *, ed25519_public_key: Any = None,
                          signing_key: Optional[bytes] = None) -> bool:
        expected = self.compute_consequence_graph_hash()
        if not hmac.compare_digest(expected,
                                     self.consequence_graph_hash or ""):
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
                          self.consequence_graph_hash.encode("utf-8"))
                return True
            except Exception:
                return False
        else:
            key = signing_key or _load_hmac_key()
            expected_sig = hmac.new(
                key, self.consequence_graph_hash.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_sig, self.signature or "")

    @classmethod
    def create(
        cls,
        issuer: str,
        subject_agent: str,
        consequence_nodes: List[ConsequenceNode],
        *,
        policy_version: str = "",
    ) -> "ConsequenceGraph":
        return cls(
            consequence_graph_id=f"csg_{uuid4().hex[:16]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            issuer=issuer,
            subject_agent=subject_agent,
            policy_version=policy_version,
            consequence_nodes=list(consequence_nodes),
        )

    def _node_map(self) -> Dict[str, ConsequenceNode]:
        return {n.consequence_id: n for n in self.consequence_nodes}

    def pending_nodes(self) -> List[ConsequenceNode]:
        return [n for n in self.consequence_nodes
                if n.status in ("pending", "eligible")]

    def triggered_nodes(self) -> List[ConsequenceNode]:
        return [n for n in self.consequence_nodes
                if n.status == "triggered"]

    def blocked_nodes(self) -> List[ConsequenceNode]:
        return [n for n in self.consequence_nodes
                if n.status in ("blocked", "held")]


# ── Consequence evaluation ──────────────────────────────────────────

@dataclass
class ConsequenceEvaluation:
    valid: bool
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_consequence(
    graph: ConsequenceGraph,
    consequence_id: str,
    *,
    acting_agent: str = "",
    satisfied_proofs: Optional[Set[str]] = None,
    accepted_deals: Optional[Set[str]] = None,
    released_values: Optional[Set[str]] = None,
    satisfied_coordination: Optional[Set[str]] = None,
    triggered_consequences: Optional[Set[str]] = None,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> ConsequenceEvaluation:
    """Deterministic evaluation of whether a consequence may advance."""
    passed: List[str] = []
    failed: List[str] = []
    satisfied_proofs = satisfied_proofs or set()
    accepted_deals = accepted_deals or set()
    released_values = released_values or set()
    satisfied_coordination = satisfied_coordination or set()
    triggered_consequences = triggered_consequences or set()

    # 1. Signature
    if graph.verify_signature(ed25519_public_key=ed25519_public_key,
                                signing_key=signing_key):
        passed.append("graph_signature_valid")
    else:
        failed.append("graph_signature_invalid")

    # 2. Node exists
    nmap = graph._node_map()
    node = nmap.get(consequence_id)
    if not node:
        failed.append(f"consequence_not_found:{consequence_id}")
        return ConsequenceEvaluation(
            valid=False, checks_passed=passed,
            checks_failed=failed, reason="; ".join(failed))
    passed.append(f"consequence_exists:{consequence_id}")

    # 3. Status
    if node.status in ("blocked", "held"):
        failed.append(f"consequence_{node.status}")
    elif node.status in ("reverted", "completed"):
        passed.append(f"already_{node.status}")
    elif node.status == "escalated":
        failed.append("consequence_escalated")
    else:
        passed.append(f"status_ok:{node.status}")

    # 4. Triggering agent
    if acting_agent and node.allowed_triggering_agent:
        if acting_agent == node.allowed_triggering_agent:
            passed.append("triggering_agent_matches")
        else:
            failed.append(f"triggering_agent_mismatch:{node.allowed_triggering_agent}!={acting_agent}")

    # 5. Required proofs
    for ref in node.required_proof_refs:
        if ref in satisfied_proofs:
            passed.append(f"proof_satisfied:{ref}")
        else:
            failed.append(f"proof_not_satisfied:{ref}")

    # 6. Acceptance state
    if node.required_acceptance_state:
        if node.required_acceptance_state in accepted_deals or consequence_id in accepted_deals:
            passed.append("acceptance_met")
        else:
            failed.append("acceptance_not_met")

    # 7. Value state
    if node.required_value_state:
        if node.required_value_state in released_values:
            passed.append("value_state_met")
        else:
            failed.append("value_state_not_met")

    # 8. Coordination state
    if node.required_coordination_state:
        if node.required_coordination_state in satisfied_coordination:
            passed.append("coordination_met")
        else:
            failed.append("coordination_not_met")

    # 9. Blocked-by dependencies
    for blocker in node.blocked_by:
        blocker_node = nmap.get(blocker)
        if blocker_node and blocker_node.status in ("completed", "triggered"):
            passed.append(f"blocker_cleared:{blocker}")
        elif blocker in triggered_consequences:
            passed.append(f"blocker_cleared_external:{blocker}")
        else:
            failed.append(f"blocked_by:{blocker}")

    valid = len(failed) == 0
    return ConsequenceEvaluation(
        valid=valid, checks_passed=passed,
        checks_failed=failed,
        reason="all checks passed" if valid else "; ".join(failed),
    )


# ── Verification ────────────────────────────────────────────────────

def verify_embedded_consequence_graph(
    graph_dict: Dict[str, Any],
    *,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    nodes_raw = graph_dict.get("consequence_nodes", [])
    nodes = [ConsequenceNode(**{k: v for k, v in n.items()
                                  if k in ConsequenceNode.__dataclass_fields__})
             for n in nodes_raw]
    g = ConsequenceGraph(**{
        k: (nodes if k == "consequence_nodes" else v)
        for k, v in graph_dict.items()
        if k in ConsequenceGraph.__dataclass_fields__
    })
    errors: List[str] = []
    sig_ok = g.verify_signature(
        ed25519_public_key=ed25519_public_key,
        signing_key=signing_key,
    )
    if not sig_ok:
        errors.append("consequence graph signature or hash mismatch")
    return {
        "signature_valid": sig_ok,
        "spec_version": g.spec_version,
        "algorithm": g.algorithm,
        "consequence_count": len(g.consequence_nodes),
        "pending": len(g.pending_nodes()),
        "triggered": len(g.triggered_nodes()),
        "blocked": len(g.blocked_nodes()),
        "errors": errors,
    }
