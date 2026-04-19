"""
Proof Export & Portability — Part 6
====================================

Export proof bundles with merkle inclusion for deal verification.
Publish daily merkle roots for anchoring.

Endpoints:
    GET  /protocol/proofs/{deal_id}/export     — Export proof bundle
    POST /protocol/proofs/publish-root          — Publish daily root
    POST /protocol/proofs/verify-bundle         — Verify a proof bundle
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from storage_root import get_data_root

logger = logging.getLogger(__name__)

_ROOTS_DIR = Path(os.getenv("PROOF_ROOTS_DIR", str(get_data_root() / "proof_roots")))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def export_proof_bundle(deal_id: str) -> Dict[str, Any]:
    """Assemble proof bundle: proofs + events + merkle inclusion + root hash.

    Returns v1 bundle (with spec_version) when the transparency log is
    available, falling back to legacy format for backward compatibility.
    """
    # Try v1 bundle first (transparency log + signed tree head)
    try:
        from protocol.bundle_spec import assemble_v1_bundle
        return assemble_v1_bundle(deal_id)
    except Exception:
        pass

    # Legacy fallback — original bundle format (no spec_version)
    bundle: Dict[str, Any] = {
        "deal_id": deal_id,
        "exported_at": _now_iso(),
        "proofs": [],
        "events": [],
        "merkle_inclusion": None,
        "root_hash": None,
    }

    # Collect proofs
    try:
        from proof_pipe import _proof_store
        bundle["proofs"] = [
            p for p in _proof_store if p.get("deal_id") == deal_id
        ]
    except Exception:
        pass

    # Collect events
    try:
        from protocol.event_store import get_event_store
        chain = get_event_store().get_chain(deal_id)
        bundle["events"] = chain
    except Exception:
        pass

    # Merkle inclusion
    try:
        from proof_merkle import get_receipt
        receipt = get_receipt(deal_id)
        if receipt:
            bundle["merkle_inclusion"] = {
                "leaf_hash": receipt.get("leaf_hash"),
                "merkle_proof": receipt.get("merkle_proof"),
                "merkle_root": receipt.get("merkle_root"),
                "date": receipt.get("date"),
            }
            bundle["root_hash"] = receipt.get("merkle_root")
    except Exception:
        pass

    # Compute bundle hash
    canonical = json.dumps({
        "deal_id": deal_id,
        "proofs": bundle["proofs"],
        "events": bundle["events"],
        "merkle_inclusion": bundle["merkle_inclusion"],
    }, sort_keys=True, default=str)
    bundle["bundle_hash"] = hashlib.sha256(canonical.encode()).hexdigest()

    return {"ok": True, **bundle}


def publish_daily_root(date: str = None) -> Dict[str, Any]:
    """Finalize merkle root for a date and persist to roots.jsonl."""
    date = date or _today()

    # Get root from proof_merkle
    root_info = None
    try:
        from proof_merkle import finalize_daily_root as _finalize
        root_info = _finalize(date)
    except Exception as e:
        logger.debug(f"[PROOF_EXPORT] proof_merkle finalize failed: {e}")

    # Also get root from event_store daily root
    event_root = None
    try:
        from protocol.event_store import get_event_store
        event_root = get_event_store().compute_daily_root(date)
    except Exception as e:
        logger.debug(f"[PROOF_EXPORT] event_store daily root failed: {e}")

    if not root_info and not event_root:
        return {"ok": False, "error": "no_data_for_date", "date": date}

    # Persist to roots.jsonl
    record = {
        "date": date,
        "published_at": _now_iso(),
        "proof_merkle_root": root_info.get("root") if root_info else None,
        "proof_leaf_count": root_info.get("leaf_count", 0) if root_info else 0,
        "event_merkle_root": event_root.get("root") if event_root else None,
        "event_count": event_root.get("event_count", 0) if event_root else 0,
    }

    try:
        _ROOTS_DIR.mkdir(parents=True, exist_ok=True)
        roots_file = _ROOTS_DIR / "roots.jsonl"
        with open(roots_file, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        logger.warning(f"[PROOF_EXPORT] Root persist failed: {e}")

    return {"ok": True, **record}


def verify_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Verify a proof bundle's integrity (supports v1 and legacy formats)."""
    spec_version = bundle.get("spec_version")

    # v1 bundle — delegate to the canonical offline verifier
    if spec_version:
        from protocol.bundle_spec import verify_bundle_offline
        result = verify_bundle_offline(bundle)
        steps = result.get("steps", {})
        return {
            "ok": True,
            "deal_id": result.get("deal_id", ""),
            "hash_verified": steps.get("bundle_hash", {}).get("passed", False),
            "merkle_verified": steps.get("merkle_inclusion", {}).get("passed", False),
            "proof_count": result.get("proof_count", 0),
            "event_count": result.get("event_count", 0),
            "computed_hash": steps.get("bundle_hash", {}).get("computed", ""),
            "claimed_hash": steps.get("bundle_hash", {}).get("claimed", ""),
            "verified": result.get("verified", False),
            "steps": steps,
        }

    # Legacy verification
    deal_id = bundle.get("deal_id", "")
    proofs = bundle.get("proofs", [])
    events = bundle.get("events", [])
    merkle_inclusion = bundle.get("merkle_inclusion")
    claimed_hash = bundle.get("bundle_hash", "")

    # Recompute bundle hash
    canonical = json.dumps({
        "deal_id": deal_id,
        "proofs": proofs,
        "events": events,
        "merkle_inclusion": merkle_inclusion,
    }, sort_keys=True, default=str)
    computed_hash = hashlib.sha256(canonical.encode()).hexdigest()

    hash_verified = computed_hash == claimed_hash

    # Verify merkle inclusion
    merkle_verified = False
    if merkle_inclusion:
        try:
            from proof_merkle import _hash_pair
            leaf_hash = merkle_inclusion.get("leaf_hash", "")
            proof = merkle_inclusion.get("merkle_proof", [])
            expected_root = merkle_inclusion.get("merkle_root", "")

            current = leaf_hash
            for step in proof:
                if step["position"] == "left":
                    current = _hash_pair(step["hash"], current)
                else:
                    current = _hash_pair(current, step["hash"])
            merkle_verified = current == expected_root
        except Exception:
            pass

    return {
        "ok": True,
        "deal_id": deal_id,
        "hash_verified": hash_verified,
        "merkle_verified": merkle_verified,
        "proof_count": len(proofs),
        "event_count": len(events),
        "computed_hash": computed_hash,
        "claimed_hash": claimed_hash,
    }


