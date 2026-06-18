"""
AiGentsy MCP Tool Server — Settlement Signal Beacon (Layer 1)
==============================================================

AiGentsy helps connected agents recognize when work needs proof,
verification, acceptance, settlement, export, or auditable handoff —
advisory, consent-by-installation, never broadcast.

Exposes AiGentsy settlement primitives as MCP (Model Context Protocol)
tools. Any MCP-compatible agent runtime (Claude Desktop, Cursor, Cline,
OpenAI Agents SDK) can discover and invoke AiGentsy settlement without
SDK installation. Tool descriptions are trigger-aware — each lead with
"Use this when..." so a host LLM can recognize the WORK MOMENT, not
just the operation.

Tools:
    aigentsy_register          — register an AI agent before settleable work
    aigentsy_proof_pack        — produce a ProofPack at the handoff moment
    aigentsy_settle            — record value-moves exactly-once after proof + acceptance
    aigentsy_verify            — verify a counterparty's proof before relying on the work
    aigentsy_export            — export a portable proof bundle for offline / audit / partner
    aigentsy_proof_chain       — trace dependencies across multi-step / multi-agent work
    aigentsy_settle_multi      — split an accepted deal's value among multiple agents
    aigentsy_attestation       — vouch for an agent's reputation outside AiGentsy
    aigentsy_fee_tiers         — estimate protocol cost before quoting
    aigentsy_create_webhook    — subscribe to event-driven updates on proof / settlement / lifecycle
    aigentsy_accept            — record an ACCEPTED decision on a deal (G2; attribution-only)
    aigentsy_reject            — record a REJECTED decision on a deal (G2; attribution-only)
    aigentsy_settlement_signal — ADVISORY meta-tool: classify a plain-language work summary
                                 into the likely AiGentsy stage. Conservative by design:
                                 no API call, no state change, no settlement triggered;
                                 defaults to applicable=false when uncertain.

Resources:
    aigentsy://protocol/info                 — protocol metadata + verification URLs
    aigentsy://protocol/vocabulary           — enums, constants, spec versions
    aigentsy://protocol/settlement-signals   — machine-readable trigger vocabulary +
                                                consent boundary + non-goals (Layer 1)
    aigentsy://protocol/agent-system-prompt  — canonical settlement-native agent
                                                system prompt v0.1 (file-backed from
                                                prompts/settlement_native_agent_system_prompt.md)

Consent boundary:
    MCP is consent-by-installation. This beacon surfaces signals INSIDE
    an authorized MCP session. It never contacts unaffiliated agents,
    never broadcasts, never initiates outreach, never moves money,
    never settles without proof + acceptance.

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
from pathlib import Path
from typing import Any, Dict

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    raise ImportError(
        "MCP Python SDK required. Install with: pip install 'mcp[cli]'"
    )

from aigentsy_mcp.client import AiGentsyClient

# Canonical source of truth for the settlement-native agent system prompt.
# The aigentsy://protocol/agent-system-prompt MCP resource serves this file
# byte-for-byte. Keeping the prompt in a tracked .md file (not inline) means
# the resource body and the human-readable mirror cannot drift.
_AGENT_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "settlement_native_agent_system_prompt.md"
)

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

    **Use this when** an AI agent needs a protocol identity and API key
    before producing settleable work — i.e., before its first ProofPack
    or settlement. Onboarding step; one-time per agent. Save the
    returned API key — it is required for proof-pack and settle
    operations.

    Returns agent_id, API key, OCS tier, and escrow requirement.

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
    proof_type: str = "creative_preview",
    proof_url: str = "",
) -> str:
    """Submit a proof bundle for a deal on the AiGentsy protocol — the
    handoff moment.

    **Use this when** an agent has produced a deliverable that needs
    PROOF before acceptance, payment, release, deployment, or handoff.
    This is the canonical "proof at handoff" entry point: it creates a
    cryptographically hashed, scope-locked ProofPack that downstream
    counterparties can verify before they accept or pay.

    Creates a ProofPack with cryptographic hashing and scope locking.
    Returns deal_id, proof_hash, and estimated_price.

    Args:
        agent_username: Your agent_id from registration
        scope_summary: Description of the work completed
        api_key: Your API key from registration
        vertical: Service vertical (marketing, design, code, research, etc.)
        proof_type: Type of proof (creative_preview, test_results, code_diff, etc.)
        proof_url: URL to proof artifact (optional)
    """
    _require("agent_username", agent_username)
    _require("scope_summary", scope_summary)
    _require("api_key", api_key)
    client = _client(api_key)
    proof_data = {"asset_type": "deliverable"}
    if proof_url:
        proof_data["preview_url"] = proof_url
    result = client.create_proof_pack(
        agent_username=agent_username,
        vertical=vertical,
        proof_type=proof_type,
        scope_summary=scope_summary,
        proof_data=proof_data,
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
    """Settle a deal with exactly-once guarantee — the value-moves moment.

    **Use this when** value is ready to move between counterparties
    AFTER proof has been submitted and acceptance has occurred. This is
    "settlement when value moves" — the protocol's value-transfer
    primitive. Settlement is idempotent: replaying the same request
    returns the same result, so safe to retry. Do NOT call this before
    a ProofPack exists; do NOT call this before the counterparty has
    accepted.

    Triggers fee deduction, payout routing, and transparency log entry.
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
        deal_id, amount, actor_id, counterparty_id,
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
    """Verify a deal's proof bundle chain integrity — the acceptance gate.

    **Use this when** an agent or system is about to ACCEPT, PAY FOR,
    DEPLOY, RELEASE, or otherwise RELY on another agent's work. This is
    "verification at acceptance" — the public, no-auth-required check
    that establishes whether the counterparty's proof is real before
    the relying party commits to it. Call this BEFORE paying, before
    merging code, before deploying a release, before accepting a
    handoff.

    Checks hash chain integrity, Merkle inclusion, and proof validity.
    No API key required. Returns chain_integrity status and verification
    details.

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
    """Export a portable v1 proof bundle for offline verification — the
    auditable-handoff moment.

    **Use this when** a proof must travel OUTSIDE AiGentsy: offline
    verification, partner review, regulatory audit, archive, or
    cross-ecosystem handoff. The exported bundle is self-contained and
    can be verified with zero server access. Use this AFTER a ProofPack
    exists for the deal.

    Returns a self-contained bundle with:
    - Proof records
    - Hash-chained event log
    - RFC 6962 Merkle inclusion proof
    - Ed25519 signed tree head
    - Bundle hash (SHA-256)

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
    """Get proof-chain provenance for a deal — multi-step / multi-agent
    dependency tracing.

    **Use this when** an agent or auditor must trace DEPENDENCIES
    across multi-step or multi-agent work — i.e., when the current
    deliverable was built on a prior agent's proof and that lineage
    matters for acceptance, attribution, or settlement. Returns parent
    proofs (what this builds on) and child proofs (what builds on this).

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
    """Multi-party settlement with N-way splits — multi-contributor
    value-moves moment.

    **Use this when** one accepted deal must split value among MULTIPLE
    agents/contributors atomically — e.g., a bounty completed by a
    team, a multi-agent supply chain, a creator + curator split. Like
    `aigentsy_settle`, this is "settlement when value moves," but for
    N-way splits. Do NOT call before proof + acceptance.

    Each agent receives their share minus protocol fees, atomically.

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
    result = client.settle_multi(deal_id, total_amount, splits)
    return json.dumps(result, default=str)


