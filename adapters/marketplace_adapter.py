"""
Marketplace Adapter — External Marketplace Integration
========================================================

Wraps the A2A marketplace endpoints (discover, commit, deliver)
into a simple facade for marketplace integrations.

Usage:
    from adapters.marketplace_adapter import MarketplaceAdapter

    mp = MarketplaceAdapter("http://localhost:10000", api_key="a2a_xxx")
    offers = mp.browse(capability="marketing", max_price=200)
    bid = mp.bid(offer_id=offers[0]["offer_id"], price=150)
    delivery = mp.deliver(job_id=bid["bid_id"], proof_data={"screenshot": "url"})
"""

from sdk.python.client import AiGentsyClient
from typing import Any, Dict, List, Optional


class MarketplaceAdapter:
    """High-level facade for the A2A marketplace (discover → bid → deliver)."""

    def __init__(self, base_url: str = "http://localhost:10000", api_key: str = None):
        self._client = AiGentsyClient(base_url, api_key=api_key)

    def browse(self, capability: str = None, sku_id: str = None,
               min_price: float = 0, max_price: float = 100000,
               limit: int = 50) -> List[Dict]:
        """Browse OfferNet for available work."""
        data = self._client.discover(
            capability=capability, sku_id=sku_id,
            min_price=min_price, max_price=max_price, limit=limit,
        )
        return data.get("offers", [])

    def bid(self, offer_id: str, price: float,
            estimated_hours: int = 24, message: str = "") -> Dict:
        """Place a bid on an offer."""
        return self._client.commit(
            offer_id=offer_id, bid_price=price,
            estimated_hours=estimated_hours, message=message,
        )

    def deliver(self, job_id: str, proof_type: str = "completion",
                proof_data: Dict = None, deal_id: str = None) -> Dict:
        """Submit proof bundle."""
        return self._client.deliver(
            job_id=job_id, proof_type=proof_type,
            proof_data=proof_data or {}, deal_id=deal_id,
        )

    def full_cycle(self, offer_id: str, price: float,
                   proof_data: Dict = None) -> Dict:
        """Complete cycle: bid → deliver → return result."""
        bid = self.bid(offer_id, price)
        delivery = self.deliver(
            job_id=bid.get("bid_id", offer_id),
            proof_data=proof_data or {},
            deal_id=bid.get("deal_id"),
        )
        return {"bid": bid, "delivery": delivery}
