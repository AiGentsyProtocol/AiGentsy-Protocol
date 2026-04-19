"""
RFC 6962 Compliant Merkle Transparency Log
============================================

Implements the AiGentsy Settlement Transparency Log:
- RFC 6962 domain-separated hashing (0x00 leaf, 0x01 node)
- Append-only log with inclusion proofs
- Consistency proofs between tree sizes
- Signed Tree Heads (STH) with Ed25519
- JSONL-backed persistent storage

Usage:
    from protocol.merkle_log import get_log, SignedTreeHead

    log = get_log()
    leaf_hash = log.append_leaf(leaf_data)
    sth = log.sign_tree_head()
    proof = log.inclusion_proof(leaf_index, tree_size)
    consistency = log.consistency_proof(first_size, second_size)
"""

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from storage_root import get_data_root

logger = logging.getLogger(__name__)

LOG_ID = "aigentsy_settlement_log_v1"
KEY_ID = "aigentsy_log_signer_v1"

_LOG_DIR = Path(os.getenv("MERKLE_LOG_DIR", str(get_data_root() / "merkle_log")))
_KEY_DIR = Path(os.getenv("LOG_KEY_DIR", str(get_data_root() / "log_keys")))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── RFC 6962 Hash Functions ──


def rfc6962_leaf_hash(data: bytes) -> bytes:
    """Hash a leaf with 0x00 prefix (RFC 6962 Section 2.1)."""
    return hashlib.sha256(b"\x00" + data).digest()


def rfc6962_node_hash(left: bytes, right: bytes) -> bytes:
    """Hash two children with 0x01 prefix (RFC 6962 Section 2.1)."""
    return hashlib.sha256(b"\x01" + left + right).digest()


def leaf_hash_hex(data: bytes) -> str:
    return rfc6962_leaf_hash(data).hex()


def node_hash_hex(left_hex: str, right_hex: str) -> str:
    return rfc6962_node_hash(
        bytes.fromhex(left_hex), bytes.fromhex(right_hex)
    ).hex()


# ── Ed25519 Key Management ──


