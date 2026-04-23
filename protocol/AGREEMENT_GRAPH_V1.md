# Agreement / Contract Graph — Specification v1

**Status:** v1 (ed25519 signed, offline-verifiable)
**Module:** `protocol.agreement_graph`
**Embedding path:** ProofPack `evidence.agreement_graph`

## 1. Purpose

Agreement Graph v1 models the explicit accepted terms between
counterparties: who agreed with whom, on what scope/SLA/value/rights,
and what downstream primitives are now authorized.

Eleven primitives now coexist in AiGentsy Stack.

## 2. Reused AiGentsy Logic

- `dealgraph.py`: deal lifecycle (PROPOSED → COMPLETED).
- `contracts/sow_generator.py`: SOW + milestones + acceptance criteria.
- `contracts/legal_terms.py`: structured legal disclosures.
- `protocol/executable_sla.py`: programmable SLA commitments.
- `protocol/graph_settlement.py`: staged escrow release.
- `protocol/acceptance_policy.py`: auto-accept rules.
- `protocol/dispute_arbitration.py`: structured dispute resolution.

## 3. Schema

AgreementNode: agreement_id, agreement_type, status,
resolved_intent_refs[], counterparty_refs[], scope, work_classes[],
sla_terms, proof/acceptance_requirements[], value_term_refs[],
rights_granted[], constraints_accepted[], revocation_conditions[],
amendment_refs[], expires_at, source_refs[].

Types: service_agreement, delegation_agreement, resource_access_agreement,
sla_agreement, matched_offer_agreement, framework_agreement.

Statuses: draft, offered, accepted, active, amended, expired, revoked, fulfilled.

## 4. Evaluation

`evaluate_agreement(graph, agreement_id, ...)` checks: signature,
node exists, status, expiry, counterparty, resolved intents, mandate scope.

## 5. ProofPack Embedding

`proof.evidence.agreement_graph` — all twelve primitives coexist.
