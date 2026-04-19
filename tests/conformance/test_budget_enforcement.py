"""Conformance tests for mandate-bounded compute limits."""

import os
import tempfile

import pytest
from hoverstack.budget_enforcer import BudgetEnforcer


@pytest.fixture
def enforcer():
    tmp = tempfile.mktemp(suffix=".json")
    e = BudgetEnforcer(path=tmp)
    yield e
    if os.path.exists(tmp):
        os.unlink(tmp)


def test_within_budget(enforcer):
    result = enforcer.check_pre("m1", "a1", 100, 1000)
    assert result["budget_status"] == "ok_pre"
    assert result["budget_remaining"] == 1000


def test_exceeds_budget_pre(enforcer):
    result = enforcer.check_pre("m1", "a1", 1500, 1000)
    assert result["budget_status"] == "exceeded_pre"
    assert result["budget_remaining"] == 1000


def test_exceeds_budget_post(enforcer):
    enforcer.check_post("m1", "a1", 400, 400, 500)
    result = enforcer.check_post("m1", "a1", 200, 200, 500)
    assert result["budget_status"] == "exceeded_post"
    assert result["tokens_consumed_cumulative"] == 1200


def test_cumulative_tracking(enforcer):
    enforcer.check_post("m1", "a1", 100, 50, 1000)
    enforcer.check_post("m1", "a1", 100, 50, 1000)
    assert enforcer.get_consumed("m1", "a1") == 300


def test_mandate_revision_resets(enforcer):
    enforcer.check_post("m1", "a1", 500, 500, 2000)
    assert enforcer.get_consumed("m1", "a1") == 1000
    count = enforcer.reset_mandate("m1")
    assert count == 1
    assert enforcer.get_consumed("m1", "a1") == 0


def test_policy_change_does_not_reset(enforcer):
    enforcer.check_post("m1", "a1", 300, 200, 1000)
    consumed_before = enforcer.get_consumed("m1", "a1")
    # No reset method for policy — budget persists
    consumed_after = enforcer.get_consumed("m1", "a1")
    assert consumed_before == consumed_after == 500


def test_zero_budget_reports_exceeded(enforcer):
    """Budget of 0 means zero tokens authorized — any input exceeds it."""
    result = enforcer.check_pre("m_none", "a_none", 100, 0)
    assert result["budget_status"] == "exceeded_pre"


def test_large_budget_allows_all(enforcer):
    result = enforcer.check_pre("m_big", "a_big", 100, 999999)
    assert result["budget_status"] == "ok_pre"


def test_attestation_metadata_shape(enforcer):
    result = enforcer.check_post("m1", "a1", 200, 100, 1000)
    assert "budget_status" in result
    assert "budget_tokens_authorized" in result
    assert "tokens_consumed_this_call" in result
    assert "tokens_consumed_cumulative" in result
    assert "budget_remaining" in result
    assert result["tokens_consumed_this_call"] == 300
    assert result["budget_remaining"] == 700
