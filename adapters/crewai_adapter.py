"""
CrewAI Adapter — Use AiGentsy Protocol as CrewAI Tools
========================================================

Usage:
    from adapters.crewai_adapter import RegisterTool, ProofPackTool, VerifyTool, SettleTool

    agent = Agent(tools=[RegisterTool(), ProofPackTool(), VerifyTool(), SettleTool()])
"""

import os
from typing import Any
from sdk.python.client import AiGentsyClient

try:
    from crewai.tools import BaseTool
except ImportError:
    from abc import ABC
    class BaseTool(ABC):
        name: str = ""
        description: str = ""
        def _run(self, **kwargs): raise NotImplementedError

BASE = os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com")


class RegisterTool(BaseTool):
    name: str = "aigentsy_register"
    description: str = "Register an AI agent on the AiGentsy settlement protocol. Returns agent_id and api_key."

    def _run(self, agent_name: str = "crewai_agent", capabilities: str = "marketing") -> str:
        client = AiGentsyClient(BASE)
        result = client.register(agent_name, capabilities=capabilities.split(","))
        return f"agent_id={result['agent_id']} api_key={result['api_key']} tier={result.get('tier')}"


class ProofPackTool(BaseTool):
    name: str = "aigentsy_proof_pack"
    description: str = "Submit proof bundle to the AiGentsy protocol. Returns deal_id and proof_hash."

    def _run(self, agent_username: str = "", scope_summary: str = "",
             api_key: str = "", vertical: str = "marketing") -> str:
        client = AiGentsyClient(BASE, api_key=api_key)
        result = client.create_proof_pack(
            agent_username=agent_username,
            vertical=vertical,
            proof_type="creative_preview",
            scope_summary=scope_summary,
            proof_data={"preview_url": "https://example.com/proof.jpg",
                        "asset_type": "deliverable", "timestamp": "2026-01-01T00:00:00Z"},
        )
        return f"deal_id={result['deal_id']} proof_hash={result.get('proof_hash')} estimated_price=${result.get('estimated_price', 0)}"


class VerifyTool(BaseTool):
    name: str = "aigentsy_verify"
    description: str = "Verify a proof bundle's chain integrity. Returns chain_integrity and chain_hash."

    def _run(self, deal_id: str = "") -> str:
        client = AiGentsyClient(BASE)
        result = client.verify_proof_bundle(deal_id)
        return f"chain_integrity={result.get('chain_integrity')} chain_hash={result.get('chain_hash')}"


class SettleTool(BaseTool):
    name: str = "aigentsy_settle"
    description: str = "Settle a deal — triggers fee deduction and payout. Returns net amount."

    def _run(self, deal_id: str = "", amount: float = 0, actor_id: str = "",
             counterparty_id: str = "", api_key: str = "", proof_hash: str = "") -> str:
        client = AiGentsyClient(BASE, api_key=api_key)
        result = client.settle(deal_id, amount, actor_id, counterparty_id, proof_hash=proof_hash)
        return f"settled={result.get('ok')} gross=${result.get('gross', 0):.2f} net=${result.get('net', 0):.2f}"
