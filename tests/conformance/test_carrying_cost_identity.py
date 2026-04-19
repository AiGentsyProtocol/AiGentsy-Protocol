"""Identity test for PreservationPolicy.decide_with_cost().

Contract: when priors are absent (None) or empty for a (shape, runtime)
pair, decide_with_cost() must return an action whose core fields are
byte-identical to decide(). Only the additive metadata fields
(preservation_prior_basis and the optional estimate fields) may differ.

Also verifies that once priors have observations, a cost-based
downgrade can fire — so the additive path is live, not dead.
"""

from __future__ import annotations

import pytest

from hoverstack.memory_plane import MemoryPlane
from hoverstack.preservation_policy import PreservationAction, PreservationPolicy
from hoverstack.primitives import ComputationalShape
from hoverstack.processing_class import ProcessingClass
from hoverstack.runtime_priors import PreservationOutcome, RuntimePriors


def _shape(sid):
    return ComputationalShape(
        shape_id=sid, feature_vector=[0.5] * 8 + [0.0] * 8,
        description=sid, base_V=1.0, base_E=0.5, base_L=0.25,
    )


def _core_fields(action: PreservationAction) -> dict:
    """Legacy/core fields that must be identical for identity."""
    return {
        "action": action.action,
        "ttl_waves": action.ttl_waves,
        "reuse_candidate": action.reuse_candidate,
        "fold_candidate": action.fold_candidate,
        "downgrade_applied": action.downgrade_applied,
        "effective_class": action.effective_class,
        "reason": action.reason,
    }


@pytest.mark.parametrize("pc", [
    ProcessingClass.EPHEMERAL,
    ProcessingClass.WARM,
    ProcessingClass.REUSABLE,
    ProcessingClass.BATCHABLE,
])
def test_identity_with_priors_none(pc):
    pp = PreservationPolicy()
    legacy = pp.decide("s1", pc)
    ext = pp.decide_with_cost("s1", pc, priors=None, runtime_name="vllm")
    assert _core_fields(legacy) == _core_fields(ext)
    assert ext.preservation_prior_basis == "none"


@pytest.mark.parametrize("pc", [
    ProcessingClass.EPHEMERAL,
    ProcessingClass.WARM,
    ProcessingClass.REUSABLE,
    ProcessingClass.BATCHABLE,
])
def test_identity_with_empty_priors(pc):
    pp = PreservationPolicy()
    priors = RuntimePriors()  # empty
    legacy = pp.decide("s1", pc)
    ext = pp.decide_with_cost("s1", pc, priors=priors, runtime_name="vllm")
    assert _core_fields(legacy) == _core_fields(ext)
    assert ext.preservation_prior_basis == "cold_default"


def test_identity_across_feedback_downgrade():
    """Even when the legacy feedback loop fires a downgrade, the extended
    path must mirror it exactly when priors are empty."""
    pp_legacy = PreservationPolicy()
    pp_ext = PreservationPolicy()
    priors = RuntimePriors()

    # Force a legacy downgrade by recording many preservations with no reuse.
    for _ in range(8):
        pp_legacy.record_preservation("s1", 3)
        pp_ext.record_preservation("s1", 3)

    legacy = pp_legacy.decide("s1", ProcessingClass.REUSABLE)
    ext = pp_ext.decide_with_cost("s1", ProcessingClass.REUSABLE,
                                    priors=priors, runtime_name="vllm")
    assert _core_fields(legacy) == _core_fields(ext)


def test_cost_based_downgrade_fires_after_hysteresis_confirmation():
    """Once priors observe zero reuse, net_value goes negative. With
    hysteresis enabled, the class only flips after N consecutive
    negative samples. First 2 calls shorten TTL; 3rd confirms and
    downgrades one class step."""
    pp = PreservationPolicy()
    priors = RuntimePriors()
    for _ in range(40):
        priors.observe(PreservationOutcome(
            shape_id="s1", runtime_name="vllm",
            was_preserved=True, was_reused=False,
            prefill_tokens_avoided=0, estimated_kv_bytes=10_000,
        ))
    assert priors.net_value_estimate_ms("s1", "vllm", expected_reuses=3) < 0

    legacy = pp.decide("s1", ProcessingClass.REUSABLE)
    assert legacy.effective_class == ProcessingClass.REUSABLE

    # First call: 1 consecutive negative < 3 threshold → TTL shortened,
    # class retained.
    ext1 = pp.decide_with_cost("s1", ProcessingClass.REUSABLE,
                                 priors=priors, runtime_name="vllm",
                                 expected_reuses=3)
    assert ext1.effective_class == ProcessingClass.REUSABLE
    assert ext1.ttl_shortened is True
    assert ext1.downgrade_applied is False
    assert "awaiting_confirm" in (ext1.downgrade_reason or "")

    # Second call: 2 consecutive negatives.
    ext2 = pp.decide_with_cost("s1", ProcessingClass.REUSABLE,
                                 priors=priors, runtime_name="vllm",
                                 expected_reuses=3)
    assert ext2.effective_class == ProcessingClass.REUSABLE
    assert ext2.ttl_shortened is True
    assert ext2.downgrade_applied is False

    # Third call: 3 consecutive negatives → confirmed → class downgrade.
    ext3 = pp.decide_with_cost("s1", ProcessingClass.REUSABLE,
                                 priors=priors, runtime_name="vllm",
                                 expected_reuses=3)
    assert ext3.effective_class == ProcessingClass.WARM
    assert ext3.downgrade_applied is True
    assert ext3.downgrade_from == ProcessingClass.REUSABLE
    assert "confirmed" in (ext3.downgrade_reason or "")
    assert ext3.preservation_prior_basis == "per_shape_runtime_model"
    assert ext3.net_value_estimate_ms is not None
    assert ext3.net_value_estimate_ms < 0


def test_memory_plane_priors_absent_keeps_legacy_behavior():
    """End-to-end on MemoryPlane: when observe_outcome() is never called,
    the plane snapshot and decisions match the legacy path."""
    mp = MemoryPlane(shapes=[_shape("a"), _shape("b")])
    for _ in range(5):
        cr_a = mp.classify(_shape("a"), ["a", "a", "b"])
        legacy = mp.preservation.decide("a", cr_a.processing_class)
        ext = mp.preservation.decide_with_cost(
            "a", cr_a.processing_class,
            priors=mp.priors, runtime_name="vllm",
        )
        assert _core_fields(legacy) == _core_fields(ext)
        if legacy.action == "preserve":
            mp.record_preservation("a", legacy.ttl_waves)
        mp.record_outcome("a", 1.0, 1.0, 0)

    # Snapshot is a strict superset — includes "priors" with zero entries.
    snap = mp.snapshot()
    assert "priors" in snap
    assert snap["priors"]["entries"] == 0
