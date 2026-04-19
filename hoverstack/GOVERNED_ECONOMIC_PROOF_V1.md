# Governed Economic Proof — Specification v1 / v1.1

**Status:** v1.1 (HMAC-SHA256 + ed25519 asymmetric signing)
**Module:** `hoverstack.governed_proof`
**Embedding path:** ProofPack `evidence.governance_attestation`

---

## 1. Purpose

Governed Economic Proof (GEP) v1 is the first fused primitive of the
AiGentsy Stack. It captures, in a single signed artifact, how
HoverStack governed a computation **before** the work handoff, so
AiGentsy can bind that governance record to the ProofPack that
proves the work handoff itself.

Downstream parties gain the ability to verify, offline, not only
that the work was proven but also that the compute path was
explicitly governed by policy, risk, and economic signals.

---

## 2. Scope

**In scope for v1:**
- Which compute path was chosen (direct recall, structural recall,
  delta, full compute).
- Which paths were refused, with machine-readable reasons.
- The policy, risk, and economic signals active at decision time.
- The shape-policy-memory reputation and tags consulted.
- The refusal / escalation / preservation rationales.
- A deterministic content hash, an HMAC signature, and a binding
  hash that ties the artifact to its enclosing ProofPack.
- Offline verification within a trust boundary that shares the
  signing key.

**Out of scope for v1 (explicit non-claims):**
- **GEP v1 does NOT prove the chosen path was globally optimal.**
- **GEP v1 does NOT prove no cheaper safe path existed.**
- **GEP v1 does NOT prove universal optimality.**
- GEP v1 does not use zk/SNARK machinery.
- GEP v1 does not require or provide blockchain attestation.
- GEP v1 does not provide public-key third-party verification —
  that belongs to v1.1 (ed25519 upgrade path; see §11).

The v1 statement is: **"this computation was governed by explicit
policy and evidence; here is the decision transcript, signed and
bound to the work proof."**

---

## 3. Threat Model

v1 assumes:
- The signing key is held by HoverStack and by any party authorized
  to verify attestations.
- An attacker without the key cannot forge a valid attestation.
- An attacker with the key can forge any attestation — this is a
  symmetric-signing limitation resolved in v1.1 via ed25519.
- Tampering with a signed artifact (changing any content field
  without recomputing the signature) is detectable.
- Swapping a genuine artifact between two ProofPacks is detectable
  via `proofpack_binding_hash`.
- An attestation without a `proofpack_binding_hash` is valid but is
  not bound to a specific work proof; consumers that require the
  binding MUST check it.

Not mitigated:
- Key compromise (defer to operational controls).
- Policy fabrication by the attestation producer (v1 attests to
  what was recorded; correctness of the recording is operational).

---

## 4. Schema (v1)

Field list. All fields are JSON-serializable. Optional fields are
set to `""` / `[]` / `{}` / `None` when absent so the schema is
fixed across serializations.

```
spec_version                  str     "governed_economic_proof/v1"
governance_id                 str     "gep_<16-hex>"
timestamp                     str     ISO-8601 UTC
runtime_name                  str     e.g. "vllm"
model_name                    str     e.g. "Llama-3.1-8B-Instruct"
shape_id                      str     workload family identifier
policy_version                str     e.g. "hoverstack/apex-8-plane"

# Decision
decision_path_chosen          str     "direct_recall" | "structural_recall"
                                      | "tail_only_delta" | "field_only_delta"
                                      | "context_patch_delta"
                                      | "no_delta_needed" | "full_compute"
candidate_paths_considered    [str]
paths_refused                 [{path: str, reason: str}]

# Signals
risk_signals                  dict    {risk_class, restrictions_applied,
                                       recall/delta fallback triggered/reason}
economic_signals              dict    {payoff_ms_estimate, carry_units_estimate,
                                       net_value_estimate_ms, kelly_fraction,
                                       cache_pressure_factor,
                                       compute_avoided_estimate_ms,
                                       consecutive_negative_waves,
                                       prefix_cache_hit, decode_batch_size}
shape_policy_summary          dict    {reputation, tags}

# Rationale
refusal_rationale             str
escalation_rationale          str
preservation_rationale        str

# Proof metadata
proof_completeness_rate       float   0..1

# Signing metadata (v1.1)
algorithm                     str     "hmac-sha256" | "ed25519"
public_key                    str     hex-encoded 32-byte ed25519 public key
                                      (empty string for HMAC artifacts)

# Computed / signed fields
governance_hash               str     SHA-256 hex over canonical content
signature                     str     HMAC-SHA256 hex (hmac-sha256) or
                                      hex-encoded 64-byte Ed25519 sig (ed25519)
proofpack_binding_hash        str     SHA-256 hex over (governance_hash ":" proofpack_hash)
```

