"""LangGraph nodes wrapping AiGentsy Settlement Protocol operations."""

import os
from typing import Any, Dict
from .client import AsyncAiGentsyClient


def _get_client(state: Dict[str, Any]) -> AsyncAiGentsyClient:
    return AsyncAiGentsyClient(
        base_url=state.get("base_url", os.getenv(
            "AME_BASE", "https://aigentsy-ame-runtime.onrender.com")),
        api_key=state.get("api_key"),
    )


async def register_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Register an agent."""
    client = _get_client(state)
    result = await client.register(
        name=state.get("agent_name", "langgraph_agent"),
        capabilities=state.get("capabilities", ["marketing"]),
    )
    return {
        **state,
        "agent_id": result["agent_id"],
        "api_key": result["api_key"],
        "ocs": result.get("ocs"),
        "tier": result.get("tier"),
    }


async def proof_pack_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Create proof pack. Supports parent_proof_ids for proof chain linking."""
    client = _get_client(state)
    kwargs = {}
    if state.get("parent_proof_ids"):
        kwargs["parent_proof_ids"] = state["parent_proof_ids"]
    result = await client.create_proof_pack(
        agent_username=state["agent_username"],
        vertical=state.get("vertical", "marketing"),
        proof_type=state.get("proof_type", "creative_preview"),
        scope_summary=state.get("scope_summary", ""),
        proof_data=state.get("proof_data", {}),
        **kwargs,
    )
    return {
        **state,
        "deal_id": result["deal_id"],
        "quote_id": result["quote_id"],
        "scope_lock_hash": result["scope_lock_hash"],
        "proof_hash": result.get("proof_hash"),
        "estimated_price": result.get("estimated_price"),
        "parent_proof_ids": result.get("parent_proof_ids", []),
    }


async def auto_go_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-GO decision."""
    client = _get_client(state)
    result = await client.auto_go(
        deal_id=state["deal_id"],
        quote_id=state["quote_id"],
        buyer_id=state.get("buyer_id", ""),
        mandate_id=state.get("mandate_id"),
        seller_agent_id=state.get("agent_id"),
    )
    decision = result.get("decision", result.get("status", "unknown"))
    return {
        **state,
        "auto_go_decision": decision,
        "auto_go_approved": decision in ("go_approved", "AUTO_GO_APPROVED"),
    }


async def go_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Approve deal (GO)."""
    client = _get_client(state)
    result = await client.go(
        deal_id=state["deal_id"],
        quote_id=state["quote_id"],
        scope_lock_hash=state["scope_lock_hash"],
    )
    return {
        **state,
        "go_approved": result.get("ok", False),
        "payment_url": result.get("payment_url"),
        "amount": result.get("amount"),
        "go_key": result.get("go_key"),
    }


async def verify_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Verify proof via provider."""
    client = _get_client(state)
    result = await client.verify_proof(
        deal_id=state["deal_id"],
        proof_hash=state.get("proof_hash", ""),
        proof_type=state.get("proof_type", "test_results"),
        proof_data=state.get("verification_data", state.get("proof_data", {})),
    )
    verification = result.get("verification", {})
    return {
        **state,
        "verified": verification.get("verified", False),
        "verification_confidence": verification.get("confidence"),
        "verification_hash": verification.get("verification_hash"),
        "verification_provider": result.get("provider_used"),
    }


async def settle_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Settle deal."""
    client = _get_client(state)
    result = await client.settle(
        deal_id=state["deal_id"],
        amount=state["amount"],
        actor_id=state.get("actor_id", state.get("agent_id", "")),
        counterparty_id=state.get("counterparty_id", state.get("buyer_id", "")),
        proof_hash=state.get("proof_hash"),
    )
    return {**state, "settlement": result}


async def timeline_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch deal timeline."""
    client = _get_client(state)
    result = await client.get_timeline(state["deal_id"])
    return {**state, "timeline": result}


async def full_deal_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Full Proof -> GO -> Verify loop."""
    state = await proof_pack_node(state)
    state = await go_node(state)
    if state.get("go_approved"):
        state = await verify_node(state)
    state = await timeline_node(state)
    return state


async def settle_multi_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Multi-party settlement with N-way splits."""
    client = _get_client(state)
    result = await client.settle_multi(
        deal_id=state["deal_id"],
        total_amount=state["total_amount"],
        splits=state["splits"],
        provider=state.get("provider", "balance"),
        proof_hash=state.get("proof_hash"),
    )
    return {**state, "multiparty_settlement": result}


async def attestation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Issue a signed reputation attestation (W3C VC)."""
    client = _get_client(state)
    agent_id = state.get("agent_id", "")
    result = await client.issue_attestation(agent_id)
    return {
        **state,
        "attestation": result.get("credential"),
        "attestation_ok": result.get("ok", False),
    }


async def proof_chain_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Query proof chain provenance for a deal."""
    client = _get_client(state)
    result = await client.get_proof_chain(state["deal_id"])
    return {
        **state,
        "proof_chain": result.get("chain"),
        "proof_chain_parents": result.get("parents", []),
        "proof_chain_children": result.get("children", []),
    }
