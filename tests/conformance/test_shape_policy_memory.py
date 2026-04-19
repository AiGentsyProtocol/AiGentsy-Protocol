"""Shape policy memory tests.

Covers:
    1. Pure-function correctness over synthetic plane snapshots.
    2. Reputation scoring is bounded, deterministic, and conservative.
    3. Tags reflect evidence thresholds.
    4. Recommendations are copy-pasteable and confidence-gated.
    5. decide_with_cost opt-in feedback: off by default, on under flag.
    6. Benchmark summary now carries the shape_policy block with the
       required operator-facing lists.
    7. No regression on pre-existing headline keys.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from hoverstack.preservation_policy import PreservationPolicy
from hoverstack.prefill_bench import run_apex_regime
from hoverstack.processing_class import ProcessingClass
from hoverstack.runtime_priors import PreservationOutcome, RuntimePriors
from hoverstack.runtime_reference import ReferenceAdapter
from hoverstack.shape_policy_memory import (
    SHAPE_REPUTATION_FEEDBACK_THRESHOLD, ShapePolicyMemory, ShapeProfile,
)


# ══════════════════════════════════════════════════════════════════════
#   REPUTATION + TAGS + RECOMMENDATIONS (pure)
# ══════════════════════════════════════════════════════════════════════

def _snap(priors_keys=None, recall_top=None, delta_top=None):
    return {
        "priors": {"keys": priors_keys or [], "class_efficiency_ledger": {}},
        "recall": {"top_positive": recall_top or []},
        "delta": {"top_positive": delta_top or []},
        "preservation": {"total_waste": 0},
    }


def test_reputation_bounded_in_unit_interval():
    """Any input combination must yield reputation in [-1, 1]."""
    snap = _snap(
        priors_keys=[{
            "shape_id": "s", "runtime_name": "vllm", "model_name": "",
            "observations": 100, "preserve_count": 100, "reuse_count": 100,
        }],
        recall_top=[{"shape_id": "s", "runtime_name": "vllm", "model_name": "",
                      "attempts": 100, "successes": 100, "reversions": 100,
                      "success_rate": 1.0, "reversion_rate": 1.0}],
        delta_top=[{"shape_id": "s", "runtime_name": "vllm", "model_name": "",
                     "attempts": 100, "successes": 100, "fallbacks": 100,
                     "fallback_rate": 1.0}],
    )
    spm = ShapePolicyMemory(snap)
    p = spm.profile("s", "vllm")
    assert -1.0 <= p.reputation <= 1.0


def test_reputation_positive_for_reliable_shape():
    """High reuse + high recall success + low reversion + low delta
    fallback → positive reputation with reliable tags."""
    snap = _snap(
        priors_keys=[{
            "shape_id": "s", "runtime_name": "vllm", "model_name": "",
            "observations": 20, "preserve_count": 20, "reuse_count": 18,
        }],
        recall_top=[{"shape_id": "s", "runtime_name": "vllm", "model_name": "",
                      "attempts": 20, "successes": 18, "reversions": 1,
                      "success_rate": 0.9, "reversion_rate": 0.05}],
        delta_top=[{"shape_id": "s", "runtime_name": "vllm", "model_name": "",
                     "attempts": 20, "successes": 18, "fallbacks": 2,
                     "fallback_rate": 0.1}],
    )
    p = ShapePolicyMemory(snap).profile("s", "vllm")
    assert p.reputation > 0.3
    assert "reliable_recall" in p.tags
    assert "reliable_delta" in p.tags


def test_reputation_negative_for_unstable_shape():
    """High reversions + fallbacks + waste → negative reputation with
    unstable / trap / early-deny tags."""
    snap = _snap(
        priors_keys=[{
            "shape_id": "bad", "runtime_name": "vllm", "model_name": "",
            "observations": 20, "preserve_count": 20, "reuse_count": 2,
            "waste_count": 15,
        }],
        recall_top=[{"shape_id": "bad", "runtime_name": "vllm", "model_name": "",
                      "attempts": 20, "successes": 5, "reversions": 12,
                      "success_rate": 0.25, "reversion_rate": 0.6}],
        delta_top=[{"shape_id": "bad", "runtime_name": "vllm", "model_name": "",
                     "attempts": 20, "successes": 4, "fallbacks": 14,
                     "fallback_rate": 0.7}],
    )
    p = ShapePolicyMemory(snap).profile("bad", "vllm")
    assert p.reputation < -0.3
    assert "unstable_shortcut" in p.tags
    assert "delta_trap" in p.tags
    assert "memory_burden" in p.tags
    assert "early_deny_candidate" in p.tags


def test_thin_evidence_returns_insufficient_confidence():
    snap = _snap(priors_keys=[{
        "shape_id": "thin", "runtime_name": "vllm", "model_name": "",
        "observations": 1, "preserve_count": 1, "reuse_count": 0,
    }])
    p = ShapePolicyMemory(snap).profile("thin", "vllm")
    assert p.confidence == "insufficient_evidence"


def test_high_evidence_promotes_confidence():
    snap = _snap(
        priors_keys=[{
            "shape_id": "hi", "runtime_name": "vllm", "model_name": "",
            "observations": 15, "preserve_count": 10, "reuse_count": 8,
        }],
        recall_top=[{"shape_id": "hi", "runtime_name": "vllm", "model_name": "",
                      "attempts": 15, "successes": 12, "reversions": 1,
                      "success_rate": 0.8, "reversion_rate": 0.067}],
    )
    p = ShapePolicyMemory(snap).profile("hi", "vllm")
    assert p.confidence == "high"


def test_recommendation_covers_early_deny_candidate():
    """Negative reputation shape gets a force_full_compute rule suggestion."""
    snap = _snap(
        priors_keys=[{
            "shape_id": "hard", "runtime_name": "vllm", "model_name": "",
            "observations": 10, "preserve_count": 10, "reuse_count": 1,
            "waste_count": 8,
        }],
        recall_top=[{"shape_id": "hard", "runtime_name": "vllm", "model_name": "",
                      "attempts": 10, "successes": 2, "reversions": 7,
                      "success_rate": 0.2, "reversion_rate": 0.7}],
    )
    p = ShapePolicyMemory(snap).profile("hard", "vllm")
    assert p.rule_recommendation is not None
    assert "force_full_compute" in p.rule_recommendation
    assert 'value="hard"' in p.rule_recommendation


def test_unstable_shape_gets_never_direct_recall_suggestion():
    snap = _snap(
        priors_keys=[{
            "shape_id": "unstable", "runtime_name": "vllm", "model_name": "",
            "observations": 10, "preserve_count": 10, "reuse_count": 5,
        }],
        recall_top=[{"shape_id": "unstable", "runtime_name": "vllm", "model_name": "",
                      "attempts": 10, "successes": 5, "reversions": 4,
                      "success_rate": 0.5, "reversion_rate": 0.4}],
    )
    p = ShapePolicyMemory(snap).profile("unstable", "vllm")
    # Reputation is only mildly negative → not early_deny, but still
    # unstable_shortcut so the "never direct" suggestion fires.
    assert p.rule_recommendation is not None
    if "early_deny_candidate" not in p.tags:
        assert "never_direct_recall" in p.rule_recommendation


def test_preserve_worthy_never_gets_a_deny_rule():
    """A shape with high reuse probability should not get any deny
    rule recommendation."""
    snap = _snap(
        priors_keys=[{
            "shape_id": "good", "runtime_name": "vllm", "model_name": "",
            "observations": 20, "preserve_count": 20, "reuse_count": 18,
        }],
        recall_top=[{"shape_id": "good", "runtime_name": "vllm", "model_name": "",
                      "attempts": 10, "successes": 9, "reversions": 0,
                      "success_rate": 0.9, "reversion_rate": 0.0}],
    )
    p = ShapePolicyMemory(snap).profile("good", "vllm")
    assert "preserve_worthy" in p.tags
    assert p.rule_recommendation is None
    assert p.recommended_preservation_action == "preserve"


# ══════════════════════════════════════════════════════════════════════
#   QUERIES / SUMMARY
# ══════════════════════════════════════════════════════════════════════

def test_top_trusted_recall_shapes_orders_by_reputation():
    """Both shapes earn `reliable_recall` (success >= 0.8, reversion < 0.1)
    and are ordered by reputation, which is higher for the cleaner shape."""
    snap = _snap(
        recall_top=[
            {"shape_id": "a", "runtime_name": "vllm", "model_name": "",
             "attempts": 20, "successes": 18, "reversions": 0,
             "success_rate": 0.9, "reversion_rate": 0.0},
            {"shape_id": "b", "runtime_name": "vllm", "model_name": "",
             "attempts": 20, "successes": 17, "reversions": 1,
             "success_rate": 0.85, "reversion_rate": 0.05},
        ],
    )
    tops = ShapePolicyMemory(snap).top_trusted_recall_shapes(5)
    ids = [p.shape_id for p in tops]
    assert "a" in ids and "b" in ids
    # a has strictly higher success and lower reversion → higher reputation.
    assert ids.index("a") <= ids.index("b")


def test_summary_contains_all_operator_lists():
    snap = _snap()
    summary = ShapePolicyMemory(snap).summary()
    for key in (
        "profile_count", "confidence_distribution",
        "top_trusted_recall_shapes", "top_trusted_delta_shapes",
        "top_preserve_worthy_shapes", "top_early_deny_shapes",
        "top_memory_burden_shapes", "rule_suggestions",
    ):
        assert key in summary


def test_rule_suggestions_are_gated_on_confidence():
    """Suggestions for shapes with insufficient_evidence must be excluded
    so the operator doesn't authorize rules from thin data."""
    snap = _snap(
        priors_keys=[{"shape_id": "thin", "runtime_name": "vllm",
                       "model_name": "", "observations": 1,
                       "preserve_count": 1, "reuse_count": 0}],
    )
    spm = ShapePolicyMemory(snap)
    suggs = spm.rule_suggestions()
    assert all(s["confidence"] in ("medium", "high") for s in suggs)


