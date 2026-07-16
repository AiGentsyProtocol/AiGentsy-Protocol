"""gate_and_prove — the one-line AiGentsy developer primitive.

Gate one agent action against a policy AND get back a portable proof that
verifies offline, in one call. This is a thin client-side wrapper over public
runtime endpoints (no backend, policy-engine, or verifier changes):

  1. POST /acceptance-runtime/evaluate            -> decision + run_id + consequence_state
  2. GET  /acceptance-runtime/runs/{run_id}/export -> offline-verifiable ProofPack
  3. aigentsy-verify (verify_bundle)              -> verify offline, zero trust in us

Order is: gate -> prove -> verify -> execute-only-if-allowed. The wrapped action
NEVER runs before the gate permits it and the proof has been exported and
honestly verified. Any failure (evaluate/export/verify/timeout/ambiguous/
non-allowed) fails CLOSED and does not run the action.

Honesty guardrail: this primitive surfaces the verifier's OWN fields. It never
prints or returns "5/5" / "fully verified" for a bundle whose Merkle/STH/
cross-reference checks were skipped or are pending anchor. See
_summarize_verification(): checks_skipped and anchor_status are always exposed.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

DEFAULT_BASE = "https://aigentsy-ame-runtime.onrender.com"
_ALLOWED_CONSEQUENCE_STATES = ("allowed", "blocked", "held")
_MANDATORY_CHECKS = ("bundle_hash", "event_chain")
_OPTIONAL_CHECKS = ("merkle_inclusion", "sth_signature", "cross_reference")


@dataclass
class GateResult:
    """Result of a gate_and_prove call. `allowed`/`blocked`/`held` are mutually
    exclusive views of the runtime's consequence_state. `action_executed` is
    True only when the wrapped action ran (i.e. allowed AND mandatory-verified)."""
    decision: Optional[str]                 # runtime decision: accepted/rejected/retry/escalated
    action: Optional[str]                   # caller-supplied action id (echoed)
    consequence_state: Optional[str]        # allowed/blocked/held (the gate signal)
    run_id: Optional[str]
    allowed: bool
    blocked: bool
    held: bool
    proof_bundle: Optional[Dict[str, Any]]  # the exported ProofPack (verifies offline)
    bundle_export_url: Optional[str]
    verification: Optional[Dict[str, Any]]  # honest verifier fields (see below)
    action_executed: bool
    action_result: Any
    fail_closed: bool
    reason: str
    error: Optional[str] = None

    def __bool__(self) -> bool:  # truthy only when the action was allowed + ran/allowed
        return bool(self.allowed and not self.fail_closed)


def _summarize_verification(v: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce the raw verify_bundle() result to honest, non-synthesized fields.

    Uses the verifier's OWN `steps`, `verified`, `verification_level`,
    `steps_run`, `steps_skipped`. Never invents a numeric score, never claims
    "5/5" — checks_skipped and anchor_status make skipped/pending checks visible.
    """
    steps = v.get("steps", {}) or {}

    def _status(name: str) -> str:
        s = steps.get(name, {}) or {}
        if s.get("passed"):
            return "pass"
        if s.get("skipped"):
            return "skipped"
        return "fail"

    skipped = [n for n in steps if (steps[n] or {}).get("skipped")]
    merkle, sth, xref = _status("merkle_inclusion"), _status("sth_signature"), _status("cross_reference")
    mandatory_passed = all((steps.get(c, {}) or {}).get("passed") for c in _MANDATORY_CHECKS)
    anchored = merkle == "pass" and sth == "pass"
    return {
        "verified": bool(v.get("verified")),
        # "full" (no skips) vs "offline" (some optional checks skipped) — verbatim from verifier
        "verification_level": v.get("verification_level"),
        "mandatory_passed": bool(mandatory_passed),
        "checks_passed": sum(1 for s in steps.values() if (s or {}).get("passed")),
        "checks_required": len(_MANDATORY_CHECKS),   # bundle_hash + event_chain
        "checks_total": len(steps),
        "checks_skipped": skipped,
        "steps_run": v.get("steps_run"),
        "steps_skipped": v.get("steps_skipped"),
        "merkle_inclusion": merkle,
        "sth_signature": sth,
        "cross_reference": xref,
        # honest anchor signal — "pending_anchor" whenever Merkle/STH are skipped
        "anchor_status": "anchored" if anchored else "pending_anchor",
        "raw": v,
    }


