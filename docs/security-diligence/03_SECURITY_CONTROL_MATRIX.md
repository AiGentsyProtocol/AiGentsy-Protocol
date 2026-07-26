# Security Control Matrix

> **This document consolidates evidence for diligence and does not define protocol or runtime behavior.** Evidence IDs reference [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md). Classifications use the legend in [`00_EXECUTIVE_README.md`](00_EXECUTIVE_README.md).

| Ctl | Domain | Objective | Current control | Impl. evidence | Test evidence | Class | Operating owner | Deployment input | Residual boundary | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| C-01 | Authentication | authenticate callers | X-API-Key (agent), OPS_ADMIN_KEY (operator, constant-time), webhook HMAC; fail-closed | AUTHN-1 | `tests/test_route_guards.py` | LIVE + TEST-PROVEN | AiGentsy | key issuance | customer key hygiene | shipped |
| C-02 | Owner scoping | prevent cross-owner disclosure | deny-by-default `_caller_owns` from signed evidence | ISOLATION-1 | `test_settlement_memory_projection.py` | LIVE + TEST-PROVEN | AiGentsy | — | — | shipped |
| C-03 | Actor enrollment | non-custodial signed identity | `/actor/enroll-key` fail-closed; agent self-enroll matches actor_id | KEY-1 | `test_actor_api_auth_binding.py` | LIVE + TEST-PROVEN | shared | key generation | customer key custody | shipped |
| C-04 | Actor revocation | revoke keys | `/actor/{key_id}/revoke` dual-auth (owner or admin) | KEY-1 | — | LIVE + SOURCE-PRESENT | shared | — | customer-owned | shipped |
| C-05 | Signature verification | bind records to keys | verifier binds `event.actor_id` to enrolled key; Ed25519 | KEY-1, OUTCOME-1 | conformance verifier tests | LIVE + TEST-PROVEN | AiGentsy | — | — | shipped |
| C-06 | Mandate attribution | policy context | caller-attributed `mandate_id`; not verified authority | ID-1 | mandate tests | PUBLICLY DOCUMENTED + SOURCE-PRESENT | customer | policy | not legal delegation | shipped (as documented) |
| C-07 | Acceptance enforcement | gate before consequence | Tier-1 `authorize_consequence_dispatch`; deny `settlement_requires_acceptance` | EXACT-1 | `tests/test_money_route_gating.py`, `test_canonical_settlement_gating.py` | LIVE + TEST-PROVEN | AiGentsy | — | — | shipped |
| C-08 | Exact authorization | bind concrete consequence identity | Tier-2 `authorize_exact_consequence`; `enforce` = fail-closed match | EXACT-2 | consequence-binding tests | SOURCE-PRESENT + CUSTOMER-CONFIGURED | shared | `CONSEQUENCE_EXACT_ENFORCE` | enable per workflow | shipped, config-gated |
| C-09 | Replay / idempotency | at-most-once | event dedup + idempotency store | EVT-1 | event-store tests | LIVE | AiGentsy | — | — | shipped |
| C-10 | Duplicate consequence | prevent double dispatch | idempotency on consequence path | EVT-1 | gating tests | LIVE | AiGentsy | — | — | shipped |
| C-11 | Event-chain integrity | tamper-evident trail | append-only SHA-256 hash chain + strict prev-hash | EVT-1 | `test_hardening.py` | LIVE + TEST-PROVEN | AiGentsy | — | — | shipped |
| C-12 | Merkle inclusion | prove membership | RFC-6962 inclusion proofs | MERKLE-1 | `test_merkle_log.py` | LIVE + TEST-PROVEN | AiGentsy | — | — | shipped |
| C-13 | Merkle consistency | prove append-only | RFC-6962 consistency proofs | MERKLE-1 | `test_merkle_log.py` | LIVE + TEST-PROVEN | AiGentsy | — | — | shipped |
| C-14 | Signed tree heads | anchor log state | Ed25519 STH; full-history signature invariant (CI) | MERKLE-1, OPS-1 | trust-claims CI | LIVE + TEST-PROVEN | AiGentsy | — | — | shipped |
| C-15 | ProofPack export | portable evidence | `proof_export` bundle | PROOF-1 | conformance | LIVE | AiGentsy | — | — | shipped |
| C-16 | Offline verification | verify without hosted trust | `aigentsy-verify` CLI/package | VERIFY-1 | package tests | PACKAGE-PUBLISHED | shared | — | — | shipped |
| C-17 | Browser verification | in-browser verify | verify.html (vendored Ed25519) | VERIFY-2 | — | LIVE | AiGentsy | — | — | shipped |
| C-18 | Tamper detection | detect modification | bundle-hash + chain + inclusion + STH fail on tamper | PROOF-1, VERIFY-1 | trust-claims CI | LIVE + TEST-PROVEN | verifier | — | — | shipped |
| C-19 | OutcomeReceipt signing | performer attestation | performer-signed OUTCOME_RECORDED | OUTCOME-1 | signing tests | LIVE + PACKAGE-PUBLISHED | customer (performer) | key | attestation ≠ external truth | shipped |
| C-20 | Reconciliation separation | non-overwriting observation | attributed OUTCOME_RECONCILED; does not rewrite receipt | RECON-1 | reconciliation producer tests | LIVE + PACKAGE-PUBLISHED | customer | — | external correspondence = optional extension | shipped |
| C-21 | Settlement Memory | read-only projection | owner-scoped projection over the event trail | MEMORY-1 | projection tests | LIVE + TEST-PROVEN | AiGentsy | — | not a second source of truth | shipped |
| C-22 | Non-custody | govern without owning/operating the governed thing | retains protocol evidence (references, records, commitments, metadata); no custody or operational control of funds/keys/systems/artifacts/results; private keys remain caller-controlled | CUSTODY-1 | — | LIVE | AiGentsy | — | holds the trail, not the thing | shipped |
| C-23 | Secret scrubbing | never log secrets | admin audit scrubs token/key values | OPS-1 | route-telemetry/audit tests | LIVE + TEST-PROVEN | AiGentsy | — | — | shipped |
| C-24 | Health / build identity | verify deployed revision | `/health`, `/build` (git_commit) | ARC-2 | `test_runtime_build_endpoint.py` | LIVE | AiGentsy | — | — | shipped |
| C-25 | Package provenance | source/package parity | `MIRROR_PROVENANCE.md`; published artifact hashes | SUPPLY-1 | — | PACKAGE-PUBLISHED + PUBLICLY DOCUMENTED | AiGentsy | — | consumer pinning | shipped |
| C-26 | Dependency / source parity | reproducible source | byte-exact 31-file mirror; digest `5bdb5ee4…` | SUPPLY-1 | mirror hash check | PACKAGE-PUBLISHED | AiGentsy | — | — | shipped |
| C-27 | Benchmark / demo labeling | honest claim boundaries | measured/reference/benchmark/demo badges; fixtures labeled non-production | BENCH-1, DEMO-1 | — | BENCHMARK / DEMO-FIXTURE | AiGentsy | — | — | shipped (labeling) |
| C-28 | Provider neutrality | avoid provider lock | payment = reference adapter; model provider-neutral | REF-1 | — | REFERENCE | shared | adapter choice | — | shipped |
| C-29 | Customer-owned callback boundary | enterprise owns execution | callback runs post-verification in enterprise env | CUSTODY-1 | — | LIVE | customer | callback | AiGentsy cannot control target-system compromise | shipped (boundary) |

## Not implemented as controls (optional extensions / absent)

Independent external-system correspondence, constrained-runtime/enclave/hardware-rooted execution attestation, recursive cryptographic proof aggregation, third-party verifier markets, slashable reputation, staking/bonding, multilateral netting — classified **OPTIONAL EXTENSION** or **ABSENT**; none is represented above as an implemented control. No security certification (SOC 2 / ISO 27001 / PCI DSS / HIPAA / FedRAMP / GDPR) is claimed — procurement-dependent, not currently claimed.