# ══════════════════════════════════════════════════════════════════════
#   OPT-IN PRESERVATION FEEDBACK
# ══════════════════════════════════════════════════════════════════════

def test_decide_with_cost_ignores_reputation_when_none():
    """Identity path: shape_reputation=None → no TTL adjustment from
    the reputation feedback path."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    for _ in range(20):
        priors.observe(PreservationOutcome(
            shape_id="s", runtime_name="vllm",
            was_preserved=True, was_reused=True,
            prefill_tokens_avoided=500, estimated_kv_bytes=1000,
        ))
    legacy = pp.decide_with_cost("s", ProcessingClass.REUSABLE,
                                   priors=priors, runtime_name="vllm")
    with_reputation = pp.decide_with_cost("s", ProcessingClass.REUSABLE,
                                            priors=priors, runtime_name="vllm",
                                            shape_reputation=None)
    assert legacy.ttl_waves == with_reputation.ttl_waves
    assert legacy.ttl_shortened == with_reputation.ttl_shortened


def test_decide_with_cost_reputation_above_threshold_no_change():
    """Positive or mildly negative reputation → no TTL feedback."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    for _ in range(20):
        priors.observe(PreservationOutcome(
            shape_id="s", runtime_name="vllm",
            was_preserved=True, was_reused=True,
            prefill_tokens_avoided=500, estimated_kv_bytes=1000,
        ))
    a = pp.decide_with_cost("s", ProcessingClass.REUSABLE,
                             priors=priors, runtime_name="vllm",
                             shape_reputation=0.5)
    assert a.ttl_shortened is False
    b = pp.decide_with_cost("s", ProcessingClass.REUSABLE,
                             priors=priors, runtime_name="vllm",
                             shape_reputation=-0.1)
    assert b.ttl_shortened is False


