"""End-to-end Tier-2 example for aigentsy-langgraph 0.3.0.

Demonstrates the signed-event flow against the live AiGentsy backend
using the new 0.3.0 nodes:

  1. Register a seller + enroll their Ed25519 keypair (enroll_key_node).
  2. Register a buyer + enroll their Ed25519 keypair.
  3. Seller submits a ProofPack (existing 0.2.0 node).
  4. Buyer signed-accepts via accept_node (Tier-2: signed event lands).
  5. Seller posts settle to trigger OUTCOME_RECORDED.
  6. outcome_receipt_node — fetch the signed OutcomeReceipt.
  7. Export the bundle; aigentsy-verify should pass 6/6 offline.

The private keys are generated locally, never transmitted to AiGentsy.
The script saves both keypairs to disposable temp files for the
duration of the run.

Requires: pip install 'aigentsy-langgraph[signed]'
"""

import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timezone

import httpx

from aigentsy_langgraph import (
    accept_node, enroll_key_node, outcome_receipt_node,
    proof_pack_node, register_node, settle_node, timeline_node,
)


BASE = os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def main():
    ts = int(time.time())
    workdir = tempfile.mkdtemp(prefix="lg030_e2e_")
    print(f"Tier-2 LangGraph e2e — using {workdir}")
    print(f"Backend: {BASE}\n")

    # ── (1) Register + enroll seller's signing key ─────────────────
    seller = await register_node({
        "agent_name": f"lg030_seller_{ts}",
        "capabilities": ["marketing"],
        "base_url": BASE,
    })
    print(f"[1a] seller registered: {seller['agent_id']}")
    seller = await enroll_key_node({
        **seller,
        "keypair_path": os.path.join(workdir, "seller.json"),
        "print_keypair_notice": False,
        "base_url": BASE,
    })
    if not seller.get("key_id"):
        raise SystemExit(f"seller enrollment failed: {seller}")
    print(f"[1b] seller key enrolled: key_id={seller['key_id']}")

    # ── (2) Register + enroll buyer's signing key ──────────────────
    buyer = await register_node({
        "agent_name": f"lg030_buyer_{ts}",
        "capabilities": ["marketing"],
        "base_url": BASE,
    })
    print(f"[2a] buyer registered: {buyer['agent_id']}")
    buyer = await enroll_key_node({
        **buyer,
        "keypair_path": os.path.join(workdir, "buyer.json"),
        "print_keypair_notice": False,
        "base_url": BASE,
    })
    if not buyer.get("key_id"):
        raise SystemExit(f"buyer enrollment failed: {buyer}")
    print(f"[2b] buyer key enrolled: key_id={buyer['key_id']}")

    # ── (3) Seller submits ProofPack ───────────────────────────────
    pp = await proof_pack_node({
        "agent_username": seller["agent_id"],
        "api_key": seller["api_key"],
        "vertical": "marketing",
        "proof_type": "creative_preview",
        "scope_summary": "Tier-2 LangGraph signed accept e2e",
        "proof_data": {
            "asset_type": "deliverable",
            "preview_url": "https://example.com/lg030.jpg",
            "timestamp": now_iso(),
        },
        "base_url": BASE,
    })
    deal_id = pp["deal_id"]
    print(f"[3] ProofPack created: deal_id={deal_id} "
          f"proof_hash={(pp.get('proof_hash') or '')[:16]}")

    # ── (4) Buyer signed-accepts ───────────────────────────────────
    accept_result = await accept_node({
        "deal_id": deal_id,
        "api_key": buyer["api_key"],
        "agent_id": buyer["agent_id"],
        "keypair": buyer["keypair"],
        "key_id": buyer["key_id"],
        "reason": "Tier-2 signed acceptance via LangGraph 0.3.0",
        "downstream_action": "settle",
        "base_url": BASE,
    })
    print(f"[4] accept_node: ok={accept_result.get('ok')} "
          f"signing_mode={accept_result.get('signing_mode')} "
          f"acceptance_id={accept_result.get('acceptance_id')}")
    if accept_result.get("signing_mode") != "signed":
        print(f"  full envelope: {json.dumps(accept_result, default=str)[:600]}")

    # ── (5) Seller records the SIGNED OUTCOME_RECORDED ─────────────
    # Per Stage 7-C, the performer (seller) signs OUTCOME_RECORDED;
    # actor_id=performer, counterparty_id=performer, payload.payer_id
    # is the actual buyer (so the receipt's buyer_id labels the payer,
    # not the performer). The adapter's send_signed_event helper from
    # signing.py drives the prepare/sign/submit ingress. The /protocol/
    # settle endpoint requires an authorization the test agents do not
    # hold, so we use the signed-event ingress directly — the
    # canonical Tier-2 way to record an outcome on the chain.
    from aigentsy_langgraph.client import AsyncAiGentsyClient
    from aigentsy_langgraph.signing import send_signed_event
    client = AsyncAiGentsyClient(BASE, api_key=seller["api_key"])
    try:
        outcome_event = await send_signed_event(
            client,
            deal_id=deal_id,
            event_type="OUTCOME_RECORDED",
            actor_id=seller["agent_id"],           # the SIGNER (performer)
            key_id=seller["key_id"],
            intent="authorized_consequence",
            keypair=seller["keypair"],
            counterparty_id=seller["agent_id"],    # preserves OCS/AIGx contracts
            amount=10.0,
            payload={"payer_id": buyer["agent_id"]},  # Stage-7-C
            source="graph_settlement",
        )
        print(f"[5] OUTCOME_RECORDED signed: "
              f"event_id={outcome_event.get('event_id', '?')[:16]}")
    except Exception as e:
        print(f"[5] OUTCOME_RECORDED via signed ingress FAILED: {e}")
    # Give the receipt builder a moment.
    await asyncio.sleep(2.0)

    # ── (6) Fetch the signed OutcomeReceipt ────────────────────────
    receipt = await outcome_receipt_node({
        "deal_id": deal_id,
        "base_url": BASE,
    })
    print(f"[6] outcome_receipt_node: receipt_state="
          f"{receipt.get('receipt_state')}")
    if receipt.get("receipt_state") == "present":
        r = receipt["outcome_receipt"]
        print(f"    buyer_id (payer):     {r['buyer_id']}")
        print(f"    seller_id (performer):{r['seller_id']}")
        sig = receipt["receipt_signature"]
        print(f"    algorithm: {sig['algorithm']} key_id: {sig['key_id']}")
    elif receipt.get("receipt_state") == "not_yet":
        print(f"    current_state: {receipt.get('current_state')}")

    # ── (7) Export bundle + show signing model ─────────────────────
    bundle = httpx.get(
        f"{BASE}/protocol/proofs/{deal_id}/export", timeout=15,
    ).json()
    print(f"[7] bundle export: spec_version={bundle.get('spec_version')} "
          f"bundle_hash={(bundle.get('bundle_hash') or '')[:16]}")
    print(f"    key_directory present: {bool(bundle.get('key_directory'))}")
    signed_events = [
        e for e in (bundle.get("events") or [])
        if (e.get("actor_signature") or {}).get("signature")
    ]
    print(f"    signed events: {len(signed_events)} of "
          f"{len(bundle.get('events') or [])}")
    if signed_events:
        for e in signed_events:
            print(f"      - {e['event_type']:<20} actor={e['actor_id']} "
                  f"key={e['actor_signature']['key_id']}")

    # Save the bundle for offline verification.
    bundle_path = os.path.join(workdir, "bundle.json")
    with open(bundle_path, "w") as f:
        json.dump(bundle, f, indent=2)
    print(f"\nbundle saved to {bundle_path}")
    print(f"deal_id={deal_id}")
    print(f"seller_id={seller['agent_id']}")
    print(f"buyer_id={buyer['agent_id']}")


if __name__ == "__main__":
    asyncio.run(main())
