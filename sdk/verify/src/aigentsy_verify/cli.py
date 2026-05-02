"""
aigentsy-verify CLI — Offline ProofPack verification from the command line.

Usage:
    aigentsy-verify bundle proofpack.json
    aigentsy-verify bundle proofpack.json --json
    aigentsy-verify bundle proofpack.json --strict
    aigentsy-verify bundle proofpack.json --fetch-key
    aigentsy-verify bundle proofpack.json --public-key key.pem
"""

import argparse
import json
import sys
from pathlib import Path

from aigentsy_verify import __version__, verify_bundle, load_public_key_from_file

_DEFAULT_KEY_URL = "https://aigentsy-ame-runtime.onrender.com/protocol/merkle/public-key"


def _load_bundle(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        with open(p) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(2)


def _fetch_public_key() -> str:
    try:
        from urllib.request import urlopen
        with urlopen(_DEFAULT_KEY_URL, timeout=10) as r:
            data = json.loads(r.read())
            return data.get("public_key_base64", "")
    except Exception as e:
        print(f"Warning: could not fetch public key: {e}", file=sys.stderr)
        return ""


def _status(passed: bool, skipped: bool = False, reason: str = "") -> str:
    if skipped:
        return f"SKIPPED ({reason})" if reason else "SKIPPED"
    return "PASS" if passed else "FAIL"


def cmd_bundle(args):
    bundle = _load_bundle(args.file)

    public_key_b64 = ""
    if args.public_key:
        try:
            public_key_b64 = load_public_key_from_file(args.public_key)
        except Exception as e:
            print(f"Error: cannot load public key: {e}", file=sys.stderr)
            sys.exit(2)
    elif args.fetch_key:
        public_key_b64 = _fetch_public_key()

    result = verify_bundle(bundle, public_key_base64=public_key_b64)

    if args.json:
        json.dump(result, sys.stdout, indent=2, default=str)
        print()
        sys.exit(0 if result["verified"] else 1)

    steps = result.get("steps", {})
    trace = bundle.get("agent_trace", [])
    level = result.get("verification_level", "unknown")

    print()
    print("AiGentsy ProofPack verification")
    print()
    print(f"  deal_id:          {result.get('deal_id', 'N/A')}")
    print(f"  spec_version:     {result.get('spec_version') or 'legacy'}")
    print(f"  proofs:           {result.get('proof_count', 0)}")
    print(f"  events:           {result.get('event_count', 0)}")
    print()

    bh = steps.get("bundle_hash", {})
    ec = steps.get("event_chain", {})
    mi = steps.get("merkle_inclusion", {})
    ss = steps.get("sth_signature", {})
    cr = steps.get("cross_reference", {})

    print(f"  bundle_hash:      {_status(bh.get('passed', False))}")
    print(f"  event_chain:      {_status(ec.get('passed', False))}  ({ec.get('event_count', 0)} events)")
    print(f"  merkle_inclusion: {_status(mi.get('passed', False), mi.get('skipped', False), 'no inclusion data')}")
    print(f"  sth_signature:    {_status(ss.get('passed', False), ss.get('skipped', False), 'no public key — use --fetch-key or --public-key')}")
    print(f"  cross_reference:  {_status(cr.get('passed', False), cr.get('skipped', False), 'no STH or inclusion')}")

    if trace:
        print(f"\n  agent_trace:      {len(trace)} roles")
        for t in trace:
            print(f"    {t.get('role', ''):22s} {t.get('event', '')}")

    print()
    verified = result["verified"]

    if args.strict and ss.get("skipped"):
        verified = False
        print(f"  verified:         false")
        print(f"  reason:           --strict requires STH signature (use --fetch-key or --public-key)")
    else:
        print(f"  verified:         {str(verified).lower()}")
        steps_run = result.get("steps_run", "?")
        steps_total = steps_run + result.get("steps_skipped", 0)
        print(f"  level:            {level} ({steps_run}/{steps_total} steps)")

    print()
    sys.exit(0 if verified else 1)


def main():
    # Handle bare `aigentsy-verify file.json` shortcut
    if len(sys.argv) >= 2 and sys.argv[1].endswith(".json"):
        sys.argv.insert(1, "bundle")

    parser = argparse.ArgumentParser(
        prog="aigentsy-verify",
        description="Standalone offline verification for AiGentsy ProofPack bundles.",
    )
    parser.add_argument("--version", action="version", version=f"aigentsy-verify {__version__}")

    sub = parser.add_subparsers(dest="command")

    bundle_p = sub.add_parser("bundle", help="Verify a ProofPack bundle JSON file")
    bundle_p.add_argument("file", help="Path to ProofPack bundle JSON")
    bundle_p.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    bundle_p.add_argument("--strict", action="store_true", help="Fail if STH signature verification is skipped")
    bundle_p.add_argument("--fetch-key", action="store_true", help="Fetch Ed25519 public key from AiGentsy runtime for STH verification")
    bundle_p.add_argument("--public-key", help="Path to Ed25519 public key PEM file")

    args = parser.parse_args()

    if args.command == "bundle":
        cmd_bundle(args)
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
