"""
Protocol Event Schemas — Canonical event types for the AiGentsy Protocol
========================================================================

The Stripe events model for AiGentsy. Every protocol action emits a
ProtocolEvent with a deal_id universal invariant, forming a hash-chained
audit trail per deal.

Event types:
    OPPORTUNITY_FOUND     — New work discovered or subcontract posted
    PROOF_READY           — Proof bundle submitted
    GO_APPROVED           — Deal/subcontract approved to proceed
    PAYMENT_AUTHORIZED    — Escrow held or payment intent created
    FULFILLMENT_STARTED   — Work has begun
    DELIVERED             — Deliverable submitted
    SETTLED               — Payment released to recipient
    OUTCOME_RECORDED      — OCS/learning outcome recorded
    DISPUTE_OPENED        — Dispute or suspension initiated
"""

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4


class ProtocolStage(str, Enum):
    OPPORTUNITY_FOUND = "opportunity_found"
    PROOF_READY = "proof_ready"
    GO_APPROVED = "go_approved"
    PAYMENT_AUTHORIZED = "payment_authorized"
    FULFILLMENT_STARTED = "fulfillment_started"
    DELIVERED = "delivered"
    SETTLED = "settled"
    OUTCOME_RECORDED = "outcome_recorded"
    DISPUTE_OPENED = "dispute_opened"


@dataclass
class ProtocolEvent:
    event_id: str
    deal_id: str
    actor_id: str
    counterparty_id: str
    amount: float
    currency: str
    stage: ProtocolStage
    timestamp: str
    idempotency_key: str
    prev_event_hash: str
    payload: Dict[str, Any] = field(default_factory=dict)


def hash_event(event: ProtocolEvent) -> str:
    """SHA-256 of canonical JSON representation of a ProtocolEvent."""
    d = asdict(event)
    d["stage"] = event.stage.value
    canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_protocol_event(
    deal_id: str,
    actor_id: str,
    counterparty_id: str,
    amount: float,
    stage: ProtocolStage,
    payload: Optional[Dict[str, Any]] = None,
    prev_event: Optional[ProtocolEvent] = None,
    currency: str = "USD",
) -> ProtocolEvent:
    """Factory: builds a ProtocolEvent with auto-generated fields and hash chain."""
    prev_hash = hash_event(prev_event) if prev_event else ""
    return ProtocolEvent(
        event_id=f"evt_proto_{uuid4().hex[:12]}",
        deal_id=deal_id,
        actor_id=actor_id,
        counterparty_id=counterparty_id,
        amount=amount,
        currency=currency,
        stage=stage,
        timestamp=datetime.now(timezone.utc).isoformat(),
        idempotency_key=uuid4().hex,
        prev_event_hash=prev_hash,
        payload=payload or {},
    )
