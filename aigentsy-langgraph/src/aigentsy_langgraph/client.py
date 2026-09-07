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

    # ── 0.3.0 additions ────────────────────────────────────────────
    #
    # All methods below are additive — the 0.2.0 surface is byte-
    # unchanged. They wrap existing live endpoints with no new backend
    # behavior. The signed-event helper (signing.send_signed_event)
    # uses ``_post_signed`` to drive the prepare/sign/submit flow.

    async def get_acceptance_by_deal(self, deal_id: str) -> Dict:
        """GET /protocol/acceptance/deal/{deal_id} — returns the
        current acceptance record for a deal, or ``acceptance: None``
        if none exists yet. Read-only."""
        resp = await self._client.get(
            f"/protocol/acceptance/deal/{deal_id}",
        )
        return resp.json()

    async def submit_for_acceptance(
        self,
        deal_id: str,
        downstream_action: str = "settle",
    ) -> Dict:
        """POST /protocol/acceptance/submit — creates the acceptance
        record for a deal. Requires X-API-Key for the submitter.
        Raises httpx.HTTPStatusError on 4xx/5xx so the node layer can
        surface a structured backend_error envelope (per the G2
        contract: failures NEVER swallowed into ok=true)."""
        resp = await self._client.post(
            "/protocol/acceptance/submit",
            json={
                "deal_id": deal_id,
                "downstream_action": downstream_action,
            },
            headers=self._headers(auth=True),
        )
        resp.raise_for_status()
        return resp.json()

    async def accept_output(
        self,
        acceptance_id: str,
        reason: str = "",
        checks_passed: List[str] = None,
        checks_failed: List[str] = None,
    ) -> Dict:
        """POST /protocol/acceptance/{id}/accept — attribution-only
        accept. The reviewer's api_key auths the call; the appended
        ACCEPTED event's actor_id is the reviewer.
        """
        resp = await self._client.post(
            f"/protocol/acceptance/{acceptance_id}/accept",
            json={
                "decision": "accept",
                "reason": reason,
                "checks_passed": list(checks_passed or []),
                "checks_failed": list(checks_failed or []),
            },
            headers=self._headers(auth=True),
        )
        resp.raise_for_status()
        return resp.json()

    async def reject_output(
        self,
        acceptance_id: str,
        reason: str = "",
        checks_passed: List[str] = None,
        checks_failed: List[str] = None,
    ) -> Dict:
        """POST /protocol/acceptance/{id}/reject — attribution-only
        reject. ``reason`` is REQUIRED at the node layer (validated
        upstream in reject_node)."""
        resp = await self._client.post(
            f"/protocol/acceptance/{acceptance_id}/reject",
            json={
                "decision": "reject",
                "reason": reason,
                "checks_passed": list(checks_passed or []),
                "checks_failed": list(checks_failed or []),
            },
            headers=self._headers(auth=True),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_outcome_receipt(self, deal_id: str) -> "httpx.Response":
        """GET /protocol/deals/{deal_id}/outcome-receipt — returns the
        raw httpx.Response so the node can route on status code:

          200 → signed receipt envelope
          409 → outcome_not_recorded (clean empty state)
          404 → deal_not_found
          422/500 → error envelope

        Read-only, public endpoint (the receipt is portably signed)."""
        return await self._client.get(
            f"/protocol/deals/{deal_id}/outcome-receipt",
        )

    async def get_signing_capability(self, actor_id: str) -> Dict:
        """GET /actor/{actor_id}/signing-capability — read-only.

        Used by the acceptance nodes to decide whether to attempt the
        signed path. If the actor has no enrolled key, the node falls
        through to the attribution-only legacy endpoint — Branch 1 of
        the Option-3 contract."""
        resp = await self._client.get(
            f"/actor/{actor_id}/signing-capability",
        )
        return resp.json()

    async def enroll_signing_key(
        self,
        actor_id: str,
        public_key_base64: str,
        actor_type: str = "agent",
        key_class: str = "production",
        metadata: Dict = None,
    ) -> Dict:
        """POST /actor/enroll-key — enroll the PUBLIC half of a
        keypair. The body is screened by ``_assert_no_private_material``
        in the calling node, mirroring the server-side
        FORBIDDEN_PRIVATE_KEY_FIELDS guard.

        Auth: for ``actor_type='agent'``, the client's stored api_key
        must authenticate as ``actor_id`` (the agent enrolling its
        own key)."""
        from .keypair import _assert_no_private_material
        body = {
            "actor_id": actor_id,
            "actor_type": actor_type,
            "public_key_base64": public_key_base64,
            "key_class": key_class,
        }
        if metadata:
            body["metadata"] = metadata
        _assert_no_private_material(body, "enrollment body")
        resp = await self._client.post(
            "/actor/enroll-key",
            json=body,
            headers=self._headers(auth=True),
        )
        resp.raise_for_status()
        return resp.json()

    async def _post_signed(self, path: str, body: Dict) -> Dict:
        """Internal helper used by signing.send_signed_event for the
        prepare + submit calls. Raises HTTPStatusError on non-2xx so
        the signed branch can surface Option-3 blocks as structured
        errors (no swallowed fake success)."""
        resp = await self._client.post(
            path,
            json=body,
            headers=self._headers(auth=True),
        )
        resp.raise_for_status()
        return resp.json()
