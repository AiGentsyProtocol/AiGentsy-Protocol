#!/usr/bin/env python3
"""
Example: Verify an AiGentsy proof bundle offline.

Usage:
    python verify_bundle.py bundle.json
    python verify_bundle.py --deal-id DEAL_ID
"""

import json
import sys
import urllib.request

from aigentsy_verify import verify_bundle, fetch_public_key

RUNTIME_URL = "https://aigentsy-ame-runtime.onrender.com"


def load_bundle(source: str) -> dict:
    """Load bundle from file path or fetch by deal_id."""
    if source.startswith("deal_") or source.startswith("DEAL_"):
        url = f"{RUNTIME_URL}/protocol/proof-bundle/{source}"
        print(f"Fetching bundle from {url}")
        resp = urllib.request.urlopen(url, timeout=15)
        return json.loads(resp.read())

    with open(source) as f:
        return json.load(f)


def main():
    if len(sys.argv) < 2:
        print("Usage: python verify_bundle.py <bundle.json | --deal-id DEAL_ID>")
        sys.exit(1)

    source = sys.argv[1]
    if source == "--deal-id" and len(sys.argv) > 2:
        source = sys.argv[2]

    # Load bundle
    bundle = load_bundle(source)
    print(f"Bundle: deal_id={bundle.get('deal_id')}, spec={bundle.get('spec_version')}")

    # Fetch public key for STH verification
    try:
        public_key = fetch_public_key()
        print(f"Public key fetched (algorithm: Ed25519)")
    except Exception as e:
        print(f"Could not fetch public key ({e}) — STH step will be skipped")
        public_key = ""

    # Verify
    result = verify_bundle(bundle, public_key_base64=public_key)

    # Display results
    print(f"\n{'=' * 50}")
    print(f"VERDICT: {'PASS' if result['verified'] else 'FAIL'}")
    print(f"{'=' * 50}")
    print(f"Deal: {result['deal_id']}")
    print(f"Spec: {result.get('spec_version', 'legacy')}")
    print(f"Proofs: {result.get('proof_count', 0)}")
    print(f"Events: {result.get('event_count', 0)}")
    print()

    for step_name, detail in result["steps"].items():
        if detail.get("skipped"):
            status = "SKIP"
        elif detail["passed"]:
            status = "PASS"
        else:
            status = "FAIL"
        print(f"  {step_name:20s} {status}")

        if not detail.get("passed") and not detail.get("skipped"):
            if "errors" in detail:
                for err in detail["errors"]:
                    print(f"    - {err}")
            if "computed" in detail and "claimed" in detail:
                print(f"    computed: {detail['computed']}")
                print(f"    claimed:  {detail['claimed']}")


if __name__ == "__main__":
    main()
