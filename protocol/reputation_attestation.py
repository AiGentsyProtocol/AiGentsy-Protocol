"""
Portable Reputation Attestations — W3C Verifiable Credential Format
=====================================================================

Issues signed, timestamped OCS attestations as W3C Verifiable Credentials.
Agents carry their AiGentsy reputation into other ecosystems. External
platforms verify the credential using AiGentsy's public Ed25519 key.

Usage:
    POST /protocol/attestations/issue    — Issue a signed OCS attestation
    GET  /protocol/attestations/{agent_id} — Get latest attestation for agent
    POST /protocol/attestations/verify   — Verify an attestation offline-capable

Credential format follows W3C Verifiable Credentials Data Model v2.0:
    https://www.w3.org/TR/vc-data-model-2.0/
"""

import base64
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from storage_root import get_data_root

logger = logging.getLogger(__name__)

_STORE_DIR = Path(os.getenv("ATTESTATION_DIR", str(get_data_root() / "reputation_attestations")))

AIGENTSY_ISSUER = "https://aigentsy.com"
CREDENTIAL_TYPE = "AiGentsyReputationCredential"
ATTESTATION_TTL_DAYS = 90  # Attestations expire after 90 days


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expiry_iso(days: int = ATTESTATION_TTL_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_credential_hash(credential: Dict[str, Any]) -> str:
    """Deterministic hash of the credential subject (excludes proof and credentialHash)."""
    hashable = {k: v for k, v in credential.items() if k not in ("proof", "credentialHash")}
    canonical = json.dumps(hashable, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _sign_credential(credential_hash: str) -> Dict[str, Any]:
    """Sign credential hash with Ed25519 (same key as Merkle log)."""
    try:
        from protocol.merkle_log import get_log
        log = get_log()
        signer = log._signer

        if signer._algorithm == "Ed25519":
            signature = signer._private_key.sign(credential_hash.encode("utf-8"))
            return {
                "type": "Ed25519Signature2020",
                "created": _now_iso(),
                "verificationMethod": f"{AIGENTSY_ISSUER}/protocol/merkle/public-key",
                "proofPurpose": "assertionMethod",
                "signature": base64.b64encode(signature).decode("ascii"),
                "algorithm": "Ed25519",
                "key_id": signer._key_id,
            }
        else:
            # HMAC fallback (dev only — not portable)
            import hmac as hmac_mod
            sig = hmac_mod.new(
                signer._hmac_key.encode(), credential_hash.encode(), hashlib.sha256
            ).hexdigest()
            return {
                "type": "HmacSignature2024",
                "created": _now_iso(),
                "verificationMethod": f"{AIGENTSY_ISSUER}/protocol/merkle/public-key",
                "proofPurpose": "assertionMethod",
                "signature": sig,
                "algorithm": "HMAC-SHA256",
                "note": "Development signature — not portable. Production uses Ed25519.",
            }
    except Exception as e:
        logger.warning(f"[ATTESTATION] Signing failed: {e}")
        return {
            "type": "Unsigned",
            "created": _now_iso(),
            "error": "signing_unavailable",
        }


class AttestationStore:
    """Persists issued attestations for lookup."""

    def __init__(self, store_dir: str = str(_STORE_DIR)):
        self._by_agent: Dict[str, Dict[str, Any]] = {}  # agent_id -> latest credential
        self._by_id: Dict[str, Dict[str, Any]] = {}  # credential_id -> credential
        self._store_file: Optional[Path] = None
        self._lock = threading.Lock()
        self._init(store_dir)

    def _init(self, store_dir: str):
        try:
            path = Path(store_dir)
            path.mkdir(parents=True, exist_ok=True)
            self._store_file = path / "attestations.jsonl"
            if self._store_file.exists():
                for line in self._store_file.read_text().strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        cred = json.loads(line)
                        cred_id = cred.get("id", "")
                        agent_id = cred.get("credentialSubject", {}).get("agent_id", "")
                        self._by_id[cred_id] = cred
                        self._by_agent[agent_id] = cred
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"[ATTESTATION] Store init failed: {e}")

    def store(self, credential: Dict[str, Any]):
        with self._lock:
            cred_id = credential.get("id", "")
            agent_id = credential.get("credentialSubject", {}).get("agent_id", "")
            self._by_id[cred_id] = credential
            self._by_agent[agent_id] = credential
            if self._store_file:
                try:
                    with open(self._store_file, "a") as f:
                        f.write(json.dumps(credential, default=str) + "\n")
                except Exception as e:
                    logger.warning(f"[ATTESTATION] Persist failed: {e}")

    def get_by_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._by_agent.get(agent_id)

    def get_by_id(self, credential_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(credential_id)

    def count(self) -> int:
        return len(self._by_id)


_store: Optional[AttestationStore] = None


def get_attestation_store() -> AttestationStore:
    global _store
    if _store is None:
        _store = AttestationStore()
    return _store


def issue_attestation(agent_id: str) -> Dict[str, Any]:
    """
    Issue a W3C Verifiable Credential for an agent's reputation.

    Returns a signed VC with the agent's OCS score, tier, settlement history,
    and the AiGentsy issuer signature.
    """
    # Get agent data from registry
    try:
        from protocol.agent_registry import get_agent_registry
        registry = get_agent_registry()
        agent = registry.get_agent(agent_id)
    except Exception:
        agent = None

    if not agent:
        return {"ok": False, "error": f"Agent {agent_id} not found"}

    ocs = agent.get("ocs", 50)
    tier = "restricted"
    if ocs >= 90:
        tier = "elite"
    elif ocs >= 75:
        tier = "trusted"
    elif ocs >= 50:
        tier = "standard"
    elif ocs >= 25:
        tier = "probation"

    credential_id = f"urn:aigentsy:attestation:{uuid4().hex[:16]}"
    now = _now_iso()
    expiry = _expiry_iso()

    # Build W3C VC
    credential = {
        "@context": [
            "https://www.w3.org/ns/credentials/v2",
            "https://aigentsy.com/ns/reputation/v1",
        ],
        "id": credential_id,
        "type": ["VerifiableCredential", CREDENTIAL_TYPE],
        "issuer": {
            "id": AIGENTSY_ISSUER,
            "name": "AiGentsy Settlement Protocol",
        },
        "issuanceDate": now,
        "expirationDate": expiry,
        "credentialSubject": {
            "id": f"urn:aigentsy:agent:{agent_id}",
            "agent_id": agent_id,
            "agent_name": agent.get("name", ""),
            "ocs_score": ocs,
            "ocs_tier": tier,
            "total_settlements": agent.get("total_settlements", 0),
            "total_volume_usd": agent.get("total_volume_usd", 0),
            "capabilities": agent.get("capabilities", []),
            "status": agent.get("status", "active"),
            "registered_at": agent.get("created_at", ""),
            "attestation_timestamp": now,
        },
    }

    # Compute hash and sign
    credential_hash = _compute_credential_hash(credential)
    credential["credentialHash"] = credential_hash
    credential["proof"] = _sign_credential(credential_hash)

    # Persist
    get_attestation_store().store(credential)

    return {"ok": True, "credential": credential}


def verify_attestation_offline(
    credential: Dict[str, Any], public_key_base64: str = "",
) -> Dict[str, Any]:
    """
    Verify a reputation attestation offline.

    Checks:
    1. Credential hash integrity
    2. Ed25519 signature (if public key provided)
    3. Expiry
    """
    result = {"steps": {}, "verified": False}

    # Step 1: Hash integrity
    claimed_hash = credential.get("credentialHash", "")
    computed_hash = _compute_credential_hash(credential)
    hash_ok = claimed_hash == computed_hash
    result["steps"]["hash_integrity"] = {"passed": hash_ok, "computed": computed_hash, "claimed": claimed_hash}

    # Step 2: Signature verification
    proof = credential.get("proof", {})
    sig_ok = False
    sig_skipped = True

    if public_key_base64 and proof.get("type") == "Ed25519Signature2020":
        sig_skipped = False
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            raw_key = base64.b64decode(public_key_base64)
            pub_key = Ed25519PublicKey.from_public_bytes(raw_key)
            signature = base64.b64decode(proof["signature"])
            pub_key.verify(signature, claimed_hash.encode("utf-8"))
            sig_ok = True
        except Exception:
            sig_ok = False

    result["steps"]["signature"] = {"passed": sig_ok, "skipped": sig_skipped}

    # Step 3: Expiry check
    expiry_str = credential.get("expirationDate", "")
    expired = False
    if expiry_str:
        try:
            expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            expired = datetime.now(timezone.utc) > expiry
        except Exception:
            pass
    result["steps"]["expiry"] = {"passed": not expired, "expiration_date": expiry_str}

    # Overall
    result["verified"] = hash_ok and (sig_ok or sig_skipped) and not expired
    result["agent_id"] = credential.get("credentialSubject", {}).get("agent_id")
    result["ocs_score"] = credential.get("credentialSubject", {}).get("ocs_score")
    result["ocs_tier"] = credential.get("credentialSubject", {}).get("ocs_tier")

    return result


# ── FastAPI Router ──

def get_attestation_router():
    try:
        from fastapi import APIRouter, Header, HTTPException
        from pydantic import BaseModel, Field
    except ImportError:
        return None

    router = APIRouter(prefix="/protocol", tags=["Reputation Attestations"])

    class VerifyAttestationRequest(BaseModel):
        credential: Dict[str, Any] = Field(..., description="The full W3C VC credential JSON")
        public_key_base64: str = Field("", description="Ed25519 public key for signature verification")

    @router.post("/attestations/issue")
    async def issue(
        agent_id: str,
        x_api_key: str = Header(..., alias="X-API-Key"),
    ):
        """Issue a signed W3C Verifiable Credential attesting an agent's reputation."""
        from protocol.agent_registry import get_agent_registry
        agent = get_agent_registry().authenticate(x_api_key)
        if not agent:
            raise HTTPException(status_code=401, detail="Invalid API key")

        result = issue_attestation(agent_id)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("error"))
        return result

    @router.get("/attestations/{agent_id}")
    async def get_attestation(agent_id: str):
        """
        Get the latest reputation attestation for an agent.

        Public endpoint — credentials are designed to be shared.
        """
        store = get_attestation_store()
        cred = store.get_by_agent(agent_id)
        if not cred:
            return {
                "ok": True,
                "credential": None,
                "message": f"No attestation found for {agent_id}. Issue one via POST /protocol/attestations/issue",
            }
        return {"ok": True, "credential": cred}

    @router.post("/attestations/verify")
    async def verify(req: VerifyAttestationRequest):
        """
        Verify a reputation attestation offline.

        No API key required — verification is a public operation.
        Provide the Ed25519 public key for full signature verification,
        or omit it for hash-only verification.
        """
        result = verify_attestation_offline(req.credential, req.public_key_base64)
        result["ok"] = True
        return result

    @router.get("/attestations")
    async def attestation_stats():
        """Get attestation system statistics."""
        store = get_attestation_store()
        return {
            "ok": True,
            "total_issued": store.count(),
            "credential_type": CREDENTIAL_TYPE,
            "ttl_days": ATTESTATION_TTL_DAYS,
            "issuer": AIGENTSY_ISSUER,
            "verification_endpoint": f"{AIGENTSY_ISSUER}/protocol/attestations/verify",
            "public_key_endpoint": "https://aigentsy-ame-runtime.onrender.com/protocol/merkle/public-key",
        }

    return router
