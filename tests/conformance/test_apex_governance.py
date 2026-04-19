"""Apex 8-plane governance tests.

Covers the three new planes (Risk, Recall, Delta), their ledger behaviour,
the no-regression contract when the apex planes are not consulted, and
the end-to-end decision-ladder integration.

Rule of thumb: every test either proves a safety behaviour (falls back
to full compute when uncertain; risk blocks unsafe recall) or proves
that bypassing the apex planes leaves HoverStack's legacy behaviour
untouched.
"""

from __future__ import annotations

import json

import pytest

from hoverstack.delta_plane import (
    DeltaDecision, DeltaLedger, DeltaMode, DeltaPolicy,
    DeltaPolicyConfig, DeltaSignals,
)
from hoverstack.memory_plane import MemoryPlane
from hoverstack.preservation_policy import PreservationPolicy
from hoverstack.primitives import ComputationalShape
from hoverstack.processing_class import ProcessingClass
from hoverstack.recall_plane import (
    RecallDecision, RecallLedger, RecallMode, RecallObject, RecallPolicy,
    RecallPolicyConfig,
)
from hoverstack.risk_plane import (
    RiskAssessment, RiskClass, RiskDimensions, RiskPlane, RiskPolicyConfig,
)
from hoverstack.runtime_adapter import (
    RuntimeCapabilities, RuntimeResponse,
)


# ══════════════════════════════════════════════════════════════════════
#   RISK PLANE
# ══════════════════════════════════════════════════════════════════════

def test_risk_low_allows_all_avoidance_paths():
    rp = RiskPlane()
    r = rp.assess(RiskDimensions(
        task_family="contract_review", answer_form="bounded",
        ambiguity=0.1, novelty=0.1, stale_context_risk=0.1,
    ))
    assert r.risk_class == RiskClass.LOW
    assert r.allow_direct_recall is True
    assert r.allow_structural_recall is True
    assert r.allow_delta_compute is True
    assert r.force_full_compute is False


def test_risk_open_reasoning_forces_elevated_min():
    rp = RiskPlane()
    r = rp.assess(RiskDimensions(
        task_family="adhoc_reason", answer_form="open_reasoning",
        ambiguity=0.1,  # low signal, but answer_form floor dominates
    ))
    assert r.risk_class in {RiskClass.ELEVATED, RiskClass.HIGH}
    assert r.allow_direct_recall is False


def test_risk_critical_domain_forces_high():
    rp = RiskPlane()
    r = rp.assess(RiskDimensions(
        task_family="diagnosis", answer_form="bounded",
        domain_criticality="medical",
    ))
    assert r.risk_class == RiskClass.HIGH
    assert r.force_full_compute is True
    assert r.allow_direct_recall is False


def test_risk_family_override_never_direct_recall():
    cfg = RiskPolicyConfig(never_direct_recall_families={"sensitive_family"})
    rp = RiskPlane(cfg)
    r = rp.assess(RiskDimensions(
        task_family="sensitive_family", answer_form="bounded",
        ambiguity=0.0, novelty=0.0,
    ))
    assert r.allow_direct_recall is False
    assert any("no_direct_recall" in s for s in r.restrictions_applied)


def test_risk_family_override_force_full_compute():
    cfg = RiskPolicyConfig(always_full_compute_families={"critical_family"})
    rp = RiskPlane(cfg)
    r = rp.assess(RiskDimensions(
        task_family="critical_family", answer_form="bounded",
        ambiguity=0.0,
    ))
    assert r.force_full_compute is True
    assert r.allow_direct_recall is False
    assert r.allow_structural_recall is False
    assert r.allow_delta_compute is False


def test_risk_operator_override_dominates():
    rp = RiskPlane()
    r = rp.assess(RiskDimensions(
        task_family="contract_review", answer_form="bounded",
        ambiguity=0.0, operator_override="high_risk",
    ))
    assert r.risk_class == RiskClass.HIGH


# ══════════════════════════════════════════════════════════════════════
#   RECALL PLANE
# ══════════════════════════════════════════════════════════════════════

def _low_risk(family="f") -> RiskAssessment:
    return RiskPlane().assess(RiskDimensions(task_family=family,
                                               answer_form="bounded"))


def _elevated_risk(family="f") -> RiskAssessment:
    return RiskPlane().assess(RiskDimensions(task_family=family,
                                               answer_form="open_reasoning"))


