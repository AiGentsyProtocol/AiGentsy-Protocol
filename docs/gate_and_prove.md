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
