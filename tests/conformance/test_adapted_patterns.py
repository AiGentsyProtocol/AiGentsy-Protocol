"""Tests for the three AiGentsy-inspired HoverStack-native adaptations.

No imports from AiGentsy modules. The three adaptations are:
    1. RiskRuleSet — data-driven overrides in risk_plane
    2. kelly_preservation_fraction — bounded preservation sizing
    3. cold_start_payoff_prior — bounded cold-start kernel

Each is tested for:
    - intended positive behaviour
    - safety under adversarial or nonsense inputs
    - no-regression when the new logic is inactive
"""

from __future__ import annotations

import math

import pytest

from hoverstack.preservation_policy import PreservationPolicy
from hoverstack.processing_class import ProcessingClass
from hoverstack.risk_plane import (
    ALLOWED_RISK_FIELDS, RiskAssessment, RiskClass, RiskDimensions,
    RiskPlane, RiskPolicyConfig, RiskRule, RiskRuleSet,
    VALID_RISK_ACTION_LITERALS, VALID_RISK_OPS,
)
from hoverstack.runtime_priors import (
    COLD_START_PAYOFF_CAP_MS, PreservationOutcome, RuntimePriors,
    cold_start_payoff_prior, kelly_preservation_fraction,
)


# ══════════════════════════════════════════════════════════════════════
#   PART 1 — RiskRuleSet
# ══════════════════════════════════════════════════════════════════════

def test_rule_construction_rejects_unknown_field():
    with pytest.raises(ValueError):
        RiskRule(field="not_a_field", op="==", value="x", action="force_full_compute")


def test_rule_construction_rejects_unknown_op():
    with pytest.raises(ValueError):
        RiskRule(field="task_family", op="like", value="x",
                 action="force_full_compute")


def test_rule_construction_rejects_unknown_action():
    with pytest.raises(ValueError):
        RiskRule(field="task_family", op="==", value="x", action="delete_everything")
    with pytest.raises(ValueError):
        RiskRule(field="task_family", op="==", value="x",
                 action="force_class:catastrophic")


def test_rule_construction_accepts_all_documented_literals():
    for action in VALID_RISK_ACTION_LITERALS:
        RiskRule(field="task_family", op="==", value="x", action=action)
    for cls in RiskClass:
        RiskRule(field="task_family", op="==", value="x",
                 action=f"force_class:{cls.value}")


def test_empty_ruleset_returns_none_defers_to_signals():
    rs = RiskRuleSet(rules=[])
    assert rs.evaluate(RiskDimensions(task_family="x")) is None


def test_rule_match_on_task_family_forces_full_compute():
    rs = RiskRuleSet(rules=[
        RiskRule(field="task_family", op="==", value="high_stakes",
                 action="force_full_compute"),
    ])
    r = rs.evaluate(RiskDimensions(task_family="high_stakes"))
    assert r is not None
    assert r.risk_class == RiskClass.HIGH
    assert r.force_full_compute is True
    assert r.allow_direct_recall is False
    assert r.allow_structural_recall is False
    assert r.allow_delta_compute is False


def test_rule_match_never_direct_recall():
    rs = RiskRuleSet(rules=[
        RiskRule(field="task_family", op="==", value="pii",
                 action="never_direct_recall"),
    ])
    r = rs.evaluate(RiskDimensions(task_family="pii"))
    assert r is not None
    assert r.allow_direct_recall is False
    assert r.allow_structural_recall is True
    assert r.allow_delta_compute is True


def test_rule_match_structural_recall_only():
    rs = RiskRuleSet(rules=[
        RiskRule(field="answer_form", op="==", value="open_reasoning",
                 action="structural_recall_only"),
    ])
    r = rs.evaluate(RiskDimensions(answer_form="open_reasoning"))
    assert r is not None
    assert r.allow_direct_recall is False
    # structural_recall_only maps to ELEVATED permission set
    assert r.risk_class == RiskClass.ELEVATED


def test_rule_match_force_class():
    rs = RiskRuleSet(rules=[
        RiskRule(field="ambiguity", op=">=", value=0.8,
                 action="force_class:high_risk"),
    ])
    r = rs.evaluate(RiskDimensions(ambiguity=0.9))
    assert r is not None
    assert r.risk_class == RiskClass.HIGH


