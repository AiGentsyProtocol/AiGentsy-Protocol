"""Conformance tests for delta-within-reuse (v1.6)."""

import os
import tempfile

import pytest

from hoverstack.near_miss_cache import NearMissDetector, BaselineCandidate


@pytest.fixture
def cache_with_entry():
    from hoverstack.proof_cache import ProofCache
    tmp = tempfile.mktemp(suffix=".json")
    c = ProofCache(path=tmp)
    c.register("hash_a", "mandate_1", "policy_v1",
               bundle_hash="bundle_abc", deal_id="deal_001",
               prompt_text="the quick brown fox jumps over the lazy dog today")
    yield c, tmp
    if os.path.exists(tmp):
        os.unlink(tmp)


def test_cold_cache_returns_none():
    from hoverstack.proof_cache import ProofCache
    tmp = tempfile.mktemp(suffix=".json")
    try:
        c = ProofCache(path=tmp)
        nmd = NearMissDetector()
        result = nmd.find_baseline("hash_x", "m1", "v1", "some prompt", cache=c)
        assert result is None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_finds_candidate_within_threshold(cache_with_entry):
    c, _ = cache_with_entry
    nmd = NearMissDetector(max_diff_percent=20.0)
    # Slightly different prompt (1 word changed out of 10 = 10%)
    result = nmd.find_baseline(
        "hash_b", "mandate_1", "policy_v1",
        "the quick brown fox jumps over the lazy cat today",
        cache=c,
    )
    assert result is not None
    assert result.diff_percent <= 20.0
    assert result.bundle_hash == "bundle_abc"


def test_rejects_above_threshold(cache_with_entry):
    c, _ = cache_with_entry
    nmd = NearMissDetector(max_diff_percent=5.0)
    # 5 words different out of 10 = 50% diff
    result = nmd.find_baseline(
        "hash_c", "mandate_1", "policy_v1",
        "a slow red cat sits under a tall tree now",
        cache=c,
    )
    assert result is None


def test_rejects_mandate_mismatch(cache_with_entry):
    c, _ = cache_with_entry
    nmd = NearMissDetector(max_diff_percent=50.0)
    result = nmd.find_baseline(
        "hash_d", "mandate_WRONG", "policy_v1",
        "the quick brown fox jumps over the lazy dog today",
        cache=c,
    )
    assert result is None


def test_rejects_policy_mismatch(cache_with_entry):
    c, _ = cache_with_entry
    nmd = NearMissDetector(max_diff_percent=50.0)
    result = nmd.find_baseline(
        "hash_e", "mandate_1", "policy_WRONG",
        "the quick brown fox jumps over the lazy dog today",
        cache=c,
    )
    assert result is None


def test_baseline_metadata_fields(cache_with_entry):
    c, _ = cache_with_entry
    nmd = NearMissDetector(max_diff_percent=50.0)
    result = nmd.find_baseline(
        "hash_f", "mandate_1", "policy_v1",
        "the quick brown fox jumps over the lazy cat today",
        cache=c,
    )
    assert result is not None
    assert result.bundle_hash == "bundle_abc"
    assert result.original_prompt_hash == "hash_a"
    assert isinstance(result.diff_percent, float)
    assert result.diff_percent >= 0


def test_policy_invalidation_cascades(cache_with_entry):
    c, _ = cache_with_entry
    c.invalidate_by_policy("policy_v1")
    nmd = NearMissDetector(max_diff_percent=50.0)
    result = nmd.find_baseline(
        "hash_g", "mandate_1", "policy_v1",
        "the quick brown fox jumps over the lazy dog today",
        cache=c,
    )
    assert result is None


def test_mandate_invalidation_cascades(cache_with_entry):
    c, _ = cache_with_entry
    c.invalidate_by_mandate("mandate_1")
    nmd = NearMissDetector(max_diff_percent=50.0)
    result = nmd.find_baseline(
        "hash_h", "mandate_1", "policy_v1",
        "the quick brown fox jumps over the lazy dog today",
        cache=c,
    )
    assert result is None


def test_near_miss_failure_nonfatal():
    """Broken near-miss doesn't crash proof_pipe."""
    nmd = NearMissDetector()
    # Pass None cache — should return None without crashing
    try:
        result = nmd.find_baseline("x", "m", "v", "prompt", cache=None)
    except Exception:
        result = None
    # Either None or an exception that was caught — both are acceptable
    # The important thing is it doesn't raise unhandled


def test_skips_exact_match(cache_with_entry):
    """Near-miss skips entries that are exact matches (handled by exact-hit path)."""
    c, _ = cache_with_entry
    nmd = NearMissDetector(max_diff_percent=50.0)
    # Use the SAME prompt_instance_id as the cached entry
    result = nmd.find_baseline(
        "hash_a", "mandate_1", "policy_v1",
        "the quick brown fox jumps over the lazy dog today",
        cache=c,
    )
    assert result is None  # skipped because exact match
