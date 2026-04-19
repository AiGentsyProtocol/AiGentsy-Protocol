"""
Idempotency Framework — exactly-once effects
==============================================

Cross-cutting primitive that ensures any operation keyed by an
idempotency key executes at most once. Retries return the stored result.

Usage:
    from protocol.idempotency import run_idempotent, idempotency_key

    key = idempotency_key(deal_id, "settle", amount=100.0)
    result = await run_idempotent(key, settle_fn, amount=100.0)
    # Second call with same key → returns stored result, no re-execution

Storage: Redis-first with file fallback (set IDEMPOTENCY_REDIS_URL for Redis).
Falls back to in-memory if filesystem also unavailable.
"""

import asyncio
import hashlib
import inspect
import json
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from storage_root import get_data_root

logger = logging.getLogger(__name__)

# ── Storage ──

_STORE_DIR = os.getenv("IDEMPOTENCY_STORE_DIR", str(get_data_root() / "idempotency"))
_MAX_MEMORY_CACHE = 100_000


class IdempotencyStore:
    """
    Persistent + in-memory idempotency store.

    Delegates to a LockBackend:
      - RedisLockBackend (if IDEMPOTENCY_REDIS_URL is set) — multi-process safe
      - FileLockBackend (default) — single-process safe, JSONL persistence

    Thread-safe atomic claim via claim_or_get() — prevents
    double-click / concurrent-request duplicate creation.
    """

    def __init__(self, store_dir: str = _STORE_DIR):
        from protocol.lock_backend import create_lock_backend
        self._backend = create_lock_backend(store_dir)

    def has(self, key: str) -> bool:
        return self._backend.has(key)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._backend.get(key)

    def put(self, key: str, result: Any, metadata: Dict[str, Any] = None):
        self._backend.put(key, result, metadata)

    def claim_or_get(self, key: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Atomic claim: returns (claimed, existing_entry).

        If key is unclaimed:
          - Inserts a sentinel {"_claimed": True, "_claimed_at": ...}
          - Returns (True, None) — caller owns this key and should proceed
        If key is already claimed or completed:
          - Returns (False, existing_entry) — caller must NOT proceed

        Multi-process safe when using Redis backend.
        Single-process safe when using file backend.
        """
        return self._backend.claim_or_get(key)

    def stats(self) -> Dict[str, Any]:
        return self._backend.stats()

    def cleanup_expired(self) -> Dict[str, Any]:
        """Remove completed idempotency entries older than the configured TTL."""
        if hasattr(self._backend, "cleanup_expired"):
            return self._backend.cleanup_expired()
        return {"note": "cleanup not supported by this backend"}


# Module-level singleton
_store: Optional[IdempotencyStore] = None


def get_idempotency_store() -> IdempotencyStore:
    global _store
    if _store is None:
        _store = IdempotencyStore()
    return _store


# ── Key Generation ──

def idempotency_key(deal_id: str, action: str, **params) -> str:
    """
    Generate a deterministic idempotency key.

    Key = SHA-256 of (deal_id, action, sorted params).
    Same inputs always produce the same key.
    """
    canonical = json.dumps({
        "deal_id": deal_id,
        "action": action,
        **{k: str(v) for k, v in sorted(params.items())},
    }, sort_keys=True)
    return f"idem_{hashlib.sha256(canonical.encode()).hexdigest()[:24]}"


# ── Core Primitive ──

async def run_idempotent(
    key: str,
    fn: Callable,
    *args,
    _metadata: Dict[str, Any] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Execute fn exactly once for this key.

    If key was already seen:
      - Return stored result with {"_idempotent": True, "_original_key": key}
    If key is new:
      - Execute fn(*args, **kwargs)
      - Store result
      - Return result with {"_idempotent": False}

    Works with both sync and async functions.
    """
    store = get_idempotency_store()

    # Check for existing result
    existing = store.get(key)
    if existing is not None:
        result = existing.get("result", {})
        if isinstance(result, dict):
            result["_idempotent"] = True
            result["_original_key"] = key
            result["_original_at"] = existing.get("stored_at")
        logger.info(f"[IDEMPOTENCY] Key {key[:20]}... already seen, returning stored result")
        return result

    # Execute function
    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(*args, **kwargs)
        else:
            result = fn(*args, **kwargs)
    except Exception as e:
        # Do NOT store failures — allow retry
        logger.warning(f"[IDEMPOTENCY] Execution failed for {key[:20]}...: {e}")
        raise

    # Store successful result
    store.put(key, result, metadata=_metadata)

    if isinstance(result, dict):
        result["_idempotent"] = False

    return result


def run_idempotent_sync(
    key: str,
    fn: Callable,
    *args,
    _metadata: Dict[str, Any] = None,
    **kwargs,
) -> Any:
    """Synchronous version of run_idempotent."""
    store = get_idempotency_store()

    existing = store.get(key)
    if existing is not None:
        result = existing.get("result", {})
        if isinstance(result, dict):
            result["_idempotent"] = True
            result["_original_key"] = key
        return result

    result = fn(*args, **kwargs)
    store.put(key, result, metadata=_metadata)

    if isinstance(result, dict):
        result["_idempotent"] = False

    return result
