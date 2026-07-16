"""Tests for the gate_and_prove one-line primitive.

Network-free: a FakeClient supplies evaluate/export results and a fake
`aigentsy_verify.bundle.verify_bundle` is injected into sys.modules, so these
run without the runtime or the published verifier installed. The invariant
under test everywhere: the wrapped action NEVER runs unless the gate allowed it
AND mandatory verification passed; anything else fails CLOSED.
"""
import sys
import types
import pathlib

import pytest

from aigentsy.gate import gate_and_prove, GateResult, _summarize_verification

# ── fake verifier (avoids requiring aigentsy-verify to be installed) ──────────
FULL_VERIFY = {
    "verified": True, "verification_level": "full", "steps_run": 5, "steps_skipped": 0,
    "steps": {"bundle_hash": {"passed": True}, "event_chain": {"passed": True},
              "merkle_inclusion": {"passed": True}, "sth_signature": {"passed": True},
              "cross_reference": {"passed": True}},
}
# lightweight/single-event bundle: mandatory pass, optional SKIPPED (Guardrail 1)
LIGHT_VERIFY = {
    "verified": True, "verification_level": "offline", "steps_run": 2, "steps_skipped": 3,
    "steps": {"bundle_hash": {"passed": True}, "event_chain": {"passed": True},
              "merkle_inclusion": {"passed": False, "skipped": True},
              "sth_signature": {"passed": False, "skipped": True},
              "cross_reference": {"passed": False, "skipped": True}},
}
BAD_VERIFY = {  # mandatory bundle_hash FAILS
    "verified": False, "verification_level": "offline", "steps_run": 1, "steps_skipped": 3,
    "steps": {"bundle_hash": {"passed": False}, "event_chain": {"passed": True},
              "merkle_inclusion": {"passed": False, "skipped": True},
              "sth_signature": {"passed": False, "skipped": True},
              "cross_reference": {"passed": False, "skipped": True}},
}


def _install_verifier(result=None, raises=None):
    mod = types.ModuleType("aigentsy_verify")
    bmod = types.ModuleType("aigentsy_verify.bundle")

    def verify_bundle(bundle, public_key_base64=""):
        if raises is not None:
            raise raises
        return result
    bmod.verify_bundle = verify_bundle
    mod.bundle = bmod
    sys.modules["aigentsy_verify"] = mod
    sys.modules["aigentsy_verify.bundle"] = bmod


def _uninstall_verifier():
    sys.modules.pop("aigentsy_verify", None)
    sys.modules.pop("aigentsy_verify.bundle", None)


class FakeClient:
    def __init__(self, evaluate=None, export=None, evaluate_exc=None, export_exc=None):
        self._eval = evaluate
        self._export = export if export is not None else {"deal_id": "d", "bundle_hash": "abc", "events": []}
        self._eval_exc = evaluate_exc
        self._export_exc = export_exc
        self.calls = {"evaluate": 0, "export": 0, "pubkey": 0}

    def acceptance_runtime_evaluate(self, **kw):
        self.calls["evaluate"] += 1
        if self._eval_exc:
            raise self._eval_exc
        return self._eval

    def export_run(self, run_id):
        self.calls["export"] += 1
        if self._export_exc:
            raise self._export_exc
        return self._export

    def get_public_key(self):
        self.calls["pubkey"] += 1
        return {"public_key_base64": "KEY"}


def _ev(decision, cstate, run_id="infer_abc123"):
    return {"ok": True, "run_id": run_id, "deal_id": "infer_deal", "decision": decision,
            "consequence_state": cstate, "reason": "test"}


class _Ran:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return "EXECUTED"


