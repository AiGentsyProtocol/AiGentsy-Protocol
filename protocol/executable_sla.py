"""
Executable SLAs — Programmable Service-Level Commitments
=========================================================

Attach programmable service-level commitments to deals. When verification
passes the SLA conditions, settlement fires automatically. When conditions
breach, staking penalties apply if staked.

An SLA is a JSON document that composes existing primitives:
- Credentials (proof of past capability)
- Staking (agent's own balance commitment)
- Programmable mandates (buyer's auto-approval rules)
- Verification providers (confidence thresholds)

No new money movement. Settlement flows through the existing GO + settle path.

Usage:
    POST /protocol/slas                    — Create an SLA
    GET  /protocol/slas/{sla_id}           — Get SLA details
    POST /protocol/slas/{sla_id}/evaluate  — Evaluate SLA against deal state
    GET  /protocol/slas/agent/{agent_id}   — List agent's SLAs

Endpoints:
    SLA creation, evaluation, listing, and deal attachment.
"""

import hashlib
import json
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from storage_root import get_data_root

logger = logging.getLogger(__name__)

_STORE_DIR = Path(os.getenv("SLA_DIR", str(get_data_root() / "slas")))

# Allowed SLA condition fields
ALLOWED_CONDITION_FIELDS = frozenset({
    "verification_confidence",
    "delivery_hours",
    "proof_type",
    "vertical",
    "amount_usd_max",
    "amount_usd_min",
    "seller_ocs_min",
})

ALLOWED_OPS = frozenset({">=", "<=", "==", "!=", ">", "<"})

