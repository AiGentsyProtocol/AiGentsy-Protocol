"""Conformance tests for mandate-driven model routing."""

import pytest
from hoverstack.model_router import ModelRouter


def test_fast_tier():
    r = ModelRouter()
    d = r.select({"mandate_id": "m1", "routing_tier": "fast"})
    assert d["routed_to"] == "fast"
    assert d["mandate_routing_tier"] == "fast"


def test_full_tier():
    r = ModelRouter()
    d = r.select({"mandate_id": "m1", "routing_tier": "full"})
    assert d["routed_to"] == "full"
    assert d["mandate_routing_tier"] == "full"


def test_no_routing_tier_defaults_full():
    r = ModelRouter()
    d = r.select({"mandate_id": "m1"})
    assert d["routed_to"] == "full"
    assert d["mandate_routing_tier"] is None


def test_invalid_tier_falls_back_full():
    r = ModelRouter()
    d = r.select({"mandate_id": "m1", "routing_tier": "turbo"})
    assert d["routed_to"] == "full"
    assert d["mandate_routing_tier"] == "turbo"


def test_no_mandate_defaults_full():
    r = ModelRouter()
    d = r.select(None)
    assert d["routed_to"] == "full"


def test_routing_metadata_complete():
    r = ModelRouter(fast_model="small-model", full_model="big-model")
    d = r.select({"mandate_id": "m1", "routing_tier": "fast"})
    assert d["model_name"] == "small-model"
    assert d["fast_model"] == "small-model"
    assert d["full_model"] == "big-model"
