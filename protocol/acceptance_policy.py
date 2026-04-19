"""
Acceptance Policies — Programmable Auto-Accept/Reject Rules
=============================================================

Narrow, explicit policies that auto-decide acceptance based on
verifiable conditions. No policy sprawl — each rule maps directly
to an operational consequence.

Usage:
    POST /protocol/acceptance-policies              — Create policy
    GET  /protocol/acceptance-policies/{agent_id}   — Get agent's policy
    POST /protocol/acceptance-policies/evaluate     — Evaluate deal against policy

Allowed conditions:
    verification_confidence >= threshold
    seller_ocs >= threshold
    amount_usd <= cap
    proof_type == expected
    vertical in allowed_list
"""

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from storage_root import get_data_root

logger = logging.getLogger(__name__)

_STORE_DIR = Path(os.getenv("ACCEPTANCE_POLICY_DIR", str(get_data_root() / "acceptance_policies")))

ALLOWED_FIELDS = frozenset({
    "verification_confidence", "seller_ocs", "amount_usd",
    "proof_type", "vertical", "delivery_hours",
    "hive_success_rate", "yield_confidence", "brain_recommended_action",
    "kyc_level", "fraud_risk_score",
    "predicted_success", "estimated_timing", "brain_ocs_score",
})

ALLOWED_OPS = frozenset({">=", "<=", "==", "!=", ">", "<", "in"})

ALLOWED_ACTIONS = frozenset({"auto_accept", "require_review", "auto_reject"})


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AcceptancePolicy:
    __slots__ = (
        "policy_id", "agent_id", "rules", "default_action",
        "policy_hash", "status", "created_at",
    )

    def __init__(self, **kw):
        self.policy_id = kw.get("policy_id", f"apol_{uuid4().hex[:12]}")
        self.agent_id = kw.get("agent_id", "")
        self.rules = kw.get("rules", [])
        self.default_action = kw.get("default_action", "require_review")
        self.status = kw.get("status", "active")
        self.created_at = kw.get("created_at", _now_iso())
        canonical = json.dumps({"rules": self.rules, "default": self.default_action},
                               sort_keys=True, separators=(",", ":"))
        self.policy_hash = kw.get("policy_hash", hashlib.sha256(canonical.encode()).hexdigest())

    def to_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


class AcceptancePolicyStore:
    def __init__(self, store_dir=str(_STORE_DIR)):
        self._policies: Dict[str, AcceptancePolicy] = {}
        self._by_agent: Dict[str, str] = {}
        self._file: Optional[Path] = None
        self._lock = threading.Lock()
        try:
            p = Path(store_dir); p.mkdir(parents=True, exist_ok=True)
            self._file = p / "policies.jsonl"
            if self._file.exists():
                for line in self._file.read_text().strip().split("\n"):
                    if line.strip():
                        try:
                            pol = AcceptancePolicy(**json.loads(line))
                            self._policies[pol.policy_id] = pol
                            if pol.status == "active":
                                self._by_agent[pol.agent_id] = pol.policy_id
                        except Exception:
                            pass
        except Exception:
            pass

    def _persist(self, pol):
        if self._file:
            try:
                with open(self._file, "a") as f:
                    f.write(json.dumps(pol.to_dict(), default=str) + "\n")
            except Exception:
                pass

    def create(self, agent_id, rules, default_action="require_review"):
        with self._lock:
            pol = AcceptancePolicy(agent_id=agent_id, rules=rules, default_action=default_action)
            self._policies[pol.policy_id] = pol
            self._by_agent[agent_id] = pol.policy_id
            self._persist(pol)
            return pol

    def get_by_agent(self, agent_id):
        pid = self._by_agent.get(agent_id)
        return self._policies.get(pid) if pid else None


_store: Optional[AcceptancePolicyStore] = None

def get_acceptance_policy_store():
    global _store
    if _store is None:
        _store = AcceptancePolicyStore()
    return _store


# ── Policy Suggestion System (Brain Policy Trainer advisory layer) ──


class PolicySuggestion:
    """A trainer-generated policy rule suggestion awaiting agent review."""
    __slots__ = (
        "suggestion_id", "agent_id", "suggested_rule", "rationale",
        "evidence", "status", "trainer_version", "created_at",
        "reviewed_at", "reviewed_by",
    )

    def __init__(self, **kw):
        self.suggestion_id = kw.get("suggestion_id", f"psug_{uuid4().hex[:12]}")
        self.agent_id = kw.get("agent_id", "")
        self.suggested_rule = kw.get("suggested_rule", {})  # same shape as policy rule
        self.rationale = kw.get("rationale", "")  # plain English explanation
        self.evidence = kw.get("evidence", {})  # outcome patterns that justify this
        self.status = kw.get("status", "pending")  # pending | adopted | dismissed
        self.trainer_version = kw.get("trainer_version", "")
        self.created_at = kw.get("created_at", _now_iso())
        self.reviewed_at = kw.get("reviewed_at", "")
        self.reviewed_by = kw.get("reviewed_by", "")

    def to_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


