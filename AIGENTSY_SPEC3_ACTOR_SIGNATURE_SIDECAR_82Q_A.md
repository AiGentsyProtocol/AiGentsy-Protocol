# Pass 82Q-A — Spec 3 Actor Signature Sidecar Fixture + Verifier Prototype

**Date**: 2026-06-18
**Scope**: `aigentsy-protocol/sdk/verify` source-only · fixture + verifier prototype · NO runtime emission · NO package publish · NO version bump · NO frontend / public copy
**Runtime SHA**: `e4bd308` (unchanged)
**Protocol pre-edit HEAD**: `c8268a6` (Pass 82J)
**Hero-final SHA**: `4f4cad8` (Pass 82P — unchanged this pass)

---

## 1. Mission

Prove that a Spec 3 actor-signature sidecar can be attached to existing AiGentsy bundles **without changing any hash, any verifier behavior, or any package surface**, by shipping the prototype as:

- one **new fixture** (built from the existing `sample_bundle.json` with a real Ed25519 signature added at top-level),
- one **opt-in verifier helper** (`verify_actor_signature_sidecar`),
- one **new test file** (20 tests) covering legacy compatibility, hash preservation, happy path, and 7 tamper modes.

**Default verifier behavior is unchanged.** Legacy bundles still verify exactly as before. The sidecar is invisible to the core 5-step verifier.

---

## 2. Baseline confirmation

| Check | Result |
|---|---|
| Frontend SHA equivalence | deployed `aigentsystack.html` == local `4f4cad8` |
| Runtime `/build` | `e4bd308` (unchanged) |
| Protocol HEAD (pre-edit) | `c8268a6` |
| MCP `@mcp.tool` count | 14 |
| `aigentsy_inference_evaluate` registered | ✓ |
| Verifier pre-existing test suite | 56/56 PASS |
| Live canonical handoff bundle | `verified: true` |
| Live inference fixture bundle | `verified: true` |
| Tampered bundle | `verified: false` |

---

## 3. Empirical probe summary (carried over from 82Q audit)

I ran a live probe earlier this session:

1. Fetched live `demo_deal_handoff_v1` bundle (18,465 bytes · `bundle_hash 9a98a70e...c6`).
2. Added a synthetic `actor_signatures` top-level field.
3. Re-verified: **bundle still PASSes** · `bundle_hash` byte-identical.

This pass formalizes that empirical result with deterministic, signed, reproducible test artifacts.

---

## 4. Chosen sidecar shape (operator-locked)

Single consolidated top-level field `actor_signature_sidecar`:

```json
{
  "actor_signature_sidecar": {
    "sidecar_version": "0.0.1",
    "canonicalization": "canonical_event_for_signing_v1",
    "signature_alg": "Ed25519",
    "sidecar_hash": "<SHA-256 over canonical sidecar payload excluding the hash itself>",
    "signatures_by_event_hash": {
      "<event_hash>": [
        {
          "actor_id": "test:acceptance_runtime_agent",
          "key_id": "test_actor_v1",
          "public_key_base64": "...",
          "signature_base64": "...",
          "intent": "evaluated_inference",
          "signed_at": "ISO-8601",
          "signed_payload_canonical_keys": [
            "event_id","event_type","deal_id","actor_id",
            "timestamp","payload","prev_hash","key_id"
          ]
        }
      ]
    }
  }
}
```

**Canonical signed payload per event** = 8-field JSON projection mirroring `runtime/protocol/signing_schema.py::canonical_event_for_signing` (7 `_hash_record` fields + `key_id`), with `sort_keys=True` and compact separators `(",", ":")`.

**Sidecar hash** = SHA-256 of `json.dumps(sidecar_without_hash, sort_keys=True, separators=(",",":"), default=str)`.

---

## 5. Why top-level sidecar was selected (Option A) — over alternatives

| Option | Verdict | Rationale |
|---|---|---|
| **A — top-level `actor_signature_sidecar`** | **SELECTED** | empirically proven byte-compatible with `compute_bundle_hash`; the whitelist projection (`spec_version`, `deal_id`, `proofs`, `events`, `merkle_inclusion`) ignores unknown top-level fields by construction |
| B — event-level `event["actor_signatures"]` | **REJECTED for v0** | risks `_hash_record` projection change; would either modify the 7-field projection (breaks all events) or require an exclusion list (couples the projection to a new field name) |
| C — separate `.actor-signatures.json` artifact | **REJECTED for v0** | UX friction, multi-file fetch in browser verifier, complicates `verify.html` |
| D — nested Spec 3 inference envelope | **DEFERRED** | premature; needs v0 ground truth first |

