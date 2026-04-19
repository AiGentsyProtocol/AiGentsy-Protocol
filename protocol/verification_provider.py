"""
Verification Providers — Pluggable Proof Verification
=======================================================

Provides a VerificationProvider ABC with three concrete implementations:
  - CICDVerificationProvider: test results, diffs, demos
  - ContentVerificationProvider: creative assets, landing pages
  - ServiceVerificationProvider: receipts, bookings, deliveries

Follows the same pattern as SettlementProvider in protocol/settlement_api.py.

Usage:
    from protocol.verification_provider import get_verification_registry

    registry = get_verification_registry()
    provider = registry.get_for_proof_type("creative_preview")
    result = await provider.verify(deal_id, proof_hash, proof_data, metadata)
"""

import hashlib
import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from storage_root import get_data_root

logger = logging.getLogger(__name__)

_RECEIPT_DIR = Path(os.getenv("VERIFICATION_RECEIPT_DIR", str(get_data_root() / "verification_receipts")))


class VerificationProvider(ABC):
    """Abstract base for proof verification providers."""
    name: str = "base"
    provider_type: str = "generic"  # "ci_cd" | "content" | "service"
    status: str = "active"         # "active" | "stubbed" | "disabled"

    @abstractmethod
    async def verify(
        self,
        deal_id: str,
        proof_hash: str,
        proof_data: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Verify a proof. Returns:
        {
            "verified": bool,
            "confidence": float (0.0-1.0),
            "provider": str,
            "details": dict,
            "verification_hash": str,
        }
        """
        ...

    @abstractmethod
    def supported_proof_types(self) -> List[str]:
        """Which proof_types this provider can verify."""
        ...

    def _make_verification_hash(self, deal_id: str, proof_hash: str, verified: bool) -> str:
        return hashlib.sha256(
            f"{deal_id}|{proof_hash}|{self.name}|{verified}".encode()
        ).hexdigest()[:24]


class CICDVerificationProvider(VerificationProvider):
    """
    CI/CD verification: checks test results, diff URLs, deployment status.
    """
    name = "ci_cd"
    provider_type = "ci_cd"

    async def verify(self, deal_id, proof_hash, proof_data, metadata):
        checks_run = []
        verified = False

        # Check test results
        tests_passed = proof_data.get("tests_passed", 0)
        if tests_passed > 0:
            verified = True
            checks_run.append("test_count")

        # Check diff URL
        diff_url = proof_data.get("diff_url", "")
        if diff_url:
            verified = True
            checks_run.append("diff_url_present")

        # Check demo URL
        demo_url = proof_data.get("demo_url", "")
        if demo_url:
            verified = True
            checks_run.append("demo_url_present")

        # Check endpoint preview
        endpoint = proof_data.get("endpoint_url", "")
        if endpoint:
            verified = True
            checks_run.append("endpoint_present")

        confidence = 0.85 if verified else 0.2
        return {
            "verified": verified,
            "confidence": confidence,
            "provider": self.name,
            "details": {"checks_run": checks_run, "tests_passed": tests_passed},
            "verification_hash": self._make_verification_hash(deal_id, proof_hash, verified),
        }

    def supported_proof_types(self):
        return ["test_results", "diff_preview", "demo_link", "endpoint_preview"]


class ContentVerificationProvider(VerificationProvider):
    """
    Content verification: validates creative assets, copy, landing pages.
    """
    name = "content"
    provider_type = "content"

    async def verify(self, deal_id, proof_hash, proof_data, metadata):
        checks_run = []
        verified = False

        # Check preview URL / attachment
        preview_url = proof_data.get("preview_url", "") or proof_data.get("attachment_url", "")
        if preview_url:
            verified = True
            checks_run.append("preview_url_present")

        # Check content items
        items = proof_data.get("items", proof_data.get("item_count", 0))
        if items and int(items) > 0:
            verified = True
            checks_run.append("items_present")

        # Check asset type
        asset_type = proof_data.get("asset_type", "")
        if asset_type:
            checks_run.append("asset_type_declared")

        confidence = 0.80 if verified else 0.15
        return {
            "verified": verified,
            "confidence": confidence,
            "provider": self.name,
            "details": {"checks_run": checks_run, "preview_url": preview_url[:100] if preview_url else None},
            "verification_hash": self._make_verification_hash(deal_id, proof_hash, verified),
        }

    def supported_proof_types(self):
        return ["creative_preview", "landing_preview", "ad_mock", "copy_preview",
                "bundle_mock", "product_page_preview", "conversion_plan_preview"]


class ServiceVerificationProvider(VerificationProvider):
    """
    Service verification: validates bookings, deliveries, invoices.
    """
    name = "service"
    provider_type = "service"

    async def verify(self, deal_id, proof_hash, proof_data, metadata):
        checks_run = []
        verified = False

        # Check receipt/confirmation data
        receipt_id = proof_data.get("receipt_id", "") or proof_data.get("confirmation_id", "")
        if receipt_id:
            verified = True
            checks_run.append("receipt_id_present")

        # Check photo/attachment
        photo_url = proof_data.get("photo_url", "") or proof_data.get("attachment_url", "")
        if photo_url:
            verified = True
            checks_run.append("photo_present")

        # Check timestamp
        completed_at = proof_data.get("completed_at", "") or proof_data.get("timestamp", "")
        if completed_at:
            checks_run.append("timestamp_present")

        # Check signature
        signature = proof_data.get("signature", "")
        if signature:
            verified = True
            checks_run.append("signature_present")

        confidence = 0.75 if verified else 0.10
        return {
            "verified": verified,
            "confidence": confidence,
            "provider": self.name,
            "details": {"checks_run": checks_run},
            "verification_hash": self._make_verification_hash(deal_id, proof_hash, verified),
        }

    def supported_proof_types(self):
        return ["pos_receipt", "booking_confirmation", "delivery_signature",
                "completion_photo", "invoice_paid"]


class UsageMeterVerificationProvider(VerificationProvider):
    """
    Usage/meter verification: validates API call logs, compute hours, token counts.
    """
    name = "usage_meter"
    provider_type = "usage"

    async def verify(self, deal_id, proof_hash, proof_data, metadata):
        checks_run = []
        verified = False

        # Check usage metrics
        api_calls = proof_data.get("api_calls", 0) or proof_data.get("call_count", 0)
        if api_calls and int(api_calls) > 0:
            verified = True
            checks_run.append("api_calls_present")

        # Check compute hours / token count
        compute_hours = proof_data.get("compute_hours", 0)
        token_count = proof_data.get("token_count", 0) or proof_data.get("tokens_used", 0)
        if compute_hours and float(compute_hours) > 0:
            verified = True
            checks_run.append("compute_hours_present")
        if token_count and int(token_count) > 0:
            verified = True
            checks_run.append("token_count_present")

        # Check meter reading
        meter_value = proof_data.get("meter_value", 0) or proof_data.get("reading", 0)
        if meter_value and float(meter_value) > 0:
            verified = True
            checks_run.append("meter_reading_present")

        # Check period / timestamp
        period_start = proof_data.get("period_start", "")
        period_end = proof_data.get("period_end", "")
        if period_start and period_end:
            checks_run.append("period_defined")

        confidence = 0.80 if verified else 0.15
        return {
            "verified": verified,
            "confidence": confidence,
            "provider": self.name,
            "details": {"checks_run": checks_run, "api_calls": api_calls, "token_count": token_count},
            "verification_hash": self._make_verification_hash(deal_id, proof_hash, verified),
        }

    def supported_proof_types(self):
        return ["usage_report", "meter_reading", "api_call_log"]


class VerificationProviderRegistry:
    """Registry of verification providers (follows SettlementProviderRegistry pattern)."""

    def __init__(self):
        self._providers: Dict[str, VerificationProvider] = {}

    def register(self, provider: VerificationProvider):
        self._providers[provider.name] = provider

    def get(self, name: str) -> Optional[VerificationProvider]:
        return self._providers.get(name)

    def get_for_proof_type(self, proof_type: str) -> Optional[VerificationProvider]:
        """Find provider that supports this proof type."""
        for p in self._providers.values():
            if proof_type in p.supported_proof_types():
                return p
        return None

    def list_providers(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": p.name,
                "provider_type": p.provider_type,
                "status": p.status,
                "proof_types": p.supported_proof_types(),
            }
            for p in self._providers.values()
        ]


# ── Verification Receipt (canonical schema + persistent store) ──

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


@dataclass
class VerificationReceipt:
    """Canonical verification receipt — deterministic receipt_hash for replay safety."""
    receipt_id: str
    deal_id: str
    proof_hash: str
    provider: str
    provider_type: str
    proof_type: str
    verified: bool
    confidence: float
    verification_hash: str
    receipt_hash: str       # SHA256(deal_id|proof_hash|provider|verified|confidence)[:24]
    checks_run: List[str] = field(default_factory=list)
    created_at: str = ""

    @staticmethod
    def compute_receipt_hash(deal_id: str, proof_hash: str, provider: str,
                             verified: bool, confidence: float) -> str:
        canonical = f"{deal_id}|{proof_hash}|{provider}|{verified}|{confidence}"
        return hashlib.sha256(canonical.encode()).hexdigest()[:24]


class ReceiptStore:
    """JSONL-backed verification receipt store. Dedup by receipt_hash."""

    def __init__(self, store_dir: str = str(_RECEIPT_DIR)):
        self._receipts: OrderedDict[str, VerificationReceipt] = OrderedDict()
        self._by_deal: Dict[str, List[str]] = {}  # deal_id -> [receipt_id]
        self._receipt_hashes: set = set()
        self._lock = threading.Lock()
        self._store_file: Optional[Path] = None
        try:
            path = Path(store_dir)
            path.mkdir(parents=True, exist_ok=True)
            self._store_file = path / "receipts.jsonl"
            self._load()
        except Exception as e:
            logger.warning(f"[RECEIPT_STORE] Init failed: {e}")

    def _load(self):
        if not self._store_file or not self._store_file.exists():
            return
        try:
            for line in self._store_file.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                data = json.loads(line)
                r = VerificationReceipt(**{k: v for k, v in data.items()
                                           if k in VerificationReceipt.__dataclass_fields__})
                self._receipts[r.receipt_id] = r
                self._receipt_hashes.add(r.receipt_hash)
                if r.deal_id not in self._by_deal:
                    self._by_deal[r.deal_id] = []
                self._by_deal[r.deal_id].append(r.receipt_id)
            logger.info(f"[RECEIPT_STORE] Loaded {len(self._receipts)} receipts")
        except Exception as e:
            logger.warning(f"[RECEIPT_STORE] Load failed: {e}")

    def store(self, receipt: VerificationReceipt) -> bool:
        """Store receipt. Idempotent: same receipt_hash = no-op. Returns True if new."""
        with self._lock:
            if receipt.receipt_hash in self._receipt_hashes:
                return False
            self._receipts[receipt.receipt_id] = receipt
            self._receipt_hashes.add(receipt.receipt_hash)
            if receipt.deal_id not in self._by_deal:
                self._by_deal[receipt.deal_id] = []
            self._by_deal[receipt.deal_id].append(receipt.receipt_id)
        if self._store_file:
            try:
                with open(self._store_file, "a") as f:
                    f.write(json.dumps(asdict(receipt), default=str) + "\n")
            except Exception as e:
                logger.warning(f"[RECEIPT_STORE] Persist failed: {e}")
        return True

    def get_by_deal(self, deal_id: str) -> List[VerificationReceipt]:
        ids = self._by_deal.get(deal_id, [])
        return [self._receipts[rid] for rid in ids if rid in self._receipts]

    def get(self, receipt_id: str) -> Optional[VerificationReceipt]:
        return self._receipts.get(receipt_id)


_receipt_store: Optional[ReceiptStore] = None


def get_receipt_store() -> ReceiptStore:
    global _receipt_store
    if _receipt_store is None:
        _receipt_store = ReceiptStore()
    return _receipt_store


# ── Singleton ──

_verification_registry: Optional[VerificationProviderRegistry] = None


def get_verification_registry() -> VerificationProviderRegistry:
    global _verification_registry
    if _verification_registry is None:
        _verification_registry = VerificationProviderRegistry()
        _verification_registry.register(CICDVerificationProvider())
        _verification_registry.register(ContentVerificationProvider())
        _verification_registry.register(ServiceVerificationProvider())
        import os as _os
        if _os.getenv("USAGE_METER_VERIFIER_ENABLED", "false").lower() in ("true", "1", "yes"):
            _verification_registry.register(UsageMeterVerificationProvider())
    return _verification_registry


# ── Router ──

def get_verification_router():
    try:
        from fastapi import APIRouter, HTTPException
        from pydantic import BaseModel, Field
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol", tags=["Verification Providers"])

    class VerifyRequest(BaseModel):
        deal_id: str
        proof_hash: str
        proof_type: str
        provider: Optional[str] = None  # auto-select if None
        proof_data: dict = Field(default_factory=dict)
        metadata: dict = Field(default_factory=dict)

    @router.get("/verify/providers")
    async def list_verification_providers():
        reg = get_verification_registry()
        return {"ok": True, "providers": reg.list_providers()}

    @router.post("/verify/provider")
    async def verify_with_provider(req: VerifyRequest):
        """Verify proof via provider. Emits PROOF_VERIFIED event on success."""
        reg = get_verification_registry()

        # Select provider
        if req.provider:
            provider = reg.get(req.provider)
            if not provider:
                raise HTTPException(status_code=400,
                    detail=f"Unknown provider: {req.provider}")
        else:
            provider = reg.get_for_proof_type(req.proof_type)
            if not provider:
                raise HTTPException(status_code=422,
                    detail=f"No provider for proof_type: {req.proof_type}")

        # Run verification
        result = await provider.verify(
            deal_id=req.deal_id,
            proof_hash=req.proof_hash,
            proof_data=req.proof_data,
            metadata=req.metadata,
        )

        # Create and store canonical receipt
        receipt = VerificationReceipt(
            receipt_id=f"rcpt_{uuid4().hex[:12]}",
            deal_id=req.deal_id,
            proof_hash=req.proof_hash,
            provider=provider.name,
            provider_type=provider.provider_type,
            proof_type=req.proof_type,
            verified=result["verified"],
            confidence=result["confidence"],
            verification_hash=result["verification_hash"],
            receipt_hash=VerificationReceipt.compute_receipt_hash(
                req.deal_id, req.proof_hash, provider.name,
                result["verified"], result["confidence"],
            ),
            checks_run=result.get("details", {}).get("checks_run", []),
            created_at=_now_iso(),
        )
        get_receipt_store().store(receipt)

        # Emit PROOF_VERIFIED event (with receipt_hash)
        if result.get("verified"):
            try:
                from protocol.event_store import emit_event
                await emit_event(
                    deal_id=req.deal_id,
                    event_type="PROOF_VERIFIED",
                    actor_id=provider.name,
                    payload={
                        "provider": provider.name,
                        "provider_type": provider.provider_type,
                        "proof_hash": req.proof_hash,
                        "proof_type": req.proof_type,
                        "verification_hash": result.get("verification_hash"),
                        "confidence": result.get("confidence"),
                        "receipt_hash": receipt.receipt_hash,
                        "receipt_id": receipt.receipt_id,
                    },
                    source="verification_provider",
                )
            except Exception as e:
                logger.warning(f"[VERIFY] Event emit failed: {e}")

            # ── SLA evaluation on PROOF_VERIFIED ──
            # If the deal has an attached SLA, evaluate it now.
            # auto_settle / require_review / breach — logged as events.
            sla_result = None
            try:
                from protocol.executable_sla import get_sla_store, evaluate_sla
                sla = get_sla_store().get_by_deal(req.deal_id)
                if sla:
                    deal_context = {
                        "verification_confidence": result.get("confidence", 0),
                        "proof_type": req.proof_type,
                    }
                    sla_result = evaluate_sla(sla, deal_context)
                    # Emit SLA evaluation event
                    try:
                        from protocol.event_store import emit_event
                        await emit_event(
                            deal_id=req.deal_id,
                            event_type="SLA_EVALUATED",
                            actor_id=provider.name,
                            payload={
                                "sla_id": sla.sla_id,
                                "outcome": sla_result["outcome"],
                                "all_conditions_passed": sla_result["all_conditions_passed"],
                                "sla_hash": sla.sla_hash,
                            },
                            source="verification_provider",
                        )
                    except Exception:
                        pass

                    # ── SLA auto-settle trigger ──
                    # If SLA outcome is auto_settle AND all conditions passed,
                    # trigger settlement automatically via the existing settle path.
                    if sla_result.get("outcome") == "auto_settle" and sla_result.get("all_conditions_passed"):
                        try:
                            # Look up the deal's settlement context from event chain
                            from protocol.event_store import get_event_store, emit_event
                            chain = get_event_store().get_chain(req.deal_id)
                            # Find GO_APPROVED event for amount + actors
                            go_event = None
                            for evt in chain:
                                if evt.get("event_type") in ("GO_APPROVED", "AUTO_GO_APPROVED"):
                                    go_event = evt
                                    break

                            if go_event:
                                go_payload = go_event.get("payload", {})
                                amount = go_event.get("amount", 0)
                                buyer_id = go_event.get("actor_id", "")
                                seller_id = go_event.get("counterparty_id", "") or sla.provider_agent_id

                                # Only settle if amount > 0 and we have both parties
                                if amount > 0 and buyer_id and seller_id:
                                    from protocol.agent_registry import get_agent_registry
                                    registry = get_agent_registry()
                                    tx = registry.record_settlement(
                                        from_agent=buyer_id, to_agent=seller_id,
                                        amount_usd=amount, job_id=req.deal_id,
                                        proof_hash=req.proof_hash,
                                    )
                                    await emit_event(
                                        deal_id=req.deal_id,
                                        event_type="SETTLED",
                                        actor_id=buyer_id,
                                        counterparty_id=seller_id,
                                        amount=amount,
                                        payload={
                                            "tx_id": tx.get("tx_id", ""),
                                            "net": tx.get("net", amount),
                                            "fee": tx.get("fee", 0),
                                            "trigger": "sla_auto_settle",
                                            "sla_id": sla.sla_id,
                                        },
                                        source="sla_auto_settle",
                                    )
                                    sla_result["auto_settled"] = True
                                    sla_result["settlement_tx_id"] = tx.get("tx_id", "")
                                    logger.info(f"[SLA] Auto-settled {req.deal_id} via SLA {sla.sla_id}")
                        except Exception as e:
                            logger.debug(f"[SLA] Auto-settle trigger failed (non-fatal): {e}")

            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"[VERIFY] SLA evaluation failed (non-fatal): {e}")

        return {
            "ok": True,
            "deal_id": req.deal_id,
            "verification": result,
            "provider_used": provider.name,
            "receipt_id": receipt.receipt_id,
            "receipt_hash": receipt.receipt_hash,
            "sla_evaluation": sla_result if result.get("verified") else None,
        }

    @router.get("/verify/{deal_id}/receipt")
    async def get_verification_receipts(deal_id: str):
        """Get all verification receipts for a deal."""
        receipts = get_receipt_store().get_by_deal(deal_id)
        return {
            "ok": True,
            "deal_id": deal_id,
            "receipt_count": len(receipts),
            "receipts": [asdict(r) for r in receipts],
        }

    return router