# SLA outcomes
SLA_OUTCOMES = frozenset({"auto_settle", "require_review", "breach"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_sla_hash(conditions: List[Dict], guarantees: Dict) -> str:
    canonical = json.dumps(
        {"conditions": conditions, "guarantees": guarantees},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class SLA:
    __slots__ = (
        "sla_id", "provider_agent_id", "conditions", "guarantees",
        "stake_amount_usd", "auto_settle_on_verify", "breach_action",
        "sla_hash", "status", "created_at", "deal_ids",
    )

    def __init__(self, **kwargs):
        self.sla_id = kwargs.get("sla_id", f"sla_{uuid4().hex[:12]}")
        self.provider_agent_id = kwargs.get("provider_agent_id", "")
        self.conditions = kwargs.get("conditions", [])
        self.guarantees = kwargs.get("guarantees", {})
        self.stake_amount_usd = kwargs.get("stake_amount_usd", 0.0)
        self.auto_settle_on_verify = kwargs.get("auto_settle_on_verify", True)
        self.breach_action = kwargs.get("breach_action", "require_review")
        self.sla_hash = kwargs.get("sla_hash", "")
        self.status = kwargs.get("status", "active")
        self.created_at = kwargs.get("created_at", _now_iso())
        self.deal_ids = kwargs.get("deal_ids", [])
        if not self.sla_hash:
            self.sla_hash = _compute_sla_hash(self.conditions, self.guarantees)

    def to_dict(self) -> Dict[str, Any]:
        return {s: getattr(self, s) for s in self.__slots__}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SLA":
        return cls(**{k: v for k, v in d.items() if k in cls.__slots__})


def evaluate_sla(sla: SLA, deal_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate an SLA against deal context.

    Returns:
        {
            "outcome": "auto_settle" | "require_review" | "breach",
            "conditions_met": [...],
            "conditions_failed": [...],
            "sla_hash": "...",
        }
    """
    met = []
    failed = []

    for cond in sla.conditions:
        field = cond.get("field", "")
        op = cond.get("op", "")
        expected = cond.get("value")
        actual = deal_context.get(field)

        if actual is None:
            failed.append({"field": field, "reason": "missing_from_context"})
            continue

        passed = False
        if op == ">=":
            passed = actual >= expected
        elif op == "<=":
            passed = actual <= expected
        elif op == ">":
            passed = actual > expected
        elif op == "<":
            passed = actual < expected
        elif op == "==":
            passed = actual == expected
        elif op == "!=":
            passed = actual != expected

        if passed:
            met.append({"field": field, "op": op, "expected": expected, "actual": actual})
        else:
            failed.append({"field": field, "op": op, "expected": expected, "actual": actual})

    # Check guarantees
    guarantee_results = {}
    if "delivery_hours" in sla.guarantees:
        max_hours = sla.guarantees["delivery_hours"]
        proof_created = deal_context.get("proof_created_at", "")
        deal_created = deal_context.get("deal_created_at", "")
        if proof_created and deal_created:
            try:
                t_proof = datetime.fromisoformat(proof_created.replace("Z", "+00:00"))
                t_deal = datetime.fromisoformat(deal_created.replace("Z", "+00:00"))
                hours_taken = (t_proof - t_deal).total_seconds() / 3600
                on_time = hours_taken <= max_hours
                guarantee_results["delivery_hours"] = {
                    "guaranteed": max_hours, "actual": round(hours_taken, 2), "met": on_time
                }
                if not on_time:
                    failed.append({"field": "delivery_hours", "reason": f"took {hours_taken:.1f}h, guaranteed {max_hours}h"})
            except Exception:
                pass

    if "quality_floor" in sla.guarantees:
        floor = sla.guarantees["quality_floor"]
        confidence = deal_context.get("verification_confidence", 0)
        met_quality = confidence >= floor
        guarantee_results["quality_floor"] = {
            "guaranteed": floor, "actual": confidence, "met": met_quality
        }
        if not met_quality:
            failed.append({"field": "quality_floor", "reason": f"confidence {confidence} < floor {floor}"})

    # Determine outcome
    if not failed:
        outcome = "auto_settle" if sla.auto_settle_on_verify else "require_review"
    else:
        outcome = sla.breach_action

    return {
        "outcome": outcome,
        "conditions_met": met,
        "conditions_failed": failed,
        "guarantee_results": guarantee_results,
        "all_conditions_passed": len(failed) == 0,
        "sla_hash": sla.sla_hash,
    }


class SLAStore:
    def __init__(self, store_dir: str = str(_STORE_DIR)):
        self._slas: Dict[str, SLA] = {}
        self._by_agent: Dict[str, List[str]] = defaultdict(list)
        self._by_deal: Dict[str, str] = {}
        self._store_file: Optional[Path] = None
        self._lock = threading.Lock()
        self._init(store_dir)

    def _init(self, store_dir: str):
        try:
            path = Path(store_dir)
            path.mkdir(parents=True, exist_ok=True)
            self._store_file = path / "slas.jsonl"
            if self._store_file.exists():
                for line in self._store_file.read_text().strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        sla = SLA.from_dict(json.loads(line))
                        self._slas[sla.sla_id] = sla
                        self._by_agent[sla.provider_agent_id].append(sla.sla_id)
                        for did in sla.deal_ids:
                            self._by_deal[did] = sla.sla_id
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"[SLA] Store init failed: {e}")

    def _persist(self, sla: SLA):
        if not self._store_file:
            return
        try:
            with open(self._store_file, "a") as f:
                f.write(json.dumps(sla.to_dict(), default=str) + "\n")
        except Exception as e:
            logger.warning(f"[SLA] Persist failed: {e}")

    def create(self, provider_agent_id: str, conditions: List[Dict],
               guarantees: Dict = None, stake_amount_usd: float = 0.0,
               auto_settle_on_verify: bool = True,
               breach_action: str = "require_review") -> SLA:
        with self._lock:
            sla = SLA(
                provider_agent_id=provider_agent_id,
                conditions=conditions,
                guarantees=guarantees or {},
                stake_amount_usd=stake_amount_usd,
                auto_settle_on_verify=auto_settle_on_verify,
                breach_action=breach_action,
            )
            self._slas[sla.sla_id] = sla
            self._by_agent[provider_agent_id].append(sla.sla_id)
            self._persist(sla)
            return sla

    def get(self, sla_id: str) -> Optional[SLA]:
        return self._slas.get(sla_id)

    def get_by_agent(self, agent_id: str) -> List[Dict[str, Any]]:
        return [self._slas[sid].to_dict() for sid in self._by_agent.get(agent_id, [])
                if sid in self._slas]

    def get_by_deal(self, deal_id: str) -> Optional[SLA]:
        sid = self._by_deal.get(deal_id)
        return self._slas.get(sid) if sid else None

    def attach_deal(self, sla_id: str, deal_id: str) -> bool:
        sla = self._slas.get(sla_id)
        if not sla:
            return False
        with self._lock:
            if deal_id not in sla.deal_ids:
                sla.deal_ids.append(deal_id)
            self._by_deal[deal_id] = sla_id
            self._persist(sla)
        return True


# ── SLA Templates ──

SLA_TEMPLATES = {
    "marketing_standard": {
        "name": "Marketing — Standard",
        "vertical": "marketing",
        "conditions": [
            {"field": "verification_confidence", "op": ">=", "value": 0.75},
        ],
        "guarantees": {"delivery_hours": 24, "quality_floor": 0.80},
        "auto_settle_on_verify": True,
        "breach_action": "require_review",
    },
    "code_standard": {
        "name": "Code / Software — Standard",
        "vertical": "code",
        "conditions": [
            {"field": "verification_confidence", "op": ">=", "value": 0.80},
        ],
        "guarantees": {"delivery_hours": 48, "quality_floor": 0.85},
        "auto_settle_on_verify": True,
        "breach_action": "require_review",
    },
    "design_standard": {
        "name": "Design — Standard",
        "vertical": "design",
        "conditions": [
            {"field": "verification_confidence", "op": ">=", "value": 0.75},
        ],
        "guarantees": {"delivery_hours": 72, "quality_floor": 0.80},
        "auto_settle_on_verify": True,
        "breach_action": "require_review",
    },
    "research_standard": {
        "name": "Research — Standard",
        "vertical": "research",
        "conditions": [
            {"field": "verification_confidence", "op": ">=", "value": 0.70},
        ],
        "guarantees": {"delivery_hours": 96, "quality_floor": 0.75},
        "auto_settle_on_verify": True,
        "breach_action": "require_review",
    },
    "data_processing": {
        "name": "Data Processing — Fast",
        "vertical": "data",
        "conditions": [
            {"field": "verification_confidence", "op": ">=", "value": 0.80},
        ],
        "guarantees": {"delivery_hours": 12, "quality_floor": 0.85},
        "auto_settle_on_verify": True,
        "breach_action": "breach",
    },
    "enterprise_premium": {
        "name": "Enterprise — Premium",
        "vertical": "enterprise",
        "conditions": [
            {"field": "verification_confidence", "op": ">=", "value": 0.90},
        ],
        "guarantees": {"delivery_hours": 24, "quality_floor": 0.90},
        "auto_settle_on_verify": False,
        "breach_action": "breach",
    },
}


_store: Optional[SLAStore] = None


def get_sla_store() -> SLAStore:
    global _store
    if _store is None:
        _store = SLAStore()
    return _store


# ── FastAPI Router ──

def get_sla_router():
    try:
        from fastapi import APIRouter, Header, HTTPException, Query
        from pydantic import BaseModel, Field
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol", tags=["Executable SLAs"])

    class CreateSLARequest(BaseModel):
        conditions: List[Dict[str, Any]] = Field(default_factory=list, description="SLA conditions (evaluated on deal context)")
        guarantees: Dict[str, Any] = Field(default_factory=dict, description="Guarantees: delivery_hours, quality_floor")
        stake_amount_usd: float = Field(0.0, ge=0, description="Amount staked against this SLA")
        auto_settle_on_verify: bool = Field(True, description="Auto-settle when all conditions pass")
        breach_action: str = Field("require_review", description="Action on breach: require_review or breach")

    class EvaluateSLARequest(BaseModel):
        deal_context: Dict[str, Any] = Field(..., description="Deal state to evaluate against SLA")

    class AttachDealRequest(BaseModel):
        deal_id: str = Field(..., description="Deal ID to attach to this SLA")

    def _auth(api_key: str):
        from protocol.agent_registry import get_agent_registry
        agent = get_agent_registry().authenticate(api_key)
        if not agent:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return agent

    # ── SLA Templates (must be before /slas/{sla_id} to avoid route conflict) ──

    @router.get("/slas/templates")
    async def list_templates():
        """List available SLA templates for common verticals."""
        return {
            "ok": True,
            "templates": {k: v for k, v in SLA_TEMPLATES.items()},
            "note": "Use POST /protocol/slas/from-template to create an SLA from a template.",
        }

    @router.get("/slas/agent/{agent_id}")
    async def list_agent_slas(agent_id: str):
        """List SLAs for an agent."""
        store = get_sla_store()
        return {"ok": True, "agent_id": agent_id, "slas": store.get_by_agent(agent_id)}

    @router.post("/slas")
    async def create_sla(req: CreateSLARequest, x_api_key: str = Header(..., alias="X-API-Key")):
        """Create an executable SLA. Attaches to deals and auto-evaluates on verification."""
        agent = _auth(x_api_key)
        store = get_sla_store()
        sla = store.create(
            provider_agent_id=agent["agent_id"],
            conditions=req.conditions,
            guarantees=req.guarantees,
            stake_amount_usd=req.stake_amount_usd,
            auto_settle_on_verify=req.auto_settle_on_verify,
            breach_action=req.breach_action,
        )

        # If staked, create protocol stake
        if req.stake_amount_usd > 0:
            try:
                from protocol.reputation_staking import get_staking_store
                get_staking_store().create_stake(
                    agent_id=agent["agent_id"],
                    deal_id=f"sla:{sla.sla_id}",
                    amount_usd=req.stake_amount_usd,
                    commitment=f"SLA guarantee: {json.dumps(req.guarantees)}",
                )
            except Exception as e:
                logger.debug(f"[SLA] Stake creation failed (non-fatal): {e}")

        try:
            from protocol.event_store import emit_event
            await emit_event(
                deal_id=f"sla:{sla.sla_id}",
                event_type="SLA_CREATED",
                actor_id=agent["agent_id"],
                amount=req.stake_amount_usd,
                payload={"sla_id": sla.sla_id, "sla_hash": sla.sla_hash,
                         "guarantees": req.guarantees, "auto_settle": req.auto_settle_on_verify},
                source="executable_sla",
            )
        except Exception:
            pass

        return {"ok": True, "sla": sla.to_dict()}

    @router.get("/slas/{sla_id}")
    async def get_sla(sla_id: str):
        """Get SLA details."""
        store = get_sla_store()
        sla = store.get(sla_id)
        if not sla:
            raise HTTPException(status_code=404, detail="SLA not found")
        return {"ok": True, "sla": sla.to_dict()}

    @router.post("/slas/{sla_id}/evaluate")
    async def evaluate(sla_id: str, req: EvaluateSLARequest):
        """Evaluate an SLA against deal context. Returns outcome: auto_settle, require_review, or breach."""
        store = get_sla_store()
        sla = store.get(sla_id)
        if not sla:
            raise HTTPException(status_code=404, detail="SLA not found")
        result = evaluate_sla(sla, req.deal_context)
        result["ok"] = True
        result["sla_id"] = sla_id
        return result

    @router.post("/slas/{sla_id}/attach")
    async def attach_deal(sla_id: str, req: AttachDealRequest, x_api_key: str = Header(..., alias="X-API-Key")):
        """Attach a deal to this SLA. Future verifications will evaluate against it."""
        _auth(x_api_key)
        store = get_sla_store()
        if not store.attach_deal(sla_id, req.deal_id):
            raise HTTPException(status_code=404, detail="SLA not found")
        return {"ok": True, "sla_id": sla_id, "deal_id": req.deal_id}

    class FromTemplateRequest(BaseModel):
        template_id: str = Field(..., description=f"Template ID. Options: {', '.join(SLA_TEMPLATES.keys())}")
        stake_amount_usd: float = Field(0.0, ge=0, description="Optional stake amount")

    @router.post("/slas/from-template")
    async def create_from_template(req: FromTemplateRequest, x_api_key: str = Header(..., alias="X-API-Key")):
        """Create an SLA from a pre-built template. One-click SLA creation."""
        agent = _auth(x_api_key)
        tmpl = SLA_TEMPLATES.get(req.template_id)
        if not tmpl:
            raise HTTPException(status_code=404, detail=f"Template '{req.template_id}' not found. Available: {list(SLA_TEMPLATES.keys())}")

        store = get_sla_store()
        sla = store.create(
            provider_agent_id=agent["agent_id"],
            conditions=tmpl["conditions"],
            guarantees=tmpl["guarantees"],
            stake_amount_usd=req.stake_amount_usd,
            auto_settle_on_verify=tmpl["auto_settle_on_verify"],
            breach_action=tmpl["breach_action"],
        )

        if req.stake_amount_usd > 0:
            try:
                from protocol.reputation_staking import get_staking_store
                get_staking_store().create_stake(
                    agent_id=agent["agent_id"],
                    deal_id=f"sla:{sla.sla_id}",
                    amount_usd=req.stake_amount_usd,
                    commitment=f"SLA template: {tmpl['name']}",
                )
            except Exception:
                pass

        try:
            from protocol.event_store import emit_event
            await emit_event(
                deal_id=f"sla:{sla.sla_id}",
                event_type="SLA_CREATED",
                actor_id=agent["agent_id"],
                amount=req.stake_amount_usd,
                payload={"sla_id": sla.sla_id, "template_id": req.template_id,
                         "template_name": tmpl["name"], "sla_hash": sla.sla_hash},
                source="executable_sla",
            )
        except Exception:
            pass

        return {
            "ok": True,
            "sla": sla.to_dict(),
            "template_used": req.template_id,
            "template_name": tmpl["name"],
        }

    return router