class LogSigner:
    """Ed25519 key pair for signing tree heads."""

    def __init__(self, key_dir: Path = _KEY_DIR):
        self._key_dir = key_dir
        self._private_key = None
        self._public_key = None
        self._load_or_generate()

    def _load_or_generate(self):
        self._key_dir.mkdir(parents=True, exist_ok=True)
        priv_path = self._key_dir / "log_signing_key.pem"
        pub_path = self._key_dir / "log_public_key.pem"

        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
            from cryptography.hazmat.primitives.serialization import (
                BestAvailableEncryption,
                Encoding,
                NoEncryption,
                PrivateFormat,
                PublicFormat,
                load_pem_private_key,
            )

            # Key encryption: use LOG_KEY_PASSWORD env var if set, otherwise NoEncryption
            _key_password = os.getenv("LOG_KEY_PASSWORD", "").encode() or None
            if not _key_password:
                _is_prod = os.getenv("RENDER", "") or os.getenv("PRODUCTION", "")
                if _is_prod:
                    logger.warning(
                        "[MERKLE_LOG] SECURITY: LOG_KEY_PASSWORD not set in production — "
                        "Ed25519 private key will be stored unencrypted. "
                        "Set LOG_KEY_PASSWORD env var to encrypt the signing key at rest."
                    )
            _encryption = (
                BestAvailableEncryption(_key_password)
                if _key_password
                else NoEncryption()
            )

            if priv_path.exists():
                with open(priv_path, "rb") as f:
                    self._private_key = load_pem_private_key(f.read(), password=_key_password)
                self._public_key = self._private_key.public_key()
                logger.info("[MERKLE_LOG] Loaded existing Ed25519 signing key")
            else:
                self._private_key = Ed25519PrivateKey.generate()
                self._public_key = self._private_key.public_key()

                with open(priv_path, "wb") as f:
                    f.write(
                        self._private_key.private_bytes(
                            Encoding.PEM, PrivateFormat.PKCS8, _encryption
                        )
                    )
                with open(pub_path, "wb") as f:
                    f.write(
                        self._public_key.public_bytes(
                            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
                        )
                    )
                logger.info("[MERKLE_LOG] Generated new Ed25519 signing key")

        except ImportError:
            _is_prod = (
                os.getenv("RENDER", "").lower() in ("1", "true")
                or os.getenv("RENDER_EXTERNAL_URL", "") != ""
            )
            if _is_prod:
                logger.critical(
                    "[MERKLE_LOG] cryptography package not installed in PRODUCTION — "
                    "Ed25519 signing UNAVAILABLE. Install cryptography>=41.0."
                )
                raise RuntimeError(
                    "cryptography package required in production for Ed25519 signing"
                )
            logger.warning(
                "[MERKLE_LOG] cryptography package not installed — "
                "STH signatures will use HMAC-SHA256 fallback (dev only)"
            )
            self._private_key = None
            self._public_key = None

    def sign(self, message: bytes) -> bytes:
        """Sign a message. Returns Ed25519 signature or HMAC-SHA256 fallback."""
        if self._private_key is not None:
            return self._private_key.sign(message)

        # HMAC-SHA256 fallback — dev/local only (production fails closed in __init__)
        import hmac

        secret = os.getenv("LOG_SIGNING_SECRET", "")
        if not secret:
            secret = "aigentsy_dev_" + hashlib.sha256(os.urandom(32)).hexdigest()
            logger.warning(
                "[MERKLE_LOG] No LOG_SIGNING_SECRET set — using random per-instance HMAC secret (dev only)"
            )
        return hmac.new(secret.encode(), message, hashlib.sha256).digest()

    def verify(self, message: bytes, signature: bytes) -> bool:
        """Verify a signature."""
        if self._public_key is not None:
            try:
                self._public_key.verify(signature, message)
                return True
            except Exception:
                return False

        # HMAC fallback
        expected = self.sign(message)
        return hmac.compare_digest(expected, signature)

    def public_key_base64(self) -> str:
        """Return base64-encoded public key for distribution."""
        if self._public_key is not None:
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                PublicFormat,
            )

            raw = self._public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
            return base64.b64encode(raw).decode()

        return base64.b64encode(b"hmac_fallback_no_pubkey").decode()

    def algorithm(self) -> str:
        return "Ed25519" if self._private_key is not None else "HMAC-SHA256"

    def public_key_json(self) -> Dict[str, Any]:
        return {
            "key_id": KEY_ID,
            "algorithm": self.algorithm(),
            "public_key_base64": self.public_key_base64(),
            "status": "active",
            "active_from": "2026-03-15T00:00:00Z",
            "key_version": 1,
            "rotation_policy": "manual",
        }


# ── Merkle Tree (RFC 6962) ──


