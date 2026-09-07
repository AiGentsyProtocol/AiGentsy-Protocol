"""LangGraph nodes wrapping AiGentsy Settlement Protocol operations."""

import os
from typing import Any, Dict
from .client import AsyncAiGentsyClient


def _get_client(state: Dict[str, Any]) -> AsyncAiGentsyClient:
    return AsyncAiGentsyClient(
        base_url=state.get("base_url", os.getenv(
            "AME_BASE", "https://aigentsy-ame-runtime.onrender.com")),
        api_key=state.get("api_key"),
    )


async def register_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Register an agent."""
    client = _get_client(state)
    result = await client.register(
        name=state.get("agent_name", "langgraph_agent"),
        capabilities=state.get("capabilities", ["marketing"]),
    )
    return {
        **state,
        "agent_id": result["agent_id"],
        "api_key": result["api_key"],
        "ocs": result.get("ocs"),
        "tier": result.get("tier"),
    }


async def proof_pack_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Create proof pack. Supports parent_proof_ids for proof chain linking."""
    client = _get_client(state)
    kwargs = {}
    if state.get("parent_proof_ids"):
        kwargs["parent_proof_ids"] = state["parent_proof_ids"]
    result = await client.create_proof_pack(
        agent_username=state["agent_username"],
        vertical=state.get("vertical", "marketing"),
        proof_type=state.get("proof_type", "creative_preview"),
        scope_summary=state.get("scope_summary", ""),
        proof_data=state.get("proof_data", {}),
        **kwargs,
    )
    return {
        **state,
        "deal_id": result["deal_id"],
        "quote_id": result["quote_id"],
        "scope_lock_hash": result["scope_lock_hash"],
        "proof_hash": result.get("proof_hash"),
        "estimated_price": result.get("estimated_price"),
        "parent_proof_ids": result.get("parent_proof_ids", []),
    }


async def auto_go_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-GO decision."""
    client = _get_client(state)
    result = await client.auto_go(
        deal_id=state["deal_id"],
        quote_id=state["quote_id"],
        buyer_id=state.get("buyer_id", ""),
        mandate_id=state.get("mandate_id"),
        seller_agent_id=state.get("agent_id"),
    )
    decision = result.get("decision", result.get("status", "unknown"))
    return {
        **state,
        "auto_go_decision": decision,
        "auto_go_approved": decision in ("go_approved", "AUTO_GO_APPROVED"),
    }


async def go_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Approve deal (GO)."""
    client = _get_client(state)
    result = await client.go(
        deal_id=state["deal_id"],
        quote_id=state["quote_id"],
        scope_lock_hash=state["scope_lock_hash"],
    )
    return {
        **state,
        "go_approved": result.get("ok", False),
        "payment_url": result.get("payment_url"),
        "amount": result.get("amount"),
        "go_key": result.get("go_key"),
    }


async def verify_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Verify proof via provider."""
    client = _get_client(state)
    result = await client.verify_proof(
        deal_id=state["deal_id"],
        proof_hash=state.get("proof_hash", ""),
        proof_type=state.get("proof_type", "test_results"),
        proof_data=state.get("verification_data", state.get("proof_data", {})),
    )
    verification = result.get("verification", {})
    return {
        **state,
        "verified": verification.get("verified", False),
        "verification_confidence": verification.get("confidence"),
        "verification_hash": verification.get("verification_hash"),
        "verification_provider": result.get("provider_used"),
    }


async def settle_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Settle deal."""
    client = _get_client(state)
    result = await client.settle(
        deal_id=state["deal_id"],
        amount=state["amount"],
        actor_id=state.get("actor_id", state.get("agent_id", "")),
        counterparty_id=state.get("counterparty_id", state.get("buyer_id", "")),
        proof_hash=state.get("proof_hash"),
    )
    return {**state, "settlement": result}


async def timeline_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch deal timeline."""
    client = _get_client(state)
    result = await client.get_timeline(state["deal_id"])
    return {**state, "timeline": result}


async def full_deal_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Full Proof -> GO -> Verify loop."""
    state = await proof_pack_node(state)
    state = await go_node(state)
    if state.get("go_approved"):
        state = await verify_node(state)
    state = await timeline_node(state)
    return state


