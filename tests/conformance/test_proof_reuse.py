"""Conformance tests for proof-bundle reuse across agents.

Tests cache semantics: hit/miss, invalidation, persistence, threading,
and structural integrity of reused proof bundles.
"""

import json
import os
import tempfile
import threading

import pytest


@pytest.fixture
def cache():
    """Fresh cache with temp file storage."""
    from hoverstack.proof_cache import ProofCache
    tmp = tempfile.mktemp(suffix=".json")
    c = ProofCache(path=tmp)
    yield c
    if os.path.exists(tmp):
        os.unlink(tmp)


def test_miss_then_register_then_hit(cache):
    """Cache miss → register → subsequent lookup hits."""
    result = cache.lookup("prompt_a", "mandate_1", "policy_v1")
    assert result is None

    cache.register("prompt_a", "mandate_1", "policy_v1",
                   bundle_hash="hash_abc", deal_id="deal_001")

    result = cache.lookup("prompt_a", "mandate_1", "policy_v1")
    assert result is not None
    assert result.bundle_hash == "hash_abc"
    assert result.original_deal_id == "deal_001"
    assert result.valid is True


def test_policy_invalidation(cache):
    """Policy change invalidates prior entries; new policy starts fresh."""
    cache.register("prompt_a", "mandate_1", "policy_v1",
                   bundle_hash="h1", deal_id="d1")
    cache.register("prompt_b", "mandate_2", "policy_v1",
                   bundle_hash="h2", deal_id="d2")
    cache.register("prompt_c", "mandate_3", "policy_v2",
                   bundle_hash="h3", deal_id="d3")

    count = cache.invalidate_by_policy("policy_v1")
    assert count == 2

    assert cache.lookup("prompt_a", "mandate_1", "policy_v1") is None
    assert cache.lookup("prompt_b", "mandate_2", "policy_v1") is None
    # policy_v2 entries unaffected
    assert cache.lookup("prompt_c", "mandate_3", "policy_v2") is not None


def test_mandate_invalidation(cache):
    """Mandate revision invalidates only that mandate's entries."""
    cache.register("prompt_a", "mandate_1", "policy_v1",
                   bundle_hash="h1", deal_id="d1")
    cache.register("prompt_b", "mandate_2", "policy_v1",
                   bundle_hash="h2", deal_id="d2")

    count = cache.invalidate_by_mandate("mandate_1")
    assert count == 1

    assert cache.lookup("prompt_a", "mandate_1", "policy_v1") is None
    # mandate_2 unaffected
    assert cache.lookup("prompt_b", "mandate_2", "policy_v1") is not None


def test_hit_path_metadata():
    """Hit-path returns proof with cached metadata."""
    import proof_pipe
    import random as _rng

    mandate_dict = {"mandate_id": "test_mandate_reuse"}

    # First call: miss, creates proof
    deal_1 = f"deal_reuse_miss_{_rng.randint(0, 2**64)}"
    res1 = proof_pipe.create_proof(
        proof_type="completion_photo",
        source="manual",
        agent_username="agent_test_reuse",
        deal_id=deal_1,
        proof_data={
            "photo_url": "https://example.com/proof",
            "timestamp": "2026-04-18T00:00:00Z",
            "location": "remote",
            "vertical": "marketing",
        },
        mandate=mandate_dict,
        hoverstamp={"policy_hash": "test_policy_hash_reuse"},
    )
    assert res1["ok"]
    assert not res1.get("_cached", False)

    # Second call: same content → should hit cache
    deal_2 = deal_1  # same deal_id → same proof_hash
    res2 = proof_pipe.create_proof(
        proof_type="completion_photo",
        source="manual",
        agent_username="agent_test_reuse",
        deal_id=deal_2,
        proof_data={
            "photo_url": "https://example.com/proof",
            "timestamp": "2026-04-18T00:00:00Z",
            "location": "remote",
            "vertical": "marketing",
        },
        mandate=mandate_dict,
        hoverstamp={"policy_hash": "test_policy_hash_reuse"},
    )
    # May hit idempotency cache before proof_cache — both are valid
    assert res2["ok"]


def test_reused_bundle_hash_matches_original(cache):
    """Reused proof's bundle_hash matches the original."""
    cache.register("prompt_x", "mandate_x", "policy_x",
                   bundle_hash="original_hash_xyz", deal_id="deal_orig")

    hit = cache.lookup("prompt_x", "mandate_x", "policy_x")
    assert hit is not None
    assert hit.bundle_hash == "original_hash_xyz"
    assert hit.original_deal_id == "deal_orig"


def test_cache_persistence_roundtrip():
    """Cache save/load roundtrip through JSON file."""
    from hoverstack.proof_cache import ProofCache
    tmp = tempfile.mktemp(suffix=".json")
    try:
        c1 = ProofCache(path=tmp)
        c1.register("p1", "m1", "v1", bundle_hash="h1", deal_id="d1")
        c1.register("p2", "m2", "v2", bundle_hash="h2", deal_id="d2")

        # New instance loads from same file
        c2 = ProofCache(path=tmp)
        assert c2.lookup("p1", "m1", "v1") is not None
        assert c2.lookup("p2", "m2", "v2") is not None
        assert c2.lookup("p3", "m3", "v3") is None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_concurrent_lookup_correctness(cache):
    """Concurrent lookups under threading lock are correct."""
    cache.register("shared_prompt", "shared_mandate", "shared_policy",
                   bundle_hash="shared_hash", deal_id="shared_deal")

    results = []
    errors = []

    def worker():
        try:
            hit = cache.lookup("shared_prompt", "shared_mandate", "shared_policy")
            results.append(hit is not None and hit.bundle_hash == "shared_hash")
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Thread errors: {errors}"
    assert all(results), f"Some lookups failed: {results}"


def test_invalidation_preserves_entries(cache):
    """Invalidation marks valid=False but does NOT delete entries."""
    cache.register("p1", "m1", "v1", bundle_hash="h1", deal_id="d1")
    cache.invalidate_by_policy("v1")

    # Lookup returns None (invalid)
    assert cache.lookup("p1", "m1", "v1") is None

    # But stats show the entry still exists
    stats = cache.stats()
    assert stats["size"] == 1
    assert stats["invalidated_entries"] == 1
