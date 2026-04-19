"""
Lock Backend — Distributed Idempotency Primitives
===================================================

Provides a LockBackend ABC with two implementations:
  - RedisLockBackend: SETNX-based distributed lock (multi-process safe)
  - FileLockBackend: JSONL + threading.Lock (single-process, existing behavior)

The IdempotencyStore delegates to whichever backend is available.
Redis is tried first (if IDEMPOTENCY_REDIS_URL is set); file is the fallback.
"""

import hashlib
import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_MAX_MEMORY_CACHE = 100_000


class LockBackend(ABC):
    """Abstract lock backend for idempotency claims."""

    @abstractmethod
    def claim_or_get(self, key: str, ttl_seconds: int = 300) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Atomic claim. Returns (claimed, existing_entry).

        If key is unclaimed:
          - Inserts a sentinel
          - Returns (True, None) — caller owns this key
        If key already exists:
          - Returns (False, existing_entry)
        """
        ...

    @abstractmethod
    def put(self, key: str, result: Any, metadata: Dict[str, Any] = None) -> None:
        """Store completed result for key (overwrites sentinel)."""
        ...

    @abstractmethod
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored entry for key."""
        ...

    @abstractmethod
    def has(self, key: str) -> bool:
        """Check if key exists."""
        ...

    @abstractmethod
    def stats(self) -> Dict[str, Any]:
        """Return backend statistics."""
        ...


# ── Redis Backend ──

