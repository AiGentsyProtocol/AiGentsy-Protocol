# Lineage / Offspring Graph — Specification v1

**Status:** v1 (ed25519 signed, offline-verifiable)
**Module:** `protocol.lineage_graph`
**Embedding path:** ProofPack `evidence.lineage_graph`

## 1. Purpose

Lineage Graph v1 models how descendant agents/artifacts emerge from
parents, what they inherit, what they mutate, and what rights,
constraints, and economic entitlements persist across generations.

Seven primitives now coexist in AiGentsy Stack.

## 2. Reused AiGentsy Logic

- `protocol/recursive_spawn.py`: parent-child spawning with inherited
  OCS, capped permissions, graduation, revocation.
- `protocol/proof_chain.py`: provenance ancestry with BFS queries and
  chain hashing.
- `revenue_flows.py`: multi-generation clone royalties (30%→10%→3%).
- `protocol/referral_graph.py`: 3-hop referral attribution chains.

This module wraps these into a portable, signed, inspectable lineage
artifact. It does NOT replace them.

## 3. Schema

LineageNode: lineage_id, subject_agent, parent_agent, parent_lineage_id,
ancestor_chain, descent_type, generation, inherited_traits[],
mutated_traits[], retained_constraints[], new_constraints[],
inherited_rights[], retained_obligations[], lineage_economic_links[],
source_refs, spawn_mandate_id, spawn_proof_chain_id, ed25519 signing.

## 4. Descent Types

clone, remix, derived_agent, delegated_spawn, fork, template_instantiation.

## 5. Inheritance Model

spawn_child() carries forward: constraints accumulate, obligations
persist, rights narrow (inherit parent's unless removed), economic
links cascade with incremented generation counter.

## 6. ProofPack Embedding

`proof.evidence.lineage_graph` — peer to all other primitives.
All seven coexist. proof_hash invariant.
