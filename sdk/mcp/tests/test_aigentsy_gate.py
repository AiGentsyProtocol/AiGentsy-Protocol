"""Tests for the aigentsy_gate MCP tool.

`mcp` may not be installed in the test env, so we inject a minimal fake
`mcp.server.fastmcp.FastMCP` (whose `.tool()` returns the function unchanged)
before importing the server. `aigentsy.gate_and_prove` is monkeypatched so no
network is hit. These prove: the tool is registered, it DELEGATES to the SDK
primitive (no duplicate gate/proof/verify logic), it surfaces honest
verification (never a fake "5/5"), and it never executes on blocked/held/fail.

Run with the canonical SDK on the path, e.g.:
  PYTHONPATH=src:~/aigentsy-ame-runtime/sdk/aigentsy/src:~/aigentsy-protocol/sdk/verify/src pytest tests/test_aigentsy_gate.py
"""
import sys
import types
import json
import inspect

import pytest


def _install_fake_mcp():
    m = types.ModuleType("mcp")
    srv = types.ModuleType("mcp.server")
    fm = types.ModuleType("mcp.server.fastmcp")

    class FakeFastMCP:
        def __init__(self, *a, **k):
            pass

        def tool(self, *a, **k):
            def deco(fn):
                return fn
            return deco

        def resource(self, *a, **k):
            def deco(fn):
                return fn
            return deco

        def run(self, *a, **k):
            pass

    fm.FastMCP = FakeFastMCP
    srv.fastmcp = fm
    m.server = srv
    sys.modules.setdefault("mcp", m)
    sys.modules.setdefault("mcp.server", srv)
    sys.modules.setdefault("mcp.server.fastmcp", fm)


_install_fake_mcp()

try:
    import aigentsy  # canonical SDK 1.15.0 (via PYTHONPATH)
    from aigentsy.gate import GateResult
    import aigentsy_mcp.server as srv
    _READY = True
except Exception as e:  # pragma: no cover
    _READY = False
    _WHY = str(e)

pytestmark = pytest.mark.skipif(not _READY, reason="canonical aigentsy SDK not importable")


def _result(**kw):
    base = dict(decision=None, action="pay", consequence_state=None, run_id=None,
                allowed=False, blocked=False, held=False, proof_bundle=None,
                bundle_export_url=None, verification=None, action_executed=False,
                action_result=None, fail_closed=False, reason="", error=None)
    base.update(kw)
    return GateResult(**base)


def test_tool_registered():
    assert hasattr(srv, "aigentsy_gate") and callable(srv.aigentsy_gate)


def test_delegates_to_gate_and_prove(monkeypatch):
    seen = {}

    def fake_gap(action, evidence=None, **kw):
        seen["action"] = action
        seen["evidence"] = evidence
        seen["run"] = kw.get("run", "MISSING")
        return _result(decision="accepted", consequence_state="allowed", run_id="r1", allowed=True,
                       verification={"verified": True, "verification_level": "full",
                                     "checks_skipped": [], "anchor_status": "anchored"})

    monkeypatch.setattr(aigentsy, "gate_and_prove", fake_gap)
    out = json.loads(srv.aigentsy_gate(action="pay", evidence='{"ok": true}'))
    assert seen["action"] == "pay" and seen["evidence"] == {"ok": True}
    assert seen["run"] is None                       # gate/prove only — never executes host action
    assert out["consequence_state"] == "allowed" and out["run_id"] == "r1"
    assert out["action_executed"] is False and out["fail_closed"] is False
    assert out["verification"]["verification_level"] == "full"


def test_reuses_sdk_not_duplicate_logic():
    src = inspect.getsource(srv.aigentsy_gate)
    assert "gate_and_prove" in src                    # reuses the SDK primitive
    assert "evaluate_inference" not in src            # does NOT reimplement evaluate
    assert "acceptance-runtime/evaluate" not in src   # no inline endpoint call
    assert "verify_bundle" not in src                 # no inline verify


def test_honest_lightweight_no_fake_5of5(monkeypatch):
    def fake_gap(action, evidence=None, **kw):
        return _result(decision="accepted", consequence_state="allowed", allowed=True, run_id="r2",
                       verification={"verified": True, "verification_level": "offline",
                                     "checks_skipped": ["merkle_inclusion", "sth_signature", "cross_reference"],
                                     "anchor_status": "pending_anchor"})

    monkeypatch.setattr(aigentsy, "gate_and_prove", fake_gap)
    out = srv.aigentsy_gate(action="pay", evidence="{}")
    assert "5/5" not in out and "fully verified" not in out.lower()
    v = json.loads(out)["verification"]
    assert v["verification_level"] == "offline" and v["anchor_status"] == "pending_anchor"


@pytest.mark.parametrize("cstate,flag", [("blocked", "blocked"), ("held", "held")])
def test_blocked_and_held_not_executed(monkeypatch, cstate, flag):
    def fake_gap(action, evidence=None, **kw):
        return _result(consequence_state=cstate, run_id="r", **{flag: True})

    monkeypatch.setattr(aigentsy, "gate_and_prove", fake_gap)
    out = json.loads(srv.aigentsy_gate(action="pay", evidence="{}"))
    assert out["action_executed"] is False and out[flag] is True and out["allowed"] is False


def test_fail_closed_passthrough(monkeypatch):
    def fake_gap(action, evidence=None, **kw):
        return _result(fail_closed=True, reason="evaluate_failed", error="boom")

    monkeypatch.setattr(aigentsy, "gate_and_prove", fake_gap)
    out = json.loads(srv.aigentsy_gate(action="pay", evidence="{}"))
    assert out["fail_closed"] is True and out["action_executed"] is False
