"""Smoke test for aigentsy-mcp.

Confirms:
* Package imports cleanly
* Server module has main() entry point
* All 10 tool functions exist
* Server boots via python -m aigentsy_mcp without immediate crash

Does NOT test live runtime calls.
Live MCP Inspector registration is a manual post-merge check.
"""

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
    }
    actual_tools = {name for name in expected_tools if hasattr(mod, name)}
    missing = expected_tools - actual_tools
    assert not missing, f"Missing tools: {missing}"


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
    print("  all 10 tool functions present")
    test_boot_no_immediate_crash()
    print("  server boots without crash")
    print("\nAll smoke tests passed.")
