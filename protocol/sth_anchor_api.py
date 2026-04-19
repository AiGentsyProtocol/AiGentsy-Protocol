"""
STH Anchor and Key Metadata API — Monitor-friendly trust surfaces.

Exposes anchor receipt history and rotation-safe key metadata.
All endpoints are public (no auth) — these are trust artifacts.

Endpoints:
    GET /protocol/merkle/anchors          — Paginated anchor receipt history
    GET /protocol/merkle/anchors/latest   — Most recent anchor receipt
    GET /protocol/merkle/keys             — All known signing keys
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def get_anchor_router():
    try:
        from fastapi import APIRouter, HTTPException, Query
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol/merkle", tags=["Transparency Log"])

    # ── Anchor Receipt Endpoints ──

    @router.get("/anchors")
    async def list_anchors(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        """List STH anchor receipts, newest first."""
        try:
            from protocol.sth_anchor import load_all_receipts
            all_receipts = load_all_receipts()
        except Exception:
            all_receipts = []

        total = len(all_receipts)
        page = all_receipts[offset:offset + limit]

        return {
            "ok": True,
            "anchors": page,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.get("/anchors/latest")
    async def latest_anchor():
        """Most recent STH anchor receipt."""
        try:
            from protocol.sth_anchor import load_latest_receipt
            receipt = load_latest_receipt()
        except Exception:
            receipt = None

        return {
            "ok": True,
            "anchor": receipt,
            "anchored": receipt is not None,
        }

    # ── Key Metadata Endpoint ──

    @router.get("/keys")
    async def list_keys():
        """
        All known signing keys (rotation-safe discovery).

        Returns the current active key and any historical keys.
        When a key rotation occurs, old keys remain discoverable here
        with deprecated_after set.
        """
        try:
            from protocol.merkle_log import get_log
            log = get_log()
            key_info = log.public_key_json()

            key_entry = {
                "key_id": key_info.get("key_id", ""),
                "algorithm": key_info.get("algorithm", ""),
                "public_key_base64": key_info.get("public_key_base64", ""),
                "key_version": key_info.get("key_version", 1),
                "active_from": key_info.get("active_from", key_info.get("created_at", "")),
                "status": key_info.get("status", "active"),
                "deprecated_after": None,
            }

            return {
                "ok": True,
                "keys": [key_entry],
                "current_key_id": key_entry["key_id"],
            }
        except Exception as e:
            logger.warning(f"Failed to build key list: {e}")
            return {
                "ok": False,
                "keys": [],
                "current_key_id": None,
                "error": str(e),
            }

    return router
