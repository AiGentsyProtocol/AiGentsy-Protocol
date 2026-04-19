"""
Public key retrieval for offline verification.

Provides helpers to fetch or load AiGentsy's Ed25519 public key
from static URLs or local files.
"""

import json
from typing import Optional

# Canonical key location (runtime — contains actual key material)
PUBLIC_KEY_URL = "https://aigentsy-ame-runtime.onrender.com/protocol/merkle/public-key"

# Discovery metadata (static — no key material, points to canonical URL)
PUBLIC_KEY_METADATA_URL = "https://aigentsy.com/data/log_public_key.json"

# Backwards compat alias
PUBLIC_KEY_RUNTIME_URL = PUBLIC_KEY_URL


def fetch_public_key(url: str = PUBLIC_KEY_RUNTIME_URL) -> str:
    """
    Fetch the Ed25519 public key from a URL.

    Args:
        url: URL to fetch key from (default: AiGentsy runtime endpoint)

    Returns:
        Base64-encoded public key string

    Raises:
        RuntimeError: If fetch fails or key is empty
    """
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        raise RuntimeError(f"Failed to fetch public key from {url}: {e}")

    key = data.get("public_key_base64", "")
    if not key:
        raise RuntimeError(f"Public key is empty at {url}")

    return key


def load_public_key_from_file(path: str) -> str:
    """
    Load the Ed25519 public key from a local JSON file.

    The file should have the same format as log_public_key.json:
        {"public_key_base64": "...", "algorithm": "Ed25519", ...}

    Args:
        path: Path to the JSON file

    Returns:
        Base64-encoded public key string

    Raises:
        RuntimeError: If file doesn't exist or key is empty
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to load public key from {path}: {e}")

    key = data.get("public_key_base64", "")
    if not key:
        raise RuntimeError(f"Public key is empty in {path}")

    return key
