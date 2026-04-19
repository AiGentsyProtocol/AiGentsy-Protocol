"""
AiGentsy Protocol Python SDK
==============================

Full-loop client for the A2A Settlement Protocol.
Covers the entire deal lifecycle: register → mandate → proof-pack → go → verify → settle.

Usage:
    from sdk.python.client import AiGentsyClient

    client = AiGentsyClient("http://localhost:10000")
    result = client.register("my_agent", capabilities=["marketing"])
    api_key = result["api_key"]

    proof = client.create_proof_pack(
        agent_username="seller",
        vertical="marketing",
        proof_type="creative_preview",
        scope_summary="Social media package",
        proof_data={"preview_url": "https://example.com"},
    )

    go = client.go(
        deal_id=proof["deal_id"],
        quote_id=proof["quote_id"],
        scope_lock_hash=proof["scope_lock_hash"],
    )
"""

import time
import logging
import httpx
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aigentsy.sdk")

_MAX_RETRIES = 3
_DEFAULT_RETRY_AFTER = 2


class AiGentsyClient:
    """Synchronous Python client for the A2A Settlement Protocol."""

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
        return resp.json()  # unreachable but satisfies type checker

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

    # ── Proof → Go → Pay Loop ──

    def create_proof_pack(self, agent_username: str, vertical: str = "marketing",
                          proof_type: str = "creative_preview",
                          scope_summary: str = "", proof_data: Dict = None,
                          attachment_url: str = None, sku_id: str = None,
                          **kwargs) -> Dict:
        """Create a ProofPack — entry point for the deal lifecycle."""
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
        params = {"amount": amount}
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

    # ── Audit & Verification ──

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

    # ── Marketplace ──

    def discover(self, capability: str = None, sku_id: str = None,
                 min_price: float = 0, max_price: float = 100000,
                 limit: int = 50) -> Dict:
        """Browse OfferNet for available work."""
        params = {"min_price": min_price, "max_price": max_price, "limit": limit}
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
    """Async Python client for the A2A Settlement Protocol (for LangGraph nodes)."""

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

    async def register(self, name: str, capabilities: List[str] = None, **kwargs) -> Dict:
        data = await self._post("/protocol/register", {
            "name": name, "capabilities": capabilities or [], **kwargs,
        })
        if data.get("api_key"):
            self._api_key = data["api_key"]
        return data

    async def create_proof_pack(self, agent_username: str, vertical: str = "marketing",
                                proof_type: str = "creative_preview",
                                scope_summary: str = "", proof_data: Dict = None,
                                **kwargs) -> Dict:
        return await self._post("/protocol/proof-pack", {
            "agent_username": agent_username, "vertical": vertical,
            "proof_type": proof_type, "scope_summary": scope_summary,
            "proof_data": proof_data or {}, **kwargs,
        })

    async def auto_go(self, deal_id: str, quote_id: str, buyer_id: str,
                      mandate_id: str = None, seller_agent_id: str = None) -> Dict:
        return await self._post("/protocol/auto-go", {
            "deal_id": deal_id, "quote_id": quote_id,
            "buyer_id": buyer_id, "mandate_id": mandate_id,
            "seller_agent_id": seller_agent_id,
        })

    async def go(self, deal_id: str, quote_id: str, scope_lock_hash: str, **kwargs) -> Dict:
        return await self._post("/protocol/go", {
            "deal_id": deal_id, "quote_id": quote_id,
            "scope_lock_hash": scope_lock_hash, **kwargs,
        })

    async def settle(self, deal_id: str, amount: float, actor_id: str,
                     counterparty_id: str, proof_hash: str = None) -> Dict:
        return await self._post("/protocol/settle", {
            "deal_id": deal_id, "amount": amount,
            "actor_id": actor_id, "counterparty_id": counterparty_id,
            "proof_hash": proof_hash,
        }, auth=True)

    async def verify_proof(self, deal_id: str, proof_hash: str, proof_type: str,
                           provider: str = None, proof_data: Dict = None) -> Dict:
        return await self._post("/protocol/verify/provider", {
            "deal_id": deal_id, "proof_hash": proof_hash,
            "proof_type": proof_type, "provider": provider,
            "proof_data": proof_data or {},
        })

    async def get_timeline(self, deal_id: str) -> Dict:
        return await self._get(f"/protocol/deals/{deal_id}/timeline")

    async def get_attribution(self, deal_id: str) -> Dict:
        return await self._get(f"/protocol/deals/{deal_id}/attribution", auth=True)

    async def get_proof_bundle(self, deal_id: str) -> Dict:
        return await self._get(f"/proof/{deal_id}")

    async def get_reputation(self, agent_id: str) -> Dict:
        return await self._get(f"/protocol/reputation/{agent_id}")