class RedisLockBackend(LockBackend):
    """
    Redis SETNX-based distributed lock.

    claim_or_get uses SET key sentinel NX EX ttl.
    put stores JSON result with no expiry (permanent).
    Connection errors raise — caller handles fallback.
    """

    def __init__(self, redis_url: str, prefix: str = "idem:"):
        self._prefix = prefix
        self._redis = None
        try:
            import redis as redis_lib
            self._redis = redis_lib.from_url(redis_url, decode_responses=True)
            self._redis.ping()
            logger.info(f"[LOCK] Redis backend connected: {redis_url[:30]}...")
        except Exception as e:
            logger.warning(f"[LOCK] Redis connection failed: {e}")
            self._redis = None
            raise

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def claim_or_get(self, key: str, ttl_seconds: int = 300) -> Tuple[bool, Optional[Dict[str, Any]]]:
        rk = self._key(key)
        sentinel = json.dumps({
            "key": key,
            "_claimed": True,
            "_claimed_at": datetime.now(timezone.utc).isoformat(),
        })
        # SETNX with TTL — atomic claim
        claimed = self._redis.set(rk, sentinel, nx=True, ex=ttl_seconds)
        if claimed:
            return (True, None)
        # Key exists — fetch stored value
        raw = self._redis.get(rk)
        if raw:
            try:
                return (False, json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                return (False, {"_raw": raw})
        return (False, None)

    # TTL for completed results (24 hours)
    _RESULT_TTL = int(os.getenv("IDEMPOTENCY_RESULT_TTL", "86400"))

    def put(self, key: str, result: Any, metadata: Dict[str, Any] = None) -> None:
        entry = {
            "key": key,
            "result": result,
            "metadata": metadata or {},
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }
        # Overwrite sentinel with completed result + TTL (default 24h)
        self._redis.set(self._key(key), json.dumps(entry, default=str), ex=self._RESULT_TTL)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        raw = self._redis.get(self._key(key))
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def has(self, key: str) -> bool:
        return bool(self._redis.exists(self._key(key)))

    def stats(self) -> Dict[str, Any]:
        try:
            info = self._redis.info("keyspace")
            db_info = info.get("db0", {})
            key_count = db_info.get("keys", 0) if isinstance(db_info, dict) else 0
        except Exception:
            key_count = -1
        return {
            "backend": "redis",
            "prefix": self._prefix,
            "keys_estimated": key_count,
        }


# ── File Backend ──

class FileLockBackend(LockBackend):
    """
    File-backed idempotency with threading.Lock.

    This is the existing behavior extracted from IdempotencyStore:
    JSONL append log + OrderedDict in-memory cache.
    Single-process safe only.
    """

    def __init__(self, store_dir: str = ""):
        from storage_root import get_data_root
        if not store_dir:
            store_dir = str(get_data_root() / "idempotency")
        self._memory: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._store_file: Optional[Path] = None
        self._lock = threading.Lock()
        try:
            path = Path(store_dir)
            path.mkdir(parents=True, exist_ok=True)
            self._store_file = path / "idempotency_log.jsonl"
            if self._store_file.exists():
                with open(self._store_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            self._memory[entry["key"]] = entry
                        except (json.JSONDecodeError, KeyError):
                            continue
                logger.info(f"[LOCK] File backend loaded {len(self._memory)} keys from {self._store_file}")
        except Exception as e:
            logger.warning(f"[LOCK] File store init failed ({e}), using memory-only")
            self._store_file = None

    def claim_or_get(self, key: str, ttl_seconds: int = 300) -> Tuple[bool, Optional[Dict[str, Any]]]:
        with self._lock:
            existing = self._memory.get(key)
            if existing is not None:
                # TTL expiration: if sentinel (claimed but never completed) is older
                # than ttl_seconds, treat as expired and reclaim
                if existing.get("_claimed") and "result" not in existing:
                    claimed_at = existing.get("_claimed_at", "")
                    try:
                        ts = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
                        age = (datetime.now(timezone.utc) - ts).total_seconds()
                        if age > ttl_seconds:
                            logger.info(f"[LOCK] Expired sentinel for {key} (age={age:.0f}s > ttl={ttl_seconds}s)")
                            sentinel = {
                                "key": key,
                                "_claimed": True,
                                "_claimed_at": datetime.now(timezone.utc).isoformat(),
                            }
                            self._memory[key] = sentinel
                            return (True, None)
                    except Exception:
                        pass
                return (False, existing)
            sentinel = {
                "key": key,
                "_claimed": True,
                "_claimed_at": datetime.now(timezone.utc).isoformat(),
            }
            self._memory[key] = sentinel
            return (True, None)

    def release(self, key: str) -> bool:
        """Explicitly release a claimed key (for crash recovery)."""
        with self._lock:
            existing = self._memory.get(key)
            if existing and existing.get("_claimed") and "result" not in existing:
                del self._memory[key]
                return True
            return False

    def put(self, key: str, result: Any, metadata: Dict[str, Any] = None) -> None:
        entry = {
            "key": key,
            "result": result,
            "metadata": metadata or {},
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._memory[key] = entry
            # Evict oldest if over limit
            while len(self._memory) > _MAX_MEMORY_CACHE:
                self._memory.popitem(last=False)
        # Persist to disk
        if self._store_file:
            try:
                with open(self._store_file, "a") as f:
                    f.write(json.dumps(entry, default=str) + "\n")
            except Exception as e:
                logger.warning(f"[LOCK] Persist failed: {e}")

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._memory.get(key)

    def has(self, key: str) -> bool:
        return key in self._memory

    # TTL for completed results (default 24 hours)
    _RESULT_TTL = int(os.getenv("IDEMPOTENCY_RESULT_TTL", "86400"))

    def cleanup_expired(self) -> Dict[str, Any]:
        """
        Remove completed idempotency entries older than _RESULT_TTL seconds.
        Returns cleanup stats.
        """
        now = datetime.now(timezone.utc)
        expired_keys = []

        with self._lock:
            for key, entry in list(self._memory.items()):
                stored_at = entry.get("stored_at", "")
                if not stored_at or entry.get("_claimed"):
                    continue  # Skip sentinels (handled by claim_or_get TTL)
                try:
                    ts = datetime.fromisoformat(stored_at.replace("Z", "+00:00"))
                    age = (now - ts).total_seconds()
                    if age > self._RESULT_TTL:
                        expired_keys.append(key)
                except Exception:
                    continue

            for key in expired_keys:
                del self._memory[key]

        # Rewrite JSONL without expired entries
        if expired_keys and self._store_file:
            try:
                remaining = [
                    json.dumps(entry, default=str)
                    for entry in self._memory.values()
                ]
                with open(self._store_file, "w") as f:
                    for line in remaining:
                        f.write(line + "\n")
            except Exception as e:
                logger.warning(f"[LOCK] Cleanup persist failed: {e}")

        return {"expired": len(expired_keys), "remaining": len(self._memory)}

    def stats(self) -> Dict[str, Any]:
        return {
            "backend": "file",
            "keys_cached": len(self._memory),
            "persistent": self._store_file is not None,
            "store_file": str(self._store_file) if self._store_file else None,
        }


# ── Factory ──

def create_lock_backend(store_dir: str = "") -> LockBackend:
    """
    Create the best available lock backend.

    Tries Redis first (if IDEMPOTENCY_REDIS_URL is set),
    falls back to file-based backend.
    """
    redis_url = os.getenv("IDEMPOTENCY_REDIS_URL", "")
    if redis_url:
        try:
            backend = RedisLockBackend(redis_url)
            logger.info("[LOCK] Using Redis lock backend")
            return backend
        except Exception as e:
            logger.warning(f"[LOCK] Redis unavailable ({e}), falling back to file backend")

    backend = FileLockBackend(store_dir)
    logger.info("[LOCK] Using file lock backend")
    return backend
