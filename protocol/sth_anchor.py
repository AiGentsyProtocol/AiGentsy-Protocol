"""
External STH Anchoring — RFC 3161 Timestamp Authority Integration.

Periodically anchors signed tree heads to external RFC 3161 timestamp
authorities, providing third-party proof that the Merkle log existed at
a given time. Anchor receipts are persisted as JSONL and exposed via API.

No new dependencies — TimeStampReq is constructed via manual DER encoding.
TimeStampResp is stored opaque (base64) for third-party verification with
`openssl ts -verify`.

Usage:
    from protocol.sth_anchor import anchor_loop, submit_anchor_for_sth

    # Background task (started from main.py)
    asyncio.create_task(anchor_loop())

    # Manual anchor submission
    receipt = await submit_anchor_for_sth(sth_dict)
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import struct
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from storage_root import get_data_root

logger = logging.getLogger(__name__)

# ── Configuration ──

ANCHOR_DIR = Path(os.getenv("STH_ANCHOR_DIR", str(get_data_root() / "sth_anchors")))
ANCHOR_LOG_FILE = ANCHOR_DIR / "anchor_receipts.jsonl"
ANCHOR_LATEST_FILE = ANCHOR_DIR / "latest_anchor.json"

ANCHOR_INTERVAL_SECONDS = int(os.getenv("ANCHOR_INTERVAL", "3600"))  # 1 hour
ANCHOR_MIN_NEW_LEAVES = 1  # Anchor if >= 1 new leaf since last anchor

TSA_URL = os.getenv("TSA_URL", "https://freetsa.org/tsr")

RECEIPT_VERSION = "1.0.0"

_write_lock = threading.Lock()


# ── RFC 3161 DER Construction ──
#
# We build a minimal TimeStampReq (RFC 3161 Section 2.4.1) by hand.
# The structure is fixed for SHA-256 digests, so no ASN.1 library is needed.
#
# TimeStampReq ::= SEQUENCE {
#     version        INTEGER { v1(1) },
#     messageImprint MessageImprint,
#     certReq        BOOLEAN DEFAULT FALSE
# }
#
# MessageImprint ::= SEQUENCE {
#     hashAlgorithm  AlgorithmIdentifier,
#     hashedMessage  OCTET STRING
# }
#
# AlgorithmIdentifier for SHA-256:
#     OID 2.16.840.1.101.3.4.2.1 + NULL parameters


# SHA-256 AlgorithmIdentifier (DER-encoded, fixed)
_SHA256_OID = bytes([
    0x30, 0x0d,                                          # SEQUENCE (13 bytes)
    0x06, 0x09,                                          # OID (9 bytes)
    0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01,  # 2.16.840.1.101.3.4.2.1
    0x05, 0x00,                                          # NULL
])


def _der_length(length: int) -> bytes:
    """Encode a DER length field."""
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return bytes([0x81, length])
    else:
        return bytes([0x82, (length >> 8) & 0xff, length & 0xff])


def _der_sequence(content: bytes) -> bytes:
    """Wrap content in a DER SEQUENCE tag."""
    return b'\x30' + _der_length(len(content)) + content


def _der_integer(value: int) -> bytes:
    """Encode a small non-negative integer as DER."""
    if value < 0x80:
        return bytes([0x02, 0x01, value])
    else:
        encoded = value.to_bytes((value.bit_length() + 8) // 8, 'big')
        return b'\x02' + _der_length(len(encoded)) + encoded


def _der_octet_string(data: bytes) -> bytes:
    """Encode data as a DER OCTET STRING."""
    return b'\x04' + _der_length(len(data)) + data


def _der_boolean(value: bool) -> bytes:
    """Encode a DER BOOLEAN."""
    return bytes([0x01, 0x01, 0xff if value else 0x00])


def build_timestamp_request(digest: bytes) -> bytes:
    """
    Build an RFC 3161 TimeStampReq for a SHA-256 digest.

    Args:
        digest: 32-byte SHA-256 hash

    Returns:
        DER-encoded TimeStampReq bytes
    """
    if len(digest) != 32:
        raise ValueError(f"Expected 32-byte SHA-256 digest, got {len(digest)}")

    # MessageImprint = SEQUENCE { hashAlgorithm, hashedMessage }
    message_imprint = _der_sequence(_SHA256_OID + _der_octet_string(digest))

    # TimeStampReq = SEQUENCE { version(1), messageImprint, certReq(TRUE) }
    content = _der_integer(1) + message_imprint + _der_boolean(True)

    return _der_sequence(content)


# ── TSA Submission ──


async def _submit_to_tsa(tsa_url: str, tsq_bytes: bytes) -> Dict[str, Any]:
    """
    Submit a TimeStampReq to an RFC 3161 TSA via HTTP POST.

    Returns dict with status and response data.
    """
    import urllib.request

    loop = asyncio.get_event_loop()

    def _post():
        req = urllib.request.Request(
            tsa_url,
            data=tsq_bytes,
            headers={
                "Content-Type": "application/timestamp-query",
                "Accept": "application/timestamp-reply",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                tsr_bytes = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                return {
                    "status": "granted",
                    "tsr_bytes": tsr_bytes,
                    "tsr_base64": base64.b64encode(tsr_bytes).decode(),
                    "content_type": content_type,
                    "tsr_size": len(tsr_bytes),
                }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "tsr_bytes": None,
                "tsr_base64": None,
            }

    return await loop.run_in_executor(None, _post)


# ── Receipt Construction ──


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_anchor_id() -> str:
    ts_hex = format(int(time.time()), "x")
    rand_hex = os.urandom(4).hex()[:4]
    return f"anchor_{ts_hex}_{rand_hex}"


def _canonical_sth_json(sth: Dict[str, Any]) -> str:
    """Canonical JSON representation of an STH for hashing."""
    return json.dumps(sth, sort_keys=True, separators=(",", ":"))


def _sth_digest(sth: Dict[str, Any]) -> str:
    """SHA-256 hex digest of the canonical STH JSON."""
    canonical = _canonical_sth_json(sth)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def submit_anchor_for_sth(sth: Dict[str, Any]) -> Dict[str, Any]:
    """
    Anchor an STH to an external RFC 3161 TSA.

    Args:
        sth: Signed tree head dict

    Returns:
        Anchor receipt dict
    """
    digest_hex = _sth_digest(sth)
    digest_bytes = bytes.fromhex(digest_hex)

    # Build RFC 3161 TimeStampReq
    tsq = build_timestamp_request(digest_bytes)

    # Submit to TSA
    tsa_result = await _submit_to_tsa(TSA_URL, tsq)

    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "anchor_id": _make_anchor_id(),
        "log_id": sth.get("log_id", ""),
        "key_id": sth.get("key_id", ""),
        "sth": {
            "tree_size": sth.get("tree_size", 0),
            "root_hash": sth.get("root_hash", ""),
            "timestamp": sth.get("timestamp", ""),
            "signature": sth.get("signature", ""),
        },
        "sth_digest": digest_hex,
        "sth_digest_algorithm": "SHA-256",
        "anchor_method": "rfc3161",
        "tsa_url": TSA_URL,
        "tsa_status": tsa_result["status"],
        "tsr_base64": tsa_result.get("tsr_base64"),
        "anchored_at": _now_iso(),
    }

    if tsa_result["status"] == "error":
        receipt["error"] = tsa_result.get("error", "unknown")

    return receipt


# ── Persistence ──


def _init_storage():
    """Ensure anchor storage directory exists."""
    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)


def persist_receipt(receipt: Dict[str, Any]) -> None:
    """Append receipt to JSONL log and update latest file."""
    _init_storage()

    with _write_lock:
        # Append to JSONL
        with open(ANCHOR_LOG_FILE, "a") as f:
            f.write(json.dumps(receipt, separators=(",", ":")) + "\n")

        # Atomic overwrite of latest
        tmp = ANCHOR_LATEST_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(receipt, f, indent=2)
        tmp.replace(ANCHOR_LATEST_FILE)


def load_latest_receipt() -> Optional[Dict[str, Any]]:
    """Load the most recent anchor receipt."""
    if not ANCHOR_LATEST_FILE.exists():
        return None
    try:
        with open(ANCHOR_LATEST_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def load_all_receipts() -> List[Dict[str, Any]]:
    """Load all anchor receipts from JSONL, newest first."""
    if not ANCHOR_LOG_FILE.exists():
        return []
    receipts = []
    try:
        with open(ANCHOR_LOG_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    receipts.append(json.loads(line))
    except Exception:
        pass
    receipts.reverse()  # newest first
    return receipts


def _load_last_anchored_size() -> int:
    """Get the tree_size of the last anchored STH."""
    latest = load_latest_receipt()
    if latest and "sth" in latest:
        return latest["sth"].get("tree_size", 0)
    return 0


# ── Background Task ──


async def anchor_loop():
    """
    Background task: periodically anchor STH to external TSAs.

    Started from main.py startup. Runs every ANCHOR_INTERVAL_SECONDS.
    Only anchors if tree has grown since last anchor.
    Failures are logged and retried next cycle.
    """
    # Wait 30 seconds after startup before first check
    await asyncio.sleep(30)

    last_anchored_size = _load_last_anchored_size()
    logger.info(
        "[ANCHOR] Started — interval=%ds, last_anchored_size=%d, tsa=%s",
        ANCHOR_INTERVAL_SECONDS, last_anchored_size, TSA_URL,
    )

    while True:
        try:
            from protocol.merkle_log import get_log

            log = get_log()
            current_size = log.tree_size

            if current_size <= last_anchored_size:
                pass  # No new leaves
            elif current_size - last_anchored_size < ANCHOR_MIN_NEW_LEAVES:
                pass  # Not enough new leaves
            else:
                sth = log.get_latest_sth()
                if sth:
                    receipt = await submit_anchor_for_sth(sth)
                    persist_receipt(receipt)

                    if receipt["tsa_status"] == "granted":
                        last_anchored_size = current_size
                        logger.info(
                            "[ANCHOR] STH anchored: tree_size=%d, anchor_id=%s",
                            current_size, receipt["anchor_id"],
                        )
                    else:
                        logger.warning(
                            "[ANCHOR] TSA returned status=%s: %s",
                            receipt["tsa_status"],
                            receipt.get("error", ""),
                        )
        except Exception:
            logger.warning("[ANCHOR] Cycle failed, will retry", exc_info=True)

        await asyncio.sleep(ANCHOR_INTERVAL_SECONDS)
