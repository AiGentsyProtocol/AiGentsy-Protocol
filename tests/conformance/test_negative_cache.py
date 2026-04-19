"""Conformance tests for negative proof cache (refusal caching)."""

import os
import tempfile
import threading

import pytest


@pytest.fixture
def cache():
    from hoverstack.negative_cache import RefusalCache
    tmp = tempfile.mktemp(suffix=".json")
    c = RefusalCache(path=tmp)
    yield c
    if os.path.exists(tmp):
        os.unlink(tmp)


def test_miss_then_register_then_hit(cache):
    assert cache.lookup("p1", "m1", "v1") is None
    cache.register("p1", "m1", "v1", refusal_type="policy_violation", reason="blocked by policy")
    hit = cache.lookup("p1", "m1", "v1")
    assert hit is not None
    assert hit.refusal_type == "policy_violation"
    assert hit.reason == "blocked by policy"
    assert hit.valid is True


def test_policy_invalidation(cache):
    cache.register("p1", "m1", "v1", refusal_type="risk_exceeded")
    cache.register("p2", "m2", "v1", refusal_type="policy_violation")
    cache.register("p3", "m3", "v2", refusal_type="other")

    count = cache.invalidate_by_policy("v1")
    assert count == 2
    assert cache.lookup("p1", "m1", "v1") is None
    assert cache.lookup("p2", "m2", "v1") is None
    assert cache.lookup("p3", "m3", "v2") is not None


def test_mandate_invalidation(cache):
    cache.register("p1", "m1", "v1", refusal_type="mandate_out_of_scope")
    cache.register("p2", "m2", "v1", refusal_type="policy_violation")

    count = cache.invalidate_by_mandate("m1")
    assert count == 1
    assert cache.lookup("p1", "m1", "v1") is None
    assert cache.lookup("p2", "m2", "v1") is not None


def test_refusal_does_not_invoke_compute():
    """Cached refusal returns without compute invocation."""
    from hoverstack.negative_cache import RefusalCache
    tmp = tempfile.mktemp(suffix=".json")
    try:
        c = RefusalCache(path=tmp)
        c.register("content_x", "mandate_x", "policy_x",
                   refusal_type="risk_exceeded", reason="too risky")
        hit = c.lookup("content_x", "mandate_x", "policy_x")
        assert hit is not None
        assert hit.refusal_hash
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_persistence_roundtrip():
    from hoverstack.negative_cache import RefusalCache
    tmp = tempfile.mktemp(suffix=".json")
    try:
        c1 = RefusalCache(path=tmp)
        c1.register("p1", "m1", "v1", refusal_type="policy_violation")
        c2 = RefusalCache(path=tmp)
        assert c2.lookup("p1", "m1", "v1") is not None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_threading_correctness(cache):
    cache.register("shared", "mandate", "policy", refusal_type="risk_exceeded")
    results = []
    errors = []

    def worker():
        try:
            hit = cache.lookup("shared", "mandate", "policy")
            results.append(hit is not None and hit.refusal_type == "risk_exceeded")
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert all(results)


def test_refusal_metadata_fields(cache):
    cache.register("p1", "m1", "v1", refusal_type="mandate_out_of_scope", reason="scope too narrow")
    hit = cache.lookup("p1", "m1", "v1")
    assert hit.refusal_hash
    assert hit.triple_hash
    assert hit.refusal_type == "mandate_out_of_scope"
    assert hit.reason == "scope too narrow"
    assert hit.mandate_id == "m1"
    assert hit.policy_version == "v1"


def test_stats_breakdown(cache):
    cache.register("p1", "m1", "v1", refusal_type="policy_violation")
    cache.register("p2", "m2", "v1", refusal_type="risk_exceeded")
    cache.register("p3", "m3", "v1", refusal_type="risk_exceeded")
    stats = cache.stats()
    assert stats["size"] == 3
    assert stats["valid_entries"] == 3
    assert stats["refusal_type_breakdown"]["risk_exceeded"] == 2
    assert stats["refusal_type_breakdown"]["policy_violation"] == 1
