# Architecture, Authority & Non-custody

> **This document consolidates evidence for diligence and does not define protocol or runtime behavior.** Canonical behavior lives in the runtime/protocol source and the specifications linked here ([`../gate_and_prove.md`](../gate_and_prove.md), [`../../protocol/MANDATE_SEMANTICS.md`](../../protocol/MANDATE_SEMANTICS.md), [`../../protocol/TRUST_PROFILE_V1.md`](../../protocol/TRUST_PROFILE_V1.md), [`../../sdk/MIRROR_PROVENANCE.md`](../../sdk/MIRROR_PROVENANCE.md)).

## Control-plane placement

AiGentsy is a **control plane**: it governs authorization and evidence for a consequence. The **consequence itself is performed by the enterprise-owned callback or adapter** in the enterprise's environment. What enters the gate is the declared action + evidence + policy context; what leaves is a decision, a portable proof trail, a signed outcome attestation, a later reconciliation, and an owner-scoped memory projection.

```
customer agent/workflow ──▶ [ AiGentsy control plane ] ──▶ customer callback / target system
   (outside)                gate · proof · verify ·           (outside; performs the consequence)
                            record · reconcile · memory
```

## Canonical lifecycle

mandate & actor context → proposed consequence → policy & Acceptance → exact authorization → ProofPack export → independent verification → enterprise-owned execution → performer-signed OutcomeReceipt → later reconciliation → Settlement Memory. One continuous `deal_id` links the trail. Payment is one reference consequence; the same pattern applies to deployment, API action, procurement, data publication, access change, and multi-agent handoff.

## Authority table

| Object / decision | Authority | Signer / attributor | Proves | Does NOT prove |
|---|---|---|---|---|
| `mandate_id` | caller-supplied policy context | caller-attributed | a referenced mandate/policy was cited | verified legal authority, employment, or corporate delegation |
| Actor key | pseudonymous signed identity | performer (enrolled Ed25519) | an enrolled actor controls a key | organization tenancy or legal identity |
| **Acceptance** | **decision authority** | policy evaluation | whether work may proceed to a consequence | that the work is externally correct |
| Exact authorization | consequence-identity binding | policy-evaluated (recomputed + matched) | the concrete consequence identity matches the authorized one (Tier-1 always; Tier-2 amount/recipient when enforced) | that the callback did exactly this in the external world |
| ProofPack | portable trust spine · canonical evidence artifact | platform-signed STH anchors the Merkle log; included actor and event signatures retain their own signer authority | the included records, signatures, and Merkle commitments verify for integrity, provenance, and internal consistency | real-world truth, independent external correspondence, or approval of the underlying work |
| Verifier result | independent verification | offline / browser / package verifier applying the published verification rules | the bundle's integrity, provenance, signature, and event-chain checks pass | that the consequence occurred externally or that the underlying claims are real-world true |
| OutcomeReceipt | performer attestation | enrolled performer using Ed25519 | an enrolled performer signed the recorded outcome attestation and linked it to the governed trail | independent external correspondence, external-system truth, or third-party confirmation of the claimed outcome |
| Reconciliation | attributed later observation | caller-attributed (`caller_attested`) | who recorded a later expected-versus-observed read-back and how it relates to the existing receipt | that the external world independently matches, unless a separate external-correspondence adapter supplies that evidence |
| Settlement Memory | read-only projection | derived from the event trail | the owner-scoped decision→outcome→reconciliation history | it is not a second source of truth or a custodial store |
| Consequence adapter | enterprise-owned execution | enterprise | the enterprise executed in its own environment | AiGentsy operated the target system |

## Exact-authorization profile

- **Tier-1** (acceptance-before-consequence) is **always enforced** on the canonical consequence path: a payout is denied with `settlement_requires_acceptance` unless a current accepted Acceptance exists.
- **Tier-2** (exact consequence-identity binding — amount/recipient/currency/instruction) is wired and enabled per deployment via `CONSEQUENCE_EXACT_ENFORCE=enforce`, which requires an exact match and **fails closed**. It is a **deployment enforcement profile**, configurable per contracted workflow. Enforcement coverage is workflow-specific: the currently deployed settlement endpoints require compatible deal/action-level authorization before persistence or dispatch, while exact payout-recipient, amount, share and term binding remains a recorded Tier-2/24E design item.

## Non-custody & data boundary

**AiGentsy governs the consequence without owning or operating the thing being governed—it holds the trail, not the thing.** AiGentsy retains protocol evidence, including mandate and actor references, policy inputs, Acceptance records, exact-authorization metadata, identifiers and hashes, signatures, event-chain records, ProofPacks, OutcomeReceipts, reconciliation observations, and Settlement Memory projections. It takes **no custody or operational control** of customer funds, credentials, private signing keys, compute, documents, customer artifacts, result payloads, execution environments, callbacks, target systems, accounts, or external settlement assets.

Private signing keys remain under the caller's control and are never transmitted to AiGentsy. The enterprise-owned callback runs only after the required Acceptance, authorization, and verification checks succeed. Its result payload is not part of the pre-execution signed ProofPack and is not retained by AiGentsy; later trail records may contain only the appropriate references, hashes, signed outcome attestations, and reconciliation observations. The enterprise owns the callback, its credentials, the target system, the external side effect, and the accuracy of the observations it later reports.

## Boundaries (how the product works — not deficiencies)

- Actor identity is pseudonymous signed identity, not verified employment or corporate delegation.
- Mandate attribution is caller-attributed policy context, not automatic legal delegation.
- OutcomeReceipt is a performer-signed attestation, not independent real-world truth.
- Reconciliation is a later attributed observation; **independent external-system correspondence is an OPTIONAL HIGH-ASSURANCE EXTENSION**, not a prerequisite of the shipped trail.
- Settlement Memory is a read-only projection over the event trail, not a second source of truth.
- Payment is one reference consequence adapter (provider-specific); model/agent providers are not the control authority.
- Operator-only multi-party **split** settlement (`/protocol/settle/multi`) exists as a reference tool: AiGentsy governs, authorizes, and records an N-way split settlement instruction (per-split events plus a single receipt) while an external provider or enterprise system performs the settlement legs. It is **not** a netting engine or an economic-finality primitive, and it is not the canonical customer consequence path.

These are authority, custody, and deployment boundaries — not product deficiencies.