---

## 6. Legacy verifier compatibility (zero regression)

The default `verify_bundle()` path is **byte-identical** in behavior with and without the sidecar:

| Surface | Behavior |
|---|---|
| `verify_bundle()` signature | unchanged — no new required argument |
| `verify_bundle()` return shape | unchanged — `steps` block still has exactly the 5 mandatory keys (`bundle_hash`, `event_chain`, `merkle_inclusion`, `sth_signature`, `cross_reference`) |
| `compute_bundle_hash()` | unchanged — whitelist projection ignores the sidecar |
| `verify_event_chain()` | unchanged — `_hash_record` projection untouched |
| `EXCLUDED_FROM_HASH` set | NOT modified (no change needed — whitelist already excludes unknown fields) |
| CLI `aigentsy-verify bundle` invocation | unchanged |
| Published `aigentsy-verify==1.5.0` on PyPI | unchanged — no republish |

---

## 7. Strict optional verifier behavior

New `verify_actor_signature_sidecar(bundle)` helper:

- **Separate function** from `verify_bundle()` — callers must explicitly opt in to strict sidecar validation.
- **Returns structured per-check result** mirroring the existing `steps` block shape, so future CLI integration can surface it as a 6th optional step.
- **Lazy-imports `cryptography`** — only when sidecar is actually present, keeping the default verifier dependency-light for legacy paths.
- **Failure modes reported separately**: `sidecar_hash` mismatch · unsupported algorithm · unsupported canonicalization · signature does not verify · signed `event_hash` not in chain · missing required fields.

| Strict-mode invocation | Sidecar present | Result |
|---|---|---|
| `verify_actor_signature_sidecar(legacy_bundle)` | NO | `{present: false, passed: false, errors: []}` — non-throwing, structured |
| `verify_actor_signature_sidecar(sidecar_bundle)` happy path | YES, valid | `{present: true, passed: true, signatures_checked: ≥1, actor_ids: [...]}` |
| `verify_actor_signature_sidecar(sidecar_bundle)` after tamper | YES, invalid | `{present: true, passed: false, errors: [...specific reason]}` |

---

## 8. Fixture created (additive — does NOT mutate any existing fixture)

| File | Status | Note |
|---|---|---|
| `sdk/verify/tests/fixtures/sample_bundle.json` | **UNCHANGED** | legacy fixture preserved verbatim |
| `sdk/verify/tests/fixtures/sample_attestation.json` | **UNCHANGED** | |
| `sdk/verify/tests/fixtures/sample_key.json` | **UNCHANGED** | |
| `sdk/verify/tests/fixtures/sample_bundle_with_actor_sigs.json` | **NEW** | built from `sample_bundle.json` with one top-level `actor_signature_sidecar` field; `bundle_hash` byte-identical to base; events byte-identical to base; first event signed by a freshly-generated test Ed25519 keypair |
| `sdk/verify/tests/fixtures/sample_actor_keypair.json` | **NEW** | test-only Ed25519 keypair persisted alongside the fixture; marked TEST-ONLY in its `note` field |

**Reproducibility note**: the new fixture was generated by a deterministic script that reads `sample_bundle.json`, signs the first event using `canonical_event_for_signing_v1`, and attaches the result as a single top-level field. The base fixture is preserved byte-for-byte; only an additional top-level field is added.

---

## 9. Tests added (20 new — full suite 76/76 PASS)

| Category | Tests |
|---|---|
| Legacy compatibility | `test_legacy_bundle_still_verifies_unchanged` · `test_legacy_bundle_event_chain_unchanged` · `test_legacy_bundle_hash_recomputes` |
| Hash preservation | `test_sidecar_bundle_hash_byte_identical_to_legacy` · `test_sidecar_does_not_mutate_events` · `test_sidecar_bundle_hash_recomputes_to_legacy_hash` |
| Core verifier unaffected | `test_sidecar_bundle_core_verification_unaffected` · `test_core_verifier_unaffected_by_tampered_sidecar` · `test_core_verifier_unaffected_by_sidecar_removal` |
| Strict happy path | `test_sidecar_strict_mode_happy_path` · `test_sidecar_strict_mode_collects_actor_ids` |
| Strict tamper cases | `test_strict_mode_altered_signature_fails` · `test_strict_mode_altered_actor_id_fails` · `test_strict_mode_altered_event_hash_key_fails` · `test_strict_mode_altered_public_key_fails` · `test_strict_mode_sidecar_hash_tamper_fails` · `test_strict_mode_unsupported_signature_alg_fails` · `test_strict_mode_unsupported_canonicalization_fails` |
| Missing-sidecar behavior | `test_missing_sidecar_non_fatal_in_default_mode` · `test_missing_sidecar_strict_mode_reports_absent` |

