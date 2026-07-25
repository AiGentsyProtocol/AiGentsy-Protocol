# Changelog

## 1.16.0 — 2026-07-24

Backward-compatible minor release adding a self-serve consequence-lifecycle SDK surface that composes existing runtime capabilities — no new authority. The signed OutcomeReceipt, reconciliation, and Settlement Memory producers are unchanged; the SDK simply exposes and joins them.

### Added

- **`AiGentsyClient.reconcile_outcome(...)`** — thin wrapper over the existing simple (X-API-Key, caller-attested) `POST /protocol/outcome-reconciliation` route, appending one `OUTCOME_RECONCILED` observation to a deal. Validates `reconciliation_status` against the existing controlled vocabulary before any request; no enrolled signing key required. A distinct, later read-back stage — not a substitute for the signed OutcomeReceipt.
- **`AiGentsyClient.get_settlement_memory(limit=None, cursor=None)`** — thin wrapper over the existing owner-scoped read-only `GET /protocol/settlement-memory` projection (decision → consequence → outcome → reconciliation, references and hashes only). Owner scope is server-derived from the API key; `limit`/`cursor` pagination mirrored; no local store.
- **Canonical non-payment lifecycle example** (`examples/canonical_consequence_lifecycle.py`, source distribution) — one joined `deal_id` spine: `gate_and_prove` → enterprise-owned callback → performer-signed `OUTCOME_RECORDED` (consequence-neutral; `amount=0.0` for this non-payment `deploy_release`) → `OUTCOME_RECONCILED` → Settlement Memory. Runs offline via a demo transport; both accepted and blocked branches are shown.
- **Signing prerequisite disclosure** — the README lifecycle section and the example document that the signed OutcomeReceipt stage uses the existing Ed25519 path and requires `cryptography` (`pip install aigentsy "cryptography>=41.0"`); the wrappers themselves require no signing key. The enterprise owns and retains its private signing key; AiGentsy never receives or retains it.
- **Lifecycle wrapper tests** (`tests/test_lifecycle_wrappers.py`, source distribution) — route/method/auth/serialization/validation for both wrappers, transport reuse (no second HTTP client), and the joined example (signed outcome + honest non-payment fields + continuous `deal_id` + inert blocked branch).

### Changed

- Synchronized the version authorities: distribution metadata, `aigentsy.__version__` (also reported by `aigentsy --version`), and the public version test now all read `1.16.0`.

### Unchanged

- No runtime or protocol authority change; no lifecycle/behavior change; Acceptance, ProofPack, verification, the `OUTCOME_RECORDED`/`OUTCOME_RECONCILED` producers, Settlement Memory projection, callback execution, and custody boundaries are all unchanged.
- No new custody, route, event, schema, store, signer, dispatcher, registry, or protocol object was introduced. No dependency graph change.

## 1.15.2 — 2026-07-23

Documentation and non-payment example patch release. Existing `gate_and_prove` functionality is unchanged from 1.15.1.

### Added

- **Runnable non-payment `gate_and_prove` example** (`examples/non_payout_gate_and_prove.py`, source distribution) — a deployment/release (`deploy_release`) consequence guarded by the existing primitive: an enterprise-owned callback executes only after the declared action is accepted and its ProofPack verifies. Runs offline with no credentials.
- **Expanded README** — a "Guard any enterprise consequence" section showing how to guard any enterprise-owned callback (deployment, release, API action, handoff, procurement, access change, delivery, publication). Payment remains one reference callback. Includes the trust boundary: AiGentsy verifies the declared action, evidence, decision, and proof trail; the enterprise remains responsible for ensuring the callback performs only the declared operation; AiGentsy does not verify real-world truth and is non-custodial.
- **Conformance coverage** for the allowed, blocked, held, and verification-failure branches.

### Unchanged

- No `gate_and_prove` API change and no runtime-authority behavior change.
- No new protocol authority, execution custody, dispatcher, registry, or consequence identity was introduced.

## 1.14.0 — 2026-06-14

Backward-compatible minor release adding the AccountMembership Admin CLI family that pairs with the Pass 79F Stage 1 runtime endpoints (`POST /admin/accounts/{account_id}/memberships`, `GET /admin/accounts/{account_id}/memberships`, `POST /admin/accounts/{account_id}/memberships/{membership_id}/status`) and the new role-aware Principal claims.

