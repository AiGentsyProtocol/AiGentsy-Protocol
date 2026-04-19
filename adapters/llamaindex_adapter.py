"""
LlamaIndex Adapter — AiGentsy Proof Tools for LlamaIndex
==========================================================

Provides FunctionTool instances for LlamaIndex agents and query engines.

Usage:
    from adapters.llamaindex_adapter import get_aigentsy_tools

    tools = get_aigentsy_tools()
    agent = ReActAgent.from_tools(tools, llm=llm)
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

try:
    from llama_index.core.tools import FunctionTool
except ImportError:
    # Stub for environments without LlamaIndex
    class FunctionTool:
        @classmethod
        def from_defaults(cls, fn=None, name="", description=""):
            return cls()


def aigentsy_stamp(agent_id: str, description: str = "") -> str:
    """Create a verifiable proof that AI/agent work was delivered. Returns proof URL, verification URL, and badge URL."""
    client = AiGentsyClient(BASE)
    result = client._post("/protocol/stamp", {
        "agent_id": agent_id,
        "description": description,
    })
    return json.dumps(result)


def aigentsy_verify(deal_id: str) -> str:
    """Verify the cryptographic integrity of a proof bundle. Returns chain integrity status and hash."""
    client = AiGentsyClient(BASE)
    result = client._get(f"/proof/{deal_id}/verify")
    return json.dumps(result)


def aigentsy_register(agent_name: str, capabilities: str = "marketing") -> str:
    """Register a new AI agent on the AiGentsy settlement protocol. Returns agent_id and api_key."""
    client = AiGentsyClient(BASE)
    caps = [c.strip() for c in capabilities.split(",")]
    result = client.register(agent_name, capabilities=caps)
    return json.dumps({"agent_id": result.get("agent_id"), "api_key": result.get("api_key")})


def aigentsy_export(deal_id: str) -> str:
    """Export a portable proof bundle for offline verification."""
    client = AiGentsyClient(BASE)
    result = client._get(f"/protocol/proofs/{deal_id}/export")
    return json.dumps(result)


def get_aigentsy_tools():
    """Return a list of LlamaIndex FunctionTools for AiGentsy proof operations."""
    return [
        FunctionTool.from_defaults(
            fn=aigentsy_stamp,
            name="aigentsy_stamp",
            description="Create verifiable proof of delivered AI work",
        ),
        FunctionTool.from_defaults(
            fn=aigentsy_verify,
            name="aigentsy_verify",
            description="Verify proof bundle cryptographic integrity",
        ),
        FunctionTool.from_defaults(
            fn=aigentsy_register,
            name="aigentsy_register",
            description="Register an AI agent on the settlement protocol",
        ),
        FunctionTool.from_defaults(
            fn=aigentsy_export,
            name="aigentsy_export",
            description="Export portable proof bundle for offline verification",
        ),
    ]
