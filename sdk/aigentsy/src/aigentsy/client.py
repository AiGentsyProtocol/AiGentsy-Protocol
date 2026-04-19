"""
AiGentsy Settlement Protocol — Python SDK
==========================================

Full-loop client for the AiGentsy Settlement Protocol.
Covers the entire deal lifecycle: register -> stamp/proof-pack -> go -> verify -> settle.

Usage:
    from aigentsy import AiGentsyClient

    client = AiGentsyClient("https://aigentsy-ame-runtime.onrender.com")
    result = client.register("my_agent", capabilities=["marketing"])

    proof = client.stamp(result["agent_id"], "Logo design delivered")
    print(proof["deal_id"], proof["verify_url"])
"""

import time
import logging
import httpx
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aigentsy")

_MAX_RETRIES = 3
_DEFAULT_RETRY_AFTER = 2


class AiGentsyClient:
    """Synchronous Python client for the AiGentsy Settlement Protocol."""

    def __init__(self, base_url: str = "http://localhost:10000", api_key: str = None):
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.Client(base_url=self._base, timeout=30.0)

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    def _post(self, path: str, body: dict = None, auth: bool = False) -> dict:
        headers = self._headers() if auth else {"Content-Type": "application/json"}
        for attempt in range(_MAX_RETRIES + 1):
            resp = self._client.post(path, json=body or {}, headers=headers)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            wait = float(resp.headers.get("Retry-After", _DEFAULT_RETRY_AFTER * (2 ** attempt)))
            logger.warning("429 on POST %s — retry %d/%d in %.1fs", path, attempt + 1, _MAX_RETRIES, wait)
            if attempt == _MAX_RETRIES:
                resp.raise_for_status()
            time.sleep(wait)
        return resp.json()

    def _get(self, path: str, params: dict = None, auth: bool = False) -> dict:
        headers = self._headers() if auth else {}
        for attempt in range(_MAX_RETRIES + 1):
            resp = self._client.get(path, params=params, headers=headers)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            wait = float(resp.headers.get("Retry-After", _DEFAULT_RETRY_AFTER * (2 ** attempt)))
            logger.warning("429 on GET %s — retry %d/%d in %.1fs", path, attempt + 1, _MAX_RETRIES, wait)
            if attempt == _MAX_RETRIES:
                resp.raise_for_status()
            time.sleep(wait)
        return resp.json()

    # ── Registration & Identity ──

    def register(self, name: str, capabilities: List[str] = None, **kwargs) -> Dict:
        """Register a new agent. Auto-stores the returned API key."""
        data = self._post("/protocol/register", {
            "name": name, "capabilities": capabilities or [], **kwargs,
        })
        if data.get("api_key"):
            self._api_key = data["api_key"]
        return data

    def get_reputation(self, agent_id: str) -> Dict:
        """Get OCS score and tier for any agent."""
        return self._get(f"/protocol/reputation/{agent_id}")

    def get_protocol_info(self) -> Dict:
        """Get protocol metadata and statistics."""
        return self._get("/protocol/info")

    # ── Proof Creation ──

    def stamp(self, agent_id: str, description: str = "",
              attachment_url: str = None) -> Dict:
        """Simplified proof creation — fewest params, fastest path.

        Equivalent to createProofPack with sensible defaults.
        Returns dict with deal_id, proof_hash, verify_url, etc.
        """
        body: Dict[str, Any] = {
            "agent_id": agent_id,
            "description": description,
        }
        if attachment_url:
            body["attachment_url"] = attachment_url
        return self._post("/protocol/stamp", body)

    def create_proof_pack(self, agent_username: str, vertical: str = "marketing",
                          proof_type: str = "creative_preview",
                          scope_summary: str = "", proof_data: Dict = None,
                          attachment_url: str = None, sku_id: str = None,
                          **kwargs) -> Dict:
        """Create a ProofPack — full control over the deal lifecycle entry point."""
        body = {
            "agent_username": agent_username, "vertical": vertical,
            "proof_type": proof_type, "scope_summary": scope_summary,
            "proof_data": proof_data or {},
        }
        if attachment_url:
            body["attachment_url"] = attachment_url
        if sku_id:
            body["sku_id"] = sku_id
        body.update(kwargs)
        return self._post("/protocol/proof-pack", body)

    # ── Buyer Mandates ──

    def create_mandate(self, buyer_id: str, max_amount: float,
                       verticals: List[str] = None, confidence: float = 0.80) -> Dict:
        """Create a pre-authorized spending limit."""
        return self._post("/protocol/mandates", {
            "buyer_id": buyer_id,
            "max_amount_per_deal_usd": max_amount,
            "allowed_verticals": verticals or ["marketing"],
            "confidence_threshold": confidence,
        }, auth=True)

    def list_mandates(self, buyer_id: str) -> Dict:
        """List mandates for a buyer."""
        return self._get(f"/protocol/mandates/{buyer_id}", auth=True)

    # ── Deal Approval ──

    def auto_go(self, deal_id: str, quote_id: str, buyer_id: str,
                mandate_id: str = None, seller_agent_id: str = None) -> Dict:
        """Autonomy mode — auto-approve if mandate + reputation + confidence pass."""
        return self._post("/protocol/auto-go", {
            "deal_id": deal_id, "quote_id": quote_id,
            "buyer_id": buyer_id, "mandate_id": mandate_id,
            "seller_agent_id": seller_agent_id,
        })

    def go(self, deal_id: str, quote_id: str, scope_lock_hash: str,
           **kwargs) -> Dict:
        """Lock scope, enforce pricing, create payment link."""
        return self._post("/protocol/go", {
            "deal_id": deal_id, "quote_id": quote_id,
            "scope_lock_hash": scope_lock_hash, **kwargs,
        })

    # ── Settlement ──

    def settle(self, deal_id: str, amount: float, actor_id: str,
               counterparty_id: str, proof_hash: str = None) -> Dict:
        """Settle a deal — triggers fee deduction and payout routing."""
        return self._post("/protocol/settle", {
            "deal_id": deal_id, "amount": amount,
            "actor_id": actor_id, "counterparty_id": counterparty_id,
            "proof_hash": proof_hash,
        }, auth=True)

    def fee_estimate(self, amount: float, agent_id: str = None,
                     rail: str = None) -> Dict:
        """Preview all fees before settlement."""
        params: Dict[str, Any] = {"amount": amount}
        if agent_id:
            params["agent_id"] = agent_id
        if rail:
            params["rail"] = rail
        return self._get("/protocol/fee-estimate", params=params)

    # ── Verification ──

    def verify_proof(self, deal_id: str, proof_hash: str, proof_type: str,
                     provider: str = None, proof_data: Dict = None) -> Dict:
        """Verify proof via a verification provider."""
        return self._post("/protocol/verify/provider", {
            "deal_id": deal_id, "proof_hash": proof_hash,
            "proof_type": proof_type, "provider": provider,
            "proof_data": proof_data or {},
        })

    def list_verification_providers(self) -> Dict:
        """List available verification providers."""
        return self._get("/protocol/verify/providers")

    # ── Audit & Proof Bundles ──

    def get_proof_bundle(self, deal_id: str) -> Dict:
        """Full proof bundle for a deal."""
        return self._get(f"/proof/{deal_id}")

    def verify_proof_bundle(self, deal_id: str) -> Dict:
        """Cryptographic verification of deal proof bundle."""
        return self._get(f"/proof/{deal_id}/verify")

    def get_timeline(self, deal_id: str) -> Dict:
        """Full deal timeline with events + ledger."""
        return self._get(f"/protocol/deals/{deal_id}/timeline")

    def get_attribution(self, deal_id: str) -> Dict:
        """Full attribution: events, ledger, referrals, policy snapshot."""
        return self._get(f"/protocol/deals/{deal_id}/attribution", auth=True)

    def get_revenue_audit(self, agent_id: str) -> Dict:
        """Revenue and cost audit trail for an agent."""
        return self._get(f"/protocol/agents/{agent_id}/revenue-audit", auth=True)

    def get_merkle_root(self) -> Dict:
        """Latest Merkle root for settlement verification."""
        return self._get("/protocol/merkle/latest")

    # ── Idempotency Admin ──

    def get_idempotency_receipt(self, key: str) -> Dict:
        """Lookup a specific idempotency receipt."""
        return self._get(f"/protocol/idempotency/{key}")

    def get_idempotency_stats(self) -> Dict:
        """Idempotency cache statistics."""
        return self._get("/protocol/idempotency/stats")

    # ── Payout Destinations ──

    def create_payout_destination(self, owner_id: str, rail: str,
                                  address: str, metadata: Dict = None) -> Dict:
        """Create a payout destination (Stripe/ACH/PayPal/Crypto)."""
        return self._post("/protocol/payout-destinations", {
            "owner_id": owner_id, "rail": rail,
            "address": address, "metadata": metadata or {},
        }, auth=True)

    def list_payout_destinations(self, owner_id: str) -> Dict:
        """List payout destinations for an owner."""
        return self._get(f"/protocol/payout-destinations/{owner_id}", auth=True)

    # ── Executable SLAs ──

    def create_sla(self, conditions: List[Dict] = None, guarantees: Dict = None,
                   stake_amount: float = 0, auto_settle: bool = True) -> Dict:
        """Create an executable SLA."""
        return self._post("/protocol/slas", {
            "conditions": conditions or [], "guarantees": guarantees or {},
            "stake_amount_usd": stake_amount, "auto_settle_on_verify": auto_settle,
        }, auth=True)

    def evaluate_sla(self, sla_id: str, deal_context: Dict) -> Dict:
        """Evaluate SLA against deal context."""
        return self._post(f"/protocol/slas/{sla_id}/evaluate", {"deal_context": deal_context})

    def get_sla(self, sla_id: str) -> Dict:
        """Get SLA details."""
        return self._get(f"/protocol/slas/{sla_id}")

    def list_sla_templates(self) -> Dict:
        """List available SLA templates for common verticals."""
        return self._get("/protocol/slas/templates")

    def create_sla_from_template(self, template_id: str,
                                 stake_amount: float = 0) -> Dict:
        """Create an SLA from a pre-built template. One-click SLA creation."""
        return self._post("/protocol/slas/from-template", {
            "template_id": template_id, "stake_amount_usd": stake_amount,
        }, auth=True)

    def meter_mcp_tool_call(self, name: str, server_name: str = "",
                            call_count: int = 1, input_tokens: int = 0,
                            output_tokens: int = 0, latency_ms: int = 0) -> Dict:
        """Record a metered MCP tool call and create a proof pack."""
        return self._post("/protocol/bridges/mcp/meter", {
            "name": name, "server_name": server_name,
            "call_count": call_count, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "latency_ms": latency_ms,
        })

    def a2a_task_complete(self, task_id: str, status_state: str = "completed",
                          artifacts: List[Dict] = None, agent_id: str = "") -> Dict:
        """Record an A2A task completion and create a proof pack."""
        return self._post("/protocol/bridges/a2a/task-complete", {
            "id": task_id, "status": {"state": status_state},
            "artifacts": artifacts or [], "agent_id": agent_id,
        })

    # ── Acceptance Gate ──

    def submit_for_acceptance(self, deal_id: str, downstream_action: str = "settle") -> Dict:
        """Submit a verified output for acceptance review before release or payment."""
        return self._post("/protocol/acceptance/submit", {
            "deal_id": deal_id, "downstream_action": downstream_action,
        }, auth=True)

    def accept_output(self, acceptance_id: str, reason: str = "",
                      checks_passed: List[str] = None) -> Dict:
        """Accept the output — triggers the configured downstream action."""
        return self._post(f"/protocol/acceptance/{acceptance_id}/accept", {
            "decision": "accept", "reason": reason,
            "checks_passed": checks_passed or [],
        }, auth=True)

    def reject_output(self, acceptance_id: str, reason: str = "",
                      checks_failed: List[str] = None) -> Dict:
        """Reject the output — triggers hold or escalation."""
        return self._post(f"/protocol/acceptance/{acceptance_id}/reject", {
            "decision": "reject", "reason": reason,
            "checks_failed": checks_failed or [],
        }, auth=True)

    def get_acceptance(self, deal_id: str) -> Dict:
        """Get acceptance status for a deal."""
        return self._get(f"/protocol/acceptance/deal/{deal_id}")

    # ── Acceptance Policies ──

    def create_acceptance_policy(self, rules: List[Dict],
                                 default_action: str = "require_review") -> Dict:
        """Create a programmable acceptance policy. First-match-wins rules."""
        return self._post("/protocol/acceptance-policies", {
            "rules": rules, "default_action": default_action,
        }, auth=True)

    def get_acceptance_policy(self, agent_id: str) -> Dict:
        """Get an agent's acceptance policy."""
        return self._get(f"/protocol/acceptance-policies/{agent_id}")

    def evaluate_acceptance_policy(self, deal_id: str, agent_id: str) -> Dict:
        """Evaluate a deal against an agent's acceptance policy."""
        return self._post("/protocol/acceptance-policies/evaluate", {
            "deal_id": deal_id, "agent_id": agent_id,
        }, auth=True)

    # ── Acceptance Policy Suggestions (Brain Policy Trainer advisory layer) ──

    def generate_policy_suggestions(self) -> Dict:
        """Generate acceptance policy suggestions from outcome patterns.

        The Brain Policy Trainer analyzes recent settlement outcomes and
        produces concrete rule suggestions. Suggestions are advisory —
        they must be explicitly adopted to take effect.
        """
        return self._post("/protocol/acceptance-policies/suggestions/generate", {}, auth=True)

    def list_policy_suggestions(self, agent_id: str, status: str = "") -> Dict:
        """List acceptance policy suggestions for an agent.

        Args:
            agent_id: Agent to list suggestions for.
            status: Optional filter — 'pending', 'adopted', or 'dismissed'.
        """
        url = f"/protocol/acceptance-policies/suggestions/{agent_id}"
        if status:
            url += f"?status={status}"
        return self._get(url)

    def review_policy_suggestion(self, suggestion_id: str, decision: str) -> Dict:
        """Adopt or dismiss a policy suggestion.

        Adopting a suggestion appends its rule to the agent's active
        acceptance policy. Dismissing records the decision but takes no action.

        Args:
            suggestion_id: The suggestion to review.
            decision: 'adopted' or 'dismissed'.
        """
        return self._post(f"/protocol/acceptance-policies/suggestions/{suggestion_id}/review", {
            "decision": decision,
        }, auth=True)

    # ── Commerce Graph ──

    def commerce_graph_query(self, capability: str = "", min_ocs: int = 0,
                             max_delivery_hours: int = 0, **kwargs) -> Dict:
        """Find the best agents for a commercial need."""
        return self._post("/protocol/commerce-graph/query", {
            "capability": capability, "min_ocs": min_ocs,
            "max_delivery_hours": max_delivery_hours, **kwargs,
        })

    def commerce_graph_profile(self, agent_id: str) -> Dict:
        """Full commercial profile for an agent."""
        return self._get(f"/protocol/commerce-graph/agent/{agent_id}")

    # ── Intent Exchange ──

    def create_intent(self, client_id: str, capability: str, budget_usd: float,
                      deadline_hours: int = 24, **kwargs) -> Dict:
        """Publish an intent for agents to bid on."""
        return self._post("/protocol/intents", {
            "client_id": client_id, "capability": capability,
            "budget_usd": budget_usd, "deadline_hours": deadline_hours, **kwargs,
        })

    def submit_bid(self, intent_id: str, agent_id: str, price_usd: float,
                   delivery_hours: int, message: str = "") -> Dict:
        """Submit a sealed bid on an intent."""
        return self._post(f"/protocol/intents/{intent_id}/bids", {
            "agent_id": agent_id, "price_usd": price_usd,
            "delivery_hours": delivery_hours, "message": message,
        })

    def close_intent(self, intent_id: str) -> Dict:
        """Close bidding, score bids, select winner."""
        return self._post(f"/protocol/intents/{intent_id}/close", {})

    def get_intent(self, intent_id: str) -> Dict:
        """Get intent details."""
        return self._get(f"/protocol/intents/{intent_id}")

    # ── Subcontracting ──

    def create_subcontract(self, deal_id: str, scope: str, budget_cap_usd: float,
                           **kwargs) -> Dict:
        """Create a subcontract under a parent deal."""
        return self._post(f"/protocol/deals/{deal_id}/subcontracts", {
            "scope": scope, "budget_cap_usd": budget_cap_usd, **kwargs,
        }, auth=True)

    def list_subcontracts(self, deal_id: str) -> Dict:
        """List subcontracts for a deal."""
        return self._get(f"/protocol/deals/{deal_id}/subcontracts", auth=True)

    # ── Capabilities ──

    def get_capabilities(self, agent_id: str) -> Dict:
        """Get agent capability manifest."""
        return self._get(f"/protocol/capabilities/{agent_id}")

    # ── Agent Storefronts ──

    def create_storefront(self, headline: str = "", description: str = "",
                          vertical: str = "", **kwargs) -> Dict:
        """Create or update agent storefront."""
        return self._post("/protocol/storefront/create", {
            "headline": headline, "description": description,
            "vertical": vertical, **kwargs,
        }, auth=True)

    def get_storefront(self, agent_id: str) -> Dict:
        """Get storefront data (JSON)."""
        return self._get(f"/protocol/storefront/{agent_id}")

    # ── KPI Dashboard ──

    def get_kpi_overview(self) -> Dict:
        """Get protocol-wide KPI overview."""
        return self._get("/protocol/kpi/overview", auth=True)

    def get_agent_kpis(self, agent_id: str) -> Dict:
        """Get per-agent KPIs."""
        return self._get(f"/protocol/kpi/agent/{agent_id}", auth=True)

    def get_vertical_kpis(self) -> Dict:
        """Get per-vertical KPI breakdown."""
        return self._get("/protocol/kpi/verticals", auth=True)

    # ── Agent Spawn Trees ──

    def spawn_child(self, parent_id: str, child_id: str,
                    stake_amount: float = 0, **kwargs) -> Dict:
        """Spawn a child agent with inherited trust."""
        return self._post(f"/protocol/agents/{parent_id}/spawn", {
            "child_id": child_id, "stake_amount": stake_amount, **kwargs,
        })

    def get_spawn_tree(self, agent_id: str) -> Dict:
        """Get spawn tree for an agent."""
        return self._get(f"/protocol/agents/{agent_id}/spawn-tree")

    # ── Outcome-Contingent Pricing ──

    def create_outcome(self, agent_id: str, client_id: str, metric: str,
                       base_usd: float, bonus_usd: float = 0,
                       threshold: float = 0, **kwargs) -> Dict:
        """Create an outcome-contingent deal."""
        return self._post("/protocol/outcomes", {
            "agent_id": agent_id, "client_id": client_id,
            "metric": metric, "base_usd": base_usd,
            "bonus_usd": bonus_usd, "threshold": threshold, **kwargs,
        })

    def measure_outcome(self, deal_id: str, measured_value: float) -> Dict:
        """Submit outcome measurement."""
        return self._post(f"/protocol/outcomes/{deal_id}/measure", {
            "measured_value": measured_value,
        })

    def resolve_outcome(self, deal_id: str) -> Dict:
        """Resolve outcome and compute payout."""
        return self._post(f"/protocol/outcomes/{deal_id}/resolve", {})

    # ── Identity Resolution ──

    def bind_identity(self, agent_id: str, binding_type: str,
                      binding_value: str) -> Dict:
        """Bind an external identity to an agent."""
        return self._post("/protocol/identity/bind", {
            "agent_id": agent_id, "binding_type": binding_type,
            "binding_value": binding_value,
        })

    def verify_identity(self, binding_id: str, token: str = "") -> Dict:
        """Verify an identity binding."""
        return self._post(f"/protocol/identity/bind/{binding_id}/verify", {
            "submitted_token": token,
        })

    def get_identity_passport(self, agent_id: str) -> Dict:
        """Get public identity passport with verified bindings."""
        return self._get(f"/protocol/identity/{agent_id}/passport")

    # ── Autonomous Commerce Loop ──

    def commerce_enroll(self, sla_id: str = "", offering_id: str = "",
                        auto_invoice: bool = True, auto_credential: bool = True) -> Dict:
        """Enroll agent in the autonomous commerce loop."""
        return self._post("/protocol/commerce/enroll", {
            "sla_id": sla_id, "offering_id": offering_id,
            "auto_invoice": auto_invoice, "auto_credential": auto_credential,
        }, auth=True)

    def commerce_trigger(self, deal_id: str) -> Dict:
        """Trigger one autonomous loop cycle for a deal."""
        return self._post("/protocol/commerce/trigger", {"deal_id": deal_id}, auth=True)

    def commerce_status(self, agent_id: str) -> Dict:
        """Get loop enrollment status."""
        return self._get(f"/protocol/commerce/status/{agent_id}", auth=True)

    # ── Embeddable Widget ──

    def configure_widget(self, theme: str = "dark", show_sla: bool = True,
                         show_pay_button: bool = True) -> Dict:
        """Create an embeddable widget configuration."""
        return self._post("/protocol/widget/configure", {
            "theme": theme, "show_sla": show_sla, "show_pay_button": show_pay_button,
        }, auth=True)

    # ── Settlement Intelligence ──

    def get_intelligence_feed(self) -> Dict:
        """Get aggregated, anonymized settlement intelligence."""
        return self._get("/protocol/intelligence/feed")

    def get_sla_benchmarks(self) -> Dict:
        """Get SLA template benchmarks."""
        return self._get("/protocol/intelligence/sla-benchmarks")

    def get_premium_intelligence(self) -> Dict:
        """Get premium intelligence feed with brain intelligence overlay.

        Authenticated. Returns unrounded metrics, full vertical stats
        without k-anonymity suppression, and brain_intelligence section
        with MetaHive pattern stats and AI routing recommendations.
        """
        return self._get("/protocol/intelligence/premium", auth=True)

    # ── SLA Marketplace ──

    def publish_service_offering(self, title: str, vertical: str = "",
                                 sla_template_id: str = "", sla_id: str = "",
                                 stake_amount: float = 0, capabilities: List[str] = None,
                                 price_range: Dict = None) -> Dict:
        """Publish an SLA-backed service offering to the marketplace."""
        return self._post("/protocol/sla-marketplace/publish", {
            "title": title, "vertical": vertical,
            "sla_template_id": sla_template_id, "sla_id": sla_id,
            "stake_amount_usd": stake_amount,
            "capabilities": capabilities or [],
            "price_range_usd": price_range or {},
        }, auth=True)

    def browse_sla_marketplace(self, vertical: str = "", min_ocs: int = 0,
                               max_delivery_hours: int = 0, limit: int = 50) -> Dict:
        """Browse SLA-backed service offerings."""
        params: Dict[str, Any] = {"limit": limit}
        if vertical:
            params["vertical"] = vertical
        if min_ocs:
            params["min_ocs"] = min_ocs
        if max_delivery_hours:
            params["max_delivery_hours"] = max_delivery_hours
        return self._get("/protocol/sla-marketplace", params=params)

    # ── Webhook Dashboard ──

    def get_webhook_dashboard(self) -> Dict:
        """Get webhook delivery dashboard overview."""
        return self._get("/protocol/webhook-dashboard", auth=True)

    def get_webhook_detail(self, hook_id: str) -> Dict:
        """Get detailed delivery history for a webhook."""
        return self._get(f"/protocol/webhook-dashboard/{hook_id}", auth=True)

    def retry_webhook(self, hook_id: str) -> Dict:
        """Retry the last failed delivery for a webhook."""
        return self._post(f"/protocol/webhook-dashboard/{hook_id}/retry", auth=True)

    # ── Referrals ──

    def register_referral(self, referrer_id: str, referred_id: str) -> Dict:
        """Register a referral link."""
        return self._post("/protocol/referrals/register", {
            "referrer_agent_id": referrer_id, "referred_agent_id": referred_id,
        }, auth=True)

    def get_referral_chain(self, agent_id: str) -> Dict:
        """Get referral chain for an agent."""
        return self._get(f"/protocol/referrals/{agent_id}")

    # ── Invoicing ──

    def generate_invoice(self, deal_id: str, notes: str = "") -> Dict:
        """Generate invoice from a settled deal."""
        return self._post("/protocol/invoices/generate", {
            "deal_id": deal_id, "notes": notes,
        }, auth=True)

    def get_invoice(self, invoice_id: str) -> Dict:
        """Get invoice details."""
        return self._get(f"/protocol/invoices/{invoice_id}")

    # ── Agent Directory ──

    def browse_directory(self, capability: str = "", min_ocs: int = 0,
                         limit: int = 25) -> Dict:
        """Browse proof-backed agent directory."""
        params: Dict[str, Any] = {"limit": limit}
        if capability:
            params["capability"] = capability
        if min_ocs:
            params["min_ocs"] = min_ocs
        return self._get("/protocol/directory", params=params)

    def get_agent_profile(self, agent_id: str) -> Dict:
        """Get proof-backed agent profile."""
        return self._get(f"/protocol/directory/{agent_id}")

    # ── Disputes ──

    def open_dispute(self, deal_id: str, claimant_id: str,
                     respondent_id: str, reason: str = "") -> Dict:
        """Open a dispute on a deal."""
        return self._post(f"/protocol/disputes/{deal_id}/open", {
            "claimant_id": claimant_id, "respondent_id": respondent_id, "reason": reason,
        }, auth=True)

    def get_dispute(self, deal_id: str) -> Dict:
        """Get dispute status for a deal."""
        return self._get(f"/protocol/disputes/{deal_id}")

    # ── Proof Chains ──

    def get_proof_chain(self, deal_id: str) -> Dict:
        """Get proof chain provenance for a deal."""
        return self._get(f"/protocol/proof-chain/{deal_id}")

    def get_proof_lineage(self, deal_id: str) -> Dict:
        """Get full provenance lineage: ancestors + self + descendants."""
        return self._get(f"/protocol/proof-chain/{deal_id}/lineage")

    # ── Multi-Party Settlement ──

    def settle_multi(self, deal_id: str, total_amount: float,
                     splits: List[Dict], provider: str = "balance",
                     proof_hash: str = None) -> Dict:
        """Multi-party settlement with N-way splits."""
        return self._post("/protocol/settle/multi", {
            "deal_id": deal_id, "total_amount_usd": total_amount,
            "splits": splits, "provider": provider,
            "proof_hash": proof_hash,
        }, auth=True)

    def get_deal_splits(self, deal_id: str) -> Dict:
        """Get multi-party split breakdown for a deal."""
        return self._get(f"/protocol/deals/{deal_id}/splits")

    # ── Webhook Subscriptions ──

    def create_webhook(self, url: str, events: List[str] = None,
                       secret: str = None) -> Dict:
        """Register a webhook for protocol events."""
        body: Dict[str, Any] = {"url": url}
        if events:
            body["events"] = events
        if secret:
            body["secret"] = secret
        return self._post("/protocol/webhooks", body, auth=True)

    def list_webhooks(self) -> Dict:
        """List registered webhooks."""
        return self._get("/protocol/webhooks", auth=True)

    def delete_webhook(self, hook_id: str) -> Dict:
        """Delete a webhook."""
        headers = self._headers()
        resp = self._client.delete(f"/protocol/webhooks/{hook_id}", headers=headers)
        resp.raise_for_status()
        return resp.json()

    def test_webhook(self, hook_id: str) -> Dict:
        """Send a test event to a webhook."""
        return self._post(f"/protocol/webhooks/{hook_id}/test", auth=True)

    # ── Programmable Mandates ──

    def create_programmable_mandate(self, buyer_id: str, rules: List[Dict],
                                    default_action: str = "reject",
                                    max_amount: float = 500.0) -> Dict:
        """Create a programmable mandate with conditional rules."""
        return self._post("/protocol/mandates/programmable", {
            "buyer_id": buyer_id, "rules": rules,
            "default_action": default_action,
            "max_amount_per_deal_usd": max_amount,
        }, auth=True)

    def evaluate_mandate(self, context: Dict, buyer_id: str = None,
                         mandate_id: str = None) -> Dict:
        """Evaluate context against a programmable mandate."""
        body: Dict[str, Any] = {"context": context}
        if buyer_id:
            body["buyer_id"] = buyer_id
        if mandate_id:
            body["mandate_id"] = mandate_id
        return self._post("/protocol/mandates/programmable/evaluate", body, auth=True)

    # ── Reputation Attestations ──

    def issue_attestation(self, agent_id: str) -> Dict:
        """Issue a signed W3C Verifiable Credential for an agent's reputation."""
        return self._post(f"/protocol/attestations/issue?agent_id={agent_id}", auth=True)

    def get_attestation(self, agent_id: str) -> Dict:
        """Get the latest reputation attestation for an agent."""
        return self._get(f"/protocol/attestations/{agent_id}")

    def verify_attestation(self, credential: Dict,
                           public_key_base64: str = "") -> Dict:
        """Verify a reputation attestation."""
        return self._post("/protocol/attestations/verify", {
            "credential": credential, "public_key_base64": public_key_base64,
        })

    # ── Credential Marketplace ──

    def publish_credential(self, deal_id: str,
                           capability_tags: List[str] = None) -> Dict:
        """Publish a verified proof as a discoverable credential."""
        return self._post("/protocol/credentials/publish", {
            "deal_id": deal_id, "capability_tags": capability_tags or [],
        }, auth=True)

    def search_credentials(self, capability: str = "", vertical: str = "",
                           agent_id: str = "", min_confidence: float = 0,
                           limit: int = 50) -> Dict:
        """Search the credential marketplace."""
        params: Dict[str, Any] = {"limit": limit}
        if capability:
            params["capability"] = capability
        if vertical:
            params["vertical"] = vertical
        if agent_id:
            params["agent_id"] = agent_id
        if min_confidence:
            params["min_confidence"] = min_confidence
        return self._get("/protocol/credentials/search", params=params)

    # ── Volume Fee Tiers ──

    def get_fee_tiers(self) -> Dict:
        """Get the public fee tier schedule."""
        return self._get("/protocol/fee-tiers")

    def get_agent_fee_tier(self, agent_id: str) -> Dict:
        """Get an agent's current volume tier and 30-day volume."""
        return self._get(f"/protocol/fee-tiers/{agent_id}")

    # ── Reputation Staking ──

    def create_stake(self, deal_id: str, amount: float,
                     commitment: str = "") -> Dict:
        """Stake balance against a commitment for a deal."""
        return self._post("/protocol/stakes", {
            "deal_id": deal_id, "amount_usd": amount,
            "commitment": commitment,
        }, auth=True)

    def resolve_stake(self, stake_id: str, outcome: str) -> Dict:
        """Resolve a stake as 'success' (bonus) or 'failure' (slash)."""
        return self._post(f"/protocol/stakes/{stake_id}/resolve", {
            "outcome": outcome,
        }, auth=True)

    def get_agent_stakes(self, agent_id: str, active_only: bool = False) -> Dict:
        """List stakes for an agent."""
        params = {"active_only": active_only} if active_only else {}
        return self._get(f"/protocol/stakes/{agent_id}", params=params)

    def get_staking_leaderboard(self, limit: int = 25) -> Dict:
        """Agents ranked by staking success."""
        return self._get("/protocol/stakes/leaderboard", params={"limit": limit})

    # ── Settlement Netting ──

    def record_netting_obligation(self, from_agent: str, to_agent: str,
                                  amount: float, deal_id: str = "") -> Dict:
        """Record a settlement obligation eligible for netting."""
        return self._post("/protocol/netting/record", {
            "from_agent": from_agent, "to_agent": to_agent,
            "amount_usd": amount, "deal_id": deal_id,
        }, auth=True)

    def run_netting_cycle(self) -> Dict:
        """Execute a netting cycle — compute bilateral nets."""
        return self._post("/protocol/netting/cycle", auth=True)

    def get_netting_positions(self) -> Dict:
        """View current bilateral net positions."""
        return self._get("/protocol/netting/positions", auth=True)

    # ── Marketplace ──

    def discover(self, capability: str = None, sku_id: str = None,
                 min_price: float = 0, max_price: float = 100000,
                 limit: int = 50) -> Dict:
        """Browse OfferNet for available work."""
        params: Dict[str, Any] = {"min_price": min_price, "max_price": max_price, "limit": limit}
        if capability:
            params["capability"] = capability
        if sku_id:
            params["sku_id"] = sku_id
        return self._get("/protocol/discover", params=params, auth=True)

    def commit(self, offer_id: str, bid_price: float,
               estimated_hours: int = 24, message: str = "") -> Dict:
        """Place a bid + lock escrow on an offer."""
        return self._post("/protocol/commit", {
            "offer_id": offer_id, "bid_price": bid_price,
            "estimated_hours": estimated_hours, "message": message,
        }, auth=True)

    def deliver(self, job_id: str, proof_type: str = "completion",
                proof_data: Dict = None, deal_id: str = None) -> Dict:
        """Submit proof bundle for a committed job."""
        return self._post("/protocol/deliver", {
            "job_id": job_id, "proof_type": proof_type,
            "proof_data": proof_data or {}, "deal_id": deal_id,
        }, auth=True)


