"""
Provider Capability Model — Off-Ramp Capability Schema
========================================================

Declares what each connected provider CAN DO, not what brand it IS.
Enables capability-based provider selection instead of name-based.

This module is PURELY ADDITIVE. Existing provider selection via
RAIL_TO_PROVIDER in payout_router.py and req.provider in settlement_api.py
continues to work unchanged. This layer adds a capability-aware alternative.

Capabilities are declared per-provider as structured JSON. Provider selection
becomes: "given this settlement instruction's requirements, which connected
providers are eligible?"

Usage:
    from protocol.provider_capabilities import select_provider, get_capability_registry

    # Find an eligible provider for a bank payout in USD
    match = select_provider(
        destination_type="bank_payout",
        currency="USD",
    )
    if match:
        provider_name = match["provider"]
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProviderCapability:
    """Normalized capability record for a settlement provider."""
    provider: str                                   # stripe, paypal, ach, crypto, balance
    status: str = "active"                          # active | stubbed | disabled

    # What it can do (capability-based, not brand-based)
    destination_types: List[str] = field(default_factory=list)
    # e.g. ["marketplace_disbursement", "bank_payout"]

    currencies: List[str] = field(default_factory=list)
    # e.g. ["USD", "EUR", "GBP"]

    regions: List[str] = field(default_factory=lambda: ["US"])
    # ISO 3166-1 alpha-2 country codes

    # Execution characteristics
    latency_class: str = "next_day"
    # real_time | same_day | next_day | t_plus_2

    min_amount: float = 0.01
    max_amount: float = 100_000.0

    # Feature support
    supports_refund: bool = False
    supports_hold_release: bool = False
    supports_staged_payout: bool = False
    supports_metadata: bool = True

    # Compliance
    kyc_level: str = "none"
    # none | basic | enhanced | full

    # Routing fee (Rail C)
    fee_pct: float = 0.0
    fee_fixed: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Default Capability Records ──
# These match the existing providers in settlement_api.py exactly.
# No new providers are added. No existing behavior is changed.

DEFAULT_CAPABILITIES: List[ProviderCapability] = [
    ProviderCapability(
        provider="stripe",
        status="active",
        destination_types=["marketplace_disbursement"],
        currencies=["USD"],
        regions=["US"],
        latency_class="next_day",
        supports_refund=True,
        supports_hold_release=True,
        supports_metadata=True,
        kyc_level="basic",
        fee_pct=0.0,
        fee_fixed=0.0,
    ),
    ProviderCapability(
        provider="balance",
        status="active",
        destination_types=["balance_transfer"],
        currencies=["USD", "AIGx"],
        regions=["US"],
        latency_class="real_time",
        supports_refund=True,
        supports_metadata=True,
        kyc_level="none",
        fee_pct=0.0,
        fee_fixed=0.0,
    ),
    ProviderCapability(
        provider="paypal",
        status="active",
        destination_types=["email_payout"],
        currencies=["USD", "EUR", "GBP"],
        regions=["US", "GB", "DE", "FR", "CA", "AU"],
        latency_class="same_day",
        supports_refund=False,
        supports_metadata=True,
        kyc_level="none",
        fee_pct=0.01,
        fee_fixed=0.0,
    ),
    ProviderCapability(
        provider="ach",
        status="stubbed",
        destination_types=["bank_payout"],
        currencies=["USD"],
        regions=["US"],
        latency_class="t_plus_2",
        supports_refund=False,
        supports_metadata=True,
        kyc_level="basic",
        fee_pct=0.0,
        fee_fixed=0.50,
    ),
    ProviderCapability(
        provider="crypto",
        status="stubbed",
        destination_types=["wallet_payout"],
        currencies=["USDC", "USDT", "ETH", "SOL"],
        regions=["US"],
        latency_class="real_time",
        supports_refund=False,
        supports_metadata=False,
        kyc_level="none",
        fee_pct=0.003,
        fee_fixed=0.0,
    ),
]


class ProviderCapabilityRegistry:
    """Registry of provider capabilities. Answers: 'who can do X?'"""

    def __init__(self, capabilities: List[ProviderCapability] = None):
        self._capabilities: Dict[str, ProviderCapability] = {}
        for cap in (capabilities or DEFAULT_CAPABILITIES):
            self._capabilities[cap.provider] = cap

    def register(self, capability: ProviderCapability):
        self._capabilities[capability.provider] = capability

    def get(self, provider: str) -> Optional[ProviderCapability]:
        return self._capabilities.get(provider)

    def list_all(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in self._capabilities.values()]

    def find_eligible(
        self,
        destination_type: str = "",
        currency: str = "USD",
        region: str = "US",
        min_amount: float = 0.0,
        max_amount: float = 0.0,
        require_refund: bool = False,
        require_active: bool = True,
    ) -> List[ProviderCapability]:
        """
        Find providers that match the given requirements.

        Returns a list of eligible providers, sorted by:
        1. Active status (active > stubbed)
        2. Lowest fees
        """
        eligible = []
        for cap in self._capabilities.values():
            # Status filter
            if require_active and cap.status != "active":
                continue

            # Destination type filter
            if destination_type and destination_type not in cap.destination_types:
                continue

            # Currency filter
            if currency and currency not in cap.currencies:
                continue

            # Region filter
            if region and region not in cap.regions:
                continue

            # Amount range filter
            if min_amount and min_amount < cap.min_amount:
                continue
            if max_amount and max_amount > cap.max_amount:
                continue

            # Feature filter
            if require_refund and not cap.supports_refund:
                continue

            eligible.append(cap)

        # Sort: active first, then by total fee (pct + fixed ascending)
        eligible.sort(key=lambda c: (
            0 if c.status == "active" else 1,
            c.fee_pct + c.fee_fixed,
        ))

        return eligible


# ── Singleton ──

_capability_registry: Optional[ProviderCapabilityRegistry] = None


def get_capability_registry() -> ProviderCapabilityRegistry:
    global _capability_registry
    if _capability_registry is None:
        _capability_registry = ProviderCapabilityRegistry()
    return _capability_registry


def select_provider(
    destination_type: str = "",
    currency: str = "USD",
    region: str = "US",
    preferred_provider: str = "",
    amount: float = 0.0,
    require_refund: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Select the best eligible provider for a settlement instruction.

    Selection order:
    1. If preferred_provider is specified AND eligible, use it
    2. Otherwise, pick the best eligible provider (active, lowest fees)
    3. If no eligible provider, return None

    This does NOT replace existing provider selection. It provides
    a capability-aware alternative that can be used alongside
    RAIL_TO_PROVIDER and req.provider.
    """
    registry = get_capability_registry()

    # Check preferred provider first
    if preferred_provider:
        cap = registry.get(preferred_provider)
        if cap and cap.status == "active":
            # Verify it actually supports the requirements
            if (not destination_type or destination_type in cap.destination_types) and \
               (not currency or currency in cap.currencies) and \
               (not region or region in cap.regions):
                return {
                    "provider": cap.provider,
                    "selected_by": "preference",
                    "capability": cap.to_dict(),
                }

    # Find eligible providers
    eligible = registry.find_eligible(
        destination_type=destination_type,
        currency=currency,
        region=region,
        min_amount=amount,
        max_amount=amount if amount > 0 else 0.0,
        require_refund=require_refund,
        require_active=True,
    )

    if not eligible:
        return None

    best = eligible[0]
    return {
        "provider": best.provider,
        "selected_by": "capability_match",
        "candidates": len(eligible),
        "capability": best.to_dict(),
    }
