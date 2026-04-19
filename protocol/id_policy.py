"""
Canonical ID Policy — deal_id is the root invariant
=====================================================

Every entity in the protocol derives from deal_id:
  - deal_id     = primary global identifier (created once at deal birth)
  - execution_id = child of deal (deal_id + step context)
  - proof_id     = child of deal (deal_id + proof context)
  - settlement_id = child of deal (deal_id + settlement context)

Usage:
    from protocol.id_policy import require_deal_id, derive_execution_id, deal_id_for_stripe

    deal_id = require_deal_id(context_dict)          # throws if missing
    exec_id = derive_execution_id(deal_id, "step_3") # deterministic child
    stripe_meta = deal_id_for_stripe(deal_id, extra)  # metadata dict for Stripe
"""

import hashlib
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class MissingDealIdError(Exception):
    """Raised when deal_id is required but not present."""
    pass


def create_deal_id() -> str:
    """Create a new canonical deal_id. Single format: deal_{12 hex chars}."""
    return f"deal_{uuid4().hex[:12]}"


def require_deal_id(context: Dict[str, Any], *, source: str = "") -> str:
    """
    Extract deal_id from a context dict. Throws if missing.

    Checks keys in priority order: deal_id, then falls back to
    contract_id, intent_id, job_id, coi_id — but logs a warning
    for non-canonical names so callers can be migrated.
    """
    # Canonical key
    deal_id = context.get("deal_id")
    if deal_id:
        return deal_id

    # Legacy fallbacks — accept but warn
    for legacy_key in ("contract_id", "intent_id", "job_id", "coi_id", "execution_id"):
        val = context.get(legacy_key)
        if val:
            logger.warning(
                f"[ID_POLICY] Using legacy key '{legacy_key}' as deal_id "
                f"(value={val[:20]}, source={source}). Migrate to 'deal_id'."
            )
            return val

    raise MissingDealIdError(
        f"deal_id is required but not found in context (source={source}). "
        f"Available keys: {list(context.keys())}"
    )


def require_deal_id_or_none(context: Dict[str, Any], *, source: str = "") -> Optional[str]:
    """Same as require_deal_id but returns None instead of throwing."""
    try:
        return require_deal_id(context, source=source)
    except MissingDealIdError:
        return None


def derive_execution_id(deal_id: str, step: str = "") -> str:
    """
    Deterministic execution_id derived from deal_id + step context.
    Always traceable back to the parent deal.

    Format: exec_{deal_hex}_{step_hash_4}
    """
    step_hash = hashlib.sha256(step.encode()).hexdigest()[:4] if step else "0000"
    # Strip 'deal_' prefix if present to keep ID compact
    deal_hex = deal_id.replace("deal_", "")
    return f"exec_{deal_hex}_{step_hash}"


def derive_proof_id(deal_id: str, proof_type: str = "") -> str:
    """Deterministic proof_id derived from deal_id + proof type."""
    type_hash = hashlib.sha256(proof_type.encode()).hexdigest()[:4] if proof_type else "0000"
    deal_hex = deal_id.replace("deal_", "")
    return f"proof_{deal_hex}_{type_hash}"


def deal_id_for_stripe(deal_id: str, extra: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Build Stripe metadata dict that ALWAYS includes deal_id.
    Use this in every PaymentIntent.create() and checkout.Session.create().
    """
    meta = {"deal_id": deal_id, "platform": "aigentsy"}
    if extra:
        meta.update(extra)
    return meta


def proof_url(deal_id: str) -> str:
    """Canonical proof URL. Always keyed by deal_id."""
    return f"https://aigentsy.com/proof/{deal_id}"


def delivery_url(deal_id: str) -> str:
    """Canonical delivery URL. Always keyed by deal_id."""
    return f"https://aigentsy.com/delivery/{deal_id}"