---

## 5. Canonicalization Rules

To make hashing deterministic across Python versions and machines:

1. Build a dict from the artifact's content (exclude
   `governance_hash`, `signature`, `proofpack_binding_hash` for the
   hash-input serialization).
2. Recursively round every `float` leaf to 6 decimal places.
3. Preserve `None` values in the dict.
4. Serialize with:
   - `sort_keys=True`
   - `ensure_ascii=True`
   - `separators=(",", ":")`
   - UTF-8 encoding of the resulting string.

The resulting bytes are the canonical content representation. All
hash and signature operations operate on these bytes.

---

## 6. Hashing Rules

- `governance_hash` = `sha256(canonical_content_bytes).hexdigest()`,
  where `canonical_content_bytes` excludes the three hash/signature
  fields themselves (cycle avoidance).

---

## 7. Signing and Verification Rules

### 7a. Algorithm field

The artifact carries an `algorithm` field:
- `"hmac-sha256"` — v1 symmetric signing (default for backward
  compatibility).
- `"ed25519"` — v1.1 asymmetric signing (public third-party
  verification).

Verification code dispatches on this field. A v1-only verifier that
does not recognise `"ed25519"` SHOULD reject the artifact rather than
silently accept; a v1.1-aware verifier MUST handle both values.

### 7b. HMAC-SHA256 (v1 path)

- `signature` = `hmac_sha256(key, governance_hash.encode("utf-8")).hexdigest()`
- Key source (priority):
  1. Explicit `signing_key: bytes` passed to `sign()`.
  2. Environment variable `HOVERSTACK_GOVERNANCE_SIGNING_KEY`.
  3. Deterministic development fallback (tests only).
- Constant-time comparison (`hmac.compare_digest`) prevents timing
  attacks.
- `public_key` field is empty (`""`).

### 7c. Ed25519 (v1.1 path)

- `signature` = hex-encoded 64-byte Ed25519 signature over
  `governance_hash.encode("utf-8")`.
- The signer's 32-byte public key is embedded on the artifact at the
  `public_key` field (hex-encoded). This allows any third party to
  verify without a shared secret and without contacting the signer.
- Key source (priority):
  1. Explicit `ed25519_private_key` passed to `sign()`.
  2. Environment variable `HOVERSTACK_GOVERNANCE_ED25519_PRIVATE_KEY`
     (hex-encoded 32-byte seed).
  3. Deterministic development fallback (tests only).
- Public-key resolution for verification (priority):
  1. Explicit `ed25519_public_key` passed to `verify_signature()`.
  2. The `public_key` field on the artifact itself.
  3. Environment variable `HOVERSTACK_GOVERNANCE_ED25519_PUBLIC_KEY`.
  4. Derived from the dev-fallback private seed.
- The `cryptography` Python package provides the Ed25519
  implementation. No custom crypto is used.

### 7d. Verification summary

A valid attestation requires:
1. `governance_hash` recomputed from the artifact's canonical
   content MUST match the stored `governance_hash`.
2. The stored `signature` MUST verify under the appropriate
   algorithm using the corresponding key material.

---

## 8. ProofPack Embedding Rules

