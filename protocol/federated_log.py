"""
Federated Transparency Logs — PREP ONLY
==========================================

Design interfaces for multi-party Merkle log co-signing.
NOT ACTIVE — interfaces defined for future activation.

When active, federated logs will:
- Allow enterprises to run their own Merkle log
- Cross-sign tree heads between AiGentsy and partner logs
- Create a web of trust where no single party can tamper
- Make the protocol credibly neutral

Endpoints (prep):
    GET  /protocol/federation/witnesses    — List registered witnesses
    POST /protocol/federation/cosign       — Submit a co-signature for a tree head

Status: PREP ONLY — interfaces defined, not yet active.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FederatedWitness(ABC):
    """
    Abstract interface for a federated transparency log witness.

    A witness independently verifies and co-signs AiGentsy's Signed Tree Heads,
    creating multi-party attestation that the log is append-only.
    """
    name: str = "base"
    status: str = "planned"  # planned | prep | active
    endpoint: str = ""

    @abstractmethod
    async def verify_and_cosign(self, sth: Dict[str, Any]) -> Dict[str, Any]:
        """Verify a Signed Tree Head and return a co-signature."""
        ...

    @abstractmethod
    async def get_latest_cosigned_sth(self) -> Dict[str, Any]:
        """Get the latest STH this witness has co-signed."""
        ...

    def info(self) -> Dict[str, Any]:
        return {"name": self.name, "status": self.status, "endpoint": self.endpoint}


class AiGentsyPrimaryWitness(FederatedWitness):
    """AiGentsy's own log — always active."""
    name = "aigentsy_primary"
    status = "active"
    endpoint = "https://aigentsy-ame-runtime.onrender.com/protocol/merkle/latest"

    async def verify_and_cosign(self, sth):
        return {"ok": True, "witness": self.name, "status": "self_signed",
                "note": "Primary log — co-signing with self"}

    async def get_latest_cosigned_sth(self):
        try:
            from protocol.merkle_log import get_log
            return get_log().get_latest_sth()
        except Exception:
            return {}


class EnterpriseWitnessStub(FederatedWitness):
    """Stub for enterprise-operated witnesses. PREP ONLY."""
    name = "enterprise_witness"
    status = "planned"

    async def verify_and_cosign(self, sth):
        return {"ok": False, "status": "planned",
                "message": "Enterprise witness federation is planned. Not yet active."}

    async def get_latest_cosigned_sth(self):
        return {"ok": False, "status": "planned"}


class WitnessRegistry:
    def __init__(self):
        self._witnesses: Dict[str, FederatedWitness] = {}

    def register(self, witness: FederatedWitness):
        self._witnesses[witness.name] = witness

    def list_witnesses(self) -> List[Dict[str, Any]]:
        return [w.info() for w in self._witnesses.values()]

    def get(self, name: str) -> Optional[FederatedWitness]:
        return self._witnesses.get(name)


_registry: Optional[WitnessRegistry] = None


def get_witness_registry() -> WitnessRegistry:
    global _registry
    if _registry is None:
        _registry = WitnessRegistry()
        _registry.register(AiGentsyPrimaryWitness())
        _registry.register(EnterpriseWitnessStub())
    return _registry


# ── FastAPI Router ──

def get_federation_router():
    try:
        from fastapi import APIRouter
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol", tags=["Federated Transparency (Prep)"])

    @router.get("/federation/witnesses")
    async def list_witnesses():
        """List registered transparency log witnesses. PREP — federation not yet active."""
        reg = get_witness_registry()
        return {
            "ok": True,
            "witnesses": reg.list_witnesses(),
            "note": "Federated transparency log co-signing is in preparation. "
                    "The primary AiGentsy log is active. Enterprise witness slots are planned.",
        }

    return router