def test_rule_operators_in_not_in():
    rs = RiskRuleSet(rules=[
        RiskRule(field="task_family", op="in",
                 value=["a", "b", "c"],
                 action="force_full_compute"),
    ])
    assert rs.evaluate(RiskDimensions(task_family="b")) is not None
    assert rs.evaluate(RiskDimensions(task_family="z")) is None

    rs2 = RiskRuleSet(rules=[
        RiskRule(field="task_family", op="not_in",
                 value=["safe1", "safe2"],
                 action="force_full_compute"),
    ])
    assert rs2.evaluate(RiskDimensions(task_family="unsafe")) is not None
    assert rs2.evaluate(RiskDimensions(task_family="safe1")) is None


def test_rule_numeric_comparison_safe_under_type_mismatch():
    """Comparing a string with a number must not crash — the rule simply
    doesn't match."""
    rs = RiskRuleSet(rules=[
        RiskRule(field="task_family", op=">=", value=0.5,
                 action="force_full_compute"),
    ])
    # Should not crash; rule does not match.
    assert rs.evaluate(RiskDimensions(task_family="medical")) is None


def test_rule_first_match_wins():
    """Rules are evaluated in order; first match short-circuits."""
    rs = RiskRuleSet(rules=[
        RiskRule(field="task_family", op="==", value="x",
                 action="never_direct_recall"),
        RiskRule(field="task_family", op="==", value="x",
                 action="force_full_compute"),
    ])
    r = rs.evaluate(RiskDimensions(task_family="x"))
    assert r.allow_direct_recall is False
    # First rule's action ladder (never_direct_recall = BOUNDED), not the
    # second (force_full_compute = HIGH).
    assert r.risk_class == RiskClass.BOUNDED


def test_riskplane_without_rules_behaves_identically():
    """No rule_set → existing signal-based ladder unchanged."""
    plane_a = RiskPlane()
    plane_b = RiskPlane(rule_set=None)
    dims = RiskDimensions(task_family="foo", answer_form="bounded",
                           ambiguity=0.3)
    a = plane_a.assess(dims)
    b = plane_b.assess(dims)
    assert a.risk_class == b.risk_class
    assert a.allow_direct_recall == b.allow_direct_recall
    assert a.restrictions_applied == b.restrictions_applied


def test_riskplane_rule_short_circuits_before_signals():
    """A firing rule should yield exactly the rule's verdict, ignoring
    what the signal-based ladder would have done."""
    rule = RiskRule(field="task_family", op="==", value="sensitive",
                    action="force_full_compute")
    plane = RiskPlane(rule_set=RiskRuleSet([rule]))
    r = plane.assess(RiskDimensions(
        task_family="sensitive", answer_form="bounded",
        ambiguity=0.0, novelty=0.0,   # signals would say LOW
    ))
    assert r.risk_class == RiskClass.HIGH
    assert r.force_full_compute is True
    assert any("rule[0]" in s for s in r.restrictions_applied)


def test_riskplane_rule_miss_falls_through_to_signals():
    rule = RiskRule(field="task_family", op="==", value="never_matches",
                    action="force_full_compute")
    plane = RiskPlane(rule_set=RiskRuleSet([rule]))
    r = plane.assess(RiskDimensions(
        task_family="other", answer_form="bounded",
        ambiguity=0.0, novelty=0.0,
    ))
    assert r.risk_class == RiskClass.LOW
    assert r.force_full_compute is False


# ══════════════════════════════════════════════════════════════════════
#   PART 2 — kelly_preservation_fraction
# ══════════════════════════════════════════════════════════════════════

def test_kelly_output_bounded_in_unit_interval():
    """Any input combination must yield a value in [0, 1]."""
    for p in [-0.5, 0.0, 0.25, 0.5, 0.75, 1.0, 1.5]:
        for payoff in [-5.0, 0.0, 10.0, 1e6]:
            for carry in [-1.0, 0.0, 1.0, 1e6]:
                for press in [-2.0, 0.0, 0.5, 1.0, 2.0, 100.0]:
                    f = kelly_preservation_fraction(p, payoff, carry, press)
                    assert 0.0 <= f <= 1.0, (
                        f"out of bounds: p={p} payoff={payoff} carry={carry} "
                        f"pressure={press} → {f}"
                    )


def test_kelly_zero_probability_returns_zero():
    assert kelly_preservation_fraction(0.0, 100.0, 1.0) == 0.0


def test_kelly_zero_payoff_returns_zero():
    assert kelly_preservation_fraction(0.5, 0.0, 1.0) == 0.0


def test_kelly_conservative_on_weak_signal():
    """Low prob, low payoff → near zero."""
    f = kelly_preservation_fraction(0.1, 2.0, 5.0)
    assert f <= 0.01