GEP v1 attestations embed at exactly one location in the ProofPack:

```
proof.evidence.governance_attestation = { ...artifact dict... }
```

This is a strict peer of the Level 1 `evidence.hoverstamp` envelope.
Neither supersedes the other; a ProofPack MAY include either, both,
or neither.

**Binding to ProofPack:**

After signing, the producer calls
`artifact.bind_to_proofpack(proofpack_hash)` where `proofpack_hash`
is the ProofPack's own proof_hash. The binding hash is:

```
proofpack_binding_hash = sha256(governance_hash + ":" + proofpack_hash).hexdigest()
```

The verifier reads the artifact from the ProofPack, knows the
enclosing ProofPack's proof_hash, and checks the binding.

**Back-compat invariant:** a ProofPack without any
`governance_attestation` field behaves identically to one produced
before this spec existed. All existing verifiers MUST ignore
unknown `evidence.*` keys safely.

---

## 9. Backward Compatibility Rules

- The ProofPack schema is not modified. The attestation lives under
  the already-optional `evidence` dict alongside `hoverstamp`.
- `proof_hash` is computed over `(proof_type, source, agent,
  deal_id, proof_data)` only. It does NOT include evidence. So the
  attestation cannot change `proof_hash` — Level 1 semantics are
  preserved.
- Verification, acceptance, and settlement paths do not read the
  attestation. It is offline-verifiable via the spec but never
  participates in those on-chain flows.
- Older verifiers that do not understand `evidence.governance_attestation`
  continue to function unchanged.

---

## 10. Explicit Non-Claims

The following statements are NOT implied by the presence of a
valid GEP v1 attestation:

1. The chosen compute path was the globally cheapest safe path.
2. No cheaper safe path existed.
3. The decision was universally optimal.
4. The signing key has not been compromised.
5. The policy configuration itself was itself correct — only that
   the recorded policy was applied as stated.

The only positive claim GEP v1 makes is:

> "This computation was governed by explicit policy and evidence.
>  Here is the decision transcript, signed and bound to the work
>  proof."

---

## 11. v1.1 Status (Shipped)

v1.1 ed25519 signing is implemented and available:

- `algorithm: "ed25519"` is now a supported value.
- The signer's public key is embedded on the artifact.
- Any third party with the public key can verify offline.
- HMAC artifacts (`algorithm: "hmac-sha256"`) continue to verify
  unchanged — dispatch is automatic.
- Canonicalization and hash rules are unchanged from v1.
- No new dependencies beyond the `cryptography` package (already
  present in the runtime environment).

Producers and verifiers MUST accept both HMAC and ed25519 artifacts.

---

## 12. Module Surface

```python
from hoverstack.governed_proof import (
    GovernanceArtifact, DecisionTranscript,
    build_signed_artifact, verify_embedded_artifact,
    SPEC_VERSION,
)

# Producer side
transcript = DecisionTranscript.from_runtime_fields(
    cell_id="c1", shape_id="contract_review",
    runtime_fields=response.hoverstamp_runtime_fields(caps),
    runtime_name="vllm", model_name="Llama-3.1-8B",
)
artifact = build_signed_artifact(
    transcript,
    proofpack_hash=proof_hash,
    signing_key=key,
    policy_version="hoverstack/apex-8-plane",
)
# Embed at evidence.governance_attestation via /protocol/proof-pack
# with the new governance_attestation=... kwarg on ProofPackRequest.

# Verifier side (offline)
report = verify_embedded_artifact(
    artifact_dict=proof["evidence"]["governance_attestation"],
    signing_key=key,
    proofpack_hash=proof["proof_hash"],
)
assert report["signature_valid"]
assert report["binding_valid"]
```

---

## 13. Non-Goals

- No marketplace for governance attestations.
- No federation of signing authorities.
- No on-chain anchoring.
- No refusal auction or refusal tokenization.
- No cross-operator attestation aggregation.

These may or may not be future work; none are part of v1.
