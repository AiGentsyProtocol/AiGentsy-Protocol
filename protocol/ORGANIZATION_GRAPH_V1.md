# Swarm / Organization Graph — Specification v1

**Status:** v1 (ed25519 signed, offline-verifiable)
**Module:** `protocol.organization_graph`
**Embedding path:** ProofPack `evidence.organization_graph`

## 1. Purpose

Organization Graph v1 models durable multi-agent organizations:
which agents belong, what roles they hold, what membership rules
apply, and how collective identity persists across many transactions.

Twelve primitives now coexist in AiGentsy Stack.

## 2. Reused AiGentsy Logic

- `csuite_base.py` / `csuite_orchestrator.py`: C-suite role structure.
- `ai_family_brain.py`: multi-model collective with specialization.
- `metabridge.py`: JV team assembly with role-based revenue splits.
- `protocol/recursive_spawn.py`: hierarchical spawning.
- `partner_mesh.py` / `partner_mesh_oem.py`: 4-tier partner membership.

## 3. Schema

MemberNode: member_id, agent_ref, membership_status, joined/left/suspended_at,
role/mandate/capability/trust/lineage_refs, source_refs.

RoleNode: role_id, role_label, role_scope, authority_bounds, obligations,
rights, assignment_rules.

OrganizationGraph: organization_id, organization_type, organization_status,
member_nodes[], role_nodes[], ed25519 signing.

Types: swarm, team, venture, realm, cluster, cell.
Member statuses: active, pending, suspended, exited.
Org statuses: forming, active, dormant, dissolved.

## 4. Evaluation

`evaluate_membership(graph, agent_ref, requested_role=...)` checks:
signature, org status, member exists + active, role assigned.

## 5. ProofPack Embedding

`proof.evidence.organization_graph` — all twelve primitives coexist.
