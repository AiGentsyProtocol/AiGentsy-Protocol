"""Pass 82J — Tests for the aigentsy_inference_evaluate MCP tool.

Mirrors the FakeRichClient + monkeypatch fixture pattern used by
``aigentsy-ame-runtime/tests/test_mcp_acceptance_tools.py`` so the tool
is exercised without ever touching the live runtime.

Coverage:
  - Tool is registered with FastMCP (smoke test count gate already
    enforces the 14-tool floor; this file adds shape assertions).
  - Required inputs validated (raw_output / prompt / policy / consequence /
    api_key).
  - intended_action is accepted as an optional param.
  - intended_action is folded into consequence["intended_action"] before
    being POSTed.
  - The client posts to ``/acceptance-runtime/evaluate``.
  - The sanitized return envelope carries decision / consequence_state /
    policy_compliance / evidence_completeness / export_path / labels /
    claim_boundary.
  - api_key is NEVER echoed back in the response.
  - The tool does NOT invoke any provider adapter or benchmark route
    (verified by call-log inspection of the fake client).
  - Failure path (HTTPStatusError + generic Exception) returns a
    sanitized error envelope rather than raising.
"""
from __future__ import annotations

import importlib
import inspect
import json
from typing import Any, Dict, List

import pytest


# ── Fake client ──────────────────────────────────────────────────────


