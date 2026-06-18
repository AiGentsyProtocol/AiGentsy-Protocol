# AiGentsy — MCP Consequence Middleware (Pass 82J)

**Date**: 2026-06-18
**Repo edited**: `aigentsy-protocol` (canonical SDK + MCP package)
**Scope**: single new MCP tool + 1 new client method + 1 smoke-test count bump + 1 new test file + 2 docs
**Runtime SHA**: unchanged at `23d0023` (Pass 82I)
**Hero-final SHA**: unchanged at `8dc9291` (Pass 82H FINAL)
**Posture**: no runtime change · no SDK SDK release · no PyPI / npm / package publish · no provider keys · no secrets · no provider calls · no benchmark calls · no new server · no new endpoint · no new bundle format · no verifier change

---

## 1. Executive summary

Pass 82J adds the **MCP consequence middleware** — a single new MCP tool, `aigentsy_inference_evaluate`, that wraps the existing live Acceptance Runtime endpoint `POST /acceptance-runtime/evaluate` (Pass 82G) and exposes it to any MCP-compatible host (Claude Desktop, Cursor, Cline, OpenAI Agents SDK, etc.).

> **"Bring any model. AiGentsy decides whether its output is allowed to become consequence."**

What ships:

- **1 new MCP tool** at `sdk/mcp/src/aigentsy_mcp/server.py` immediately after `aigentsy_reject`. Follows the existing `@mcp.tool()` decorator + `_require()` validation + `_client(api_key)` factory pattern verbatim.
- **1 new client method** `AiGentsyClient.evaluate_inference(...)` at `sdk/mcp/src/aigentsy_mcp/client.py:122+` that calls `self._post("/acceptance-runtime/evaluate", body)` via the existing `_post` helper. **`intended_action` is folded ADDITIVELY into the outgoing `consequence` payload as `consequence["intended_action"]`** — additive only, affects NEW evaluation events only.
- **1 new test file** at `sdk/mcp/tests/test_inference_evaluate_tool.py` (21 tests) that mirrors the `FakeRichClient + monkeypatch` pattern used by `aigentsy-ame-runtime/tests/test_mcp_acceptance_tools.py`.
- **1 smoke-test bump** at `sdk/mcp/tests/smoke_test.py`: expected tool count 13 → 14. Also synced the previously-mismatched `expected_tools` set (the existing test was referring to `aigentsy_acceptance_submit/decide/status` which never existed; corrected to match the actual `aigentsy_accept` / `aigentsy_reject` / `aigentsy_settlement_signal` names).
- **2 docs**: this report + `AIGENTSY_SPEC_3_PER_ACTOR_INFERENCE_BUNDLE_PLAN.md` (planning only).

**Allowed claim**: *"AiGentsy is the Consequence Layer for autonomous work — Recall what was proven, Accept what is allowed, Prove what happened, Verify the record, Settle only when consequence is authorized."*

**Forbidden claims held**:
- No "AiGentsy improves model intelligence" claim.
- No "AiGentsy guarantees correctness" claim.
- No "live GPT/Claude/Gemini benchmarking" claim (this tool does NOT call providers).
- No SDK/package publish.
- No new server, no new endpoint, no new ProofPack format.

---

## 2. Reuse audit summary

| Existing primitive | Reuse pattern in 82J |
|---|---|
| `mcp.server.fastmcp.FastMCP` instance `mcp` | `@mcp.tool()` decorator on new function — auto-discovery |
| `_require(name, value)` helper | Validates `prompt` / `raw_output` / `policy` / `consequence` / `api_key` |
| `_client(api_key)` factory | Constructs `AiGentsyClient` with the per-call key |
| `AiGentsyClient._post(path, body)` | Existing generic POST helper with `X-API-Key` header support |
| `AME_BASE` + `AME_API_KEY` env vars | Inherited from existing config (no new env vars) |
| `AiGentsyClient` constructor signature `(base_url, api_key)` | Reused verbatim by the new `evaluate_inference` method |
| 82G runtime endpoint `POST /acceptance-runtime/evaluate` | Single target endpoint; new client method just builds the body |
| 82G runtime endpoint `GET /acceptance-runtime/runs/{run_id}/export` | Surfaced as `export_path` in the tool envelope; the host LLM can follow it via the existing `aigentsy_export` tool or direct HTTP |
| Test fixture pattern `FakeRichClient + monkeypatch _make_rich_client` from `aigentsy-ame-runtime/tests/test_mcp_acceptance_tools.py` | Mirrored as `FakeClient + monkeypatch _client` for the new test file |

**Nothing was duplicated.** No new server. No new evaluator. No new endpoint. No new bundle format. No new auth surface.

---

