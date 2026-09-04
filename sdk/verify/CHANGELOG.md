# Changelog

## 1.6.2

### Security — `skipped` means unevaluated, never failed-but-ignored (ANCHORLESS-VERDICT-1)

1.6.1 added consequence-identity equality inside `cross_reference`: a bundle
asserting an exact consequence authorization must show the dispatched or
reconciled identity equal to an authorized one. That check was correct, but the
step's `skipped` flag was still derived from anchor availability ALONE
(`not (merkle_inclusion and sth)`), and the overall verdict tolerates any
skipped step. So a bundle with no Merkle inclusion and no STH reported
`cross_reference.passed = False` with `consequence_identity_mismatch` and still
returned `verified: true`.

Consequence equality is computed from the event bytes present in the bundle and
needs no anchor, so once it establishes a definitive failure the step HAS been
evaluated. `cross_skipped` is now cleared whenever the consequence binding is a
definitive mismatch, so every definitive mismatch is fatal whether anchors are
full, partial or absent. A valid actor signature does not launder it, and a
full bundle rehash does not erase it — it is an internal-consistency
requirement, not a hash comparison.

**Deliberately narrow.** Only `consequence_identity_mismatch` clears the flag.
`no_consequence_authorization_claimed`, `consequence_authorized_not_dispatched`
and `consequence_bound` leave `skipped` exactly as anchor availability set it.
Anchorless bundles are NOT globally rejected: a legitimate anchorless bundle
keeps its established result, and unavailable anchoring stays skipped under the
existing contract.

### Security — malformed anchor material fails closed (ANCHORLESS-VERDICT-1)

A bundle is untrusted input, but a hostile `merkle_inclusion` block escaped as
an uncaught `TypeError`, `ValueError` or `KeyError` instead of producing a
verdict: a proof node of the wrong type, a non-hex or wrong-length hash, a
non-integer leaf index or tree size, a `proof` that is not a list, or a proof
entry object with no `hash` key. Callers received no result at all — a
denial-of-verdict on attacker-chosen bytes — and the browser verifier hung with
its button disabled. Reproduced identically on 1.6.0 and 1.6.1, so this
predates the consequence work.

Closed by validating anchor material structurally BEFORE the existing
normalization and verification, which are left byte-for-byte unchanged at their
original indentation (the Stage-7 additive-only freeze on this file is
respected, not amended). `merkle.py` and the RFC6962 algorithm are UNCHANGED,
and a well-formed anchor is passed through as the same object, so valid proofs
take exactly the same path and produce exactly the same result.

The validator is rejection-preserving, not permissive coercion. A malformed
anchor is never repaired into something that might still verify: the whole
block is replaced by a single guaranteed-failing sentinel whose `tree_size` of
0 makes verification return false on its first guard, before any hex decoding,
recursion or root comparison. That closes the collision a naive sanitizer would
open — dropping a malformed proof to `[]` while keeping `tree_size` 1 and
`leaf_hash == merkle_root` would otherwise make a hostile bundle verify as a
valid single-leaf tree. `bool` is rejected as an index or size for the same
reason, since `True` would masquerade as 1.

Malformed material is not treated as merely missing — `skipped` stays false, so
it fails rather than being tolerated — while a genuinely ABSENT anchor still
skips as before. No attacker-controlled text is reflected into the result.

**Result shape unchanged:** the same five step keys, no sixth step, no new
bundle field, no spec-version change, and the existing status vocabulary is
reused. Historical bundles that claim no consequence authorization are
unaffected.

## 1.6.0

### Security — leaf-to-event binding (PROOF-BINDING-1)

`cross_reference` now requires the signed Merkle leaf to correspond to exactly
one canonical event present in the bundle, in addition to the existing
root-matches-STH check.

Previously each step passed individually on a bundle whose inclusion proof
belonged to a *different* event: they proved a leaf existed under a signed root,
never that the presented event produced it. An attacker who rewrote an event,
repaired the event chain and bundle hash, and kept the original proof/STH passed
all five steps. Borrowed proofs and full-chain rehashes are now rejected without
the log-signing key.

The leaf is recomputed from `{deal_id, event_type, event_id, event_hash,
timestamp}` using the log's canonical JSON + RFC6962 `0x00` leaf hash, so no
bundle field, schema version or exporter change is required.

**Result-shape note:** the published five step keys are UNCHANGED. `cross_reference`
gains an in-step `leaf_binding` diagnostic (`bound` / `anchor_unbound` /
`anchor_ambiguous` / `no_anchor_claimed`), the same pattern as
`merkle_inclusion["type"]`. `merkle_inclusion` keeps its purely mathematical
meaning — a borrowed proof still verifies mathematically and now fails
cross-reference.

