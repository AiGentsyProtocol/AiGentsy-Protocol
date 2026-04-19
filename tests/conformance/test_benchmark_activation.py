"""Benchmark activation tests for the three AiGentsy-inspired adaptations.

Verifies that the existing prefill_bench callers now actually pass
APEX_RISK_RULES into RiskPlane and per-family cold_start_hint into
decide_with_cost. Does NOT re-test the helpers themselves — those are
covered by test_adapted_patterns.py.

All tests use the reference adapter with sim prefix cache so they are
fast and deterministic on any host.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from hoverstack import prefill_bench
from hoverstack.preservation_policy import PreservationAction, PreservationPolicy
from hoverstack.prefill_bench import (
    APEX_RISK_RULES, PREFILL_DOMINANT_FAMILIES, run_apex_regime,
    run_benchmark,
)
from hoverstack.risk_plane import RiskClass, RiskRule, RiskRuleSet
from hoverstack.runtime_reference import ReferenceAdapter


# ══════════════════════════════════════════════════════════════════════
#   RULE SET SHAPE
# ══════════════════════════════════════════════════════════════════════

def test_apex_risk_rules_is_non_empty_list():
    assert isinstance(APEX_RISK_RULES, list)
    assert len(APEX_RISK_RULES) >= 2


def test_apex_risk_rules_cover_clinical_qa_and_rare_freeform():
    fams_covered = {r.value for r in APEX_RISK_RULES
                     if r.field == "task_family" and r.op == "=="}
    assert "clinical_qa" in fams_covered
    assert "rare_freeform" in fams_covered


def test_apex_risk_rule_for_clinical_qa_forces_full_compute():
    rules_for_clinical = [
        r for r in APEX_RISK_RULES
        if r.field == "task_family" and r.op == "==" and r.value == "clinical_qa"
    ]
    assert rules_for_clinical, "no rule for clinical_qa"
    assert rules_for_clinical[0].action == "force_full_compute"


def test_apex_risk_rule_for_rare_freeform_forces_full_compute():
    """Tuning pass: rare_freeform was `never_direct_recall`, which still
    allowed structural / delta recall — inappropriate for an open-
    reasoning one-off. Upgraded to `force_full_compute` so the risk
    plane refuses every avoidance path on this family."""
    rules_for_rare = [
        r for r in APEX_RISK_RULES
        if r.field == "task_family" and r.op == "==" and r.value == "rare_freeform"
    ]
    assert rules_for_rare, "no rule for rare_freeform"
    assert rules_for_rare[0].action == "force_full_compute"


# ══════════════════════════════════════════════════════════════════════
#   FAMILY METADATA HAS RECURRENCE_PRIOR
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("family_id", [
    "contract_review", "clinical_qa", "bom_extract", "rare_freeform",
])
def test_prefill_families_carry_recurrence_prior(family_id):
    hints = PREFILL_DOMINANT_FAMILIES[family_id].get("risk_hints", {})
    assert "recurrence_prior" in hints, (
        f"{family_id} risk_hints missing recurrence_prior"
    )
    val = hints["recurrence_prior"]
    assert 0.0 <= float(val) <= 1.0


def test_recurrence_priors_ordered_by_expected_recurrence():
    """Dominant families should carry higher priors than rare ones."""
    contract = PREFILL_DOMINANT_FAMILIES["contract_review"]["risk_hints"]["recurrence_prior"]
    clinical = PREFILL_DOMINANT_FAMILIES["clinical_qa"]["risk_hints"]["recurrence_prior"]
    rare = PREFILL_DOMINANT_FAMILIES["rare_freeform"]["risk_hints"]["recurrence_prior"]
    assert contract > clinical > rare


# ══════════════════════════════════════════════════════════════════════
#   BENCHMARK PASSES RISKRULESET INTO RISKPLANE
# ══════════════════════════════════════════════════════════════════════

def test_benchmark_replaces_risk_plane_with_rule_aware_instance():
    """Spy on RiskPlane construction inside _run_with_policy and confirm
    it gets called with a non-None rule_set argument."""
    calls = []
    orig = prefill_bench.RiskPlane

    class _Spy(orig):
        def __init__(self, *a, **kw):
            calls.append(kw)
            super().__init__(*a, **kw)

    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    with patch.object(prefill_bench, "RiskPlane", _Spy):
        run_apex_regime(adapter, "sim-model", "mixed",
                          seed=42, num_waves=1)

    # _run_with_policy runs once per mode (lifecycle_only + runtime_native).
    # At least one call site should supply a RiskRuleSet.
    rule_sets = [c.get("rule_set") for c in calls if c.get("rule_set") is not None]
    assert rule_sets, (
        f"RiskPlane was never constructed with rule_set. All calls: {calls}"
    )
    # And each of those rule_sets must contain the documented rules.
    for rs in rule_sets:
        assert isinstance(rs, RiskRuleSet)
        assert len(rs.rules) >= 2


# ══════════════════════════════════════════════════════════════════════
#   BENCHMARK RULE-DRIVEN RISK SHOWS UP IN HOVERSTAMP PAYLOADS
# ══════════════════════════════════════════════════════════════════════

def test_risk_restricted_run_shows_rule_tag_in_restrictions():
    """Cells from clinical_qa / rare_freeform should carry a rule tag
    in their risk_restrictions_applied field (visible via the adapter's
    HoverStamp runtime_fields → via the per-request records →
    surfaced through the net_value_by_class block)."""
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    summary = run_apex_regime(adapter, "sim-model", "risk_restricted",
                                seed=42, num_waves=2)
    # headline_economics.risk_forced_full_compute_rate > 0 confirms that
    # the rule for clinical_qa fired.
    he = summary["headline_economics"]
    assert he["risk_forced_full_compute_rate"] > 0.0, (
        "rule-driven force_full_compute did not fire in risk_restricted regime"
    )


def test_recall_suitable_run_not_affected_by_clinical_qa_rule():
    """The recall_suitable regime does not include clinical_qa or
    rare_freeform; neither rule should fire, and risk_forced_full stays 0."""
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    summary = run_apex_regime(adapter, "sim-model", "recall_suitable",
                                seed=42, num_waves=2)
    assert summary["headline_economics"]["risk_forced_full_compute_rate"] == 0.0


# ══════════════════════════════════════════════════════════════════════
#   BENCHMARK PASSES COLD_START_HINT INTO decide_with_cost
# ══════════════════════════════════════════════════════════════════════

def test_benchmark_passes_cold_start_hint_into_decide_with_cost():
    """Spy on PreservationPolicy.decide_with_cost and confirm each call
    receives a cold_start_hint kwarg with answer_form + recurrence."""
    calls = []
    orig = PreservationPolicy.decide_with_cost

    def _spy(self, *args, **kwargs):
        calls.append(kwargs)
        return orig(self, *args, **kwargs)

    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    with patch.object(PreservationPolicy, "decide_with_cost", _spy):
        run_apex_regime(adapter, "sim-model", "mixed",
                          seed=42, num_waves=1)

    assert calls, "decide_with_cost was never called"
    # Every call should carry a cold_start_hint dict.
    missing = [c for c in calls if "cold_start_hint" not in c]
    assert not missing, (
        f"{len(missing)} calls missing cold_start_hint; first: {missing[0]}"
    )
    # Hint shape should be {answer_form, shape_recurrence_prior}.
    for c in calls:
        h = c["cold_start_hint"]
        assert isinstance(h, dict)
        assert "answer_form" in h
        assert "shape_recurrence_prior" in h
        assert 0.0 <= float(h["shape_recurrence_prior"]) <= 1.0


# ══════════════════════════════════════════════════════════════════════
#   COLD-START BASIS VISIBLE ON FIRST-SEEN SHAPES
# ══════════════════════════════════════════════════════════════════════

def test_cold_start_basis_appears_for_first_wave_cells():
    """Build up a minimal decision-ladder path and confirm the first
    cell for a fresh shape gets preservation_prior_basis =
    'cold_start_prior_kernel' (not 'cold_default')."""
    from hoverstack.memory_plane import MemoryPlane
    from hoverstack.prefill_bench import _shape_from_family
    from hoverstack.processing_class import ProcessingClass

    plane = MemoryPlane(shapes=[
        _shape_from_family(f, PREFILL_DOMINANT_FAMILIES) for f in PREFILL_DOMINANT_FAMILIES
    ])
    hints = PREFILL_DOMINANT_FAMILIES["contract_review"]["risk_hints"]
    hint = {
        "answer_form": hints["answer_form"],
        "shape_recurrence_prior": hints["recurrence_prior"],
    }
    action = plane.preservation.decide_with_cost(
        "contract_review", ProcessingClass.REUSABLE,
        priors=plane.priors, runtime_name="vllm", model_name="",
        cold_start_hint=hint,
    )
    assert action.preservation_prior_basis == "cold_start_prior_kernel"
    assert action.payoff_ms_estimate is not None
    assert action.payoff_ms_estimate > 0.0


# ══════════════════════════════════════════════════════════════════════
#   BACK-COMPAT
# ══════════════════════════════════════════════════════════════════════

def test_legacy_run_benchmark_summary_shape_still_intact():
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    s = run_benchmark(adapter, "sim-model", seed=42, num_waves=1)
    # Both legacy regime keys still present.
    assert "prefill_dominant" in s
    assert "adversarial" in s
    assert "answer_to_main_question" in s
    # headline_economics still present per regime.
    for regime in ("prefill_dominant", "adversarial"):
        he = s[regime].get("headline_economics", {})
        for k in ("recall_attempt_rate", "delta_attempt_rate",
                  "risk_forced_full_compute_rate",
                  "proof_completeness_rate"):
            assert k in he


def test_activation_does_not_corrupt_required_headline_keys():
    """All 15 headline keys required by the apex staircase spec remain
    present after activation."""
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    s = run_apex_regime(adapter, "sim-model", "mixed",
                         seed=42, num_waves=1)
    he = s["headline_economics"]
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
        assert k in he, f"activation dropped required headline key: {k}"