## 3. New MCP tool — `aigentsy_inference_evaluate`

### Signature

```python
@mcp.tool()
def aigentsy_inference_evaluate(
    prompt: str,                       # required
    raw_output: str,                   # required
    policy: str,                       # required — JSON object string
    consequence: str,                  # required — JSON object string
    api_key: str,                      # required
    required_evidence: str = "",       # optional — JSON object string
    risk_tier: str = "medium",         # optional — low / medium / high
    model_metadata: str = "",          # optional — JSON object string
    expected_decision: str = "",       # optional — accepted / rejected / retry / escalated
    intended_action: str = "",         # optional — Pass 82J · folded into consequence
) -> str
```

JSON-string inputs (`policy` / `consequence` / `required_evidence` / `model_metadata`) match the MCP convention: FastMCP tool arguments are JSON-serializable primitives + strings, so structured inputs cross the wire as strings and the tool parses them inline with explicit `ValueError` on malformed JSON.

### Behavior

1. Validate every required input with `_require()` — raises `ValueError(f"{name} is required")` on empty / whitespace-only / `None`.
2. Parse the 4 JSON-string inputs (`policy`, `consequence`, `required_evidence`, `model_metadata`). Malformed JSON raises `ValueError(f"{name} must be a JSON object string: ...")`.
3. Construct an `AiGentsyClient` via the existing `_client(api_key)` factory.
4. Call `client.evaluate_inference(prompt, raw_output, policy, consequence, required_evidence, risk_tier, model_metadata, expected_decision, intended_action)`.
5. On success, return a sanitized JSON envelope (see §5).
6. On `httpx.HTTPStatusError`, return a structured error envelope with `status_code` + `response` body (no stack trace, no api_key, no env vars).
7. On any other `Exception`, return `{ok: false, error_class, safe_error, labels, claim_boundary}` — never echoes the api_key.

### Reuse posture

- Same `@mcp.tool()` decorator + docstring lead pattern as `aigentsy_accept` / `aigentsy_reject`.
- Same `_require()` validation.
- Same per-call `_client(api_key)` factory.
- Same honest failure surfacing (HTTPStatusError → JSON envelope) seen in `_decide_acceptance_via_mcp`.

---

## 4. New client method — `AiGentsyClient.evaluate_inference`

Location: `sdk/mcp/src/aigentsy_mcp/client.py`, immediately after `acceptance_status` (existing acceptance helpers).

```python
def evaluate_inference(
    self,
    prompt: str,
    raw_output: str,
    policy: Dict[str, Any],
    consequence: Optional[Dict[str, Any]] = None,
    required_evidence: Optional[Dict[str, bool]] = None,
    risk_tier: str = "medium",
    model_metadata: Optional[Dict[str, Any]] = None,
    expected_decision: Optional[str] = None,
    intended_action: str = "",
) -> Dict[str, Any]:
    """POST /acceptance-runtime/evaluate via the existing runtime."""
    cons = dict(consequence or {})
    if intended_action:
        cons["intended_action"] = intended_action
    body: Dict[str, Any] = {
        "prompt": prompt,
        "raw_output": raw_output,
        "policy": policy or {},
        "required_evidence": required_evidence or {},
        "consequence": cons,
        "risk_tier": risk_tier or "medium",
        "model_metadata": model_metadata or {},
    }
    if expected_decision:
        body["expected_decision"] = expected_decision
    return self._post("/acceptance-runtime/evaluate", body)
```

### `intended_action` semantics

- **Additive only.** When `intended_action` is supplied, it is folded into the outgoing `consequence` dict as `consequence["intended_action"]`. The original `kind` / `scope` / `amount_usd` keys are preserved verbatim.
- **Forward to the runtime as-is.** The runtime's `evaluate_inference()` already spreads the `consequence` dict into `INFERENCE_CONSEQUENCE_RECORDED.payload`, so `intended_action` lands in the payload of the **new** event with no runtime change required.
- **Does NOT alter pre-existing event hashes / bundle hashes.** `_hash_record` hashes the canonical 7-field projection of each individual event AT THE TIME IT IS EMITTED. New events emitted today carry their new payload key (`intended_action`); past events emitted yesterday do not. The verifier validates each event's own hash against its own payload — no cross-event drift.
- **Does NOT touch** `_hash_record` / `compute_bundle_hash_v1` / `canonical_event_for_signing` separators / verifier behavior / bundle format / signing keys.

---

## 5. Sanitized return envelope

On success, the MCP tool returns this JSON-string envelope:

```json
{
  "ok": true,
  "run_id": "infer_<hex16>",
  "deal_id": "infer_deal_infer_<hex16>",
  "decision": "accepted | rejected | retry | escalated",
  "consequence_state": "allowed | blocked | held",
  "reason": "...",
  "policy_compliance": 0.0,
  "evidence_completeness": 0.0,
  "escalation_route": null,
  "retry_remaining": 0,
  "hoverstack_reuse_kind": "policy_path | decision_template | evidence_shape | proofpack_pattern | none",
  "decision_envelope_ref": {"decision_id": "...", "decision": "...", "envelope_hash": "..."},
  "attestation_class": "platform_attested | attribution_only",
  "spec_version": "2.0.0",
  "export_path": "/acceptance-runtime/runs/<run_id>/export",
  "labels": [
    "mcp_inference_evaluation",
    "mcp_consequence_middleware",
    "acceptance_runtime",
    "proofpack_export_available"
  ],
  "claim_boundary": {
    "bring_any_model": true,
    "does_not_call_model_provider": true,
    "does_not_improve_model_intelligence": true,
    "does_not_guarantee_correctness": true,
    "governs_consequence": true
  },
  "intended_action": "<echoed when supplied>"
}
```

**Honesty markers**:
- `labels` carry the public taxonomy markers from the 82H Consequence Layer alignment.
- `claim_boundary` is structured so an automated host can refuse to misquote the tool's scope.
- `export_path` is the existing 82G route; no new export logic.

**Sanitization guarantees**:
- `api_key` NEVER appears in the response (verified by `test_C2_api_key_is_never_echoed_in_response` and `test_E3_failure_does_not_echo_api_key`).
- Env vars (`AME_BASE`, `AME_API_KEY`, `OPS_ADMIN_KEY`, `OPENAI_API_KEY`, etc.) NEVER appear in the response.
- Authorization headers NEVER appear.
- Provider keys NEVER appear.
- Raw stack traces NEVER appear (failures get `error_class` + truncated `safe_error`).

---

## 6. Evaluator endpoint reused

`POST /acceptance-runtime/evaluate` — live since Pass 82G commit `993d0af` at `https://aigentsy-ame-runtime.onrender.com`. **Verified live with HTTP 200 + `decision=accepted` + 4 events emitted under default env (no provider keys)** during the 82I deploy verification.

The MCP tool wraps this endpoint without changing it. No runtime change in 82J.

---

## 7. Export path behavior

Each successful evaluation returns an `export_path` like `/acceptance-runtime/runs/infer_<hex>/export`. This is the EXISTING 82G route. The MCP host can fetch the offline-verifiable bundle by:

1. Calling the path directly via HTTP (the host has the `api_key`).
2. Or calling the existing `aigentsy_export(deal_id, ...)` MCP tool with the returned `deal_id` (which the existing tool already supports).

**No new export wrapper. No new ProofPack format. No new signing.** The same 5-step CLI / browser verifier handles the bundle.

---

## 8. Tests run

```
$ PYTHONPATH=src python3 -m pytest tests/test_inference_evaluate_tool.py \
                              tests/smoke_test.py::test_imports \
                              tests/smoke_test.py::test_tool_count \
                              tests/smoke_test.py::test_fastmcp_signatures_valid -v --no-header
collected 24 items

test_A1_tool_is_registered_on_server_module                      PASSED
test_A2_tool_signature_has_intended_action                       PASSED
test_A3_tool_returns_json_string                                 PASSED
test_B1_prompt_required                                          PASSED
test_B2_raw_output_required                                      PASSED
test_B3_policy_required                                          PASSED
test_B4_consequence_required                                     PASSED
test_B5_api_key_required                                         PASSED
test_B6_malformed_policy_json_raises_value_error                 PASSED
test_C1_happy_path_returns_sanitized_envelope                    PASSED
test_C2_api_key_is_never_echoed_in_response                      PASSED
test_C3_intended_action_passes_through_to_client_kwargs          PASSED
test_C3b_client_folds_intended_action_into_consequence           PASSED
test_C4_intended_action_omitted_keeps_consequence_untouched      PASSED
test_C5_intended_action_reflected_in_envelope_when_supplied      PASSED
test_C6_client_posts_to_acceptance_runtime_evaluate              PASSED
test_C7_api_key_flows_into_client_construction                   PASSED
test_D1_no_forbidden_method_called_on_client                     PASSED
test_E1_generic_exception_returns_sanitized_envelope             PASSED
test_E2_http_status_error_surfaces_status_code_and_body          PASSED
test_E3_failure_does_not_echo_api_key                            PASSED
tests/smoke_test.py::test_imports                                PASSED
tests/smoke_test.py::test_tool_count                             PASSED
tests/smoke_test.py::test_fastmcp_signatures_valid               PASSED

============================== 24 passed in 0.49s ==============================
```

