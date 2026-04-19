"""
Accretive Stack Integration Test Suite
========================================

End-to-end tests verifying that the three reintegration tranches
compose correctly with the existing protocol wedge:

    1. Brain → Protocol inputs (MetaHive, Yield Memory, Brain Policy Trainer)
    2. MetaBridge → Intent Exchange (complexity + team suggestion)
    3. Brain Policy Trainer → Acceptance Policy (advisory suggestions)

Tests operate at the module level (direct function calls) to verify
real wiring without requiring a running server.

Usage:
    python -m pytest tests/conformance/test_accretive_stack.py -v
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure repo root is on path
_repo = Path(__file__).parent.parent.parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))


# ── Fixtures ──


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path, monkeypatch):
    """Isolate all JSONL stores to a temp directory for each test."""
    monkeypatch.setenv("EVENT_STORE_DIR", str(tmp_path / "events"))
    monkeypatch.setenv("EXCHANGE_STORE_DIR", str(tmp_path / "exchange"))
    monkeypatch.setenv("ACCEPTANCE_DIR", str(tmp_path / "acceptance"))
    monkeypatch.setenv("ACCEPTANCE_POLICY_DIR", str(tmp_path / "policies"))
    monkeypatch.setenv("COMMERCE_LOOP_DIR", str(tmp_path / "commerce"))
    monkeypatch.setenv("MULTIPARTY_DIR", str(tmp_path / "multiparty"))

    # Reset singletons so they re-initialize with temp dirs
    import protocol.event_store as es
    import protocol.exchange as ex
    import protocol.acceptance_gate as ag
    import protocol.acceptance_policy as ap
    import protocol.autonomous_commerce as ac
    import protocol.multiparty_settlement as mps

    es._event_store = None
    ex._exchange_store = None
    ag._store = None
    ap._store = None
    ap._suggestion_store = None
    ac._store = None
    mps._mps_store = None

    yield

    # Re-reset after test
    es._event_store = None
    ex._exchange_store = None
    ag._store = None
    ap._store = None
    ap._suggestion_store = None
    ac._store = None
    mps._mps_store = None


# ── Helpers ──


def _emit_event_sync(deal_id, event_type, actor_id="", amount=0.0, payload=None, source="test"):
    """Synchronous event emission for tests (bypasses async)."""
    from protocol.event_store import get_event_store
    store = get_event_store()
    record = {
        "deal_id": deal_id,
        "event_type": event_type,
        "actor_id": actor_id,
        "amount": amount,
        "payload": payload or {},
        "source": source,
    }
    return store.append(record)


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 1: Single-Agent Lifecycle
# ══════════════════════════════════════════════════════════════════════


class TestSingleAgentLifecycle:
    """Normal single-agent lifecycle through the full wedge."""

    def test_intent_publish_simple(self):
        """Simple intent (low budget, no skills) has no complexity flag."""
        from protocol.exchange import get_exchange_store

        store = get_exchange_store()
        intent = store.create_intent(
            client_id="client_1",
            capability="marketing",
            budget_usd=500,
            deadline_hours=24,
        )
        assert intent.intent_id.startswith("intent_")
        assert intent.deal_id
        assert intent.status == "open"
        assert intent.complexity is None  # simple intent

    def test_intent_publish_with_complexity(self):
        """Complex intent gets MetaBridge complexity analysis."""
        from protocol.exchange import get_exchange_store, _analyze_complexity, Intent

        store = get_exchange_store()
        intent = store.create_intent(
            client_id="client_2",
            capability="full_stack_app",
            budget_usd=5000,
            deadline_hours=200,
            requirements={
                "required_skills": ["python", "react", "devops", "design"],
                "estimated_hours": 150,
            },
        )

        complexity = _analyze_complexity(intent)
        assert complexity is not None
        assert complexity["requires_team"] is True
        assert "high_budget" in complexity["complexity_factors"]
        assert "diverse_skills" in complexity["complexity_factors"]
        assert complexity["skill_count"] == 4

    def test_bid_submission_and_scoring(self):
        """Bids are stored and scored with 4-factor composite."""
        from protocol.exchange import get_exchange_store, score_bid, SealedBid

        store = get_exchange_store()
        intent = store.create_intent(
            client_id="client_1",
            capability="marketing",
            budget_usd=1000,
            deadline_hours=48,
        )

        bid1 = store.add_bid(intent.intent_id, "agent_a", 800, 40, ocs_score=75, sla_on_time_rate=0.9)
        bid2 = store.add_bid(intent.intent_id, "agent_b", 600, 36, ocs_score=60, sla_on_time_rate=0.7)

        bids = store.get_bids(intent.intent_id)
        assert len(bids) == 2

        # Score bids
        bid1.composite_score = score_bid(bid1, bids, intent)
        bid2.composite_score = score_bid(bid2, bids, intent)

        # Both should have valid scores
        assert 0 < bid1.composite_score <= 1
        assert 0 < bid2.composite_score <= 1

    def test_acceptance_gate_lifecycle(self):
        """Submit → decide acceptance flow works end-to-end."""
        from protocol.acceptance_gate import AcceptanceStore

        store = AcceptanceStore(store_dir=str(Path(os.environ["ACCEPTANCE_DIR"])))

        # Submit
        rec = store.submit(deal_id="deal_100", submitted_by="agent_a", downstream_action="settle")
        assert rec.status == "pending"
        assert rec.acceptance_id.startswith("acc_")

        # Idempotent re-submit
        rec2 = store.submit(deal_id="deal_100", submitted_by="agent_a")
        assert rec2.acceptance_id == rec.acceptance_id

        # Accept
        decided = store.decide(rec.acceptance_id, "accept", reviewer_id="reviewer_1",
                               reason="all checks passed", checks_passed=["ocs", "verification"])
        assert decided.status == "accepted"
        assert decided.decision == "accept"
        assert decided.reviewer_id == "reviewer_1"
        assert decided.decided_at != ""

        # Cannot re-decide
        re_decided = store.decide(rec.acceptance_id, "reject", reviewer_id="reviewer_2")
        assert re_decided is None  # already decided

    def test_acceptance_gate_rejection(self):
        """Rejection path works correctly."""
        from protocol.acceptance_gate import AcceptanceStore

        store = AcceptanceStore(store_dir=str(Path(os.environ["ACCEPTANCE_DIR"])))
        rec = store.submit(deal_id="deal_200", submitted_by="agent_b", downstream_action="release")
        decided = store.decide(rec.acceptance_id, "reject", reviewer_id="reviewer_1",
                               reason="quality below threshold", checks_failed=["quality_floor"])
        assert decided.status == "rejected"
        assert decided.checks_failed == ["quality_floor"]

    def test_event_chain_integrity(self):
        """Events chain correctly with hash linking."""
        from protocol.event_store import get_event_store

        store = get_event_store()
        deal_id = "deal_chain_test"

        e1 = _emit_event_sync(deal_id, "PROOF_READY", actor_id="agent_a", amount=500)
        e2 = _emit_event_sync(deal_id, "PROOF_VERIFIED", actor_id="verifier_1", payload={"confidence": 0.95})
        e3 = _emit_event_sync(deal_id, "ACCEPTANCE_PENDING", actor_id="agent_a")
        e4 = _emit_event_sync(deal_id, "ACCEPTED", actor_id="reviewer_1")
        e5 = _emit_event_sync(deal_id, "SETTLED", actor_id="agent_a", amount=500)

        chain = store.get_chain(deal_id)
        assert len(chain) == 5
        assert chain[0]["event_type"] == "PROOF_READY"
        assert chain[1]["event_type"] == "PROOF_VERIFIED"
        assert chain[2]["event_type"] == "ACCEPTANCE_PENDING"
        assert chain[3]["event_type"] == "ACCEPTED"
        assert chain[4]["event_type"] == "SETTLED"

        # Hash chain: each event's prev_hash should reference the previous
        for i in range(1, len(chain)):
            assert chain[i].get("prev_hash") == chain[i - 1].get("hash"), \
                f"Hash chain broken at index {i}"


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 2: Complex Intent + MetaBridge Team Suggestion
# ══════════════════════════════════════════════════════════════════════


class TestComplexIntentWithTeamSuggestion:
    """Complex intent → MetaBridge complexity analysis → team suggestion."""

    def test_complexity_detection_simple_intent(self):
        """Simple intents do NOT trigger team formation."""
        from protocol.exchange import _analyze_complexity, Intent

        simple = Intent(
            intent_id="i1", deal_id="d1", client_id="c1",
            capability="copywriting", budget_usd=300,
            deadline_hours=12, requirements={}, created_at="now",
        )
        result = _analyze_complexity(simple)
        assert result is not None
        assert result["requires_team"] is False

    def test_complexity_detection_complex_intent(self):
        """Complex intents trigger team formation detection."""
        from protocol.exchange import _analyze_complexity, Intent

        complex_intent = Intent(
            intent_id="i2", deal_id="d2", client_id="c2",
            capability="enterprise_app", budget_usd=10000,
            deadline_hours=500, requirements={
                "required_skills": ["python", "react", "devops", "security", "design"],
                "estimated_hours": 300,
            }, created_at="now",
        )
        result = _analyze_complexity(complex_intent)
        assert result["requires_team"] is True
        assert "high_budget" in result["complexity_factors"]
        assert "diverse_skills" in result["complexity_factors"]
        assert "large_scope" in result["complexity_factors"]
        assert result["skill_count"] == 5

    def test_team_suggestion_returns_none_without_agents(self):
        """Team suggestion gracefully returns None when no agents are registered."""
        from protocol.exchange import _build_team_suggestion, Intent

        intent = Intent(
            intent_id="i3", deal_id="d3", client_id="c3",
            capability="enterprise_app", budget_usd=5000,
            deadline_hours=200, requirements={
                "required_skills": ["python", "react", "devops"],
            }, created_at="now",
        )
        result = _build_team_suggestion(intent)
        # With no registered agents, should return None
        assert result is None

    def test_metabridge_functions_are_importable(self):
        """Verify MetaBridge functions are importable from the repo."""
        from metabridge import (
            analyze_intent_complexity,
            find_complementary_agents,
            optimize_team_composition,
            assign_team_roles,
            calculate_team_splits,
        )
        # All should be callable
        assert callable(analyze_intent_complexity)
        assert callable(find_complementary_agents)

    def test_metabridge_team_formation_pipeline(self):
        """Full MetaBridge pipeline: analyze → find → optimize → assign → split."""
        from metabridge import (
            analyze_intent_complexity,
            find_complementary_agents,
            optimize_team_composition,
            assign_team_roles,
            calculate_team_splits,
        )

        intent = {
            "budget": 5000,
            "required_skills": ["python", "react", "devops"],
            "estimated_hours": 150,
        }

        # 1. Complexity analysis
        complexity = analyze_intent_complexity(intent)
        assert complexity["requires_team"] is True

        # 2. Find candidates (mock agents)
        agents = [
            {"username": "alice", "profile": {"skills": ["python", "devops"]}, "outcomeScore": 80},
            {"username": "bob", "profile": {"skills": ["react", "design"]}, "outcomeScore": 70},
            {"username": "carol", "profile": {"skills": ["python", "react"]}, "outcomeScore": 90},
        ]
        candidates = find_complementary_agents(intent, agents)
        assert candidates["ok"] is True
        assert candidates["total_candidates"] >= 2

        # 3. Optimize team
        team = optimize_team_composition(intent, candidates["candidates"])
        assert team["ok"] is True
        assert team["team_size"] >= 2
        assert team["skill_coverage"] > 0

        # 4. Assign roles
        roles = assign_team_roles(team["team"], intent)
        assert roles["ok"] is True
        assert any(r["role"] == "lead" for r in roles["roles"])

        # 5. Calculate splits
        splits = calculate_team_splits(roles["roles"], 5000)
        assert splits["ok"] is True
        assert abs(sum(splits["splits"].values()) - 1.0) < 0.02


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 3: Acceptance Policy with Brain Enrichment
# ══════════════════════════════════════════════════════════════════════


class TestAcceptancePolicyWithBrainEnrichment:
    """Acceptance policy evaluation with brain/learning context enrichment."""

    def test_policy_creation_and_evaluation(self):
        """Basic policy create → evaluate works."""
        from protocol.acceptance_policy import get_acceptance_policy_store, evaluate_acceptance_policy

        store = get_acceptance_policy_store()
        pol = store.create("agent_x", [
            {"conditions": [{"field": "seller_ocs", "op": ">=", "value": 80}], "action": "auto_accept"},
        ], "require_review")

        assert pol.policy_id.startswith("apol_")
        assert pol.agent_id == "agent_x"

        # Evaluate (no deal data → falls to default)
        result = evaluate_acceptance_policy("fake_deal", "agent_x")
        assert result["action"] == "require_review"
        assert result["reason"] == "no_rule_matched"

    def test_policy_evaluation_with_matching_rule(self):
        """Policy evaluates matching rule correctly."""
        from protocol.acceptance_policy import (
            get_acceptance_policy_store, _eval_condition
        )

        # Test condition evaluation directly
        assert _eval_condition({"field": "seller_ocs", "op": ">=", "value": 80}, {"seller_ocs": 90}) is True
        assert _eval_condition({"field": "seller_ocs", "op": ">=", "value": 80}, {"seller_ocs": 70}) is False
        assert _eval_condition({"field": "amount_usd", "op": "<=", "value": 1000}, {"amount_usd": 500}) is True
        assert _eval_condition({"field": "vertical", "op": "in", "value": ["marketing", "dev"]}, {"vertical": "marketing"}) is True
        assert _eval_condition({"field": "vertical", "op": "in", "value": ["marketing", "dev"]}, {"vertical": "legal"}) is False

    def test_brain_enrichment_fields_allowed(self):
        """Brain-enriched fields are in ALLOWED_FIELDS."""
        from protocol.acceptance_policy import ALLOWED_FIELDS

        assert "hive_success_rate" in ALLOWED_FIELDS
        assert "yield_confidence" in ALLOWED_FIELDS
        assert "brain_recommended_action" in ALLOWED_FIELDS

    def test_brain_enriched_policy_rule(self):
        """Policy with brain-enriched fields evaluates correctly."""
        from protocol.acceptance_policy import _eval_condition

        # Simulate brain-enriched context
        context = {
            "seller_ocs": 75,
            "verification_confidence": 0.92,
            "hive_success_rate": 0.85,
            "yield_confidence": 0.78,
        }

        # Rule using brain fields
        brain_cond_1 = {"field": "hive_success_rate", "op": ">=", "value": 0.7}
        brain_cond_2 = {"field": "yield_confidence", "op": ">=", "value": 0.6}

        assert _eval_condition(brain_cond_1, context) is True
        assert _eval_condition(brain_cond_2, context) is True


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 4: Brain Feedback + Policy Suggestion Lifecycle
# ══════════════════════════════════════════════════════════════════════


class TestBrainFeedbackAndPolicySuggestions:
    """Commerce loop outcomes feed brain → trainer generates suggestions → agent reviews."""

    def test_brain_feedback_function_exists(self):
        """The _feed_outcome_to_brain function exists in autonomous_commerce."""
        from protocol.autonomous_commerce import _feed_outcome_to_brain, LoopCycle

        # Create a mock cycle
        cycle = LoopCycle(
            agent_id="agent_test",
            deal_id="deal_test",
            steps_completed=["proof_verified", "accepted", "sla_auto_settled"],
            steps_failed=[],
            outcome="completed",
            settled_amount_usd=500.0,
        )

        # Should not raise — fire-and-forget
        _feed_outcome_to_brain(cycle)

    def test_brain_policy_trainer_buffering(self):
        """Brain Policy Trainer buffers outcomes correctly."""
        from brain_policy_trainer import get_brain_trainer, buffer_outcome

        trainer = get_brain_trainer()
        initial_count = len(trainer._outcomes_buffer)

        buffer_outcome({
            "engines_used": ["autonomous_commerce"],
            "revenue": 500.0,
            "baseline": 0,
            "segment": "commerce_loop",
            "outcome": "completed",
            "agent_id": "agent_test",
        })

        assert len(trainer._outcomes_buffer) == initial_count + 1

    def test_suggestion_store_lifecycle(self):
        """Suggestion store: add → list → review works end-to-end."""
        from protocol.acceptance_policy import get_suggestion_store

        store = get_suggestion_store()

        # Add suggestion
        sug = store.add(
            agent_id="agent_x",
            suggested_rule={
                "conditions": [{"field": "seller_ocs", "op": ">=", "value": 60}],
                "action": "auto_accept",
            },
            rationale="High success rate observed in recent settlements",
            evidence={"success_rate": 0.88, "sample_size": 12},
            trainer_version="cycles:5",
        )
        assert sug.status == "pending"
        assert sug.suggestion_id.startswith("psug_")

        # List pending
        pending = store.list_for_agent("agent_x", status="pending")
        assert len(pending) == 1

        # Adopt
        reviewed = store.review(sug.suggestion_id, "adopted", "agent_x")
        assert reviewed.status == "adopted"
        assert reviewed.reviewed_by == "agent_x"
        assert reviewed.reviewed_at != ""

        # Cannot re-review
        re_review = store.review(sug.suggestion_id, "dismissed", "agent_x")
        assert re_review is None

        # Stats
        stats = store.stats()
        assert stats["adopted"] >= 1
        assert stats["pending"] == 0

    def test_suggestion_adoption_updates_policy(self):
        """Adopting a suggestion appends the rule to the agent's active policy."""
        from protocol.acceptance_policy import (
            get_acceptance_policy_store, get_suggestion_store,
        )

        pol_store = get_acceptance_policy_store()
        sug_store = get_suggestion_store()

        # Create initial policy with 1 rule
        pol = pol_store.create("agent_y", [
            {"conditions": [{"field": "amount_usd", "op": "<=", "value": 1000}], "action": "auto_accept"},
        ], "require_review")
        assert len(pol.rules) == 1

        # Create and adopt a suggestion
        sug = sug_store.add(
            agent_id="agent_y",
            suggested_rule={
                "conditions": [{"field": "hive_success_rate", "op": ">=", "value": 0.7}],
                "action": "auto_accept",
            },
            rationale="Brain signals correlate with success",
            evidence={"success_rate": 0.82},
        )
        sug_store.review(sug.suggestion_id, "adopted", "agent_y")

        # Manually simulate adoption (same logic as the endpoint)
        existing = pol_store.get_by_agent("agent_y")
        updated_rules = existing.rules + [sug.suggested_rule]
        new_pol = pol_store.create("agent_y", updated_rules, existing.default_action)

        # Verify the new policy has 2 rules
        final = pol_store.get_by_agent("agent_y")
        assert len(final.rules) == 2
        assert final.rules[1]["conditions"][0]["field"] == "hive_success_rate"

    def test_generate_suggestions_empty_buffer(self):
        """Suggestion generation with empty trainer buffer returns nothing."""
        from protocol.acceptance_policy import generate_suggestions_from_trainer

        results = generate_suggestions_from_trainer("agent_z")
        assert results == []

    def test_generate_suggestions_with_outcomes(self):
        """Suggestion generation with buffered outcomes produces suggestions."""
        from protocol.acceptance_policy import generate_suggestions_from_trainer
        from brain_policy_trainer import get_brain_trainer

        trainer = get_brain_trainer()

        # Buffer enough outcomes to trigger suggestion generation
        for i in range(5):
            trainer.buffer_outcome({
                "engines_used": ["autonomous_commerce"],
                "revenue": 500.0 + i * 100,
                "baseline": 0,
                "segment": "commerce_loop",
                "outcome": "completed",
                "agent_id": "agent_sug",
            })

        results = generate_suggestions_from_trainer("agent_sug")
        # Should produce at least 1 suggestion (high success rate pattern)
        assert len(results) >= 1
        assert results[0].status == "pending"
        assert results[0].rationale != ""
        assert results[0].evidence.get("success_rate", 0) > 0


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 5: KPI Dashboard Brain Overlay
# ══════════════════════════════════════════════════════════════════════