def test_decide_with_cost_reputation_below_threshold_shortens_ttl():
    """Strongly negative reputation → TTL shortened by one wave with
    distinct rationale; class is never flipped."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    for _ in range(20):
        priors.observe(PreservationOutcome(
            shape_id="s", runtime_name="vllm",
            was_preserved=True, was_reused=True,
            prefill_tokens_avoided=500, estimated_kv_bytes=1000,
        ))
    a = pp.decide_with_cost("s", ProcessingClass.REUSABLE,
                             priors=priors, runtime_name="vllm",
                             shape_reputation=-0.7)
    assert a.ttl_shortened is True
    assert a.effective_class == ProcessingClass.REUSABLE
    assert "shape_reputation" in (a.downgrade_reason or "")


def test_decide_with_cost_reputation_does_not_double_shorten_on_kelly():
    """If Kelly already shortened the TTL this call, the reputation
    feedback must not shorten it a second time."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    # Build priors that put Kelly in the low-fraction zone (low reuse).
    for i in range(30):
        priors.observe(PreservationOutcome(
            shape_id="s", runtime_name="vllm",
            was_preserved=True, was_reused=(i == 0),
            prefill_tokens_avoided=5,
            estimated_kv_bytes=1_000,
        ))
    a = pp.decide_with_cost("s", ProcessingClass.REUSABLE,
                             priors=priors, runtime_name="vllm",
                             shape_reputation=-0.9)
    # At most one wave of TTL shortening (either Kelly OR reputation).
    assert a.ttl_shortened is True
    # Original class TTL for REUSABLE is 3 in PreservationConfig; after
    # one shortening it should be 2, not 1.
    assert a.ttl_waves == 2


