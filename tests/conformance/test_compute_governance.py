"""Tests for the compute-governance maximum-form upgrades.

Covers:
    - Carrying-cost decomposition structure and cache-pressure scaling
    - Model-keying isolates priors across (shape, runtime, model)
    - Consecutive-wave hysteresis (3-of-3 rule) before class downgrade
    - Marginal-negative band → shorten TTL, keep class
    - Per-class efficiency ledger aggregation
    - top_negative_net_shapes ranking
    - misclassification_signals returns reusable_failing / stuck_warm
    - Cold-start rationale labeling
    - Class efficiency snapshot surfaced in HoverStamp runtime fields
"""

from __future__ import annotations

import pytest

from hoverstack.preservation_policy import PreservationPolicy
from hoverstack.primitives import ComputationalShape
from hoverstack.processing_class import ProcessingClass
from hoverstack.runtime_adapter import (
    RuntimeCapabilities, RuntimeRequest, RuntimeResponse,
)
from hoverstack.runtime_priors import (
    PreservationOutcome, RuntimePriors,
)


# ── Carrying-cost decomposition ─────────────────────────────────────

def test_carry_cost_decomposition_has_all_expected_fields():
    p = RuntimePriors()
    # Cold: should return defaults with structured fields.
    d = p.carry_cost_decomposition("s1", "vllm")
    expected_keys = {
        "kv_bytes_estimate", "residency_waves_avg", "overhead_ms_estimate",
        "cache_pressure_factor", "raw_units", "normalized_score",
    }
    assert set(d.keys()) == expected_keys
    assert d["cache_pressure_factor"] == 1.0


def test_cache_pressure_factor_scales_carry_units():
    p = RuntimePriors()
    # Cold-default carry.
    base = p.carry_units_estimate("s1", "vllm")
    p.cache_pressure_factor = 3.0
    scaled = p.carry_units_estimate("s1", "vllm")
    assert abs(scaled - 3.0 * base) < 1e-9, (
        f"expected 3× cold-default carry, got {scaled} vs base {base}"
    )
    # Decomposition also reflects the multiplier.
    d = p.carry_cost_decomposition("s1", "vllm")
    assert d["cache_pressure_factor"] == 3.0
    assert abs(d["normalized_score"] - 3.0 * d["raw_units"]) < 1e-9


# ── Model keying ────────────────────────────────────────────────────

def test_model_keying_isolates_priors_across_models():
    p = RuntimePriors()
    for _ in range(10):
        p.observe(PreservationOutcome(
            shape_id="s1", runtime_name="vllm", model_name="llama-8b",
            was_preserved=True, was_reused=True,
            prefill_tokens_avoided=500, estimated_kv_bytes=10_000,
        ))
    assert p.has_observations("s1", "vllm", "llama-8b")
    # Same shape+runtime but different model is a cold bucket.
    assert p.has_observations("s1", "vllm", "qwen-7b") is False
    # Default "" bucket also isolated from named models.
    assert p.has_observations("s1", "vllm", "") is False
    # Legacy 2-arg callers resolve to the "" bucket (back-compat).
    assert p.payoff_ms_estimate("s1", "vllm") == 0.0


# ── Hysteresis ──────────────────────────────────────────────────────

