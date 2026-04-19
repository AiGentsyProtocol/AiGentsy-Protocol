"""Wedge-economics tests.

Covers:
  1. Pure-function correctness of compute_wedge_metrics on synthetic
     records (no benchmark required).
  2. Negative-intelligence lists derive correctly from plane snapshots.
  3. The benchmark headline now surfaces wedge_economics and
     negative_intelligence blocks with every required key present.
  4. No-regression: all 15 pre-existing headline keys are still present.
  5. Simulator-backed per-regime expectations for the wedge block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from hoverstack.prefill_bench import run_apex_regime
from hoverstack.runtime_reference import ReferenceAdapter
from hoverstack.wedge_economics import (
    compute_wedge_metrics, early_deny_candidates, negative_intelligence,
    top_delta_traps, top_false_recall_shapes,
    top_negative_shortcut_shapes,
)


@dataclass
class _FakeRecord:
    total_ms: float = 10.0
    runtime_fields: Dict[str, Any] = field(default_factory=dict)


def _cell(
    recall_mode: Optional[str] = None,
    delta_mode: Optional[str] = None,
    recall_fallback: bool = False,
    delta_fallback: bool = False,
    restrictions: Optional[List[str]] = None,
    compute_avoided: float = 0.0,
    total_ms: float = 10.0,
    decision_rationale: Optional[str] = None,
    preservation_prior_basis: Optional[str] = None,
    decision_key: Optional[str] = None,
) -> _FakeRecord:
    rf: Dict[str, Any] = {}
    if recall_mode is not None:
        rf["recall_mode"] = recall_mode
    if delta_mode is not None:
        rf["delta_mode"] = delta_mode
    if recall_fallback:
        rf["recall_fallback_triggered"] = True
    if delta_fallback:
        rf["delta_fallback_triggered"] = True
    if restrictions:
        rf["risk_restrictions_applied"] = restrictions
    if compute_avoided:
        rf["compute_avoided_estimate"] = compute_avoided
    if decision_rationale:
        rf["decision_rationale"] = decision_rationale
    if preservation_prior_basis:
        rf["preservation_prior_basis"] = preservation_prior_basis
    if decision_key:
        rf["decision_key"] = decision_key
    return _FakeRecord(total_ms=total_ms, runtime_fields=rf)


# ── compute_wedge_metrics core numbers ────────────────────────────────

def test_governed_compute_avoided_sums_successful_shortcut_cells():
    records = [
        _cell(recall_mode="direct_recall", compute_avoided=100.0),
        _cell(delta_mode="tail_only_delta", compute_avoided=50.0),
        _cell(recall_mode="full_compute"),                 # no avoid
        _cell(recall_mode="direct_recall",                  # fallback → no avoid
              recall_fallback=True, compute_avoided=999.0),
    ]
    m = compute_wedge_metrics(records, {})
    assert m["governed_compute_avoided_ms"] == 150.0


def test_safe_avoided_excludes_restricted_cells():
    """safe_compute_avoided_ms counts shortcuts only when no risk
    restrictions were applied. A shortcut under risk restriction is not
    'safe' in the wedge sense."""
    records = [
        _cell(recall_mode="direct_recall", compute_avoided=30.0),
        _cell(recall_mode="structural_recall", compute_avoided=20.0,
              restrictions=["rule[0]:never_direct_recall"]),
    ]
    m = compute_wedge_metrics(records, {})
    assert m["governed_compute_avoided_ms"] == 50.0
    assert m["safe_compute_avoided_ms"] == 30.0


def test_risk_forced_compute_only_when_rule_fired():
    records = [
        # Forced by risk (restriction present) → counts.
        _cell(recall_mode="full_compute", total_ms=40.0,
              restrictions=["rule[0]:force_full_compute"]),
        # Full compute but no rule — ordinary fallback, not risk-forced.
        _cell(recall_mode="full_compute", total_ms=20.0),
    ]
    m = compute_wedge_metrics(records, {})
    assert m["risk_forced_compute_ms"] == 40.0
    assert m["risky_shortcuts_prevented"] == 1


def test_unsafe_shortcuts_prevented_counts_refusals():
    records = [
        _cell(recall_mode="full_compute",
              restrictions=["rule[0]:force_full_compute"]),
        _cell(recall_mode="full_compute", recall_fallback=True),
        _cell(delta_mode="full_compute_required", delta_fallback=True),
        _cell(recall_mode="direct_recall", compute_avoided=10.0),  # success
    ]
    m = compute_wedge_metrics(records, {})
    # Recall refusals with rule or fallback: 2
    # Delta refusal with fallback: 1
    assert m["unsafe_shortcuts_prevented"] == 3


def test_proof_complete_rate_counts_rationale():
    records = [
        _cell(decision_rationale="direct_recall: confidence 0.92"),
        _cell(decision_rationale="full_compute forced by risk"),
        _cell(),  # no rationale
    ]
    m = compute_wedge_metrics(records, {})
    # The metric is rounded to 4 decimals; 2/3 = 0.6667 after rounding.
    assert m["proof_complete_decision_rate"] == pytest.approx(2 / 3, abs=1e-3)


def test_cold_start_denial_vs_opportunity_bucketing():
    records = [
        # Cold-start with full_compute → denial.
        _cell(recall_mode="full_compute",
              preservation_prior_basis="cold_start_prior_kernel"),
        # Cold-start with successful shortcut → opportunity.
        _cell(recall_mode="structural_recall",
              preservation_prior_basis="cold_start_prior_kernel"),
        # Warm cell — not counted either way.
        _cell(recall_mode="direct_recall",
              preservation_prior_basis="per_shape_runtime_model"),
    ]
    m = compute_wedge_metrics(records, {})
    assert m["cold_start_denial_count"] == 1
    assert m["cold_start_opportunity_count"] == 1


def test_ttl_shortened_counted_from_decision_key():
    records = [
        _cell(decision_key="warm|preserve|...|ttl_short"),
        _cell(decision_key="reusable|preserve|..."),  # no ttl_short
    ]
    m = compute_wedge_metrics(records, {})
    assert m["ttl_shortened_soft_corrections"] == 1


def test_preservation_burden_refused_pulled_from_snapshot():
    plane_snap = {"preservation": {"total_waste": 7}}
    m = compute_wedge_metrics([], plane_snap)
    assert m["preservation_burden_refused"] == 7


# ── Negative intelligence ────────────────────────────────────────────

def test_top_false_recall_shapes_orders_by_reversion_rate():
    snap = {
        "recall": {
            "top_positive": [
                {"shape_id": "a", "runtime_name": "vllm", "model_name": "",
                 "attempts": 10, "reversions": 6, "success_rate": 0.4},
                {"shape_id": "b", "runtime_name": "vllm", "model_name": "",
                 "attempts": 10, "reversions": 2, "success_rate": 0.8},
                {"shape_id": "c", "runtime_name": "vllm", "model_name": "",
                 "attempts": 10, "reversions": 0, "success_rate": 1.0},
            ],
        },
    }
    top = top_false_recall_shapes(snap, k=5)
    ids = [e["shape_id"] for e in top]
    assert ids == ["a", "b"]  # c has no reversions → excluded


def test_top_delta_traps_filters_to_high_fallback():
    snap = {
        "delta": {
            "top_positive": [
                {"shape_id": "x", "runtime_name": "vllm", "model_name": "",
                 "attempts": 10, "fallbacks": 7},
                {"shape_id": "y", "runtime_name": "vllm", "model_name": "",
                 "attempts": 10, "fallbacks": 0},  # excluded
            ],
        },
    }
    traps = top_delta_traps(snap, k=5)
    ids = [e["shape_id"] for e in traps]
    assert ids == ["x"]


def test_early_deny_candidates_gates_on_combined_score():
    snap = {
        "recall": {"top_positive": [
            {"shape_id": "bad", "runtime_name": "vllm", "model_name": "",
             "attempts": 10, "reversions": 6, "success_rate": 0.4},
            {"shape_id": "mild", "runtime_name": "vllm", "model_name": "",
             "attempts": 10, "reversions": 1, "success_rate": 0.9},
        ]},
        "delta": {"top_positive": [
            {"shape_id": "bad", "runtime_name": "vllm", "model_name": "",
             "attempts": 10, "fallbacks": 6},
        ]},
    }
    cands = early_deny_candidates(snap, min_combined_score=0.5)
    ids = [e["shape_id"] for e in cands]
    assert "bad" in ids
    assert "mild" not in ids
    # Recommendation string is operator-actionable.
    assert any("RiskRule" in e["recommendation"] for e in cands)


def test_negative_intelligence_wraps_all_four_lists():
    snap = {"recall": {"top_positive": []},
            "delta": {"top_positive": []}}
    ni = negative_intelligence(snap)
    for k in ("top_false_recall_shapes", "top_delta_traps",
              "top_negative_shortcut_shapes", "early_deny_candidates"):
        assert k in ni


# ── Benchmark integration ────────────────────────────────────────────

def _run(regime: str, waves: int = 2) -> Dict[str, Any]:
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    return run_apex_regime(adapter, "sim-model", regime,
                             seed=42, num_waves=waves)


def test_benchmark_summary_includes_wedge_economics_block():
    summary = _run("mixed", waves=2)
    he = summary["headline_economics"]
    assert "wedge_economics" in he
    we = he["wedge_economics"]
    for key in (
        "governed_compute_avoided_ms", "safe_compute_avoided_ms",
        "risk_forced_compute_ms", "unsafe_shortcuts_prevented",
        "risky_shortcuts_prevented", "preservation_burden_refused",
        "carry_cost_consumed_units", "observed_payoff_ms",
        "net_value_of_refusal_ms",
        "recall_refusals", "delta_refusals",
        "ttl_shortened_soft_corrections",
        "proof_complete_decision_rate",
        "cold_start_denial_count", "cold_start_opportunity_count",
    ):
        assert key in we, f"wedge_economics missing {key}"


def test_benchmark_summary_includes_negative_intelligence_block():
    summary = _run("mixed", waves=2)
    he = summary["headline_economics"]
    assert "negative_intelligence" in he
    ni = he["negative_intelligence"]
    for key in ("top_false_recall_shapes", "top_delta_traps",
                "top_negative_shortcut_shapes", "early_deny_candidates"):
        assert key in ni


def test_benchmark_preserves_all_pre_existing_headline_keys():
    """Wedge additions must not displace any of the 15 spec-required
    headline keys from the apex staircase contract."""
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
    ):
        assert k in he, f"wedge additions dropped required key: {k}"


def test_risk_restricted_wedge_reflects_forced_compute():
    """In the risk_restricted regime, the wedge block must show both
    risky_shortcuts_prevented > 0 AND risk_forced_compute_ms > 0."""
    summary = _run("risk_restricted", waves=2)
    we = summary["headline_economics"]["wedge_economics"]
    assert we["risky_shortcuts_prevented"] > 0
    assert we["risk_forced_compute_ms"] > 0


def test_recall_suitable_wedge_shows_safe_avoidance_without_risk_forced():
    """In recall_suitable, nothing should force full compute; safe
    avoidance should be the dominant number."""
    summary = _run("recall_suitable", waves=2)
    we = summary["headline_economics"]["wedge_economics"]
    assert we["risk_forced_compute_ms"] == 0.0
    assert we["risky_shortcuts_prevented"] == 0


def test_delta_suitable_wedge_shows_no_risk_forced():
    summary = _run("delta_suitable", waves=2)
    we = summary["headline_economics"]["wedge_economics"]
    assert we["risk_forced_compute_ms"] == 0.0
