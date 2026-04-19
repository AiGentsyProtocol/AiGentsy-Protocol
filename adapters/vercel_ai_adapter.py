"""
Vercel AI SDK Adapter — AiGentsy Proof Tools for Vercel AI SDK
================================================================

Provides tool definitions and handlers compatible with Vercel AI SDK's
server-side tool pattern (used with ai/rsc, ai/core, and Next.js routes).

Since Vercel AI SDK is TypeScript-first, this adapter provides:
1. JSON tool schemas (same format as OpenAI function calling)
2. A Python handler for server-side tool execution
3. Documentation for the TypeScript tool() definition pattern

Usage (Python server-side):
    from adapters.vercel_ai_adapter import AiGentsyVercelAI

    adapter = AiGentsyVercelAI()
    result = adapter.handle("aigentsy_stamp", {"agent_id": "...", "description": "..."})

Usage (TypeScript — copy into your Next.js route):
    import { tool } from 'ai';
    import { z } from 'zod';

    const stamptool = tool({
      description: 'Create verifiable proof of delivered AI work',
      parameters: z.object({
        agent_id: z.string().describe('Agent ID creating the proof'),
        description: z.string().describe('What was delivered'),
      }),
      execute: async ({ agent_id, description }) => {
        const res = await fetch('https://aigentsy-ame-runtime.onrender.com/protocol/stamp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ agent_id, description }),
        });
        return res.json();
      },
    });
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


# ── Tool definitions (OpenAI-compatible, works with Vercel AI SDK) ──

VERCEL_AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "aigentsy_stamp",
            "description": "Create verifiable proof of delivered AI work",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID creating the proof"},
                    "description": {"type": "string", "description": "What was delivered"},
                },
                "required": ["agent_id", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aigentsy_verify",
            "description": "Verify proof bundle cryptographic integrity",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "Deal ID to verify"},
                },
                "required": ["deal_id"],
            },
        },
    },
]


class AiGentsyVercelAI:
    """Server-side handler for Vercel AI SDK tool calls."""

    def __init__(self, base_url=None, api_key=None):
        self.client = AiGentsyClient(
            base_url=base_url or BASE,
            api_key=api_key or os.getenv("AME_API_KEY"),
        )

    @property
    def tools(self):
        return VERCEL_AI_TOOLS

    def handle(self, tool_name: str, args: dict) -> str:
        try:
            if tool_name == "aigentsy_stamp":
                result = self.client._post("/protocol/stamp", {
                    "agent_id": args["agent_id"],
                    "description": args.get("description", ""),
                })
                return json.dumps(result)
            elif tool_name == "aigentsy_verify":
                result = self.client._get(f"/proof/{args['deal_id']}/verify")
                return json.dumps(result)
            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as e:
            return json.dumps({"error": str(e)})