async def settle_multi_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Multi-party settlement with N-way splits."""
    client = _get_client(state)
    result = await client.settle_multi(
        deal_id=state["deal_id"],
        total_amount=state["total_amount"],
        splits=state["splits"],
        provider=state.get("provider", "balance"),
        proof_hash=state.get("proof_hash"),
    )
    return {**state, "multiparty_settlement": result}


async def attestation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Issue a signed reputation attestation (W3C VC)."""
    client = _get_client(state)
    agent_id = state.get("agent_id", "")
    result = await client.issue_attestation(agent_id)
    return {
        **state,
        "attestation": result.get("credential"),
        "attestation_ok": result.get("ok", False),
    }


async def proof_chain_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Query proof chain provenance for a deal."""
    client = _get_client(state)
    result = await client.get_proof_chain(state["deal_id"])
    return {
        **state,
        "proof_chain": result.get("chain"),
        "proof_chain_parents": result.get("parents", []),
        "proof_chain_children": result.get("children", []),
    }


# ────────────────────────────────────────────────────────────────────
# 0.3.0 — Tier-2 parity: enroll_key / accept / reject / outcome_receipt
#
# All four nodes are ADDITIVE. The 0.2.0 surface above is byte-
# unchanged. The four new nodes preserve the Option-3 posture:
#
#   no-key                → attribution-only (Tier-1 ACCEPTED/REJECTED)
#   key + valid signature → signed (Tier-2 ACCEPTED/REJECTED, 6/6)
#   key + signing failure → structured block error, no event emitted,
#                           NEVER swallowed into ok=true.
#
# Honest labels: every emitted event carries its real
# ``signing_mode``. The unsigned base install only needs httpx; the
# signed path additionally needs the optional ``[signed]`` extra
# (``cryptography>=41.0``) and a client-side ``SigningKeypair``.
# ────────────────────────────────────────────────────────────────────


def _require_state(state: Dict[str, Any], *required: str) -> None:
    """Raise ValueError if any required state key is missing / blank.

    Mirrors the validation contract used by the MCP G2 tools
    (``adapters/mcp_server.py:_require``). Applied at the node
    boundary, before any backend call."""
    for name in required:
        v = state.get(name)
        if v is None:
            raise ValueError(f"{name} is required")
        if isinstance(v, str) and not v.strip():
            raise ValueError(f"{name} is required (got empty string)")


def _surface_http_error(
    exc, *, decision_or_action: str, deal_id: str = "",
    acceptance_id: str = "",
) -> Dict[str, Any]:
    """Structured failure envelope — mirrors the MCP G2 contract
    (adapters/mcp_server.py:_decide_acceptance_via_mcp). Caller passes
    an httpx.HTTPStatusError; we extract status + body + identifiers
    so the host LLM / orchestrator sees the failure honestly."""
    body: Any
    try:
        body = exc.response.json()
    except Exception:
        body = (getattr(exc.response, "text", "") or "")[:512]
    return {
        "ok": False,
        "error": "backend_error",
        "status_code": exc.response.status_code,
        "detail": body,
        "deal_id": deal_id,
        "acceptance_id": acceptance_id,
        "decision": decision_or_action,
    }


async def enroll_key_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a non-custodial Ed25519 keypair locally and enroll the
    PUBLIC half with the protocol.

    **Use this when** an agent will sign its own ACCEPTED / REJECTED /
    OUTCOME_RECORDED events (Tier-2). The keypair is generated on the
    user's host; the private key NEVER transmits to AiGentsy. Only the
    public half travels in the enrollment body; the body is screened
    by ``_assert_no_private_material`` before it crosses the wire.

    Requires the ``[signed]`` extra (``pip install
    'aigentsy-langgraph[signed]'``). The plain install raises a
    structured ``RuntimeError`` here with the install hint.

    State inputs:
        agent_id, api_key       (required — the agent enrolling)
        keypair_path            (optional — if set, save the private
                                 key to this file with 0600 perms;
                                 refuses to overwrite)
        actor_type              (default "agent")
        key_class               (default "production")
        print_keypair_notice    (default True — prints the non-
                                 custodial notice when a key is
                                 generated)

    State outputs:
        keypair                 SigningKeypair object (in-process only)
        key_id                  enrolled key_id from the backend
        public_key_base64       enrolled public half
        keypair_path            path saved to (if requested)
        signing_mode            "enrolled_locally"
        enrollment              full backend response (audit trail)
    """
    _require_state(state, "agent_id", "api_key")
    from .keypair import SigningKeypair, _assert_no_private_material
    kp = SigningKeypair.generate(
        print_notice=bool(state.get("print_keypair_notice", True)),
    )
    save_path = state.get("keypair_path")
    saved_path = None
    if save_path:
        saved_path = str(kp.save_to_file(save_path))

    body = kp.to_enrollment_body(
        actor_id=state["agent_id"],
        actor_type=state.get("actor_type", "agent"),
        key_class=state.get("key_class", "production"),
    )
    # Double-check at the node boundary; the body builder already
    # ran the same assertion, but a defense-in-depth re-check before
    # the HTTP call costs nothing.
    _assert_no_private_material(body, "enroll_key_node body")

    client = _get_client(state)
    try:
        result = await client.enroll_signing_key(
            actor_id=body["actor_id"],
            public_key_base64=body["public_key_base64"],
            actor_type=body["actor_type"],
            key_class=body["key_class"],
        )
    except Exception as e:
        return {
            **state,
            "ok": False,
            "error": "enrollment_failed",
            "detail": str(e),
            "signing_mode": "enrollment_failed",
        }

    return {
        **state,
        "keypair": kp,
        "key_id": result.get("key_id") or result.get("enrolled_key_id"),
        "public_key_base64": kp.public_key_base64,
        "keypair_path": saved_path,
        "signing_mode": "enrolled_locally",
        "enrollment": result,
    }


