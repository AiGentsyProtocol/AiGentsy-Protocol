# Pass 82Q-D — Strong Level 1 Actor-Key Binding (Protocol Verifier)

**Pass:** 82Q-D — Strong Level 1 actor-key binding · protocol verifier half
**Repo:** `aigentsy-protocol`
**Date:** 2026-06-19
**Status:** Code shipped; legacy Pass 82Q-A bundles unchanged in their
acceptance/rejection behavior. Pass 82Q-D adds an additive
`key_directory` binding check that fails-closed when present and is
informational when absent.

---

## What changed

`sdk/verify/src/aigentsy_verify/bundle.py` was extended with three
internal helpers and one branch inside
`verify_actor_signature_sidecar()`:

1. `_iso_le(a, b)` — lexicographic ISO-8601 comparison helper.
2. `_key_active_at(entry, at_ts)` — returns `True` iff the directory
   entry satisfies all of:
     * `status == "active"`
     * `issued_at <= at_ts`
     * `revoked_at is None OR at_ts < revoked_at`
3. `_lookup_key_in_directory(bundle, key_id)` — returns the
   `keys_by_key_id[key_id]` entry from a top-level `key_directory`
   block, or `None` when the directory or the key_id is absent.

The main signature loop now consults
`bundle.get("key_directory", {}).get("keys_by_key_id")`. When the
directory is present, every sidecar signature is checked against it:

* **Lookup miss** → `binding_errors.append("signature N on EVH...: key_id KID not in bundle.key_directory.keys_by_key_id")`
* **Actor mismatch** (directory says X, event says Y) → `binding_errors.append(...)`
* **Public-key mismatch** (sidecar entry vs. directory) → `binding_errors.append(...)`
* **Inactive / revoked / issued-after-signed_at** → `binding_errors.append(...)`

When a directory entry matches cleanly, its `public_key_base64` becomes
the **canonical** verification key for Ed25519 verification of that
signature — i.e. the sidecar-supplied public key is checked for
**equality** against the directory, and verification proceeds against
the directory key. This is the binding step that lifts the verification
guarantee from "valid signature against a self-supplied key" to "valid
signature against the key the runtime registry says this actor uses."

The verifier returns five new fields on
`verify_actor_signature_sidecar()`:

| Field | Meaning |
|-------|---------|
| `binding_present` | `True` iff `bundle.key_directory.keys_by_key_id` is present and non-empty |
| `binding_verified` | `True` iff `binding_present` and `binding_errors == []` |
| `binding_source` | `"bundle_key_directory"` when bound, else `""` |
| `binding_errors` | List of per-signature binding errors (empty when bound or absent) |
| `bindings_checked` | Number of signatures whose binding passed cleanly |

Step 6 (the verify-actor-signature-sidecar step) fail policy:
* `key_directory` absent → step is informational; `binding_present=False`,
  `binding_verified=False`, `binding_errors=[]`. Step does NOT fail
  solely because the directory is absent.
* `key_directory` present + `binding_errors != []` → step **fails**.

This is the Strong Level 1 semantic: a sidecar without a directory
verifies on its own self-supplied keys (Pass 82Q-A behavior preserved);
a sidecar **with** a directory must additionally bind to that
directory's keys, or it is rejected.

---

## Files modified

| File | Change |
|------|--------|
| `sdk/verify/src/aigentsy_verify/bundle.py` | +79 lines: 3 helpers + directory consultation branch inside `verify_actor_signature_sidecar()`; no-sidecar early return extended with binding fields |
| `sdk/verify/tests/fixtures/sample_bundle_with_sidecar_and_directory.json` | New fixture — byte-equal events + sidecar to `sample_bundle_with_actor_sigs.json`, adds top-level `key_directory` with one matching `key_id` |
| `sdk/verify/tests/test_bundle_actor_sidecar.py` | +11 new tests (`test_82qd_*`) covering: directory-absent / directory-present-matching / key-id-missing / actor-id-mismatch / pub-key-mismatch / revoked / signed-before-issued / signed-after-revoked / directory-pub-key-is-canonical / tampered-directory-caught / legacy-82qa-fixture-passes |
| `AIGENTSY_KEY_DIRECTORY_STRONG_LEVEL_1_82Q_D.md` | This report (new) |