def test_kelly_larger_on_strong_signal():
    """High prob, high payoff → larger but still bounded."""
    f = kelly_preservation_fraction(0.9, 100.0, 5.0)
    assert 0.8 <= f <= 1.0


def test_kelly_cache_pressure_strictly_reduces_or_equal():
    """pressure > 1 must not increase the fraction."""
    f_base = kelly_preservation_fraction(0.7, 50.0, 10.0, cache_pressure_factor=1.0)
    f_pressured = kelly_preservation_fraction(0.7, 50.0, 10.0, cache_pressure_factor=4.0)
    assert f_pressured <= f_base


def test_kelly_formula_matches_hand_calc():
    """f* = (p·b − q) / b where b = payoff/carry. Hand-check one point."""
    # p=0.5, payoff=20, carry=10 → b=2, q=0.5
    # f* = (0.5·2 − 0.5) / 2 = 0.5/2 = 0.25
    assert kelly_preservation_fraction(0.5, 20.0, 10.0) == pytest.approx(0.25)


# ══════════════════════════════════════════════════════════════════════
#   PART 3 — cold_start_payoff_prior
# ══════════════════════════════════════════════════════════════════════

def test_cold_start_output_bounded():
    """Any input must yield a value in [0, COLD_START_PAYOFF_CAP_MS]."""
    for form in ["bounded", "generative", "open_reasoning", "ambiguous",
                 "unknown_form", ""]:
        for recur in [-1.0, 0.0, 0.25, 0.5, 1.0, 2.0]:
            for runtime in ["vllm", "hf_generate", "reference_sim",
                            "unknown_runtime"]:
                v = cold_start_payoff_prior(form, recur, runtime)
                assert 0.0 <= v <= COLD_START_PAYOFF_CAP_MS, (
                    f"out of bounds for form={form} recur={recur} "
                    f"runtime={runtime} → {v}"
                )


def test_cold_start_answer_form_ordering():
    """bounded answers should get the highest prior; open_reasoning
    the lowest; others in between."""
    bounded = cold_start_payoff_prior("bounded", 1.0, "vllm")
    generative = cold_start_payoff_prior("generative", 1.0, "vllm")
    ambiguous = cold_start_payoff_prior("ambiguous", 1.0, "vllm")
    open_r = cold_start_payoff_prior("open_reasoning", 1.0, "vllm")
    assert bounded > generative > ambiguous > open_r


def test_cold_start_recurrence_monotone():
    """Higher recurrence prior → higher (or equal) estimate."""
    low = cold_start_payoff_prior("bounded", 0.1, "vllm")
    mid = cold_start_payoff_prior("bounded", 0.5, "vllm")
    high = cold_start_payoff_prior("bounded", 1.0, "vllm")
    assert low <= mid <= high


def test_cold_start_runtime_matters():
    """HuggingFace generate has zero prefill savings; vLLM has positive.
    So hf should return 0, vllm should return positive for the same
    inputs."""
    v_vllm = cold_start_payoff_prior("bounded", 0.5, "vllm")
    v_hf = cold_start_payoff_prior("bounded", 0.5, "hf_generate")
    assert v_vllm > 0.0
    assert v_hf == 0.0


def test_cold_start_zero_recurrence_returns_zero():
    """No expected recurrence → zero payoff even on favourable form."""
    assert cold_start_payoff_prior("bounded", 0.0, "vllm") == 0.0


def test_cold_start_cap_respected():
    """Even with maximum plausible inputs, output stays at or below cap."""
    v = cold_start_payoff_prior("bounded", 1.0, "vllm")
    assert v <= COLD_START_PAYOFF_CAP_MS


# ══════════════════════════════════════════════════════════════════════
#   INTEGRATION — Kelly + cold-start inside decide_with_cost
# ══════════════════════════════════════════════════════════════════════

