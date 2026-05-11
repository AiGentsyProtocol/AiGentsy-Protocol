"""
AiGentsy MCP Tool Server
=========================

Exposes AiGentsy settlement primitives as MCP (Model Context Protocol) tools.
Any MCP-compatible agent runtime (Claude, Cursor, Cline, OpenAI Agents SDK)
can discover and invoke AiGentsy settlement without SDK installation.

Tools:
    aigentsy_register     — Register an AI agent, receive agent_id + API key
    aigentsy_proof_pack   — Submit proof bundle for a deal
    aigentsy_settle       — Settle a deal with exactly-once guarantee
    aigentsy_verify       — Verify a proof bundle's chain integrity
    aigentsy_export       — Export a portable v1 proof bundle for offline verification

Usage:
    # Run as stdio server (for Claude Desktop, Cursor, etc.)
    python -m adapters.mcp_server

    # Or use mcp CLI
    mcp run adapters/mcp_server.py

Configuration:
    Set AME_BASE env var to override the default API base URL.
    Set AME_API_KEY env var to provide a default API key.
"""

import json
import os

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    raise ImportError(
        "MCP Python SDK required. Install with: pip install 'mcp[cli]'"
    )

from aigentsy_mcp.client import AiGentsyClient

# ── Config ──

AME_BASE = os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com")
AME_API_KEY = os.getenv("AME_API_KEY", "")

mcp = FastMCP(
    "aigentsy-settlement",
    instructions="AiGentsy Settlement Protocol — proof bundle verification, "
                "exactly-once settlement, portable verification bundles, "
                "and RFC 6962 Merkle transparency log for AI agent work.",
)


def _client(api_key: str = "") -> AiGentsyClient:
    key = api_key or AME_API_KEY
    return AiGentsyClient(AME_BASE, api_key=key)


def _require(name: str, value):
    """Raise ValueError if a required arg is empty, None, or whitespace-only."""
    if value is None:
        raise ValueError(f"{name} is required")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{name} is required (got empty string)")
    return value


# ── Tools ──


@mcp.tool()
def aigentsy_register(
    agent_name: str,
    capabilities: str = "marketing",
) -> str:
    """Register a new AI agent on the AiGentsy settlement protocol.

    Returns agent_id, API key, OCS tier, and escrow requirement.
    Save the API key — it is required for proof-pack and settle operations.

    Args:
        agent_name: Display name for the agent (e.g. "design_agent_v2")
        capabilities: Comma-separated list of capabilities (e.g. "marketing,design,code")
    """
    _require("agent_name", agent_name)
    client = _client()
    result = client.register(agent_name, capabilities=capabilities.split(","))
    return json.dumps({
        "agent_id": result.get("agent_id"),
        "api_key": result.get("api_key"),
        "tier": result.get("tier"),
        "ocs": result.get("ocs"),
        "escrow_requirement": result.get("escrow_requirement"),
        "protocol_fee": result.get("protocol_fee"),
    })


@mcp.tool()
def aigentsy_proof_pack(
    agent_username: str,
    scope_summary: str,
    api_key: str,
    vertical: str = "marketing",
    proof_type: str = "research_summary",
    proof_url: str = "",
) -> str:
    """Submit proof bundle for a deal on the AiGentsy protocol.

    Creates a ProofPack with cryptographic hashing and scope locking.
    Returns deal_id, proof_hash, and estimated_price.

    Args:
        agent_username: Your agent_id from registration
        scope_summary: Description of the work completed
        api_key: Your API key from registration
        vertical: Service vertical (marketing, design, code, research, etc.)
        proof_type: Type of proof. Default research_summary only requires
            a timestamp (auto-injected). Other proof_types may require
            additional fields in proof_data — see PROOF_TYPES in proof_pipe.
        proof_url: URL to proof artifact (optional)
    """
    from datetime import datetime, timezone

    _require("agent_username", agent_username)
    _require("scope_summary", scope_summary)
    _require("api_key", api_key)
    client = _client(api_key)
    proof_data = {"timestamp": datetime.now(timezone.utc).isoformat()}
    result = client.create_proof_pack(
        agent_username=agent_username,
        vertical=vertical,
        proof_type=proof_type,
        scope_summary=scope_summary,
        proof_data=proof_data,
        attachment_url=proof_url,
    )
    return json.dumps({
        "deal_id": result.get("deal_id"),
        "proof_hash": result.get("proof_hash"),
        "estimated_price": result.get("estimated_price"),
        "scope_lock_hash": result.get("scope_lock_hash"),
    })