---

## Tests

**`sdk/verify/tests/test_bundle_actor_sidecar.py` — 87 / 87 PASS**

Composition:
* 76 pre-existing Pass 82Q-A tests — unchanged, all still pass; legacy
  fixture `sample_bundle_with_actor_sigs.json` continues to verify with
  `present=True, passed=True, binding_present=False,
   binding_verified=False, binding_errors=[]`
* 11 new Pass 82Q-D tests — happy path + 10 binding-failure scenarios

The new fixture `sample_bundle_with_sidecar_and_directory.json` has
`bundle_hash` byte-identical to the legacy fixture's `bundle_hash`,
proving that adding `key_directory` does not alter the canonical bundle
hash (it is in `EXCLUDED_FROM_HASH`).

---

## Invariants preserved

* **`compute_bundle_hash_v1` whitelist unchanged.** Still projects
  `{spec_version, deal_id, proofs, events, merkle_inclusion}`.
  `key_directory` is excluded from hashing by both whitelist projection
  and the explicit `EXCLUDED_FROM_HASH` set in `protocol/signing_schema.py`.
* **No SDK version bump.** No package publish.
* **No new endpoint, no new signing key, no new MCP, no new SDK
  release.** The protocol-verifier extension is a pure read-side
  addition.
* **`actor_signature_sidecar` shape unchanged.** Pass 82Q-A's locked
  shape (sidecar_version `0.0.1`, signature_alg `Ed25519`,
  canonicalization `canonical_event_for_signing_v1`, signed-payload
  canonical keys `[event_id, event_type, deal_id, actor_id, timestamp,
  payload, prev_hash, key_id]`) is byte-equal.
* **No event mutation.** Verifier is read-only; reads
  `bundle["events"]`, never writes.

---

## Verifier semantic table

| Bundle state | `present` | `passed` | `binding_present` | `binding_verified` | Step 6 fails? |
|--------------|-----------|----------|-------------------|--------------------|---------------|
| No sidecar | False | False | False | False | No |
| Sidecar, no directory (legacy 82Q-A) | True | True | False | False | No |
| Sidecar + matching directory | True | True | True | True | No |
| Sidecar + directory, key_id not in directory | True | True | True | False | **Yes** |
| Sidecar + directory, actor mismatch | True | True | True | False | **Yes** |
| Sidecar + directory, pub_key mismatch | True | True | True | False | **Yes** |
| Sidecar + directory, key revoked | True | True | True | False | **Yes** |
| Sidecar + directory, key inactive at signed_at | True | True | True | False | **Yes** |
| Sidecar self-invalid (bad Ed25519 sig) | True | False | * | * | **Yes** |
| Sidecar self-invalid, also directory mismatch | True | False | True | False | **Yes** |

`passed` covers the cryptographic correctness of the sidecar itself
(sidecar_hash, per-signature Ed25519 verification, event_hash present
in chain). `binding_verified` covers the actor-key binding to the
registry snapshot. Step 6's overall result is `passed AND (not
binding_present OR binding_verified)`.

---

## Public claim boundary

The protocol verifier extension does **not** justify any new public
claim on its own. Public claim eligibility activates only when a real
bundle in the wild carries both a sidecar AND a `key_directory`
populated from the persistent runtime `actor_registry`, AND the
browser verifier reports `binding_verified=True`. That requires the
operator follow-up described in the runtime report. Until then, all
existing Pass 82Q-A / 82Q-C public copy remains accurate without
modification.

Allowed claim once a real bound bundle exists:
> "Sidecar verified in browser. Actor key binding verified against
> runtime actor registry snapshot."

Forbidden claims (unchanged from prior passes):
* actor identity verified
* authenticated actor
* provider/model-authenticated output
* KYC / legal identity verified
* guaranteed provenance
* certified actor
* all actors signed
* Spec 3 live
* per-actor signed inference live

---

## Sequence

This is the protocol-verifier half of Pass 82Q-D. The runtime emission
half (`protocol/proof_export.py` enrollment gate + `key_directory`
emission, 7 new runtime tests) ships in a separate commit on
`aigentsy-ame-runtime`. The browser verifier half ships in a separate
commit on `aigentsy-hero-final`.

All three commits are staged but not pushed; the operator decides
when to push and in what order.
