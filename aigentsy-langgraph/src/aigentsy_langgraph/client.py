"""Async client for the AiGentsy A2A Settlement Protocol."""

import httpx
from typing import Any, Dict, List


class AsyncAiGentsyClient:
    """Async Python client for the A2A Settlement Protocol (for LangGraph nodes)."""

    def __init__(self, base_url: str = "https://aigentsy-ame-runtime.onrender.com",
                 api_key: str = None):
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(base_url=self._base, timeout=30.0)

    def _headers(self, auth: bool = False) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if auth and self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    async def register(self, name: str, capabilities: List[str] = None, **kwargs) -> Dict:
        resp = await self._client.post("/protocol/register", json={
            "name": name, "capabilities": capabilities or [], **kwargs,
        }, headers=self._headers())
        data = resp.json()
        if data.get("api_key"):
            self._api_key = data["api_key"]
        return data

    async def create_proof_pack(self, agent_username: str, vertical: str = "marketing",
                                proof_type: str = "creative_preview",
                                scope_summary: str = "", proof_data: Dict = None,
                                **kwargs) -> Dict:
        resp = await self._client.post("/protocol/proof-pack", json={
            "agent_username": agent_username, "vertical": vertical,
            "proof_type": proof_type, "scope_summary": scope_summary,
            "proof_data": proof_data or {}, **kwargs,
        }, headers=self._headers())
        return resp.json()

    async def auto_go(self, deal_id: str, quote_id: str, buyer_id: str,
                      mandate_id: str = None, seller_agent_id: str = None) -> Dict:
        resp = await self._client.post("/protocol/auto-go", json={
            "deal_id": deal_id, "quote_id": quote_id,
            "buyer_id": buyer_id, "mandate_id": mandate_id,
            "seller_agent_id": seller_agent_id,
        }, headers=self._headers())
        return resp.json()

    async def go(self, deal_id: str, quote_id: str, scope_lock_hash: str, **kwargs) -> Dict:
        resp = await self._client.post("/protocol/go", json={
            "deal_id": deal_id, "quote_id": quote_id,
            "scope_lock_hash": scope_lock_hash, **kwargs,
        }, headers=self._headers())
        return resp.json()

    async def settle(self, deal_id: str, amount: float, actor_id: str,
                     counterparty_id: str, proof_hash: str = None) -> Dict:
        resp = await self._client.post("/protocol/settle", json={
            "deal_id": deal_id, "amount": amount,
            "actor_id": actor_id, "counterparty_id": counterparty_id,
            "proof_hash": proof_hash,
        }, headers=self._headers(auth=True))
        return resp.json()

    async def verify_proof(self, deal_id: str, proof_hash: str, proof_type: str,
                           provider: str = None, proof_data: Dict = None) -> Dict:
        resp = await self._client.post("/protocol/verify/provider", json={
            "deal_id": deal_id, "proof_hash": proof_hash,
            "proof_type": proof_type, "provider": provider,
            "proof_data": proof_data or {},
        }, headers=self._headers())
        return resp.json()

    async def get_timeline(self, deal_id: str) -> Dict:
        resp = await self._client.get(f"/protocol/deals/{deal_id}/timeline")
        return resp.json()

    async def get_attribution(self, deal_id: str) -> Dict:
        resp = await self._client.get(f"/protocol/deals/{deal_id}/attribution",
                                       headers=self._headers(auth=True))
        return resp.json()

    async def get_proof_bundle(self, deal_id: str) -> Dict:
        resp = await self._client.get(f"/proof/{deal_id}")
        return resp.json()

    async def get_reputation(self, agent_id: str) -> Dict:
        resp = await self._client.get(f"/protocol/reputation/{agent_id}")
        return resp.json()

    async def settle_multi(self, deal_id: str, total_amount: float,
                           splits: List[Dict], provider: str = "balance",
                           proof_hash: str = None) -> Dict:
        resp = await self._client.post("/protocol/settle/multi", json={
            "deal_id": deal_id, "total_amount_usd": total_amount,
            "splits": splits, "provider": provider, "proof_hash": proof_hash,
        }, headers=self._headers(auth=True))
        return resp.json()

    async def issue_attestation(self, agent_id: str) -> Dict:
        resp = await self._client.post(
            f"/protocol/attestations/issue?agent_id={agent_id}",
            headers=self._headers(auth=True),
        )
        return resp.json()

    async def get_proof_chain(self, deal_id: str) -> Dict:
        resp = await self._client.get(f"/protocol/proof-chain/{deal_id}")
        return resp.json()
