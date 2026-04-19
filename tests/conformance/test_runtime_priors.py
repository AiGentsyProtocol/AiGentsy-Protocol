"""Unit tests for RuntimePriors.

Covers:
    - empty priors return zero / cold-default estimates
    - EWMA converges on stable observations
    - load/save round-trip preserves state
    - keying by runtime_name isolates priors across venues
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from hoverstack.runtime_priors import (
    PreservationOutcome,
    RuntimePriors,
    _RUNTIME_COLD_DEFAULTS,
)


def _obs(shape, runtime, **kw):
    defaults = dict(
        was_preserved=True, was_reused=False,
        prefill_tokens_avoided=0, queue_ms_saved=0.0,
        residency_waves=0, estimated_kv_bytes=0,
    )
    defaults.update(kw)
    return PreservationOutcome(shape_id=shape, runtime_name=runtime, **defaults)


def test_empty_priors_return_zero_payoff():
    p = RuntimePriors()
    assert p.has_observations("s1", "vllm") is False
    assert p.payoff_ms_estimate("s1", "vllm") == 0.0
    assert p.net_value_estimate_ms("s1", "vllm", expected_reuses=3) == 0.0
    assert p.reuse_probability("s1", "vllm") == 0.0


def test_empty_priors_return_conservative_carry():
    p = RuntimePriors()
    assert p.carry_units_estimate("s1", "vllm") == _RUNTIME_COLD_DEFAULTS["vllm"]["carry_units_per_wave"]
    assert p.carry_units_estimate("s1", "unknown_runtime") == _RUNTIME_COLD_DEFAULTS["default"]["carry_units_per_wave"]


def test_ewma_converges_on_stable_observations():
    p = RuntimePriors()
    for _ in range(60):
        p.observe(_obs("s1", "vllm", was_preserved=True, was_reused=True,
                       prefill_tokens_avoided=400, queue_ms_saved=5.0,
                       estimated_kv_bytes=100_000))
    # After > 2 half-lives, EWMA should be within ~1% of the stable value.
    assert p.has_observations("s1", "vllm")
    payoff = p.payoff_ms_estimate("s1", "vllm")
    expected_prefill_ms = 400 * _RUNTIME_COLD_DEFAULTS["vllm"]["prefill_ms_per_token"]
    assert abs(payoff - (expected_prefill_ms + 5.0)) / (expected_prefill_ms + 5.0) < 0.05


def test_reuse_probability_tracks_real_rate():
    p = RuntimePriors()
    # 10 preserved, 3 reused
    for i in range(10):
        p.observe(_obs("s1", "vllm", was_preserved=True, was_reused=(i < 3)))
    assert p.reuse_probability("s1", "vllm") == pytest.approx(0.3)


def test_net_value_positive_when_payoff_exceeds_carry():
    p = RuntimePriors()
    for _ in range(40):
        p.observe(_obs("s1", "vllm", was_preserved=True, was_reused=True,
                       prefill_tokens_avoided=1000, estimated_kv_bytes=10_000))
    nv = p.net_value_estimate_ms("s1", "vllm", expected_reuses=3)
    assert nv > 0, f"expected net_value > 0 for profitable workload, got {nv}"


def test_net_value_non_positive_when_no_reuse_observed():
    p = RuntimePriors()
    for _ in range(40):
        p.observe(_obs("s1", "vllm", was_preserved=True, was_reused=False,
                       prefill_tokens_avoided=0, estimated_kv_bytes=10_000))
    nv = p.net_value_estimate_ms("s1", "vllm", expected_reuses=3)
    assert nv <= 0.0, f"expected net_value <= 0 when zero reuse observed, got {nv}"


def test_runtime_keying_isolates_venues():
    p = RuntimePriors()
    for _ in range(30):
        p.observe(_obs("s1", "vllm", was_preserved=True, was_reused=True,
                       prefill_tokens_avoided=500, estimated_kv_bytes=50_000))
    # Another runtime has zero observations for the same shape.
    assert p.has_observations("s1", "vllm") is True
    assert p.has_observations("s1", "hf_generate") is False
    assert p.payoff_ms_estimate("s1", "hf_generate") == 0.0
    # hf_generate cold default has zero prefill payoff even when data exists
    # for the same shape under vllm — keys must not bleed.
    assert p.reuse_probability("s1", "hf_generate") == 0.0


def test_persist_and_load_roundtrip():
    p = RuntimePriors()
    for i in range(15):
        p.observe(_obs("s1", "vllm", was_preserved=True, was_reused=(i % 2 == 0),
                       prefill_tokens_avoided=200 + i, estimated_kv_bytes=5_000))
        p.observe(_obs("s2", "vllm", was_preserved=False, was_reused=False))
    p.note_waste("s1", "vllm")

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "priors.json")
        p.persist(path)
        # File is valid JSON with the expected shape.
        payload = json.load(open(path))
        assert payload["version"] >= 1
        assert any(r["shape_id"] == "s1" for r in payload["records"])

        q = RuntimePriors()
        q.load(path)
        assert q.has_observations("s1", "vllm")
        assert q.has_observations("s2", "vllm")
        # EWMA and counters match.
        assert abs(q.payoff_ms_estimate("s1", "vllm") - p.payoff_ms_estimate("s1", "vllm")) < 1e-9
        assert q.reuse_probability("s1", "vllm") == p.reuse_probability("s1", "vllm")


def test_load_missing_file_is_a_noop():
    q = RuntimePriors()
    q.load("/tmp/definitely_does_not_exist_hoverstack_priors.json")
    assert q.has_observations("anything", "anywhere") is False


def test_summary_shape():
    p = RuntimePriors()
    p.observe(_obs("s1", "vllm", was_preserved=True))
    summary = p.summary()
    assert summary["entries"] == 1
    assert summary["keys"][0]["shape_id"] == "s1"
    assert summary["keys"][0]["runtime_name"] == "vllm"
    assert summary["keys"][0]["observations"] == 1
