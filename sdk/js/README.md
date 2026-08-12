# aigentsy

JavaScript SDK for [AiGentsy](https://aigentsy.com) — the acceptance gate
between autonomous work and real-world consequence, with portable ProofPacks
and offline verification.

**AiGentsy is the Consequence Layer for autonomous work.** Build your agent
anywhere. Before its output moves money or changes a system, route the
*proposed consequence* through mandate, evidence, policy acceptance, and exact
authorization. AiGentsy returns a portable ProofPack that verifies
independently; **your systems execute.**

AiGentsy does **not** custody your compute, credentials, artifacts, documents,
or funds, and does **not** independently prove real-world truth.

A consequence is any action with real effect — a deployment, a release, an API
call, a handoff, a procurement, an access change, a publication, a delivery, or
a payment. **Payout is one reference adapter, not the architecture.**
Settlement is the stage where value actually moves.

## Install

    npm install aigentsy

## What it does

- Create signed ProofPacks for consequential agent work
- Verify ProofPacks offline
- Submit work through explicit acceptance gates
- Coordinate settlement after verification and acceptance
- Work with Node.js 18+ and modern browsers
- Use zero runtime dependencies

## Why AiGentsy

Mandate before work. Evidence before acceptance. Acceptance before
consequence. Settlement only when value actually moves.

AiGentsy provides:

- ProofPack v2.0.0 for portable signed evidence
- Offline verification without relying on AiGentsy servers
- Acceptance-gated settlement coordination
- Ed25519 + HMAC signing
- RFC 6962 transparency log support
- Recall for reuse of prior attested work

## Recall

**Recall** is reuse of prior attested work. When an agent encounters work that
has already been attested by a ProofPack, Recall lets that prior evidence be
reused instead of redundantly recomputed. Reuse decisions are themselves
recorded and signed.

## Five live consequence-gate demos

AiGentsy is the acceptance gate between autonomous work and real-world consequence. Five live test-mode endpoints prove the same shape: proof verifies, acceptance fails, and downstream consequence stays held. The runtime emits a signed `REJECTED` (or held) event carrying a
`policy_snapshot` of **bounded public provenance** — `policy_hash`,
`rule_index`, `evaluation_action`, `evaluation_reason` — and, where
applicable, an embedded `adapter_evaluation`. Private rule bodies,
thresholds, evaluated inputs/context, failed conditions, and matched-rule
internals are **not** distributed in portable ProofPacks. Every held response returns `downstream_triggered: false` and a consequence-class-specific safety marker.

| Demo | Endpoint | Safety marker |
|------|----------|---------------|
| Payout Held | `POST /demo/payout-held/run` | `no_funds_moved` |
| Deployment Held | `POST /demo/deployment-held/run` | `no_deployment_triggered` |
| Handoff Held | `POST /demo/handoff-held/run` | `no_handoff_triggered` |
| API Action Held | `POST /demo/api-action-held/run` | `no_external_api_call_made` |
| Procurement Held | `POST /demo/procurement-held/run` | `no_purchase_order_created`, `no_vendor_commitment_made` |

These are test-mode only. `test_mode=true` is returned on every held response, alongside the safety marker shown above and `downstream_triggered=false`. Funds are not moved, deployments are not triggered, handoffs are not executed, external API calls are not made, purchase orders are not created, and vendor commitments are not made.

Run any of them directly with `fetch`:

```js
const r = await fetch(
  "https://aigentsy-ame-runtime.onrender.com/demo/payout-held/run",
  { method: "POST" }
);
const out = await r.json();
// out.consequence_state === "payout_held"
// out.downstream_triggered === false
// out.no_funds_moved === true
// out.test_mode === true
```

The Verified-but-Rejected scenario plus the five held scenarios above are also runnable in the browser at [aigentsy.com/playground](https://aigentsy.com/playground).

Wedge invariant: **mandate before work, evidence before acceptance, acceptance before consequence, settlement when value moves.**

## Related packages

- `aigentsy-verify` - standalone offline ProofPack verifier
- `aigentsy-langgraph` - LangGraph nodes for AiGentsy workflows

## Links

- Docs: https://aigentsy.com/integrations
- Protocol: https://github.com/AiGentsyProtocol/AiGentsy-Protocol

## License

Apache-2.0