@mcp.tool()
def aigentsy_settle(
    deal_id: str,
    amount: float,
    actor_id: str,
    counterparty_id: str,
    api_key: str,
    proof_hash: str = "",
) -> str:
    """Settle a deal with exactly-once guarantee.

    Triggers fee deduction, payout routing, and transparency log entry.
    Settlement is idempotent — replaying the same request returns the same result.
    Returns gross, net, fees, and settlement event details.

    Args:
        deal_id: The deal_id from proof-pack
        amount: Settlement amount in USD
        actor_id: Seller agent_id (who did the work)
        counterparty_id: Buyer agent_id (who pays)
        api_key: Your API key
        proof_hash: Proof hash from proof-pack (for verification)
    """
    _require("deal_id", deal_id)
    _require("actor_id", actor_id)
    _require("counterparty_id", counterparty_id)
    _require("api_key", api_key)
    client = _client(api_key)
    result = client.settle(
        deal_id=deal_id,
        amount_usd=amount,
        to_agent=counterparty_id,
        proof_hash=proof_hash,
    )
    return json.dumps({
        "ok": result.get("ok"),
        "deal_id": deal_id,
        "gross": result.get("gross"),
        "net": result.get("net"),
        "protocol_fee": result.get("protocol_fee"),
        "platform_fee": result.get("platform_fee"),
        "events_emitted": result.get("events_emitted"),
    })


@mcp.tool()
def aigentsy_verify(deal_id: str) -> str:
    """Verify a deal's proof bundle chain integrity.

    Checks hash chain integrity, Merkle inclusion, and proof validity.
    This is a public endpoint — no API key required.
    Returns chain_integrity status and verification details.

    Args:
        deal_id: The deal_id to verify
    """
    _require("deal_id", deal_id)
    client = _client()
    result = client.verify_proof_bundle(deal_id)
    return json.dumps({
        "chain_integrity": result.get("chain_integrity"),
        "chain_hash": result.get("chain_hash"),
        "proof_count": result.get("proof_count"),
        "event_count": result.get("event_count"),
        "merkle_root": result.get("merkle_root"),
    })


@mcp.tool()
def aigentsy_export(deal_id: str) -> str:
    """Export a portable v1 proof bundle for offline verification.

    Returns a self-contained bundle with:
    - Proof records
    - Hash-chained event log
    - RFC 6962 Merkle inclusion proof
    - Ed25519 signed tree head
    - Bundle hash (SHA-256)

    The bundle can be verified offline with zero access to AiGentsy's servers.
    See the Proof Bundle Spec at https://aigentsy.com/data/proof_bundle_spec.md

    Args:
        deal_id: The deal_id to export
    """
    _require("deal_id", deal_id)
    client = _client()
    result = client.get_proof_bundle(deal_id)
    return json.dumps(result, default=str)


# ── v1.2+ Tools ──


@mcp.tool()
def aigentsy_proof_chain(deal_id: str) -> str:
    """Get proof chain provenance for a deal.

    Shows parent proofs (who this proof builds on) and child proofs
    (who builds on this proof). Useful for tracing supply chains.

    Args:
        deal_id: The deal_id to query provenance for
    """
    _require("deal_id", deal_id)
    client = _client()
    result = client.get_proof_chain(deal_id)
    return json.dumps(result, default=str)


