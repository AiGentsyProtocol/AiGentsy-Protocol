#!/usr/bin/env python3
"""
AiGentsy CLI — command-driven developer path.

Usage:
    python cli.py init           # Register agent, save credentials
    python cli.py stamp "work"   # Create a ProofPack
    python cli.py verify DEAL_ID # Verify a proof bundle
    python cli.py settle DEAL_ID # Settle a deal
    python cli.py status         # Show agent status
    python cli.py demo           # Run full proof→verify→export flow
"""

import argparse
import json
import os
import sys

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)

BASE = os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com")
CRED_FILE = os.path.expanduser("~/.aigentsy_credentials.json")


def _load_creds():
    if os.path.exists(CRED_FILE):
        with open(CRED_FILE) as f:
            return json.load(f)
    return {}


def _save_creds(creds):
    with open(CRED_FILE, "w") as f:
        json.dump(creds, f, indent=2)
    os.chmod(CRED_FILE, 0o600)


def _client():
    creds = _load_creds()
    c = httpx.Client(base_url=BASE, timeout=30.0)
    return c, creds


def cmd_init(args):
    """Register a new agent and save credentials locally."""
    c, _ = _client()
    name = args.name or input("Agent name: ").strip()
    r = c.post("/protocol/register", json={"name": name, "capabilities": ["general"]}).json()
    if not r.get("api_key"):
        print("Registration failed:", json.dumps(r, indent=2))
        return
    creds = {"agent_id": r["agent_id"], "api_key": r["api_key"], "base": BASE}
    _save_creds(creds)
    print(f"Agent registered: {r['agent_id']}")
    print(f"API key saved to {CRED_FILE}")
    print(f"OCS: {r.get('ocs', 0)} | Tier: {r.get('tier', 'restricted')}")


def cmd_stamp(args):
    """Create a ProofPack."""
    c, creds = _client()
    if not creds.get("api_key"):
        print("Run 'aigentsy init' first.")
        return
    desc = args.description or input("Deliverable description: ").strip()
    r = c.post("/protocol/stamp", json={
        "agent_id": creds["agent_id"], "description": desc,
    }).json()
    if r.get("ok"):
        print(f"ProofPack created: {r['deal_id']}")
        print(f"Proof URL: {r.get('proof_url', '')}")
        print(f"Verify URL: {r.get('verify_url', '')}")
    else:
        print("Failed:", json.dumps(r, indent=2))


def cmd_verify(args):
    """Verify a proof bundle."""
    c, _ = _client()
    r = c.get(f"/proof/{args.deal_id}/verify").json()
    if r.get("verified"):
        print(f"VERIFIED — chain integrity: {r.get('chain_integrity')}, events: {r.get('event_count')}")
    else:
        print(f"NOT VERIFIED — errors: {r.get('errors', [])}")


def cmd_settle(args):
    """Settle a deal."""
    c, creds = _client()
    if not creds.get("api_key"):
        print("Run 'aigentsy init' first.")
        return
    r = c.post("/protocol/settle", json={
        "deal_id": args.deal_id, "amount_usd": args.amount,
        "to_agent": creds["agent_id"], "provider": "balance",
    }, headers={"X-API-Key": creds["api_key"]}).json()
    print(json.dumps(r, indent=2))


def cmd_status(args):
    """Show current agent status."""
    creds = _load_creds()
    if not creds.get("agent_id"):
        print("No agent registered. Run 'aigentsy init'.")
        return
    c, _ = _client()
    r = c.get(f"/protocol/reputation/{creds['agent_id']}").json()
    print(f"Agent: {creds['agent_id']}")
    print(f"Base: {creds.get('base', BASE)}")
    print(f"OCS: {r.get('ocs', '?')} | Tier: {r.get('tier', '?')}")


def cmd_demo(args):
    """Run full proof→verify→export demo."""
    c, creds = _client()
    if not creds.get("api_key"):
        print("Registering new agent...")
        r = c.post("/protocol/register", json={"name": "cli_demo", "capabilities": ["demo"]}).json()
        creds = {"agent_id": r["agent_id"], "api_key": r["api_key"], "base": BASE}
        _save_creds(creds)
        print(f"  Agent: {r['agent_id']}")

    print("\n1. Creating ProofPack...")
    p = c.post("/protocol/proof-pack", json={
        "agent_username": creds["agent_id"], "vertical": "marketing",
        "proof_type": "creative_preview", "scope_summary": "CLI demo proof",
        "proof_data": {"preview_url": "https://example.com/demo.jpg", "asset_type": "graphic",
                       "timestamp": "2026-01-01T00:00:00Z"},
    }).json()
    if not p.get("ok"):
        print("  Failed:", p)
        return
    print(f"  Deal: {p['deal_id']}")

    print("\n2. Verifying...")
    v = c.get(f"/proof/{p['deal_id']}/verify").json()
    print(f"  Verified: {v.get('verified')} | Chain: {v.get('chain_integrity')} | Events: {v.get('event_count')}")

    print("\n3. Exporting bundle...")
    b = c.get(f"/proof/{p['deal_id']}").json()
    print(f"  Proofs: {b.get('proof_count')} | Events: {b.get('event_count')}")

    print(f"\nDone. View: {BASE}/proof/{p['deal_id']}")


def main():
    from aigentsy import __version__
    parser = argparse.ArgumentParser(prog="aigentsy", description="AiGentsy CLI")
    parser.add_argument("-V", "--version", action="version", version=f"aigentsy {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Register agent")
    p_init.add_argument("--name", default="")

    p_stamp = sub.add_parser("stamp", help="Create ProofPack")
    p_stamp.add_argument("description", nargs="?", default="")

    p_verify = sub.add_parser("verify", help="Verify proof")
    p_verify.add_argument("deal_id")

    p_settle = sub.add_parser("settle", help="Settle deal")
    p_settle.add_argument("deal_id")
    p_settle.add_argument("--amount", type=float, default=0)

    p_status = sub.add_parser("status", help="Agent status")
    sub.add_parser("demo", help="Full demo flow")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    {"init": cmd_init, "stamp": cmd_stamp, "verify": cmd_verify,
     "settle": cmd_settle, "status": cmd_status, "demo": cmd_demo}[args.command](args)


if __name__ == "__main__":
    main()
