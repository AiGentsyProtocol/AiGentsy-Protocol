"""Smoke test for aigentsy-mcp.

Confirms:
* Package imports cleanly
* Server module has main() entry point
* All 13 tool functions exist
* FastMCP accepts every tool signature (no InvalidSignature, no leading-_ params)
* Server boots via python -m aigentsy_mcp without immediate crash

Plus two live contract gates against AME_BASE (defaults to production):
* aigentsy_export returns a bundle that aigentsy-verify accepts (F1 gate)
* Anonymous proof_pack remains publicly verifiable (anonymous-proof gate)

Set AIGENTSY_SKIP_LIVE=1 to skip the live gates locally; the release pipeline
must run them green before publishing.
"""

import asyncio
import importlib
import json
import os
import subprocess
import sys


def test_imports():
    mod = importlib.import_module("aigentsy_mcp.server")
    assert hasattr(mod, "main"), "server.main() missing"
    assert hasattr(mod, "mcp"), "FastMCP instance missing"


def test_tool_count():
    mod = importlib.import_module("aigentsy_mcp.server")
    expected_tools = {
        "aigentsy_register",
        "aigentsy_proof_pack",
        "aigentsy_settle",
        "aigentsy_verify",
        "aigentsy_export",
        "aigentsy_proof_chain",
        "aigentsy_settle_multi",
        "aigentsy_attestation",
        "aigentsy_fee_tiers",
        "aigentsy_create_webhook",
        "aigentsy_acceptance_submit",
        "aigentsy_acceptance_decide",
        "aigentsy_acceptance_status",
    }
    actual_tools = {name for name in expected_tools if hasattr(mod, name)}
    missing = expected_tools - actual_tools
    assert not missing, f"Missing tools: {missing}"


def test_fastmcp_signatures_valid():
    """All tool wrappers must register with FastMCP without InvalidSignature.

    Guards against parameter names beginning with '_' (FastMCP rejects them)
    and any other signature constraint that would prevent stdio tool dispatch.
    """
    mod = importlib.import_module("aigentsy_mcp.server")
    tool_names = asyncio.run(_collect_tool_names(mod.mcp))
    assert len(tool_names) == 13, (
        f"FastMCP registered {len(tool_names)} tools, expected 13. "
        f"Got: {sorted(tool_names)}"
    )


async def _collect_tool_names(mcp_instance):
    tools = await mcp_instance.list_tools()
    return [t.name for t in tools]


def test_export_bundle_is_verifiable():
    """aigentsy_export must return a bundle that aigentsy-verify accepts.

    Gate against the F1 regression class (export hits a non-spec endpoint
    and returns a bundle that fails offline verification). Run live against
    AME_BASE (defaults to production); skipped if AIGENTSY_SKIP_LIVE=1 is set.

    Requires aigentsy-verify to be installed in the same environment.
    """
    if os.environ.get("AIGENTSY_SKIP_LIVE") == "1":
        print("  [skip] AIGENTSY_SKIP_LIVE=1")
        return

    try:
        from aigentsy_verify import verify_bundle, fetch_public_key
    except ImportError:
        raise AssertionError(
            "aigentsy-verify is required for the export-verifiability gate. "
            "Install with: pip install aigentsy-verify"
        )

    server = importlib.import_module("aigentsy_mcp.server")

    # Disposable agent + proof via the public wrappers (no signup-time secrets)
    reg = json.loads(server.aigentsy_register(
        agent_name="mcp_export_gate_smoke",
        capabilities="research",
    ))
    api_key = reg["api_key"]
    agent_id = reg["agent_id"]

    pp = json.loads(server.aigentsy_proof_pack(
        agent_username=agent_id,
        scope_summary="export-verifiability smoke",
        api_key=api_key,
    ))
    deal_id = pp.get("deal_id")
    assert deal_id, f"proof_pack returned no deal_id: {pp}"

    bundle = json.loads(server.aigentsy_export(deal_id=deal_id))

    public_key = fetch_public_key()
    result = verify_bundle(bundle, public_key_base64=public_key)

    assert result.get("verified") is True, (
        f"aigentsy-verify rejected the exported bundle. result={result}"
    )
    steps = result.get("steps", {})
    failed = [name for name, step in steps.items() if not step.get("passed")]
    assert not failed, (
        f"aigentsy-verify reported failed/skipped checks: {failed}. "
        f"full steps={steps}"
    )
    assert result.get("steps_run", 0) == 5, (
        f"expected 5 verification steps to run; got {result.get('steps_run')}"
    )


