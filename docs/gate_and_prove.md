# Gate and prove in one wrapper

`gate_and_prove` lets developers wrap an action so AiGentsy evaluates the gate, exports the ProofPack, verifies the evidence honestly, and executes **only if allowed**.

The atom:

> **gate → export ProofPack → verify honestly → execute only if allowed**

## Install

```bash
pip install aigentsy==1.15.0
```

## Quickstart

```python
from aigentsy import gate_and_prove

@gate_and_prove(action="contractor_payout")
def release_payment(donation_id):
    return f"disbursed {donation_id}"

r = release_payment("DON-4471", evidence={
    "credit_check_passed": True,
    "nonprofit_verified": True,
    "within_cap": True,
})

print(r.consequence_state)                   # allowed / blocked / held
print(r.verification["verified"])            # True/False from the offline verifier
print(r.verification["verification_level"])  # "full" (anchored) or "offline"
print(r.verification["checks_skipped"])      # e.g. ["merkle_inclusion","sth_signature","cross_reference"]
print(r.action_executed)                     # True only if allowed AND mandatory checks passed
```

## How it behaves

- **allowed** — the wrapped action executes, but only after mandatory verification (bundle hash + event chain) passes.
- **blocked** — the action does **not** execute; the proof is still returned.
- **held** — the action does **not** execute; the proof is still returned.
- **fail-closed** — errors, timeouts, or ambiguous decisions do **not** execute the action.
- **honest verification** — the SDK surfaces the verifier's actual level; skipped checks are surfaced, not hidden.

Whatever the decision, you get the `consequence_state`, a proof reference (`bundle_export_url`), and an honest `verification` summary in the returned `GateResult`. Only `allowed` + verified runs your function body.

## MCP

- **Package:** `aigentsy-mcp==1.4.0`
- **Tool:** `aigentsy_gate`
- **Requires:** `aigentsy>=1.15.0`

`aigentsy_gate` exposes the same gate/prove primitive to any MCP client. It calls the SDK's `gate_and_prove` and does **not** duplicate gate, proof, or verify logic. The tool gates and proves; it does not execute a consequential action by itself — the host system wires any execution deliberately on its side.

## A note on verification honesty

Some bundles are fully anchored, with all checks passing. Lightweight or pre-anchor bundles may show skipped Merkle / STH / cross-reference checks and a `pending_anchor` status. The SDK surfaces the verifier's **actual** level (`full` when anchored and all checks pass, otherwise `offline`) and lists exactly which checks were skipped — instead of printing a blanket pass. Always read `verification_level` and `checks_skipped` rather than assuming a clean result.

## What verification proves (and what it doesn't)

Offline verification proves the **integrity and provenance** of the exported ProofPack — bundle integrity, signing/provenance, event-chain consistency, and available anchoring checks. It does **not** prove real-world outcome quality, and it does not replace post-action reconciliation from the target system of record.

Pre-action authorization proof and post-action reconciliation answer different questions. The gate records whether the action was **allowed to run** before it touched the system. Read-back from the system of record confirms **what happened** after execution.

## Outcome reconciliation (an event on the same trail)

`OUTCOME_RECONCILED` is an additive event on the existing ProofPack trail — not a new layer and not a separate product. The gate records whether an action was **authorized before consequence**; outcome reconciliation records **what the system of record reported afterward**, qualified by the source and attestation strength of that read-back. Same trail, same ProofPack lineage, same settlement memory — no world-truth claim. A `matched` status is a statement about the supplied read-back evidence versus the approved intent (qualified by `readback_source_type`); it does not claim the external system is honest or that the world ended in the approved state.

## Where the public source lives

The public AiGentsy protocol, verifier, SDK, MCP package, examples, and this note live at <https://github.com/AiGentsyProtocol/AiGentsy-Protocol>. The hosted AME Runtime is the production service and is **not** required to verify an exported ProofPack — you can verify a bundle offline with the standalone `aigentsy-verify` package.
