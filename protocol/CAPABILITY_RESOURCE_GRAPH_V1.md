# Capability / Resource Graph — Specification v1

**Status:** v1 (ed25519 signed, offline-verifiable)
**Module:** `protocol.capability_resource_graph`
**Embedding path:** ProofPack `evidence.capability_resource_graph`

## 1. Purpose

Capability/Resource Graph v1 models what an agent or swarm can
actually execute with: capabilities, tools, inventories, budgets,
rails, and operational capacity under current constraints.

Ten primitives now coexist in AiGentsy Stack.

## 2. Reused AiGentsy Logic

- `routing/inventory_fit.py`: OfferPack + has_capacity() + skill matching.
- `agent_registry.py`: Capability enums, verification gates, indexed discovery.
- `agent_spending.py`: Daily budget enforcement + check_spending_capacity().
- `protocol/provider_capabilities.py`: Rail/provider selection by capabilities.
- `allocation/r3_allocator.py`: Runway-aware budget allocation.
- `protocol/credential_marketplace.py`: Proof-backed credential index.

## 3. Schema

ResourceNode: resource_id, resource_type, status, capability_label,
availability_state, capacity_total/available, budget_available,
inventory_quantity, required_authority_scope[], required_trust_threshold,
usable_for_work_classes[], blocked_by[], expires_at, source_refs[].

Types: capability, tool_access, inventory, budget, rail_access,
license_unlock, resource_pool, runtime_capacity.

Statuses: available, limited, exhausted, blocked, expired, revoked.

## 4. Evaluation

`evaluate_availability(graph, resource_id, ...)` checks 10 conditions:
signature, node exists, status, expiry, capacity, budget, work_class,
trust threshold, authority scope, blocked-by.

## 5. ProofPack Embedding

`proof.evidence.capability_resource_graph` — all ten primitives coexist.