### Added

- **`aigentsy admin account membership` subcommand family** — three handlers wrapping the admin-protected AccountMembership endpoints. Each reads `OPS_ADMIN_KEY` from env only, never accepts the token as a CLI flag, never echoes it in stdout / stderr, never persists it.
  - `aigentsy admin account membership add` — POST `/admin/accounts/{account_id}/memberships`. Required: `--account-id`, `--agent-id`, `--role` ∈ {owner, admin, operator, auditor, viewer}. Optional: `--enterprise-id`, `--workspace-id`, `--status` ∈ {active, suspended, disabled} (default active), `--base-url`. Server denormalizes enterprise/workspace from the parent AccountRecord.
  - `aigentsy admin account membership list` — GET `/admin/accounts/{account_id}/memberships`. Optional `--status` filter.
  - `aigentsy admin account membership status` — POST `/admin/accounts/{account_id}/memberships/{membership_id}/status`. Status-only update; preserves all other fields server-side.
- All three handlers accept `--base-url` to override the default runtime URL.
- 30-test invariant suite at `sdk/aigentsy/tests/test_cli_admin_account_membership.py`. Includes four sentinel-token leakage guards covering admin-key-shaped, PyPI-token-shaped, npm-token-shaped, and `V77D3_`-shaped sentinel strings — none may appear in CLI stdout or stderr. Also asserts no subcommand exposes `--admin-token` and the `X-Admin-Token` header literal never appears in CLI output.
- Updated `aigentsy admin account` parent help to list the new `membership` sibling alongside `create | list | get | suspend | disable | activate`.
- README: new "AccountMembership Admin CLI" section with usage examples for all three subcommands, role + status enums, security warnings, and explicit claim boundaries.

### Role-aware Principal support (runtime side, Pass 79F Stage 1)

The SDK 1.14.0 client surfaces Principal role claims provided by the runtime (Stage 1 already live). The Principal now carries:

- `role` — highest-trust active role for the current account context
- `roles` — list of active memberships across all accounts
- `role_source` ∈ {membership, owner_implicit, none}

The role is resolved server-side from AccountMembership rows with backward-compatible fallback to implicit "owner" when an agent matches `AccountRecord.owner_agent_id`. No SDK code change is required to consume the role claim; it appears in the `principal` field of `/vault/records?scope=enterprise` responses.

### Vault auditor-read (runtime side, Pass 79F Stage 1)

`/vault/records?scope=enterprise&view=auditor` is live on the runtime. The SDK does not yet ship a dedicated client wrapper for this (operators craft the query string directly); a future release may add a `client.vault_records(scope="enterprise", view="auditor")` shortcut.

### Compatibility

- No breaking import changes.
- No removed CLI commands. All existing `init`, `stamp`, `verify`, `settle`, `status`, `demo`, `create-agent`, `adapter`, `admin owner-bound`, `admin account create | list | get | suspend | disable | activate` subcommands continue to work unchanged.
- No schema, verifier, protocol, or runtime endpoint changes BEYOND the three new admin endpoints (already live at runtime SHA `5017663e7ac83ec78fb839cea7b93b1e46739782`).
- No new runtime dependency. The `verify` and `langgraph` optional-deps groups are unchanged.
- The optional `[verify]` extra continues to resolve `aigentsy-verify>=1.0`. Users who install `aigentsy[verify]` will pick up `aigentsy-verify@1.5.0` (the latest), which provides 7-step adapter-backed replay.

### Migration

- Drop-in upgrade. `pip install --upgrade aigentsy` to `1.14.0`. To use the new `aigentsy admin account membership ...` subcommands, export `OPS_ADMIN_KEY` in your shell; the CLI never accepts the token as a flag.

### Claim boundaries

- The AccountMembership Admin CLI manages **platform-attested membership records** — not tenant isolation, not full workspace RBAC platform, not multi-user login, not SSO/SAML, not customer-managed enterprise keys, not self-serve enterprise onboarding, not public membership management, not cross-account / multi-enterprise read. Vault G1's agent-binding guard continues to gate every read of `/vault/records`. Suspending or disabling a membership immediately collapses the role claim for that account; role-aware access (`view=auditor` on enterprise scope) is read-only.

### Not in this release

- npm `aigentsy` membership-CLI parity (Python-only at 1.14.0).
- `aigentsy-verify` is unchanged at 1.5.0.