class PolicySuggestionStore:
    """JSONL-backed store for trainer-generated policy suggestions."""

    def __init__(self, store_dir=str(_STORE_DIR)):
        self._suggestions: Dict[str, PolicySuggestion] = {}
        self._by_agent: Dict[str, List[str]] = {}  # agent_id -> [suggestion_ids]
        self._file: Optional[Path] = None
        self._lock = threading.Lock()
        try:
            p = Path(store_dir); p.mkdir(parents=True, exist_ok=True)
            self._file = p / "suggestions.jsonl"
            if self._file.exists():
                for line in self._file.read_text().strip().split("\n"):
                    if line.strip():
                        try:
                            sug = PolicySuggestion(**json.loads(line))
                            self._suggestions[sug.suggestion_id] = sug
                            self._by_agent.setdefault(sug.agent_id, []).append(sug.suggestion_id)
                        except Exception:
                            pass
        except Exception:
            pass

    def _persist(self, sug: PolicySuggestion):
        if self._file:
            try:
                with open(self._file, "a") as f:
                    f.write(json.dumps(sug.to_dict(), default=str) + "\n")
            except Exception:
                pass

    def add(self, agent_id: str, suggested_rule: dict, rationale: str,
            evidence: dict, trainer_version: str = "") -> PolicySuggestion:
        with self._lock:
            sug = PolicySuggestion(
                agent_id=agent_id,
                suggested_rule=suggested_rule,
                rationale=rationale,
                evidence=evidence,
                trainer_version=trainer_version,
            )
            self._suggestions[sug.suggestion_id] = sug
            self._by_agent.setdefault(agent_id, []).append(sug.suggestion_id)
            self._persist(sug)
            return sug

    def get(self, suggestion_id: str) -> Optional[PolicySuggestion]:
        return self._suggestions.get(suggestion_id)

    def list_for_agent(self, agent_id: str, status: str = "") -> List[PolicySuggestion]:
        ids = self._by_agent.get(agent_id, [])
        results = [self._suggestions[sid] for sid in ids if sid in self._suggestions]
        if status:
            results = [s for s in results if s.status == status]
        return results

    def review(self, suggestion_id: str, decision: str, reviewer_id: str) -> Optional[PolicySuggestion]:
        """Mark suggestion as adopted or dismissed."""
        sug = self._suggestions.get(suggestion_id)
        if not sug or sug.status != "pending":
            return None
        sug.status = decision  # "adopted" or "dismissed"
        sug.reviewed_at = _now_iso()
        sug.reviewed_by = reviewer_id
        self._persist(sug)
        return sug

    def stats(self) -> Dict[str, int]:
        counts = {"total": 0, "pending": 0, "adopted": 0, "dismissed": 0}
        for sug in self._suggestions.values():
            counts["total"] += 1
            counts[sug.status] = counts.get(sug.status, 0) + 1
        return counts


_suggestion_store: Optional[PolicySuggestionStore] = None


def get_suggestion_store() -> PolicySuggestionStore:
    global _suggestion_store
    if _suggestion_store is None:
        _suggestion_store = PolicySuggestionStore()
    return _suggestion_store