def _high_risk(family="f") -> RiskAssessment:
    return RiskPlane().assess(RiskDimensions(task_family=family,
                                               domain_criticality="medical"))


def test_recall_no_object_returns_full_compute():
    rp = RecallPolicy()
    d = rp.decide("f", _low_risk(), recall_object=None)
    assert d.mode == RecallMode.FULL
    assert d.fallback_triggered is False


def test_recall_stale_object_falls_back_to_full():
    rp = RecallPolicy()
    ro = RecallObject(shape_id="f", recall_confidence=0.95,
                      freshness_score=0.1)
    d = rp.decide("f", _low_risk(), recall_object=ro)
    assert d.mode == RecallMode.FULL
    assert d.fallback_triggered is True
    assert d.fallback_reason == "stale"


def test_recall_direct_mode_when_low_risk_and_high_confidence():
    rp = RecallPolicy()
    ro = RecallObject(shape_id="f", recall_confidence=0.9,
                      freshness_score=0.9)
    d = rp.decide("f", _low_risk(), recall_object=ro)
    assert d.mode == RecallMode.DIRECT


def test_recall_elevated_risk_blocks_direct_allows_structural():
    rp = RecallPolicy()
    ro = RecallObject(shape_id="f", recall_confidence=0.9,
                      freshness_score=0.9)
    d = rp.decide("f", _elevated_risk(), recall_object=ro)
    assert d.mode == RecallMode.STRUCTURAL
    assert d.fallback_triggered is True
    assert d.fallback_reason == "risk_blocked_direct"


def test_recall_high_risk_forces_full_compute():
    rp = RecallPolicy()
    ro = RecallObject(shape_id="f", recall_confidence=0.99,
                      freshness_score=0.99)
    d = rp.decide("f", _high_risk(), recall_object=ro)
    assert d.mode == RecallMode.FULL


def test_recall_medium_confidence_becomes_delta():
    rp = RecallPolicy()
    ro = RecallObject(shape_id="f", recall_confidence=0.55,
                      freshness_score=0.9)
    d = rp.decide("f", _low_risk(), recall_object=ro)
    assert d.mode == RecallMode.DELTA


def test_recall_low_confidence_full_compute():
    rp = RecallPolicy()
    ro = RecallObject(shape_id="f", recall_confidence=0.2,
                      freshness_score=0.9)
    d = rp.decide("f", _low_risk(), recall_object=ro)
    assert d.mode == RecallMode.FULL


def test_recall_reversion_blocks_direct_recall():
    ledger = RecallLedger()
    for _ in range(5):
        ledger.record("f", "vllm", success=False, reverted=True)
    rp = RecallPolicy(ledger=ledger)
    ro = RecallObject(shape_id="f", recall_confidence=0.99, freshness_score=0.99)
    d = rp.decide("f", _low_risk(), recall_object=ro, runtime_name="vllm")
    # Direct blocked by reversion history → falls through to structural.
    assert d.mode == RecallMode.STRUCTURAL


def test_recall_ledger_records_and_reports():
    ledger = RecallLedger()
    for i in range(5):
        ledger.record("f", "vllm", success=(i < 3), reverted=(i >= 3),
                       payoff_ms=10.0 if i < 3 else 0.0)
    s = ledger.summary()
    assert s["total_attempts"] == 5
    assert s["total_successes"] == 3
    assert s["total_reversions"] == 2
    assert s["top_positive"][0]["shape_id"] == "f"


# ══════════════════════════════════════════════════════════════════════
#   DELTA PLANE
# ══════════════════════════════════════════════════════════════════════

def test_delta_risk_denial_forces_full():
    policy = DeltaPolicy()
    r = _high_risk()
    sig = DeltaSignals(shape_stable=True, answer_form_bounded=True,
                       changed_tail_ratio=0.05)
    d = policy.decide(sig, r)
    assert d.mode == DeltaMode.FULL_COMPUTE_REQUIRED
    assert d.fallback_reason == "risk_denied"


def test_delta_unstable_shape_forces_full():
    policy = DeltaPolicy()
    d = policy.decide(DeltaSignals(shape_stable=False,
                                     answer_form_bounded=True),
                      _low_risk())
    assert d.mode == DeltaMode.FULL_COMPUTE_REQUIRED
    assert d.fallback_reason == "unstable_shape"