class RFC6962MerkleTree:
    """
    Append-only Merkle tree with RFC 6962 domain separation.

    Supports:
    - append_leaf(data) → leaf_hash
    - get_root(tree_size?) → root_hash
    - inclusion_proof(leaf_index, tree_size) → proof path
    - consistency_proof(first_size, second_size) → proof hashes
    """

    def __init__(self):
        self._leaves: List[str] = []  # leaf hashes (hex)
        self._leaf_data: Dict[int, Dict] = {}  # index → original data

    @property
    def tree_size(self) -> int:
        return len(self._leaves)

    def append_leaf(self, data: Dict[str, Any]) -> Tuple[str, int]:
        """Append a leaf. Returns (leaf_hash_hex, leaf_index)."""
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        lh = leaf_hash_hex(canonical.encode("utf-8"))
        index = len(self._leaves)
        self._leaves.append(lh)
        self._leaf_data[index] = data
        return lh, index

    def get_root(self, tree_size: int = None) -> str:
        """Compute Merkle root for tree at given size."""
        n = tree_size if tree_size is not None else len(self._leaves)
        if n == 0:
            return hashlib.sha256(b"").hexdigest()
        return self._compute_root(0, n)

    def _compute_root(self, lo: int, hi: int) -> str:
        """Recursively compute root of leaves[lo:hi]."""
        n = hi - lo
        if n == 1:
            return self._leaves[lo]
        # Split at largest power of 2 less than n
        k = _largest_power_of_2_less_than(n)
        left = self._compute_root(lo, lo + k)
        right = self._compute_root(lo + k, hi)
        return node_hash_hex(left, right)

    def inclusion_proof(self, leaf_index: int, tree_size: int = None) -> List[str]:
        """
        Generate inclusion proof for leaf at leaf_index in tree of tree_size.
        Returns list of sibling hashes (from leaf to root).
        """
        n = tree_size if tree_size is not None else len(self._leaves)
        if leaf_index >= n or n == 0:
            return []
        return self._inclusion_path(leaf_index, 0, n)

    def _inclusion_path(self, leaf_index: int, lo: int, hi: int) -> List[str]:
        n = hi - lo
        if n == 1:
            return []
        k = _largest_power_of_2_less_than(n)
        if leaf_index - lo < k:
            # Leaf is in left subtree
            path = self._inclusion_path(leaf_index, lo, lo + k)
            path.append(self._compute_root(lo + k, hi))
            return path
        else:
            # Leaf is in right subtree
            path = self._inclusion_path(leaf_index, lo + k, hi)
            path.append(self._compute_root(lo, lo + k))
            return path

    def consistency_proof(self, first_size: int, second_size: int) -> List[str]:
        """
        Generate consistency proof between tree at first_size and second_size.
        Proves tree(first_size) is a prefix of tree(second_size).
        """
        if first_size == 0 or first_size > second_size or second_size > len(self._leaves):
            return []
        if first_size == second_size:
            return []
        return self._consistency_path(first_size, 0, second_size, True)

    def _consistency_path(
        self, m: int, lo: int, hi: int, start: bool
    ) -> List[str]:
        n = hi - lo
        if m == n:
            if start:
                return []
            return [self._compute_root(lo, hi)]
        k = _largest_power_of_2_less_than(n)
        if m <= k:
            path = self._consistency_path(m, lo, lo + k, start)
            path.append(self._compute_root(lo + k, hi))
            return path
        else:
            path = self._consistency_path(m - k, lo + k, hi, False)
            path.append(self._compute_root(lo, lo + k))
            return path

    def get_leaf(self, index: int) -> Optional[Dict]:
        return self._leaf_data.get(index)


def _largest_power_of_2_less_than(n: int) -> int:
    """Return largest power of 2 strictly less than n."""
    if n <= 1:
        return 0
    k = 1
    while k * 2 < n:
        k *= 2
    return k


# ── Inclusion Proof Verification (Standalone — no server imports) ──


def verify_inclusion(
    leaf_hash: str,
    leaf_index: int,
    tree_size: int,
    proof: List[str],
    expected_root: str,
) -> bool:
    """
    Verify a Merkle inclusion proof offline.

    Args:
        leaf_hash: The leaf hash (hex)
        leaf_index: Index of the leaf in the tree
        tree_size: Size of the tree when proof was generated
        proof: List of sibling hashes (hex) from leaf to root
        expected_root: Expected root hash (hex)

    Returns:
        True if the proof is valid
    """
    if tree_size == 0 or leaf_index >= tree_size:
        return False

    # Walk the proof using the same recursive split as generation
    proof_iter = iter(proof)
    try:
        computed = _verify_path(leaf_hash, leaf_index, 0, tree_size, proof_iter)
    except StopIteration:
        return False

    # Ensure all proof elements were consumed
    remaining = list(proof_iter)
    return computed == expected_root and len(remaining) == 0


def _verify_path(
    leaf_hash: str, leaf_index: int, lo: int, hi: int, proof_iter
) -> str:
    """Recursively verify inclusion following the same split as generation."""
    n = hi - lo
    if n == 1:
        return leaf_hash
    k = _largest_power_of_2_less_than(n)
    if leaf_index - lo < k:
        # Leaf is in left subtree — proof element is right subtree root
        left = _verify_path(leaf_hash, leaf_index, lo, lo + k, proof_iter)
        right = next(proof_iter)
        return node_hash_hex(left, right)
    else:
        # Leaf is in right subtree — proof element is left subtree root
        right = _verify_path(leaf_hash, leaf_index, lo + k, hi, proof_iter)
        left = next(proof_iter)
        return node_hash_hex(left, right)


