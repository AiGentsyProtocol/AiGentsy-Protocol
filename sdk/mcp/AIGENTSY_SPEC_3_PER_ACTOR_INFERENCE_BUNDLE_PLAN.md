# AiGentsy — `spec_version=3.0.0` Per-Actor Signed Inference Bundle Plan

**Status**: PLANNING ONLY — DO NOT IMPLEMENT
**Pass**: 82J planning artifact
**Date**: 2026-06-18
**Posture**: no implementation in this pass · no protocol change · no verifier change · no signing key change

---

## 1. Goal

Plan a backward-compatible path to attach per-actor Ed25519 signatures to `INFERENCE_*` events without breaking any of:

- The existing `spec_version=2.0.0` event chain.
- The existing `_hash_record` 7-field projection.
- The existing `compute_bundle_hash_v1` canonical-JSON contract.
- The existing 5-step verifier (CLI + browser).
- The 82E `parsePyJson` Python-faithful canonicalizer.
- Bundle hashes for every existing bundle on disk.
- The 82H Consequence Layer public taxonomy.

This document recommends the **safest first path** for a future implementation pass.

---

## 2. Current state (Pass 82J landing point)

- **Spec version of all inference bundles**: `2.0.0`.
- **Attestation class on every `INFERENCE_*` event**: `platform_attested` or `attribution_only`. Never `actor_signed`.
- **`actor_signature` field on events**: not present.
- **`key_directory` block on bundles**: not present for `INFERENCE_*` bundles.
- **`canonical_event_for_signing()`** at `runtime/protocol/signing_schema.py:128`: already exists; covers the 7 `_hash_record` fields + `key_id`. Already used by ACCEPTED / REJECTED / OUTCOME_RECORDED / DISPUTE_OPENED via Tier-2 Stages 7-A/B/C.
- **`INTENT_VALUES`** at `runtime/protocol/signing_schema.py:56`: controlled enum of allowed signing intents (`produced_work`, `submitted_evidence`, `verified_artifact`, `accepted_work`, `rejected_work`, `authorized_consequence`, `acknowledged_receipt`). **Does NOT yet include an inference-specific value.**

---

## 3. Recommended path — `actor_signatures` SIDECAR keyed by existing `event_hash`

The recommendation is to **add a top-level `actor_signatures` array on the bundle**, NOT a per-event `actor_signature` field, in the first implementation pass.

Each entry in the sidecar:

```json
{
  "event_hash": "<SHA-256 of the existing 7-field projection — UNCHANGED>",
  "actor_id": "<who signed>",
  "key_id": "<which public key>",
  "signature": "<base64 Ed25519>",
  "signed_at": "<ISO-8601>",
  "intent": "evaluated_inference",
  "sig_scheme": "ed25519-canonical-event-v1"
}
```

### Why this is the safest first path

1. **Preserves the v2 event chain byte-for-byte.** The event itself is NEVER modified. `event_hash` (computed via the existing `_hash_record` over the existing 7-field projection) is the join key — no new field is added to the hashed projection.
2. **Preserves the v2 bundle hash for OLD bundles.** Bundles emitted before the sidecar exists do not have an `actor_signatures` block; their `bundle_hash` is computed exactly as today.
3. **Preserves the existing verifier behavior.** The Pass 82E `parsePyJson` + 5-step verifier validate `bundle_hash + event_chain + merkle_inclusion + sth_signature + cross_reference` over the existing fields. A sidecar adds a 6th OPTIONAL verification step (`actor_signatures`) that the verifier can choose to perform; if absent, the 5 mandatory steps still pass.
4. **Avoids touching `compute_bundle_hash_v1`.** New `actor_signatures` field is added to the EXISTING `signing_schema.py` exclusion list at line 233 — same posture as the existing `key_directory` / `signed_tree_head` / `root_hash` / `bundle_hash` / `sth_anchor` / `governance_summary` / `agent_trace` exclusions. **This is the only hash-related change.** The exclusion list is metadata-only; the hash contract is unchanged.
5. **Backward compatible with bundle export.** `assemble_v1_bundle()` adds the sidecar only when at least one event in the chain has been signed; otherwise the bundle is byte-identical to today's output.
6. **CLI verifier additive update.** `aigentsy-verify` adds an `--strict-actor-signatures` flag (default off). When off, the existing 5-step verification posture is preserved. When on, additionally validate each sidecar entry against the `key_directory` snapshot.
7. **Browser verifier (`parsePyJson` + 5-step in `verify.html`)**: unchanged for the mandatory 5 steps. An additional optional step can be added in a future pass without weakening anything.