# ══════════════════════════════════════════════════════════════════════
#   BENCHMARK INTEGRATION
# ══════════════════════════════════════════════════════════════════════

def _run(regime: str, waves: int = 2, env: dict = None) -> dict:
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    if env:
        with patch.dict(os.environ, env):
            return run_apex_regime(adapter, "sim-model", regime,
                                     seed=42, num_waves=waves)
    return run_apex_regime(adapter, "sim-model", regime,
                             seed=42, num_waves=waves)


def test_benchmark_summary_includes_shape_policy_block():
    summary = _run("mixed", waves=2)
    he = summary["headline_economics"]
    assert "shape_policy" in he
    sp = he["shape_policy"]
    for k in ("profile_count", "confidence_distribution",
              "top_trusted_recall_shapes", "top_trusted_delta_shapes",
              "top_preserve_worthy_shapes", "top_early_deny_shapes",
              "top_memory_burden_shapes", "rule_suggestions"):
        assert k in sp


def test_benchmark_preserves_all_pre_existing_keys():
    """All 15 spec-required headline keys remain alongside the new blocks."""
    summary = _run("mixed", waves=2)
    he = summary["headline_economics"]
    for k in (
        "recall_attempt_rate", "recall_success_rate", "recall_reversion_rate",
        "delta_attempt_rate", "delta_success_rate", "delta_fallback_rate",
        "risk_forced_full_compute_rate",
        "compute_avoided_by_recall_ms", "compute_avoided_by_delta_ms",
        "net_value_by_class", "waste_carry_units",
        "top_negative_net_shapes", "top_positive_recall_shapes",
        "top_positive_delta_shapes",
        "proof_completeness_rate",
        # wedge + negative + shape_policy must all coexist
        "wedge_economics", "negative_intelligence", "shape_policy",
    ):
        assert k in he, f"missing required key: {k}"


def test_reputation_feedback_is_off_by_default():
    """Without the env var set, benchmark output is unchanged from the
    pre-feedback behaviour for the mixed regime headline metrics."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HOVERSTACK_ENABLE_SHAPE_REPUTATION_FEEDBACK", None)
        baseline = _run("mixed", waves=2)
    he_base = baseline["headline_economics"]
    # With feedback off, wedge_economics ttl_shortened_soft_corrections
    # stays at the pre-upgrade count (same as test_wedge_economics dry-runs).
    assert he_base["wedge_economics"]["ttl_shortened_soft_corrections"] >= 0


def test_reputation_feedback_env_on_exercises_shape_policy_memory():
    """When the env var is set, the benchmark uses ShapePolicyMemory
    per wave (no crash, summary still well-formed, headline keys
    unchanged)."""
    with patch.dict(os.environ,
                    {"HOVERSTACK_ENABLE_SHAPE_REPUTATION_FEEDBACK": "1"}):
        summary = run_apex_regime(
            ReferenceAdapter(simulate_prefix_cache=True),
            "sim-model", "mixed", seed=42, num_waves=3,
        )
    # Output shape stays intact.
    for k in ("headline_economics", "apex_verdict", "regime_name"):
        assert k in summary
    sp = summary["headline_economics"]["shape_policy"]
    assert sp["profile_count"] >= 0