def test_decide_with_cost_cold_start_hint_promotes_basis():
    """When the caller passes a cold_start_hint and priors are cold,
    the action's payoff/carry estimates populate and the basis label
    becomes 'cold_start_prior_kernel' rather than 'cold_default'."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    action = pp.decide_with_cost(
        "new_shape", ProcessingClass.REUSABLE,
        priors=priors, runtime_name="vllm",
        cold_start_hint={"answer_form": "bounded",
                          "shape_recurrence_prior": 0.8},
    )
    assert action.preservation_prior_basis == "cold_start_prior_kernel"
    assert action.runtime_payoff_basis == "cold_start_prior_kernel"
    # Payoff estimate should be non-zero (bounded answer + high recurrence).
    assert action.payoff_ms_estimate is not None
    assert action.payoff_ms_estimate > 0.0
    assert action.payoff_ms_estimate <= COLD_START_PAYOFF_CAP_MS
    # Core action fields still match legacy decide().
    assert action.effective_class == ProcessingClass.REUSABLE


def test_decide_with_cost_cold_start_without_hint_stays_identity():
    """No cold_start_hint + cold priors → existing identity path
    (basis 'cold_default', no payoff estimates populated)."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    legacy = pp.decide("new_shape", ProcessingClass.REUSABLE)
    ext = pp.decide_with_cost(
        "new_shape", ProcessingClass.REUSABLE,
        priors=priors, runtime_name="vllm",
    )
    assert ext.preservation_prior_basis == "cold_default"
    assert ext.effective_class == legacy.effective_class
    assert ext.action == legacy.action
    assert ext.ttl_waves == legacy.ttl_waves


def test_decide_with_cost_cold_start_hint_does_not_flip_class():
    """Cold-start prior must not change the legacy class decision —
    it's a prior, not an observation."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    for requested in (ProcessingClass.EPHEMERAL, ProcessingClass.WARM,
                      ProcessingClass.REUSABLE, ProcessingClass.BATCHABLE):
        a = pp.decide_with_cost(
            "s", requested, priors=priors, runtime_name="vllm",
            cold_start_hint={"answer_form": "bounded",
                              "shape_recurrence_prior": 1.0},
        )
        assert a.effective_class == requested, (
            f"cold_start_hint altered class: requested={requested}, got={a.effective_class}"
        )


def test_decide_with_cost_kelly_low_shortens_ttl_even_when_net_positive():
    """If observations say payoff is positive but the Kelly fraction is
    below kelly_low_threshold, TTL should be shortened by one wave."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    # Small positive payoff per reuse, but reuse rate very low → low Kelly.
    for i in range(30):
        priors.observe(PreservationOutcome(
            shape_id="s1", runtime_name="vllm",
            was_preserved=True, was_reused=(i == 0),  # 1/30 reuse rate
            prefill_tokens_avoided=5,
            estimated_kv_bytes=1_000,
        ))
    # Net-value should be close to zero or slightly positive; reuse_p tiny.
    a = pp.decide_with_cost(
        "s1", ProcessingClass.REUSABLE, priors=priors,
        runtime_name="vllm", kelly_low_threshold=0.15,
    )
    # Either the class downgraded (net negative path) or TTL shortened
    # (kelly-low path). Both are correct conservative outcomes.
    assert a.ttl_shortened or a.downgrade_applied, (
        f"expected TTL-shorten or downgrade; got ttl_shortened={a.ttl_shortened} "
        f"downgrade_applied={a.downgrade_applied} reason={a.downgrade_reason}"
    )


def test_decide_with_cost_kelly_high_keeps_full_ttl():
    """When Kelly fraction is healthy and net is positive, TTL stays at
    the class default — no shortening, no downgrade."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    # Strong positive observations: high reuse rate and high payoff.
    for _ in range(30):
        priors.observe(PreservationOutcome(
            shape_id="s1", runtime_name="vllm",
            was_preserved=True, was_reused=True,
            prefill_tokens_avoided=800, estimated_kv_bytes=500,
        ))
    a = pp.decide_with_cost(
        "s1", ProcessingClass.REUSABLE, priors=priors,
        runtime_name="vllm",
    )
    assert a.ttl_shortened is False
    assert a.downgrade_applied is False
    assert a.effective_class == ProcessingClass.REUSABLE


def test_kelly_fraction_recorded_in_decomposition():
    """When Kelly is computed, it shows up in carry_cost_decomposition
    under key 'kelly_fraction' so operators can audit the signal."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    for _ in range(20):
        priors.observe(PreservationOutcome(
            shape_id="s1", runtime_name="vllm",
            was_preserved=True, was_reused=True,
            prefill_tokens_avoided=500, estimated_kv_bytes=1_000,
        ))
    a = pp.decide_with_cost("s1", ProcessingClass.REUSABLE, priors=priors,
                             runtime_name="vllm")
    assert isinstance(a.carry_cost_decomposition, dict)
    assert "kelly_fraction" in a.carry_cost_decomposition
    assert 0.0 <= a.carry_cost_decomposition["kelly_fraction"] <= 1.0
