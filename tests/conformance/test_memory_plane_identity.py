"""Behavior-preservation test for MemoryPlane.

Rule for the Memory Plane refactor: absolutely no behavior drift vs the
existing ShapeMemoryGraph + FrequencyPolicy + PreservationPolicy path.

This test drives identical workloads through (a) the legacy direct-use
path and (b) the MemoryPlane facade, then asserts the outputs match
byte-for-byte on every observable surface.
"""

from __future__ import annotations

import pytest

from hoverstack.config import HoverConfig
from hoverstack.frequency_policy import FrequencyPolicy
from hoverstack.memory_plane import MemoryPlane
from hoverstack.preservation_policy import PreservationPolicy
from hoverstack.primitives import ComputationalShape
from hoverstack.shape_memory import ShapeMemoryGraph


def _shapes():
    return [
        ComputationalShape(shape_id="a", feature_vector=[0.9] * 8 + [0.0] * 8,
                           description="freq+sim", base_V=0.8, base_E=0.3, base_L=0.15),
        ComputationalShape(shape_id="b", feature_vector=[0.7, 0.6] * 4 + [0.0] * 8,
                           description="freq+mod", base_V=1.0, base_E=0.5, base_L=0.3),
        ComputationalShape(shape_id="c", feature_vector=[0.2] * 4 + [0.0] * 12,
                           description="rare+cheap", base_V=0.3, base_E=0.1, base_L=0.05),
    ]


WAVES = [
    ["a", "a", "b", "a", "b"],
    ["a", "b", "a", "a"],
    ["a", "b", "c"],
    ["a", "a", "b", "b", "c"],
]


def _drive_legacy():
    cfg = HoverConfig(seed=42, embedding_dim=16)
    sm = ShapeMemoryGraph(cfg)
    for s in _shapes():
        sm.register_shape(s)
    fp = FrequencyPolicy(sm)
    pp = PreservationPolicy()

    decisions = []
    for wi, wave in enumerate(WAVES):
        for sid in wave:
            shape = next(s for s in _shapes() if s.shape_id == sid)
            cr = fp.classify(shape, wave)
            action = pp.decide(sid, cr.processing_class)
            if action.action == "preserve":
                pp.record_preservation(sid, action.ttl_waves)
            sm.record_outcome(sid, 1.0, 1.0, wi)
            decisions.append({
                "sid": sid,
                "pc": action.effective_class.value,
                "action": action.action,
                "ttl": action.ttl_waves,
                "downgrade": action.downgrade_applied,
                "freq": round(cr.frequency_score, 6),
                "reuse": round(cr.reuse_potential, 6),
            })
        pp.tick_wave()
    return decisions, pp.snapshot(), sm.get_all_stats()


def _drive_plane():
    cfg = HoverConfig(seed=42, embedding_dim=16)
    mp = MemoryPlane(config=cfg, shapes=_shapes())

    decisions = []
    for wi, wave in enumerate(WAVES):
        for sid in wave:
            shape = next(s for s in _shapes() if s.shape_id == sid)
            cr = mp.classify(shape, wave)
            action = mp.decide_preservation(sid, cr.processing_class)
            if action.action == "preserve":
                mp.record_preservation(sid, action.ttl_waves)
            mp.record_outcome(sid, 1.0, 1.0, wi)
            decisions.append({
                "sid": sid,
                "pc": action.effective_class.value,
                "action": action.action,
                "ttl": action.ttl_waves,
                "downgrade": action.downgrade_applied,
                "freq": round(cr.frequency_score, 6),
                "reuse": round(cr.reuse_potential, 6),
            })
        mp.tick_wave()
    return decisions, mp.preservation_snapshot(), mp.shape_stats()


def test_memory_plane_matches_legacy_decisions():
    legacy_dec, _, _ = _drive_legacy()
    plane_dec, _, _ = _drive_plane()
    assert legacy_dec == plane_dec, (
        "MemoryPlane produced different decisions than the legacy path"
    )


def test_memory_plane_matches_preservation_snapshot():
    _, legacy_snap, _ = _drive_legacy()
    _, plane_snap, _ = _drive_plane()
    assert legacy_snap == plane_snap, (
        "MemoryPlane preservation snapshot diverged from PreservationPolicy"
    )


def test_memory_plane_matches_shape_stats():
    _, _, legacy_stats = _drive_legacy()
    _, _, plane_stats = _drive_plane()
    assert legacy_stats == plane_stats, (
        "MemoryPlane shape_stats diverged from ShapeMemoryGraph"
    )