async def _resolve_or_create_acceptance(
    client, state: Dict[str, Any],
) -> str:
    """Step 1+2 of the MCP-G2 contract: resolve deal_id →
    acceptance_id (lookup first; auto-submit if absent and
    ``auto_submit`` is True). Raises ValueError on the
    auto_submit=False no-acceptance branch so the caller can return
    a clean structured envelope instead of throwing."""
    if state.get("acceptance_id"):
        return state["acceptance_id"]
    lookup = await client.get_acceptance_by_deal(state["deal_id"])
    acc = (lookup or {}).get("acceptance")
    if acc and acc.get("acceptance_id"):
        return acc["acceptance_id"]
    if not state.get("auto_submit", True):
        raise ValueError("no_pending_acceptance")
    sub = await client.submit_for_acceptance(
        state["deal_id"],
        downstream_action=state.get("downstream_action", "settle"),
    )
    sub_acc = (sub or {}).get("acceptance") or {}
    new_id = sub_acc.get("acceptance_id", "")
    if not new_id:
        raise ValueError(f"submit_returned_no_acceptance_id: {sub}")
    return new_id


async def accept_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Record an ACCEPT decision on a deal.

    **Use this when** the reviewer / buyer has reviewed a
    counterparty's proof and decides to ACCEPT, triggering the
    configured downstream action (settle / release / complete /
    publish). Produces a canonical ACCEPTED record — Vault-visible,
    Merkle-anchored, OCS-eligible.

    Option-3 posture (matches the SDK contract):
      - No keypair in state → attribution-only via
        ``/protocol/acceptance/{id}/accept``. Settlement proceeds.
        ``signing_mode = "attribution_only"``.
      - Keypair + key_id in state → signed via
        ``/protocol/event/{prepare,submit}`` (Tier-2). The bundle for
        this deal becomes ``spec_version=3.0.0`` and verifies 6/6.
        ``signing_mode = "signed"``.
      - Keypair present but the signed call fails (signature invalid,
        actor-key mismatch, etc.) → a structured ``backend_error``
        envelope is returned with ``signing_mode = "signed_block"``;
        no event is emitted. NEVER swallowed.

    State inputs (required):
        deal_id, api_key

    State inputs (optional):
        agent_id              (reviewer; used as actor_id on the
                               signed event)
        reason                (carried verbatim to the canonical event)
        acceptance_id         (skips the deal_id lookup if known)
        downstream_action     (settle | release | complete | publish)
        auto_submit           (default True — auto-submits the deal
                               for acceptance if none exists yet)
        keypair               (SigningKeypair from enroll_key_node)
        key_id                (the enrolled key_id paired with keypair)
    """
    _require_state(state, "deal_id", "api_key")
    return await _decide_via_node("accept", state)


async def reject_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Record a REJECT decision on a deal.

    **Use this when** the reviewer / buyer has reviewed a
    counterparty's proof and decides to REJECT — failing quality bar,
    scope drift, unverifiable claims, missing evidence. Produces a
    canonical REJECTED record — Vault-visible to the rejected
    counterparty (``/vault/rejections``), tamper-evident, and
    available as audit-defense evidence.

    ``reason`` is REQUIRED — the rejected counterparty needs to know
    why. Carried verbatim through to the backend body, into the
    canonical REJECTED event's ``payload.reason``, and surfaced on
    the rejected counterparty's Vault row.

    Same Option-3 posture as ``accept_node`` — see its docstring.

    State inputs (required): deal_id, reason, api_key
    State inputs (optional): same as accept_node.
    """
    _require_state(state, "deal_id", "reason", "api_key")
    return await _decide_via_node("reject", state)