def _client(client, base_url):
    if client is not None:
        return client
    from aigentsy.client import AiGentsyClient
    return AiGentsyClient(base_url or DEFAULT_BASE)


def gate_and_prove(
    action: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
    *,
    run: Optional[Callable[[], Any]] = None,
    client: Any = None,
    base_url: Optional[str] = None,
    # real /acceptance-runtime/evaluate fields (pass-through; nothing invented)
    policy: Optional[Dict[str, Any]] = None,
    consequence: Optional[Dict[str, Any]] = None,
    required_evidence: Optional[Dict[str, bool]] = None,
    risk_tier: str = "medium",
    raw_output: str = "",
    prompt: str = "",
    model_metadata: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
    fail_closed: bool = True,
    verify: bool = True,
    public_key_base64: Optional[str] = None,
):
    """Gate an action and prove the decision.

    Two shapes:

      # direct call — runs `run` only if allowed + mandatory-verified
      r = gate_and_prove("contractor_payout", evidence={...}, run=lambda: release())

      # decorator — evidence supplied at call time
      @gate_and_prove(action="contractor_payout")
      def release(...): ...
      r = release(..., evidence={...})   # r is a GateResult; r.action_result has release()'s return if allowed
    """
    # ---- decorator mode: @gate_and_prove(action="...") ----
    if evidence is None and run is None:
        def _decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def _wrapper(*args, evidence: Dict[str, Any], **kwargs) -> GateResult:
                return gate_and_prove(
                    action=action, evidence=evidence, run=lambda: fn(*args, **kwargs),
                    client=client, base_url=base_url, policy=policy, consequence=consequence,
                    required_evidence=required_evidence, risk_tier=risk_tier, raw_output=raw_output,
                    prompt=prompt, model_metadata=model_metadata, timeout=timeout,
                    fail_closed=fail_closed, verify=verify, public_key_base64=public_key_base64,
                )
            return _wrapper
        return _decorator

    # ---- direct mode ----
    cl = _client(client, base_url)
    export_url = None

    def _fail(reason: str, error: Optional[str] = None, **extra) -> GateResult:
        base = dict(
            decision=None, action=action, consequence_state=None, run_id=None,
            allowed=False, blocked=False, held=False, proof_bundle=None,
            bundle_export_url=export_url, verification=None, action_executed=False,
            action_result=None, fail_closed=True, reason=reason, error=error,
        )
        base.update(extra)
        return GateResult(**base)

    # 1-3. evaluate (conform to the actual public endpoint schema; no invented fields)
    body = {
        "prompt": prompt,
        "raw_output": raw_output,
        "policy": policy or {},
        "required_evidence": required_evidence if required_evidence is not None else (evidence or {}),
        "consequence": consequence if consequence is not None else ({"kind": action} if action else {}),
        "risk_tier": risk_tier,
        "model_metadata": model_metadata or {},
    }
    try:
        ev = cl.acceptance_runtime_evaluate(**body)
    except Exception as e:  # network / http / timeout
        return _fail("evaluate_failed", "%s: %s" % (type(e).__name__, e))

    decision = ev.get("decision")
    run_id = ev.get("run_id")
    cstate = ev.get("consequence_state")
    reason_txt = ev.get("reason", "") or ""

    # 4. missing run_id / ambiguous decision -> fail closed
    if not run_id:
        return _fail("missing_run_id: gate returned no run_id", decision=decision, consequence_state=cstate)
    if cstate not in _ALLOWED_CONSEQUENCE_STATES:
        return _fail("ambiguous_decision: consequence_state=%r" % (cstate,),
                     decision=decision, run_id=run_id, consequence_state=cstate)

    allowed, blocked, held = cstate == "allowed", cstate == "blocked", cstate == "held"
    export_url = "%s/acceptance-runtime/runs/%s/export" % ((base_url or DEFAULT_BASE).rstrip("/"), run_id)

    # 5. export ProofPack
    try:
        bundle = cl.export_run(run_id)
    except Exception as e:
        return _fail("export_failed", "%s: %s" % (type(e).__name__, e),
                     decision=decision, run_id=run_id, consequence_state=cstate,
                     blocked=blocked, held=held)

    # 6-7. verify offline (honest surfacing)
    verification = None
    if verify:
        try:
            from aigentsy_verify.bundle import verify_bundle
        except Exception:
            return _fail("verifier_unavailable: install with  pip install 'aigentsy[verify]'",
                         "aigentsy-verify not importable",
                         decision=decision, run_id=run_id, consequence_state=cstate,
                         proof_bundle=bundle, blocked=blocked, held=held)
        pk = public_key_base64
        if pk is None:
            try:
                pk = (cl.get_public_key() or {}).get("public_key_base64", "")
            except Exception:
                pk = ""  # verify without key -> STH/xref skip (honest "offline" level)
        try:
            vraw = verify_bundle(bundle, public_key_base64=pk or "")
        except Exception as e:
            return _fail("verification_error", "%s: %s" % (type(e).__name__, e),
                         decision=decision, run_id=run_id, consequence_state=cstate,
                         proof_bundle=bundle, blocked=blocked, held=held)
        verification = _summarize_verification(vraw)

    # 8. execute ONLY IF allowed AND mandatory verification passed
    if allowed and verify:
        ok = bool(verification and verification.get("verified") and verification.get("mandatory_passed"))
        if not ok:
            return _fail("verification_insufficient: mandatory checks did not pass",
                         None, decision=decision, run_id=run_id, consequence_state=cstate,
                         proof_bundle=bundle, verification=verification)

    result = GateResult(
        decision=decision, action=action, consequence_state=cstate, run_id=run_id,
        allowed=allowed, blocked=blocked, held=held, proof_bundle=bundle,
        bundle_export_url=export_url, verification=verification, action_executed=False,
        action_result=None, fail_closed=False, reason=reason_txt or cstate, error=None,
    )
    if allowed and run is not None:
        try:
            result.action_result = run()
            result.action_executed = True
        except Exception as e:
            # The action itself raised AFTER being allowed — surface it, do not mask.
            # (This is not a gate failure; the gate correctly permitted the run.)
            result.error = "action_raised: %s: %s" % (type(e).__name__, e)
    return result


def gate_langchain_tool(func: Callable = None, *, action: Optional[str] = None,
                        name: Optional[str] = None, description: Optional[str] = None, **cfg):
    """Optional LangChain wrapper — reuses the SAME gate_and_prove core (no duplicate
    gate/proof logic). Requires the optional extra:  pip install 'aigentsy[langchain]'.

    Returns a LangChain StructuredTool whose invocation gates+proves before running
    `func`. Ergonomics are approximate across LangChain versions; the base SDK does
    NOT import LangChain (this import is lazy and only happens when you call this).
    """
    try:
        from langchain_core.tools import StructuredTool
    except Exception as e:  # graceful, actionable hint
        raise ImportError(
            "LangChain is not installed. Install the optional extra:\n"
            "    pip install 'aigentsy[langchain]'"
        ) from e

    gated = gate_and_prove(action=action, **cfg)(func)  # same core, decorator form
    return StructuredTool.from_function(
        func=gated,
        name=name or getattr(func, "__name__", "gated_tool"),
        description=description or (getattr(func, "__doc__", None) or "AiGentsy gate-and-prove tool"),
    )
