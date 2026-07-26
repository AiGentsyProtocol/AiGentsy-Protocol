# Evidence Index

> **This document consolidates evidence for diligence and does not define protocol or runtime behavior.**

Each row maps a claim to its source. Public URLs are given where the material is openly published; private-source evidence is named by repository, path, and commit (no clone URLs). `RT` = runtime repository (private) `aigentsy-ame-runtime` @ `c05759b5`; `PUB` = public protocol repository `github.com/AiGentsyProtocol/AiGentsy-Protocol` @ `4a0d54a`; live = `https://aigentsy-ame-runtime.onrender.com`. Freshness checkpoint: 2026-07 / runtime `c05759b5`.

| ID | Domain | Claim | Repo | Path | Commit / version | Public URL | Class | Owner | Customer relevance | Cust. verify |
|---|---|---|---|---|---|---|---|---|---|---|
| ARC-1 | Architecture | Canonical Consequence-Layer lifecycle | PUB | `docs/gate_and_prove.md` | 4a0d54a | github blob | PUBLICLY DOCUMENTED | AiGentsy | high | n |
| ARC-2 | Architecture | Live runtime build identity | live | `/build` | c05759b5 | live GET | LIVE | AiGentsy | high | y |
| ARC-3 | Architecture | OpenAPI lifecycle discoverability (11 canonical tags) | live | `/openapi.json`, `/docs` | c05759b5 | live GET | LIVE | AiGentsy | high | y |
| AUTH-1 | Authority | Acceptance is decision authority | RT | `protocol/inference_acceptance_router.py`; `AIGENTSY_ACCEPTANCE_RUNTIME_82G.md` | c05759b5 | n/a — source | SOURCE-PRESENT + LIVE | AiGentsy | high | shared |
| EXACT-1 | Exact-auth | Tier-1 enforced (no consequence without accepted acceptance) | RT | `protocol/payout_router.py` (`settlement_requires_acceptance`) | c05759b5 | n/a — source | LIVE + TEST-PROVEN | AiGentsy | high | shared |
| EXACT-2 | Exact-auth | Tier-2 exact identity binding (`CONSEQUENCE_EXACT_ENFORCE=enforce`, fail-closed match) | RT | `protocol/acceptance_gate.py` (`consequence_binding_mode`, `authorize_exact_consequence`) | c05759b5 | n/a — source | SOURCE-PRESENT + CUSTOMER-CONFIGURED | shared | high | shared |
| ID-1 | Identity | mandate semantics + authority boundary (caller-attributed) | PUB | `protocol/MANDATE_SEMANTICS.md`, `protocol/MANDATE_GRAPH_V1.md` | 4a0d54a | github blob | PUBLICLY DOCUMENTED | AiGentsy | high | n |
| KEY-1 | Keys | actor key enrollment / revocation (fail-closed, dual-auth, non-custodial) | RT / PUB | `protocol/actor_api.py`; `AIGENTSY_KEY_DIRECTORY_STRONG_LEVEL_1_82Q_D.md`, `AIGENTSY_SPEC3_ACTOR_SIGNATURE_SIDECAR_82Q_A.md` | c05759b5 / 4a0d54a | github blob (spec) | LIVE + PUBLICLY DOCUMENTED | AiGentsy | high | shared |
| MERKLE-1 | Integrity | RFC-6962 merkle log (inclusion, consistency, signed tree heads) | RT | `protocol/merkle_log.py`; `tests/conformance/test_merkle_log.py` | c05759b5 | n/a — source | LIVE + TEST-PROVEN | AiGentsy | high | y |
| EVT-1 | Integrity | append-only hash-chained event store; strict prev-hash | RT | `protocol/event_store.py` | c05759b5 | n/a — source | LIVE | AiGentsy | high | shared |
| PROOF-1 | Proof | ProofPack export | RT / PUB | `protocol/proof_export.py`; `PROOFPACK_REUSE.md` | c05759b5 / 4a0d54a | github blob (spec) | LIVE + PUBLICLY DOCUMENTED | AiGentsy | high | y |
| VERIFY-1 | Verification | offline verifier (independent, no hosted-service trust) | PUB / PyPI | `sdk/verify/README.md`; `aigentsy-verify` | 4a0d54a / 1.5.0 | pypi.org/project/aigentsy-verify | PACKAGE-PUBLISHED | shared | high | y |
| VERIFY-2 | Verification | browser verifier | frontend | `verify.html` | live | https://www.aigentsy.com/verify | LIVE | AiGentsy | high | y |
| OUTCOME-1 | Outcome | performer-signed OUTCOME_RECORDED (OutcomeReceipt) | RT / PyPI | `protocol/event_ingress*`; SDK `record_signed_outcome` | c05759b5 / 1.16.0 | pypi.org/project/aigentsy/1.16.0 | LIVE + PACKAGE-PUBLISHED | shared | high | shared |
| RECON-1 | Reconciliation | OUTCOME_RECONCILED (attributed, `caller_attested`, non-overwriting) | RT / PyPI | `protocol/outcome_reconciliation_api.py`; SDK `reconcile_outcome` | c05759b5 / 1.16.0 | pypi.org/project/aigentsy/1.16.0 | LIVE + PACKAGE-PUBLISHED | shared | high | shared |
| MEMORY-1 | Memory | Settlement Memory (owner-scoped, read-only projection) | RT / PyPI | `protocol/settlement_memory.py`; SDK `get_settlement_memory` | c05759b5 / 1.16.0 | pypi.org/project/aigentsy/1.16.0 | LIVE + PACKAGE-PUBLISHED | AiGentsy | high | y |
| CUSTODY-1 | Non-custody | no custody of funds/systems/creds/keys/artifacts | RT | `sdk/aigentsy/gate.py` (enterprise callback); `protocol/settlement_memory.py` | c05759b5 | n/a — source | LIVE | AiGentsy | high | shared |
| AUTHN-1 | Auth | X-API-Key + OPS_ADMIN_KEY (constant-time, fail-closed) + webhook HMAC | RT | `route_guards.py`; `tests/test_route_guards.py` | c05759b5 | n/a — source | LIVE + TEST-PROVEN | AiGentsy | high | shared |
| ISOLATION-1 | Isolation | owner-scoped deny-by-default (pseudonymous, not org tenancy) | RT | `protocol/settlement_memory.py` (`_caller_owns`) | c05759b5 | n/a — source | LIVE | AiGentsy | high | shared |
| STORAGE-1 | Storage | DATA_ROOT durable stores; replay-safe; self-host guide | RT | `storage_root.py`; `docs/self_host.md` | c05759b5 | n/a — controlled evidence | SOURCE-PRESENT + PUBLICLY DOCUMENTED | shared | high | shared |
| OPS-1 | Ops | trust-claims CI gate (payout-auth, default-off, STH, merkle/verifier, bundle-hash) | RT | `.gitlab-ci.yml`; `scripts/ci_trust_claims.sh` | c05759b5 | n/a — source | TEST-PROVEN | AiGentsy | high | shared |
| SUPPLY-1 | Supply chain | package/source parity + artifact hashes | PUB / PyPI | `sdk/MIRROR_PROVENANCE.md` | 4a0d54a / 1.16.0 | github blob | PACKAGE-PUBLISHED + PUBLICLY DOCUMENTED | AiGentsy | high | y |
| DEMO-1 | Boundaries | Vault/Playground demo fixtures labeled non-production | frontend | `vault.html`, `playground.html` | live | https://www.aigentsy.com/vault.html?demo=1 | DEMO-FIXTURE | AiGentsy | medium | y |
| BENCH-1 | Boundaries | HoverStack savings measured-benchmark (not production) | PUB / frontend | `hoverstack/GOVERNED_ECONOMIC_PROOF_V1.md`; deck badges | 4a0d54a | github blob | BENCHMARK | AiGentsy | medium | y |
| RECALL-1 | Boundaries | Recall / reuse governance | RT | `hoverstack/decision_envelope.py`; `protocol/inference_acceptance_router.py` (reuse boundaries) | c05759b5 | n/a — source | DEFAULT-OFF / BENCHMARK / SOURCE-PRESENT | AiGentsy | low | shared |
| REF-1 | Reference | payout consequence adapter (reference, provider-specific) | RT | `protocol/payout_router.py` | c05759b5 | n/a — source | REFERENCE | shared | medium | shared |
| MSET-1 | Reference | `/protocol/settle/multi` operator-only split settlement (not netting/finality) | RT | `protocol/multiparty_settlement.py` (`admin_token_dependency`) | c05759b5 | n/a — source | REFERENCE + OPTIONAL EXTENSION | AiGentsy (operator) | low | shared |

All evidence IDs are unique. `n/a — source` marks private-runtime evidence available under diligence; `n/a — controlled evidence` marks material distributed during a buyer engagement. No private clone URLs or local paths are published.