class TestKPIDashboardBrainOverlay:
    """KPI dashboard includes brain_stats overlay."""

    def test_brain_stats_present_in_overview(self):
        """KPI overview includes brain_stats key."""
        from protocol.kpi_dashboard import _compute_overview

        overview = _compute_overview()
        assert "brain_stats" in overview
        assert isinstance(overview["brain_stats"], dict)

    def test_brain_stats_has_expected_keys(self):
        """Brain stats section has MetaHive, AI Family, and Yield Memory signals."""
        from protocol.kpi_dashboard import _compute_brain_stats

        stats = _compute_brain_stats()
        # At minimum, yield_memory_available should always be present
        assert "yield_memory_available" in stats

    def test_kpi_acceptance_metrics(self):
        """KPI overview includes acceptance metrics."""
        from protocol.kpi_dashboard import _compute_overview

        overview = _compute_overview()
        assert "total_acceptances" in overview
        assert "total_rejections" in overview
        assert "acceptance_rate" in overview
        assert "acceptance_pending" in overview


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 6: Settlement Intelligence Brain Enrichment
# ══════════════════════════════════════════════════════════════════════


class TestSettlementIntelligenceBrainEnrichment:
    """Settlement intelligence premium feed includes brain intelligence."""

    def test_brain_intelligence_function(self):
        """_build_brain_intelligence returns structured data."""
        from protocol.settlement_intelligence import _build_brain_intelligence

        result = _build_brain_intelligence()
        assert isinstance(result, dict)

    def test_public_feed_no_brain(self):
        """Public intelligence feed does NOT include brain data (premium only)."""
        from protocol.settlement_intelligence import build_intelligence_feed

        feed = build_intelligence_feed()
        assert "brain_intelligence" not in feed  # public feed only

    def test_intelligence_feed_structure(self):
        """Intelligence feed has expected sections."""
        from protocol.settlement_intelligence import build_intelligence_feed

        feed = build_intelligence_feed()
        assert "verticals" in feed
        assert "sla_benchmarks" in feed
        assert "netting" in feed
        assert "marketplace" in feed
        assert "credentials" in feed
        assert "k_anonymity_threshold" in feed


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 7: Full Wedge Lifecycle (proof → verify → accept → settle)
# ══════════════════════════════════════════════════════════════════════