## 1.13.0 — 2026-06-14

Backward-compatible minor release adding the Account Registry Admin CLI family that pairs with the Pass 79A admin endpoint and the Pass 79C runtime endpoints (`GET /admin/accounts`, `GET /admin/accounts/{account_id}`, `POST /admin/accounts/{account_id}/status`).

### Added

- **`aigentsy admin account` subcommand family** — six handlers wrapping the admin-protected Account Registry endpoints. Each reads `OPS_ADMIN_KEY` from env only, never accepts the token as a CLI flag, never echoes it in stdout / stderr, never persists it.
  - `aigentsy admin account create` — POST `/admin/accounts`. Wraps the 79A upsert endpoint; validates `--account-type` ∈ {developer, enterprise, internal, demo} and `--status` ∈ {active, suspended, disabled} client-side.
  - `aigentsy admin account list` — GET `/admin/accounts`. Optional filters: `--account-id`, `--enterprise-id`, `--owner-agent-id`, `--status`. Filters AND-compose server-side.
  - `aigentsy admin account get` — GET `/admin/accounts/{account_id}`. 404 surfaced cleanly.
  - `aigentsy admin account suspend` — POST `/admin/accounts/{account_id}/status` with `{"status": "suspended"}`. Preserves all other fields server-side.
  - `aigentsy admin account disable` — same with `disabled`.
  - `aigentsy admin account activate` — same with `active`. Restores a previously suspended/disabled account.
- All six handlers accept `--base-url` to override the default runtime URL.
- 32-test invariant suite at `sdk/aigentsy/tests/test_cli_admin_account.py`. Includes four sentinel-token leakage guards covering admin-key-shaped, PyPI-token-shaped, npm-token-shaped, and `V77D3_`-shaped sentinel strings — none may appear in CLI stdout or stderr. Also asserts no subcommand exposes `--admin-token` as a flag.
- README: new "Account Registry CLI" section with usage examples for all six subcommands, security warnings, and explicit claim boundaries.

### Compatibility

- No breaking import changes.
- No removed CLI commands. All existing `init`, `stamp`, `verify`, `settle`, `status`, `demo`, `create-agent`, `adapter`, `admin owner-bound` subcommands continue to work unchanged.
- No schema, verifier, protocol, or runtime endpoint changes BEYOND the three new admin endpoints (which ship as a separate runtime commit prior to this SDK release).
- No new runtime dependency. The `verify` and `langgraph` optional-deps groups are unchanged.
- The optional `[verify]` extra continues to resolve `aigentsy-verify>=1.0`. Users who install `aigentsy[verify]` will pick up `aigentsy-verify@1.5.0` (the latest), which provides 7-step adapter-backed replay.

### Migration

- Drop-in upgrade. `pip install --upgrade aigentsy` to `1.13.0`. To use the new `aigentsy admin account ...` subcommands, export `OPS_ADMIN_KEY` in your shell; the CLI never accepts the token as a flag.

### Claim boundaries

- The Account Registry Admin CLI manages **platform-attested account records** — not tenant isolation, not RBAC, not auditor login, not multi-user enterprise workspace, not customer-managed enterprise keys, not self-serve enterprise onboarding. Vault G1's agent-binding guard continues to gate every read of `/vault/records`. Disabled / suspended accounts are excluded from the enterprise secondary index that powers `/vault/records?scope=enterprise`.

## 1.12.0 — 2026-06-14

Backward-compatible minor release adding the admin-protected Vault owner-binding CLI.

### Added

- **`aigentsy admin owner-bound`** subcommand: thin admin-protected wrapper around the production endpoint `POST /vault/owner-bound` (Pass 78G). Creates a platform-attested `VAULT_OWNER_BOUND` event from an admin operator's terminal. Reads `OPS_ADMIN_KEY` from env only — never accepts the token as a CLI flag, never echoes it in stdout / stderr, never persists it. Validates client-side mirror of the server's constraints (deal_id + agent_id required, scope_type ∈ {agent, account, workspace, enterprise}, non-agent scope requires one of enterprise_id/workspace_id/account_id/user_id, length caps, control-character rejection). Surfaces `binding_id`, `source_event_id`, `stored_binding_present`, `attested`, `binding_quality`, `issuer` on success. 18-test invariant suite includes two sentinel-token tests (success and 403 paths) that fail if the token ever appears in CLI output.
- README: new "Admin CLI" section with usage, env vars, security warnings, and claim boundaries.