### Why NOT the alternative (per-event `actor_signature` field)

A per-event `actor_signature` field would require:

- Modifying the existing `_hash_record` projection to either include OR exclude `actor_signature` (either choice has consequences). Including it changes every event's hash. Excluding it requires `_hash_record` to know about a new field name — coupling that doesn't exist today for `INFERENCE_*` (which already has `key_id` exclusion plumbing for Tier-2, but adding per-event signing inside the event body is heavier than a sidecar).
- Bumping `spec_version` per-bundle conditionally, similar to how `assemble_v1_bundle()` already bumps `2.0.0 → 3.0.0` when `key_directory` is present. This is feasible (Tier-2 already does this for ACCEPTED/REJECTED) but stacks more conditional logic.
- More test surface to keep stable across the 82E + CLI + browser verifier paths.

The sidecar achieves the same end (auditable per-actor signature provenance per `INFERENCE_*` event) with strictly less coupling.

---

## 4. Required additions (when implemented in a future pass)

1. **`runtime/protocol/signing_schema.py`**:
   - Add `"evaluated_inference"` to `INTENT_VALUES` (line 56). One-line additive change.
   - Add `"actor_signatures"` to the bundle exclusion list (line 233). One-line additive change.
2. **`runtime/protocol/bundle_spec.py`**:
   - Optional `actor_signatures` field on the assembled bundle, populated only when `evaluate_inference()` was called with an Ed25519 signing keypair.
