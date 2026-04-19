"""Trust / Risk Plane.

Decides how aggressively HoverStack is allowed to avoid fresh compute
for a given workload. Pure policy — no I/O, no runtime dependencies.
Always safe to disable: if the recall/delta planes never consult a
RiskAssessment, HoverStack's legacy behaviour is unchanged.

Four risk classes, ordered from most permissive to most restrictive:

    low_risk      — direct recall, structural recall, delta, all allowed
    bounded_risk  — structural recall + delta allowed; direct recall
                    restricted to very-high-confidence cases
    elevated_risk — structural recall only if confidence is very high;
                    delta allowed if tightly bounded; full compute
                    preferred on ambiguity
    high_risk     — recall disabled; reuse conservative; full compute
                    required unless explicit policy says otherwise

Risk is assessed from operational signals the caller provides in
`RiskDimensions`. Family-level overrides can force specific behaviour
regardless of the computed class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Set


class RiskClass(str, Enum):
    LOW = "low_risk"
    BOUNDED = "bounded_risk"
    ELEVATED = "elevated_risk"
    HIGH = "high_risk"


@dataclass
class RiskDimensions:
    """Inputs the caller supplies to risk evaluation.

    All fields optional with conservative defaults so a caller that
    supplies nothing gets a safe baseline."""
    task_family: str = ""
    answer_form: str = "bounded"           # bounded | open_reasoning | generative | ambiguous
    ambiguity: float = 0.0                 # 0-1
    novelty: float = 0.0                   # 0-1
    domain_criticality: str = "normal"     # normal | medical | financial | legal | safety
    fallback_cost: float = 1.0             # relative; 0 = cheap, higher = expensive
    stale_context_risk: float = 0.0        # 0-1
    operator_override: Optional[str] = None  # explicit forced risk class


@dataclass
class RiskAssessment:
    """Output of the risk plane. Consumed by recall / delta policies."""
    risk_class: RiskClass
    allow_direct_recall: bool
    allow_structural_recall: bool
    allow_delta_compute: bool
    force_full_compute: bool
    restrictions_applied: List[str]
    reason: str

    def to_dict(self) -> dict:
        return {
            "risk_class": self.risk_class.value,
            "allow_direct_recall": self.allow_direct_recall,
            "allow_structural_recall": self.allow_structural_recall,
            "allow_delta_compute": self.allow_delta_compute,
            "force_full_compute": self.force_full_compute,
            "restrictions_applied": list(self.restrictions_applied),
            "reason": self.reason,
        }


@dataclass
class RiskPolicyConfig:
    """Thresholds + family-level overrides."""
    # Classification thresholds (all 0-1).
    ambiguity_high: float = 0.6
    ambiguity_elevated: float = 0.35
    novelty_high: float = 0.6
    novelty_elevated: float = 0.35
    stale_context_high: float = 0.5

    # Answer-form risk (higher = more restrictive).
    open_reasoning_min_risk: RiskClass = RiskClass.ELEVATED
    ambiguous_min_risk: RiskClass = RiskClass.ELEVATED
    generative_min_risk: RiskClass = RiskClass.BOUNDED

    # Family overrides.
    never_direct_recall_families: Set[str] = field(default_factory=set)
    always_full_compute_families: Set[str] = field(default_factory=set)
    structural_recall_only_families: Set[str] = field(default_factory=set)

    # Critical-domain family hint.
    critical_domains: Set[str] = field(default_factory=lambda: {"medical", "legal", "safety"})


# ── Rule engine (native rewrite, inspired by AiGentsy's programmable
#    mandate pattern; rewritten here — no cross-module import). Allowlist
#    of fields and operators keeps the surface auditable. ────────────

ALLOWED_RISK_FIELDS: Set[str] = frozenset({
    "task_family", "answer_form", "ambiguity", "novelty",
    "domain_criticality", "fallback_cost", "stale_context_risk",
    "operator_override",
})

VALID_RISK_OPS: Set[str] = frozenset({
    "==", "!=", "<", "<=", ">", ">=", "in", "not_in",
})

VALID_RISK_ACTION_LITERALS: Set[str] = frozenset({
    "never_direct_recall",
    "force_full_compute",
    "structural_recall_only",
})


@dataclass
class RiskRule:
    """A single conditional override: if {field op value} matches, apply action."""
    field: str
    op: str
    value: Any
    action: str

    def __post_init__(self) -> None:
        if self.field not in ALLOWED_RISK_FIELDS:
            raise ValueError(
                f"RiskRule: unsupported field '{self.field}'. "
                f"Allowed: {sorted(ALLOWED_RISK_FIELDS)}"
            )
        if self.op not in VALID_RISK_OPS:
            raise ValueError(
                f"RiskRule: unsupported op '{self.op}'. "
                f"Allowed: {sorted(VALID_RISK_OPS)}"
            )
        if not self._action_is_valid():
            raise ValueError(
                f"RiskRule: unsupported action '{self.action}'. "
                f"Must be one of {sorted(VALID_RISK_ACTION_LITERALS)} "
                f"or 'force_class:<low_risk|bounded_risk|elevated_risk|high_risk>'."
            )

    def _action_is_valid(self) -> bool:
        if self.action in VALID_RISK_ACTION_LITERALS:
            return True
        if self.action.startswith("force_class:"):
            cls_name = self.action.split(":", 1)[1]
            try:
                RiskClass(cls_name)
                return True
            except ValueError:
                return False
        return False


class RiskRuleSet:
    """Data-driven overrides consulted before the signal-based ladder.

    `default_action="signal_driven"` means: if no rule fires, return None
    so RiskPlane.assess falls through to its existing signal logic. This
    is the identity-preserving default.
    """

    def __init__(
        self,
        rules: Optional[List[RiskRule]] = None,
        default_action: str = "signal_driven",
    ) -> None:
        self.rules: List[RiskRule] = list(rules or [])
        self.default_action: str = default_action

    def evaluate(self, dims: "RiskDimensions") -> Optional["RiskAssessment"]:
        """Return a RiskAssessment when a rule fires; None to defer to signals."""
        for idx, rule in enumerate(self.rules):
            if self._match(rule, dims):
                return self._build_assessment(rule, idx)
        if self.default_action == "signal_driven":
            return None
        # Non-default_action-"signal_driven" is only used for tests /
        # operator scenarios that want a hard fallback; reuse the action
        # path with a synthetic rule index = -1.
        synthetic = RiskRule(field="task_family", op="==", value="",
                              action=self.default_action)
        return self._build_assessment(synthetic, -1,
                                       synthetic_reason="default_action")

    # ── Internals ────────────────────────────────────────────────────

    @staticmethod
    def _match(rule: "RiskRule", dims: "RiskDimensions") -> bool:
        left = getattr(dims, rule.field, None)
        right = rule.value
        try:
            if rule.op == "==":
                return left == right
            if rule.op == "!=":
                return left != right
            if rule.op == "<":
                return left is not None and left < right
            if rule.op == "<=":
                return left is not None and left <= right
            if rule.op == ">":
                return left is not None and left > right
            if rule.op == ">=":
                return left is not None and left >= right
            if rule.op == "in":
                return left in right if right is not None else False
            if rule.op == "not_in":
                return left not in right if right is not None else True
        except TypeError:
            # e.g., comparing string with int — treat as no-match rather
            # than raise, so rule authoring mistakes never crash inference.
            return False
        return False

    @staticmethod
    def _build_assessment(
        rule: "RiskRule",
        idx: int,
        synthetic_reason: Optional[str] = None,
    ) -> "RiskAssessment":
        tag = (
            f"default_action={rule.action}"
            if synthetic_reason == "default_action"
            else f"rule[{idx}]:{rule.field}{rule.op}{rule.value}->{rule.action}"
        )
        restrictions = [tag]
        if rule.action == "force_full_compute":
            return RiskAssessment(
                RiskClass.HIGH, False, False, False, True, restrictions,
                f"rule forced full compute [{tag}]",
            )
        if rule.action == "never_direct_recall":
            return RiskAssessment(
                RiskClass.BOUNDED, False, True, True, False, restrictions,
                f"rule blocks direct recall [{tag}]",
            )
        if rule.action == "structural_recall_only":
            return RiskAssessment(
                RiskClass.ELEVATED, False, True, True, False, restrictions,
                f"rule restricts to structural recall [{tag}]",
            )
        if rule.action.startswith("force_class:"):
            cls = RiskClass(rule.action.split(":", 1)[1])
            # Use the ladder mapping owned by RiskPlane so the action
            # produces the same permission set a signal-based classification
            # would. We avoid instantiating a RiskPlane here because this
            # is called from within RiskPlane.assess; instead, we inline
            # the ladder via RiskPlane._ladder_for_class after the rule
            # fires (see RiskPlane.assess).
            if cls == RiskClass.LOW:
                return RiskAssessment(cls, True, True, True, False, restrictions,
                                       f"rule forced class={cls.value} [{tag}]")
            if cls == RiskClass.BOUNDED:
                return RiskAssessment(cls, False, True, True, False, restrictions,
                                       f"rule forced class={cls.value} [{tag}]")
            if cls == RiskClass.ELEVATED:
                return RiskAssessment(cls, False, True, True, False, restrictions,
                                       f"rule forced class={cls.value} [{tag}]")
            # HIGH
            return RiskAssessment(cls, False, False, False, True, restrictions,
                                   f"rule forced class={cls.value} [{tag}]")
        # Unknown action shouldn't reach here because __post_init__
        # validates on construction, but be safe-conservative.
        return RiskAssessment(
            RiskClass.HIGH, False, False, False, True, restrictions,
            f"rule action unrecognized; conservative high_risk fallback [{tag}]",
        )


class RiskPlane:
    """Assesses operational risk and emits an action-ladder permission set.

    Stateless. Safe to construct per-benchmark, per-request, or keep one
    instance for the process. Optional rule_set is consulted before the
    signal-based ladder; a firing rule short-circuits the assessment.
    """

    def __init__(
        self,
        config: Optional[RiskPolicyConfig] = None,
        rule_set: Optional[RiskRuleSet] = None,
    ) -> None:
        self._cfg = config or RiskPolicyConfig()
        self._rules = rule_set

    def assess(self, dims: RiskDimensions) -> RiskAssessment:
        # Data-driven rules are consulted FIRST. A firing rule fully
        # short-circuits the signal-based ladder. If no rule fires
        # (default_action="signal_driven" and no rule matches), we
        # fall through to the existing logic unchanged — preserving
        # identity for legacy callers that never set a rule_set.
        if self._rules is not None:
            rule_result = self._rules.evaluate(dims)
            if rule_result is not None:
                return rule_result

        restrictions: List[str] = []
        reason_parts: List[str] = []

        # Explicit operator override wins outright.
        if dims.operator_override:
            forced = RiskClass(dims.operator_override)
            return self._ladder_for_class(forced, [f"operator_override={forced.value}"],
                                           f"operator override → {forced.value}")

        # Domain criticality hard-floors the class.
        domain_floor = (
            RiskClass.HIGH if dims.domain_criticality in self._cfg.critical_domains else None
        )

        # Answer-form floor.
        answer_floor = None
        if dims.answer_form in ("open_reasoning",):
            answer_floor = self._cfg.open_reasoning_min_risk
            restrictions.append("answer_form=open_reasoning")
        elif dims.answer_form == "ambiguous":
            answer_floor = self._cfg.ambiguous_min_risk
            restrictions.append("answer_form=ambiguous")
        elif dims.answer_form == "generative":
            answer_floor = self._cfg.generative_min_risk
            restrictions.append("answer_form=generative")

        # Signal-based class assignment.
        if (dims.ambiguity >= self._cfg.ambiguity_high
                or dims.novelty >= self._cfg.novelty_high
                or dims.stale_context_risk >= self._cfg.stale_context_high):
            signal_class = RiskClass.ELEVATED
            reason_parts.append("high signal (amb/nov/stale)")
        elif (dims.ambiguity >= self._cfg.ambiguity_elevated
                or dims.novelty >= self._cfg.novelty_elevated):
            signal_class = RiskClass.BOUNDED
            reason_parts.append("moderate signal")
        else:
            signal_class = RiskClass.LOW
            reason_parts.append("low signal")

        # Combine: pick the most restrictive.
        final = signal_class
        for candidate in (domain_floor, answer_floor):
            if candidate is None:
                continue
            if self._is_more_restrictive(candidate, final):
                final = candidate

        # Family overrides — strongest.
        fam = dims.task_family
        if fam in self._cfg.always_full_compute_families:
            restrictions.append(f"family={fam}:force_full")
            reason_parts.append("family forces full compute")
            return self._ladder_for_class(
                RiskClass.HIGH, restrictions, "; ".join(reason_parts),
                override_force_full=True,
            )
        if fam in self._cfg.never_direct_recall_families:
            restrictions.append(f"family={fam}:no_direct_recall")
            final = self._max_restrictive(final, RiskClass.BOUNDED)
        if fam in self._cfg.structural_recall_only_families:
            restrictions.append(f"family={fam}:structural_only")
            final = self._max_restrictive(final, RiskClass.ELEVATED)

        return self._ladder_for_class(final, restrictions, "; ".join(reason_parts))

    # ── Ladder mapping ──────────────────────────────────────────────

    def _ladder_for_class(
        self,
        cls: RiskClass,
        restrictions: List[str],
        reason: str,
        override_force_full: bool = False,
    ) -> RiskAssessment:
        if cls == RiskClass.LOW:
            return RiskAssessment(cls, True, True, True, False, restrictions,
                                   f"{cls.value}: all avoidance paths allowed [{reason}]")
        if cls == RiskClass.BOUNDED:
            return RiskAssessment(cls, False, True, True, False, restrictions,
                                   f"{cls.value}: structural+delta allowed; direct recall denied [{reason}]")
        if cls == RiskClass.ELEVATED:
            return RiskAssessment(cls, False, True, True, False, restrictions,
                                   f"{cls.value}: structural only with high confidence; delta tightly bounded [{reason}]")
        # HIGH
        return RiskAssessment(
            cls, False, False, False, override_force_full or True, restrictions,
            f"{cls.value}: recall disabled; full compute required [{reason}]",
        )

    @staticmethod
    def _order(cls: RiskClass) -> int:
        return {
            RiskClass.LOW: 0, RiskClass.BOUNDED: 1,
            RiskClass.ELEVATED: 2, RiskClass.HIGH: 3,
        }[cls]

    @classmethod
    def _is_more_restrictive(cls, a: RiskClass, b: RiskClass) -> bool:
        return cls._order(a) > cls._order(b)

    @classmethod
    def _max_restrictive(cls, a: RiskClass, b: RiskClass) -> RiskClass:
        return a if cls._order(a) >= cls._order(b) else b
