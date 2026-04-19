"""Commitment / Coordination Graph v1.

Fourth institutional primitive in AiGentsy Stack. Models how multiple
authorized agents and dependent work commitments are structured,
constrained, satisfied, and unlocked before downstream consequences.

Stack primitives:
    HoverStack          — compute governance
    Mandate Graph       — authority
    Coordination Graph  — multi-agent coordination & dependency
    ProofPack / GEP     — work proof / acceptance / downstream gating

v1 claim:
    "These work commitments were structured, their dependencies are
    recorded, and their completion/acceptance states are inspectable
    and verifiable."

v1 non-claims:
    - Does NOT orchestrate execution (the graph is declarative, not
      a workflow engine).
    - Does NOT enforce transitions at runtime (evaluation is offline-
      capable; enforcement is the caller's responsibility).
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


SPEC_VERSION = "coordination_graph/v1"

_EXCLUDE_FROM_HASH = frozenset({"graph_hash", "signature"})


# ── Shared signing (delegates to governed_proof primitives) ──────────

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


# ── Commitment status model ─────────────────────────────────────────

VALID_STATUSES = frozenset({
    "pending", "ready", "in_progress", "completed",
    "accepted", "blocked", "failed", "escalated",
})


# ── Schema ───────────────────────────────────────────────────────────

@dataclass
class CommitmentNode:
    """One obligation in the coordination graph."""
    commitment_id: str = ""
    work_label: str = ""
    responsible_agent: str = ""
    required_mandate_id: str = ""
    work_class: str = ""
    status: str = "pending"
    depends_on: List[str] = field(default_factory=list)
    parallelizable: bool = True
    joint_completion_group: str = ""
    required_proof_types: List[str] = field(default_factory=list)
    required_acceptance_state: str = ""
    unlocks_consequences: List[str] = field(default_factory=list)
    allowed_downstream_actions: List[str] = field(default_factory=list)
    deadline: str = ""
    failure_mode: str = "escalate"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CoordinationGraph:
    """Signed, portable coordination artifact.

    Embeds inside ProofPack at evidence.coordination_graph.
    """
    spec_version: str = SPEC_VERSION
    graph_id: str = ""
    created_at: str = ""
    issuer: str = ""
    policy_version: str = ""
    commitments: List[CommitmentNode] = field(default_factory=list)

    # Signing
    algorithm: str = "ed25519"
    public_key: str = ""
    graph_hash: str = ""
    signature: str = ""

    # ── Serialization ────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    def _content_bytes(self) -> bytes:
        d = self.to_dict()
        for k in _EXCLUDE_FROM_HASH:
            d.pop(k, None)
        return _canonical_json_bytes(d)

    def compute_graph_hash(self) -> str:
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
        self.graph_hash = self.compute_graph_hash()
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.signature = pk.sign(
                self.graph_hash.encode("utf-8")).hex()
        else:
            key = signing_key or _load_hmac_key()
            self.signature = hmac.new(
                key, self.graph_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()

    def verify_signature(self, *, ed25519_public_key: Any = None,
                          signing_key: Optional[bytes] = None) -> bool:
        expected = self.compute_graph_hash()
        if not hmac.compare_digest(expected, self.graph_hash or ""):
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
                          self.graph_hash.encode("utf-8"))
                return True
            except Exception:
                return False
        else:
            key = signing_key or _load_hmac_key()
            expected_sig = hmac.new(
                key, self.graph_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_sig, self.signature or "")

    # ── Construction helpers ─────────────────────────────────────────

    @classmethod
    def create(
        cls,
        issuer: str,
        commitments: List[CommitmentNode],
        *,
        policy_version: str = "",
    ) -> "CoordinationGraph":
        return cls(
            graph_id=f"cg_{uuid4().hex[:16]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            issuer=issuer,
            policy_version=policy_version,
            commitments=list(commitments),
        )

    # ── Graph inspection ─────────────────────────────────────────────

    def _node_map(self) -> Dict[str, CommitmentNode]:
        return {n.commitment_id: n for n in self.commitments}

    def root_commitments(self) -> List[CommitmentNode]:
        return [n for n in self.commitments if not n.depends_on]

    def leaf_commitments(self) -> List[CommitmentNode]:
        all_deps: Set[str] = set()
        for n in self.commitments:
            all_deps.update(n.depends_on)
        return [n for n in self.commitments
                if n.commitment_id not in all_deps]

    def dependency_chain(self, commitment_id: str) -> List[str]:
        """Return ordered list of commitment_ids from root to this node."""
        nmap = self._node_map()
        chain: List[str] = []
        visited: Set[str] = set()
        def _walk(cid: str):
            if cid in visited:
                return
            visited.add(cid)
            node = nmap.get(cid)
            if node:
                for dep in node.depends_on:
                    _walk(dep)
            chain.append(cid)
        _walk(commitment_id)
        return chain

    def joint_group_members(self, group_id: str) -> List[CommitmentNode]:
        return [n for n in self.commitments
                if n.joint_completion_group == group_id and group_id]


# ── Coordination Validity Evaluation ─────────────────────────────────

@dataclass
class CoordinationEvaluation:
    valid: bool
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_transition(
    graph: CoordinationGraph,
    commitment_id: str,
    *,
    new_status: str = "",
    acting_agent: str = "",
    available_proofs: Optional[Set[str]] = None,
    accepted_commitments: Optional[Set[str]] = None,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> CoordinationEvaluation:
    """Evaluate whether a commitment can transition to a new status.

    Deterministic and auditable. Returns passed/failed checks.
    """
    passed: List[str] = []
    failed: List[str] = []
    available_proofs = available_proofs or set()
    accepted_commitments = accepted_commitments or set()

    # 1. Signature
    if graph.verify_signature(ed25519_public_key=ed25519_public_key,
                                signing_key=signing_key):
        passed.append("graph_signature_valid")
    else:
        failed.append("graph_signature_invalid")

    # 2. Node exists
    nmap = graph._node_map()
    node = nmap.get(commitment_id)
    if not node:
        failed.append(f"commitment_not_found:{commitment_id}")
        return CoordinationEvaluation(
            valid=False, checks_passed=passed,
            checks_failed=failed, reason="; ".join(failed))

    passed.append(f"commitment_exists:{commitment_id}")

    # 3. Agent matches
    if acting_agent:
        if node.responsible_agent == acting_agent:
            passed.append("agent_matches")
        else:
            failed.append(f"agent_mismatch:{node.responsible_agent}!={acting_agent}")

    # 4. Dependencies satisfied
    for dep_id in node.depends_on:
        dep_node = nmap.get(dep_id)
        if dep_node and dep_node.status in ("completed", "accepted"):
            passed.append(f"dep_satisfied:{dep_id}")
        elif dep_id in accepted_commitments:
            passed.append(f"dep_satisfied_external:{dep_id}")
        else:
            failed.append(f"dep_not_satisfied:{dep_id}")

    # 5. Joint completion group
    if node.joint_completion_group:
        group = graph.joint_group_members(node.joint_completion_group)
        all_complete = all(
            m.status in ("completed", "accepted")
            or m.commitment_id in accepted_commitments
            for m in group
            if m.commitment_id != commitment_id
        )
        if all_complete:
            passed.append(f"joint_group_satisfied:{node.joint_completion_group}")
        else:
            failed.append(f"joint_group_incomplete:{node.joint_completion_group}")

    # 6. Required proofs
    for pt in node.required_proof_types:
        if pt in available_proofs:
            passed.append(f"proof_available:{pt}")
        else:
            failed.append(f"proof_missing:{pt}")

    # 7. Required acceptance
    if node.required_acceptance_state:
        if node.required_acceptance_state in ("accepted",) and node.status == "accepted":
            passed.append("acceptance_met")
        elif commitment_id in accepted_commitments:
            passed.append("acceptance_met_external")
        else:
            passed.append("acceptance_not_yet_required")

    # 8. Status transition validity
    if new_status:
        if new_status not in VALID_STATUSES:
            failed.append(f"invalid_status:{new_status}")
        elif node.status == "blocked" and failed:
            failed.append("cannot_transition_while_blocked")
        else:
            passed.append(f"status_transition_ok:{node.status}->{new_status}")

    valid = len(failed) == 0
    return CoordinationEvaluation(
        valid=valid, checks_passed=passed,
        checks_failed=failed,
        reason="all checks passed" if valid else "; ".join(failed),
    )


# ── Verification helper ─────────────────────────────────────────────

def verify_embedded_coordination_graph(
    graph_dict: Dict[str, Any],
    *,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    """Offline verification of a coordination graph from a ProofPack."""
    errors: List[str] = []
    commitments_raw = graph_dict.get("commitments", [])
    nodes = [CommitmentNode(**{k: v for k, v in c.items()
                                if k in CommitmentNode.__dataclass_fields__})
             for c in commitments_raw]
    g = CoordinationGraph(**{
        k: (nodes if k == "commitments" else v)
        for k, v in graph_dict.items()
        if k in CoordinationGraph.__dataclass_fields__
    })
    sig_ok = g.verify_signature(
        ed25519_public_key=ed25519_public_key,
        signing_key=signing_key,
    )
    if not sig_ok:
        errors.append("graph signature or hash does not match content")
    return {
        "signature_valid": sig_ok,
        "spec_version": g.spec_version,
        "algorithm": g.algorithm,
        "commitment_count": len(g.commitments),
        "errors": errors,
    }