@mcp.tool()
def aigentsy_settle_multi(
    deal_id: str,
    total_amount: float,
    splits_json: str,
    api_key: str,
) -> str:
    """Multi-party settlement with N-way splits.

    Settles a deal across multiple agents atomically. Each agent receives
    their share minus protocol fees.

    Args:
        deal_id: The deal_id to settle
        total_amount: Total settlement amount in USD
        splits_json: JSON array of splits: [{"agent_id":"...", "role":"...", "share":0.5}, ...]
        api_key: Your API key
    """
    _require("deal_id", deal_id)
    _require("splits_json", splits_json)
    _require("api_key", api_key)
    client = _client(api_key)
    splits = json.loads(splits_json)
    result = client.settle_multi(deal_id, total_amount_usd=total_amount, splits=splits)
    return json.dumps(result, default=str)


@mcp.tool()
def aigentsy_attestation(agent_id: str, api_key: str) -> str:
    """Issue a portable reputation attestation (W3C Verifiable Credential).

    Creates a signed credential attesting the agent's OCS score, tier,
    and settlement history. The credential is portable — other ecosystems
    can verify it using AiGentsy's public Ed25519 key.

    Args:
        agent_id: Agent to issue attestation for
        api_key: Your API key
    """
    _require("agent_id", agent_id)
    _require("api_key", api_key)
    client = _client(api_key)
    result = client.issue_attestation(agent_id)
    return json.dumps(result, default=str)


@mcp.tool()
def aigentsy_fee_tiers(placeholder: str = "") -> str:
    """Get the volume-based fee tier schedule.

    Shows the 4 fee tiers (Starter, Growth, Scale, Enterprise)
    and their rates. Higher settlement volume = lower fees.
    """
    client = _client()
    result = client.get_fee_tiers()
    return json.dumps(result, default=str)


@mcp.tool()
def aigentsy_create_webhook(
    url: str,
    events: str,
    api_key: str,
    secret: str = "",
) -> str:
    """Register a webhook for protocol events.

    Receive POST notifications when proof, settlement, or lifecycle
    events occur. 17 event types available. Use "*" for all events.

    Args:
        url: HTTPS callback URL
        events: Comma-separated event types (e.g. "proof.created,settled") or "*" for all
        api_key: Your API key
        secret: Optional shared secret for HMAC signature verification
    """
    _require("url", url)
    _require("events", events)
    _require("api_key", api_key)
    client = _client(api_key)
    event_list = ["*"] if events == "*" else [e.strip() for e in events.split(",")]
    result = client.create_webhook(url, events=event_list, secret=secret or None)
    return json.dumps(result, default=str)


# ── v1.1 Acceptance Gate Tools ──


@mcp.tool()
def aigentsy_acceptance_submit(
    deal_id: str,
    api_key: str,
    downstream_action: str = "settle",
    review_deadline_seconds: int = 0,
) -> str:
    """Submit verified output for acceptance review before downstream action.

    Gates settlement, release, or completion behind explicit accept/reject.
    Requires a ProofPack to exist for the deal first.

    Args:
        deal_id: The deal_id with a verified proof
        api_key: Your API key
        downstream_action: Action on accept: settle, release, complete, publish
        review_deadline_seconds: Optional deadline in seconds (0 = no deadline)
    """
    _require("deal_id", deal_id)
    _require("api_key", api_key)
    client = _client(api_key)
    result = client.acceptance_submit(
        deal_id, downstream_action=downstream_action,
        review_deadline_seconds=review_deadline_seconds,
    )
    return json.dumps(result, default=str)


@mcp.tool()
def aigentsy_acceptance_decide(
    acceptance_id: str,
    decision: str,
    api_key: str,
    reason: str = "",
    checks_passed: str = "",
    checks_failed: str = "",
) -> str:
    """Record accept or reject decision on a pending acceptance gate.

    Accepted outputs trigger the configured downstream action (settle, release, etc.).
    Rejected outputs trigger hold or escalation.

    Args:
        acceptance_id: The acceptance_id from submit
        decision: 'accept' or 'reject'
        api_key: Your API key
        reason: Reason for decision
        checks_passed: Comma-separated checks that passed (optional)
        checks_failed: Comma-separated checks that failed (optional)
    """
    _require("acceptance_id", acceptance_id)
    _require("decision", decision)
    _require("api_key", api_key)
    client = _client(api_key)
    passed = [c.strip() for c in checks_passed.split(",") if c.strip()] if checks_passed else []
    failed = [c.strip() for c in checks_failed.split(",") if c.strip()] if checks_failed else []
    result = client.acceptance_decide(
        acceptance_id, decision, reason=reason,
        checks_passed=passed, checks_failed=failed,
    )
    return json.dumps(result, default=str)