3. **`runtime/protocol/inference_acceptance.py`**:
   - Optional `signing_key` / `key_id` / `intent="evaluated_inference"` triple (all-or-none, mirroring `emit_event`'s Tier-2 Stage 3 contract). When all three are present, sign each emitted event using `canonical_event_for_signing()` and accumulate the sidecar entry.
4. **`aigentsy-verify` CLI** at `aigentsy-protocol/sdk/verify/`:
   - Add `--strict-actor-signatures` flag (default off).
   - When on: for each event with a corresponding sidecar entry, verify the Ed25519 signature against the bundle's `key_directory` snapshot.
5. **MCP `aigentsy_inference_evaluate` tool** (the one shipped in 82J):
   - Add optional `signing_keypair_b64` arg. When present, fold into the client call so the runtime emits signed events.
   - **Sidecar payload is platform-attested only.** The MCP layer cannot carry a per-actor Ed25519 keypair safely without a key-management story (out of scope for this pass).

---

## 5. NOT touched by this plan

The following remain **byte-identical** under the sidecar approach:

| Surface | Why unchanged |
|---|---|
| `_hash_record` 7-field projection | Sidecar lives on the bundle, never on the event |
| `compute_bundle_hash_v1` canonical-JSON output | `actor_signatures` excluded same way as `key_directory` |
| `canonical_event_for_signing` | Already covers the 7 fields + `key_id`; no change needed |
| `LogSigner` / `aigentsy_log_signer_v1` Ed25519 key | Not used for actor signatures (each actor brings their own keypair) |
| `TransparencyLog` Merkle tree | Inclusion proof unchanged; sidecar is outside the tree |
| 82E `parsePyJson` browser verifier | 5 mandatory steps unchanged |
| CLI `aigentsy-verify bundle` 5/5 PASS contract | 5 mandatory steps unchanged; sidecar is optional 6th |
| Browser verifier `verify.html` (Pass 82E) | 5 mandatory steps unchanged |
| `proof_export.export_proof_bundle()` | Delegated path unchanged; sidecar appended at assembly time |
| Bundle `bundle_type`, `spec_version` default `2.0.0` | No mandatory bump; `3.0.0` only if a future pass decides to use it as a signal |
| Existing `INFERENCE_*` event types and counts | 4-event lifecycle unchanged |

---

## 6. Compatibility matrix (post-implementation)

| Bundle exported by | Sidecar present? | CLI `--strict-actor-signatures off` | CLI `--strict-actor-signatures on` |
|---|---|---|---|
| Pre-sidecar runtime (today) | no | 5/5 PASS | 5/5 PASS (sidecar absent — verifier skips actor-sig step) |
| Post-sidecar runtime, no signing keypair supplied | no | 5/5 PASS | 5/5 PASS |
| Post-sidecar runtime, signing keypair supplied | yes | 5/5 PASS (sidecar ignored at default strictness) | 5/5 PASS + sidecar verified |
| Tampered bundle (any era) | n/a | FAIL | FAIL |

The matrix preserves the 82E "tampered fixture still fails" guarantee and the 82G "canonical handoff bundle 5/5 PASS" guarantee under every configuration.

---

## 7. Out of scope for this plan

The following are deliberately deferred even further:

- **Key directory enrollment flow** for inference actor keys. The actor key-management story (how an LLM agent or workflow operator gets a non-custodial Ed25519 keypair and how its `actor_id` ↔ `key_id` binding gets onto a public registry) is a separate planning pass. Until that's resolved, sidecar signatures will be platform-attested only.
- **Spec bump semantics.** Whether to also bump `spec_version` to `3.0.0` when a sidecar is present, OR keep `2.0.0` and let the sidecar speak for itself, is a separate design decision. The recommendation here is **keep `2.0.0`** until clear consumer demand exists; the sidecar is purely additive and doesn't require a version flag to be valid.
- **Multi-actor signatures per event.** The sidecar schema above accommodates one signature per `(event_hash, actor_id)` pair, so multiple actors can sign the same event. But the runtime emission contract today is single-actor per event (the actor whose keypair is currently supplied). Multi-actor signing is a Tier-3 follow-up.

---

## 8. Estimated implementation effort (for a future pass)

| Item | LOC est. |
|---|---|
| `INTENT_VALUES` + exclusion-list addition | +2 |
| `evaluate_inference` signing keypair plumbing | +60 |
| Bundle assembly sidecar emission | +80 |
| CLI verifier sidecar verification path | +120 |
| MCP tool optional signing param | +30 |
| Tests (sidecar present + absent; tampered sidecar; key/actor binding) | +300 |
| Total | ~600 |

This is roughly comparable to Pass 82G's runtime evaluator (618 LOC for `inference_acceptance.py`). Spread across one focused pass.

---

## 9. Rollout posture (when the future pass ships)

1. Ship sidecar emission opt-in (no caller change is forced).
2. Ship CLI flag `--strict-actor-signatures off` by default.
3. Run the existing 5-step verifier in CI on every existing 2.0.0 bundle to confirm zero regression.
4. Document the sidecar shape under `protocol/fixtures/spec_3_actor_signatures_examples/` (planning artifact).
5. Update the 82F fixtures' `claim_boundaries` block to clarify "actor signatures available where signing keypair was supplied; platform-attested otherwise."

---

## 10. Decision request when implementation is approved

Before implementing, the operator should approve:

1. **Sidecar location**: `bundle["actor_signatures"]` (top-level) vs `bundle["events"][i]["actor_signature"]` (per-event embedded). **Recommendation: top-level sidecar.**
2. **Strictness default**: CLI `--strict-actor-signatures off` (5/5 PASS preserved by default) vs default on. **Recommendation: off.**
3. **`spec_version` behavior**: bump `2.0.0 → 3.0.0` when sidecar present vs keep `2.0.0`. **Recommendation: keep `2.0.0`.**
4. **MCP signing arg**: add `signing_keypair_b64` to `aigentsy_inference_evaluate` vs defer until key-enrollment story is ready. **Recommendation: defer.**
5. **Intent enum addition**: `evaluated_inference` is the proposed value. Operator may prefer `evaluated_inference_acceptance` for symmetry with the existing `accepted_work` / `rejected_work` pair.

---

*End of plan. NO IMPLEMENTATION IN THIS PASS.*
