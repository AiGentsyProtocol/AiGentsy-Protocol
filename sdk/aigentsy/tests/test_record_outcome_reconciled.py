"""Pass 24B — SDK record_outcome_reconciled mirrors the signed-event pattern.

No network: send_signed_event is monkeypatched to capture the call. Proves the
method emits event_type=OUTCOME_RECONCILED with a hash-first payload, defaults
to hash_only redaction, validates the controlled vocabularies, and does not
remove any existing public method.
"""
import pytest

from aigentsy import AiGentsyClient


class _FakeKeypair:
    private_key_base64 = "AA=="  # never used — send_signed_event is patched


def _client(monkeypatch):
    c = AiGentsyClient("https://example.invalid", api_key="k")
    captured = {}

    def fake_send_signed_event(**kwargs):
        captured.update(kwargs)
        return {"event_type": kwargs["event_type"], "payload": kwargs["payload"],
                "actor_id": kwargs["actor_id"], "actor_signature": "sig"}

    monkeypatch.setattr(c, "send_signed_event", fake_send_signed_event)
    return c, captured


def _args(**over):
    base = dict(
        deal_id="deal_1",
        reconciler_id="reconciler_agent",
        key_id="key_1",
        keypair=_FakeKeypair(),
        expected_outcome_hash="e" * 64,
        observed_outcome_hash="o" * 64,
        reconciliation_status="matched",
        readback_source="system_of_record",
        readback_source_type="first_party",
        evidence_hash="v" * 64,
    )
    base.update(over)
    return base


def test_method_exists_and_delegates(monkeypatch):
    c, captured = _client(monkeypatch)
    assert callable(getattr(c, "record_outcome_reconciled", None))
    out = c.record_outcome_reconciled(**_args())
    assert captured["event_type"] == "OUTCOME_RECONCILED"
    assert captured["actor_id"] == "reconciler_agent"          # reconciler signs
    assert captured["intent"] == "post_action_reconciliation"
    assert out["event_type"] == "OUTCOME_RECONCILED"


def test_payload_is_hash_first_and_default_hash_only(monkeypatch):
    c, captured = _client(monkeypatch)
    c.record_outcome_reconciled(**_args())
    p = captured["payload"]
    assert p["evidence_redaction_status"] == "hash_only"        # DEFAULT
    assert p["expected_outcome_hash"] == "e" * 64
    assert p["observed_outcome_hash"] == "o" * 64
    assert p["reconciliation_status"] == "matched"
    # no raw payload fields
    assert "observed_outcome" not in p and "expected_outcome" not in p


@pytest.mark.parametrize("status", ["matched", "mismatched", "inconclusive", "unavailable"])
def test_valid_statuses(monkeypatch, status):
    c, captured = _client(monkeypatch)
    c.record_outcome_reconciled(**_args(reconciliation_status=status))
    assert captured["payload"]["reconciliation_status"] == status


def test_invalid_status_rejected(monkeypatch):
    c, _ = _client(monkeypatch)
    with pytest.raises(ValueError):
        c.record_outcome_reconciled(**_args(reconciliation_status="approved"))


def test_invalid_source_type_rejected(monkeypatch):
    c, _ = _client(monkeypatch)
    with pytest.raises(ValueError):
        c.record_outcome_reconciled(**_args(readback_source_type="magic"))


def test_full_payload_opt_in_not_default(monkeypatch):
    c, captured = _client(monkeypatch)
    # explicit opt-in is allowed but must be deliberate
    c.record_outcome_reconciled(**_args(evidence_redaction_status="full_payload_opt_in"))
    assert captured["payload"]["evidence_redaction_status"] == "full_payload_opt_in"
    # default call never yields full opt-in
    c2, cap2 = _client(monkeypatch)
    c2.record_outcome_reconciled(**_args())
    assert cap2["payload"]["evidence_redaction_status"] == "hash_only"


def test_existing_signed_outcome_method_preserved():
    # additive: the sibling method still exists
    assert callable(getattr(AiGentsyClient, "record_signed_outcome", None))
    assert callable(getattr(AiGentsyClient, "record_outcome_reconciled", None))
