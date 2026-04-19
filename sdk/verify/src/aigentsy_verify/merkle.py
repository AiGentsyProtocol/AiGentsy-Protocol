"""
RFC 6962 Merkle verification and Ed25519 STH signature verification.

All functions are standalone — no AiGentsy runtime imports.
Algorithms match protocol/merkle_log.py exactly.
"""

import base64
import hashlib
from typing import Any, Dict, List


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


# ── Inclusion Proof Verification ──


def _largest_power_of_2_less_than(n: int) -> int:
    if n <= 1:
        return 0
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def _verify_path(
    leaf_hash: str, leaf_index: int, lo: int, hi: int, proof_iter
) -> str:
    n = hi - lo
    if n == 1:
        return leaf_hash
    k = _largest_power_of_2_less_than(n)
    if leaf_index - lo < k:
        left = _verify_path(leaf_hash, leaf_index, lo, lo + k, proof_iter)
        right = next(proof_iter)
        return node_hash_hex(left, right)
    else:
        right = _verify_path(leaf_hash, leaf_index, lo + k, hi, proof_iter)
        left = next(proof_iter)
        return node_hash_hex(left, right)


def verify_inclusion(
    leaf_hash: str,
    leaf_index: int,
    tree_size: int,
    proof: List[str],
    expected_root: str,
) -> bool:
    """
    Verify an RFC 6962 Merkle inclusion proof offline.

    Args:
        leaf_hash: The leaf hash (hex string)
        leaf_index: Index of the leaf in the tree
        tree_size: Size of the tree when proof was generated
        proof: List of sibling hashes (hex strings) from leaf to root
        expected_root: Expected root hash (hex string)

    Returns:
        True if the proof is valid
    """
    if tree_size == 0 or leaf_index >= tree_size:
        return False

    proof_iter = iter(proof)
    try:
        computed = _verify_path(leaf_hash, leaf_index, 0, tree_size, proof_iter)
    except StopIteration:
        return False

    remaining = list(proof_iter)
    return computed == expected_root and len(remaining) == 0


# ── Consistency Proof Verification ──


def verify_consistency(
    old_size: int,
    new_size: int,
    old_root: str,
    new_root: str,
    proof: List[str],
) -> bool:
    """
    Verify an RFC 6962 Merkle consistency proof offline.

    Proves that the tree of old_size is a prefix of the tree of new_size,
    i.e., no leaves were changed — only new leaves were appended.

    Based on RFC 6962 Section 2.1.2 (Merkle Consistency Proof).

    Args:
        old_size: Tree size of the earlier STH
        new_size: Tree size of the later STH
        old_root: Root hash of the earlier tree (hex)
        new_root: Root hash of the later tree (hex)
        proof: Consistency proof hashes (hex strings)

    Returns:
        True if the consistency proof is valid
    """
    if old_size < 0 or new_size < 0:
        return False
    if old_size > new_size:
        return False
    if old_size == 0:
        return True  # Empty tree is consistent with everything
    if old_size == new_size:
        return old_root == new_root and len(proof) == 0

    # RFC 6962 consistency proof verification algorithm
    # Find the node that splits old_size and new_size
    proof_iter = iter(proof)

    # If old_size is a power of 2, the first proof element is NOT
    # used for the old root computation.
    is_power_of_2 = (old_size & (old_size - 1)) == 0

    try:
        if is_power_of_2:
            # Start from old_root
            old_hash = old_root
            new_hash = old_root
        else:
            first = next(proof_iter)
            old_hash = first
            new_hash = first

        # Walk from the split node up to both roots
        node = old_size - 1
        last_node = new_size - 1

        # Find the split point
        while node > 0 and (node & 1) == 1:
            sibling = next(proof_iter)
            old_hash = node_hash_hex(sibling, old_hash)
            new_hash = node_hash_hex(sibling, new_hash)
            node >>= 1
            last_node >>= 1

        while node > 0:
            sibling = next(proof_iter)
            old_hash = node_hash_hex(sibling, old_hash)
            node >>= 1
            last_node >>= 1

        # Continue building new_hash to the new root
        while last_node > 0:
            sibling = next(proof_iter)
            new_hash = node_hash_hex(new_hash, sibling)
            last_node >>= 1

    except StopIteration:
        return False

    # Verify no extra proof elements remain
    remaining = list(proof_iter)
    if remaining:
        return False

    return old_hash == old_root and new_hash == new_root


# ── STH Signature Verification ──


def verify_sth_signature(
    sth: Dict[str, Any],
    public_key_base64: str,
) -> bool:
    """
    Verify an Ed25519 signed tree head (STH) signature offline.

    The signature input format matches AiGentsy's LogSigner:
        "{log_id}|{tree_size}|{root_hash}|{timestamp}"

    Args:
        sth: Signed tree head dict with log_id, tree_size, root_hash,
             timestamp, signature, algorithm fields
        public_key_base64: Base64-encoded Ed25519 public key

    Returns:
        True if the signature is valid
    """
    algorithm = sth.get("algorithm", "Ed25519")
    if algorithm != "Ed25519":
        return False

    sign_input = (
        f"{sth.get('log_id', '')}|{sth.get('tree_size', 0)}"
        f"|{sth.get('root_hash', '')}|{sth.get('timestamp', '')}"
    )

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        signature = base64.b64decode(sth.get("signature", ""))
        raw_key = base64.b64decode(public_key_base64)
        pub_key = Ed25519PublicKey.from_public_bytes(raw_key)
        pub_key.verify(signature, sign_input.encode("utf-8"))
        return True
    except Exception:
        return False