# ── 1. accept/allowed path ────────────────────────────────────────────────────
def test_accept_runs_after_verification():
    _install_verifier(FULL_VERIFY)
    cl = FakeClient(evaluate=_ev("accepted", "allowed"))
    ran = _Ran()
    r = gate_and_prove("contractor_payout", evidence={"ok": True}, run=ran, client=cl)
    assert r.allowed and not r.blocked and not r.held
    assert r.action_executed is True and r.action_result == "EXECUTED" and ran.n == 1
    assert cl.calls == {"evaluate": 1, "export": 1, "pubkey": 1}   # gate→prove→verify order
    assert r.decision == "accepted" and r.run_id == "infer_abc123"
    assert r.verification["verified"] and r.verification["verification_level"] == "full"
    assert r.proof_bundle is not None and r.fail_closed is False


# ── 2. reject/blocked path ────────────────────────────────────────────────────
def test_reject_does_not_run_but_returns_proof():
    _install_verifier(FULL_VERIFY)
    cl = FakeClient(evaluate=_ev("rejected", "blocked"))
    ran = _Ran()
    r = gate_and_prove("contractor_payout", evidence={"ok": False}, run=ran, client=cl)
    assert r.blocked and not r.allowed
    assert r.action_executed is False and ran.n == 0
    assert r.proof_bundle is not None                       # signed rejection is evidence too
    assert cl.calls["export"] == 1 and r.verification is not None


# ── 3. hold/require_review path ───────────────────────────────────────────────
def test_hold_does_not_run_but_returns_proof():
    _install_verifier(FULL_VERIFY)
    cl = FakeClient(evaluate=_ev("require_review", "held"))
    ran = _Ran()
    r = gate_and_prove("contractor_payout", evidence={"partial": True}, run=ran, client=cl)
    assert r.held and not r.allowed and r.action_executed is False and ran.n == 0
    assert r.proof_bundle is not None and r.verification is not None


# ── 4-8. fail-closed paths ────────────────────────────────────────────────────
def test_fail_closed_evaluate_error():
    _install_verifier(FULL_VERIFY)
    cl = FakeClient(evaluate_exc=RuntimeError("boom"))
    ran = _Ran()
    r = gate_and_prove("x", evidence={}, run=ran, client=cl)
    assert r.fail_closed and r.action_executed is False and ran.n == 0
    assert "evaluate_failed" in r.reason and cl.calls["export"] == 0


def test_fail_closed_export_error():
    _install_verifier(FULL_VERIFY)
    cl = FakeClient(evaluate=_ev("accepted", "allowed"), export_exc=RuntimeError("no export"))
    ran = _Ran()
    r = gate_and_prove("x", evidence={}, run=ran, client=cl)
    assert r.fail_closed and r.action_executed is False and ran.n == 0
    assert "export_failed" in r.reason


def test_fail_closed_verification_error():
    _install_verifier(raises=ValueError("verify blew up"))
    cl = FakeClient(evaluate=_ev("accepted", "allowed"))
    ran = _Ran()
    r = gate_and_prove("x", evidence={}, run=ran, client=cl)
    assert r.fail_closed and r.action_executed is False and ran.n == 0
    assert "verification_error" in r.reason


def test_fail_closed_verification_insufficient():
    # allowed but mandatory bundle_hash fails -> must NOT run
    _install_verifier(BAD_VERIFY)
    cl = FakeClient(evaluate=_ev("accepted", "allowed"))
    ran = _Ran()
    r = gate_and_prove("x", evidence={}, run=ran, client=cl)
    assert r.fail_closed and r.action_executed is False and ran.n == 0
    assert "verification_insufficient" in r.reason


def test_fail_closed_missing_run_id():
    _install_verifier(FULL_VERIFY)
    cl = FakeClient(evaluate={"decision": "accepted", "consequence_state": "allowed"})  # no run_id
    ran = _Ran()
    r = gate_and_prove("x", evidence={}, run=ran, client=cl)
    assert r.fail_closed and r.action_executed is False and ran.n == 0
    assert "missing_run_id" in r.reason and cl.calls["export"] == 0


def test_fail_closed_ambiguous_decision():
    _install_verifier(FULL_VERIFY)
    cl = FakeClient(evaluate=_ev("weird", "maybe"))  # consequence_state not allowed/blocked/held
    ran = _Ran()
    r = gate_and_prove("x", evidence={}, run=ran, client=cl)
    assert r.fail_closed and r.action_executed is False and ran.n == 0
    assert "ambiguous_decision" in r.reason and cl.calls["export"] == 0


