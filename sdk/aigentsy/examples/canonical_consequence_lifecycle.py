"""AiGentsy — the complete Consequence Gate lifecycle, one joined example.

Shows how an enterprise moves through the ALREADY-FUNCTIONAL Consequence Gate
using only existing SDK primitives — no hand-written HTTP, no hidden operator
knowledge. The consequence here is a non-payment deployment/release; the same
pattern applies to API action, handoff, procurement, access change, delivery,
publication, and other bounded consequences. Payment is one reference
consequence, not the architecture.

Journey (single ``deal_id`` causal spine):

    output + evidence
    → gate_and_prove  (Acceptance → export ProofPack → verify → run only if allowed)
    → enterprise-owned callback executes  (in YOUR environment)
    → record_signed_outcome  (signed OUTCOME_RECORDED OutcomeReceipt — the performer
                              attests the consequence occurred; consequence-neutral,
                              so a non-payment deploy carries amount=0.0 and no payer)
    → reconcile_outcome  (OUTCOME_RECONCILED: what was observed vs expected)
    → get_settlement_memory  (owner-scoped read-only projection of the chain)

The OutcomeReceipt and the reconciliation are DISTINCT stages: the OutcomeReceipt
is the performer's Ed25519-signed attestation that the authorized consequence was
carried out; reconciliation is a later, caller-attested read-back comparing the
observed result against what was expected. Reconciliation does NOT replace the
OutcomeReceipt.

TRUST BOUNDARY (honest):
  AiGentsy proves and records the declared action, evidence, Acceptance decision,
  ProofPack integrity, independent verification, whether the callback was
  permitted/invoked, and the reconciliation/memory references. The enterprise
  owns the callback, its credentials/runtime, the target system, the external
  side effect, operational correctness, and the truthfulness of the observations
  it reports. The callback runs AFTER verification; its result is NOT part of the
  pre-execution signed ProofPack. The OutcomeReceipt is the performer's signed
  attestation that the authorized consequence was carried out — AiGentsy records
  that attestation and its references, not independent real-world truth.
  Reconciliation records a later observation — it does not rewrite history and is
  not a substitute for the OutcomeReceipt. Settlement Memory is a read-only event
  projection. AiGentsy is non-custodial and does not verify real-world truth. No
  exactly-once claim is made.

Against a LIVE runtime you delete the demo transport below and use:

    from aigentsy import AiGentsyClient, gate_and_prove
    client = AiGentsyClient(base_url="https://aigentsy-ame-runtime.onrender.com",
                            api_key="a2a_...your key...")
    result = gate_and_prove(action="deploy_release", evidence=..., run=..., client=client)
    if result.action_executed:
        client.record_signed_outcome(deal_id=result.run_id, performer_id="a2a_...",
                                     payer_id="", amount=0.0, key_id="your_enrolled_key",
                                     keypair=your_keypair, intent="authorized_consequence")
        client.reconcile_outcome(deal_id=result.run_id, reconciliation_status="matched", ...)
        client.get_settlement_memory()

PREREQUISITE (signing dependency):
  The signed OutcomeReceipt stage (``SigningKeypair.generate()`` →
  ``record_signed_outcome`` → ``OUTCOME_RECORDED``) uses the existing Ed25519
  signing path, which requires the ``cryptography`` package. It is NOT part of
  the base ``aigentsy`` install, and the gate/reconcile/memory wrappers do not
  need it — only this signing step does. Install it before running:

      pip install aigentsy "cryptography>=41.0"

  This example generates a TEMPORARY local Ed25519 key (``SigningKeypair.generate``)
  purely for the isolated offline demonstration. In production the enterprise
  manages and enrolls its OWN private signing key; AiGentsy never receives or
  retains the private key — the private bytes are used to sign locally and dropped.

This file runs OFFLINE (no network, no credentials) via a demo transport so both
branches and the joined chain are visible (with ``cryptography`` installed):

    python examples/canonical_consequence_lifecycle.py
"""
from __future__ import annotations

import hashlib
import sys
import types
from typing import Any, Dict

from aigentsy import AiGentsyClient, gate_and_prove  # real SDK primitives — not reimplemented
from aigentsy.keypair import SigningKeypair          # local, non-custodial Ed25519 key


DEAL_ID = "infer_deal_demo_deploy"
PRIOR_EVENT_ID = "evt_demo_decision"


# ── enterprise-owned downstream system (in-memory; no network/subprocess) ─────
deployment_state: Dict[str, str] = {"status": "not_released"}


