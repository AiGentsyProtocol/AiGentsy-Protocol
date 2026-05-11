"""Smoke test for aigentsy-mcp.

Confirms:
* Package imports cleanly
* Server module has main() entry point
* All 13 tool functions exist
* FastMCP accepts every tool signature (no InvalidSignature, no leading-_ params)
* Server boots via python -m aigentsy_mcp without immediate crash

Does NOT test live runtime calls.
Live MCP Inspector registration is a manual post-merge check.
"""

import asyncio
import importlib
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
    test_boot_no_immediate_crash()
    print("  server boots without crash")
    print("\nAll smoke tests passed.")
