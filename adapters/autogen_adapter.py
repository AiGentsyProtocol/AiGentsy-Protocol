"""
AutoGen Adapter — Use AiGentsy Protocol with Microsoft AutoGen
===============================================================

Provides callable functions for AutoGen's function_map pattern.

Usage:
    from adapters.autogen_adapter import AIGENTSY_FUNCTIONS, aigentsy_stamp, aigentsy_verify

    assistant = AssistantAgent("prover", llm_config={"functions": AIGENTSY_FUNCTIONS})
    user_proxy = UserProxyAgent("user", function_map={
        "aigentsy_stamp": aigentsy_stamp,
        "aigentsy_verify": aigentsy_verify,
        "aigentsy_register": aigentsy_register,
        "aigentsy_export": aigentsy_export,
    })
"""

import json
import os

try:
    from sdk.python.client import AiGentsyClient
except ImportError:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from sdk.python.client import AiGentsyClient

BASE = os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com")


# ── AutoGen function schemas ──

AIGENTSY_FUNCTIONS = [
    {
        "name": "aigentsy_stamp",
        "description": "Create a verifiable proof that AI/agent work was delivered. Returns proof URL, verification URL, and badge URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The agent ID creating the proof"},
                "description": {"type": "string", "description": "Short description of what was delivered"},
            },
            "required": ["agent_id", "description"],
        },
    },
    {
        "name": "aigentsy_verify",
        "description": "Verify the cryptographic integrity of a proof bundle. Returns chain integrity status.",
        "parameters": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "string", "description": "The deal ID to verify"},
            },
            "required": ["deal_id"],
        },
    },
    {
        "name": "aigentsy_register",
        "description": "Register a new AI agent on the AiGentsy settlement protocol. Returns agent_id and api_key.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Name for the agent"},
                "capabilities": {"type": "string", "description": "Comma-separated capabilities"},
            },
            "required": ["agent_name"],
        },
    },
    {
        "name": "aigentsy_export",
        "description": "Export a portable proof bundle for offline verification.",
        "parameters": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "string", "description": "The deal ID to export"},
            },
            "required": ["deal_id"],
        },
    },
]


# ── Callable functions (for function_map) ──

def aigentsy_stamp(agent_id: str, description: str = "") -> str:
    client = AiGentsyClient(BASE)
    result = client._post("/protocol/stamp", {
        "agent_id": agent_id,
        "description": description,
    })
    return json.dumps(result)


def aigentsy_verify(deal_id: str) -> str:
    client = AiGentsyClient(BASE)
    result = client._get(f"/proof/{deal_id}/verify")
    return json.dumps(result)


def aigentsy_register(agent_name: str, capabilities: str = "marketing") -> str:
    client = AiGentsyClient(BASE)
    caps = [c.strip() for c in capabilities.split(",")]
    result = client.register(agent_name, capabilities=caps)
    return json.dumps({"agent_id": result.get("agent_id"), "api_key": result.get("api_key")})


def aigentsy_export(deal_id: str) -> str:
    client = AiGentsyClient(BASE)
    result = client._get(f"/protocol/proofs/{deal_id}/export")
    return json.dumps(result)
