"""Local Ed25519 signing helpers for the LangGraph adapter (0.3.0).

Implements the Stage 7-A signed-event round-trip — prepare → local
sign → submit — against the live AiGentsy backend, using a
client-side ``SigningKeypair``. The private key is read into a
transient ``Ed25519PrivateKey`` object inside this module, used to
sign, and dropped. It is NEVER sent over the wire; every outgoing
request body is inspected by ``_assert_no_private_material`` before
transmission (the same belt-and-suspenders guard the rich SDK uses,
mirroring the server-side ``FORBIDDEN_PRIVATE_KEY_FIELDS`` set in
``protocol/actor_registry.py``).

Reference contract: ``sdk/aigentsy/src/aigentsy/client.py:432-522``
(``send_signed_event``).
"""
from __future__ import annotations

import base64
from typing import Any, Dict, Optional

from .keypair import SigningKeypair, _assert_no_private_material


async def send_signed_event(
    client,  # AsyncAiGentsyClient — typed loosely to avoid circular import
    *,
    deal_id: str,
    event_type: str,
    actor_id: str,
    key_id: str,
    intent: str,
    keypair: SigningKeypair,
    payload: Optional[Dict[str, Any]] = None,
    counterparty_id: str = "",
    amount: float = 0.0,
    source: str = "",
    actor_role: str = "",
) -> Dict:
    """Generic Stage 7-A signed-event round-trip — async.

    Phase 1 ``POST /protocol/event/prepare`` (returns canonical bytes)
    → local Ed25519 sign of those bytes →
    Phase 2 ``POST /protocol/event/submit`` (returns the appended
    event with ``actor_signature`` attached).

    The keypair's private key is decoded into a transient
    Ed25519PrivateKey, used to sign, then deleted. It does NOT appear
    in any HTTP body the client constructs; both bodies are
    pre-screened by ``_assert_no_private_material``.

    Raises ``RuntimeError`` if the optional ``[signed]`` extra is not
    installed (``cryptography`` missing).
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
    except ImportError as e:
        raise RuntimeError(
            "send_signed_event requires the `cryptography` package "
            "(pip install 'aigentsy-langgraph[signed]' or "
            "'cryptography>=41.0')."
        ) from e

    # 1. Prepare — pre-screen the body for any private-key material
    # before sending, even though we never put any in.
    prepare_body = {
        "deal_id":         deal_id,
        "event_type":      event_type,
        "actor_id":        actor_id,
        "key_id":          key_id,
        "intent":          intent,
        "payload":         payload or {},
        "counterparty_id": counterparty_id,
        "amount":          amount,
        "source":          source,
        "actor_role":      actor_role,
    }
    _assert_no_private_material(prepare_body, "prepare body")
    prep = await client._post_signed(
        "/protocol/event/prepare", prepare_body,
    )

    token = prep["token"]
    canonical_b64 = prep["canonical_bytes_b64"]
    canonical_bytes = base64.b64decode(canonical_b64)

    # 2. Sign locally — the private key is decoded, used, and dropped
    # in this scope; no reference to it ever leaves this function.
    priv_raw = base64.b64decode(keypair.private_key_base64)
    try:
        priv = Ed25519PrivateKey.from_private_bytes(priv_raw)
        sig = priv.sign(canonical_bytes)
        sig_b64 = base64.b64encode(sig).decode("ascii")
    finally:
        try:
            del priv
        except NameError:
            pass
        priv_raw = None  # noqa: F841

    # 3. Submit — only signature + token cross the wire; pre-screen
    # again to make absolutely sure no private material crept in.
    submit_body = {
        "token": token,
        "actor_signature": {
            "actor_id":  actor_id,
            "key_id":    key_id,
            "intent":    intent,
            "signature": sig_b64,
        },
    }
    _assert_no_private_material(submit_body, "submit body")
    result = await client._post_signed(
        "/protocol/event/submit", submit_body,
    )
    return result.get("event", result)
