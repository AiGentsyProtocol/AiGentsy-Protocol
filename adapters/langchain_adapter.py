"""
LangChain Adapter — Use AiGentsy Protocol as LangChain Tools
==============================================================

Usage:
    from adapters.langchain_adapter import RegisterTool, ProofPackTool, VerifyTool, SettleTool

    tools = [RegisterTool(), ProofPackTool(), VerifyTool(), SettleTool()]
    agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS)
"""

import os
from typing import Optional, Type
from sdk.python.client import AiGentsyClient

try:
    from langchain_core.tools import BaseTool
    from pydantic import BaseModel, Field
except ImportError:
    from abc import ABC
    class BaseTool(ABC):
        name: str = ""
        description: str = ""
        def _run(self, **kwargs): raise NotImplementedError
        async def _arun(self, **kwargs): raise NotImplementedError
    from dataclasses import dataclass as BaseModel
    def Field(*a, **kw): return kw.get("default")

BASE = os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com")


class RegisterInput(BaseModel):
    agent_name: str = Field(default="langchain_agent", description="Name for the new agent")
    capabilities: str = Field(default="marketing", description="Comma-separated capabilities")


class ProofPackInput(BaseModel):
    agent_username: str = Field(description="Agent ID to submit proof for")
    scope_summary: str = Field(description="Description of work done")
    api_key: str = Field(default="", description="API key from registration")
    vertical: str = Field(default="marketing", description="Service vertical")


class VerifyInput(BaseModel):
    deal_id: str = Field(description="Deal ID to verify")


class SettleInput(BaseModel):
    deal_id: str = Field(description="Deal ID to settle")
    amount: float = Field(description="Settlement amount in USD")
    actor_id: str = Field(description="Seller agent ID")
    counterparty_id: str = Field(description="Buyer agent ID")
    api_key: str = Field(default="", description="API key")
    proof_hash: str = Field(default="", description="Proof hash from proof-pack")


class RegisterTool(BaseTool):
    name: str = "aigentsy_register"
    description: str = "Register an AI agent on the AiGentsy settlement protocol. Returns agent_id and api_key."
    args_schema: Type[BaseModel] = RegisterInput

    def _run(self, agent_name: str = "langchain_agent", capabilities: str = "marketing") -> str:
        client = AiGentsyClient(BASE)
        result = client.register(agent_name, capabilities=capabilities.split(","))
        return f"agent_id={result['agent_id']} api_key={result['api_key']} tier={result.get('tier')}"

    async def _arun(self, **kwargs) -> str:
        return self._run(**kwargs)


class ProofPackTool(BaseTool):
    name: str = "aigentsy_proof_pack"
    description: str = "Submit proof bundle to the AiGentsy protocol. Returns deal_id and proof_hash."
    args_schema: Type[BaseModel] = ProofPackInput

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

    async def _arun(self, **kwargs) -> str:
        return self._run(**kwargs)


class VerifyTool(BaseTool):
    name: str = "aigentsy_verify"
    description: str = "Verify a proof bundle's chain integrity. Returns chain_integrity and chain_hash."
    args_schema: Type[BaseModel] = VerifyInput

    def _run(self, deal_id: str = "") -> str:
        client = AiGentsyClient(BASE)
        result = client.verify_proof_bundle(deal_id)
        return f"chain_integrity={result.get('chain_integrity')} chain_hash={result.get('chain_hash')}"

    async def _arun(self, **kwargs) -> str:
        return self._run(**kwargs)


class SettleTool(BaseTool):
    name: str = "aigentsy_settle"
    description: str = "Settle a deal — triggers fee deduction and payout. Returns net amount."
    args_schema: Type[BaseModel] = SettleInput

    def _run(self, deal_id: str = "", amount: float = 0, actor_id: str = "",
             counterparty_id: str = "", api_key: str = "", proof_hash: str = "") -> str:
        client = AiGentsyClient(BASE, api_key=api_key)
        result = client.settle(deal_id, amount, actor_id, counterparty_id, proof_hash=proof_hash)
        return f"settled={result.get('ok')} gross=${result.get('gross', 0):.2f} net=${result.get('net', 0):.2f}"

    async def _arun(self, **kwargs) -> str:
        return self._run(**kwargs)