**Verdict change (intended):** a bundle whose inclusion proof is valid but
unbound to its presented events now returns `verified: false`. This is the
security correction, not a schema break.

## Unreleased

### Added
- Optional strict swarm-verification profile: `verify_bundle_swarm_strict()` and the
  `--swarm-strict` CLI flag. Composed from the existing per-event actor-signature
  verifier; additionally requires complete, temporally-valid signature coverage of the
  bundle's designated swarm event set (the latest signed `swarm_policy` event inside
  `events`), applies a strict malformed-lifecycle rule (non-`active` key status with no
  `revoked_at` fails), accepts both flat and nested `key_directory` shapes, and
  cross-checks the runtime's hash-committed `swarm_enforcement` snapshot when present.
  It distinguishes bundle integrity from swarm-authentication coverage and never re-runs
  policy or claims real-world correctness.

### Notes
- The default profile is unchanged: 2.0.0 unsigned bundles keep verifying, `--strict`
  keeps its STH-only meaning, and historical signatures made before a later rotation or
  revocation remain valid under both profiles.

## 1.5.1 — 2026-08-17

### Changed
- Public packaging and metadata only. Verifier behavior is identical to 1.5.0.
- `__version__` now reports the package version. 1.5.0 shipped with `__version__ = "1.4.0"`, so
  `aigentsy-verify --version` under-reported.
- README license statement corrected to Apache-2.0, matching the manifest, the bundled LICENSE, and
  the published metadata. The license itself is unchanged; only the README was wrong.
- Removed the `Repository` project URL. It pointed at a repository that is not publicly accessible.
- Removed internal implementation-pass identifiers from comments, docstrings, and one assertion
  message. Comment edits preserve line counts, so compiled bytecode is unchanged.
- Renamed the actor-signature verifier test module to `tests/test_verifier_actor_signatures.py`, and
  removed a developer's absolute path from a test fixture reference.

### Notes
- No API, signature, dependency, entry point, or Python-version change.
- No behavioral change: `adapter.py` logic, `verify_bundle`, and all replay statuses are unchanged.

## 1.5.0 — 2026-06-12

### Added
- `adapter.py` module included in the published wheel + sdist. Exposes:
  - `verify_adapter_replay(bundle)` — 7-check adapter-backed replay
  - `recompute_contract_hash`, `recompute_input_schema_hash`
  - `validate_adapter_contract_schema`
  - `replay_policy_decision`
- Per-check status codes (`ok`, `legacy_no_adapter`, `schema_fail`, `contract_hash_mismatch`, `input_schema_hash_mismatch`, `normalized_inputs_not_in_allowed_policy_fields`, `validator_declaration_missing`, `validator_result_inconsistent`, `matched_rule_does_not_fire_against_evaluated_inputs`, `adapter_evaluation_shape_invalid`).

### Fixed
- 1.4.0 wheel + sdist were built before `adapter.py` was on disk; the published package therefore did not perform adapter-backed replay. **Fixed in 1.5.0:** the wheel now contains `adapter.py` and adapter-backed replay works from the installed wheel.

### Notes
- Classic 5-step bundle verification (`verify_bundle`) is unchanged and remains byte-identical to 1.4.0 behavior on the same bundle inputs.
- No new runtime dependency. No network dependency. Offline replay remains offline.
- ProofPack 3.0.0 `actor_signatures` step continues to be detected as in 1.4.0.

## 1.2.1 — 2026-05-02

### Added
- `--fetch-key` flag for opt-in public key fetching from AiGentsy runtime
- `verification_level` field in output (`"offline"` or `"full"`)
- `steps_run` and `steps_skipped` counts in verification result
- Clearer SKIPPED messages with reason and remediation hint

### Changed
- STH SKIPPED now shows: `SKIPPED (no public key — use --fetch-key or --public-key)`
- `--strict` failure message includes remediation guidance
- Output footer shows `level: offline (4/5 steps)` or `level: full (5/5 steps)`

### Notes
- Default behavior remains offline (no network calls)
- Use `--fetch-key` to enable Step 4 (STH signature verification)

## 1.2.0 — 2026-05-01

### Added
- CLI entrypoint: `aigentsy-verify bundle proofpack.json`
- `--json` flag for machine-readable output
- `--strict` flag (fails if STH signature verification is skipped)
- `--public-key` flag for local Ed25519 key file
- `__main__.py` for `python -m aigentsy_verify`
- Agent trace display when present in bundle

## 1.1.0 — 2026-04-17

### Added
- Policy layer display
- Anchor receipt verification

## 1.0.0 — 2026-03-27

### Initial release
- 5-step offline bundle verification
- Ed25519 STH signature verification
- RFC 6962 Merkle inclusion and consistency proofs
- Attestation verification
- Public key fetching