### Compatibility

- No breaking import changes.
- No removed CLI commands.
- No schema, verifier, protocol, or runtime endpoint changes.
- All existing commands (`init`, `stamp`, `verify`, `settle`, `status`, `demo`, `create-agent`, `adapter`) work unchanged.

### Migration

- Drop-in upgrade. `pip install --upgrade aigentsy` to `1.12.0`. To use the new `aigentsy admin owner-bound`, export `OPS_ADMIN_KEY` in your shell; the CLI never accepts the token as a flag.

### Claim boundaries

- The admin CLI creates **platform-attested owner bindings** — not tenant isolation, not RBAC, not auditor login, not multi-user enterprise workspace, not customer-managed enterprise keys, not self-serve enterprise binding. Vault G1's agent-binding guard continues to gate every read of `/vault/records`.

## 1.11.0 — 2026-06-12

Backward-compatible minor release that catches the published Python SDK up with the source tree's additive CLI / developer-UX surface that accumulated after `1.10.0` (Pass 65, Pass 67, Pass 68, Pass 69A), and re-frames the README around the six live test-mode consequence-gate demos.

### Added

- **Consequence-gate README packaging.** New "Six live consequence-gate demos" section documenting the six live test-mode runtime endpoints:
  - Verified but Rejected
  - Payout Held
  - Deployment Held
  - Handoff Held
  - API Action Held
  - Procurement Held
- **AdapterContract developer UX (Pass 65).**
  - `aigentsy create-agent NAME --template settlement-native-mcp` scaffolds a settlement-native agent project.
  - New bundled templates: `acceptance_policy.example.json`, `adapter_contract.example.json`, expanded `README.md.template`, `lifecycle.md`, `test_settlement_lifecycle.py.template`.
- **AdapterContract lifecycle/versioning commands (Pass 67).**
  - `aigentsy adapter list` — list registered adapter contracts.
  - `aigentsy adapter pin` — pin a contract version.
  - `aigentsy adapter bump` — bump contract version.
  - `aigentsy adapter diff` — diff two contract versions.
- **Signed AdapterContract publication (Pass 68).**
  - `aigentsy adapter attest` — sign an entry for the publication manifest.
  - `aigentsy adapter manifest verify` — verify a signed manifest offline (reuses `aigentsy_log_signer_v1`).
- **Lifecycle warning surfacing (Pass 69A).** `aigentsy adapter lint` now emits lifecycle warnings for revoked / superseded contract use in new artifacts.

### Changed

- README now frames AiGentsy as **the acceptance gate between autonomous work and real-world consequence**.
- Related-Packages guidance now points to **`aigentsy-verify==1.5.0`** for adapter-backed offline replay (1.4.0 wheel was missing `adapter.py`; fixed in 1.5.0).
- `__version__` constant in `aigentsy/__init__.py` bumped to `1.11.0`.

### Compatibility

- No breaking import changes. Every public symbol exposed by `aigentsy` and `aigentsy.client` in 1.10.0 remains importable and callable with byte-identical signatures.
- No removed CLI commands. `init`, `stamp`, `verify`, `settle`, `status`, `demo`, `create-agent` continue to work unchanged. The new `adapter` subcommand family is purely additive.
- No schema, verifier, protocol, or runtime endpoint changes.
- No new runtime dependency. The `verify` and `langgraph` optional-deps groups are unchanged.
- The optional `[verify]` extra continues to resolve `aigentsy-verify>=1.0`. Users who install `aigentsy[verify]` will pick up `aigentsy-verify@1.5.0` (the latest), which adds 7-step adapter-backed replay.

### Migration

- No migration required for users on `1.10.0`. Running `pip install --upgrade aigentsy` to `1.11.0` is a drop-in update; existing scripts that call the documented CLI commands or import `AiGentsyClient` work without changes.
- To exercise the new `aigentsy adapter ...` subcommands, see the new "AdapterContract developer CLI" section in the README.

## 1.10.0 — 2026-06-02 (previously published)

- Stage 7-C `record_signed_outcome` helpers.

## 1.9.0 — 2026-05-30 (previously published)

- Stage 7-A signed-event ingress helpers.
