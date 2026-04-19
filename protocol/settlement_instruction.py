"""
Settlement Instruction Contract — Layer 2/3 Boundary
=====================================================

The Settlement Instruction is the provider-neutral output of AiGentsy's
verification and coordination layer (Layer 2). It captures WHAT should be
paid, to WHOM, with WHAT proof — without specifying HOW or by WHICH provider.

The instruction is:
    - Provider-neutral (no Stripe/PayPal/etc. specifics)
    - Derived from verified settlement outputs
    - Hashable and auditable (instruction_hash)
    - Linked to proof_hash, policy_hash, idempotency_key
    - Portable (can be handed to any eligible provider)

This module is PURELY ADDITIVE. It does NOT modify any existing settlement,
payout, or provider flows. Existing code paths continue to work unchanged.
The instruction is produced ALONGSIDE existing flows, not instead of them.

Usage:
    from protocol.settlement_instruction import build_instruction

    instruction = build_instruction(
        deal_id="deal_abc",
        net_amount=97.00,
        currency="USD",
        recipient_id="agent_xyz",
        destination_type="bank_payout",
        proof_hash="sha256...",
        policy_hash="sha256...",
    )
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

SPEC_VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class FeeBreakdown:
    """Fee breakdown by rail (A/B/C)."""
    protocol_fee: float = 0.0       # set by caller based on their fee policy
    autonomy_fee: float = 0.0       # Rail B: 0.5% if auto-go
    routing_fee: float = 0.0        # Rail C: per-rail fee
    total_fees: float = 0.0


@dataclass
class SettlementInstruction:
    """
    Provider-neutral settlement instruction.

    This is the output of Layer 2 (AiGentsy verification/coordination).
    Any eligible provider can receive and execute this instruction.
    """
    # Identity
    instruction_id: str = ""
    spec_version: str = SPEC_VERSION
    deal_id: str = ""

    # Amounts
    gross_amount: float = 0.0
    net_amount: float = 0.0
    currency: str = "USD"
    fees: Dict[str, float] = field(default_factory=dict)

    # Recipient (capability-based, not brand-based)
    recipient_id: str = ""
    destination_type: str = ""          # bank_payout, wallet_payout, marketplace_disbursement, etc.
    destination_identifier: str = ""    # Opaque to AiGentsy — email, account token, wallet address

    # Proof linkage (Layer 2 outputs)
    proof_hash: str = ""
    policy_hash: str = ""
    idempotency_key: str = ""
    source_event_id: str = ""

    # Execution hints (non-binding)
    preferred_provider: str = ""        # Operator hint, not a mandate
    required_capabilities: List[str] = field(default_factory=list)

    # Metadata
    created_at: str = ""
    instruction_hash: str = ""          # SHA-256 of canonical instruction
    status: str = "pending"             # pending | executed | failed

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_instruction_hash(instruction: SettlementInstruction) -> str:
    """Compute SHA-256 of canonical instruction fields (excludes mutable fields)."""
    canonical = json.dumps(
        {
            "spec_version": instruction.spec_version,
            "deal_id": instruction.deal_id,
            "gross_amount": instruction.gross_amount,
            "net_amount": instruction.net_amount,
            "currency": instruction.currency,
            "fees": instruction.fees,
            "recipient_id": instruction.recipient_id,
            "destination_type": instruction.destination_type,
            "proof_hash": instruction.proof_hash,
            "policy_hash": instruction.policy_hash,
            "idempotency_key": instruction.idempotency_key,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_instruction(
    deal_id: str,
    gross_amount: float,
    net_amount: float,
    currency: str = "USD",
    recipient_id: str = "",
    destination_type: str = "",
    destination_identifier: str = "",
    proof_hash: str = "",
    policy_hash: str = "",
    idempotency_key: str = "",
    source_event_id: str = "",
    preferred_provider: str = "",
    required_capabilities: List[str] = None,
    fees: Dict[str, float] = None,
) -> SettlementInstruction:
    """
    Build a provider-neutral settlement instruction.

    This is called AFTER AiGentsy's Layer 2 verification is complete.
    The instruction captures the verified settlement output for handoff
    to any eligible execution provider.
    """
    instruction = SettlementInstruction(
        instruction_id=f"si_{uuid4().hex[:16]}",
        deal_id=deal_id,
        gross_amount=gross_amount,
        net_amount=net_amount,
        currency=currency,
        fees=fees or {},
        recipient_id=recipient_id,
        destination_type=destination_type,
        destination_identifier=destination_identifier,
        proof_hash=proof_hash,
        policy_hash=policy_hash,
        idempotency_key=idempotency_key,
        source_event_id=source_event_id,
        preferred_provider=preferred_provider,
        required_capabilities=required_capabilities or [],
        created_at=_now_iso(),
    )
    instruction.instruction_hash = compute_instruction_hash(instruction)
    return instruction


# ── Destination Type Constants ──
# Capability-based, not brand-based

DESTINATION_TYPES = {
    "bank_payout": "Direct bank transfer (ACH, wire, SEPA)",
    "card_payout": "Push-to-card payout",
    "email_payout": "Payout via email address (PayPal, Venmo)",
    "marketplace_disbursement": "Marketplace seller payout (Stripe Connect)",
    "wallet_payout": "Crypto wallet payout (USDC, USDT)",
    "balance_transfer": "Internal platform balance transfer",
}

# Map existing rails to capability-based destination types
RAIL_TO_DESTINATION_TYPE = {
    "STRIPE_CONNECT": "marketplace_disbursement",
    "PAYPAL": "email_payout",
    "ACH": "bank_payout",
    "CRYPTO_USDT": "wallet_payout",
    "CRYPTO_USDC": "wallet_payout",
}


def instruction_from_payout_context(
    deal_id: str,
    to_agent: str,
    gross_amount: float,
    platform_fee: float,
    settlement_fee: float,
    autonomy_fee: float = 0.0,
    routing_fee: float = 0.0,
    destination_rail: str = "",
    destination_address: str = "",
    proof_hash: str = "",
    policy_hash: str = "",
    source_event_id: str = "",
) -> SettlementInstruction:
    """
    Build an instruction from the same context that route_payout() uses.

    This is a convenience wrapper that translates the existing payout context
    into a SettlementInstruction WITHOUT changing route_payout().
    """
    net = round(gross_amount - platform_fee - settlement_fee - autonomy_fee - routing_fee, 2)
    dest_type = RAIL_TO_DESTINATION_TYPE.get(destination_rail, "balance_transfer")

    return build_instruction(
        deal_id=deal_id,
        gross_amount=gross_amount,
        net_amount=net,
        recipient_id=to_agent,
        destination_type=dest_type,
        destination_identifier=destination_address,
        proof_hash=proof_hash,
        policy_hash=policy_hash,
        source_event_id=source_event_id,
        fees={
            "protocol_fee": platform_fee,
            "settlement_fee": settlement_fee,
            "autonomy_fee": autonomy_fee,
            "routing_fee": routing_fee,
        },
    )
