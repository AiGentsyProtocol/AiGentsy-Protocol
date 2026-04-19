"""
LangGraph Adapter — Use AiGentsy Protocol as LangGraph Nodes
==============================================================

Wraps protocol operations as async graph nodes. Each node takes a state dict,
calls the protocol, and returns an updated state dict.

Usage:
    from adapters.langgraph_adapter import proof_pack_node, go_node, settle_node, verify_node

    # In a LangGraph StateGraph:
    graph = StateGraph(DealState)
    graph.add_node("create_proof", proof_pack_node)
    graph.add_node("approve", go_node)
    graph.add_node("verify", verify_node)
    graph.add_node("settle", settle_node)
    graph.add_edge("create_proof", "approve")
    graph.add_edge("approve", "verify")
    graph.add_edge("verify", "settle")

Required state fields per node:
    proof_pack_node: agent_username, vertical (optional), proof_type (optional),
                     scope_summary (optional), proof_data (optional)
    auto_go_node:    deal_id, quote_id, buyer_id, mandate_id (optional)
    go_node:         deal_id, quote_id, scope_lock_hash
    verify_node:     deal_id, proof_hash, proof_type (optional)
    settle_node:     deal_id, amount, actor_id, counterparty_id, api_key
"""

import os
from typing import Any, Dict
from sdk.python.client import AsyncAiGentsyClient


def _get_client(state: Dict[str, Any]) -> AsyncAiGentsyClient:
    return AsyncAiGentsyClient(
        base_url=state.get("base_url", os.getenv("AME_BASE", "http://localhost:10000")),
        api_key=state.get("api_key"),
    )


async def register_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node: Register an agent."""
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
    """LangGraph node: Create proof pack."""
    client = _get_client(state)
    result = await client.create_proof_pack(
        agent_username=state["agent_username"],
        vertical=state.get("vertical", "marketing"),
        proof_type=state.get("proof_type", "creative_preview"),
        scope_summary=state.get("scope_summary", ""),
        proof_data=state.get("proof_data", {}),
    )
    return {
        **state,
        "deal_id": result["deal_id"],
        "quote_id": result["quote_id"],
        "scope_lock_hash": result["scope_lock_hash"],
        "proof_hash": result.get("proof_hash"),
        "estimated_price": result.get("estimated_price"),
    }


async def auto_go_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node: Auto-GO decision."""
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
    """LangGraph node: Approve deal (GO)."""
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
    """LangGraph node: Verify proof via provider."""
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
    """LangGraph node: Settle deal."""
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
    """LangGraph node: Fetch deal timeline."""
    client = _get_client(state)
    result = await client.get_timeline(state["deal_id"])
    return {**state, "timeline": result}


# ── Convenience: Full-loop node ──

async def full_deal_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience node that runs the full Proof → GO → Verify loop.

    Expects: agent_username, proof_data, proof_type (optional)
    Returns: deal_id, go_approved, verified, amount, timeline
    """
    state = await proof_pack_node(state)
    state = await go_node(state)
    if state.get("go_approved"):
        state = await verify_node(state)
    state = await timeline_node(state)
    return state
