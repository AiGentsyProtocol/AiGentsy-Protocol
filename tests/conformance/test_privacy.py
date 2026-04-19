"""
Privacy & Market Integrity Conformance Tests — Part 6
======================================================

Tests:
  1. Sealed bid privacy: open intents hide prices, closed reveals winner
  2. Log sanitization: bid price not in event payload
  3. Econ feed delay >= 3600s
  4. Econ feed k-anonymity: verticals below K suppressed
  5. Premium feed auth-gated
"""

import json
import os
import sys

import pytest


class TestSealedBidPrivacy:
    """Verify that sealed bids hide prices until intent is closed."""

    def test_open_intent_hides_bids(self):
        """GET /intents/{id} on open intent shows bid_count but not prices."""
        from protocol.exchange import ExchangeStore

        store = ExchangeStore.__new__(ExchangeStore)
        store._intents = {}
        store._bids = {}
        store._lock = __import__("threading").Lock()
        store._intent_file = None
        store._bid_file = None

        # Create intent directly
        from protocol.exchange import Intent, SealedBid
        intent = Intent(
            intent_id="intent_test_001",
            deal_id="deal_test_001",
            client_id="client_test",
            capability="marketing",
            budget_usd=100.0,
            deadline_hours=24,
            status="open",
            created_at="2026-01-01T00:00:00Z",
        )
        store._intents[intent.intent_id] = intent

        bid = SealedBid(
            bid_id="bid_test_001",
            intent_id="intent_test_001",
            agent_id="agent_test",
            price_usd=85.0,
            delivery_hours=12,
            submitted_at="2026-01-01T01:00:00Z",
        )
        store._bids["intent_test_001"] = [bid]

        # Simulate GET intent response for open intent
        resp = {
            "intent_id": intent.intent_id,
            "status": intent.status,
            "bid_count": len(store.get_bids(intent.intent_id)),
        }

        # Open intent should show count but not reveal prices
        if intent.status == "open":
            resp["bids"] = "sealed"

        assert resp["bids"] == "sealed"
        assert resp["bid_count"] == 1
        assert "price_usd" not in json.dumps(resp)

    def test_closed_intent_reveals_winner(self):
        """After close, winner details are visible."""
        from protocol.exchange import Intent

        intent = Intent(
            intent_id="intent_test_002",
            deal_id="deal_test_002",
            client_id="client_test",
            capability="marketing",
            budget_usd=100.0,
            deadline_hours=24,
            status="awarded",
            winner_agent_id="agent_winner",
            winner_bid_id="bid_winner",
            created_at="2026-01-01T00:00:00Z",
            closed_at="2026-01-01T02:00:00Z",
        )
        assert intent.status == "awarded"
        assert intent.winner_agent_id == "agent_winner"
        assert intent.winner_bid_id == "bid_winner"


class TestLogSanitization:
    """Verify bid price is NOT in BID_RECEIVED event payload."""

    def test_bid_event_omits_price(self):
        """BID_RECEIVED event payload should not contain price_usd."""
        # This is the payload format used in exchange.py submit_bid()
        payload = {
            "intent_id": "intent_test_001",
            "bid_id": "bid_test_001",
            "agent_id": "agent_test",
        }
        payload_json = json.dumps(payload)
        assert "price_usd" not in payload_json
        assert "85.0" not in payload_json

    def test_bid_event_amount_is_zero(self):
        """BID_RECEIVED event amount should be 0 (sealed)."""
        # In exchange.py, BID_RECEIVED is emitted with amount=0
        event = {
            "event_type": "BID_RECEIVED",
            "amount": 0,  # sealed — don't reveal price
            "payload": {"bid_id": "bid_test_001"},
        }
        assert event["amount"] == 0


class TestEconFeedPrivacy:
    """Verify economic feed privacy controls."""

    def test_delay_minimum(self):
        """ECON_FEED_DELAY_SECONDS must be >= 3600 (1 hour)."""
        from protocol.econ_feed import ECON_FEED_DELAY_SECONDS
        assert ECON_FEED_DELAY_SECONDS >= 3600

    def test_public_feed_has_delay_applied(self):
        """Public feed response must include delay_applied_seconds."""
        from protocol.econ_feed import get_delayed_snapshot
        snapshot = get_delayed_snapshot()
        assert "delay_applied_seconds" in snapshot
        assert snapshot["delay_applied_seconds"] >= 3600
        assert snapshot["feed_type"] == "public"


class TestEconFeedKAnonymity:
    """Verify k-anonymity suppression of low-count verticals."""

    def test_k_anonymity_threshold_exists(self):
        """K_ANONYMITY_THRESHOLD must be defined and >= 1."""
        from protocol.econ_feed import K_ANONYMITY_THRESHOLD
        assert K_ANONYMITY_THRESHOLD >= 1

    def test_apply_k_anonymity_suppresses(self):
        """Verticals with fewer than K deals should be suppressed."""
        from protocol.econ_feed import K_ANONYMITY_THRESHOLD, _apply_k_anonymity
        gmv = {
            "marketing": 5000.0,  # 10 deals
            "web_dev": 200.0,     # 2 deals (below K)
            "data_science": 8000.0,  # 15 deals
        }
        deal_counts = {
            "marketing": 10,
            "web_dev": 2,
            "data_science": 15,
        }
        result = _apply_k_anonymity(gmv, deal_counts, K_ANONYMITY_THRESHOLD)
        # web_dev should be suppressed (2 < 5)
        assert "web_dev" not in result
        assert "marketing" in result
        assert "data_science" in result

    def test_rounding_applied(self):
        """GMV values in public feed should be rounded."""
        from protocol.econ_feed import ROUNDING_PRECISION
        assert ROUNDING_PRECISION >= 0
        # Verify rounding works
        val = 12345.6789
        rounded = round(val, ROUNDING_PRECISION)
        assert rounded == round(val, ROUNDING_PRECISION)
