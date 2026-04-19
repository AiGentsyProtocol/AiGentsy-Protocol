"""
Settlement Policy — Part 11
=============================

Programmable, declarative settlement policies with allowlisted operators.
No eval/exec — predicates are structured dicts with permitted fields and ops.

PolicySpec: list of predicates, frozen_at timestamp, policy_hash.
Evaluate at quote/freeze time by proof_pipe and graph_settlement.

Endpoints:
    POST /protocol/policies/validate — Validate a policy spec
    POST /protocol/policies/evaluate — Evaluate policy against context
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Allowlisted fields that policies can reference
ALLOWED_FIELDS = frozenset({
    "verifier_confidence",
    "quorum_count",
    "approval_mode",
    "dispute_sla_hours",
    "ocs_min",
    "amount_max_usd",
})

# Allowlisted comparison operators
ALLOWED_OPS = frozenset({">=", "<=", "==", "!=", "in"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


@dataclass
class Predicate:
    field: str
    op: str
    value: Any


@dataclass
class PolicySpec:
    predicates: List[Dict[str, Any]] = field(default_factory=list)
    frozen_at: str = ""
    policy_hash: str = ""


def validate_predicates(predicates: List[Dict[str, Any]]) -> List[str]:
    """Validate predicates against allowed fields and ops."""
    errors = []
    for i, pred in enumerate(predicates):
        f = pred.get("field", "")
        op = pred.get("op", "")
        val = pred.get("value")

        if f not in ALLOWED_FIELDS:
            errors.append(f"Predicate {i}: field '{f}' not in allowed fields: {sorted(ALLOWED_FIELDS)}")
        if op not in ALLOWED_OPS:
            errors.append(f"Predicate {i}: op '{op}' not in allowed ops: {sorted(ALLOWED_OPS)}")
        if val is None:
            errors.append(f"Predicate {i}: value is required")

        # Type validation
        if f in ("verifier_confidence", "ocs_min", "amount_max_usd", "dispute_sla_hours", "quorum_count"):
            if op == "in":
                if not isinstance(val, list):
                    errors.append(f"Predicate {i}: 'in' op requires list value")
            elif not isinstance(val, (int, float)):
                errors.append(f"Predicate {i}: field '{f}' requires numeric value")

    return errors


def create_policy_spec(predicates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create and validate a policy spec."""
    errors = validate_predicates(predicates)
    if errors:
        return {"ok": False, "errors": errors}

    spec = PolicySpec(predicates=predicates)
    return {"ok": True, "spec": asdict(spec), "predicate_count": len(predicates)}


def freeze_policy(predicates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Freeze a policy — creates immutable hash."""
    errors = validate_predicates(predicates)
    if errors:
        return {"ok": False, "errors": errors}

    frozen_at = _now_iso()
    canonical = json.dumps(predicates, sort_keys=True, default=str)
    policy_hash = hashlib.sha256(canonical.encode()).hexdigest()

    spec = PolicySpec(
        predicates=predicates,
        frozen_at=frozen_at,
        policy_hash=policy_hash,
    )

    return {
        "ok": True,
        "spec": asdict(spec),
        "policy_hash": policy_hash,
        "frozen_at": frozen_at,
    }


def evaluate_policy(predicates: List[Dict[str, Any]], context: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a policy against a context dict. All predicates must pass."""
    errors = validate_predicates(predicates)
    if errors:
        return {"ok": False, "passed": False, "errors": errors}

    results = []
    all_passed = True

    for pred in predicates:
        f = pred["field"]
        op = pred["op"]
        expected = pred["value"]
        actual = context.get(f)

        if actual is None:
            results.append({"field": f, "op": op, "passed": False, "reason": "field_missing_from_context"})
            all_passed = False
            continue

        passed = False
        if op == ">=":
            passed = actual >= expected
        elif op == "<=":
            passed = actual <= expected
        elif op == "==":
            passed = actual == expected
        elif op == "!=":
            passed = actual != expected
        elif op == "in":
            passed = actual in expected

        results.append({
            "field": f, "op": op, "expected": expected,
            "actual": actual, "passed": passed,
        })
        if not passed:
            all_passed = False

    return {
        "ok": True,
        "passed": all_passed,
        "predicate_count": len(predicates),
        "results": results,
    }


# ── Router ──

def get_settlement_policy_router():
    try:
        from fastapi import APIRouter, HTTPException
        from pydantic import BaseModel, Field
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol", tags=["Settlement Policies"])

    class ValidatePolicyRequest(BaseModel):
        model_config = {"extra": "ignore"}
        predicates: List[Dict[str, Any]] = Field(...)

    class EvaluatePolicyRequest(BaseModel):
        model_config = {"extra": "ignore"}
        predicates: List[Dict[str, Any]] = Field(...)
        context: Dict[str, Any] = Field(...)

    @router.post("/policies/validate")
    async def validate_policy(req: ValidatePolicyRequest):
        """Validate a settlement policy spec."""
        errors = validate_predicates(req.predicates)
        if errors:
            raise HTTPException(status_code=422, detail={"errors": errors})
        frozen = freeze_policy(req.predicates)
        return frozen

    @router.post("/policies/evaluate")
    async def evaluate(req: EvaluatePolicyRequest):
        """Evaluate a policy against context."""
        result = evaluate_policy(req.predicates, req.context)
        if not result.get("ok"):
            raise HTTPException(status_code=422, detail=result.get("errors", []))
        return result

    return router
