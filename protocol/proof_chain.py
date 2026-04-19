"""
Proof Chains — Composable Provenance Graph
============================================

Allows proofs to reference parent proofs, creating supply chains on-protocol.
Agent A's output becomes Agent B's input proof. Each link is a new settlement.

Usage:
    from protocol.proof_chain import get_proof_chain_store

    store = get_proof_chain_store()
    store.register_link(
        deal_id="deal_abc",
        proof_hash="sha256...",
        parent_proof_ids=["deal_xyz:proof_001"],
    )

    # Query provenance
    ancestors = store.get_ancestors("deal_abc")
    descendants = store.get_descendants("deal_xyz")
    lineage = store.get_full_lineage("deal_abc")

Endpoints:
    GET  /protocol/proof-chain/{deal_id}       — Provenance for a deal
    GET  /protocol/proof-chain/{deal_id}/lineage — Full ancestor + descendant graph
    GET  /protocol/proof-chain/roots            — All root proofs (no parents)
"""

import hashlib
import json
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4
from storage_root import get_data_root

logger = logging.getLogger(__name__)

_STORE_DIR = os.getenv("PROOF_CHAIN_DIR", str(get_data_root() / "proof_chains"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProofChainLink:
    """A single link in the provenance graph."""

    __slots__ = (
        "link_id", "deal_id", "proof_hash", "parent_proof_ids",
        "agent_id", "vertical", "created_at",
    )

    def __init__(
        self,
        deal_id: str,
        proof_hash: str,
        parent_proof_ids: List[str],
        agent_id: str = "",
        vertical: str = "",
        link_id: str = "",
        created_at: str = "",
    ):
        self.link_id = link_id or f"pcl_{uuid4().hex[:12]}"
        self.deal_id = deal_id
        self.proof_hash = proof_hash
        self.parent_proof_ids = parent_proof_ids or []
        self.agent_id = agent_id
        self.vertical = vertical
        self.created_at = created_at or _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "link_id": self.link_id,
            "deal_id": self.deal_id,
            "proof_hash": self.proof_hash,
            "parent_proof_ids": self.parent_proof_ids,
            "agent_id": self.agent_id,
            "vertical": self.vertical,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProofChainLink":
        return cls(
            link_id=d.get("link_id", ""),
            deal_id=d["deal_id"],
            proof_hash=d.get("proof_hash", ""),
            parent_proof_ids=d.get("parent_proof_ids", []),
            agent_id=d.get("agent_id", ""),
            vertical=d.get("vertical", ""),
            created_at=d.get("created_at", ""),
        )


class ProofChainStore:
    """
    Provenance graph for proof chains.

    Indexes:
        _by_deal: deal_id -> ProofChainLink
        _children: parent_deal_id -> [child_deal_id, ...]
        _parents: child_deal_id -> [parent_deal_id, ...]
    """

    def __init__(self, store_dir: str = _STORE_DIR):
        self._by_deal: Dict[str, ProofChainLink] = {}
        self._children: Dict[str, List[str]] = defaultdict(list)
        self._parents: Dict[str, List[str]] = defaultdict(list)
        self._store_file: Optional[Path] = None
        self._lock = threading.Lock()
        self._init_store(store_dir)

    def _init_store(self, store_dir: str):
        try:
            path = Path(store_dir)
            path.mkdir(parents=True, exist_ok=True)
            self._store_file = path / "proof_chains.jsonl"
            if self._store_file.exists():
                count = 0
                for line in self._store_file.read_text().strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        link = ProofChainLink.from_dict(json.loads(line))
                        self._index(link)
                        count += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
                logger.info(f"[PROOF_CHAIN] Loaded {count} chain links")
        except Exception as e:
            logger.warning(f"[PROOF_CHAIN] File store unavailable ({e}), memory-only")

    def _index(self, link: ProofChainLink):
        self._by_deal[link.deal_id] = link
        for parent_id in link.parent_proof_ids:
            # parent_id can be a deal_id or deal_id:proof_id
            parent_deal = parent_id.split(":")[0] if ":" in parent_id else parent_id
            if link.deal_id not in self._children[parent_deal]:
                self._children[parent_deal].append(link.deal_id)
            if parent_deal not in self._parents[link.deal_id]:
                self._parents[link.deal_id].append(parent_deal)

    def register_link(
        self,
        deal_id: str,
        proof_hash: str = "",
        parent_proof_ids: List[str] = None,
        agent_id: str = "",
        vertical: str = "",
    ) -> ProofChainLink:
        """Register a proof chain link. Idempotent per deal_id."""
        with self._lock:
            existing = self._by_deal.get(deal_id)
            if existing:
                return existing

            link = ProofChainLink(
                deal_id=deal_id,
                proof_hash=proof_hash,
                parent_proof_ids=parent_proof_ids or [],
                agent_id=agent_id,
                vertical=vertical,
            )
            self._index(link)

            # Persist
            if self._store_file:
                try:
                    with open(self._store_file, "a") as f:
                        f.write(json.dumps(link.to_dict(), default=str) + "\n")
                except Exception as e:
                    logger.warning(f"[PROOF_CHAIN] Persist failed: {e}")

            return link

    def get_link(self, deal_id: str) -> Optional[ProofChainLink]:
        return self._by_deal.get(deal_id)

    def get_children(self, deal_id: str) -> List[str]:
        """Get direct child deal_ids (proofs that reference this deal as parent)."""
        return list(self._children.get(deal_id, []))

    def get_parents(self, deal_id: str) -> List[str]:
        """Get direct parent deal_ids."""
        return list(self._parents.get(deal_id, []))

    def get_ancestors(self, deal_id: str, max_depth: int = 50) -> List[Dict[str, Any]]:
        """Walk up the provenance graph. Returns ancestor links in BFS order."""
        visited: Set[str] = set()
        queue = [deal_id]
        ancestors = []
        depth = 0

        while queue and depth < max_depth:
            next_queue = []
            for did in queue:
                for parent in self._parents.get(did, []):
                    if parent not in visited:
                        visited.add(parent)
                        link = self._by_deal.get(parent)
                        if link:
                            ancestors.append({**link.to_dict(), "depth": depth + 1})
                        next_queue.append(parent)
            queue = next_queue
            depth += 1

        return ancestors

    def get_descendants(self, deal_id: str, max_depth: int = 50) -> List[Dict[str, Any]]:
        """Walk down the provenance graph. Returns descendant links in BFS order."""
        visited: Set[str] = set()
        queue = [deal_id]
        descendants = []
        depth = 0

        while queue and depth < max_depth:
            next_queue = []
            for did in queue:
                for child in self._children.get(did, []):
                    if child not in visited:
                        visited.add(child)
                        link = self._by_deal.get(child)
                        if link:
                            descendants.append({**link.to_dict(), "depth": depth + 1})
                        next_queue.append(child)
            queue = next_queue
            depth += 1

        return descendants

    def get_full_lineage(self, deal_id: str) -> Dict[str, Any]:
        """Full provenance graph: ancestors + self + descendants."""
        link = self._by_deal.get(deal_id)
        return {
            "deal_id": deal_id,
            "link": link.to_dict() if link else None,
            "is_root": deal_id not in self._parents or len(self._parents[deal_id]) == 0,
            "ancestors": self.get_ancestors(deal_id),
            "descendants": self.get_descendants(deal_id),
            "ancestor_count": len(self.get_ancestors(deal_id)),
            "descendant_count": len(self.get_descendants(deal_id)),
        }

    def get_roots(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all root proofs (no parents) — supply chain origins."""
        roots = []
        for deal_id, link in self._by_deal.items():
            if not link.parent_proof_ids:
                child_count = len(self._children.get(deal_id, []))
                roots.append({**link.to_dict(), "descendant_count": child_count})
                if len(roots) >= limit:
                    break
        return roots

    def compute_chain_hash(self, deal_id: str) -> str:
        """Compute deterministic hash over the full provenance chain for a deal."""
        lineage = self.get_full_lineage(deal_id)
        all_ids = sorted(
            [a["deal_id"] for a in lineage["ancestors"]]
            + [deal_id]
            + [d["deal_id"] for d in lineage["descendants"]]
        )
        canonical = json.dumps(all_ids, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def stats(self) -> Dict[str, Any]:
        total = len(self._by_deal)
        roots = sum(1 for d in self._by_deal if d not in self._parents or not self._parents[d])
        leaves = sum(1 for d in self._by_deal if d not in self._children or not self._children[d])
        return {
            "total_links": total,
            "root_proofs": roots,
            "leaf_proofs": leaves,
            "chain_proofs": total - roots - leaves if total > roots + leaves else 0,
        }


# ── Singleton ──

_store: Optional[ProofChainStore] = None


def get_proof_chain_store() -> ProofChainStore:
    global _store
    if _store is None:
        _store = ProofChainStore()
    return _store


# ── FastAPI Router ──

def get_proof_chain_router():
    try:
        from fastapi import APIRouter, HTTPException, Query
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol", tags=["Proof Chains"])

    @router.get("/proof-chain/{deal_id}")
    async def get_proof_chain(deal_id: str):
        """Get proof chain provenance for a deal."""
        store = get_proof_chain_store()
        link = store.get_link(deal_id)
        if not link:
            return {
                "ok": True,
                "deal_id": deal_id,
                "chain": None,
                "message": "No proof chain registered for this deal",
            }
        return {
            "ok": True,
            "deal_id": deal_id,
            "chain": link.to_dict(),
            "parents": store.get_parents(deal_id),
            "children": store.get_children(deal_id),
            "is_root": len(link.parent_proof_ids) == 0,
        }

    @router.get("/proof-chain/{deal_id}/lineage")
    async def get_proof_lineage(deal_id: str):
        """Get full provenance lineage: ancestors + self + descendants."""
        store = get_proof_chain_store()
        lineage = store.get_full_lineage(deal_id)
        lineage["ok"] = True
        lineage["chain_hash"] = store.compute_chain_hash(deal_id)
        return lineage

    @router.get("/proof-chain/roots")
    async def get_chain_roots(limit: int = Query(100, le=500)):
        """Get all root proofs (supply chain origins)."""
        store = get_proof_chain_store()
        return {
            "ok": True,
            "roots": store.get_roots(limit=limit),
            "stats": store.stats(),
        }

    return router
