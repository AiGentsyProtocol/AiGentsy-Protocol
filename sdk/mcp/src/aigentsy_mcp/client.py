"""Thin httpx client for the AiGentsy Settlement Protocol.

Self-contained — no dependency on the aigentsy SDK package.
Talks to the AiGentsy runtime over HTTPS.
"""

import os
from typing import Any, Dict, List, Optional

import httpx

_DEFAULT_BASE = "https://aigentsy-ame-runtime.onrender.com"
_TIMEOUT = 30.0


class AiGentsyClient:
    def __init__(self, base_url: str = "", api_key: str = ""):
        self._base = (base_url or os.getenv("AME_BASE", _DEFAULT_BASE)).rstrip("/")
        self._api_key = api_key or os.getenv("AME_API_KEY", "")

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    def _get(self, path: str) -> Dict[str, Any]:
        resp = httpx.get(f"{self._base}{path}", headers=self._headers(), timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        resp = httpx.post(f"{self._base}{path}", json=body, headers=self._headers(), timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def register(self, name: str, capabilities: Optional[List[str]] = None) -> Dict[str, Any]:
        data = self._post("/protocol/register", {
            "name": name,
            "capabilities": capabilities or ["marketing"],
        })
        if data.get("api_key"):
            self._api_key = data["api_key"]
        return data

    def create_proof_pack(self, agent_username: str, vertical: str = "marketing",
                          proof_type: str = "creative_preview",
                          scope_summary: str = "", proof_data: Optional[Dict] = None,
                          attachment_url: str = "",
                          **kwargs) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "agent_username": agent_username, "vertical": vertical,
            "proof_type": proof_type, "scope_summary": scope_summary,
            "proof_data": proof_data or {},
        }
        if attachment_url:
            body["attachment_url"] = attachment_url
        body.update(kwargs)
        return self._post("/protocol/proof-pack", body)

    def settle(self, deal_id: str, amount_usd: float, to_agent: str,
               proof_hash: str = "") -> Dict[str, Any]:
        return self._post("/protocol/settle", {
            "deal_id": deal_id,
            "amount_usd": amount_usd,
            "to_agent": to_agent,
            "proof_hash": proof_hash,
        })

    def verify_proof_bundle(self, deal_id: str) -> Dict[str, Any]:
        return self._get(f"/proof/{deal_id}/verify")

    def get_proof_bundle(self, deal_id: str) -> Dict[str, Any]:
        return self._get(f"/protocol/proofs/{deal_id}/export")

    def get_proof_chain(self, deal_id: str) -> Dict[str, Any]:
        return self._get(f"/protocol/proof-chain/{deal_id}")

    def settle_multi(self, deal_id: str, total_amount_usd: float,
                     splits: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._post("/protocol/settle/multi", {
            "deal_id": deal_id, "total_amount_usd": total_amount_usd, "splits": splits,
        })

    def issue_attestation(self, agent_id: str) -> Dict[str, Any]:
        return self._get(f"/protocol/agents/{agent_id}/attestation")

    def get_fee_tiers(self) -> Dict[str, Any]:
        return self._get("/protocol/fee-tiers")

    def create_webhook(self, url: str, events: Optional[List[str]] = None,
                       secret: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"url": url, "events": events or ["*"]}
        if secret:
            body["secret"] = secret
        return self._post("/protocol/webhooks", body)

    # ── Acceptance Gate (v1.1) ──

    def acceptance_submit(self, deal_id: str, downstream_action: str = "settle",
                          review_deadline_seconds: int = 0) -> Dict[str, Any]:
        return self._post("/protocol/acceptance/submit", {
            "deal_id": deal_id,
            "downstream_action": downstream_action,
            "review_deadline_seconds": review_deadline_seconds,
        })

    def acceptance_decide(self, acceptance_id: str, decision: str,
                          reason: str = "", checks_passed: Optional[List[str]] = None,
                          checks_failed: Optional[List[str]] = None) -> Dict[str, Any]:
        endpoint = f"/protocol/acceptance/{acceptance_id}/accept" if decision == "accept" else f"/protocol/acceptance/{acceptance_id}/reject"
        return self._post(endpoint, {
            "decision": decision,
            "reason": reason,
            "checks_passed": checks_passed or [],
            "checks_failed": checks_failed or [],
        })

    def acceptance_status(self, deal_id: str) -> Dict[str, Any]:
        return self._get(f"/protocol/acceptance/deal/{deal_id}")

    # ── Acceptance Runtime · Inference Acceptance Layer (Pass 82J) ──

    def evaluate_inference(
        self,
        prompt: str,
        raw_output: str,
        policy: Dict[str, Any],
        consequence: Optional[Dict[str, Any]] = None,
        required_evidence: Optional[Dict[str, bool]] = None,
        risk_tier: str = "medium",
        model_metadata: Optional[Dict[str, Any]] = None,
        expected_decision: Optional[str] = None,
        intended_action: str = "",
    ) -> Dict[str, Any]:
        """POST /acceptance-runtime/evaluate via the existing runtime.

        Pass 82J · MCP Consequence Middleware. Delegates the decision to
        the live Acceptance Runtime evaluator (Pass 82G). No new evaluator,
        no new endpoint, no new bundle format.

        ``intended_action`` is folded ADDITIVELY into the outgoing
        consequence payload as ``consequence["intended_action"]`` so it
        lands on ``INFERENCE_CONSEQUENCE_RECORDED.payload`` for NEW
        evaluations only. Existing event chains and bundle hashes are
        unaffected.
        """
        cons = dict(consequence or {})
        if intended_action:
            cons["intended_action"] = intended_action
        body: Dict[str, Any] = {
            "prompt": prompt,
            "raw_output": raw_output,
            "policy": policy or {},
            "required_evidence": required_evidence or {},
            "consequence": cons,
            "risk_tier": risk_tier or "medium",
            "model_metadata": model_metadata or {},
        }
        if expected_decision:
            body["expected_decision"] = expected_decision
        return self._post("/acceptance-runtime/evaluate", body)
