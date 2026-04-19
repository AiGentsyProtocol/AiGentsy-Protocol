"""VerifierSession — shared-state verifier for batch bundle verification.

Caches policy-snapshot verification across bundles signed under the
same policy. Reduces redundant Ed25519 signature checks when verifying
many bundles in sequence.

Usage:
    from aigentsy_verify import VerifierSession

    session = VerifierSession()
    for bundle in bundles:
        result = session.verify_bundle(bundle)

Backward compatible: existing verify_bundle() is unchanged.
"""

from collections import OrderedDict
from typing import Any, Dict, Optional

from .bundle import verify_bundle as _verify_bundle_standalone


class VerifierSession:
    """Batch-optimized bundle verifier with policy-snapshot caching.

    Maintains an LRU cache of verified policy snapshot hashes. When a
    bundle references a previously-verified snapshot, the snapshot-level
    signature check is skipped (the bundle's binding to the snapshot is
    still verified).
    """

    def __init__(self, max_cached_snapshots: int = 100):
        self._snapshot_cache: OrderedDict[str, bool] = OrderedDict()
        self._max = max_cached_snapshots
        self._total = 0
        self._snapshot_hits = 0
        self._snapshots_cached = 0
        self._sig_verifications_avoided = 0

    def verify_bundle(
        self,
        bundle: Dict[str, Any],
        public_key_b64: str = "",
        sth: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Verify a bundle, reusing cached policy-snapshot verification."""
        self._total += 1

        # Check if the STH (signed tree head) has been verified before
        sth_to_check = sth or bundle.get("signed_tree_head")
        sth_cache_key = None
        if sth_to_check:
            sig = sth_to_check.get("signature", "")
            root = sth_to_check.get("root_hash", "")
            sth_cache_key = f"{sig}:{root}"

        if sth_cache_key and sth_cache_key in self._snapshot_cache:
            self._snapshot_hits += 1
            self._sig_verifications_avoided += 1
            # Run verification but skip STH signature check by not
            # passing the STH — the bundle hash, event chain, merkle
            # inclusion, and cross-reference are still verified.
            result = _verify_bundle_standalone(bundle, public_key_b64, sth=None)
            # Restore the STH step result from cache
            result["steps"]["sth_signature"] = {
                "passed": True,
                "skipped": False,
                "cached": True,
            }
            # Re-evaluate overall verdict with cached STH pass
            mandatory = ["bundle_hash", "event_chain"]
            optional = ["merkle_inclusion", "sth_signature", "cross_reference"]
            mandatory_pass = all(
                result["steps"].get(s, {}).get("passed", False)
                for s in mandatory
            )
            optional_pass = all(
                result["steps"].get(s, {}).get("passed", False)
                or result["steps"].get(s, {}).get("skipped", False)
                or result["steps"].get(s, {}).get("cached", False)
                for s in optional
            )
            result["verified"] = mandatory_pass and optional_pass
            return result

        # Full verification
        result = _verify_bundle_standalone(bundle, public_key_b64, sth=sth_to_check)

        # Cache the STH verification result if it passed
        if sth_cache_key and result["steps"].get("sth_signature", {}).get("passed"):
            if sth_cache_key not in self._snapshot_cache:
                self._snapshots_cached += 1
            self._snapshot_cache[sth_cache_key] = True
            if len(self._snapshot_cache) > self._max:
                self._snapshot_cache.popitem(last=False)

        return result

    def metrics(self) -> Dict[str, Any]:
        return {
            "total_bundles_verified": self._total,
            "snapshots_cached": self._snapshots_cached,
            "snapshots_served_from_cache": self._snapshot_hits,
            "signature_chain_verifications_avoided": self._sig_verifications_avoided,
            "snapshot_cache_size": len(self._snapshot_cache),
            "hit_rate": round(self._snapshot_hits / max(1, self._total), 4),
        }

    def stats(self) -> Dict[str, Any]:
        return self.metrics()
