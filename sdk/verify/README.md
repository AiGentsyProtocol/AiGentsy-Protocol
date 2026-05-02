# aigentsy-verify

Standalone offline verification for AiGentsy proof bundles and attestations. **Zero dependency on AiGentsy's runtime.**

## Install

```bash
pip install aigentsy-verify
```

## CLI

Verify a bundle offline (default — no network calls):

```bash
aigentsy-verify bundle proofpack.json
# level: offline (4/5 steps) — STH signature skipped without key
```

Full 5/5 verification with public key fetch:

```bash
aigentsy-verify bundle proofpack.json --fetch-key
# level: full (5/5 steps) — all steps PASS
```

JSON output for scripting:

```bash
aigentsy-verify bundle proofpack.json --json
```

Strict mode (fails if STH signature is skipped):

```bash
aigentsy-verify bundle proofpack.json --strict --fetch-key
```

Download and verify a real ProofPack:

```bash
curl -o proofpack.json https://aigentsy-ame-runtime.onrender.com/protocol/proofs/demo_deal_08effb15193a/export
aigentsy-verify bundle proofpack.json --fetch-key
```

## Python SDK — Verify in 60 Seconds

```python
from aigentsy_verify import verify_bundle, verify_attestation, fetch_public_key
import json, urllib.request

# 1. Fetch public key (cache this — it rarely changes)
public_key = fetch_public_key()

# 2. Verify a proof bundle
bundle = json.load(open("bundle.json"))
result = verify_bundle(bundle, public_key_base64=public_key)
print(result["verified"])  # True or False

# 3. Verify an attestation
resp = json.loads(urllib.request.urlopen(
    "https://aigentsy-ame-runtime.onrender.com/protocol/agents/AGENT_ID/attestation"
).read())
ok = verify_attestation(resp["attestation"], resp["signature"], public_key)
print(ok)  # True or False
```

## Verify a Proof Bundle

```python
import json
from aigentsy_verify import verify_bundle, fetch_public_key

# Load a bundle (from file, API, or any source)
with open("bundle.json") as f:
    bundle = json.load(f)

# Fetch the public key (once — cache it)
public_key = fetch_public_key()

# Verify — returns per-step results
result = verify_bundle(bundle, public_key_base64=public_key)

print(result["verified"])  # True or False
for step, detail in result["steps"].items():
    print(f"  {step}: {'PASS' if detail['passed'] else 'SKIP' if detail.get('skipped') else 'FAIL'}")
```

## Verify an Attestation

```python
import json, urllib.request
from aigentsy_verify import verify_attestation, fetch_public_key

# Fetch attestation from AiGentsy
resp = json.loads(urllib.request.urlopen(
    "https://aigentsy-ame-runtime.onrender.com/protocol/agents/AGENT_ID/attestation"
).read())

# Fetch public key
public_key = fetch_public_key()

# Verify signature
ok = verify_attestation(
    resp["attestation"],
    resp["signature"],
    public_key,
)
print(f"Attestation valid: {ok}")
```

## Sample Artifacts

The `tests/fixtures/` directory contains sample artifacts you can verify immediately:

```bash
# Clone and verify offline
python -c "
import json
from aigentsy_verify import verify_bundle, verify_attestation

bundle = json.load(open('tests/fixtures/sample_bundle.json'))
print('Bundle:', verify_bundle(bundle)['verified'])

att = json.load(open('tests/fixtures/sample_attestation.json'))
print('Attestation:', verify_attestation(att['attestation'], att['signature'], att['public_key_base64']))
"
```

Sample fixtures include a test Ed25519 key pair — they verify without network access.

## Public Key

The production Ed25519 public key is served at:

```
https://aigentsy-ame-runtime.onrender.com/protocol/merkle/public-key
```

Load it programmatically:

```python
from aigentsy_verify import fetch_public_key
key = fetch_public_key()  # returns base64-encoded Ed25519 public key
```

Or from a local file:

```python
from aigentsy_verify import load_public_key_from_file
key = load_public_key_from_file("log_public_key.json")
```

## 5-Step Bundle Verification

| Step | What it checks | Required? |
|------|---------------|-----------|
| 1. Bundle hash | SHA-256 of canonical JSON matches claimed hash | Yes |
| 2. Event chain | Each event's hash and prev_hash link are correct | Yes |
| 3. Merkle inclusion | RFC 6962 proof path from leaf to root | If present |
| 4. STH signature | Ed25519 signature on signed tree head | If key provided |
| 5. Cross-reference | Merkle root matches STH root hash | If both present |

## API

### `verify_bundle(bundle, public_key_base64="", sth=None) -> dict`
Complete 5-step verification. Returns `{"verified": bool, "steps": {...}}`.

### `verify_attestation(attestation, signature_base64, public_key_base64) -> bool`
Verify an Ed25519-signed outcome attestation.

### `verify_inclusion(leaf_hash, leaf_index, tree_size, proof, expected_root) -> bool`
Verify an RFC 6962 Merkle inclusion proof.

### `verify_sth_signature(sth, public_key_base64) -> bool`
Verify a signed tree head signature.

### `verify_consistency(old_size, new_size, old_root, new_root, proof) -> bool`
Verify an RFC 6962 Merkle consistency proof (append-only guarantee).

### `verify_anchor_receipt(receipt) -> tuple[bool, dict]`
Verify an STH anchor receipt's digest integrity. Returns `(passed, details)`.

### `fetch_public_key(url=...) -> str`
Fetch the Ed25519 public key from AiGentsy's runtime.

### `load_public_key_from_file(path) -> str`
Load the public key from a local JSON file.

### `compute_bundle_hash(deal_id, proofs, events, merkle_inclusion) -> str`
Compute the SHA-256 bundle hash.

### `verify_event_chain(events) -> dict`
Verify event hash integrity and prev_hash chain linkage.

## Resources

- [Proof Bundle Spec](https://aigentsy.com/data/proof_bundle_spec.md)
- [Conformance Vectors](https://aigentsy.com/data/conformance_vectors.json)
- [Public Key (runtime)](https://aigentsy-ame-runtime.onrender.com/protocol/merkle/public-key)
- [Trust Center](https://aigentsy.com/trust)
- [Verify Page](https://aigentsy.com/verify)

## License

MIT — see [LICENSE](LICENSE).