### Coverage map

| Section | Asserts |
|---|---|
| A — Registration | Tool exists on the module · signature has `intended_action` · returns `str` (FastMCP requirement) |
| B — Input validation | Each of `prompt` / `raw_output` / `policy` / `consequence` / `api_key` is required · malformed `policy` JSON raises a clean `ValueError` |
| C — Happy path | Sanitized envelope shape · `api_key` not echoed · `intended_action` passes through to the client · **client folds `intended_action` into outgoing consequence** · client posts to `/acceptance-runtime/evaluate` · `api_key` flows into client construction |
| D — Forbidden methods | The tool NEVER invokes any client method other than `evaluate_inference` (no provider adapter call, no benchmark call) |
| E — Failure surfacing | Generic exception → sanitized envelope with `error_class` + `safe_error` · `HTTPStatusError` → envelope with `status_code` + `response` body · `api_key` not echoed in any error path |

---

## 9. Docs created

- **This report** (`sdk/mcp/AIGENTSY_MCP_CONSEQUENCE_MIDDLEWARE_82J.md`).
- **Planning doc** (`sdk/mcp/AIGENTSY_SPEC_3_PER_ACTOR_INFERENCE_BUNDLE_PLAN.md`) — planning only; recommends actor_signatures sidecar keyed by existing event_hash as the safest first path.

---

## 10. Runtime mirror not touched

`/Users/wadepapas/aigentsy-ame-runtime/adapters/mcp_server.py` is the runtime-repo development mirror of the canonical SDK MCP server. Per the operator-locked scope decision, it was **not edited in 82J**.

If/when the mirror needs to be re-synced with this pass, the diff is contained to the same surgical region (after `aigentsy_reject`, before the settlement-signal advisory tool). That sync is a separate, mechanical pass — out of scope for 82J.

---

## 11. Hard constraints — VERIFIED held

| Constraint | Status |
|---|---|
| Do not touch `aigentsy-ame-runtime/adapters/mcp_server.py` | ✓ Untouched |
| Do not touch runtime `/acceptance-runtime/evaluate` | ✓ Unchanged |
| Do not touch runtime evaluator logic | ✓ Unchanged |
| Do not touch benchmark harness (82I) | ✓ Unchanged |
| Do not touch `_hash_record` | ✓ Unchanged |
| Do not touch `compute_bundle_hash_v1` | ✓ Unchanged |
| Do not touch canonical signing separators | ✓ Unchanged |
| Do not touch ProofPack export format | ✓ Unchanged |
| Do not touch verifier logic | ✓ Unchanged |
| Do not touch browser verifier | ✓ Unchanged |
| Do not touch CLI verifier | ✓ Unchanged |
| Do not rename routes / files / modules / endpoints | ✓ No renames |
| Do not publish PyPI / npm | ✓ No publish |
| Do not commit secrets | ✓ No secrets in diff |
| Do not invoke provider SDKs | ✓ No SDK imports added |
| Do not call providers | ✓ No provider call in tool path |
| Do not call benchmark harness | ✓ Verified by `test_D1` |

---

## 12. Files changed

| File | Change | LOC |
|---|---|---|
| `sdk/mcp/src/aigentsy_mcp/client.py` | + `evaluate_inference()` method | +42 / −0 |
| `sdk/mcp/src/aigentsy_mcp/server.py` | + `aigentsy_inference_evaluate` tool | +163 / −0 |
| `sdk/mcp/tests/smoke_test.py` | tool count 13 → 14; sync expected_tools to reality | +6 / −5 |
| `sdk/mcp/tests/test_inference_evaluate_tool.py` | NEW · 21 tests | +358 |
| `sdk/mcp/AIGENTSY_MCP_CONSEQUENCE_MIDDLEWARE_82J.md` | NEW · this report | ~360 |
| `sdk/mcp/AIGENTSY_SPEC_3_PER_ACTOR_INFERENCE_BUNDLE_PLAN.md` | NEW · planning only | ~250 |

**Runtime repo (aigentsy-ame-runtime): NOT TOUCHED in this commit.**

**No provider keys committed. No SDK SDK release. No PyPI / npm package publish.**

---

## 13. Recommended next pass

**82K — Stack-Wide Before/After Consequence Demo.**

Scope to plan:
- Side-by-side demo on the Vault or Playground showing one scenario WITHOUT the Consequence Layer and the SAME scenario WITH it — same prompt, same model output, same policy, two different consequence states.
- Reuses the existing 5 fixtures + 82J MCP tool path; no new runtime endpoint.
- Honest labels preserved: `bring_any_model=true`, `does_not_call_model_provider=true`, `does_not_improve_model_intelligence=true`.

---

*End of report.*