def test_hysteresis_requires_three_consecutive_negatives():
    pp = PreservationPolicy()
    priors = RuntimePriors()
    # Set up a negative-net workload.
    for _ in range(40):
        priors.observe(PreservationOutcome(
            shape_id="s1", runtime_name="vllm",
            was_preserved=True, was_reused=False,
            prefill_tokens_avoided=0, estimated_kv_bytes=10_000,
        ))
    assert priors.net_value_estimate_ms("s1", "vllm", 3) < 0

    # Calls 1 & 2 must NOT flip class.
    a1 = pp.decide_with_cost("s1", ProcessingClass.REUSABLE,
                              priors=priors, runtime_name="vllm")
    a2 = pp.decide_with_cost("s1", ProcessingClass.REUSABLE,
                              priors=priors, runtime_name="vllm")
    assert a1.effective_class == ProcessingClass.REUSABLE
    assert a2.effective_class == ProcessingClass.REUSABLE
    assert a1.downgrade_applied is False
    assert a2.downgrade_applied is False
    assert a1.ttl_shortened is True
    assert "awaiting_confirm" in (a1.downgrade_reason or "")

    # Call 3 confirms and downgrades.
    a3 = pp.decide_with_cost("s1", ProcessingClass.REUSABLE,
                              priors=priors, runtime_name="vllm")
    assert a3.effective_class == ProcessingClass.WARM
    assert a3.downgrade_applied is True
    assert "confirmed" in (a3.downgrade_reason or "")


def test_single_positive_sample_never_upgrades():
    """Priors are never used to upgrade — by design."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    for _ in range(40):
        priors.observe(PreservationOutcome(
            shape_id="s1", runtime_name="vllm",
            was_preserved=True, was_reused=True,
            prefill_tokens_avoided=2000, estimated_kv_bytes=1000,
        ))
    # Even if net_value is positive, class should not be elevated
    # beyond whatever pc the caller asked for.
    a = pp.decide_with_cost("s1", ProcessingClass.WARM,
                             priors=priors, runtime_name="vllm")
    assert a.effective_class == ProcessingClass.WARM


# ── Marginal-negative TTL shortening ────────────────────────────────

def test_marginal_negative_band_shortens_ttl_not_class():
    """When net_value is marginally negative, TTL shortens but class
    stays. This is the 'preserve but shorten TTL' sharper output."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    # Tune priors so net_value is small negative (within marginal band).
    # Strategy: tiny KV + modest payoff + zero reuse → slight negative.
    for _ in range(10):
        priors.observe(PreservationOutcome(
            shape_id="s1", runtime_name="vllm",
            was_preserved=True, was_reused=False,
            prefill_tokens_avoided=0, estimated_kv_bytes=100,
        ))
    net = priors.net_value_estimate_ms("s1", "vllm", 3)
    assert net < 0

    a = pp.decide_with_cost("s1", ProcessingClass.REUSABLE,
                             priors=priors, runtime_name="vllm",
                             marginal_band_pct=10.0)  # wide band → will match
    assert a.effective_class == ProcessingClass.REUSABLE
    assert a.ttl_shortened is True
    assert a.downgrade_applied is False


# ── Per-class ledger ────────────────────────────────────────────────

def test_class_efficiency_ledger_aggregates_outcomes():
    p = RuntimePriors()
    p.record_class_outcome("reusable", preserved=True, carry_units=2.0)
    p.record_class_outcome("reusable", preserved=True, reused=True,
                           carry_units=2.0, payoff_ms=8.0)
    p.record_class_outcome("warm", preserved=True, carry_units=1.0)
    p.record_class_outcome("warm", waste=True)
    p.record_class_outcome("reusable", downgrade=True)

    ledger = p.class_efficiency_ledger()
    assert ledger["reusable"]["preserved"] == 2
    assert ledger["reusable"]["reused"] == 1
    assert ledger["reusable"]["downgrades"] == 1
    assert ledger["reusable"]["total_carry_units"] == pytest.approx(4.0)
    assert ledger["reusable"]["total_payoff_ms"] == pytest.approx(8.0)
    assert ledger["reusable"]["net_value_ms"] == pytest.approx(4.0)
    assert ledger["warm"]["preserved"] == 1
    assert ledger["warm"]["waste"] == 1


# ── top_negative_net_shapes ranking ─────────────────────────────────