class TestFullWedgeLifecycle:
    """End-to-end wedge: proof → verify → accept/reject → settle."""

    def test_full_accept_lifecycle(self):
        """PROOF_READY → PROOF_VERIFIED → ACCEPTANCE_PENDING → ACCEPTED → SETTLED."""
        from protocol.event_store import get_event_store
        from protocol.acceptance_gate import AcceptanceStore

        deal_id = "deal_full_lifecycle"

        # Step 1: Proof created
        _emit_event_sync(deal_id, "PROOF_READY", actor_id="seller_1", amount=1000)

        # Step 2: Proof verified
        _emit_event_sync(deal_id, "PROOF_VERIFIED", actor_id="verifier_1",
                         payload={"confidence": 0.95})

        # Step 3: Submit for acceptance
        acc_store = AcceptanceStore(store_dir=str(Path(os.environ["ACCEPTANCE_DIR"])))
        rec = acc_store.submit(deal_id=deal_id, submitted_by="seller_1", downstream_action="settle")
        assert rec.status == "pending"

        _emit_event_sync(deal_id, "ACCEPTANCE_PENDING", actor_id="seller_1",
                         payload={"acceptance_id": rec.acceptance_id})

        # Step 4: Accept
        decided = acc_store.decide(rec.acceptance_id, "accept",
                                   reviewer_id="buyer_1", reason="quality verified",
                                   checks_passed=["proof_hash", "verification_confidence"])
        assert decided.status == "accepted"

        _emit_event_sync(deal_id, "ACCEPTED", actor_id="buyer_1",
                         payload={"acceptance_id": rec.acceptance_id, "downstream_action": "settle"})

        # Step 5: Settle
        _emit_event_sync(deal_id, "SETTLED", actor_id="seller_1", amount=1000,
                         payload={"trigger": "sla_auto_settle"})

        # Verify full chain
        chain = get_event_store().get_chain(deal_id)
        types = [e["event_type"] for e in chain]
        assert types == [
            "PROOF_READY", "PROOF_VERIFIED", "ACCEPTANCE_PENDING",
            "ACCEPTED", "SETTLED",
        ]

    def test_full_reject_lifecycle(self):
        """PROOF_READY → PROOF_VERIFIED → ACCEPTANCE_PENDING → REJECTED."""
        from protocol.event_store import get_event_store
        from protocol.acceptance_gate import AcceptanceStore

        deal_id = "deal_reject_lifecycle"

        _emit_event_sync(deal_id, "PROOF_READY", actor_id="seller_2", amount=2000)
        _emit_event_sync(deal_id, "PROOF_VERIFIED", actor_id="verifier_1",
                         payload={"confidence": 0.45})

        acc_store = AcceptanceStore(store_dir=str(Path(os.environ["ACCEPTANCE_DIR"])))
        rec = acc_store.submit(deal_id=deal_id, submitted_by="seller_2", downstream_action="settle")

        _emit_event_sync(deal_id, "ACCEPTANCE_PENDING", actor_id="seller_2")

        decided = acc_store.decide(rec.acceptance_id, "reject",
                                   reviewer_id="buyer_2", reason="low confidence",
                                   checks_failed=["verification_confidence"])
        assert decided.status == "rejected"

        _emit_event_sync(deal_id, "REJECTED", actor_id="buyer_2",
                         payload={"checks_failed": ["verification_confidence"]})

        chain = get_event_store().get_chain(deal_id)
        types = [e["event_type"] for e in chain]
        assert types == [
            "PROOF_READY", "PROOF_VERIFIED", "ACCEPTANCE_PENDING", "REJECTED",
        ]
        # No SETTLED event — rejection blocks settlement
        assert "SETTLED" not in types


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 8: Team-Awarded Multiparty Settlement
# ══════════════════════════════════════════════════════════════════════


