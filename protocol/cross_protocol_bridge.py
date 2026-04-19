"""
Cross-Protocol Settlement Bridge — Adapter Interfaces (PREP ONLY)
===================================================================

Thin adapter interfaces for bridging external agent protocols into
AiGentsy's settlement layer. Each adapter maps the external protocol's
task/tool completion events to AiGentsy proof→go→settle flow.

Status: PREP ONLY — interfaces defined, no external API calls.

Supported protocols (planned):
    - Google A2A: Task completion → proof pack → settle
    - MCP (Model Context Protocol): Tool call metering → proof → settle
    - LangGraph: Already shipped via aigentsy-langgraph package
    - CrewAI/AutoGen: Agent task completion → proof → settle

Usage (future):
    from protocol.cross_protocol_bridge import get_bridge

    bridge = get_bridge("a2a")
    result = await bridge.on_task_complete(task_id="...", output={...})
    # → creates proof pack + settlement record

Endpoints:
    GET /protocol/bridges             — List available bridge adapters
    GET /protocol/bridges/{protocol}  — Get bridge adapter details + status
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProtocolBridge(ABC):
    """
    Abstract adapter for bridging external agent protocols into AiGentsy settlement.

    Each bridge maps:
        External task/tool completion → AiGentsy proof pack
        External payment trigger → AiGentsy GO
        External confirmation → AiGentsy settle
    """

    name: str = "base"
    protocol_version: str = ""
    status: str = "planned"  # planned | prep | active
    description: str = ""

    @abstractmethod
    async def on_task_complete(self, task_id: str, output: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Handle task completion from external protocol. Returns proof pack result."""
        ...

    @abstractmethod
    async def on_payment_trigger(self, task_id: str, amount: float, **kwargs) -> Dict[str, Any]:
        """Handle payment/approval trigger. Returns GO result."""
        ...

    @abstractmethod
    def map_to_proof_data(self, external_event: Dict[str, Any]) -> Dict[str, Any]:
        """Map external event format to AiGentsy proof_data schema."""
        ...

    def info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "protocol_version": self.protocol_version,
            "status": self.status,
            "description": self.description,
        }