def test_delta_unbounded_answer_forces_full():
    policy = DeltaPolicy()
    d = policy.decide(DeltaSignals(shape_stable=True,
                                     answer_form_bounded=False),
                      _low_risk())
    assert d.mode == DeltaMode.FULL_COMPUTE_REQUIRED
    assert d.fallback_reason == "unbounded_answer"


def test_delta_high_ambiguity_forces_full():
    policy = DeltaPolicy()
    d = policy.decide(DeltaSignals(shape_stable=True,
                                     answer_form_bounded=True,
                                     ambiguity=0.9),
                      _low_risk())
    assert d.mode == DeltaMode.FULL_COMPUTE_REQUIRED
    assert d.fallback_reason == "ambiguity_high"


def test_delta_no_change_returns_no_delta_needed():
    policy = DeltaPolicy()
    d = policy.decide(DeltaSignals(shape_stable=True, answer_form_bounded=True,
                                     changed_tail_ratio=0.0,
                                     changed_field_count=0,
                                     changed_context_blocks=0),
                      _low_risk())
    assert d.mode == DeltaMode.NO_DELTA_NEEDED


def test_delta_tail_only_selected_for_small_tail():
    policy = DeltaPolicy()
    d = policy.decide(DeltaSignals(shape_stable=True, answer_form_bounded=True,
                                     changed_tail_ratio=0.1,
                                     changed_field_count=0,
                                     changed_context_blocks=0),
                      _low_risk())
    assert d.mode == DeltaMode.TAIL_ONLY


def test_delta_field_only_selected_for_bounded_fields():
    policy = DeltaPolicy()
    d = policy.decide(DeltaSignals(shape_stable=True, answer_form_bounded=True,
                                     changed_tail_ratio=0.3,
                                     changed_field_count=1,
                                     total_field_count=10,
                                     changed_context_blocks=0),
                      _low_risk())
    assert d.mode == DeltaMode.FIELD_ONLY


def test_delta_context_patch_selected_for_bounded_blocks():
    policy = DeltaPolicy()
    d = policy.decide(DeltaSignals(shape_stable=True, answer_form_bounded=True,
                                     changed_tail_ratio=0.3,
                                     changed_field_count=0,
                                     changed_context_blocks=1,
                                     total_context_blocks=4),
                      _low_risk())
    assert d.mode == DeltaMode.CONTEXT_PATCH


def test_delta_too_large_falls_back_to_full():
    policy = DeltaPolicy(DeltaPolicyConfig(context_patch_max_blocks_pct=0.2))
    d = policy.decide(DeltaSignals(shape_stable=True, answer_form_bounded=True,
                                     changed_tail_ratio=0.9,
                                     changed_field_count=5,
                                     total_field_count=6,
                                     changed_context_blocks=3,
                                     total_context_blocks=4),
                      _low_risk())
    assert d.mode == DeltaMode.FULL_COMPUTE_REQUIRED
    assert d.fallback_triggered is True


def test_delta_ledger_records_and_reports():
    ledger = DeltaLedger()
    for i in range(4):
        ledger.record("f", "vllm", success=(i < 3),
                       fallback=(i == 3), compute_avoided_ms=20.0)
    s = ledger.summary()
    assert s["total_attempts"] == 4
    assert s["total_successes"] == 3
    assert s["total_fallbacks"] == 1
    assert s["top_positive"][0]["shape_id"] == "f"


# ══════════════════════════════════════════════════════════════════════
#   NO-REGRESSION: apex planes exist but aren't consulted
# ══════════════════════════════════════════════════════════════════════

def test_memory_plane_snapshot_is_strict_superset():
    """Legacy keys still present; new apex keys added with empty state."""
    mp = MemoryPlane()
    snap = mp.snapshot()
    for k in ("preservation", "frequency", "shapes", "priors"):
        assert k in snap, f"legacy key {k} missing"
    for k in ("recall", "delta"):
        assert k in snap, f"apex key {k} missing"
        assert snap[k]["entries"] == 0
        assert snap[k]["total_attempts"] == 0