class FakeClient:
    """Stand-in for ``aigentsy_mcp.client.AiGentsyClient``.

    Captures every call into ``self.calls`` so tests can assert on what
    the MCP tool sent without hitting the network. Each fake instance
    holds the ``api_key`` it was constructed with so tests can verify
    that the key flows through (and never appears in the tool response).
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        canned_result: Dict[str, Any] = None,
        canned_exception: Exception = None,
    ):
        self._base = base_url
        self._api_key = api_key
        self.calls: List[Dict[str, Any]] = []
        self._canned_result = canned_result or {
            "ok": True,
            "run_id": "infer_FAKE0123456789ab",
            "deal_id": "infer_deal_infer_FAKE0123456789ab",
            "decision": "accepted",
            "consequence_state": "allowed",
            "reason": "all required evidence present",
            "policy_compliance": 1.0,
            "evidence_completeness": 1.0,
            "escalation_route": None,
            "retry_remaining": 0,
            "hoverstack": {"measured": False, "reuse_kind": "none"},
            "decision_envelope_ref": None,
            "attestation_class": "platform_attested",
            "spec_version": "2.0.0",
            "events_emitted": 4,
        }
        self._canned_exception = canned_exception

    def evaluate_inference(self, **kwargs):
        self.calls.append({"endpoint": "/acceptance-runtime/evaluate", "body": kwargs})
        if self._canned_exception is not None:
            raise self._canned_exception
        return dict(self._canned_result)

    # Catch any attempt by the tool to invoke other client methods —
    # if 82J ever drifts and starts calling a benchmark/provider path
    # by accident, these will record the call and the test will fail.
    def __getattr__(self, name):
        # Only triggered for attrs NOT defined above. Record any other
        # method invocation as a forbidden call.
        def _forbidden(*args, **kwargs):
            self.calls.append({"forbidden_method": name, "args": args, "kwargs": kwargs})
            return None
        return _forbidden


@pytest.fixture
def install_fake(monkeypatch):
    """Patch ``aigentsy_mcp.server._client`` to return a FakeClient.

    Yields a callable ``install(canned_result=..., canned_exception=...)``
    that returns the FakeClient instance for assertion access. Tests
    typically call ``fc = install(...)`` then assert on ``fc.calls``.
    """
    mod = importlib.import_module("aigentsy_mcp.server")
    holder: Dict[str, FakeClient] = {}

    def install(canned_result: Dict[str, Any] = None, canned_exception: Exception = None):
        def _make_client(api_key: str = ""):
            fc = FakeClient(
                base_url="https://aigentsy-ame-runtime.onrender.com",
                api_key=api_key,
                canned_result=canned_result,
                canned_exception=canned_exception,
            )
            holder["fc"] = fc
            return fc

        monkeypatch.setattr(mod, "_client", _make_client)
        return holder

    yield install


def _server():
    return importlib.import_module("aigentsy_mcp.server")


# ── A. Registration ──────────────────────────────────────────────────


def test_A1_tool_is_registered_on_server_module():
    mod = _server()
    assert hasattr(mod, "aigentsy_inference_evaluate"), \
        "aigentsy_inference_evaluate is not exported from aigentsy_mcp.server"
    fn = mod.aigentsy_inference_evaluate
    assert callable(fn)


def test_A2_tool_signature_has_intended_action():
    mod = _server()
    sig = inspect.signature(mod.aigentsy_inference_evaluate)
    params = list(sig.parameters.keys())
    # Required positional
    for required in ("prompt", "raw_output", "policy", "consequence", "api_key"):
        assert required in params, f"missing required param {required!r}"
    # Optional including intended_action (Pass 82J)
    for optional in ("required_evidence", "risk_tier", "model_metadata", "expected_decision", "intended_action"):
        assert optional in params, f"missing optional param {optional!r}"


def test_A3_tool_returns_json_string():
    """Docstring contract: MCP tool returns a JSON string."""
    mod = _server()
    sig = inspect.signature(mod.aigentsy_inference_evaluate)
    assert sig.return_annotation is str, "tool must annotate -> str (FastMCP requirement)"


# ── B. Input validation ──────────────────────────────────────────────


def test_B1_prompt_required(install_fake):
    install_fake()
    mod = _server()
    with pytest.raises(ValueError, match="prompt"):
        mod.aigentsy_inference_evaluate(
            prompt="",
            raw_output="approve",
            policy=json.dumps({"policy_id": "pol_t"}),
            consequence=json.dumps({"kind": "payout"}),
            api_key="a2a_test_key",
        )


def test_B2_raw_output_required(install_fake):
    install_fake()
    mod = _server()
    with pytest.raises(ValueError, match="raw_output"):
        mod.aigentsy_inference_evaluate(
            prompt="approve invoice X",
            raw_output="",
            policy=json.dumps({"policy_id": "pol_t"}),
            consequence=json.dumps({"kind": "payout"}),
            api_key="a2a_test_key",
        )


def test_B3_policy_required(install_fake):
    install_fake()
    mod = _server()
    with pytest.raises(ValueError, match="policy"):
        mod.aigentsy_inference_evaluate(
            prompt="approve invoice X",
            raw_output="approve",
            policy="",
            consequence=json.dumps({"kind": "payout"}),
            api_key="a2a_test_key",
        )


def test_B4_consequence_required(install_fake):
    install_fake()
    mod = _server()
    with pytest.raises(ValueError, match="consequence"):
        mod.aigentsy_inference_evaluate(
            prompt="approve invoice X",
            raw_output="approve",
            policy=json.dumps({"policy_id": "pol_t"}),
            consequence="",
            api_key="a2a_test_key",
        )


def test_B5_api_key_required(install_fake):
    install_fake()
    mod = _server()
    with pytest.raises(ValueError, match="api_key"):
        mod.aigentsy_inference_evaluate(
            prompt="approve invoice X",
            raw_output="approve",
            policy=json.dumps({"policy_id": "pol_t"}),
            consequence=json.dumps({"kind": "payout"}),
            api_key="",
        )


def test_B6_malformed_policy_json_raises_value_error(install_fake):
    install_fake()
    mod = _server()
    with pytest.raises(ValueError, match="policy must be a JSON object string"):
        mod.aigentsy_inference_evaluate(
            prompt="approve invoice X",
            raw_output="approve",
            policy="not-json{",
            consequence=json.dumps({"kind": "payout"}),
            api_key="a2a_test_key",
        )


# ── C. Happy path + intended_action folding ──────────────────────────


def test_C1_happy_path_returns_sanitized_envelope(install_fake):
    fc_holder = install_fake()
    mod = _server()
    out_json = mod.aigentsy_inference_evaluate(
        prompt="approve invoice INV-001 from ACME for $100",
        raw_output="approve. vendor authorized.",
        policy=json.dumps({"policy_id": "pol_payable_v3", "required_evidence": ["vendor_authorized"]}),
        consequence=json.dumps({"kind": "payout", "scope": "ACME / $100"}),
        api_key="a2a_real_key_12345abcdef",
        required_evidence=json.dumps({"vendor_authorized": True}),
        risk_tier="low",
        model_metadata=json.dumps({"name": "gpt-4o-mini", "provider": "openai"}),
    )
    out = json.loads(out_json)
    assert out["ok"] is True
    assert out["run_id"] == "infer_FAKE0123456789ab"
    assert out["deal_id"] == "infer_deal_infer_FAKE0123456789ab"
    assert out["decision"] == "accepted"
    assert out["consequence_state"] == "allowed"
    assert out["policy_compliance"] == 1.0
    assert out["evidence_completeness"] == 1.0
    assert out["spec_version"] == "2.0.0"
    assert out["attestation_class"] == "platform_attested"
    assert out["export_path"] == "/acceptance-runtime/runs/infer_FAKE0123456789ab/export"
    # Labels + claim boundary
    assert set(out["labels"]) == {
        "mcp_inference_evaluation",
        "mcp_consequence_middleware",
        "acceptance_runtime",
        "proofpack_export_available",
    }
    cb = out["claim_boundary"]
    assert cb == {
        "bring_any_model": True,
        "does_not_call_model_provider": True,
        "does_not_improve_model_intelligence": True,
        "does_not_guarantee_correctness": True,
        "governs_consequence": True,
    }


def test_C2_api_key_is_never_echoed_in_response(install_fake):
    install_fake()
    mod = _server()
    secret = "a2a_super_secret_key_DO_NOT_LEAK_xyz_1234567890"
    out_json = mod.aigentsy_inference_evaluate(
        prompt="approve invoice X",
        raw_output="approve",
        policy=json.dumps({"policy_id": "pol_t"}),
        consequence=json.dumps({"kind": "payout"}),
        api_key=secret,
    )
    # The literal secret must NOT appear anywhere in the response JSON.
    assert secret not in out_json, "api_key leaked into MCP tool response"


def test_C3_intended_action_passes_through_to_client_kwargs(install_fake):
    """The MCP tool passes intended_action as a kwarg to the client's
    evaluate_inference. The CLIENT (not the tool) folds it into
    consequence before POSTing — that's covered separately in
    ``test_C3b_client_folds_intended_action_into_consequence``.
    """
    fc_holder = install_fake()
    mod = _server()
    mod.aigentsy_inference_evaluate(
        prompt="Update CRM record for cust_2034",
        raw_output="Setting renewal_date = March 15, 2027.",
        policy=json.dumps({"policy_id": "pol_api_action_v1", "required_evidence": ["schema_valid_payload"]}),
        consequence=json.dumps({"kind": "api_call", "scope": "CRM /v1/customers/cust_2034 PATCH"}),
        api_key="a2a_test_key",
        intended_action="PATCH /v1/customers/cust_2034 with renewal_date=2027-03-15",
    )
    fc = fc_holder["fc"]
    assert len(fc.calls) == 1
    call = fc.calls[0]
    assert call["endpoint"] == "/acceptance-runtime/evaluate"
    body = call["body"]
    assert body["intended_action"] == \
        "PATCH /v1/customers/cust_2034 with renewal_date=2027-03-15"
    # The consequence kwarg the tool passed to the client preserves the
    # caller's original consequence dict verbatim — the CLIENT method does
    # the folding before sending to the wire.
    assert body["consequence"]["kind"] == "api_call"
    assert body["consequence"]["scope"] == "CRM /v1/customers/cust_2034 PATCH"


def test_C3b_client_folds_intended_action_into_consequence(monkeypatch):
    """The CLIENT method ``AiGentsyClient.evaluate_inference`` folds
    intended_action into the outgoing consequence dict before POSTing.

    This is the load-bearing additive behavior — verify it directly at
    the client layer so the test fails if the folding is removed.
    """
    from aigentsy_mcp.client import AiGentsyClient
    posted: List[Dict[str, Any]] = []

    def fake_post(self, path, body):
        posted.append({"path": path, "body": body})
        return {"ok": True, "run_id": "infer_FAKE", "deal_id": "infer_deal_FAKE",
                "decision": "accepted", "consequence_state": "allowed",
                "spec_version": "2.0.0", "attestation_class": "platform_attested"}

    monkeypatch.setattr(AiGentsyClient, "_post", fake_post)
    c = AiGentsyClient(base_url="https://example", api_key="a2a_test")
    c.evaluate_inference(
        prompt="x",
        raw_output="y",
        policy={"policy_id": "pol_api_v1"},
        consequence={"kind": "api_call", "scope": "CRM PATCH"},
        intended_action="PATCH /v1/customers/cust_2034",
    )
    assert len(posted) == 1
    assert posted[0]["path"] == "/acceptance-runtime/evaluate"
    sent_consequence = posted[0]["body"]["consequence"]
    # CRITICAL: intended_action is folded into the outgoing consequence
    # dict — additive, never overwriting kind/scope.
    assert sent_consequence["intended_action"] == "PATCH /v1/customers/cust_2034"
    assert sent_consequence["kind"] == "api_call"
    assert sent_consequence["scope"] == "CRM PATCH"


def test_C4_intended_action_omitted_keeps_consequence_untouched(monkeypatch):
    """Without intended_action, the client posts the consequence dict
    verbatim with no added keys (no payload drift)."""
    from aigentsy_mcp.client import AiGentsyClient
    posted: List[Dict[str, Any]] = []

    def fake_post(self, path, body):
        posted.append({"path": path, "body": body})
        return {"ok": True, "run_id": "infer_FAKE", "deal_id": "x",
                "decision": "accepted", "consequence_state": "allowed",
                "spec_version": "2.0.0", "attestation_class": "platform_attested"}

    monkeypatch.setattr(AiGentsyClient, "_post", fake_post)
    c = AiGentsyClient(base_url="https://example", api_key="a2a_test")
    c.evaluate_inference(
        prompt="x",
        raw_output="y",
        policy={"policy_id": "p"},
        consequence={"kind": "payout", "scope": "ACME / $100"},
    )
    sent_consequence = posted[0]["body"]["consequence"]
    assert "intended_action" not in sent_consequence
    assert sent_consequence == {"kind": "payout", "scope": "ACME / $100"}


def test_C5_intended_action_reflected_in_envelope_when_supplied(install_fake):
    install_fake()
    mod = _server()
    out = json.loads(mod.aigentsy_inference_evaluate(
        prompt="approve invoice X",
        raw_output="approve",
        policy=json.dumps({"policy_id": "pol_t"}),
        consequence=json.dumps({"kind": "payout"}),
        api_key="a2a_test_key",
        intended_action="ACH push $100 to ACME",
    ))
    assert out.get("intended_action") == "ACH push $100 to ACME"


def test_C6_client_posts_to_acceptance_runtime_evaluate(install_fake):
    fc_holder = install_fake()
    mod = _server()
    mod.aigentsy_inference_evaluate(
        prompt="x",
        raw_output="y",
        policy=json.dumps({"policy_id": "p"}),
        consequence=json.dumps({"kind": "k"}),
        api_key="a2a_test_key",
    )
    fc = fc_holder["fc"]
    assert fc.calls[0]["endpoint"] == "/acceptance-runtime/evaluate"


def test_C7_api_key_flows_into_client_construction(install_fake):
    fc_holder = install_fake()
    mod = _server()
    mod.aigentsy_inference_evaluate(
        prompt="x",
        raw_output="y",
        policy=json.dumps({"policy_id": "p"}),
        consequence=json.dumps({"kind": "k"}),
        api_key="a2a_specific_key_777",
    )
    # The fake client recorded the api_key it was constructed with.
    assert fc_holder["fc"]._api_key == "a2a_specific_key_777"


# ── D. No-provider / no-benchmark guarantee ──────────────────────────


def test_D1_no_forbidden_method_called_on_client(install_fake):
    """The MCP tool must NOT invoke any provider adapter or benchmark
    method on the client. Only ``evaluate_inference`` may be called."""
    fc_holder = install_fake()
    mod = _server()
    mod.aigentsy_inference_evaluate(
        prompt="x",
        raw_output="y",
        policy=json.dumps({"policy_id": "p"}),
        consequence=json.dumps({"kind": "k"}),
        api_key="a2a_test_key",
    )
    fc = fc_holder["fc"]
    # Every recorded call must be the evaluate endpoint; no "forbidden_method" wraps.
    for call in fc.calls:
        assert "forbidden_method" not in call, \
            f"MCP tool invoked forbidden client method: {call.get('forbidden_method')}"
        assert call["endpoint"] == "/acceptance-runtime/evaluate"


# ── E. Failure surfacing ─────────────────────────────────────────────


def test_E1_generic_exception_returns_sanitized_envelope(install_fake):
    install_fake(canned_exception=RuntimeError("network unreachable"))
    mod = _server()
    out = json.loads(mod.aigentsy_inference_evaluate(
        prompt="x",
        raw_output="y",
        policy=json.dumps({"policy_id": "p"}),
        consequence=json.dumps({"kind": "k"}),
        api_key="a2a_test_key",
    ))
    assert out["ok"] is False
    assert out["error_class"] == "RuntimeError"
    # Labels + claim boundary stay attached even in the error path.
    assert "mcp_inference_evaluation" in out["labels"]
    assert out["claim_boundary"]["governs_consequence"] is True


def test_E2_http_status_error_surfaces_status_code_and_body(install_fake):
    import httpx
    class _Resp:
        status_code = 422
        text = '{"detail":"validation failed: required_evidence must be dict"}'
        def json(self): return json.loads(self.text)
    err = httpx.HTTPStatusError("422 Unprocessable", request=None, response=_Resp())
    install_fake(canned_exception=err)
    mod = _server()
    out = json.loads(mod.aigentsy_inference_evaluate(
        prompt="x",
        raw_output="y",
        policy=json.dumps({"policy_id": "p"}),
        consequence=json.dumps({"kind": "k"}),
        api_key="a2a_test_key",
    ))
    assert out["ok"] is False
    assert out["error_class"] == "HTTPStatusError"
    assert out["status_code"] == 422
    assert out["response"]["detail"].startswith("validation failed")


def test_E3_failure_does_not_echo_api_key(install_fake):
    install_fake(canned_exception=RuntimeError("upstream offline"))
    mod = _server()
    secret = "a2a_SECRET_VALUE_must_not_appear_in_error_xyz"
    out_json = mod.aigentsy_inference_evaluate(
        prompt="x",
        raw_output="y",
        policy=json.dumps({"policy_id": "p"}),
        consequence=json.dumps({"kind": "k"}),
        api_key=secret,
    )
    assert secret not in out_json
