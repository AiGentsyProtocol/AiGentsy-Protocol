"""Delta Plane.

Decides the minimum novel fragment that actually requires fresh compute.
Pure policy — no I/O. Always fallback-safe: if any signal is uncertain
or the trust/risk plane forbids delta, the plane returns
`full_compute_required` and records the fallback.

Delta modes (narrowest → widest):
    no_delta_needed         — nothing changed; direct/structural recall applies
    tail_only_delta         — only the prompt tail changed
    field_only_delta        — a bounded set of fields changed
    context_patch_delta     — a context block changed but shape is stable
    full_compute_required   — change too large or signals uncertain

A DeltaLedger tracks per-(shape, runtime, model) attempts and payoff so
the attribution plane can surface top_positive_delta_shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .risk_plane import RiskAssessment


class DeltaMode(str, Enum):
    NO_DELTA_NEEDED = "no_delta_needed"
    TAIL_ONLY = "tail_only_delta"
    FIELD_ONLY = "field_only_delta"
    CONTEXT_PATCH = "context_patch_delta"
    FULL_COMPUTE_REQUIRED = "full_compute_required"


@dataclass
class DeltaSignals:
    """What the caller believes has changed about this cell vs prior.

    All fields default to a conservative 'no prior' state so a caller
    that supplies nothing gets full_compute_required."""
    changed_tail_ratio: float = 1.0      # 0 = identical tail, 1 = fully new
    changed_field_count: int = 0
    total_field_count: int = 0
    changed_context_blocks: int = 0
    total_context_blocks: int = 0
    ambiguity: float = 0.0
    shape_stable: bool = False
    answer_form_bounded: bool = False


@dataclass
class DeltaDecision:
    mode: DeltaMode
    size_estimate: float       # 0-1 fraction of full compute to run
    reason: str
    fallback_triggered: bool = False
    fallback_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "size_estimate": round(self.size_estimate, 4),
            "reason": self.reason,
            "fallback_triggered": self.fallback_triggered,
            "fallback_reason": self.fallback_reason,
        }


@dataclass
class DeltaPolicyConfig:
    # Ratios / counts below these → narrower delta modes.
    tail_only_max_ratio: float = 0.25
    field_only_max_ratio: float = 0.35
    context_patch_max_blocks_pct: float = 0.50

    # Ambiguity above this forbids delta.
    ambiguity_max: float = 0.5


@dataclass
class _DeltaShapeStats:
    attempts: int = 0
    successes: int = 0
    fallbacks: int = 0
    total_compute_avoided_ms: float = 0.0

    def record(self, success: bool, fallback: bool, compute_avoided_ms: float) -> None:
        self.attempts += 1
        if success:
            self.successes += 1
            self.total_compute_avoided_ms += compute_avoided_ms
        if fallback:
            self.fallbacks += 1

    def to_dict(self) -> dict:
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "fallbacks": self.fallbacks,
            "total_compute_avoided_ms": round(self.total_compute_avoided_ms, 3),
            "success_rate": round(self.successes / max(1, self.attempts), 4),
            "fallback_rate": round(self.fallbacks / max(1, self.attempts), 4),
        }


class DeltaLedger:
    def __init__(self) -> None:
        self._stats: Dict[Tuple[str, str, str], _DeltaShapeStats] = {}

    @staticmethod
    def _key(shape_id: str, runtime_name: str, model_name: str = "") -> Tuple[str, str, str]:
        return (shape_id, runtime_name, model_name or "")

    def record(self, shape_id: str, runtime_name: str, success: bool,
               fallback: bool, compute_avoided_ms: float = 0.0,
               model_name: str = "") -> None:
        key = self._key(shape_id, runtime_name, model_name)
        stats = self._stats.setdefault(key, _DeltaShapeStats())
        stats.record(success, fallback, compute_avoided_ms)

    def top_positive_delta_shapes(self, k: int = 5) -> List[Dict[str, Any]]:
        entries = []
        for (sid, rt, mdl), rec in self._stats.items():
            if rec.successes == 0:
                continue
            entries.append({
                "shape_id": sid, "runtime_name": rt, "model_name": mdl,
                **rec.to_dict(),
            })
        entries.sort(key=lambda e: e["total_compute_avoided_ms"], reverse=True)
        return entries[:k]

    def summary(self) -> Dict[str, Any]:
        total_attempts = sum(s.attempts for s in self._stats.values())
        total_successes = sum(s.successes for s in self._stats.values())
        total_fallbacks = sum(s.fallbacks for s in self._stats.values())
        return {
            "entries": len(self._stats),
            "total_attempts": total_attempts,
            "total_successes": total_successes,
            "total_fallbacks": total_fallbacks,
            "global_success_rate": round(
                total_successes / max(1, total_attempts), 4),
            "global_fallback_rate": round(
                total_fallbacks / max(1, total_attempts), 4),
            "top_positive": self.top_positive_delta_shapes(5),
        }


class DeltaPolicy:
    """Selects the narrowest safe delta mode, or falls back to full compute."""

    def __init__(self, config: Optional[DeltaPolicyConfig] = None,
                 ledger: Optional[DeltaLedger] = None) -> None:
        self._cfg = config or DeltaPolicyConfig()
        self._ledger = ledger or DeltaLedger()

    @property
    def ledger(self) -> DeltaLedger:
        return self._ledger

    def decide(
        self,
        signals: DeltaSignals,
        risk: RiskAssessment,
    ) -> DeltaDecision:
        # Risk forbids delta outright.
        if not risk.allow_delta_compute:
            return DeltaDecision(
                mode=DeltaMode.FULL_COMPUTE_REQUIRED, size_estimate=1.0,
                reason=f"risk={risk.risk_class.value} forbids delta_compute",
                fallback_triggered=True,
                fallback_reason="risk_denied",
            )

        # Shape unstable or ambiguous → full compute.
        if not signals.shape_stable:
            return DeltaDecision(
                mode=DeltaMode.FULL_COMPUTE_REQUIRED, size_estimate=1.0,
                reason="shape not stable → full_compute_required",
                fallback_triggered=True, fallback_reason="unstable_shape",
            )
        if not signals.answer_form_bounded:
            return DeltaDecision(
                mode=DeltaMode.FULL_COMPUTE_REQUIRED, size_estimate=1.0,
                reason="answer form not bounded → full_compute_required",
                fallback_triggered=True, fallback_reason="unbounded_answer",
            )
        if signals.ambiguity > self._cfg.ambiguity_max:
            return DeltaDecision(
                mode=DeltaMode.FULL_COMPUTE_REQUIRED, size_estimate=1.0,
                reason=(
                    f"ambiguity {signals.ambiguity:.2f} > "
                    f"max {self._cfg.ambiguity_max} → full_compute_required"
                ),
                fallback_triggered=True, fallback_reason="ambiguity_high",
            )

        # Tail-only: tail ratio small and no field or block change.
        tail_small = signals.changed_tail_ratio <= self._cfg.tail_only_max_ratio
        no_fields = signals.changed_field_count == 0
        no_blocks = signals.changed_context_blocks == 0

        if signals.changed_tail_ratio <= 0.001 and no_fields and no_blocks:
            return DeltaDecision(
                mode=DeltaMode.NO_DELTA_NEEDED, size_estimate=0.0,
                reason="no change detected → no_delta_needed",
            )

        if tail_small and no_fields and no_blocks:
            return DeltaDecision(
                mode=DeltaMode.TAIL_ONLY, size_estimate=signals.changed_tail_ratio,
                reason=(
                    f"tail_only_delta: changed_tail_ratio "
                    f"{signals.changed_tail_ratio:.2f} ≤ "
                    f"{self._cfg.tail_only_max_ratio}"
                ),
            )

        # Field-only: bounded field change, no block change.
        total_fields = max(1, signals.total_field_count)
        field_ratio = signals.changed_field_count / total_fields
        if (signals.changed_field_count > 0 and no_blocks
                and field_ratio <= self._cfg.field_only_max_ratio):
            return DeltaDecision(
                mode=DeltaMode.FIELD_ONLY,
                size_estimate=field_ratio,
                reason=(
                    f"field_only_delta: {signals.changed_field_count}/"
                    f"{total_fields} fields changed (ratio "
                    f"{field_ratio:.2f} ≤ {self._cfg.field_only_max_ratio})"
                ),
            )

        # Context patch: limited block change.
        total_blocks = max(1, signals.total_context_blocks)
        block_pct = signals.changed_context_blocks / total_blocks
        if block_pct <= self._cfg.context_patch_max_blocks_pct:
            return DeltaDecision(
                mode=DeltaMode.CONTEXT_PATCH,
                size_estimate=block_pct,
                reason=(
                    f"context_patch_delta: {signals.changed_context_blocks}/"
                    f"{total_blocks} blocks changed (pct {block_pct:.2f})"
                ),
            )

        # Too much change — full compute.
        return DeltaDecision(
            mode=DeltaMode.FULL_COMPUTE_REQUIRED, size_estimate=1.0,
            reason="change exceeds all delta thresholds → full_compute_required",
            fallback_triggered=True, fallback_reason="change_too_large",
        )