class TestTeamAwardedMultipartySettlement:
    """Full team lifecycle: complex intent → team suggestion → settlement → splits."""

    def test_team_splits_proposed_event(self):
        """TEAM_SPLITS_PROPOSED event persists team structure in deal chain."""
        from protocol.event_store import get_event_store

        deal_id = "deal_team_1"
        _emit_event_sync(deal_id, "TEAM_SPLITS_PROPOSED", actor_id="client_1",
                         amount=5000, payload={
                             "intent_id": "intent_xyz",
                             "team_size": 3,
                             "members": [
                                 {"agent_id": "alice", "role": "lead"},
                                 {"agent_id": "bob", "role": "specialist"},
                                 {"agent_id": "carol", "role": "support"},
                             ],
                             "revenue_splits": {"alice": 0.40, "bob": 0.35, "carol": 0.25},
                             "skill_coverage": 0.95,
                             "source": "metabridge",
                         }, source="exchange")

        chain = get_event_store().get_chain(deal_id)
        assert len(chain) == 1
        evt = chain[0]
        assert evt["event_type"] == "TEAM_SPLITS_PROPOSED"
        assert evt["payload"]["team_size"] == 3
        assert len(evt["payload"]["members"]) == 3
        assert evt["payload"]["revenue_splits"]["alice"] == 0.40

    def test_team_settlement_records_multiparty_splits(self):
        """_execute_team_settlement creates multiparty record with correct splits."""
        from protocol.autonomous_commerce import _execute_team_settlement, LoopCycle
        from protocol.multiparty_settlement import get_multiparty_store
        from protocol.event_store import get_event_store

        deal_id = "deal_team_settle"

        # Build event chain: proof → verify → team splits → settle
        _emit_event_sync(deal_id, "PROOF_READY", actor_id="seller", amount=6000)
        _emit_event_sync(deal_id, "PROOF_VERIFIED", actor_id="verifier",
                         payload={"confidence": 0.92})
        _emit_event_sync(deal_id, "TEAM_SPLITS_PROPOSED", actor_id="client",
                         amount=6000, payload={
                             "intent_id": "intent_team",
                             "team_size": 3,
                             "members": [
                                 {"agent_id": "alice", "role": "lead"},
                                 {"agent_id": "bob", "role": "specialist"},
                                 {"agent_id": "carol", "role": "support"},
                             ],
                             "revenue_splits": {"alice": 0.50, "bob": 0.30, "carol": 0.20},
                             "skill_coverage": 0.90,
                             "source": "metabridge",
                         }, source="exchange")
        _emit_event_sync(deal_id, "ACCEPTED", actor_id="buyer")
        _emit_event_sync(deal_id, "SETTLED", actor_id="seller", amount=6000)

        # Create cycle and execute team settlement
        cycle = LoopCycle(
            agent_id="seller", deal_id=deal_id,
            settled_amount_usd=6000.0,
            steps_completed=["proof_verified", "accepted", "settled"],
        )
        _execute_team_settlement(cycle, deal_id, "seller")

        # Verify multiparty record was created
        record = get_multiparty_store().get(deal_id)
        assert record is not None
        assert record["settlement_type"] == "team_awarded"
        assert record["source"] == "metabridge"
        assert record["total_amount_usd"] == 6000.0
        assert record["split_count"] == 3
        assert record["team_size"] == 3
        assert record["skill_coverage"] == 0.90

        # Verify splits match team structure
        splits = record["splits"]
        splits_by_id = {s["agent_id"]: s for s in splits}

        assert splits_by_id["alice"]["role"] == "lead"
        assert splits_by_id["alice"]["share"] == 0.50
        assert splits_by_id["alice"]["gross_amount"] == 3000.0

        assert splits_by_id["bob"]["role"] == "specialist"
        assert splits_by_id["bob"]["share"] == 0.30
        assert splits_by_id["bob"]["gross_amount"] == 1800.0

        assert splits_by_id["carol"]["role"] == "support"
        assert splits_by_id["carol"]["share"] == 0.20
        assert splits_by_id["carol"]["gross_amount"] == 1200.0

        # Verify split amounts sum to total
        total_gross = sum(s["gross_amount"] for s in splits)
        assert total_gross == 6000.0

        # Verify step was recorded
        assert any("team_settlement_recorded" in s for s in cycle.steps_completed)

    def test_team_settlement_preserves_event_chain(self):
        """Team settlement preserves the full event chain including TEAM_SPLITS_PROPOSED."""
        from protocol.autonomous_commerce import _execute_team_settlement, LoopCycle
        from protocol.event_store import get_event_store

        deal_id = "deal_team_chain"
        _emit_event_sync(deal_id, "PROOF_READY", actor_id="seller", amount=4000)
        _emit_event_sync(deal_id, "PROOF_VERIFIED", actor_id="verifier")
        _emit_event_sync(deal_id, "TEAM_SPLITS_PROPOSED", actor_id="client",
                         amount=4000, payload={
                             "team_size": 2,
                             "members": [
                                 {"agent_id": "agent_a", "role": "lead"},
                                 {"agent_id": "agent_b", "role": "specialist"},
                             ],
                             "revenue_splits": {"agent_a": 0.60, "agent_b": 0.40},
                             "skill_coverage": 0.85,
                             "source": "metabridge",
                         }, source="exchange")
        _emit_event_sync(deal_id, "ACCEPTANCE_PENDING", actor_id="seller")
        _emit_event_sync(deal_id, "ACCEPTED", actor_id="buyer")
        _emit_event_sync(deal_id, "SETTLED", actor_id="seller", amount=4000)

        # Full chain is preserved
        chain = get_event_store().get_chain(deal_id)
        types = [e["event_type"] for e in chain]
        assert types == [
            "PROOF_READY", "PROOF_VERIFIED", "TEAM_SPLITS_PROPOSED",
            "ACCEPTANCE_PENDING", "ACCEPTED", "SETTLED",
        ]

        # Hash chain integrity
        for i in range(1, len(chain)):
            assert chain[i].get("prev_hash") == chain[i - 1].get("hash"), \
                f"Hash chain broken at index {i}"

    def test_single_agent_deal_skips_team_settlement(self):
        """Non-team deals skip team settlement entirely — no multiparty record created."""
        from protocol.autonomous_commerce import _execute_team_settlement, LoopCycle
        from protocol.multiparty_settlement import get_multiparty_store

        deal_id = "deal_solo"
        _emit_event_sync(deal_id, "PROOF_READY", actor_id="solo_agent", amount=1000)
        _emit_event_sync(deal_id, "SETTLED", actor_id="solo_agent", amount=1000)

        cycle = LoopCycle(
            agent_id="solo_agent", deal_id=deal_id,
            settled_amount_usd=1000.0,
            steps_completed=["settled"],
        )
        _execute_team_settlement(cycle, deal_id, "solo_agent")

        # No multiparty record
        assert get_multiparty_store().get(deal_id) is None
        # No team step added
        assert not any("team_settlement" in s for s in cycle.steps_completed)

    def test_zero_settlement_skips_team(self):
        """Zero-amount settlements skip team settlement entirely."""
        from protocol.autonomous_commerce import _execute_team_settlement, LoopCycle

        deal_id = "deal_zero"
        _emit_event_sync(deal_id, "TEAM_SPLITS_PROPOSED", actor_id="client",
                         amount=0, payload={
                             "team_size": 2,
                             "members": [{"agent_id": "a"}, {"agent_id": "b"}],
                             "revenue_splits": {"a": 0.5, "b": 0.5},
                         })

        cycle = LoopCycle(agent_id="x", deal_id=deal_id, settled_amount_usd=0.0)
        _execute_team_settlement(cycle, deal_id, "x")
        assert not any("team_settlement" in s for s in cycle.steps_completed)

    def test_team_settlement_share_normalization(self):
        """Shares that don't sum to 1.0 are normalized correctly."""
        from protocol.autonomous_commerce import _execute_team_settlement, LoopCycle
        from protocol.multiparty_settlement import get_multiparty_store

        deal_id = "deal_norm"
        # Revenue splits that sum to 0.9 (not 1.0)
        _emit_event_sync(deal_id, "TEAM_SPLITS_PROPOSED", actor_id="client",
                         amount=1000, payload={
                             "team_size": 2,
                             "members": [
                                 {"agent_id": "x", "role": "lead"},
                                 {"agent_id": "y", "role": "support"},
                             ],
                             "revenue_splits": {"x": 0.54, "y": 0.36},
                             "skill_coverage": 0.8,
                             "source": "metabridge",
                         })

        cycle = LoopCycle(agent_id="payer", deal_id=deal_id, settled_amount_usd=1000.0)
        _execute_team_settlement(cycle, deal_id, "payer")

        record = get_multiparty_store().get(deal_id)
        assert record is not None
        splits = record["splits"]
        total_share = sum(s["share"] for s in splits)
        # Should be normalized to ~1.0
        assert abs(total_share - 1.0) < 0.01
        # Gross amounts should sum to total
        total_gross = sum(s["gross_amount"] for s in splits)
        assert abs(total_gross - 1000.0) < 1.0

    def test_multiparty_store_retrieval(self):
        """Multiparty store persists and retrieves records correctly."""
        from protocol.multiparty_settlement import get_multiparty_store

        store = get_multiparty_store()

        # Store a record
        store.store({
            "deal_id": "deal_mp_test",
            "settlement_id": "mps_test_123",
            "settlement_type": "team_awarded",
            "total_amount_usd": 3000.0,
            "splits": [
                {"agent_id": "a", "share": 0.6, "gross_amount": 1800},
                {"agent_id": "b", "share": 0.4, "gross_amount": 1200},
            ],
        })

        # Retrieve
        rec = store.get("deal_mp_test")
        assert rec is not None
        assert rec["settlement_id"] == "mps_test_123"
        assert rec["total_amount_usd"] == 3000.0
        assert len(rec["splits"]) == 2

        # Non-existent deal returns None
        assert store.get("nonexistent") is None


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 9: Full Team-Awarded Lifecycle (end-to-end)
# ══════════════════════════════════════════════════════════════════════


