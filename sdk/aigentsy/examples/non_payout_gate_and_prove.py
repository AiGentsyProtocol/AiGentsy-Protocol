"""AiGentsy — guard ANY enterprise consequence with `gate_and_prove` (non-payout).

Payment is one reference consequence, not the architecture. `gate_and_prove`
guards *any* enterprise-owned callback: the callback executes ONLY after the
declared action is accepted AND its ProofPack verifies. Here the consequence is a
deployment/release — no money, no Stripe, no settlement identity.

Canonical pattern (against a live runtime, pass a real client or base_url):

    from aigentsy import gate_and_prove

    result = gate_and_prove(
        action="deploy_release",
        evidence=evidence,
        run=enterprise_owned_callback,     # your function; runs only if allowed
        base_url="https://aigentsy-ame-runtime.onrender.com",
    )
    if result.action_executed:
        ...  # your callback ran, and result.proof_bundle verifies offline

TRUST BOUNDARY (honest):
  AiGentsy proves — the declared action, the submitted evidence, the Acceptance
  decision, the exported ProofPack, verification success, whether execution was
  permitted, and whether the callback was invoked.
  The enterprise owns — the callback implementation, the target system, callback
  credentials/runtime, the external side effect, and the callback's result. The
  callback runs in YOUR environment AFTER verification; its return value is NOT
  part of the pre-execution signed ProofPack. AiGentsy holds no funds, compute,
  documents, provider credentials, output artifacts, or keys.

This file runs OFFLINE (no network, no credentials) using a small in-example
demonstration acceptance client + stubbed verifier so you can see both branches:

    python examples/non_payout_gate_and_prove.py
"""
from __future__ import annotations

import sys
import types
from typing import Any, Dict

from aigentsy import gate_and_prove  # reuse the SDK primitive — not reimplemented


# ── enterprise-owned downstream system (in-memory; no network/subprocess) ─────
# This stands in for the enterprise's real deployment system. AiGentsy never
# touches it; the enterprise owns and runs it.
deployment_state: Dict[str, str] = {"status": "not_released"}


def enterprise_deploy_callback() -> Dict[str, Any]:
    """Enterprise-owned callback: release a tested build into a controlled env.

    In production this would call the enterprise's own deployment system. Here it
    only mutates isolated in-memory state and returns a small normalized result.
    """
    deployment_state["status"] = "released"
    return {"released": True, "build": "app-build-42", "environment": "staging"}


# ── offline demonstration harness (fake acceptance client + stub verifier) ────
# Against a LIVE runtime you delete all of this and pass base_url=... instead.
_FULL_VERIFY = {
    "verified": True, "verification_level": "full", "steps_run": 5, "steps_skipped": 0,
    "steps": {k: {"passed": True} for k in
              ("bundle_hash", "event_chain", "merkle_inclusion", "sth_signature", "cross_reference")},
}


def _install_stub_verifier() -> None:
    mod = types.ModuleType("aigentsy_verify")
    bmod = types.ModuleType("aigentsy_verify.bundle")
    bmod.verify_bundle = lambda bundle, public_key_base64="": _FULL_VERIFY  # noqa: E731
    mod.bundle = bmod
    sys.modules["aigentsy_verify"] = mod
    sys.modules["aigentsy_verify.bundle"] = bmod


class _DemoAcceptanceClient:
    """Stands in for the live Acceptance Runtime so the example runs offline.

    Returns a fixed decision so both branches are demonstrable. A real client
    calls POST /acceptance-runtime/evaluate and GET /runs/{run_id}/export.
    """

    def __init__(self, decision: str, consequence_state: str):
        self._decision = decision
        self._cstate = consequence_state

    def acceptance_runtime_evaluate(self, **kw) -> Dict[str, Any]:
        return {"ok": True, "run_id": "infer_demo_deploy", "deal_id": "infer_deal_demo",
                "decision": self._decision, "consequence_state": self._cstate,
                "reason": "demo fixture"}

    def export_run(self, run_id: str) -> Dict[str, Any]:
        # A minimal bundle shape; the real export returns the signed ProofPack.
        return {"deal_id": "infer_deal_demo", "bundle_hash": "demo_hash", "events": []}

    def get_public_key(self) -> Dict[str, str]:
        return {"public_key_base64": "DEMO_KEY"}


def _run_branch(label: str, decision: str, consequence_state: str) -> None:
    deployment_state["status"] = "not_released"  # reset per branch
    client = _DemoAcceptanceClient(decision=decision, consequence_state=consequence_state)

    result = gate_and_prove(
        action="deploy_release",
        evidence={
            "build_tested": True,
            "target_ref": "svc-checkout",          # non-sensitive fixture id
            "release_ref": "app-build-42",
            "environment": "staging",
        },
        run=enterprise_deploy_callback,            # enterprise-owned; runs only if allowed
        client=client,                             # DEMO ONLY — omit + pass base_url live
    )

    print(f"\n=== {label} ===")
    print(f"declared action     : deploy_release")
    print(f"decision            : {result.decision}")
    print(f"consequence_state   : {result.consequence_state}")
    print(f"proof verified      : {bool(result.verification and result.verification.get('verified'))}")
    print(f"callback executed   : {result.action_executed}")
    print(f"callback result     : {result.action_result}")   # enterprise-owned, post-verification
    print(f"deployment_state    : {deployment_state['status']}")
    print(f"run_id              : {result.run_id}")


def main() -> None:
    _install_stub_verifier()
    print("AiGentsy — guard a non-payout enterprise consequence via gate_and_prove")
    print("(payment is one reference consequence, not the architecture)")

    # A. ACCEPTED + VERIFIED → callback runs exactly once, state mutates.
    _run_branch("ACCEPTED + VERIFIED", decision="accepted", consequence_state="allowed")

    # B. REJECTED/BLOCKED → callback never runs, downstream state unchanged.
    _run_branch("REJECTED / BLOCKED", decision="rejected", consequence_state="blocked")

    print("\nThe callback runs ONLY on the accepted+verified branch, in your "
          "environment, after the ProofPack verifies. AiGentsy records references "
          "and hashes only. Record the outcome with client.record_signed_outcome(...) "
          "and reconcile with client.record_outcome_reconciled(...).")


if __name__ == "__main__":
    main()