def enterprise_deploy_callback() -> Dict[str, Any]:
    """Enterprise-owned callback: release a tested build. In production this calls
    the enterprise's own deployment system; here it mutates isolated in-memory
    state and returns a small normalized result."""
    deployment_state["status"] = "released"
    return {"released": True, "build": "app-build-42", "environment": "staging"}


def _sha256(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


# ── offline demo transport (subclasses the REAL client; fakes HTTP only) ──────
# Against a live runtime you remove this and pass a real AiGentsyClient.
class _DemoClient(AiGentsyClient):
    def __init__(self, decision: str, consequence_state: str):
        super().__init__(base_url="http://demo.local", api_key="a2a_demo")
        self._decision = decision
        self._cstate = consequence_state

    # gate_and_prove transport
    def acceptance_runtime_evaluate(self, **kw) -> Dict[str, Any]:
        return {"ok": True, "run_id": DEAL_ID, "deal_id": DEAL_ID,
                "decision": self._decision, "consequence_state": self._cstate,
                "reason": "demo fixture"}

    def export_run(self, run_id: str) -> Dict[str, Any]:
        return {"deal_id": DEAL_ID, "bundle_hash": "demo_bundle_hash", "events": []}

    def get_public_key(self) -> Dict[str, str]:
        return {"public_key_base64": "DEMO_KEY"}

    # wrapper transport — the REAL record_signed_outcome / reconcile_outcome /
    # get_settlement_memory run through these; only the HTTP round-trip is faked.
    # record_signed_outcome performs a genuine local Ed25519 signature over the
    # canonical bytes returned by /protocol/event/prepare (nothing is stubbed in
    # the SDK's signing path — only the two HTTP hops are).
    def _post(self, path, body=None, auth=False):
        assert auth is True
        if path == "/protocol/event/prepare":
            import base64
            return {"token": "demo_token",
                    "canonical_bytes_b64": base64.b64encode(
                        b"demo OUTCOME_RECORDED canonical bytes").decode("ascii")}
        if path == "/protocol/event/submit":
            # amount echoes what the performer signed (0.0 for this non-payment deploy).
            return {"event": {"event_type": "OUTCOME_RECORDED",
                              "event_id": "evt_demo_outcome", "deal_id": DEAL_ID,
                              "amount": 0.0, "intent": "authorized_consequence",
                              "source": "graph_settlement"}}
        assert path == "/protocol/outcome-reconciliation"
        return {"ok": True, "event_type": "OUTCOME_RECONCILED",
                "deal_id": (body or {}).get("deal_id"),
                "event_id": "evt_demo_reconciled",
                "readback_source_type": "caller_attested"}

    def _get(self, path, params=None, auth=False):
        assert path == "/protocol/settlement-memory" and auth is True
        return {"ok": True, "deals": [{
            "deal_id": DEAL_ID, "acceptance_state": "accepted",
            "consequence_state": "allowed",
            "reconciliation": {"reconciliation_status": "matched",
                               "event_id": "evt_demo_reconciled",
                               "readback_source_type": "caller_attested"},
            "proof": {"bundle_hash": "demo_bundle_hash"}}],
            "next_cursor": None, "limit": params.get("limit") if params else None}


def _stub_verifier() -> None:
    mod = types.ModuleType("aigentsy_verify")
    bmod = types.ModuleType("aigentsy_verify.bundle")
    bmod.verify_bundle = lambda bundle, public_key_base64="": {
        "verified": True, "verification_level": "full", "steps_run": 5, "steps_skipped": 0,
        "steps": {k: {"passed": True} for k in
                  ("bundle_hash", "event_chain", "merkle_inclusion", "sth_signature", "cross_reference")}}
    mod.bundle = bmod
    sys.modules["aigentsy_verify"] = mod
    sys.modules["aigentsy_verify.bundle"] = bmod


def run_branch(label: str, decision: str, consequence_state: str) -> None:
    deployment_state["status"] = "not_released"  # reset per branch
    client = _DemoClient(decision=decision, consequence_state=consequence_state)

    # 1) gate the declared consequence; the callback runs only if allowed+verified.
    result = gate_and_prove(
        action="deploy_release",
        evidence={"build_tested": True, "target_ref": "svc-checkout",
                  "release_ref": "app-build-42", "environment": "staging"},
        run=enterprise_deploy_callback,     # enterprise-owned
        client=client,
    )

    print(f"\n=== {label} ===")
    print(f"deal_id            : {result.run_id}")
    print(f"decision           : {result.decision}")
    print(f"consequence_state  : {result.consequence_state}")
    print(f"proof verified     : {bool(result.verification and result.verification.get('verified'))}")
    print(f"callback executed  : {result.action_executed}")
    print(f"callback result    : {result.action_result}")     # enterprise-owned, post-verification
    print(f"deployment_state   : {deployment_state['status']}")

    if not result.action_executed:
        print("no consequence occurred → no outcome to reconcile")
        return

    # 2) record the SIGNED OutcomeReceipt (OUTCOME_RECORDED) — the performer attests
    #    the authorized consequence was carried out. OUTCOME_RECORDED is
    #    consequence-neutral (it gates payment, release, deployment, access change,
    #    audit record, ...), so this non-payment deploy is honest with NO fabricated
    #    money: amount=0.0 (the runtime's own default) and payer_id="" (no payer, so
    #    buyer_id falls back to the performer). There is no currency/provider field
    #    to invent. The signature is real: record_signed_outcome round-trips
    #    /protocol/event/prepare → local Ed25519 sign → /protocol/event/submit. Here
    #    the key is demo-generated and non-custodial; against a live runtime the
    #    enterprise enrolls its own performer key via the operator enrollment flow.
    receipt_key = SigningKeypair.generate(print_notice=False)
    receipt = client.record_signed_outcome(
        deal_id=result.run_id,
        performer_id="a2a_demo",          # the client authenticates as this performer
        payer_id="",                      # non-payment ⇒ no payer; buyer_id → performer
        amount=0.0,                       # non-payment ⇒ zero; honest, not fabricated
        key_id="demo_deploy_key",
        keypair=receipt_key,              # local, non-custodial Ed25519 key
        intent="authorized_consequence",  # gates ANY consequence, not only payment
        extra_payload={"consequence_type": "deploy_release",
                       "release_ref": "app-build-42", "environment": "staging"},
    )
    print(f"outcome receipt    : {receipt.get('event_type')} "
          f"intent={receipt.get('intent')} amount={receipt.get('amount')} "
          f"deal={receipt.get('deal_id')}")

    # 3) record the observed outcome (OUTCOME_RECONCILED) — references/hashes only,
    #    same deal_id. Simple X-API-Key caller-attested path (no keypair). This is a
    #    DISTINCT stage from the OutcomeReceipt above — a later read-back comparison,
    #    NOT a substitute for it.
    rec = client.reconcile_outcome(
        deal_id=result.run_id,
        reconciliation_status="matched",
        expected_outcome_hash=_sha256("expected: released app-build-42"),
        observed_outcome_hash=_sha256("observed: released app-build-42"),
        evidence_hash=_sha256("deploy readback evidence"),
        prior_authorization_event_id=PRIOR_EVENT_ID,
        readback_source="ci_deploy_log",
        comparison_method="hash_equality",
    )
    print(f"reconciliation     : {rec.get('event_type')} status=matched "
          f"source_type={rec.get('readback_source_type')} deal={rec.get('deal_id')}")

    # 4) query owner-scoped Settlement Memory — the read-only projection of the chain.
    mem = client.get_settlement_memory(limit=10)
    d = (mem.get("deals") or [{}])[0]
    print(f"settlement memory  : deal={d.get('deal_id')} "
          f"acceptance={d.get('acceptance_state')} "
          f"reconciliation={d.get('reconciliation', {}).get('reconciliation_status')} "
          f"proof={d.get('proof', {}).get('bundle_hash')}")
    print("chain continuous   : "
          f"{result.run_id == receipt.get('deal_id') == rec.get('deal_id') == d.get('deal_id')}")


def main() -> None:
    _stub_verifier()
    print("AiGentsy — complete Consequence Gate lifecycle (non-payment: deploy_release)")
    print("gate_and_prove → callback → record_signed_outcome → reconcile_outcome "
          "→ get_settlement_memory")
    run_branch("ACCEPTED + VERIFIED", decision="accepted", consequence_state="allowed")
    run_branch("REJECTED / BLOCKED", decision="rejected", consequence_state="blocked")
    print("\nThe callback runs only on the accepted+verified branch, in your "
          "environment, after the ProofPack verifies. AiGentsy stores references "
          "and hashes only; it is non-custodial and does not verify real-world truth.")


if __name__ == "__main__":
    main()
