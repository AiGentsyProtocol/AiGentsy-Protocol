"""
Programmable Mandates — Rule Engine for Autonomous Buyer Policies
==================================================================

Extends buyer mandates with conditional rule evaluation:
- If seller.ocs >= 85 AND amount <= 500 → auto_approve
- If vertical == "code_review" AND seller.ocs >= 70 → auto_approve
- If amount > 1000 → require_human_approval
- Default: reject

Buyers program once, their agents transact autonomously within policy.

Usage:
    from protocol.programmable_mandate import get_programmable_mandate_store

    store = get_programmable_mandate_store()
    mandate = store.create(
        buyer_id="buyer_abc",
        rules=[
            {"conditions": [{"field": "seller_ocs", "op": ">=", "value": 85},
                            {"field": "amount_usd", "op": "<=", "value": 500}],
             "action": "auto_approve"},
            {"conditions": [{"field": "amount_usd", "op": ">", "value": 1000}],
             "action": "require_human"},
        ],
        default_action="reject",
    )

    decision = store.evaluate(mandate.mandate_id, context={
        "seller_ocs": 90, "amount_usd": 300, "vertical": "marketing",
    })
    # → {"action": "auto_approve", "rule_index": 0, "matched": True}

Endpoints:
    POST /protocol/mandates/programmable          — Create programmable mandate
    GET  /protocol/mandates/programmable/{buyer_id} — Get programmable mandate
    POST /protocol/mandates/programmable/evaluate  — Evaluate context against mandate
"""

import hashlib
import json
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from storage_root import get_data_root

logger = logging.getLogger(__name__)

_STORE_DIR = Path(os.getenv("PROG_MANDATE_DIR", str(get_data_root() / "programmable_mandates")))

# Allowlisted fields that rules can reference
ALLOWED_RULE_FIELDS = frozenset({
    # Seller attributes
    "seller_ocs",
    "seller_tier",
    "seller_dispute_rate",
    "seller_total_settlements",
    # Deal attributes
    "amount_usd",
    "vertical",
    "proof_type",
    "sku_id",
    # Confidence / risk
    "verifier_confidence",
    "risk_flag_count",
    # Agent history
    "seller_is_new",
    "sku_is_new",
    "previous_deals_with_seller",
})

ALLOWED_OPS = frozenset({">=", "<=", "==", "!=", ">", "<", "in", "not_in"})

