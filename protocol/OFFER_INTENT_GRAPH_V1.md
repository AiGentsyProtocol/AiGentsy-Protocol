# Offer / Intent Graph — Specification v1

**Status:** v1 (ed25519 signed, offline-verifiable)
**Module:** `protocol.offer_intent_graph`
**Embedding path:** ProofPack `evidence.offer_intent_graph`

## 1. Purpose

Offer/Intent Graph v1 models pre-commitment transaction intent: what
an agent offers, what it seeks, what constraints apply, and how
structural compatibility is evaluated before commitments form.

Eight primitives now coexist in AiGentsy Stack.

## 2. Reused AiGentsy Logic

- `intent_exchange.py`: publish/bid/award auction with intent schema.
- `protocol/sla_marketplace.py`: ServiceOffering registry.
- `dealgraph.py`: deal state machine (PROPOSED→COMPLETED).
- `routing/inventory_fit.py`: capability/skill matching + offer packs.

## 3. Schema

IntentNode: intent_id, intent_type, status, work_class[],
offered_capabilities[], requested_capabilities[],
required_counterparty_traits, required_mandate_scope[],
required_trust_thresholds, value_expectation,
coordination_preconditions[], expires_at, withdrawn_at,
matched_to, source_refs[].

Intent types: offer, request, open_need, partner_seek,
delegation_seek, resource_offer, resource_request.

Statuses: open, matched, withdrawn, expired, fulfilled, blocked.

## 4. Compatibility Evaluation

`evaluate_compatibility(offer_node, request_node, ...)` checks:
both open, work_class overlap, capabilities met, trust thresholds,
mandate scope compatibility, not expired/withdrawn.
Returns `CompatibilityResult(compatible, checks_passed, checks_failed)`.

## 5. ProofPack Embedding

`proof.evidence.offer_intent_graph` — peer to all other primitives.
All eight coexist. proof_hash invariant.
