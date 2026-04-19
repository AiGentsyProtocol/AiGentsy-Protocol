"""
OpenAI Agents / Function-Calling Adapter for AiGentsy
=====================================================

Provides tool schemas and a dispatcher for OpenAI's function-calling
format (Responses API, Assistants API, Chat Completions with tools).

Proof-first: stamp → verify → register → settle.

Usage with OpenAI Responses API:
    from adapters.openai_adapter import AiGentsyOpenAI

    adapter = AiGentsyOpenAI()

    # Pass adapter.tools to OpenAI
    response = client.responses.create(
        model="gpt-4o",
        tools=adapter.tools,
        input="Stamp this deliverable: logo design completed",
    )

    # Handle tool calls
    for call in response.output:
        if call.type == "function_call":
            result = adapter.handle(call.name, json.loads(call.arguments))
"""

import json
import os

try:
    from sdk.python.client import AiGentsyClient
except ImportError:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from sdk.python.client import AiGentsyClient


# ═══════════════════════════════════════════════════════════════════════════
# Tool Definitions (OpenAI function-calling schema)
# ═══════════════════════════════════════════════════════════════════════════

AIGENTSY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "aigentsy_stamp",
            "description": "Create a verifiable proof that AI/agent work was delivered. Returns proof URL, verification URL, and badge URL. This is the simplest way to prove a handoff.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The agent ID creating the proof",
                    },
                    "description": {
                        "type": "string",
                        "description": "Short description of what was delivered",
                    },
                    "attachment_url": {
                        "type": "string",
                        "description": "Optional URL to a preview asset",
                    },
                },
                "required": ["agent_id", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aigentsy_verify",
            "description": "Verify the cryptographic integrity of a proof bundle. Returns chain integrity status, hash verification, and Merkle inclusion data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {
                        "type": "string",
                        "description": "The deal ID to verify",
                    },
                },
                "required": ["deal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aigentsy_register",
            "description": "Register a new AI agent on the AiGentsy settlement protocol. Returns agent_id and api_key.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name for the agent",
                    },
                    "capabilities": {
                        "type": "string",
                        "description": "Comma-separated capabilities (e.g. 'marketing,design')",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aigentsy_export",
            "description": "Export a portable proof bundle for offline verification. Returns the full cryptographic proof bundle with Merkle inclusion data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {
                        "type": "string",
                        "description": "The deal ID to export",
                    },
                },
                "required": ["deal_id"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# Adapter Class
# ═══════════════════════════════════════════════════════════════════════════

class AiGentsyOpenAI:
    """OpenAI function-calling adapter for AiGentsy proof/settlement."""

    def __init__(self, base_url=None, api_key=None):
        self.client = AiGentsyClient(
            base_url=base_url or os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com"),
            api_key=api_key or os.getenv("AME_API_KEY"),
        )

    @property
    def tools(self):
        """Tool definitions for OpenAI's tools parameter."""
        return AIGENTSY_TOOLS

    def handle(self, tool_name: str, args: dict) -> str:
        """
        Dispatch a tool call and return JSON result string.

        Args:
            tool_name: Function name from OpenAI tool_call
            args: Parsed arguments dict

        Returns:
            JSON string result for the tool response
        """
        handlers = {
            "aigentsy_stamp": self._stamp,
            "aigentsy_verify": self._verify,
            "aigentsy_register": self._register,
            "aigentsy_export": self._export,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            return handler(args)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _stamp(self, args: dict) -> str:
        result = self.client._post("/protocol/stamp", {
            "agent_id": args["agent_id"],
            "description": args.get("description", ""),
            "attachment_url": args.get("attachment_url"),
        })
        return json.dumps(result)

    def _verify(self, args: dict) -> str:
        result = self.client._get(f"/proof/{args['deal_id']}/verify")
        return json.dumps(result)

    def _register(self, args: dict) -> str:
        caps = args.get("capabilities", "marketing").split(",")
        result = self.client.register(args["agent_name"], capabilities=[c.strip() for c in caps])
        return json.dumps({"agent_id": result.get("agent_id"), "api_key": result.get("api_key")})

    def _export(self, args: dict) -> str:
        result = self.client._get(f"/protocol/proofs/{args['deal_id']}/export")
        return json.dumps(result)