`pytest tests/` total: **76 passed in 0.37s** (56 pre-existing + 20 new).

### Special note on `test_strict_mode_altered_actor_id_fails`

The test docstring documents an honest verifier-design boundary: the sidecar entry's `actor_id` field is metadata; the cryptographic check binds `event.actor_id` + `key_id` via the canonical signed payload, not the sidecar metadata. If a malicious editor changes only the sidecar `actor_id` (without re-signing) and recomputes the sidecar hash, the signature still verifies — because the signed payload binds the event's actor_id, not the sidecar field. **Real audit fences compare actor_id ↔ key_id ↔ public_key against a `key_directory` snapshot**; that's 82Q-B scope. The 82Q-A test documents this boundary explicitly rather than papering over it.

---

## 10. Hashes unchanged confirmation

| Hash | Pre-sidecar | Post-sidecar | Identical? |
|---|---|---|---|
| `bundle_hash` (fixture) | `d00559fc5cc24adea6a58bcc...` | `d00559fc5cc24adea6a58bcc...` | **YES** |
| All event `hash` values (fixture) | unchanged | unchanged | **YES** |
| Live canonical handoff `bundle_hash` | `9a98a70e...c6` | n/a (live bundle unmodified) | n/a |
| Verifier `compute_bundle_hash()` projection | 5 whitelisted fields | unchanged | **YES** |
| Verifier `verify_event_chain` 7-field projection | unchanged | unchanged | **YES** |
| `_hash_record` runtime projection | unchanged | unchanged | **YES** |
| `compute_bundle_hash_v1` runtime contract | unchanged | unchanged | **YES** |
| `EXCLUDED_FROM_HASH` set | unchanged | unchanged | **YES** |

---

## 11. Files touched

| File | Repo | Change | Net LOC |
|---|---|---|---|
| `sdk/verify/src/aigentsy_verify/bundle.py` | aigentsy-protocol | Added `verify_actor_signature_sidecar()` + helpers `_canonical_signed_payload()` + `_compute_sidecar_hash()` + module-level `ACTOR_SIDECAR_CANONICAL_KEYS` tuple | +175 |
| `sdk/verify/tests/test_bundle_actor_sidecar.py` | aigentsy-protocol | NEW — 20 tests | NEW |
| `sdk/verify/tests/fixtures/sample_bundle_with_actor_sigs.json` | aigentsy-protocol | NEW fixture | NEW |
| `sdk/verify/tests/fixtures/sample_actor_keypair.json` | aigentsy-protocol | NEW test-only keypair (clearly labeled non-production) | NEW |
| `AIGENTSY_SPEC3_ACTOR_SIGNATURE_SIDECAR_82Q_A.md` | aigentsy-protocol | This report | NEW |

**No edits to any other file.**

---

## 12. Files intentionally NOT touched

| Surface | Reason |
|---|---|
| `sdk/verify/pyproject.toml` | NO version bump · no republish |
| `sdk/verify/src/aigentsy_verify/cli.py` | NO CLI flag change · prototype is verifier-source-only |
| `sdk/verify/src/aigentsy_verify/merkle.py` | NO change |
| `sdk/verify/tests/fixtures/sample_bundle.json` | preserved verbatim |
| `sdk/verify/tests/fixtures/sample_attestation.json` | preserved verbatim |
| `sdk/verify/tests/fixtures/sample_key.json` | preserved verbatim |
| `sdk/verify/tests/test_verify.py` · `test_cli.py` | NOT touched — existing 56 tests preserved |
| Runtime repo (`aigentsy-ame-runtime`) | NO change — runtime emission is deferred to 82Q-B |
| `aigentsy-protocol/sdk/mcp/*` | NO change — MCP behavior preserved |
| `aigentsy-protocol/sdk/aigentsy/*` | NO change — SDK source / CLI behavior preserved |
| `aigentsy-hero-final/*.html` | NO frontend / public copy change — public "spec 3 live" claim still forbidden |
| Runtime `_hash_record` (`protocol/event_store.py`) | trust spine — never touched |
| Runtime `compute_bundle_hash_v1` (`protocol/bundle_spec.py`) | trust spine — never touched |
| Runtime `canonical_event_for_signing` (`protocol/signing_schema.py`) | trust spine — never touched |
| Runtime `EXCLUDED_FROM_HASH` set | unchanged — whitelist projection already inherently excludes unknown top-level fields; the additive safety-net change is deferred to 82Q-B |
| `INTENT_VALUES` enum in runtime | NOT extended in 82Q-A — the new `evaluated_inference` intent is referenced as a string only in fixture/test data; runtime enum extension is 82Q-B scope |

