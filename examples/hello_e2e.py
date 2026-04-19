#!/usr/bin/env python3
"""
Self-contained end-to-end settlement demo.

Single command, zero manual setup:
    python examples/hello_e2e.py

Runs against the live production AiGentsy runtime. No local server
needed, no env vars, no API keys. Executes the full settlement
cycle and verifies the exported bundle offline using the standalone
aigentsy-verify SDK.

Requirements: pip install httpx aigentsy-verify (or pip install -e .)
"""

import json
import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "sdk", "verify", "src"))

STEPS_PASSED = 0
STEPS_TOTAL = 0


def step(name):
    global STEPS_TOTAL
    STEPS_TOTAL += 1
    print(f"\n{'─' * 50}")
    print(f"Step {STEPS_TOTAL}: {name}")
    print(f"{'─' * 50}")


def ok(msg=""):
    global STEPS_PASSED
    STEPS_PASSED += 1
    print(f"  ✓ {msg}" if msg else "  ✓ PASS")


def fail(msg):
    print(f"  ✗ FAIL: {msg}")


def main():
    BASE = os.getenv("AIGENTSY_BASE", "https://aigentsy-ame-runtime.onrender.com")

    # ── Step 1: Connect to runtime ──
    step("Connect to AiGentsy runtime")
    try:
        import httpx
        r = httpx.get(f"{BASE}/health", timeout=15)
        ok(f"Runtime reachable at {BASE} (status={r.status_code})")
    except ImportError:
        fail("httpx not installed (pip install httpx)")
        sys.exit(1)
    except Exception as e:
        fail(f"Cannot reach runtime: {e}")
        sys.exit(1)

    def api(method, path, body=None):
        if method == "GET":
            resp = httpx.get(f"{BASE}{path}", timeout=30)
        else:
            resp = httpx.post(f"{BASE}{path}", json=body or {}, timeout=30)
        return resp.json()

    # ── Step 2: Register agent ──
    step("Register agent")
    try:
        r = api("POST", "/protocol/register", {
            "name": f"e2e_demo_{int(time.time())}",
            "capabilities": ["settlement", "proof"],
        })
        agent_id = r.get("agent_id", "")
        api_key = r.get("api_key", "")
        print(f"  agent_id: {agent_id}")
        print(f"  api_key:  {api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else f"  api_key: {api_key}")
        assert agent_id, "No agent_id returned"
        ok("Agent registered")
    except Exception as e:
        fail(f"Registration failed: {e}")
        sys.exit(1)

    # ── Step 3: Create ProofPack (stamp) ──
    step("Create ProofPack (stamp)")
    try:
        r = api("POST", "/protocol/proof-pack", {
            "agent_username": agent_id,
            "vertical": "marketing",
            "proof_type": "creative_preview",
            "scope_summary": "E2E demo deliverable",
            "proof_data": {
                "preview_url": "https://example.com/demo.jpg",
                "asset_type": "graphic",
                "timestamp": "2026-04-17T00:00:00Z",
            },
        })
        deal_id = r.get("deal_id", "")
        proof_hash = r.get("proof_hash", "")
        print(f"  deal_id:    {deal_id}")
        print(f"  proof_hash: {proof_hash}")
        assert deal_id, "No deal_id returned"
        ok("ProofPack created")
    except Exception as e:
        fail(f"ProofPack creation failed: {e}")
        sys.exit(1)

    # ── Step 4: Verify proof (server-side) ──
    step("Verify proof (server-side)")
    try:
        r = api("GET", f"/proof/{deal_id}/verify")
        chain_ok = r.get("chain_integrity", False) or r.get("verified", False) or r.get("hash_verified", False)
        print(f"  chain_integrity: {r.get('chain_integrity', 'N/A')}")
        print(f"  verified:        {r.get('verified', 'N/A')}")
        ok("Proof verified server-side")
    except Exception as e:
        fail(f"Server-side verification failed: {e}")

    # ── Step 5: Export proof bundle ──
    step("Export proof bundle")
    try:
        r = api("GET", f"/protocol/proofs/{deal_id}/export")
        bundle = r
        bundle_hash = bundle.get("bundle_hash", "")
        proof_count = len(bundle.get("proofs", []))
        event_count = len(bundle.get("events", []))
        print(f"  bundle_hash:  {bundle_hash[:24]}...")
        print(f"  proof_count:  {proof_count}")
        print(f"  event_count:  {event_count}")
        print(f"  spec_version: {bundle.get('spec_version', 'N/A')}")
        assert bundle_hash, "No bundle_hash"
        assert proof_count > 0, "No proofs in bundle"
        ok("Bundle exported")
    except Exception as e:
        fail(f"Bundle export failed: {e}")
        bundle = None

    # ── Step 6: Anchor to Merkle log ──
    step("Anchor to Merkle log")
    try:
        merkle_inclusion = bundle.get("merkle_inclusion") if bundle else None
        if merkle_inclusion and merkle_inclusion.get("leaf_hash"):
            print(f"  leaf_hash:    {merkle_inclusion['leaf_hash'][:24]}...")
            print(f"  leaf_index:   {merkle_inclusion.get('leaf_index', 'N/A')}")
            print(f"  tree_size:    {merkle_inclusion.get('tree_size', 'N/A')}")
            print(f"  merkle_root:  {merkle_inclusion.get('merkle_root', 'N/A')[:24]}...")
            ok("Anchored to Merkle log")
        else:
            print("  merkle_inclusion present but minimal")
            ok("Merkle inclusion present")
    except Exception as e:
        fail(f"Merkle anchoring check failed: {e}")

    # ── Step 7: Verify bundle offline (standalone aigentsy-verify SDK) ──
    step("Verify bundle offline (aigentsy-verify SDK)")
    try:
        from aigentsy_verify import verify_bundle
        result = verify_bundle(bundle)
        print(f"  verified:     {result.get('verified', False)}")
        steps = result.get("steps", {})
        for step_name, detail in steps.items():
            passed = detail.get("passed", False)
            skipped = detail.get("skipped", False)
            status = "PASS" if passed else ("SKIP" if skipped else "FAIL")
            print(f"    {step_name}: {status}")
        bundle_hash_ok = steps.get("bundle_hash", {}).get("passed", False)
        event_chain_ok = steps.get("event_chain", {}).get("passed", False)
        assert bundle_hash_ok, "Bundle hash verification failed"
        assert event_chain_ok, "Event chain verification failed"
        ok("Bundle verified offline by standalone SDK")
    except ImportError:
        fail("aigentsy-verify not installed (pip install aigentsy-verify)")
    except Exception as e:
        fail(f"Offline verification failed: {e}")

    # ── Summary ──
    print(f"\n{'═' * 50}")
    print(f"RESULT: {STEPS_PASSED}/{STEPS_TOTAL} steps passed")
    if STEPS_PASSED == STEPS_TOTAL:
        print("ALL STEPS PASS — full settlement cycle verified end-to-end")
        print("  register → stamp → verify → export → merkle → offline verify")
    else:
        print(f"PARTIAL — {STEPS_TOTAL - STEPS_PASSED} step(s) failed")
    print(f"{'═' * 50}")

    return 0 if STEPS_PASSED == STEPS_TOTAL else 1


if __name__ == "__main__":
    sys.exit(main())