def generate_suggestions_from_trainer(agent_id: str) -> List[PolicySuggestion]:
    """Query Brain Policy Trainer and generate concrete acceptance rule suggestions.

    Analyzes buffered outcomes for the agent, identifies patterns that correlate
    with successful settlements, and produces suggested policy rules in the same
    format as existing acceptance policy rules.

    Returns list of new suggestions (may be empty). Never fails — returns [] on error.
    """
    suggestions: List[PolicySuggestion] = []
    try:
        from brain_policy_trainer import get_brain_trainer
        trainer = get_brain_trainer()
        stats = trainer.get_stats()
        trainer_version = f"cycles:{stats.get('training_cycles', 0)}"

        # Analyze buffered outcomes for patterns relevant to acceptance
        outcomes = trainer._outcomes_buffer
        if not outcomes:
            return []

        # Filter to this agent's outcomes (from commerce loop)
        agent_outcomes = [o for o in outcomes if o.get("agent_id") == agent_id
                          or o.get("segment") == "commerce_loop"]

        if len(agent_outcomes) < 3:
            return []  # need minimum sample before suggesting

        # Analyze outcome patterns
        completed = [o for o in agent_outcomes if o.get("outcome") == "completed"]
        failed = [o for o in agent_outcomes if o.get("outcome") != "completed"]
        total = len(agent_outcomes)
        success_rate = len(completed) / total if total else 0

        # Pattern 1: High success rate → suggest auto-accept for similar conditions
        if success_rate >= 0.8 and len(completed) >= 3:
            avg_revenue = sum(o.get("revenue", 0) for o in completed) / len(completed)
            if avg_revenue > 0:
                suggestions.append(get_suggestion_store().add(
                    agent_id=agent_id,
                    suggested_rule={
                        "conditions": [
                            {"field": "seller_ocs", "op": ">=", "value": 60},
                            {"field": "verification_confidence", "op": ">=", "value": 0.7},
                        ],
                        "action": "auto_accept",
                    },
                    rationale=(
                        f"Based on {total} recent outcomes with {success_rate:.0%} success rate "
                        f"and avg settlement of ${avg_revenue:.2f}. Agents with OCS >= 60 "
                        f"and verification confidence >= 0.7 consistently deliver."
                    ),
                    evidence={
                        "total_outcomes": total,
                        "completed": len(completed),
                        "failed": len(failed),
                        "success_rate": round(success_rate, 4),
                        "avg_revenue_usd": round(avg_revenue, 2),
                    },
                    trainer_version=trainer_version,
                ))

        # Pattern 2: High failure rate → suggest require_review
        if len(failed) >= 3 and success_rate < 0.5:
            suggestions.append(get_suggestion_store().add(
                agent_id=agent_id,
                suggested_rule={
                    "conditions": [
                        {"field": "seller_ocs", "op": "<", "value": 40},
                    ],
                    "action": "require_review",
                },
                rationale=(
                    f"Based on {total} recent outcomes with only {success_rate:.0%} success rate. "
                    f"Low-OCS agents (< 40) show elevated failure. Manual review recommended."
                ),
                evidence={
                    "total_outcomes": total,
                    "completed": len(completed),
                    "failed": len(failed),
                    "success_rate": round(success_rate, 4),
                },
                trainer_version=trainer_version,
            ))

        # Pattern 3: Brain signals correlating with success → leverage hive/yield
        if success_rate >= 0.7 and len(completed) >= 3:
            # Check if hive_success_rate was available in DO NOW context enrichment
            suggestions.append(get_suggestion_store().add(
                agent_id=agent_id,
                suggested_rule={
                    "conditions": [
                        {"field": "hive_success_rate", "op": ">=", "value": 0.7},
                        {"field": "yield_confidence", "op": ">=", "value": 0.6},
                    ],
                    "action": "auto_accept",
                },
                rationale=(
                    f"Brain intelligence signals (MetaHive success rate + Yield Memory confidence) "
                    f"correlate with {success_rate:.0%} settlement success across {len(completed)} deals. "
                    f"When both signals are high, auto-accept is safe."
                ),
                evidence={
                    "total_outcomes": total,
                    "success_rate": round(success_rate, 4),
                    "brain_signals_used": ["hive_success_rate", "yield_confidence"],
                },
                trainer_version=trainer_version,
            ))

    except Exception:
        pass

    return suggestions


def _eval_condition(cond, context):
    field, op, expected = cond.get("field"), cond.get("op"), cond.get("value")
    actual = context.get(field)
    if actual is None:
        return False
    if op == ">=": return actual >= expected
    if op == "<=": return actual <= expected
    if op == ">": return actual > expected
    if op == "<": return actual < expected
    if op == "==": return actual == expected
    if op == "!=": return actual != expected
    if op == "in": return actual in expected if isinstance(expected, list) else False
    return False


