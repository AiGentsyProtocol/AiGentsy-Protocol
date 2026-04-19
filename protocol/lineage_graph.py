"""Lineage / Offspring Graph v1.

Seventh institutional primitive in AiGentsy Stack. Models how
descendant agents or artifacts emerge from parent agents/artifacts,
what they inherit, what they mutate, what rights and constraints
persist, and how recursive accountability remains intact.

AUDIT RESULT — WHAT WAS REUSED:
    protocol/recursive_spawn.py  — parent-child agent spawning with
      inherited OCS (50%), capped permissions, graduation, revocation.
    protocol/proof_chain.py      — parent-child proof provenance with
      BFS ancestry/descendant queries and chain hashing.
    multi-generation royalty system —  clone royalties
      (30% → 10% → 3%) with cascading lineage tracking.
    protocol/referral_graph.py   — 3-hop referral attribution chains.

    This module WRAPS these existing systems into a portable, signed,
    inspectable lineage artifact. It does NOT replace them.

Stack primitives:
    HoverStack           — compute governance
    Mandate Graph        — authority
    Coordination Graph   — obligations & dependency
    Value Flow Graph     — value allocation & release conditions
    Trust Profile        — accumulated reliability & trust posture
    Lineage Graph        — recursive descent, inheritance, accountability
    ProofPack / GEP      — work proof / acceptance / downstream gating
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


SPEC_VERSION = "lineage_graph/v1"

_EXCLUDE_FROM_HASH = frozenset({"lineage_hash", "signature"})

VALID_DESCENT_TYPES = frozenset({
    "clone", "remix", "derived_agent", "delegated_spawn",
    "fork", "template_instantiation",
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
class InheritedTrait:
    """One trait carried from parent to child."""
    trait_name: str = ""
    trait_value: Any = None
    inherited: bool = True
    mutated: bool = False
    mutation_description: str = ""
    source: str = ""


@dataclass
class LineageEconomicLink:
    """An economic entitlement surviving descent.

    Reuses the multi-generation royalty pattern
    (30% → 10% → 3%) and referral_graph.py attribution chains.
    """
    link_type: str = ""         # "royalty" | "referral_fee" | "revenue_share"
    beneficiary: str = ""       # who receives
    share: float = 0.0          # 0-1 fraction
    generation: int = 0
    source_ref: str = ""


@dataclass
class LineageNode:
    """One node in the lineage graph."""
    lineage_id: str = ""
    spec_version: str = SPEC_VERSION
    created_at: str = ""
    issuer: str = ""
    subject_agent: str = ""
    parent_agent: str = ""
    parent_lineage_id: str = ""
    ancestor_chain: List[str] = field(default_factory=list)
    descent_type: str = "derived_agent"
    generation: int = 0
    policy_version: str = ""

    # Inheritance model
    inherited_traits: List[InheritedTrait] = field(default_factory=list)
    mutated_traits: List[InheritedTrait] = field(default_factory=list)
    retained_constraints: List[str] = field(default_factory=list)
    new_constraints: List[str] = field(default_factory=list)
    inherited_rights: List[str] = field(default_factory=list)
    retained_obligations: List[str] = field(default_factory=list)

    # Economic links surviving descent
    lineage_economic_links: List[LineageEconomicLink] = field(default_factory=list)

    # Evidence
    source_refs: List[str] = field(default_factory=list)
    spawn_mandate_id: str = ""
    spawn_proof_chain_id: str = ""

    # Signing
    algorithm: str = "ed25519"
    public_key: str = ""
    lineage_hash: str = ""
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _content_bytes(self) -> bytes:
        d = self.to_dict()
        for k in _EXCLUDE_FROM_HASH:
            d.pop(k, None)
        return _canonical_json_bytes(d)

    def compute_lineage_hash(self) -> str:
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
        self.lineage_hash = self.compute_lineage_hash()
        if alg == "ed25519":
            pk = ed25519_private_key or _load_ed25519_private()
            self.signature = pk.sign(
                self.lineage_hash.encode("utf-8")).hex()
        else:
            key = signing_key or _load_hmac_key()
            self.signature = hmac.new(
                key, self.lineage_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()

    def verify_signature(self, *, ed25519_public_key: Any = None,
                          signing_key: Optional[bytes] = None) -> bool:
        expected = self.compute_lineage_hash()
        if not hmac.compare_digest(expected, self.lineage_hash or ""):
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
                          self.lineage_hash.encode("utf-8"))
                return True
            except Exception:
                return False
        else:
            key = signing_key or _load_hmac_key()
            expected_sig = hmac.new(
                key, self.lineage_hash.encode("utf-8"), hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_sig, self.signature or "")

    @classmethod
    def create(
        cls,
        issuer: str,
        subject_agent: str,
        parent_agent: str,
        *,
        descent_type: str = "derived_agent",
        parent_lineage_id: str = "",
        ancestor_chain: Optional[List[str]] = None,
        generation: int = 0,
        inherited_traits: Optional[List[InheritedTrait]] = None,
        mutated_traits: Optional[List[InheritedTrait]] = None,
        retained_constraints: Optional[List[str]] = None,
        new_constraints: Optional[List[str]] = None,
        inherited_rights: Optional[List[str]] = None,
        retained_obligations: Optional[List[str]] = None,
        lineage_economic_links: Optional[List[LineageEconomicLink]] = None,
        source_refs: Optional[List[str]] = None,
        spawn_mandate_id: str = "",
        spawn_proof_chain_id: str = "",
        policy_version: str = "",
    ) -> "LineageNode":
        return cls(
            lineage_id=f"lin_{uuid4().hex[:16]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            issuer=issuer,
            subject_agent=subject_agent,
            parent_agent=parent_agent,
            parent_lineage_id=parent_lineage_id,
            ancestor_chain=list(ancestor_chain or []),
            descent_type=descent_type,
            generation=generation,
            policy_version=policy_version,
            inherited_traits=list(inherited_traits or []),
            mutated_traits=list(mutated_traits or []),
            retained_constraints=list(retained_constraints or []),
            new_constraints=list(new_constraints or []),
            inherited_rights=list(inherited_rights or []),
            retained_obligations=list(retained_obligations or []),
            lineage_economic_links=list(lineage_economic_links or []),
            source_refs=list(source_refs or []),
            spawn_mandate_id=spawn_mandate_id,
            spawn_proof_chain_id=spawn_proof_chain_id,
        )

    def spawn_child(
        self,
        child_agent: str,
        *,
        descent_type: str = "derived_agent",
        inherited_traits: Optional[List[InheritedTrait]] = None,
        mutated_traits: Optional[List[InheritedTrait]] = None,
        new_constraints: Optional[List[str]] = None,
        lineage_economic_links: Optional[List[LineageEconomicLink]] = None,
    ) -> "LineageNode":
        """Create a child lineage node inheriting from this node.

        Constraints and obligations carry forward by default. Rights
        narrow (child inherits parent's rights unless explicitly removed).
        Economic links accumulate across generations.
        """
        child_ancestor_chain = list(self.ancestor_chain)
        child_ancestor_chain.append(self.lineage_id)
        child_gen = self.generation + 1
        child_constraints = list(self.retained_constraints) + list(self.new_constraints)
        child_obligations = list(self.retained_obligations)
        # Parent's economic links cascade to child with incremented gen.
        cascaded_links = []
        for link in self.lineage_economic_links:
            cascaded_links.append(LineageEconomicLink(
                link_type=link.link_type,
                beneficiary=link.beneficiary,
                share=link.share,
                generation=link.generation + 1,
                source_ref=link.source_ref,
            ))
        if lineage_economic_links:
            cascaded_links.extend(lineage_economic_links)

        return LineageNode.create(
            issuer=self.subject_agent,
            subject_agent=child_agent,
            parent_agent=self.subject_agent,
            descent_type=descent_type,
            parent_lineage_id=self.lineage_id,
            ancestor_chain=child_ancestor_chain,
            generation=child_gen,
            inherited_traits=inherited_traits or [],
            mutated_traits=mutated_traits or [],
            retained_constraints=child_constraints,
            new_constraints=list(new_constraints or []),
            inherited_rights=list(self.inherited_rights),
            retained_obligations=child_obligations,
            lineage_economic_links=cascaded_links,
            policy_version=self.policy_version,
        )


def verify_embedded_lineage(
    lineage_dict: Dict[str, Any],
    *,
    ed25519_public_key: Any = None,
    signing_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    traits_raw = lineage_dict.get("inherited_traits", [])
    traits = [InheritedTrait(**{k: v for k, v in t.items()
                                 if k in InheritedTrait.__dataclass_fields__})
              for t in traits_raw]
    mutated_raw = lineage_dict.get("mutated_traits", [])
    mutated = [InheritedTrait(**{k: v for k, v in t.items()
                                  if k in InheritedTrait.__dataclass_fields__})
               for t in mutated_raw]
    links_raw = lineage_dict.get("lineage_economic_links", [])
    links = [LineageEconomicLink(**{k: v for k, v in l.items()
                                     if k in LineageEconomicLink.__dataclass_fields__})
             for l in links_raw]
    node = LineageNode(**{
        k: (traits if k == "inherited_traits"
            else mutated if k == "mutated_traits"
            else links if k == "lineage_economic_links"
            else v)
        for k, v in lineage_dict.items()
        if k in LineageNode.__dataclass_fields__
    })
    errors: List[str] = []
    sig_ok = node.verify_signature(
        ed25519_public_key=ed25519_public_key,
        signing_key=signing_key,
    )
    if not sig_ok:
        errors.append("lineage signature or hash does not match content")
    return {
        "signature_valid": sig_ok,
        "spec_version": node.spec_version,
        "algorithm": node.algorithm,
        "subject_agent": node.subject_agent,
        "parent_agent": node.parent_agent,
        "descent_type": node.descent_type,
        "generation": node.generation,
        "errors": errors,
    }