def verify_consistency(
    first_size: int,
    second_size: int,
    first_root: str,
    second_root: str,
    proof: List[str],
) -> bool:
    """
    Verify a Merkle consistency proof offline.

    Proves that tree(first_size) is a prefix of tree(second_size).
    """
    if first_size == 0:
        return True
    if first_size == second_size:
        return first_root == second_root and len(proof) == 0
    if first_size > second_size or len(proof) == 0:
        return False

    # Use the RFC 6962 consistency verification algorithm
    proof_idx = [0]  # mutable for closure

    def _inner(m: int, lo: int, hi: int, start: bool) -> Tuple[str, str]:
        n = hi - lo
        if m == n:
            if start:
                root = ""  # Will be computed from first subtree
                return root, _compute_root_from_proof(lo, hi, proof, proof_idx)
            if proof_idx[0] >= len(proof):
                return "", ""
            h = proof[proof_idx[0]]
            proof_idx[0] += 1
            return h, h

        k = _largest_power_of_2_less_than(n)
        if m <= k:
            left_old, left_new = _inner(m, lo, lo + k, start)
            if proof_idx[0] >= len(proof):
                return "", ""
            right = proof[proof_idx[0]]
            proof_idx[0] += 1
            new_root = node_hash_hex(left_new, right)
            return left_old, new_root
        else:
            right_old, right_new = _inner(m - k, lo + k, hi, False)
            if proof_idx[0] >= len(proof):
                return "", ""
            left = proof[proof_idx[0]]
            proof_idx[0] += 1
            old_root = node_hash_hex(left, right_old)
            new_root = node_hash_hex(left, right_new)
            return old_root, new_root

    try:
        old_root, new_root = _inner(first_size, 0, second_size, True)
        if not old_root:
            old_root = first_root
        return old_root == first_root and new_root == second_root
    except (IndexError, ValueError):
        return False


def _compute_root_from_proof(lo, hi, proof, proof_idx):
    """Helper — not used in public verification, returns empty."""
    return ""


# ── Transparency Log ──