def test_hoverstamp_omits_apex_fields_when_absent():
    """If no apex plane populated the response, none of the apex fields
    appear in the HoverStamp payload."""
    caps = RuntimeCapabilities()
    resp = RuntimeResponse(
        output_text="x", output_tokens=1, success=True, total_ms=1.0,
        runtime_name="vllm",
    )
    fields = resp.hoverstamp_runtime_fields(caps)
    for k in (
        "risk_class", "risk_restrictions_applied",
        "recall_attempted", "recall_mode", "recall_confidence",
        "recall_prior_basis", "recall_fallback_triggered",
        "recall_fallback_reason", "delta_mode", "delta_size_estimate",
        "delta_fallback_triggered", "delta_fallback_reason",
        "compute_avoided_estimate",
    ):
        assert k not in fields, f"apex field {k} leaked when absent"


def test_hoverstamp_emits_apex_fields_when_populated():
    """When the harness populates apex fields, they flow into the stamp."""
    caps = RuntimeCapabilities()
    resp = RuntimeResponse(
        output_text="x", output_tokens=1, success=True, total_ms=1.0,
        runtime_name="vllm",
        risk_class="low_risk",
        risk_restrictions_applied=["family=f:no_direct_recall"],
        recall_attempted=True,
        recall_mode="structural_recall",
        recall_confidence=0.82,
        recall_prior_basis="per_shape_runtime_model",
        recall_fallback_triggered=True,
        recall_fallback_reason="risk_blocked_direct",
        delta_mode="tail_only_delta",
        delta_size_estimate=0.1,
        delta_fallback_triggered=False,
        compute_avoided_estimate=38.4,
    )
    fields = resp.hoverstamp_runtime_fields(caps)
    assert fields["risk_class"] == "low_risk"
    assert fields["recall_mode"] == "structural_recall"
    assert fields["recall_confidence"] == 0.82
    assert fields["recall_fallback_triggered"] is True
    assert fields["recall_fallback_reason"] == "risk_blocked_direct"
    assert fields["delta_mode"] == "tail_only_delta"
    assert fields["delta_size_estimate"] == 0.1
    assert fields["compute_avoided_estimate"] == 38.4


# ══════════════════════════════════════════════════════════════════════
#   DECISION LADDER END-TO-END
# ══════════════════════════════════════════════════════════════════════

def test_decision_ladder_end_to_end_recall_path():
    """A low-risk, stable-shape, high-confidence cell ends up on the
    direct_recall path; ledger records it."""
    mp = MemoryPlane()
    risk = mp.risk_plane.assess(RiskDimensions(
        task_family="contract_review", answer_form="bounded",
        ambiguity=0.1, novelty=0.05,
    ))
    ro = RecallObject(shape_id="contract_review",
                      recall_confidence=0.92, freshness_score=0.9,
                      answer_form="bounded", runtime_name="vllm")
    recall = mp.recall_policy.decide("contract_review", risk, ro,
                                       runtime_name="vllm")
    assert recall.mode == RecallMode.DIRECT
    delta = mp.delta_policy.decide(
        DeltaSignals(shape_stable=True, answer_form_bounded=True,
                     changed_tail_ratio=0.05), risk)
    assert delta.mode == DeltaMode.TAIL_ONLY

    # Post-execution: record outcomes.
    mp.recall_policy.ledger.record("contract_review", "vllm",
                                     success=True, reverted=False,
                                     payoff_ms=35.0)
    mp.delta_policy.ledger.record("contract_review", "vllm",
                                    success=True, fallback=False,
                                    compute_avoided_ms=12.0)
    snap = mp.snapshot()
    assert snap["recall"]["total_successes"] == 1
    assert snap["delta"]["total_successes"] == 1


def test_decision_ladder_end_to_end_risk_blocks_recall():
    """A critical-domain cell is routed to full_compute regardless of
    recall confidence."""
    mp = MemoryPlane()
    risk = mp.risk_plane.assess(RiskDimensions(
        task_family="clinical_qa", answer_form="bounded",
        domain_criticality="medical",
    ))
    ro = RecallObject(shape_id="clinical_qa", recall_confidence=0.99,
                      freshness_score=0.99)
    recall = mp.recall_policy.decide("clinical_qa", risk, ro)
    assert recall.mode == RecallMode.FULL
    delta = mp.delta_policy.decide(
        DeltaSignals(shape_stable=True, answer_form_bounded=True,
                     changed_tail_ratio=0.05), risk)
    assert delta.mode == DeltaMode.FULL_COMPUTE_REQUIRED
    assert delta.fallback_reason == "risk_denied"
