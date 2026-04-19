# Consequence / State-Change Graph — Specification v1

**Status:** v1 (ed25519 signed, offline-verifiable)
**Module:** `protocol.consequence_graph`
**Embedding path:** ProofPack `evidence.consequence_graph`

## 1. Purpose

Consequence Graph v1 models what downstream state changes are
authorized, what conditions unlock them, who may trigger them, and
how consequence movement is represented after proof and acceptance.

Nine primitives now coexist in AiGentsy Stack.

## 2. Reused AiGentsy Logic

- `protocol/acceptance_gate.py`: gated state changes, downstream_action.
- `protocol/event_store.py`: hash-chained event ledger, stage transitions.
- `protocol/event_bus.py`: pub/sub + webhook dispatch.
- `protocol/graph_settlement.py`: per-stage escrow release.
- `routes/proof_verifier.py`: GO button (scope lock → payment → event).
- `protocol/autonomous_commerce.py`: zero-touch lifecycle consequence.
- Mandate.consequence_rights + CommitmentNode.unlocks_consequences.

## 3. Schema

ConsequenceNode: consequence_id, consequence_type, status,
triggering_conditions[], required_proof_refs[], required_acceptance_state,
required_value_state, required_mandate_scope[], required_coordination_state,
allowed_triggering_agent, blocked_by[], unlocks_next[],
reversion_target, escalation_target, source_refs[].

Types: settlement_request, release, access_grant, state_change,
downstream_task_start, escalation, hold, reversion.

Statuses: pending, eligible, triggered, blocked, held, escalated,
reverted, completed.

## 4. Evaluation

`evaluate_consequence(graph, consequence_id, ...)` checks 9 conditions:
signature, node exists, status, triggering agent, proof refs,
acceptance, value state, coordination state, blocked-by deps.

## 5. ProofPack Embedding

`proof.evidence.consequence_graph` — all nine primitives coexist.
