# Threat Model (public)

> **This document consolidates evidence for diligence and does not define protocol or runtime behavior.** Evidence IDs reference [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md).

Scope: the AiGentsy control plane and its trust boundaries. It excludes threats inside a customer-owned target system, which AiGentsy does not operate and cannot control.

## Assets

Mandate & authorization context · actor public-key identity · Acceptance decisions · exact-authorization parameters (consequence identity) · the append-only event trail · Merkle roots & signed tree heads · ProofPacks · OutcomeReceipts · reconciliation records · Settlement Memory · package & source provenance. Customer callback credentials and private signing keys are **customer-retained assets** outside AiGentsy custody.

## Trust boundaries

customer agent/workflow | AiGentsy runtime | customer callback/adapter | external target system | verifier | event store | package registry (PyPI) | public source mirror (GitHub) | optional external provider.

## Threat actors

unauthenticated caller · compromised actor key · malicious enrolled actor · compromised customer callback · malicious/unavailable provider · package-substitution attacker · cross-owner attacker · operator error · evidence tamperer.

## Threat → control matrix

| Threat | Implemented control | Evidence | Residual risk | Owner | Class |
|---|---|---|---|---|---|
| Actor spoofing | Ed25519 enrolled-key binding; verifier binds `event.actor_id` to enrolled key | KEY-1, OUTCOME-1 | key hygiene | AiGentsy + customer | shared |
| Mandate spoofing | mandate is caller-attributed context; **Acceptance** (not the mandate) is the decision authority | AUTH-1, ID-1 | policy design | customer | customer |
| Acceptance bypass | Tier-1 enforced (`settlement_requires_acceptance`); money-route gating test in CI | EXACT-1, OPS-1 | — | AiGentsy | product |
| Exact-parameter substitution | Tier-2 consequence-identity binding (`enforce`, fail-closed match) | EXACT-2 | enable per deployment | shared | deployment-specific |
| Replay | event dedup by `event_id`; idempotency store; strict prev-hash | EVT-1 | — | AiGentsy | product |
| Duplicate dispatch | idempotency guard on the consequence path | EVT-1, EXACT-1 | — | AiGentsy | product |
| Event tampering | append-only hash chain + RFC-6962 merkle inclusion/consistency + STH | MERKLE-1, EVT-1 | — | AiGentsy | product |
| ProofPack tampering | bundle-hash + event-chain + merkle-inclusion + STH checks; offline verifier fails on tamper | PROOF-1, VERIFY-1, OPS-1 | — | AiGentsy + verifier | product |
| Receipt forgery | performer Ed25519 signature over canonical bytes | OUTCOME-1, KEY-1 | performer key compromise | customer | shared |
| False reconciliation observation | reconciliation is attributed + does not overwrite the receipt; matched/mismatched/inconclusive/unavailable vocabulary | RECON-1 | needs external-correspondence adapter for external truth | customer | shared / optional extension |
| Cross-owner disclosure | owner-scoped deny-by-default from signed evidence | ISOLATION-1 | — | AiGentsy | product |
| Key compromise | revocation endpoint; non-custodial (key never leaves caller) | KEY-1, CUSTODY-1 | customer-owned | customer | customer |
| Package substitution | published artifact hashes + byte-exact public source mirror + parity | SUPPLY-1 | consumer pinning | customer | shared |
| Customer callback compromise | out of AiGentsy control (boundary); gate authorizes, enterprise executes | CUSTODY-1 | customer-owned | customer | customer |
| Provider failure | provider-neutral; payment is a reference adapter | REF-1 | customer/provider | customer | customer |
| Configuration downgrade | Tier-1 always on; Tier-2 mode is operator config; trust-claims CI blocks regression of default-off/auth invariants | EXACT-1, EXACT-2, OPS-1 | operator diligence | AiGentsy + customer | shared |

## Explicit non-goals

AiGentsy cannot control compromise inside the customer's target system, cannot prove independent real-world truth (integrity/provenance only), and does not assert exactly-once execution in external systems. Independent external correspondence, constrained-runtime/enclave/hardware-rooted execution attestation, and recursive proof aggregation are **optional high-assurance extensions**, not shipped controls.