class AsyncAiGentsyClient:
    """Async Python client for the AiGentsy Settlement Protocol."""

    def __init__(self, base_url: str = "http://localhost:10000", api_key: str = None):
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(base_url=self._base, timeout=30.0)

    def _headers(self, auth: bool = False) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if auth and self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    async def _post(self, path: str, body: dict = None, auth: bool = False) -> dict:
        import asyncio
        headers = self._headers(auth=auth)
        for attempt in range(_MAX_RETRIES + 1):
            resp = await self._client.post(path, json=body or {}, headers=headers)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            wait = float(resp.headers.get("Retry-After", _DEFAULT_RETRY_AFTER * (2 ** attempt)))
            logger.warning("429 on POST %s — retry %d/%d in %.1fs", path, attempt + 1, _MAX_RETRIES, wait)
            if attempt == _MAX_RETRIES:
                resp.raise_for_status()
            await asyncio.sleep(wait)
        return resp.json()

    async def _get(self, path: str, params: dict = None, auth: bool = False) -> dict:
        import asyncio
        headers = self._headers(auth=auth)
        for attempt in range(_MAX_RETRIES + 1):
            resp = await self._client.get(path, params=params, headers=headers)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            wait = float(resp.headers.get("Retry-After", _DEFAULT_RETRY_AFTER * (2 ** attempt)))
            logger.warning("429 on GET %s — retry %d/%d in %.1fs", path, attempt + 1, _MAX_RETRIES, wait)
            if attempt == _MAX_RETRIES:
                resp.raise_for_status()
            await asyncio.sleep(wait)
        return resp.json()

    # ── Registration & Identity ──

    async def register(self, name: str, capabilities: List[str] = None, **kwargs) -> Dict:
        """Register a new agent. Auto-stores the returned API key."""
        data = await self._post("/protocol/register", {
            "name": name, "capabilities": capabilities or [], **kwargs,
        })
        if data.get("api_key"):
            self._api_key = data["api_key"]
        return data

    async def get_reputation(self, agent_id: str) -> Dict:
        """Get OCS score and tier for any agent."""
        return await self._get(f"/protocol/reputation/{agent_id}")

    # ── Proof Creation ──

    async def stamp(self, agent_id: str, description: str = "",
                    attachment_url: str = None) -> Dict:
        """Simplified proof creation — fewest params, fastest path."""
        body: Dict[str, Any] = {
            "agent_id": agent_id,
            "description": description,
        }
        if attachment_url:
            body["attachment_url"] = attachment_url
        return await self._post("/protocol/stamp", body)

    async def create_proof_pack(self, agent_username: str, vertical: str = "marketing",
                                proof_type: str = "creative_preview",
                                scope_summary: str = "", proof_data: Dict = None,
                                **kwargs) -> Dict:
        """Create a ProofPack — full control over the deal lifecycle entry point."""
        return await self._post("/protocol/proof-pack", {
            "agent_username": agent_username, "vertical": vertical,
            "proof_type": proof_type, "scope_summary": scope_summary,
            "proof_data": proof_data or {}, **kwargs,
        })

    # ── Deal Approval ──

    async def auto_go(self, deal_id: str, quote_id: str, buyer_id: str,
                      mandate_id: str = None, seller_agent_id: str = None) -> Dict:
        """Autonomy mode — auto-approve if mandate + reputation + confidence pass."""
        return await self._post("/protocol/auto-go", {
            "deal_id": deal_id, "quote_id": quote_id,
            "buyer_id": buyer_id, "mandate_id": mandate_id,
            "seller_agent_id": seller_agent_id,
        })

    async def go(self, deal_id: str, quote_id: str, scope_lock_hash: str, **kwargs) -> Dict:
        """Lock scope, enforce pricing, create payment link."""
        return await self._post("/protocol/go", {
            "deal_id": deal_id, "quote_id": quote_id,
            "scope_lock_hash": scope_lock_hash, **kwargs,
        })

    # ── Settlement ──

    async def settle(self, deal_id: str, amount: float, actor_id: str,
                     counterparty_id: str, proof_hash: str = None) -> Dict:
        """Settle a deal — triggers fee deduction and payout routing."""
        return await self._post("/protocol/settle", {
            "deal_id": deal_id, "amount": amount,
            "actor_id": actor_id, "counterparty_id": counterparty_id,
            "proof_hash": proof_hash,
        }, auth=True)

    # ── Verification ──

    async def verify_proof(self, deal_id: str, proof_hash: str, proof_type: str,
                           provider: str = None, proof_data: Dict = None) -> Dict:
        """Verify proof via a verification provider."""
        return await self._post("/protocol/verify/provider", {
            "deal_id": deal_id, "proof_hash": proof_hash,
            "proof_type": proof_type, "provider": provider,
            "proof_data": proof_data or {},
        })

    # ── Audit & Proof Bundles ──

    async def get_timeline(self, deal_id: str) -> Dict:
        """Full deal timeline with events + ledger."""
        return await self._get(f"/protocol/deals/{deal_id}/timeline")

    async def get_attribution(self, deal_id: str) -> Dict:
        """Full attribution: events, ledger, referrals, policy snapshot."""
        return await self._get(f"/protocol/deals/{deal_id}/attribution", auth=True)

    async def get_proof_bundle(self, deal_id: str) -> Dict:
        """Full proof bundle for a deal."""
        return await self._get(f"/proof/{deal_id}")

    async def verify_proof_bundle(self, deal_id: str) -> Dict:
        """Cryptographic verification of deal proof bundle."""
        return await self._get(f"/proof/{deal_id}/verify")

    async def get_merkle_root(self) -> Dict:
        """Latest Merkle root for settlement verification."""
        return await self._get("/protocol/merkle/latest")

    # ── Proof Chains ──

    async def get_proof_chain(self, deal_id: str) -> Dict:
        return await self._get(f"/protocol/proof-chain/{deal_id}")

    async def get_proof_lineage(self, deal_id: str) -> Dict:
        return await self._get(f"/protocol/proof-chain/{deal_id}/lineage")

    # ── Multi-Party Settlement ──

    async def settle_multi(self, deal_id: str, total_amount: float,
                           splits: List[Dict], provider: str = "balance",
                           proof_hash: str = None) -> Dict:
        return await self._post("/protocol/settle/multi", {
            "deal_id": deal_id, "total_amount_usd": total_amount,
            "splits": splits, "provider": provider, "proof_hash": proof_hash,
        }, auth=True)

    # ── Webhook Subscriptions ──

    async def create_webhook(self, url: str, events: List[str] = None,
                             secret: str = None) -> Dict:
        body: Dict[str, Any] = {"url": url}
        if events:
            body["events"] = events
        if secret:
            body["secret"] = secret
        return await self._post("/protocol/webhooks", body, auth=True)

    # ── Programmable Mandates ──

    async def create_programmable_mandate(self, buyer_id: str, rules: List[Dict],
                                          default_action: str = "reject",
                                          max_amount: float = 500.0) -> Dict:
        return await self._post("/protocol/mandates/programmable", {
            "buyer_id": buyer_id, "rules": rules,
            "default_action": default_action, "max_amount_per_deal_usd": max_amount,
        }, auth=True)

    async def evaluate_mandate(self, context: Dict, buyer_id: str = None,
                               mandate_id: str = None) -> Dict:
        body: Dict[str, Any] = {"context": context}
        if buyer_id:
            body["buyer_id"] = buyer_id
        if mandate_id:
            body["mandate_id"] = mandate_id
        return await self._post("/protocol/mandates/programmable/evaluate", body, auth=True)

    # ── Reputation Attestations ──

    async def issue_attestation(self, agent_id: str) -> Dict:
        return await self._post(f"/protocol/attestations/issue?agent_id={agent_id}", auth=True)

    async def get_attestation(self, agent_id: str) -> Dict:
        return await self._get(f"/protocol/attestations/{agent_id}")

    async def verify_attestation(self, credential: Dict,
                                 public_key_base64: str = "") -> Dict:
        return await self._post("/protocol/attestations/verify", {
            "credential": credential, "public_key_base64": public_key_base64,
        })

    # ── Credential Marketplace ──

    async def publish_credential(self, deal_id: str,
                                 capability_tags: List[str] = None) -> Dict:
        return await self._post("/protocol/credentials/publish", {
            "deal_id": deal_id, "capability_tags": capability_tags or [],
        }, auth=True)

    async def search_credentials(self, capability: str = "", vertical: str = "",
                                 min_confidence: float = 0, limit: int = 50) -> Dict:
        params: Dict[str, Any] = {"limit": limit}
        if capability:
            params["capability"] = capability
        if vertical:
            params["vertical"] = vertical
        if min_confidence:
            params["min_confidence"] = min_confidence
        return await self._get("/protocol/credentials/search", params=params)

    # ── Volume Fee Tiers ──

    async def get_fee_tiers(self) -> Dict:
        return await self._get("/protocol/fee-tiers")

    async def get_agent_fee_tier(self, agent_id: str) -> Dict:
        return await self._get(f"/protocol/fee-tiers/{agent_id}")

    # ── Reputation Staking ──

    async def create_stake(self, deal_id: str, amount: float,
                           commitment: str = "") -> Dict:
        return await self._post("/protocol/stakes", {
            "deal_id": deal_id, "amount_usd": amount, "commitment": commitment,
        }, auth=True)

    async def resolve_stake(self, stake_id: str, outcome: str) -> Dict:
        return await self._post(f"/protocol/stakes/{stake_id}/resolve", {
            "outcome": outcome,
        }, auth=True)

    # ── Settlement Netting ──

    async def record_netting_obligation(self, from_agent: str, to_agent: str,
                                        amount: float, deal_id: str = "") -> Dict:
        return await self._post("/protocol/netting/record", {
            "from_agent": from_agent, "to_agent": to_agent,
            "amount_usd": amount, "deal_id": deal_id,
        }, auth=True)

    async def run_netting_cycle(self) -> Dict:
        return await self._post("/protocol/netting/cycle", auth=True)

    # ── Marketplace ──

    async def discover(self, capability: str = None, sku_id: str = None,
                       min_price: float = 0, max_price: float = 100000,
                       limit: int = 50) -> Dict:
        """Browse OfferNet for available work."""
        params: Dict[str, Any] = {"min_price": min_price, "max_price": max_price, "limit": limit}
        if capability:
            params["capability"] = capability
        if sku_id:
            params["sku_id"] = sku_id
        return await self._get("/protocol/discover", params=params, auth=True)