def evaluate_acceptance_policy(deal_id: str, agent_id: str) -> Dict[str, Any]:
    """Evaluate a deal against the agent's acceptance policy. Called by commerce loop."""
    store = get_acceptance_policy_store()
    policy = store.get_by_agent(agent_id)
    if not policy:
        return {"action": "require_review", "reason": "no_policy"}

    # Build context from deal data
    context: Dict[str, Any] = {}
    try:
        from protocol.event_store import get_event_store
        chain = get_event_store().get_chain(deal_id)
        for evt in chain:
            if evt.get("event_type") == "PROOF_VERIFIED":
                context["verification_confidence"] = evt.get("payload", {}).get("confidence", 0)
            if evt.get("event_type") in ("GO_APPROVED", "AUTO_GO_APPROVED"):
                context["amount_usd"] = evt.get("amount", 0)
                context["vertical"] = evt.get("payload", {}).get("vertical", "")
    except Exception:
        pass

    try:
        from protocol.agent_registry import get_agent_registry
        seller = get_agent_registry().get_agent(agent_id)
        if seller:
            context["seller_ocs"] = seller.get("ocs", 0)
    except Exception:
        pass

    # Enrich context with brain/learning signals (additive — failure is silent)
    try:
        from metahive_brain import query_hive
        vertical = context.get("vertical", "")
        if vertical:
            hive_result = query_hive(
                context={"vertical": vertical, "agent_id": agent_id},
                pattern_type="settlement",
                min_weight=0.3,
                limit=5,
            )
            if hive_result.get("ok") and hive_result.get("patterns"):
                patterns = hive_result["patterns"]
                total_success = sum(1 for p in patterns if p.get("outcome", {}).get("success"))
                context["hive_success_rate"] = round(total_success / max(len(patterns), 1), 4)
    except Exception:
        pass

    try:
        from yield_memory import get_best_action
        yield_result = get_best_action(
            username=agent_id,
            context={"deal_id": deal_id, "vertical": context.get("vertical", "")},
            pattern_type="acceptance",
        )
        if yield_result.get("ok"):
            context["yield_confidence"] = yield_result.get("confidence", 0)
            action = yield_result.get("recommended_action", {})
            if isinstance(action, dict) and action.get("action"):
                context["brain_recommended_action"] = action["action"]
    except Exception:
        pass

    # Enrich context with compliance/fraud signals (additive — failure is silent)
    try:
        from compliance_oracle import get_kyc_status
        kyc = get_kyc_status(agent_id)
        if kyc.get("ok"):
            level = kyc.get("kyc_level") or kyc.get("kyc", {}).get("level", "NONE")
            context["kyc_level"] = level
    except Exception:
        pass

    try:
        from fraud_detector import _BLOCKLIST, _ACTION_LOG
        risk = 0
        if agent_id in _BLOCKLIST:
            risk = 100
        else:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            recent = sum(1 for a in _ACTION_LOG
                         if a.get("username") == agent_id and a.get("timestamp", "") > cutoff)
            if recent > 50:
                risk = min(30 + recent, 100)
        context["fraud_risk_score"] = risk
    except Exception:
        pass

    # Enrich context with execution history signals (additive — failure is silent)
    try:
        from learning.execution_similarity import ExecutionSimilarityEngine
        sim = ExecutionSimilarityEngine()
        vertical = context.get("vertical", "")
        matches = sim.find_similar(
            pack=vertical or "general",
            platform="aigentsy",
            budget_usd=context.get("amount_usd", 0),
            title=vertical,
            limit=5,
            success_only=False,
        )
        if matches:
            successes = sum(1 for m in matches if m.execution.success)
            context["predicted_success"] = round(successes / len(matches), 4)
            durations = [m.execution.duration_minutes for m in matches if m.execution.duration_minutes > 0]
            if durations:
                context["estimated_timing"] = round(sum(durations) / len(durations), 1)
    except Exception:
        pass

    try:
        from brain_overlay.ocs import score_entity
        brain_score = score_entity(agent_id)
        if brain_score and brain_score > 0:
            context["brain_ocs_score"] = round(brain_score, 2)
    except Exception:
        pass

    # Evaluate rules — first match wins
    for i, rule in enumerate(policy.rules):
        conditions = rule.get("conditions", [])
        all_match = all(_eval_condition(c, context) for c in conditions)
        if all_match:
            return {
                "action": rule.get("action", "require_review"),
                "rule_index": i,
                "reason": f"policy_rule_{i}",
                "checks_passed": [c["field"] for c in conditions],
                "policy_hash": policy.policy_hash,
            }

    return {"action": policy.default_action, "reason": "no_rule_matched", "policy_hash": policy.policy_hash}


# ── Router ──