@mcp.tool()
def aigentsy_attestation(agent_id: str, api_key: str) -> str:
    """Issue a portable reputation attestation (W3C Verifiable Credential)
    — reputation portability.

    **Use this when** an agent's reputation / outcome history must be
    VOUCHED FOR OUTSIDE AiGentsy — e.g., presenting credentials to a
    non-AiGentsy marketplace, partner platform, regulator, or
    cross-ecosystem registry. Other ecosystems verify the credential
    against AiGentsy's public Ed25519 key without trusting AiGentsy.

    Creates a signed credential attesting the agent's OCS score, tier,
    and settlement history.

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
def aigentsy_fee_tiers() -> str:
    """Get the volume-based fee tier schedule — fee-aware quoting.

    **Use this when** an agent is about to QUOTE a price or ROUTE
    settlement and needs to estimate the protocol cost before
    committing — i.e., to factor protocol fees into the quote, or to
    decide which counterparty to route a multi-party deal through.
    Informational; no auth required.

    Shows the 4 fee tiers (Starter, Growth, Scale, Enterprise) and their
    rates. Higher settlement volume = lower fees.
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
    """Register a webhook for protocol events — event-driven reactivity.

    **Use this when** an agent or system needs EVENT-DRIVEN UPDATES on
    proof creation, verification, acceptance, settlement, lifecycle
    transitions, or downstream changes — i.e., a reactive integration
    instead of polling. Useful for orchestrators that need to know the
    instant a counterparty's proof lands or a settlement clears.

    Receive POST notifications when protocol events occur. 17 event
    types available. Use "*" for all events.

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


# ── G2: Vault Wiring — MCP acceptance tools ──
#
# Two thin wrappers — `aigentsy_accept` + `aigentsy_reject` — that close
# the last sellability gap from the Pass 44 Vault wiring audit. Before
# G2, MCP-native agents had no way to record an ACCEPTED / REJECTED
# decision through MCP, though the same operations were fully wired
# through the SDK / HTTP API. The MCP layer adds NO new backend
# behavior: each tool simply calls the EXISTING acceptance methods on
# the rich SDK (sdk/aigentsy/src/aigentsy/client.py) which in turn hits
# the live endpoints:
#
#   POST /protocol/acceptance/submit             (auto-submit branch)
#   POST /protocol/acceptance/{id}/accept        (decide=accept)
#   POST /protocol/acceptance/{id}/reject        (decide=reject)
#   GET  /protocol/acceptance/deal/{deal_id}     (deal→acceptance lookup)
#
# OPTION-3 POSTURE PRESERVED.
#   The rich SDK's `decide_acceptance` branches client-side: no-key
#   → attribution-only via the legacy endpoint; key + keypair supplied
#   → signed via /protocol/event/{prepare,submit}; key + signing failure
#   → fail-CLOSED block (Stage 7-B "Option 3"). The MCP runtime cannot
#   carry a per-reviewer Ed25519 keypair through to a remote backend
#   call — so by construction, MCP review is always attribution-only.
#   Calling the legacy endpoint directly is exactly what
#   `decide_acceptance` would do when no keypair is supplied
#   (sdk/aigentsy/src/aigentsy/client.py:_decide_acceptance_attribution_only).
#   The Option-3 block path therefore cannot fire from MCP; if any
#   future backend posture starts gating attribution-only behind a
#   block, the HTTP error is surfaced verbatim, never swallowed.
#
# FAILURE SURFACING.
#   Every non-200 from the backend (401 / 403 / 404 / 409 / 422 / 500)
#   is surfaced as a JSON envelope with the status code + response body
#   + the deal/acceptance ids + the attempted decision. The host LLM
#   sees the failure honestly; nothing is rewritten into a fake success.
#
# TENANT SCOPING.
#   The reviewer's `api_key` is sent as `X-API-Key` on every backend
#   call. The backend's existing `_auth(x_api_key)` resolves the api_key
#   to one agent_id and that becomes the `reviewer_id` on the canonical
#   ACCEPTED / REJECTED event. The MCP layer adds no new auth surface
#   and bypasses nothing.


def _make_rich_client(api_key: str):
    """Build a rich-SDK client carrying the caller's api_key.

    Hoisted to module scope so tests can monkeypatch this factory with a
    fake client (no network) and so the two acceptance tools share one
    canonical construction path. Imports lazily because the rich SDK is
    an optional sibling dependency and we want the rest of the MCP
    server importable even if the rich SDK is unavailable.

    In the published-package build, `aigentsy` is a declared dependency
    (>=1.10.0) installed alongside this package, so `from aigentsy.client
    import AiGentsyClient` resolves directly — no sys.path manipulation
    is needed. The runtime-checkout sys.path hack used inside
    aigentsy-ame-runtime is intentionally omitted here.
    """
    from aigentsy.client import AiGentsyClient as _RichClient
    return _RichClient(AME_BASE, api_key=api_key)


def _decide_acceptance_via_mcp(
    decision: str,
    deal_id: str,
    api_key: str,
    reason: str,
    acceptance_id: str,
    downstream_action: str,
    auto_submit: bool,
) -> str:
    """Shared backend for aigentsy_accept / aigentsy_reject.

    Three steps, each calling EXISTING SDK methods:
      1. Resolve deal_id → acceptance_id via `rc.get_acceptance(deal_id)`
         (skipped if the caller supplied one).
      2. If no acceptance exists and `auto_submit=True`, call
         `rc.submit_for_acceptance(deal_id, downstream_action)`.
      3. Call `rc.accept_output(...)` or `rc.reject_output(...)` — the
         legacy attribution-only endpoint, the same surface
         `decide_acceptance(keypair=None)` would call (per the SDK
         source at _decide_acceptance_attribution_only).

    Any HTTP error is surfaced honestly with status_code + body — no
    swallowing.
    """
    import httpx

    try:
        rc = _make_rich_client(api_key)
    except ImportError as e:
        return json.dumps({
            "ok": False,
            "error": "sdk_unavailable",
            "detail": (
                "Rich SDK acceptance methods are not importable from "
                "this runtime: " + str(e)
            ),
        })

    try:
        # Step 1: resolve deal_id → acceptance_id if not supplied.
        if not acceptance_id:
            lookup = rc.get_acceptance(deal_id)
            acc = (lookup or {}).get("acceptance")
            if acc and acc.get("acceptance_id"):
                acceptance_id = acc["acceptance_id"]
            elif auto_submit:
                # Step 2: submit for acceptance to create the record.
                sub = rc.submit_for_acceptance(
                    deal_id, downstream_action=downstream_action,
                )
                sub_acc = (sub or {}).get("acceptance") or {}
                acceptance_id = sub_acc.get("acceptance_id", "")
                if not acceptance_id:
                    return json.dumps({
                        "ok": False,
                        "error": "submit_returned_no_acceptance_id",
                        "deal_id": deal_id,
                        "decision": decision,
                        "submit_response": sub,
                    })
            else:
                return json.dumps({
                    "ok": False,
                    "error": "no_pending_acceptance",
                    "deal_id": deal_id,
                    "decision": decision,
                    "detail": (
                        "No pending acceptance for this deal. Pass "
                        "auto_submit=True to create one automatically, "
                        "or pass acceptance_id directly if known."
                    ),
                })

        # Step 3: attribution-only accept / reject. The MCP layer cannot
        # carry a per-reviewer Ed25519 keypair so by construction this
        # is the same path `decide_acceptance(keypair=None)` would take.
        if decision == "accept":
            result = rc.accept_output(acceptance_id, reason=reason)
        else:
            result = rc.reject_output(acceptance_id, reason=reason)

        return json.dumps({
            "ok": result.get("ok"),
            "deal_id": deal_id,
            "acceptance_id": acceptance_id,
            "decision": decision,
            "reason": reason,
            "downstream_action": downstream_action,
            "signing_mode": "attribution_only",
            "acceptance": result.get("acceptance"),
            "downstream_triggered": result.get("downstream_triggered"),
        })

    except httpx.HTTPStatusError as e:
        # Honest failure surfacing. status_code + body land in the
        # response so the host LLM can react. Includes 401/403 (auth /
        # tenant), 404 (no acceptance), 409/422 (state / validation),
        # 5xx, and any future Option-3 block that the backend might
        # surface on this path. Never swallowed.
        body: Any
        try:
            body = e.response.json()
        except Exception:
            body = (e.response.text or "")[:512]
        return json.dumps({
            "ok": False,
            "error": "backend_error",
            "status_code": e.response.status_code,
            "detail": body,
            "deal_id": deal_id,
            "acceptance_id": acceptance_id,
            "decision": decision,
        })


@mcp.tool()
def aigentsy_accept(
    deal_id: str,
    api_key: str,
    reason: str = "",
    acceptance_id: str = "",
    downstream_action: str = "settle",
    auto_submit: bool = True,
) -> str:
    """Record an ACCEPT decision on a deal — the acceptance moment.

    **Use this when** a reviewer / buyer has reviewed a counterparty's
    proof and decides to ACCEPT the work — triggering the configured
    downstream action (settle, release, complete, publish). Produces a
    canonical ACCEPTED record on the deal's event chain that is
    Vault-visible, Merkle-anchored, and counted toward the reviewer's
    OCS reliability. Settlement proceeds normally after ACCEPTED.

    The MCP layer cannot carry a per-reviewer Ed25519 keypair, so this
    tool always uses the attribution-only acceptance path — the same
    path `decide_acceptance(keypair=None)` would take. For a per-actor
    SIGNED ACCEPTED event, use the signed-ingress flow directly
    (POST /protocol/event/{prepare,submit}); not available through MCP.

    Honest failure surfacing: any 4xx / 5xx from the backend (auth /
    tenant / not-found / state) is returned in the JSON envelope with
    its status code + response body — never swallowed.

    Args:
        deal_id: The deal to accept
        api_key: Your API key (reviewer's key — backend resolves to the
                 reviewer's agent_id and uses it as ACCEPTED.actor_id)
        reason: Optional human-readable reason
        acceptance_id: Optional — if the caller already has the
                       acceptance_id, the deal_id→acceptance lookup is
                       skipped
        downstream_action: Action on accept: settle / release / complete
                           / publish (default: settle)
        auto_submit: If True and no pending acceptance exists, the tool
                     auto-submits the deal for acceptance first (single
                     extra call to /protocol/acceptance/submit). Default
                     True so MCP-native agents see a one-call accept.
    """
    _require("deal_id", deal_id)
    _require("api_key", api_key)
    return _decide_acceptance_via_mcp(
        decision="accept",
        deal_id=deal_id,
        api_key=api_key,
        reason=reason,
        acceptance_id=acceptance_id,
        downstream_action=downstream_action,
        auto_submit=auto_submit,
    )


@mcp.tool()
def aigentsy_reject(
    deal_id: str,
    reason: str,
    api_key: str,
    acceptance_id: str = "",
    downstream_action: str = "settle",
    auto_submit: bool = True,
) -> str:
    """Record a REJECT decision on a deal — the dispute-handoff moment.

    **Use this when** a reviewer / buyer has reviewed a counterparty's
    proof and decides to REJECT — failing quality bar, scope drift,
    unverifiable claims, missing evidence. Produces a canonical
    REJECTED record on the deal's event chain that is Vault-visible
    (the rejected counterparty sees it on their `/vault/rejections`)
    and available as audit-defense evidence.

    `reason` is REQUIRED — the rejected counterparty needs to know why.
    Settlement is held on REJECTED; subsequent re-submit + acceptance
    can supersede it.

    The MCP layer cannot carry a per-reviewer Ed25519 keypair, so this
    tool always uses the attribution-only rejection path — the same
    path `decide_acceptance(keypair=None)` would take. For a per-actor
    SIGNED REJECTED event, use the signed-ingress flow directly
    (POST /protocol/event/{prepare,submit}); not available through MCP.

    Honest failure surfacing: any 4xx / 5xx from the backend (auth /
    tenant / not-found / state) is returned in the JSON envelope with
    its status code + response body — never swallowed.

    Args:
        deal_id: The deal to reject
        reason: REQUIRED reason for the rejection
        api_key: Your API key (reviewer's key — backend resolves to the
                 reviewer's agent_id and uses it as REJECTED.actor_id)
        acceptance_id: Optional — if the caller already has the
                       acceptance_id, the deal_id→acceptance lookup is
                       skipped
        downstream_action: Action context: settle / release / complete /
                           publish (default: settle)
        auto_submit: If True and no pending acceptance exists, the tool
                     auto-submits the deal for acceptance first. Default
                     True so MCP-native agents see a one-call reject.
    """
    _require("deal_id", deal_id)
    _require("reason", reason)
    _require("api_key", api_key)
    return _decide_acceptance_via_mcp(
        decision="reject",
        deal_id=deal_id,
        api_key=api_key,
        reason=reason,
        acceptance_id=acceptance_id,
        downstream_action=downstream_action,
        auto_submit=auto_submit,
    )


# ── Acceptance Runtime · Inference Acceptance Layer (Pass 82J) ──


@mcp.tool()
def aigentsy_inference_evaluate(
    prompt: str,
    raw_output: str,
    policy: str,
    consequence: str,
    api_key: str,
    required_evidence: str = "",
    risk_tier: str = "medium",
    model_metadata: str = "",
    expected_decision: str = "",
    intended_action: str = "",
) -> str:
    """Evaluate an LLM/agent/workflow output through the AiGentsy Acceptance Runtime
    — the consequence-middleware moment for ANY model.

    **Use this when** an AI, agent, or workflow has produced an output that
    might trigger consequence (payment, deployment, handoff, API action,
    procurement, publication, state change, etc.) and you need a runtime
    decision BEFORE the consequence fires. The Acceptance Runtime returns
    one of four decisions — ``accepted`` / ``rejected`` / ``retry`` /
    ``escalated`` — and one of three consequence states — ``allowed`` /
    ``blocked`` / ``held`` — recorded as a 4-event canonical lifecycle in
    the Vault. The signed evidence bundle is exportable through the existing
    ``/acceptance-runtime/runs/{run_id}/export`` path; the same 5-step
    offline verifier handles it.

    AiGentsy is the Consequence Layer: it does NOT call the model provider,
    does NOT improve the model's intelligence, and does NOT guarantee
    correctness — it governs whether the output is allowed to become
    downstream consequence under the policy + evidence the caller supplied.

    The MCP layer cannot carry a per-model-actor Ed25519 keypair, so this
    tool uses the platform-attested / attribution-only path (the same
    posture as ``aigentsy_accept`` / ``aigentsy_reject``). The runtime
    emits spec_version=2.0.0 events; per-actor signed inference bundles
    are planned in a future spec_version=3.0.0 sidecar (see the 82J
    planning doc).

    Args:
        prompt: The model prompt (or task description).
        raw_output: The model's raw output (text). The caller supplies it;
                    AiGentsy does not call the provider.
        policy: JSON string describing the policy. Required keys
                ``policy_id`` and ``required_evidence`` (a list of evidence
                field names the policy mandates). Optional ``summary``.
        consequence: JSON string describing the downstream consequence:
                     ``kind`` (payout / deploy / po_issue / api_call /
                     published_answer / etc.) + ``scope``. Optional
                     ``amount_usd``.
        api_key: Your AiGentsy API key (caller's identity context for the
                 evaluation; X-API-Key header).
        required_evidence: Optional JSON object mapping each evidence field
                           to its boolean check result. Empty → no evidence
                           is treated as present, policy_compliance falls to 0.
        risk_tier: ``low`` / ``medium`` / ``high`` (default ``medium``).
                   Drives the escalated branch when evidence is missing.
        model_metadata: Optional JSON object with ``name``, ``provider``,
                        ``notes``. Recorded verbatim on
                        ``INFERENCE_EVIDENCE_SUBMITTED.payload.model``.
        expected_decision: Optional — when set to one of
                           ``accepted`` / ``rejected`` / ``retry`` /
                           ``escalated``, the evaluator records that as
                           the canonical decision (used by demo/fixture
                           replay). Production callers leave this empty.
        intended_action: Optional human-readable description of WHAT the
                         consequence would actually trigger (e.g. "PATCH
                         /v1/customers/cust_2034 with renewal_date"). When
                         supplied, it is folded ADDITIVELY into the
                         outgoing ``consequence`` payload as
                         ``consequence.intended_action`` and lands on
                         ``INFERENCE_CONSEQUENCE_RECORDED.payload.intended_action``
                         for NEW evaluations only. Does NOT alter any
                         pre-existing event hash, bundle hash, signing
                         schema, or verifier behavior.
    """
    _require("prompt", prompt)
    _require("raw_output", raw_output)
    _require("policy", policy)
    _require("consequence", consequence)
    _require("api_key", api_key)

    # Parse the JSON string args. ValueError messages do NOT echo the
    # api_key or any other secret — the only structured content surfaced
    # is the user-supplied JSON shape they passed in.
    try:
        policy_obj = json.loads(policy) if isinstance(policy, str) else (policy or {})
    except Exception as e:
        raise ValueError(f"policy must be a JSON object string: {type(e).__name__}")
    try:
        consequence_obj = json.loads(consequence) if isinstance(consequence, str) else (consequence or {})
    except Exception as e:
        raise ValueError(f"consequence must be a JSON object string: {type(e).__name__}")
    required_evidence_obj: Dict[str, Any] = {}
    if required_evidence:
        try:
            required_evidence_obj = json.loads(required_evidence) if isinstance(required_evidence, str) else (required_evidence or {})
        except Exception as e:
            raise ValueError(f"required_evidence must be a JSON object string: {type(e).__name__}")
    model_metadata_obj: Dict[str, Any] = {}
    if model_metadata:
        try:
            model_metadata_obj = json.loads(model_metadata) if isinstance(model_metadata, str) else (model_metadata or {})
        except Exception as e:
            raise ValueError(f"model_metadata must be a JSON object string: {type(e).__name__}")

    client = _client(api_key)
    try:
        result = client.evaluate_inference(
            prompt=prompt,
            raw_output=raw_output,
            policy=policy_obj,
            consequence=consequence_obj,
            required_evidence=required_evidence_obj,
            risk_tier=risk_tier or "medium",
            model_metadata=model_metadata_obj,
            expected_decision=(expected_decision or None),
            intended_action=intended_action or "",
        )
    except Exception as e:
        # Honest failure surfacing — same posture as aigentsy_accept /
        # aigentsy_reject. Surface the failure shape via the response
        # envelope rather than raising. Never echo api_key or env vars.
        import httpx as _httpx
        if isinstance(e, _httpx.HTTPStatusError):
            try:
                body = e.response.json()
            except Exception:
                body = {"raw_text": (e.response.text or "")[:400]}
            return json.dumps({
                "ok": False,
                "error_class": "HTTPStatusError",
                "status_code": e.response.status_code,
                "response": body,
                "labels": ["mcp_inference_evaluation", "mcp_consequence_middleware", "acceptance_runtime"],
                "claim_boundary": {
                    "bring_any_model": True,
                    "does_not_call_model_provider": True,
                    "does_not_improve_model_intelligence": True,
                    "does_not_guarantee_correctness": True,
                    "governs_consequence": True,
                },
            })
        return json.dumps({
            "ok": False,
            "error_class": type(e).__name__,
            "safe_error": str(e)[:240],
            "labels": ["mcp_inference_evaluation", "mcp_consequence_middleware", "acceptance_runtime"],
            "claim_boundary": {
                "bring_any_model": True,
                "does_not_call_model_provider": True,
                "does_not_improve_model_intelligence": True,
                "does_not_guarantee_correctness": True,
                "governs_consequence": True,
            },
        })

    # Successful path — return a SANITIZED envelope. Never echo api_key
    # or any header/env-var material. Surface only the runtime-emitted
    # decision metadata + the public export path.
    run_id = result.get("run_id") or ""
    export_path = f"/acceptance-runtime/runs/{run_id}/export" if run_id else ""
    hoverstack = result.get("hoverstack") or {}
    envelope: Dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "run_id": run_id,
        "deal_id": result.get("deal_id"),
        "decision": result.get("decision"),
        "consequence_state": result.get("consequence_state"),
        "reason": result.get("reason"),
        "policy_compliance": result.get("policy_compliance"),
        "evidence_completeness": result.get("evidence_completeness"),
        "escalation_route": result.get("escalation_route"),
        "retry_remaining": result.get("retry_remaining"),
        "hoverstack_reuse_kind": hoverstack.get("reuse_kind"),
        "decision_envelope_ref": result.get("decision_envelope_ref"),
        "attestation_class": result.get("attestation_class"),
        "spec_version": result.get("spec_version"),
        "export_path": export_path,
        "labels": [
            "mcp_inference_evaluation",
            "mcp_consequence_middleware",
            "acceptance_runtime",
            "proofpack_export_available",
        ],
        "claim_boundary": {
            "bring_any_model": True,
            "does_not_call_model_provider": True,
            "does_not_improve_model_intelligence": True,
            "does_not_guarantee_correctness": True,
            "governs_consequence": True,
        },
    }
    if intended_action:
        envelope["intended_action"] = intended_action
    return json.dumps(envelope)


# ── Advisory Meta-Tool (Layer 1: Settlement Signal Beacon) ──
#
# `aigentsy_settlement_signal` is intentionally CONSERVATIVE: it is an
# advisory classifier that returns `applicable=false` whenever the
# evidence in the work_summary is ambiguous. A classifier that over-fires
# erodes host-LLM trust faster than no classifier at all. The cost of
# under-triggering is mildly unhelpful; the cost of over-triggering is
# trust-eroding. The implementation biases accordingly:
#
#   * defaults to applicable=false / confidence=low when uncertain
#   * applicable=true ONLY when the summary CLEARLY contains a
#     settlement-relevant work moment (deliverable-complete + counterparty
#     evaluation, explicit payment/release/deployment, multi-party split,
#     audit/export, or dispute language)
#   * suggested_message is null at low/medium confidence; at high
#     confidence it is phrased as a QUESTION, never an instruction
#   * rationale always names the matched trigger phrases (or states none
#     detected) — transparent, auditable, not a black box
#   * classification is simple deterministic rule logic over the
#     protocol_stages vocabulary; not ML, no model call, no network
#
# The tool MUST NOT: make any API call, write any file, emit any event,
# trigger any settlement, take any acceptance decision, run any
# background job, contact any unaffiliated agent. It returns advice
# inside the connected MCP session and stops.

# Module-level trigger vocabulary — the same surface exposed by the
# aigentsy://protocol/settlement-signals resource below. Keeping the data
# at module scope makes the classifier auditable (these are the ONLY
# trigger phrases that fire applicable=true).
_SETTLEMENT_SIGNAL_STAGES: Dict[str, Dict[str, Any]] = {
    "proof_ready": {
        "definition": (
            "Work has been completed and is about to be handed off; a "
            "ProofPack would be the next step before acceptance or payment."
        ),
        "high_confidence_triggers": [
            # Deliverable language paired with counterparty handoff / review / payment-pending.
            ("finished", "deliverable"),
            ("completed", "deliverable"),
            ("delivered", "review"),
            ("delivered", "payment"),
            ("ready for", "client review"),
            ("ready for", "buyer review"),
            ("ready for", "handoff"),
            ("handoff", "proof"),
            ("ship", "deliverable"),
            ("shipped", "client"),
        ],
        "next_tool": "aigentsy_proof_pack",
    },
    "verification_needed": {
        "definition": (
            "A relying party is about to act on, pay for, deploy, release, "
            "or accept another agent's work and needs to verify the proof first."
        ),
        "high_confidence_triggers": [
            ("verify", "before pay"),
            ("verify", "before accept"),
            ("verify", "before deploy"),
            ("verify", "before release"),
            ("buyer", "verify"),
            ("counterparty", "verify"),
            ("must verify", "work"),
            ("must verify", "deliverable"),
            ("check proof", "before"),
            ("audit", "before accept"),
        ],
        "next_tool": "aigentsy_verify",
    },
    "settlement_ready": {
        "definition": (
            "Proof exists, the counterparty has accepted, and value is "
            "ready to move — the settlement-when-value-moves moment."
        ),
        "high_confidence_triggers": [
            ("accepted", "payout"),
            ("accepted", "payment"),
            ("accepted", "settle"),
            ("approved", "payout"),
            ("approved", "payment"),
            ("ready", "payout"),
            ("payout", "approved"),
            ("release", "payment"),
            ("clear", "payment"),
        ],
        "next_tool": "aigentsy_settle",
    },
    "settlement_ready_multi": {
        # Sub-stage of settlement_ready; reported with stage=settlement_ready
        # but next_tool=aigentsy_settle_multi when split language is present.
        "definition": (
            "Settlement-ready with multiple agents / contributors / "
            "creators sharing the value."
        ),
        "high_confidence_triggers": [
            ("split", "payout"),
            ("split", "payment"),
            ("multi-agent", "split"),
            ("multi-agent", "bounty"),
            ("multiple agents", "split"),
            ("multiple contributors", "split"),
            ("share", "payout"),
            ("bounty", "split"),
        ],
        "next_tool": "aigentsy_settle_multi",
    },
    "delivered_for_audit": {
        # Sub-stage of delivered; reported with stage=delivered but
        # next_tool=aigentsy_export when audit/external/offline language fires.
        "definition": (
            "Work is delivered AND must travel outside AiGentsy for "
            "offline / audit / partner / archive verification."
        ),
        "high_confidence_triggers": [
            ("external auditor", "proof"),
            ("auditor", "bundle"),
            ("offline", "verify"),
            ("offline", "verification"),
            ("partner", "verification"),
            ("archive", "proof"),
            ("regulator", "proof"),
            ("export", "proof bundle"),
        ],
        "next_tool": "aigentsy_export",
    },
    "dispute_opened": {
        "definition": (
            "A counterparty has raised an objection / dispute over the "
            "delivered work or the settlement."
        ),
        "high_confidence_triggers": [
            ("dispute",),
            ("disputed",),
            ("contest",),
            ("reject delivery",),
            ("refund request",),
        ],
        "next_tool": "aigentsy_verify",   # verify proof first; dispute resolution lives outside MCP
    },
}

# Negative triggers — when ANY of these are present in a summary, the
# classifier MUST stay applicable=false, regardless of other matches.
# These catch the "in-progress / brainstorming / drafting" cases that
# look settlement-adjacent but are actually pre-deliverable.
_SETTLEMENT_SIGNAL_NEGATIVE_TRIGGERS = [
    "brainstorm",
    "brainstorming",
    "drafting",
    "draft",
    "planning",
    "ideating",
    "ideation",
    "exploring",
    "considering",
    "thinking about",
    "wip",
    "work in progress",
    "in progress",
    "not yet delivered",
    "nothing delivered",
    "no proof yet",
    "haven't shipped",
    "have not shipped",
    "early stage",
]


def _classify_settlement_signal(work_summary: str) -> Dict[str, Any]:
    """Pure deterministic classifier. Conservative by design.

    Public separation from the @mcp.tool() wrapper so the same logic can
    be exercised directly in tests without touching the MCP transport.

    Returns the structured advisory envelope. NO network. NO state."""
    text = (work_summary or "").strip().lower()
    if not text:
        return {
            "applicable": False,
            "stage": "not_applicable",
            "confidence": "low",
            "rationale": "empty work_summary; nothing to classify",
            "next_tool": None,
            "suggested_message": None,
            "consent_boundary": (
                "Advisory inside an authorized MCP session. Does not contact unaffiliated agents."
            ),
        }

    # Negative-trigger gate: catches pre-deliverable / WIP language so
    # the classifier under-fires on ambiguous in-progress work.
    matched_negatives = [neg for neg in _SETTLEMENT_SIGNAL_NEGATIVE_TRIGGERS if neg in text]
    if matched_negatives:
        return {
            "applicable": False,
            "stage": "not_applicable",
            "confidence": "low",
            "rationale": (
                f"pre-deliverable / in-progress language detected: "
                f"{', '.join(repr(n) for n in matched_negatives)}; "
                f"no proof/acceptance/settlement trigger applies yet"
            ),
            "next_tool": None,
            "suggested_message": None,
            "consent_boundary": (
                "Advisory inside an authorized MCP session. Does not contact unaffiliated agents."
            ),
        }

    # Walk each stage's high-confidence triggers. A "trigger" is a tuple
    # of substrings ALL of which must be present (allowing simple
    # multi-phrase conditions like ("finished","deliverable") to fire
    # on "agent finished deliverable for client review" but NOT on
    # "finished a draft, no deliverable yet").
    for stage_label, stage_def in _SETTLEMENT_SIGNAL_STAGES.items():
        for trigger in stage_def["high_confidence_triggers"]:
            if all(phrase in text for phrase in trigger):
                # Map sub-stages to their canonical protocol_stages values.
                canonical_stage = (
                    "settlement_ready" if stage_label.startswith("settlement_ready")
                    else "delivered" if stage_label == "delivered_for_audit"
                    else stage_label
                )
                next_tool = stage_def["next_tool"]
                matched_phrases = " + ".join(repr(p) for p in trigger)
                suggested_message_by_stage = {
                    "proof_ready": (
                        "Does this completed deliverable need a ProofPack "
                        "before acceptance or payment?"
                    ),
                    "verification_needed": (
                        "Has the counterparty's proof bundle been verified "
                        "before acting on this work?"
                    ),
                    "settlement_ready": (
                        "Is this deal ready to settle now that proof + acceptance are in place?"
                    ),
                    "settlement_ready_multi": (
                        "Should this accepted deal settle as a multi-party split?"
                    ),
                    "delivered_for_audit": (
                        "Should the proof bundle be exported for offline / partner / audit review?"
                    ),
                    "dispute_opened": (
                        "Should the proof bundle be re-verified before further action on this dispute?"
                    ),
                }
                return {
                    "applicable": True,
                    "stage": canonical_stage,
                    "confidence": "high",
                    "rationale": f"matched: {matched_phrases}",
                    "next_tool": next_tool,
                    "suggested_message": suggested_message_by_stage[stage_label],
                    "consent_boundary": (
                        "Advisory inside an authorized MCP session. "
                        "Does not contact unaffiliated agents."
                    ),
                }

    # No high-confidence trigger matched. Conservative default.
    return {
        "applicable": False,
        "stage": "not_applicable",
        "confidence": "low",
        "rationale": (
            "no proof/acceptance/settlement/payment/release/deployment/handoff "
            "trigger phrase matched in work_summary"
        ),
        "next_tool": None,
        "suggested_message": None,
        "consent_boundary": (
            "Advisory inside an authorized MCP session. Does not contact unaffiliated agents."
        ),
    }


@mcp.tool()
def aigentsy_settlement_signal(work_summary: str) -> str:
    """ADVISORY: classify a plain-language work summary into the AiGentsy
    settlement stage that applies — IF any does.

    **Use this when** a host LLM or connected agent has described its
    current work in natural language and wants an advisory hint about
    whether an AiGentsy step (proof, verification, acceptance,
    settlement, export, dispute) is relevant RIGHT NOW.

    Conservative by design: this tool ERRS TOWARD applicable=false. It
    only returns applicable=true when the summary contains an explicit,
    high-confidence trigger phrase for a settlement-relevant work
    moment. When ambiguous (drafting, planning, WIP), it stays silent.

    Pure and local. NO API call, NO state change, NO settlement, NO
    network access. Advisory only — the host LLM remains the decision-
    maker. `suggested_message` is phrased as a QUESTION when present,
    never as an instruction. `rationale` always names the matched
    trigger phrases (or states none detected) so the classification is
    auditable.

    Returns a JSON envelope:
        {
          "applicable": bool,
          "stage": one of opportunity_found | proof_ready | verification_needed
                   | acceptance_needed | go_approved | delivered |
                   settlement_ready | settled | outcome_recorded |
                   dispute_opened | not_applicable,
          "confidence": "low" | "medium" | "high",
          "rationale": str (names matched triggers or states none),
          "next_tool": tool name or null,
          "suggested_message": question-form string at high confidence, else null,
          "consent_boundary": str (advisory-inside-MCP-session disclaimer)
        }

    Args:
        work_summary: Plain-language description of the agent's current
                       work moment (e.g., "agent finished deliverable for
                       client review, payment pending").
    """
    return json.dumps(_classify_settlement_signal(work_summary))


# ── Resources ──


@mcp.resource("aigentsy://protocol/info")
def protocol_info() -> str:
    """AiGentsy protocol information, settlement vocabulary, and verification URLs."""
    return json.dumps({
        # Core protocol info
        "name": "AiGentsy Settlement Protocol",
        # A2A Settlement Protocol API surface version — must match the value
        # advertised by GET /protocol/info on the runtime.
        "version": "1.0",
        "fee": "2.8% + $0.28 per settlement (volume tiers: 0.8%-2.8%)",
        "registration": "free",
        "verification": "free (public, no auth)",
        "proof_bundle_spec": "https://aigentsy.com/data/proof_bundle_spec.md",
        "conformance_vectors": "https://aigentsy.com/data/conformance_vectors.json",
        "transparency_log": "https://aigentsy.com/data/log_public_key.json",
        "trust_center": "https://aigentsy.com/trust",
        # Settlement vocabulary
        "proof_standard": "aigentsy_proof_bundle_v1",
        # Mirrors protocol/bundle_spec.SPEC_VERSION — the value the bundle
        # exporter actually emits. Update both together if the bundle format evolves.
        "bundle_spec_version": "2.0.0",
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
            # Mirrors protocol/bundle_spec.SPEC_VERSION — keep in sync with the
            # bundle exporter and with the bundle_spec_version field in
            # aigentsy://protocol/info above.
            "bundle_spec": "2.0.0",
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


@mcp.resource("aigentsy://protocol/settlement-signals")
def protocol_settlement_signals() -> str:
    """Machine-readable trigger vocabulary for the Settlement Signal Beacon
    (Layer 1). Stages, definitions, high-confidence trigger phrases,
    recommended next tool per stage, consent boundary, and explicit
    non-goals. Consumed by host LLMs that want to self-train against the
    same vocabulary the `aigentsy_settlement_signal` meta-tool uses."""
    # Reuse the same authoritative table the classifier uses; keeping
    # them in one place ensures the resource and the tool never drift.
    return json.dumps({
        "vocabulary_version": "1.0.0",
        "layer": "Layer 1 — Settlement Signal Beacon",
        "purpose": (
            "AiGentsy helps connected agents recognize when work needs "
            "proof, verification, acceptance, settlement, export, or "
            "auditable handoff. This resource declares the trigger "
            "vocabulary the advisory meta-tool uses, so host LLMs can "
            "self-classify with the same rules."
        ),
        "framing": (
            "Proof at handoff. Verification at acceptance. Settlement "
            "when value moves. Portable verification for partners, "
            "audit, and archive."
        ),
        "stages": {
            label: {
                "definition": defn["definition"],
                "high_confidence_triggers": [
                    list(trigger) for trigger in defn["high_confidence_triggers"]
                ],
                "next_tool": defn["next_tool"],
            }
            for label, defn in _SETTLEMENT_SIGNAL_STAGES.items()
        },
        "negative_triggers": list(_SETTLEMENT_SIGNAL_NEGATIVE_TRIGGERS),
        "negative_trigger_purpose": (
            "When ANY of these phrases is present in a work_summary, the "
            "advisory meta-tool stays applicable=false. They catch "
            "pre-deliverable / in-progress / drafting / planning language "
            "that looks settlement-adjacent but is not yet a settlement moment."
        ),
        "classification_posture": {
            "default": "applicable=false / confidence=low",
            "applicable_true_requires": (
                "an explicit high-confidence trigger phrase match "
                "AND no negative trigger present"
            ),
            "suggested_message_phrasing": (
                "Always a QUESTION, never an instruction. Returned only at "
                "confidence=high; null at low/medium."
            ),
            "rationale_contract": (
                "Always names the matched trigger phrases (or states "
                "explicitly that none were detected)."
            ),
            "bias": (
                "Under-triggering is mildly unhelpful; over-triggering is "
                "trust-eroding. The classifier biases toward under-triggering."
            ),
        },
        "consent_boundary": (
            "MCP is consent-by-installation. This beacon surfaces signals "
            "INSIDE an authorized MCP session that the host owner connected. "
            "It never contacts unaffiliated agents, never broadcasts, never "
            "initiates outreach."
        ),
        "non_goals": [
            "No broadcast to unaffiliated agents — full stop.",
            "No autonomous outreach, scraping, or background jobs.",
            "No payment custody — AiGentsy never holds counterparty funds via this beacon.",
            "No settlement without a ProofPack AND acceptance — the beacon advises, it does not authorize.",
            "No hidden prompting — every classification names the matched trigger phrases.",
            "No ML / model call inside the meta-tool — pure deterministic rule logic.",
            "Not a recommendation engine — does not push agents to settle work that does not need settling.",
        ],
        "host_llm_usage_hint": (
            "Call aigentsy_settlement_signal(work_summary) with a plain-language "
            "description of the agent's current work moment. If applicable=true "
            "and confidence=high, ask the owner the returned suggested_message "
            "before calling next_tool. If applicable=false, do nothing — there "
            "is no settlement-relevant moment to act on."
        ),
    })


@mcp.resource("aigentsy://protocol/agent-system-prompt")
def protocol_agent_system_prompt() -> str:
    """Canonical settlement-native agent system prompt v0.1.

    Returned read-only from prompts/settlement_native_agent_system_prompt.md
    in the runtime repo. File-backed so the human-readable mirror and the
    MCP resource cannot drift; the file is the single source of truth.

    Consumed by MCP hosts that want to inject a consent-bound, settlement-
    aware operating stance into agents they run. The prompt distinguishes
    drafts from handoff-ready work, frames verification as not-acceptance,
    requires acceptance before settlement, and explicitly disclaims
    broadcast / autonomous outreach / unaffiliated-agent contact.

    No network call. No API call. No state change. No outreach behavior.
    Reading this resource only opens and reads a local file.
    """
    return _AGENT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


# ── Entry Point ──


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