def test_anonymous_proof_is_verifiable():
    """Anonymous proof_pack (no api_key) must remain publicly verifiable.

    Protocol invariant: proof is open, consequence is authenticated. The
    runtime accepts /protocol/proof-pack with no X-API-Key. If the MCP wrapper
    re-introduces a client-side api_key requirement, anonymous proofs become
    unreachable through the documented Claude Desktop / Cursor / Cline path —
    a contract regression rather than a wire bug.

    This gate creates an anonymous proof through the wrapper, verifies it via
    the public verify path (chain_integrity), and verifies the exported bundle
    offline via aigentsy-verify (verified). Both must hold.

    Requires aigentsy-verify to be installed in the same environment.
    """
    if os.environ.get("AIGENTSY_SKIP_LIVE") == "1":
        print("  [skip] AIGENTSY_SKIP_LIVE=1")
        return

    try:
        from aigentsy_verify import verify_bundle, fetch_public_key
    except ImportError:
        raise AssertionError(
            "aigentsy-verify is required for the anonymous-proof gate. "
            "Install with: pip install aigentsy-verify"
        )

    server = importlib.import_module("aigentsy_mcp.server")

    # Disposable agent identity for attribution (no api_key supplied below)
    reg = json.loads(server.aigentsy_register(
        agent_name="mcp_anon_proof_gate",
        capabilities="research",
    ))
    agent_id = reg["agent_id"]

    # Anonymous proof creation — no api_key
    pp = json.loads(server.aigentsy_proof_pack(
        agent_username=agent_id,
        scope_summary="anonymous-proof gate",
        api_key="",
    ))
    deal_id = pp.get("deal_id")
    proof_hash = pp.get("proof_hash")
    assert deal_id, f"anonymous proof_pack returned no deal_id: {pp}"
    assert proof_hash, f"anonymous proof_pack returned no proof_hash: {pp}"

    # Public verify path (no auth)
    v = json.loads(server.aigentsy_verify(deal_id=deal_id))
    assert v.get("chain_integrity") is True, (
        f"public verify rejected anonymous proof: {v}"
    )

    # Offline verifier on the exported bundle
    bundle = json.loads(server.aigentsy_export(deal_id=deal_id))
    public_key = fetch_public_key()
    result = verify_bundle(bundle, public_key_base64=public_key)
    assert result.get("verified") is True, (
        f"aigentsy-verify rejected the anonymous bundle. result={result}"
    )
    steps = result.get("steps", {})
    failed = [name for name, step in steps.items() if not step.get("passed")]
    assert not failed, (
        f"aigentsy-verify reported failed/skipped checks on anonymous bundle: "
        f"{failed}. full steps={steps}"
    )


def test_boot_no_immediate_crash():
    proc = subprocess.Popen(
        [sys.executable, "-m", "aigentsy_mcp"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        proc.wait(timeout=3)
        stdout, stderr = proc.communicate()
        raise AssertionError(
            f"Server exited prematurely (rc={proc.returncode})\n"
            f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=2)


if __name__ == "__main__":
    print("Running aigentsy-mcp smoke test...")
    test_imports()
    print("  imports ok")
    test_tool_count()
    print("  all 13 tool functions present")
    test_fastmcp_signatures_valid()
    print("  all 13 tool wrappers register with FastMCP (no InvalidSignature)")
    test_export_bundle_is_verifiable()
    print("  exported bundle verified end-to-end (5/5 checks)")
    test_anonymous_proof_is_verifiable()
    print("  anonymous proof publicly verifiable end-to-end")
    test_boot_no_immediate_crash()
    print("  server boots without crash")
    print("\nAll smoke tests passed.")