def get_acceptance_policy_router():
    try:
        from fastapi import APIRouter, Header, HTTPException
        from pydantic import BaseModel, Field
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol", tags=["Acceptance Policies"])

    class CreatePolicyRequest(BaseModel):
        rules: list = Field(..., description="Ordered rules — first match wins")
        default_action: str = Field("require_review")

    class EvaluateRequest(BaseModel):
        deal_id: str = Field(...)
        agent_id: str = Field(...)

    def _auth(api_key):
        from protocol.agent_registry import get_agent_registry
        a = get_agent_registry().authenticate(api_key)
        if not a:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return a

    @router.post("/acceptance-policies")
    async def create_policy(req: CreatePolicyRequest, x_api_key: str = Header(..., alias="X-API-Key")):
        """Create a programmable acceptance policy. First-match-wins rule evaluation."""
        agent = _auth(x_api_key)
        store = get_acceptance_policy_store()
        pol = store.create(agent["agent_id"], req.rules, req.default_action)
        return {"ok": True, "policy": pol.to_dict()}

    @router.get("/acceptance-policies/{agent_id}")
    async def get_policy(agent_id: str):
        """Get agent's acceptance policy."""
        store = get_acceptance_policy_store()
        pol = store.get_by_agent(agent_id)
        if not pol:
            return {"ok": True, "policy": None, "message": "No acceptance policy"}
        return {"ok": True, "policy": pol.to_dict()}

    @router.post("/acceptance-policies/evaluate")
    async def evaluate(req: EvaluateRequest, x_api_key: str = Header(..., alias="X-API-Key")):
        """Evaluate a deal against an agent's acceptance policy."""
        _auth(x_api_key)
        result = evaluate_acceptance_policy(req.deal_id, req.agent_id)
        result["ok"] = True
        return result

    # ── Policy Suggestion Endpoints (Brain Policy Trainer advisory layer) ──

    @router.post("/acceptance-policies/suggestions/generate")
    async def generate_suggestions(x_api_key: str = Header(..., alias="X-API-Key")):
        """Generate policy suggestions from Brain Policy Trainer based on observed outcomes.

        Analyzes recent acceptance/settlement outcome patterns and produces concrete
        rule suggestions in the same format as acceptance policy rules. Suggestions
        are advisory — they must be explicitly adopted to take effect.
        """
        agent = _auth(x_api_key)
        new_suggestions = generate_suggestions_from_trainer(agent["agent_id"])
        return {
            "ok": True,
            "suggestions_generated": len(new_suggestions),
            "suggestions": [s.to_dict() for s in new_suggestions],
        }

    @router.get("/acceptance-policies/suggestions/{agent_id}")
    async def list_suggestions(agent_id: str, status: str = ""):
        """List policy suggestions for an agent. Optional status filter: pending, adopted, dismissed."""
        store = get_suggestion_store()
        suggestions = store.list_for_agent(agent_id, status=status)
        return {
            "ok": True,
            "agent_id": agent_id,
            "suggestions": [s.to_dict() for s in suggestions],
            "stats": store.stats(),
        }

    class ReviewSuggestionRequest(BaseModel):
        decision: str = Field(..., description="'adopted' or 'dismissed'")

    @router.post("/acceptance-policies/suggestions/{suggestion_id}/review")
    async def review_suggestion(
        suggestion_id: str,
        req: ReviewSuggestionRequest,
        x_api_key: str = Header(..., alias="X-API-Key"),
    ):
        """Review a policy suggestion — adopt it into the active policy or dismiss it.

        Adopting a suggestion appends its rule to the agent's active acceptance policy.
        Dismissing it marks the suggestion as reviewed but takes no action.
        Both decisions are recorded with reviewer identity and timestamp.
        """
        agent = _auth(x_api_key)
        if req.decision not in ("adopted", "dismissed"):
            raise HTTPException(status_code=422, detail="Decision must be 'adopted' or 'dismissed'")

        sug_store = get_suggestion_store()
        sug = sug_store.get(suggestion_id)
        if not sug:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        if sug.status != "pending":
            raise HTTPException(status_code=422, detail=f"Suggestion already {sug.status}")

        # Record the review decision
        reviewed = sug_store.review(suggestion_id, req.decision, agent["agent_id"])

        result = {
            "ok": True,
            "suggestion_id": suggestion_id,
            "decision": req.decision,
            "reviewed_by": agent["agent_id"],
            "reviewed_at": reviewed.reviewed_at if reviewed else "",
        }

        # If adopted, append the suggested rule to the agent's active policy
        if req.decision == "adopted" and reviewed:
            pol_store = get_acceptance_policy_store()
            existing = pol_store.get_by_agent(sug.agent_id)
            if existing:
                # Append new rule to existing policy
                updated_rules = existing.rules + [sug.suggested_rule]
                new_pol = pol_store.create(sug.agent_id, updated_rules, existing.default_action)
                result["policy_updated"] = True
                result["new_policy_id"] = new_pol.policy_id
                result["new_policy_hash"] = new_pol.policy_hash
                result["total_rules"] = len(updated_rules)
            else:
                # No existing policy — create one with just this rule
                new_pol = pol_store.create(sug.agent_id, [sug.suggested_rule], "require_review")
                result["policy_created"] = True
                result["new_policy_id"] = new_pol.policy_id
                result["total_rules"] = 1

        return result

    return router
