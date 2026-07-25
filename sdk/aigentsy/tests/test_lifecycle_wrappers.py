"""Pass 30-Z-A — thin SDK wrappers for the existing OUTCOME_RECONCILED (simple
X-API-Key) route and the owner-scoped Settlement Memory projection, plus the
canonical joined-lifecycle example.

These are SDK COMPOSITION over existing runtime contracts — no new authority,
route, event, schema, store, or client. Network-free: a FakeTransport captures
the exact path/method/body/params the wrappers send.
"""
from __future__ import annotations

import pathlib

import pytest

from aigentsy.client import AiGentsyClient


class _Capture(AiGentsyClient):
    """Real client; captures transport calls instead of hitting the network."""
    def __init__(self, get_return=None, post_return=None):
        super().__init__(base_url="http://t.local", api_key="a2a_key")
        self.calls = []
        self._get_return = get_return if get_return is not None else {"ok": True, "deals": [], "next_cursor": None}
        self._post_return = post_return if post_return is not None else {"ok": True, "event_type": "OUTCOME_RECONCILED"}

    def _post(self, path, body=None, auth=False):
        self.calls.append(("POST", path, body, auth))
        return self._post_return

    def _get(self, path, params=None, auth=False):
        self.calls.append(("GET", path, params, auth))
        return self._get_return


# ── reconcile_outcome wrapper (1-6) ──────────────────────────────────────────

def test_reconcile_uses_exact_route_method_and_auth():
    c = _Capture()
    c.reconcile_outcome(deal_id="d1", reconciliation_status="matched",
                        expected_outcome_hash="e", observed_outcome_hash="o",
                        evidence_hash="ev", prior_authorization_event_id="evt1")
    m, path, body, auth = c.calls[0]
    assert m == "POST" and path == "/protocol/outcome-reconciliation" and auth is True


def test_reconcile_serialization_matches_runtime_contract():
    c = _Capture()
    c.reconcile_outcome(deal_id="d1", reconciliation_status="mismatched",
                        expected_outcome_hash="e", observed_outcome_hash="o",
                        evidence_hash="ev", prior_authorization_event_id="evt1",
                        readback_source="ci", mismatch_reason="drift")
    _, _, body, _ = c.calls[0]
    for k in ("deal_id", "reconciliation_status", "expected_outcome_hash",
              "observed_outcome_hash", "evidence_hash", "prior_authorization_event_id"):
        assert k in body
    assert body["reconciliation_status"] == "mismatched" and body["mismatch_reason"] == "drift"


def test_reconcile_auth_headers_inherited_from_client():
    c = _Capture()
    # the client transport is authenticated (auth=True passed); header logic is the
    # client's existing _headers() (X-API-Key) — the wrapper does not re-implement it.
    c.reconcile_outcome(deal_id="d", reconciliation_status="matched",
                        expected_outcome_hash="e", observed_outcome_hash="o",
                        evidence_hash="ev", prior_authorization_event_id="x")
    assert c.calls[0][3] is True  # auth=True → client attaches X-API-Key


def test_reconcile_invalid_status_preserves_validation():
    c = _Capture()
    with pytest.raises(ValueError) as ei:
        c.reconcile_outcome(deal_id="d", reconciliation_status="bogus",
                            expected_outcome_hash="e", observed_outcome_hash="o",
                            evidence_hash="ev", prior_authorization_event_id="x")
    assert "reconciliation_status" in str(ei.value)
    assert c.calls == []  # no request sent on invalid input


def test_reconcile_response_exposed_accurately():
    c = _Capture(post_return={"ok": True, "event_type": "OUTCOME_RECONCILED",
                              "deal_id": "d1", "event_id": "evt_r"})
    r = c.reconcile_outcome(deal_id="d1", reconciliation_status="matched",
                            expected_outcome_hash="e", observed_outcome_hash="o",
                            evidence_hash="ev", prior_authorization_event_id="x")
    assert r["event_type"] == "OUTCOME_RECONCILED" and r["event_id"] == "evt_r"


def test_reconcile_no_keypair_and_no_money_fields():
    import inspect
    sig = inspect.signature(AiGentsyClient.reconcile_outcome)
    params = set(sig.parameters)
    assert "keypair" not in params and "amount" not in params and "currency" not in params


# ── get_settlement_memory wrapper (7-13) ─────────────────────────────────────

def test_memory_uses_exact_route_method_and_auth():
    c = _Capture()
    c.get_settlement_memory()
    m, path, params, auth = c.calls[0]
    assert m == "GET" and path == "/protocol/settlement-memory" and auth is True


def test_memory_owner_auth_inherited():
    c = _Capture()
    c.get_settlement_memory()
    assert c.calls[0][3] is True  # auth=True → X-API-Key owner scope, server-derived


def test_memory_limit_and_cursor_serialize():
    c = _Capture()
    c.get_settlement_memory(limit=25, cursor="abc")
    _, _, params, _ = c.calls[0]
    assert params == {"limit": 25, "cursor": "abc"}


def test_memory_omits_none_params():
    c = _Capture()
    c.get_settlement_memory()
    _, _, params, _ = c.calls[0]
    assert params == {}  # no None limit/cursor leaked into the query