@mcp.tool()
def aigentsy_acceptance_status(deal_id: str) -> str:
    """Get acceptance gate status for a deal.

    Returns the acceptance record if one exists, or null if no gate
    has been created. Public endpoint — no API key required.

    Args:
        deal_id: The deal_id to check
    """
    _require("deal_id", deal_id)
    client = _client()
    result = client.acceptance_status(deal_id)
    return json.dumps(result, default=str)


# ── Resources ──


@mcp.resource("aigentsy://protocol/info")
def protocol_info() -> str:
    """AiGentsy protocol information, settlement vocabulary, and verification URLs."""
    return json.dumps({
        # Core protocol info
        "name": "AiGentsy Settlement Protocol",
        "version": "1.3.0",
        "fee": "2.8% + $0.28 per settlement (volume tiers: 0.8%-2.8%)",
        "registration": "free",
        "verification": "free (public, no auth)",
        "proof_bundle_spec": "https://aigentsy.com/data/proof_bundle_spec.md",
        "conformance_vectors": "https://aigentsy.com/data/conformance_vectors.json",
        "transparency_log": "https://aigentsy.com/data/log_public_key.json",
        "trust_center": "https://aigentsy.com/trust",
        # Settlement vocabulary
        "proof_standard": "aigentsy_proof_bundle_v1",
        "bundle_spec_version": "1.0.0",
        "attestation_version": "1.0.0",
        "hash_algorithm": "SHA-256",
        "signing_algorithm": "Ed25519",
        "transparency_log_standard": "RFC6962",
        "log_id": "aigentsy_settlement_log_v1",
        "rails": ["stripe", "paypal", "balance"],
        "currencies": ["USD"],
        "settlement_modes": ["api", "mcp"],
        "trust_score": "OCS",
        "trust_tiers": ["restricted", "probation", "standard", "trusted", "elite"],
        # Verification URLs
        "verify_api": f"{AME_BASE}/protocol/verify",
        "verify_ui": "https://aigentsy.com/verify",
        "public_key_url": f"{AME_BASE}/protocol/merkle/public-key",
        "sth_url": f"{AME_BASE}/protocol/merkle/latest",
        "attestation_url_template": f"{AME_BASE}/protocol/agents/{{agent_id}}/attestation",
    })


@mcp.resource("aigentsy://protocol/vocabulary")
def protocol_vocabulary() -> str:
    """Machine-readable settlement vocabulary: spec versions, enums, constants."""
    return json.dumps({
        "vocabulary_version": "1.0.0",
        "spec_versions": {
            "bundle_spec": "1.0.0",
            "attestation": "1.0.0",
            "settlement_instruction": "1.0.0",
        },
        "enums": {
            "proof_types": [
                "pos_receipt", "booking_confirmation", "delivery_signature",
                "completion_photo", "invoice_paid", "creative_preview",
                "landing_preview", "ad_mock", "copy_preview",
                "test_results", "diff_preview", "demo_link",
                "endpoint_preview",
            ],
            "protocol_stages": [
                "opportunity_found", "proof_ready", "go_approved",
                "payment_authorized", "fulfillment_started",
                "delivered", "settled", "outcome_recorded",
                "dispute_opened",
            ],
            "settlement_rails": ["stripe", "paypal", "balance"],
            "trust_tiers": [
                "restricted", "probation", "standard", "trusted", "elite",
            ],
            "destination_types": [
                "bank_payout", "card_payout", "email_payout",
                "marketplace_disbursement", "wallet_payout",
                "balance_transfer",
            ],
        },
        "constants": {
            "hash_algorithm": "SHA-256",
            "signing_algorithm": "Ed25519",
            "transparency_log_standard": "RFC6962",
            "log_id": "aigentsy_settlement_log_v1",
            "key_id": "aigentsy_log_signer_v1",
            "proof_standard": "aigentsy_proof_bundle_v1",
        },
    })


# ── Entry Point ──


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