async def _decide_via_node(
    decision: str, state: Dict[str, Any],
) -> Dict[str, Any]:
    """Shared body for accept_node / reject_node.

    Three steps:
      1. Resolve deal_id → acceptance_id (lookup; auto-submit if no
         acceptance and ``auto_submit=True``).
      2. If keypair + key_id present, send signed via
         ``send_signed_event`` (Tier-2). Otherwise call the legacy
         attribution-only endpoint (Tier-1).
      3. Surface backend HTTP errors as a structured envelope —
         status + body + IDs + attempted decision. No swallowed
         fake success.

    Reference: MCP G2 implementation at
    ``adapters/mcp_server.py:_decide_acceptance_via_mcp`` (same
    contract, different host).
    """
    import httpx
    client = _get_client(state)

    # Step 1 — resolve / auto-submit
    try:
        acceptance_id = await _resolve_or_create_acceptance(client, state)
    except ValueError as e:
        msg = str(e)
        if msg == "no_pending_acceptance":
            return {
                **state,
                "ok": False,
                "error": "no_pending_acceptance",
                "deal_id": state["deal_id"],
                "decision": decision,
                "detail": (
                    "No pending acceptance for this deal. Pass "
                    "auto_submit=True (the default) to create one "
                    "automatically, or set acceptance_id directly."
                ),
            }
        return {
            **state,
            "ok": False,
            "error": msg.split(":", 1)[0],
            "deal_id": state["deal_id"],
            "decision": decision,
            "detail": msg,
        }
    except httpx.HTTPStatusError as e:
        return {
            **state,
            **_surface_http_error(
                e, decision_or_action=decision,
                deal_id=state["deal_id"], acceptance_id="",
            ),
        }

    keypair = state.get("keypair")
    key_id = state.get("key_id")
    reason = state.get("reason", "")
    downstream_action = state.get("downstream_action", "settle")

    # Step 2a — Signed branch (keypair + key_id present)
    if keypair is not None and key_id:
        from .signing import send_signed_event
        event_type = "ACCEPTED" if decision == "accept" else "REJECTED"
        intent = "accepted_work" if decision == "accept" \
            else "rejected_work"
        if decision == "accept":
            payload = {
                "acceptance_id":     acceptance_id,
                "downstream_action": downstream_action,
                "checks_passed":     [],
                "reason":            reason,
                "policy_snapshot":   {},
            }
        else:
            payload = {
                "acceptance_id":   acceptance_id,
                "checks_failed":   [],
                "reason":          reason,
                "policy_snapshot": {},
            }

        actor_id = state.get("agent_id", "") or ""
        try:
            event = await send_signed_event(
                client,
                deal_id=state["deal_id"],
                event_type=event_type,
                actor_id=actor_id,
                key_id=key_id,
                intent=intent,
                keypair=keypair,
                payload=payload,
                source="acceptance_gate",
            )
        except httpx.HTTPStatusError as e:
            # Option-3 block (signed-path 4xx) surfaces as a
            # structured backend_error — never a fake success.
            return {
                **state,
                **_surface_http_error(
                    e, decision_or_action=decision,
                    deal_id=state["deal_id"],
                    acceptance_id=acceptance_id,
                ),
                "signing_mode": "signed_block",
            }
        return {
            **state,
            "ok": True,
            "deal_id": state["deal_id"],
            "acceptance_id": acceptance_id,
            "decision": decision,
            "reason": reason,
            "downstream_action": downstream_action,
            "signing_mode": "signed",
            ("accepted_event" if decision == "accept" else "rejected_event"):
                event,
        }

    # Step 2b — Attribution-only branch
    try:
        if decision == "accept":
            result = await client.accept_output(
                acceptance_id, reason=reason,
            )
        else:
            result = await client.reject_output(
                acceptance_id, reason=reason,
            )
    except httpx.HTTPStatusError as e:
        return {
            **state,
            **_surface_http_error(
                e, decision_or_action=decision,
                deal_id=state["deal_id"],
                acceptance_id=acceptance_id,
            ),
        }

    return {
        **state,
        "ok": bool(result.get("ok", True)),
        "deal_id": state["deal_id"],
        "acceptance_id": acceptance_id,
        "decision": decision,
        "reason": reason,
        "downstream_action": downstream_action,
        "signing_mode": "attribution_only",
        "acceptance": result.get("acceptance"),
        "downstream_triggered": result.get("downstream_triggered"),
    }