---

## 13. No runtime emission

Runtime emission of the sidecar (i.e. `evaluate_inference()` accepting `signing_key` + `key_id` + `intent` triple, and `assemble_v1_bundle()` attaching the sidecar to exported bundles) is **explicitly deferred to Pass 82Q-B**.

The 82Q-A prototype proves:

- the sidecar shape is byte-compatible with existing infrastructure
- the verifier can validate it strictly when asked
- the verifier ignores it cleanly when not asked
- legacy bundles continue to verify exactly as before

Once 82Q-A is reviewed and accepted, 82Q-B can wire runtime emission with no remaining verifier-side uncertainty.

---

## 14. No MCP behavior change

`aigentsy_inference_evaluate` response envelope, MCP tool count (14), MCP server module — all preserved verbatim. The MCP path returns `export_path`; clients fetch the bundle themselves and can opt into strict sidecar validation at their own layer.

---

## 15. No frontend / public copy

| Surface | Status |
|---|---|
| `/aigentsystack` | UNCHANGED (deployed `4f4cad8`) |
| `/integrations` | UNCHANGED |
| `/verify.html` | UNCHANGED |
| `/vault.html?demo=1` · `/playground.html?mode=savings-trace` · `/quickstart.html` · `/builders` · `/enterprise-pilot` · `/` | UNCHANGED |
| Public "spec 3 live" claim | **still forbidden** — `spec_version` remains `2.0.0` |
| Public "per-actor signed inference live" claim | **still forbidden** |
| Trust-line distribution (`does not train on customer model content`) | preserved at exactly 3 approved locations: scaffold README + quickstart + enterprise-pilot |

---

## 16. No package publish · no version bump

| Package | Version | Action |
|---|---|---|
| `aigentsy-verify` | 1.5.0 (latest on PyPI) | **NO bump · NO republish** |
| `aigentsy-mcp` | 1.3.1 | **NO change** |
| `aigentsy` (runtime SDK) | 1.14.0 | **NO change** |
| Protocol SDK `aigentsy` | 1.6.2 | **NO change** |

The verifier prototype lives in source only. The new helper `verify_actor_signature_sidecar` is accessible to callers who install from source (e.g. `pip install -e .` against the local repo) but is NOT yet on PyPI. Tests run against the local source via `PYTHONPATH=src` for the same reason.

---

## 17. Deferred — Full runtime emission plan (82Q-B candidate scope)

When operator approves moving forward:

| File | Tier | Estimated LOC | Action |
|---|---|---|---|
| `aigentsy-ame-runtime/protocol/signing_schema.py` | additive | +2 | Add `evaluated_inference` to `INTENT_VALUES`; add `actor_signature_sidecar` to `EXCLUDED_FROM_HASH` (safety net even though whitelist projection makes this strictly unnecessary) |
| `aigentsy-ame-runtime/protocol/bundle_spec.py` | additive | +50 | Optional sidecar assembly in `assemble_v1_bundle()` only when a signed event exists |
| `aigentsy-ame-runtime/protocol/inference_acceptance.py` | additive | +60 | Optional `(signing_key, key_id, intent="evaluated_inference")` triple on `evaluate_inference()` |
| `aigentsy-ame-runtime/sdk/aigentsy/tests/test_inference_actor_sidecar.py` | NEW | +120 | Runtime tests |
| `aigentsy-protocol/sdk/verify/src/aigentsy_verify/cli.py` | additive | +30 | `--strict-actor-signatures` flag (default OFF) |
| `aigentsy-protocol/sdk/verify/pyproject.toml` | bump | +1 | 1.5.0 → 1.6.0 (separate publish decision) |

Estimated total for 82Q-B: ~260 LOC (well below the 600 LOC 82J estimate, because 82Q-A already proved the verifier prototype).

---

## 18. Recommended next pass

**Pass 82Q-B — Runtime Emission for Optional Actor Signature Sidecar**. Wire the verified prototype into the runtime `assemble_v1_bundle()` + optional `evaluate_inference()` signing triple. No MCP/SDK helper. No CLI behavior change beyond an opt-in `--strict-actor-signatures` flag. Verifier source already proven; runtime emission is the remaining additive step before any potential package republish.

---

*End of report.*
