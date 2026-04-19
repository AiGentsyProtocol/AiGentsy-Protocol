#!/usr/bin/env python3
"""
Example: Verify an AiGentsy agent attestation offline.

Usage:
    python verify_attestation.py AGENT_ID
    python verify_attestation.py attestation.json
"""

import json
import sys
import urllib.request

from aigentsy_verify import verify_attestation, fetch_public_key

RUNTIME_URL = "https://aigentsy-ame-runtime.onrender.com"


def fetch_attestation(agent_id: str) -> dict:
    """Fetch attestation from the runtime API."""
    url = f"{RUNTIME_URL}/protocol/agents/{agent_id}/attestation"
    print(f"Fetching attestation from {url}")
    resp = urllib.request.urlopen(url, timeout=15)
    return json.loads(resp.read())


def main():
    if len(sys.argv) < 2:
        print("Usage: python verify_attestation.py <AGENT_ID | attestation.json>")
        sys.exit(1)

    source = sys.argv[1]

    # Load attestation
    if source.endswith(".json"):
        with open(source) as f:
            data = json.load(f)
    else:
        data = fetch_attestation(source)

    attestation = data.get("attestation", data)
    signature = data.get("signature", "")
    algorithm = data.get("algorithm", "Ed25519")

    print(f"Agent: {attestation.get('agent_id', 'unknown')}")
    print(f"OCS:   {attestation.get('ocs_score', 'N/A')}")
    print(f"Tier:  {attestation.get('tier', 'N/A')}")
    print(f"Algo:  {algorithm}")

    if not signature:
        print("\nNo signature found — cannot verify.")
        sys.exit(1)

    # Fetch public key
    try:
        public_key = fetch_public_key()
    except Exception as e:
        print(f"\nCould not fetch public key: {e}")
        sys.exit(1)

    # Verify
    ok = verify_attestation(attestation, signature, public_key)

    print(f"\n{'=' * 40}")
    print(f"SIGNATURE: {'VALID' if ok else 'INVALID'}")
    print(f"{'=' * 40}")

    if not ok:
        print("The attestation signature could not be verified.")
        print("This may mean the attestation was tampered with,")
        print("or the signing key has changed.")


if __name__ == "__main__":
    main()