def test_memory_response_and_cursor_exposed():
    c = _Capture(get_return={"ok": True, "deals": [{"deal_id": "d1"}], "next_cursor": "next"})
    r = c.get_settlement_memory(limit=10)
    assert r["deals"][0]["deal_id"] == "d1" and r["next_cursor"] == "next"


def test_memory_no_deal_id_filter_invented():
    # the runtime route is owner-scoped by key with only limit+cursor; the wrapper
    # must NOT invent a deal_id/agent_id query the route does not support.
    import inspect
    params = set(inspect.signature(AiGentsyClient.get_settlement_memory).parameters)
    assert params == {"self", "limit", "cursor"}


# ── no-duplication / non-custody (14-16, 29) ─────────────────────────────────

def test_wrappers_use_existing_transport_not_new_client():
    # AST-based: wrappers call the existing self._post/self._get transport and
    # introduce no second HTTP client. (Docstrings may say "no cache/store" — a
    # negation — so scan code identifiers, not raw source.)
    import ast, inspect
    calls = set()
    for fn in (AiGentsyClient.reconcile_outcome, AiGentsyClient.get_settlement_memory):
        for n in ast.walk(ast.parse(inspect.getsource(fn).lstrip())):
            if isinstance(n, ast.Attribute):
                calls.add(n.attr)
            if isinstance(n, ast.Name):
                calls.add(n.id)
    assert "_post" in calls or "_get" in calls          # reuses existing transport
    assert "Client" not in calls and "requests" not in calls  # no second HTTP client


def test_public_exports_unchanged_compatible():
    import aigentsy
    for sym in ("AiGentsyClient", "gate_and_prove", "GateResult"):
        assert hasattr(aigentsy, sym)


# ── canonical example (17-28) ────────────────────────────────────────────────

def _load_example():
    import importlib.util
    root = pathlib.Path(__file__).resolve().parents[1]
    ex = root / "examples" / "canonical_consequence_lifecycle.py"
    spec = importlib.util.spec_from_file_location("canon_lifecycle", ex)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, ex


def test_example_imports_real_sdk_no_raw_http_records_signed_outcome():
    import ast
    mod, ex = _load_example()
    src = ex.read_text()
    tree = ast.parse(src)
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            imported.add(n.module or "")
            for a in n.names:
                imported.add(a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                imported.add(a.name)
    assert {"AiGentsyClient", "gate_and_prove"} <= imported
    # canonical lifecycle: the example MUST demonstrate the signed OutcomeReceipt
    # stage (record_signed_outcome) as well as reconciliation + memory.
    called = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for stage in ("record_signed_outcome", "reconcile_outcome", "get_settlement_memory"):
        assert stage in called, f"example must demonstrate {stage}"
    # no raw HTTP client, no FABRICATED payment (currency/payout/provider). amount is
    # allowed ONLY as the honest zero for a non-payment outcome — asserted below.
    idents = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            idents.add(n.id.lower())
        elif isinstance(n, ast.Attribute):
            idents.add(n.attr.lower())
    for banned in ("stripe", "payout", "paymentintent", "currency",
                   "requests", "subprocess", "socket"):
        assert banned not in idents, f"example must not use {banned}"


def test_example_outcome_receipt_is_honest_non_payment():
    # the signed OutcomeReceipt in the example must carry amount=0.0 and payer_id=""
    # — no fabricated money value, no invented payer/currency/provider.
    import ast
    _, ex = _load_example()
    tree = ast.parse(ex.read_text())
    receipt_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "record_signed_outcome"
    ]
    assert receipt_calls, "example must call record_signed_outcome"
    kw = {k.arg: k.value for k in receipt_calls[0].keywords}
    assert isinstance(kw.get("amount"), ast.Constant) and kw["amount"].value in (0, 0.0)
    assert isinstance(kw.get("payer_id"), ast.Constant) and kw["payer_id"].value == ""
    # intent is the consequence-neutral default, not a payment-specific intent.
    assert isinstance(kw.get("intent"), ast.Constant) and kw["intent"].value == "authorized_consequence"


def test_example_runs_offline_both_branches_and_chain(capsys):
    mod, _ = _load_example()
    mod.main()
    out = capsys.readouterr().out.lower()
    assert "accepted + verified" in out and "rejected / blocked" in out
    assert "callback executed  : true" in out and "callback executed  : false" in out
    # accepted branch: signed OutcomeReceipt → reconciliation → memory → continuous chain
    assert "outcome receipt" in out and "outcome_recorded" in out
    assert "amount=0.0" in out            # honest non-payment OutcomeReceipt
    assert "outcome_reconciled" in out and "settlement memory" in out
    assert "chain continuous   : true" in out
    # blocked branch does not reconcile
    assert "no consequence occurred" in out


def test_example_callback_result_not_in_pre_execution_proof():
    # the example's proof bundle (export_run) has no callback result embedded.
    mod, _ = _load_example()
    c = mod._DemoClient("accepted", "allowed")
    bundle = c.export_run("r")
    assert "released" not in repr(bundle)