async def outcome_receipt_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch the signed OutcomeReceipt for a deal.

    **Use this when** the deal has reached ``OUTCOME_RECORDED`` and you
    need the portable, Ed25519-signed, offline-verifiable receipt for
    audit / customer dashboard / partner handoff. The receipt's
    ``buyer_id`` is the payer (per Stage-7-C labeling); ``seller_id``
    is the performer.

    Surfaces three states as structured outputs (no exceptions on
    happy paths):
      - 200: ``receipt_state = "present"`` plus the full receipt and
        signature envelope.
      - 409 ``outcome_not_recorded``: ``receipt_state = "not_yet"``
        plus ``current_state`` (e.g. ``PROOF_READY``). This is a
        normal empty state, not an error.
      - 404 ``deal_not_found``: ``receipt_state = "deal_not_found"``.
      - 422/500 or network failure: ``receipt_state = "unavailable"``
        with structured backend_error fields.

    State inputs (required):
        deal_id

    State outputs:
        receipt_state, outcome_receipt (200 only), receipt_signature
        (200 only), current_state (409 only), backend_error fields on
        other failures.
    """
    _require_state(state, "deal_id")
    import httpx
    client = _get_client(state)
    try:
        resp = await client.get_outcome_receipt(state["deal_id"])
    except httpx.RequestError as e:
        return {
            **state,
            "receipt_state": "unavailable",
            "ok": False,
            "error": "network_error",
            "detail": str(e),
            "deal_id": state["deal_id"],
        }

    if resp.status_code == 200:
        body = resp.json()
        return {
            **state,
            "receipt_state": "present",
            "ok": True,
            "outcome_receipt": body.get("receipt"),
            "receipt_signature": {
                "payload_hash":      body.get("payload_hash"),
                "signature":         body.get("signature"),
                "algorithm":         body.get("algorithm"),
                "key_id":            body.get("key_id"),
                "public_key_base64": body.get("public_key_base64"),
            },
            "verify_url": body.get("verify_url"),
        }
    if resp.status_code == 409:
        body = resp.json()
        detail = body.get("detail") if isinstance(body, dict) else {}
        return {
            **state,
            "receipt_state": "not_yet",
            "ok": True,  # Honest: valid state, not an error
            "current_state": (detail or {}).get("current_state"),
            "deal_id": state["deal_id"],
        }
    if resp.status_code == 404:
        return {
            **state,
            "receipt_state": "deal_not_found",
            "ok": False,
            "deal_id": state["deal_id"],
        }

    # Anything else (422, 500) — surface honestly
    try:
        detail = resp.json()
    except Exception:
        detail = (resp.text or "")[:512]
    return {
        **state,
        "receipt_state": "unavailable",
        "ok": False,
        "error": "backend_error",
        "status_code": resp.status_code,
        "detail": detail,
        "deal_id": state["deal_id"],
    }