# ── 9-10. GUARDRAIL 1 — honest verification, no fake "5/5" ────────────────────
def test_lightweight_bundle_surfaced_honestly():
    _install_verifier(LIGHT_VERIFY)
    cl = FakeClient(evaluate=_ev("accepted", "allowed"))
    ran = _Ran()
    r = gate_and_prove("x", evidence={}, run=ran, client=cl)
    v = r.verification
    # allowed + mandatory passed -> action runs, but honesty fields must be loud
    assert r.action_executed is True
    assert v["verified"] is True
    assert v["verification_level"] == "offline"           # not "full"
    assert v["checks_skipped"] == ["merkle_inclusion", "sth_signature", "cross_reference"]
    assert v["steps_skipped"] == 3 and v["checks_passed"] == 2
    assert v["anchor_status"] == "pending_anchor"          # not anchored
    assert v["merkle_inclusion"] == "skipped" and v["sth_signature"] == "skipped"
    # NO blanket "5/5" / "fully verified" anywhere in the surfaced verification
    blob = repr(v).lower()
    assert "5/5" not in blob
    assert "fully verified" not in blob
    assert "all checks passed" not in blob
    assert "complete verification" not in blob


def test_verification_fields_are_reused_not_synthesized():
    _install_verifier(FULL_VERIFY)
    v = _summarize_verification(FULL_VERIFY)
    assert v["raw"] is FULL_VERIFY                         # verifier's own object preserved
    assert v["checks_passed"] == 5 and v["verification_level"] == "full"
    assert v["anchor_status"] == "anchored" and v["checks_skipped"] == []
    # no synthesized numeric score field
    assert "score" not in v


# ── 11. decorator ergonomics + action-never-before-allowed ────────────────────
def test_decorator_one_line_accept_and_reject():
    _install_verifier(FULL_VERIFY)

    @gate_and_prove(action="release", client=FakeClient(evaluate=_ev("accepted", "allowed")))
    def release_ok(x):
        return x * 2

    r = release_ok(21, evidence={"ok": True})
    assert isinstance(r, GateResult)
    assert r.allowed and r.action_executed and r.action_result == 42

    @gate_and_prove(action="release", client=FakeClient(evaluate=_ev("rejected", "blocked")))
    def release_blocked(x):
        raise AssertionError("must not run when blocked")

    r2 = release_blocked(21, evidence={"ok": False})
    assert r2.blocked and r2.action_executed is False


# ── 12. LangChain wrapper: base import works; graceful hint when extra missing ─
def test_langchain_wrapper_graceful_without_extra():
    import aigentsy  # base SDK imports fine without LangChain
    assert hasattr(aigentsy, "gate_and_prove") and hasattr(aigentsy, "gate_langchain_tool")
    from aigentsy.gate import gate_langchain_tool
    # ensure langchain_core is absent for this assertion
    had = sys.modules.pop("langchain_core", None)
    try:
        import importlib
        if importlib.util.find_spec("langchain_core") is None:
            with pytest.raises(ImportError) as ei:
                gate_langchain_tool(lambda: None, action="x")
            assert "aigentsy[langchain]" in str(ei.value)
        else:
            pytest.skip("langchain_core installed in env; graceful-hint path not exercised")
    finally:
        if had is not None:
            sys.modules["langchain_core"] = had


# ── 13. version drift: aigentsy[verify] pins the public 1.5.0 + README note ────
def test_verifier_version_pin_and_note():
    root = pathlib.Path(__file__).resolve().parents[1]
    pyproj = (root / "pyproject.toml").read_text()
    assert "aigentsy-verify>=1.5.0" in pyproj              # pins the public release, not >=1.0
    readme = (root / "README.md").read_text()
    assert "Verifier version" in readme and "1.5.0" in readme and "1.2.1" in readme