ALLOWED_ACTIONS = frozenset({"auto_approve", "require_human", "reject", "require_staking"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


def _evaluate_condition(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Evaluate a single condition against context. Returns False if field missing."""
    field = condition.get("field", "")
    op = condition.get("op", "")
    expected = condition.get("value")
    actual = context.get(field)

    if actual is None:
        return False

    if op == ">=":
        return actual >= expected
    elif op == "<=":
        return actual <= expected
    elif op == ">":
        return actual > expected
    elif op == "<":
        return actual < expected
    elif op == "==":
        return actual == expected
    elif op == "!=":
        return actual != expected
    elif op == "in":
        return actual in expected if isinstance(expected, list) else False
    elif op == "not_in":
        return actual not in expected if isinstance(expected, list) else True
    return False


def validate_rules(rules: List[Dict[str, Any]]) -> List[str]:
    """Validate programmable mandate rules."""
    errors = []
    for i, rule in enumerate(rules):
        conditions = rule.get("conditions", [])
        action = rule.get("action", "")

        if not conditions:
            errors.append(f"Rule {i}: must have at least one condition")
        if action not in ALLOWED_ACTIONS:
            errors.append(f"Rule {i}: action '{action}' not in {sorted(ALLOWED_ACTIONS)}")

        for j, cond in enumerate(conditions):
            f = cond.get("field", "")
            op = cond.get("op", "")
            if f not in ALLOWED_RULE_FIELDS:
                errors.append(f"Rule {i}, condition {j}: field '{f}' not allowed")
            if op not in ALLOWED_OPS:
                errors.append(f"Rule {i}, condition {j}: op '{op}' not allowed")
            if cond.get("value") is None:
                errors.append(f"Rule {i}, condition {j}: value is required")

    return errors


class ProgrammableMandate:
    __slots__ = (
        "mandate_id", "buyer_id", "rules", "default_action",
        "max_amount_per_deal_usd", "max_amount_per_day_usd",
        "status", "policy_hash", "created_at", "updated_at",
    )

    def __init__(
        self,
        buyer_id: str,
        rules: List[Dict[str, Any]],
        default_action: str = "reject",
        max_amount_per_deal_usd: float = 500.0,
        max_amount_per_day_usd: float = 0.0,
        mandate_id: str = "",
        status: str = "ACTIVE",
        policy_hash: str = "",
        created_at: str = "",
        updated_at: str = "",
    ):
        self.mandate_id = mandate_id or f"pmnd_{uuid4().hex[:12]}"
        self.buyer_id = buyer_id
        self.rules = rules
        self.default_action = default_action
        self.max_amount_per_deal_usd = max_amount_per_deal_usd
        self.max_amount_per_day_usd = max_amount_per_day_usd
        self.status = status
        self.policy_hash = policy_hash or self._compute_hash()
        self.created_at = created_at or _now_iso()
        self.updated_at = updated_at or self.created_at

    def _compute_hash(self) -> str:
        canonical = json.dumps(
            {"rules": self.rules, "default_action": self.default_action},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mandate_id": self.mandate_id,
            "buyer_id": self.buyer_id,
            "rules": self.rules,
            "default_action": self.default_action,
            "max_amount_per_deal_usd": self.max_amount_per_deal_usd,
            "max_amount_per_day_usd": self.max_amount_per_day_usd,
            "status": self.status,
            "policy_hash": self.policy_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProgrammableMandate":
        return cls(**{k: v for k, v in d.items() if k in cls.__slots__})


class ProgrammableMandateStore:
    def __init__(self, store_dir: str = str(_STORE_DIR)):
        self._mandates: OrderedDict[str, ProgrammableMandate] = OrderedDict()
        self._buyer_index: Dict[str, str] = {}
        self._store_file: Optional[Path] = None
        self._lock = threading.Lock()
        self._init(store_dir)

    def _init(self, store_dir: str):
        try:
            path = Path(store_dir)
            path.mkdir(parents=True, exist_ok=True)
            self._store_file = path / "programmable_mandates.jsonl"
            if self._store_file.exists():
                for line in self._store_file.read_text().strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        m = ProgrammableMandate.from_dict(json.loads(line))
                        self._mandates[m.mandate_id] = m
                        if m.status != "REVOKED":
                            self._buyer_index[m.buyer_id] = m.mandate_id
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"[PROG_MANDATE] Store init failed: {e}")

    def _persist(self, mandate: ProgrammableMandate):
        if not self._store_file:
            return
        try:
            with open(self._store_file, "a") as f:
                f.write(json.dumps(mandate.to_dict(), default=str) + "\n")
        except Exception as e:
            logger.warning(f"[PROG_MANDATE] Persist failed: {e}")

    def create(
        self,
        buyer_id: str,
        rules: List[Dict[str, Any]],
        default_action: str = "reject",
        max_amount_per_deal_usd: float = 500.0,
        max_amount_per_day_usd: float = 0.0,
    ) -> ProgrammableMandate:
        with self._lock:
            mandate = ProgrammableMandate(
                buyer_id=buyer_id,
                rules=rules,
                default_action=default_action,
                max_amount_per_deal_usd=max_amount_per_deal_usd,
                max_amount_per_day_usd=max_amount_per_day_usd,
            )
            self._mandates[mandate.mandate_id] = mandate
            self._buyer_index[buyer_id] = mandate.mandate_id
            self._persist(mandate)
        return mandate

    def get(self, mandate_id: str) -> Optional[ProgrammableMandate]:
        return self._mandates.get(mandate_id)

    def get_by_buyer(self, buyer_id: str) -> Optional[ProgrammableMandate]:
        mid = self._buyer_index.get(buyer_id)
        return self._mandates.get(mid) if mid else None

    def evaluate(self, mandate_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate context against programmable mandate rules.
        Rules are evaluated in order — first match wins.
        """
        mandate = self._mandates.get(mandate_id)
        if not mandate:
            return {"matched": False, "action": "reject", "reason": "mandate_not_found"}
        if mandate.status != "ACTIVE":
            return {"matched": False, "action": "reject", "reason": f"mandate_{mandate.status.lower()}"}

        # Hard cap check first
        amount = context.get("amount_usd", 0)
        if mandate.max_amount_per_deal_usd > 0 and amount > mandate.max_amount_per_deal_usd:
            return {
                "matched": True,
                "action": "reject",
                "reason": f"exceeds_max_per_deal ({amount} > {mandate.max_amount_per_deal_usd})",
                "rule_index": -1,
            }

        # Evaluate rules in order — first match wins
        for i, rule in enumerate(mandate.rules):
            conditions = rule.get("conditions", [])
            all_match = all(_evaluate_condition(c, context) for c in conditions)

            if all_match:
                return {
                    "matched": True,
                    "action": rule["action"],
                    "rule_index": i,
                    "conditions_evaluated": len(conditions),
                    "policy_hash": mandate.policy_hash,
                }

        # No rule matched — use default
        return {
            "matched": False,
            "action": mandate.default_action,
            "reason": "no_rule_matched",
            "policy_hash": mandate.policy_hash,
        }

    def revoke(self, mandate_id: str) -> bool:
        m = self._mandates.get(mandate_id)
        if not m:
            return False
        with self._lock:
            m.status = "REVOKED"
            m.updated_at = _now_iso()
            if self._buyer_index.get(m.buyer_id) == mandate_id:
                del self._buyer_index[m.buyer_id]
            self._persist(m)
        return True


_store: Optional[ProgrammableMandateStore] = None


def get_programmable_mandate_store() -> ProgrammableMandateStore:
    global _store
    if _store is None:
        _store = ProgrammableMandateStore()
    return _store


# ── FastAPI Router ──

def get_programmable_mandate_router():
    try:
        from fastapi import APIRouter, Header, HTTPException
        from pydantic import BaseModel, Field
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol", tags=["Programmable Mandates"])

    class RuleCondition(BaseModel):
        field: str = Field(..., description=f"Field to evaluate. Allowed: {sorted(ALLOWED_RULE_FIELDS)}")
        op: str = Field(..., description=f"Operator. Allowed: {sorted(ALLOWED_OPS)}")
        value: Any = Field(..., description="Expected value")

    class Rule(BaseModel):
        conditions: List[Dict[str, Any]] = Field(..., description="List of conditions (all must match)")
        action: str = Field(..., description=f"Action if all conditions match. Allowed: {sorted(ALLOWED_ACTIONS)}")

    class CreateProgrammableMandateRequest(BaseModel):
        buyer_id: str = Field(..., description="Buyer identifier")
        rules: List[Dict[str, Any]] = Field(..., description="Ordered list of rules (first match wins)")
        default_action: str = Field("reject", description="Action if no rule matches")
        max_amount_per_deal_usd: float = Field(500.0, gt=0)
        max_amount_per_day_usd: float = Field(0.0, ge=0)

    class EvaluateMandateRequest(BaseModel):
        mandate_id: str = Field(None, description="Mandate ID (or use buyer_id)")
        buyer_id: str = Field(None, description="Buyer ID (looks up active mandate)")
        context: Dict[str, Any] = Field(..., description="Context to evaluate against rules")

    def _auth(api_key: str):
        from protocol.agent_registry import get_agent_registry
        agent = get_agent_registry().authenticate(api_key)
        if not agent:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return agent

    @router.post("/mandates/programmable")
    async def create_programmable_mandate(
        req: CreateProgrammableMandateRequest,
        x_api_key: str = Header(..., alias="X-API-Key"),
    ):
        """
        Create a programmable mandate with conditional rules.

        Rules are evaluated in order — first match wins. Each rule has
        conditions (all must match) and an action (auto_approve, require_human, reject).
        """
        _auth(x_api_key)

        # Validate rules
        errors = validate_rules(req.rules)
        if errors:
            raise HTTPException(status_code=422, detail={"errors": errors})

        if req.default_action not in ALLOWED_ACTIONS:
            raise HTTPException(
                status_code=422,
                detail=f"default_action '{req.default_action}' not in {sorted(ALLOWED_ACTIONS)}",
            )

        store = get_programmable_mandate_store()

        # Check for existing active mandate
        existing = store.get_by_buyer(req.buyer_id)
        if existing and existing.status == "ACTIVE":
            return {
                "ok": True,
                "mandate": existing.to_dict(),
                "note": "Existing active programmable mandate returned. Revoke first to create new.",
            }

        mandate = store.create(
            buyer_id=req.buyer_id,
            rules=req.rules,
            default_action=req.default_action,
            max_amount_per_deal_usd=req.max_amount_per_deal_usd,
            max_amount_per_day_usd=req.max_amount_per_day_usd,
        )

        # Emit event
        try:
            from protocol.event_store import emit_event
            await emit_event(
                deal_id=f"mandate:{mandate.mandate_id}",
                event_type="MANDATE_CREATED",
                actor_id=req.buyer_id,
                amount=req.max_amount_per_deal_usd,
                payload={
                    "mandate_id": mandate.mandate_id,
                    "mandate_type": "programmable",
                    "rule_count": len(req.rules),
                    "default_action": req.default_action,
                    "policy_hash": mandate.policy_hash,
                },
                source="programmable_mandate",
            )
        except Exception as e:
            logger.debug(f"[PROG_MANDATE] Event emission failed: {e}")

        return {
            "ok": True,
            "mandate": mandate.to_dict(),
            "available_fields": sorted(ALLOWED_RULE_FIELDS),
            "available_ops": sorted(ALLOWED_OPS),
            "available_actions": sorted(ALLOWED_ACTIONS),
        }

    @router.get("/mandates/programmable/{buyer_id}")
    async def get_programmable_mandate(
        buyer_id: str,
        x_api_key: str = Header(..., alias="X-API-Key"),
    ):
        """Get active programmable mandate for a buyer. Caller must be the buyer."""
        agent = _auth(x_api_key)
        if agent.get("agent_id") != buyer_id:
            raise HTTPException(status_code=403, detail="Cannot view other agent's mandates")
        store = get_programmable_mandate_store()
        mandate = store.get_by_buyer(buyer_id)
        if not mandate:
            raise HTTPException(status_code=404, detail="No programmable mandate found for buyer")
        return {"ok": True, "mandate": mandate.to_dict()}

    @router.post("/mandates/programmable/evaluate")
    async def evaluate_mandate(
        req: EvaluateMandateRequest,
        x_api_key: str = Header(..., alias="X-API-Key"),
    ):
        """
        Evaluate a context against a programmable mandate.

        Returns the action decision and which rule matched (if any).
        """
        _auth(x_api_key)
        store = get_programmable_mandate_store()

        mandate_id = req.mandate_id
        if not mandate_id and req.buyer_id:
            m = store.get_by_buyer(req.buyer_id)
            if m:
                mandate_id = m.mandate_id

        if not mandate_id:
            raise HTTPException(status_code=422, detail="Provide mandate_id or buyer_id")

        result = store.evaluate(mandate_id, req.context)
        result["ok"] = True
        return result

    @router.post("/mandates/programmable/{mandate_id}/revoke")
    async def revoke_programmable_mandate(
        mandate_id: str,
        x_api_key: str = Header(..., alias="X-API-Key"),
    ):
        """Revoke a programmable mandate."""
        _auth(x_api_key)
        store = get_programmable_mandate_store()
        if not store.revoke(mandate_id):
            raise HTTPException(status_code=404, detail="Mandate not found")

        try:
            from protocol.event_store import emit_event
            mandate = store.get(mandate_id)
            await emit_event(
                deal_id=f"mandate:{mandate_id}",
                event_type="MANDATE_REVOKED",
                actor_id=mandate.buyer_id if mandate else "",
                payload={"mandate_id": mandate_id, "mandate_type": "programmable"},
                source="programmable_mandate",
            )
        except Exception:
            pass

        return {"ok": True, "mandate_id": mandate_id, "status": "REVOKED"}

    return router