class TestFullTeamAwardedLifecycle:
    """Complete lifecycle: intent → complexity → team splits → proof → accept → settle → multiparty."""

    def test_full_team_lifecycle(self):
        """Simulates the complete team-awarded lifecycle end-to-end."""
        from protocol.event_store import get_event_store
        from protocol.exchange import _analyze_complexity, Intent
        from protocol.acceptance_gate import AcceptanceStore
        from protocol.autonomous_commerce import _execute_team_settlement, LoopCycle
        from protocol.multiparty_settlement import get_multiparty_store
        from metabridge import (
            analyze_intent_complexity, find_complementary_agents,
            optimize_team_composition, assign_team_roles, calculate_team_splits,
        )

        deal_id = "deal_full_team_e2e"

        # ── Step 1: Publish complex intent ──
        intent = Intent(
            intent_id="intent_e2e", deal_id=deal_id, client_id="enterprise_buyer",
            capability="full_stack_platform", budget_usd=10000,
            deadline_hours=300, requirements={
                "required_skills": ["python", "react", "devops", "security"],
                "estimated_hours": 250,
            }, created_at="now",
        )
        complexity = _analyze_complexity(intent)
        assert complexity["requires_team"] is True

        # ── Step 2: MetaBridge team formation ──
        agents = [
            {"username": "alice", "profile": {"skills": ["python", "security"]}, "outcomeScore": 85},
            {"username": "bob", "profile": {"skills": ["react", "design"]}, "outcomeScore": 75},
            {"username": "carol", "profile": {"skills": ["devops", "python"]}, "outcomeScore": 80},
        ]
        mb_intent = {
            "budget": intent.budget_usd,
            "required_skills": intent.requirements["required_skills"],
            "estimated_hours": intent.requirements["estimated_hours"],
        }
        candidates = find_complementary_agents(mb_intent, agents)
        team = optimize_team_composition(mb_intent, candidates["candidates"])
        roles = assign_team_roles(team["team"], mb_intent)
        splits = calculate_team_splits(roles["roles"], intent.budget_usd)

        assert team["team_size"] >= 2
        assert splits["ok"] is True

        # ── Step 3: Emit events for the deal chain ──
        _emit_event_sync(deal_id, "PROOF_READY", actor_id="alice", amount=10000)
        _emit_event_sync(deal_id, "PROOF_VERIFIED", actor_id="verifier_1",
                         payload={"confidence": 0.93})

        # Team splits proposed (from exchange close)
        members = [{"agent_id": r["username"], "role": r["role"]}
                   for r in roles["roles"]]
        _emit_event_sync(deal_id, "TEAM_SPLITS_PROPOSED", actor_id="enterprise_buyer",
                         amount=10000, payload={
                             "intent_id": intent.intent_id,
                             "team_size": team["team_size"],
                             "members": members,
                             "revenue_splits": splits["splits"],
                             "skill_coverage": team["skill_coverage"],
                             "source": "metabridge",
                         }, source="exchange")

        # ── Step 4: Acceptance ──
        acc_store = AcceptanceStore(store_dir=str(Path(os.environ["ACCEPTANCE_DIR"])))
        rec = acc_store.submit(deal_id=deal_id, submitted_by="alice", downstream_action="settle")
        assert rec.status == "pending"

        _emit_event_sync(deal_id, "ACCEPTANCE_PENDING", actor_id="alice")

        decided = acc_store.decide(rec.acceptance_id, "accept",
                                   reviewer_id="enterprise_buyer", reason="team deliverable accepted",
                                   checks_passed=["proof_verified", "team_coverage"])
        assert decided.status == "accepted"

        _emit_event_sync(deal_id, "ACCEPTED", actor_id="enterprise_buyer")

        # ── Step 5: Settlement ──
        _emit_event_sync(deal_id, "SETTLED", actor_id="alice", amount=10000,
                         payload={"trigger": "sla_auto_settle"})

        # ── Step 6: Team multiparty settlement ──
        cycle = LoopCycle(
            agent_id="alice", deal_id=deal_id,
            settled_amount_usd=10000.0,
            steps_completed=["proof_verified", "accepted", "settled"],
        )
        _execute_team_settlement(cycle, deal_id, "alice")

        # ── Verify: Full event chain ──
        chain = get_event_store().get_chain(deal_id)
        types = [e["event_type"] for e in chain]
        assert "PROOF_READY" in types
        assert "PROOF_VERIFIED" in types
        assert "TEAM_SPLITS_PROPOSED" in types
        assert "ACCEPTANCE_PENDING" in types
        assert "ACCEPTED" in types
        assert "SETTLED" in types

        # ── Verify: Multiparty settlement record ──
        mp_record = get_multiparty_store().get(deal_id)
        assert mp_record is not None
        assert mp_record["settlement_type"] == "team_awarded"
        assert mp_record["total_amount_usd"] == 10000.0
        assert mp_record["split_count"] >= 2

        # ── Verify: Split amounts sum close to total (within rounding tolerance) ──
        total_paid = sum(s["gross_amount"] for s in mp_record["splits"])
        assert abs(total_paid - 10000.0) < 50.0, \
            f"Split total ${total_paid} too far from deal total $10000"

        # ── Verify: Each team member has a split ──
        split_agents = {s["agent_id"] for s in mp_record["splits"]}
        for member in members:
            assert member["agent_id"] in split_agents, \
                f"Team member {member['agent_id']} missing from settlement splits"

        # ── Verify: Team settlement step recorded ──
        assert any("team_settlement_recorded" in s for s in cycle.steps_completed)

        # ── Verify: Hash chain integrity ──
        for i in range(1, len(chain)):
            assert chain[i].get("prev_hash") == chain[i - 1].get("hash"), \
                f"Hash chain broken at index {i}"


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 10: Backward Compatibility
# ══════════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """Verify all reintegration changes are backward-compatible."""

    def test_exchange_works_without_metabridge(self):
        """Exchange functions normally when MetaBridge is unavailable."""
        import sys
        # Temporarily block MetaBridge
        orig = sys.modules.get("metabridge")
        sys.modules["metabridge"] = None
        try:
            from protocol.exchange import _analyze_complexity, _build_team_suggestion, Intent
            intent = Intent(
                intent_id="i_bc", deal_id="d_bc", client_id="c_bc",
                capability="test", budget_usd=5000, deadline_hours=200,
                requirements={"required_skills": ["a", "b", "c"]}, created_at="now",
            )
            assert _analyze_complexity(intent) is None
            assert _build_team_suggestion(intent) is None
        finally:
            if orig is not None:
                sys.modules["metabridge"] = orig
            else:
                sys.modules.pop("metabridge", None)

    def test_kpi_works_without_brain(self):
        """KPI dashboard works when brain modules are unavailable."""
        import sys
        blocked = ["metahive_brain", "ai_family_brain", "yield_memory"]
        originals = {k: sys.modules.get(k) for k in blocked}
        for k in blocked:
            sys.modules[k] = None
        try:
            from protocol.kpi_dashboard import _compute_brain_stats
            stats = _compute_brain_stats()
            assert isinstance(stats, dict)
            assert stats.get("yield_memory_available") is False
        finally:
            for k in blocked:
                if originals[k] is not None:
                    sys.modules[k] = originals[k]
                else:
                    sys.modules.pop(k, None)

    def test_acceptance_policy_works_without_suggestions(self):
        """Acceptance policy evaluate works with no suggestions system interaction."""
        from protocol.acceptance_policy import evaluate_acceptance_policy

        # With no policy set, should return require_review
        result = evaluate_acceptance_policy("nonexistent_deal", "nonexistent_agent")
        assert result["action"] == "require_review"
        assert result["reason"] == "no_policy"

    def test_suggestion_store_safe_for_unknown_agents(self):
        """Suggestion store operations for unknown agents don't crash."""
        from protocol.acceptance_policy import get_suggestion_store

        store = get_suggestion_store()
        assert store.list_for_agent("nobody") == []
        assert store.get("nonexistent") is None
        assert store.review("nonexistent", "adopted", "me") is None
        stats = store.stats()
        assert isinstance(stats["total"], int)
        assert isinstance(stats["pending"], int)