def test_top_negative_net_shapes_ranks_worst_first():
    p = RuntimePriors()
    # Shape A: high KV bytes, zero reuse → very negative.
    for _ in range(10):
        p.observe(PreservationOutcome(
            shape_id="A", runtime_name="vllm",
            was_preserved=True, was_reused=False,
            prefill_tokens_avoided=0, estimated_kv_bytes=100_000,
        ))
    # Shape B: moderate KV bytes, moderate reuse → less negative.
    for i in range(10):
        p.observe(PreservationOutcome(
            shape_id="B", runtime_name="vllm",
            was_preserved=True, was_reused=(i % 2 == 0),
            prefill_tokens_avoided=500, estimated_kv_bytes=5_000,
        ))
    # Shape C: positive economics.
    for _ in range(10):
        p.observe(PreservationOutcome(
            shape_id="C", runtime_name="vllm",
            was_preserved=True, was_reused=True,
            prefill_tokens_avoided=2000, estimated_kv_bytes=1_000,
        ))
    top = p.top_negative_net_shapes(k=3)
    assert len(top) == 3
    # Most negative first.
    assert top[0]["shape_id"] == "A"
    # C (positive) should be last.
    assert top[-1]["shape_id"] == "C"


# ── Misclassification signals ───────────────────────────────────────

def test_misclassification_signals_flag_reusable_failing():
    p = RuntimePriors()
    for _ in range(10):
        p.observe(PreservationOutcome(
            shape_id="failing", runtime_name="vllm",
            was_preserved=True, was_reused=False,
        ))
    sig = p.misclassification_signals()
    failing_ids = {e["shape_id"] for e in sig["reusable_failing"]}
    assert "failing" in failing_ids


def test_misclassification_signals_flag_stuck_warm():
    p = RuntimePriors()
    for _ in range(10):
        p.observe(PreservationOutcome(
            shape_id="stuck", runtime_name="vllm",
            was_preserved=True, was_reused=True,
        ))
    sig = p.misclassification_signals()
    stuck_ids = {e["shape_id"] for e in sig["stuck_warm"]}
    assert "stuck" in stuck_ids


# ── Cold-start rationale labeling ───────────────────────────────────

def test_cold_start_rationale_labeled():
    pp = PreservationPolicy()
    priors = RuntimePriors()  # empty
    a = pp.decide_with_cost("new_shape", ProcessingClass.REUSABLE,
                             priors=priors, runtime_name="vllm")
    assert a.preservation_prior_basis == "cold_default"
    assert a.runtime_payoff_basis == "cold_default"


# ── HoverStamp additive surfaces ───────────────────────────────────

def test_hoverstamp_emits_runtime_payoff_basis_and_class_snapshot():
    caps = RuntimeCapabilities(
        prefix_cache=True, prefill_decode_split=True,
        batched_decode=True, per_request_metrics=True,
        cache_compat_guarantee=True,
    )
    resp = RuntimeResponse(
        output_text="x", output_tokens=1, success=True, total_ms=10.0,
        runtime_name="vllm",
        runtime_payoff_basis="per_shape_runtime_model",
        class_efficiency_snapshot={"reusable": {"preserved": 3, "reused": 2}},
        carry_cost_decomposition={"raw_units": 1.5, "normalized_score": 1.5},
    )
    fields = resp.hoverstamp_runtime_fields(caps)
    assert fields["runtime_payoff_basis"] == "per_shape_runtime_model"
    assert "class_efficiency_snapshot" in fields
    assert fields["class_efficiency_snapshot"]["reusable"]["preserved"] == 3
    assert "carry_cost_decomposition" in fields


def test_hoverstamp_omits_absent_rationale_fields():
    """When rationale fields aren't set, they're omitted entirely —
    absence is a valid state (no non-trivial decision happened)."""
    caps = RuntimeCapabilities()
    resp = RuntimeResponse(
        output_text="x", output_tokens=1, success=True, total_ms=10.0,
        runtime_name="vllm",
    )
    fields = resp.hoverstamp_runtime_fields(caps)
    assert "runtime_payoff_basis" not in fields
    assert "class_efficiency_snapshot" not in fields
    assert "carry_cost_decomposition" not in fields
    assert "decision_rationale" not in fields
    assert "decision_key" not in fields