class A2ABridge(ProtocolBridge):
    """
    Google A2A (Agent-to-Agent) Protocol Bridge — ACTIVE.

    Maps A2A TaskStatusUpdateEvent → AiGentsy proof pack.
    A2A uses JSON-RPC 2.0 with tasks/send and tasks/get.

    Ref: https://google.github.io/A2A/
    """

    name = "a2a"
    protocol_version = "0.2.1"
    status = "active"
    description = (
        "Google A2A bridge: maps A2A task completions to AiGentsy proof packs. "
        "Send task completion data and receive a deal_id with proof hash for settlement."
    )

    async def on_task_complete(self, task_id: str, output: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Create a real proof pack from A2A task completion data."""
        agent_id = kwargs.get("agent_id", "a2a_agent")

        proof_data = self.map_to_proof_data(output)

        try:
            import httpx
            import os
            base = os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com")
            async with httpx.AsyncClient(base_url=base, timeout=30.0) as client:
                resp = await client.post("/protocol/proof-pack", json={
                    "agent_username": agent_id,
                    "vertical": "a2a_task",
                    "proof_type": "completion_photo",
                    "scope_summary": f"A2A task: {task_id}",
                    "proof_data": proof_data,
                })
                result = resp.json()
                return {
                    "ok": result.get("ok", False),
                    "status": "active",
                    "deal_id": result.get("deal_id"),
                    "proof_hash": result.get("proof_hash"),
                    "a2a_task_id": task_id,
                    "artifacts": proof_data.get("artifacts", []),
                }
        except Exception as e:
            return {"ok": False, "status": "active", "error": str(e)}

    async def on_payment_trigger(self, task_id: str, amount: float, **kwargs) -> Dict[str, Any]:
        return {
            "ok": True,
            "status": "active",
            "message": "Use POST /protocol/settle with the deal_id from on_task_complete.",
            "task_id": task_id,
            "amount": amount,
        }

    def map_to_proof_data(self, external_event: Dict[str, Any]) -> Dict[str, Any]:
        """Map A2A TaskStatusUpdateEvent to AiGentsy proof_data."""
        return {
            "source_protocol": "a2a",
            "a2a_task_id": external_event.get("id"),
            "a2a_status": external_event.get("status", {}).get("state"),
            "artifacts": [
                {
                    "name": a.get("name"),
                    "type": a.get("parts", [{}])[0].get("type") if a.get("parts") else None,
                }
                for a in external_event.get("artifacts", [])
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class MCPBridge(ProtocolBridge):
    """
    Model Context Protocol (MCP) Bridge — ACTIVE.

    Maps MCP tool call completions to AiGentsy proof packs.
    Meters tool calls (call count, tokens, latency) for settlement.

    Ref: https://modelcontextprotocol.io/
    """

    name = "mcp"
    protocol_version = "2025-03-26"
    status = "active"
    description = (
        "MCP bridge: meters MCP tool calls and maps completions to AiGentsy proofs. "
        "Wraps tool execution with proof creation and optional settlement."
    )

    async def on_task_complete(self, task_id: str, output: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Create a real proof pack from MCP tool-call completion data."""
        agent_id = kwargs.get("agent_id", "mcp_agent")
        api_key = kwargs.get("api_key", "")

        proof_data = self.map_to_proof_data(output)

        try:
            import httpx
            import os
            base = os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com")
            async with httpx.AsyncClient(base_url=base, timeout=30.0) as client:
                resp = await client.post("/protocol/proof-pack", json={
                    "agent_username": agent_id,
                    "vertical": "mcp_tool_call",
                    "proof_type": "usage_report",
                    "scope_summary": f"MCP tool call: {output.get('name', 'unknown')}",
                    "proof_data": proof_data,
                })
                result = resp.json()
                return {
                    "ok": result.get("ok", False),
                    "status": "active",
                    "deal_id": result.get("deal_id"),
                    "proof_hash": result.get("proof_hash"),
                    "metering": {
                        "call_count": proof_data.get("call_count", 1),
                        "input_tokens": proof_data.get("input_tokens", 0),
                        "output_tokens": proof_data.get("output_tokens", 0),
                        "latency_ms": proof_data.get("latency_ms", 0),
                    },
                }
        except Exception as e:
            return {"ok": False, "status": "active", "error": str(e)}

    async def on_payment_trigger(self, task_id: str, amount: float, **kwargs) -> Dict[str, Any]:
        """Trigger settlement for metered MCP tool calls."""
        return {
            "ok": True,
            "status": "active",
            "message": "Use POST /protocol/settle with the deal_id from on_task_complete to settle metered calls.",
            "task_id": task_id,
            "amount": amount,
        }

    def map_to_proof_data(self, external_event: Dict[str, Any]) -> Dict[str, Any]:
        """Map MCP tool call result to AiGentsy proof_data."""
        return {
            "source_protocol": "mcp",
            "mcp_tool_name": external_event.get("name"),
            "mcp_server_name": external_event.get("server_name"),
            "call_count": external_event.get("call_count", 1),
            "input_tokens": external_event.get("input_tokens", 0),
            "output_tokens": external_event.get("output_tokens", 0),
            "latency_ms": external_event.get("latency_ms", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class CrewAIBridge(ProtocolBridge):
    """
    CrewAI / AutoGen Bridge.

    Maps crew task completions to AiGentsy proof packs.
    """

    name = "crewai"
    protocol_version = "0.x"
    status = "planned"
    description = (
        "CrewAI/AutoGen bridge: maps agent crew task completions to AiGentsy proofs. "
        "Planned — depends on CrewAI callback stabilization."
    )

    async def on_task_complete(self, task_id: str, output: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        return {"ok": False, "status": "planned", "message": "CrewAI bridge is planned."}

    async def on_payment_trigger(self, task_id: str, amount: float, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "status": "planned", "message": "CrewAI bridge is planned."}

    def map_to_proof_data(self, external_event: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "source_protocol": "crewai",
            "task_description": external_event.get("description"),
            "agent_role": external_event.get("agent", {}).get("role"),
            "output_summary": external_event.get("output", "")[:500],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Bridge Registry ──

class BridgeRegistry:
    def __init__(self):
        self._bridges: Dict[str, ProtocolBridge] = {}

    def register(self, bridge: ProtocolBridge):
        self._bridges[bridge.name] = bridge

    def get(self, name: str) -> Optional[ProtocolBridge]:
        return self._bridges.get(name)

    def list_bridges(self) -> List[Dict[str, Any]]:
        return [b.info() for b in self._bridges.values()]


_registry: Optional[BridgeRegistry] = None


def get_bridge_registry() -> BridgeRegistry:
    global _registry
    if _registry is None:
        _registry = BridgeRegistry()
        _registry.register(A2ABridge())
        _registry.register(MCPBridge())
        _registry.register(CrewAIBridge())
    return _registry


def get_bridge(name: str) -> Optional[ProtocolBridge]:
    return get_bridge_registry().get(name)


# ── FastAPI Router ──

def get_bridge_router():
    try:
        from fastapi import APIRouter, HTTPException
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol", tags=["Cross-Protocol Bridges"])

    @router.get("/bridges")
    async def list_bridges():
        """List available cross-protocol bridge adapters."""
        reg = get_bridge_registry()
        bridges = reg.list_bridges()
        return {
            "ok": True,
            "bridges": bridges,
            "note": "Bridges in 'prep' status have interfaces defined but are not yet active. "
                    "LangGraph integration is already shipped as a separate package: aigentsy-langgraph.",
            "langgraph_package": "pip install aigentsy-langgraph",
        }

    @router.get("/bridges/{protocol}")
    async def get_bridge_info(protocol: str):
        """Get details for a specific bridge adapter."""
        reg = get_bridge_registry()
        bridge = reg.get(protocol)
        if not bridge:
            raise HTTPException(status_code=404, detail=f"No bridge for protocol '{protocol}'")
        info = bridge.info()
        info["ok"] = True

        # Add mapping example
        if hasattr(bridge, "map_to_proof_data"):
            info["proof_data_schema_example"] = bridge.map_to_proof_data({
                "id": "example_task_123",
                "status": {"state": "completed"},
                "name": "example_tool",
                "server_name": "example_server",
                "description": "Example task",
                "agent": {"role": "researcher"},
                "output": "Example output",
                "artifacts": [{"name": "result.json", "parts": [{"type": "application/json"}]}],
            })

        return info

    @router.post("/bridges/mcp/meter")
    async def mcp_meter_tool_call(body: dict):
        """
        Record a metered MCP tool call and create a proof pack.

        Send tool-call completion data and get back a deal_id with metering.
        The deal_id can later be settled via POST /protocol/settle.

        Body: {
            "name": "tool_name",
            "server_name": "mcp_server",
            "call_count": 1,
            "input_tokens": 500,
            "output_tokens": 200,
            "latency_ms": 350,
            "agent_id": "your_agent_id"
        }
        """
        reg = get_bridge_registry()
        mcp = reg.get("mcp")
        if not mcp or mcp.status != "active":
            raise HTTPException(status_code=503, detail="MCP bridge not active")
        result = await mcp.on_task_complete(
            task_id=body.get("name", "unknown"),
            output=body,
            agent_id=body.get("agent_id", "mcp_agent"),
            api_key=body.get("api_key", ""),
        )
        return result

    @router.post("/bridges/a2a/task-complete")
    async def a2a_task_complete(body: dict):
        """
        Record an A2A task completion and create a proof pack.

        Send A2A TaskStatusUpdateEvent data and get back a deal_id.
        The deal_id can later be settled via POST /protocol/settle.

        Body: {
            "id": "a2a_task_id",
            "status": {"state": "completed"},
            "artifacts": [...],
            "agent_id": "your_agent_id"
        }
        """
        reg = get_bridge_registry()
        a2a = reg.get("a2a")
        if not a2a or a2a.status != "active":
            raise HTTPException(status_code=503, detail="A2A bridge not active")
        result = await a2a.on_task_complete(
            task_id=body.get("id", "unknown"),
            output=body,
            agent_id=body.get("agent_id", "a2a_agent"),
        )
        return result

    return router