def wrap_as_verifiable_credential(deal_id: str, bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap a proof bundle in a W3C Verifiable Credential envelope.

    Follows https://www.w3.org/TR/vc-data-model-2.0/ structure.
    The credential is unsigned (no proof.jws) — signing requires
    a DID-based key pair which is a future upgrade.
    """
    base_url = os.getenv("AIGENTSY_URL", "https://aigentsy.com")
    runtime_url = os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com")

    return {
        "@context": [
            "https://www.w3.org/ns/credentials/v2",
            "https://www.w3.org/ns/credentials/examples/v2",
        ],
        "type": ["VerifiableCredential", "AiGentsyProofCredential"],
        "issuer": {
            "id": f"{runtime_url}/protocol/hello",
            "name": "AiGentsy Settlement Protocol",
        },
        "issuanceDate": bundle.get("exported_at", _now_iso()),
        "credentialSubject": {
            "id": f"{base_url}/verify.html?deal={deal_id}",
            "type": "AIWorkDeliveryProof",
            "dealId": deal_id,
            "bundleHash": bundle.get("bundle_hash"),
            "proofCount": len(bundle.get("proofs", [])),
            "eventCount": len(bundle.get("events", [])),
            "merkleRoot": bundle.get("root_hash"),
            "verificationEndpoint": f"{runtime_url}/proof/{deal_id}/verify",
        },
        "evidence": [
            {
                "type": "AiGentsyProofBundle",
                "verifier": f"{base_url}/verify.html?deal={deal_id}",
                "bundle": bundle,
            }
        ],
        "credentialStatus": {
            "type": "AiGentsyVerification",
            "statusEndpoint": f"{runtime_url}/proof/{deal_id}/verify",
        },
    }


# ── Router ──

def get_proof_export_router():
    try:
        from fastapi import APIRouter, HTTPException, Header
        from pydantic import BaseModel, Field
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol", tags=["Proof Portability"])

    class PublishRootRequest(BaseModel):
        model_config = {"extra": "ignore"}
        date: str = Field("")

    class VerifyBundleRequest(BaseModel):
        model_config = {"extra": "allow"}
        deal_id: str = Field(...)
        spec_version: Optional[str] = Field(None)
        proofs: List[Dict[str, Any]] = Field(default_factory=list)
        events: List[Dict[str, Any]] = Field(default_factory=list)
        merkle_inclusion: Optional[Dict[str, Any]] = Field(None)
        signed_tree_head: Optional[Dict[str, Any]] = Field(None)
        bundle_hash: str = Field("")

    @router.get("/proofs/{deal_id}/export")
    async def export(deal_id: str, format: str = "bundle", x_api_key: str = Header(None, alias="X-API-Key")):
        """Export proof bundle for a deal.

        Query params:
            format=bundle  (default) — native proof bundle
            format=vc      — W3C Verifiable Credential envelope
            format=pdf     — human-readable PDF document
        """
        from fastapi.responses import Response

        result = export_proof_bundle(deal_id)

        if x_api_key:
            try:
                from protocol.agent_registry import get_agent_registry
                registry = get_agent_registry()
                agent = registry.authenticate(x_api_key)
                if agent:
                    proofs = result.get("proofs", [])
                    deal_agent = proofs[0].get("agent", "") if proofs else ""
                    if deal_agent and agent.get("agent_id") != deal_agent:
                        raise HTTPException(status_code=404, detail="deal not found")
            except HTTPException:
                raise
            except Exception:
                pass
        if format == "vc":
            return wrap_as_verifiable_credential(deal_id, result)
        if format == "pdf":
            from protocol.pdf_export import generate_proof_pdf
            pdf_bytes = generate_proof_pdf(result)
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="aigentsy-proof-{deal_id}.pdf"',
                },
            )
        return result

    @router.post("/proofs/publish-root")
    async def publish_root(req: PublishRootRequest):
        """Publish daily merkle root."""
        result = publish_daily_root(date=req.date or None)
        if not result.get("ok"):
            raise HTTPException(status_code=422, detail=result.get("error", "failed"))
        return result

    @router.post("/proofs/verify-bundle")
    async def verify(req: VerifyBundleRequest):
        """Verify a proof bundle."""
        return verify_bundle(req.dict())

    return router