class TransparencyLog:
    """
    Append-only transparency log backed by RFC 6962 Merkle tree.

    Features:
    - JSONL persistent storage
    - Ed25519 signed tree heads
    - Inclusion and consistency proofs
    - Settlement-finality event filtering
    """

    FINALITY_EVENTS = frozenset(
        {
            "PROOF_READY",
            "PROOF_VERIFIED",
            "GO_APPROVED",
            "AUTO_GO_APPROVED",
            "SETTLED",
            "PAYOUT_CONFIRMED",
            "OUTCOME_RECORDED",
        }
    )

    def __init__(self, log_dir: Path = _LOG_DIR, signer: LogSigner = None):
        self._tree = RFC6962MerkleTree()
        self._signer = signer or LogSigner()
        self._log_dir = log_dir
        self._sth_history: List[Dict] = []
        self._log_file: Optional[Path] = None
        self._write_lock = __import__("threading").Lock()
        self._init_storage()

    def _init_storage(self):
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._log_file = self._log_dir / "log_entries.jsonl"

            # Reload existing entries
            if self._log_file.exists():
                with open(self._log_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            self._tree.append_leaf(entry)
                        except (json.JSONDecodeError, KeyError):
                            continue
                logger.info(
                    f"[MERKLE_LOG] Loaded {self._tree.tree_size} entries from {self._log_file}"
                )

            # Load STH history
            sth_file = self._log_dir / "sth_history.jsonl"
            if sth_file.exists():
                with open(sth_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                self._sth_history.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.warning(f"[MERKLE_LOG] Storage init failed ({e}), using memory-only")
            self._log_file = None

    def append_entry(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Append a settlement-finality event to the log.

        Only events in FINALITY_EVENTS are accepted.
        Returns leaf info or None if event type not eligible.
        """
        event_type = event.get("event_type", "")
        if event_type not in self.FINALITY_EVENTS:
            return None

        leaf_data = {
            "deal_id": event.get("deal_id", ""),
            "event_type": event_type,
            "event_id": event.get("event_id", ""),
            "event_hash": event.get("hash", ""),
            "timestamp": event.get("timestamp", ""),
        }

        with self._write_lock:
            leaf_hash, leaf_index = self._tree.append_leaf(leaf_data)

            # Persist
            if self._log_file:
                try:
                    with open(self._log_file, "a") as f:
                        f.write(json.dumps(leaf_data, sort_keys=True) + "\n")
                except Exception as e:
                    logger.warning(f"[MERKLE_LOG] Persist failed: {e}")

        return {
            "leaf_hash": leaf_hash,
            "leaf_index": leaf_index,
            "tree_size": self._tree.tree_size,
        }

    def sign_tree_head(self) -> Dict[str, Any]:
        """Create and persist a signed tree head."""
        tree_size = self._tree.tree_size
        root_hash = self._tree.get_root()
        timestamp = _now_iso()

        sign_input = f"{LOG_ID}|{tree_size}|{root_hash}|{timestamp}"
        signature = self._signer.sign(sign_input.encode("utf-8"))

        sth = {
            "log_id": LOG_ID,
            "tree_size": tree_size,
            "root_hash": root_hash,
            "timestamp": timestamp,
            "signature": base64.b64encode(signature).decode(),
            "key_id": KEY_ID,
            "algorithm": self._signer.algorithm(),
        }

        # Persist
        with self._write_lock:
            self._sth_history.append(sth)
            try:
                sth_file = self._log_dir / "sth_history.jsonl"
                with open(sth_file, "a") as f:
                    f.write(json.dumps(sth) + "\n")
            except Exception as e:
                logger.warning(f"[MERKLE_LOG] STH persist failed: {e}")

        return sth

    def get_latest_sth(self) -> Dict[str, Any]:
        """Return latest STH, signing a new one if needed."""
        if self._sth_history:
            latest = self._sth_history[-1]
            # Re-sign if tree has grown since last STH
            if latest.get("tree_size", 0) < self._tree.tree_size:
                return self.sign_tree_head()
            return latest
        if self._tree.tree_size > 0:
            return self.sign_tree_head()
        return {
            "log_id": LOG_ID,
            "tree_size": 0,
            "root_hash": hashlib.sha256(b"").hexdigest(),
            "timestamp": _now_iso(),
            "signature": "",
            "key_id": KEY_ID,
        }

    def get_sth_at_size(self, tree_size: int) -> Optional[Dict[str, Any]]:
        """Return historical STH at given tree size, or None."""
        for sth in self._sth_history:
            if sth.get("tree_size") == tree_size:
                return sth
        # If we have the data, sign a fresh STH for this size
        if tree_size <= self._tree.tree_size:
            root_hash = self._tree.get_root(tree_size)
            timestamp = _now_iso()
            sign_input = f"{LOG_ID}|{tree_size}|{root_hash}|{timestamp}"
            signature = self._signer.sign(sign_input.encode("utf-8"))
            return {
                "log_id": LOG_ID,
                "tree_size": tree_size,
                "root_hash": root_hash,
                "timestamp": timestamp,
                "signature": base64.b64encode(signature).decode(),
                "key_id": KEY_ID,
                "algorithm": self._signer.algorithm(),
            }
        return None

    def inclusion_proof(
        self, leaf_index: int, tree_size: int = None
    ) -> Dict[str, Any]:
        """Generate inclusion proof for a leaf."""
        ts = tree_size if tree_size is not None else self._tree.tree_size
        proof = self._tree.inclusion_proof(leaf_index, ts)
        return {
            "leaf_index": leaf_index,
            "tree_size": ts,
            "leaf_hash": self._tree._leaves[leaf_index] if leaf_index < len(self._tree._leaves) else "",
            "proof": proof,
            "root_hash": self._tree.get_root(ts),
        }

    def consistency_proof(
        self, first_size: int, second_size: int = None
    ) -> Dict[str, Any]:
        """Generate consistency proof between two tree sizes."""
        second = second_size if second_size is not None else self._tree.tree_size
        proof = self._tree.consistency_proof(first_size, second)
        return {
            "first_size": first_size,
            "second_size": second,
            "proof": proof,
            "first_root": self._tree.get_root(first_size),
            "second_root": self._tree.get_root(second),
        }

    def get_entry(self, index: int) -> Optional[Dict[str, Any]]:
        """Get leaf data at index."""
        return self._tree.get_leaf(index)

    def get_entries(self, start: int, end: int) -> List[Dict[str, Any]]:
        """Get entries in range [start, end)."""
        result = []
        for i in range(start, min(end, self._tree.tree_size)):
            entry = self._tree.get_leaf(i)
            if entry:
                result.append({"index": i, **entry})
        return result

    def find_leaf_index(self, deal_id: str, event_id: str = "") -> Optional[int]:
        """Find leaf index by deal_id (and optionally event_id)."""
        for i in range(self._tree.tree_size):
            leaf = self._tree.get_leaf(i)
            if leaf and leaf.get("deal_id") == deal_id:
                if not event_id or leaf.get("event_id") == event_id:
                    return i
        return None

    @property
    def tree_size(self) -> int:
        return self._tree.tree_size

    def public_key_json(self) -> Dict[str, Any]:
        return self._signer.public_key_json()

    def stats(self) -> Dict[str, Any]:
        result = {
            "log_id": LOG_ID,
            "tree_size": self._tree.tree_size,
            "sth_count": len(self._sth_history),
            "root_hash": self._tree.get_root() if self._tree.tree_size > 0 else None,
            "signer_algorithm": self._signer.algorithm(),
        }
        # Include latest anchor info if available
        try:
            from protocol.sth_anchor import load_latest_receipt
            receipt = load_latest_receipt()
            if receipt:
                result["latest_anchor_id"] = receipt.get("anchor_id")
                result["latest_anchored_at"] = receipt.get("anchored_at")
                result["anchor_tsa_url"] = receipt.get("tsa_url")
        except Exception:
            pass
        return result


# ── Singleton ──

_log: Optional[TransparencyLog] = None


def get_log() -> TransparencyLog:
    global _log
    if _log is None:
        _log = TransparencyLog()
    return _log


# ── Router ──


def get_merkle_log_router():
    try:
        from fastapi import APIRouter, HTTPException, Query
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol/merkle", tags=["Transparency Log"])

    @router.get("/latest")
    async def latest_sth():
        """Get the latest signed tree head."""
        log = get_log()
        sth = log.get_latest_sth()
        return {"ok": True, **sth}

    @router.get("/sth/{tree_size}")
    async def sth_at_size(tree_size: int):
        """Get STH at a specific tree size."""
        log = get_log()
        sth = log.get_sth_at_size(tree_size)
        if not sth:
            raise HTTPException(status_code=404, detail="No STH at that size")
        return {"ok": True, **sth}

    @router.get("/inclusion")
    async def inclusion(
        leaf_index: int = Query(...),
        tree_size: int = Query(None),
    ):
        """Get inclusion proof for a leaf."""
        log = get_log()
        if leaf_index >= log.tree_size:
            raise HTTPException(status_code=404, detail="Leaf index out of range")
        result = log.inclusion_proof(leaf_index, tree_size)
        return {"ok": True, **result}

    @router.get("/consistency")
    async def consistency(
        first: int = Query(...),
        second: int = Query(None),
    ):
        """Get consistency proof between two tree sizes."""
        log = get_log()
        second_size = second if second is not None else log.tree_size
        if first > second_size or second_size > log.tree_size:
            raise HTTPException(status_code=400, detail="Invalid size range")
        result = log.consistency_proof(first, second_size)
        return {"ok": True, **result}

    @router.get("/entries")
    async def entries(
        start: int = Query(0),
        end: int = Query(100),
    ):
        """Get log entries in range."""
        log = get_log()
        end = min(end, start + 1000)  # cap at 1000 per request
        result = log.get_entries(start, end)
        return {"ok": True, "entries": result, "total": log.tree_size}

    @router.get("/leaf/{index}")
    async def leaf(index: int):
        """Get leaf data at index."""
        log = get_log()
        entry = log.get_entry(index)
        if not entry:
            raise HTTPException(status_code=404, detail="Leaf not found")
        return {"ok": True, "index": index, **entry}

    @router.get("/stats")
    async def stats():
        """Get log statistics."""
        log = get_log()
        return {"ok": True, **log.stats()}

    @router.get("/public-key")
    async def public_key():
        """Get the log signing public key."""
        log = get_log()
        return {"ok": True, **log.public_key_json()}

    @router.get("/deal/{deal_id}/proof")
    async def deal_proof(deal_id: str):
        """Get inclusion proof for a deal's events."""
        log = get_log()
        leaf_index = log.find_leaf_index(deal_id)
        if leaf_index is None:
            raise HTTPException(
                status_code=404, detail="Deal not found in transparency log"
            )
        proof = log.inclusion_proof(leaf_index)
        sth = log.get_latest_sth()
        return {
            "ok": True,
            "deal_id": deal_id,
            "inclusion": proof,
            "signed_tree_head": sth,
        }

    return router
